# Deploying Sangam on AWS (one EC2 instance)

A self-hosted alternative to the Vercel deploy in `CLAUDE.md`, "Deployment". A GitHub Actions workflow builds both
images, pushes them to GHCR, and restarts them on one EC2 instance over SSH. Postgres, Storage and sign-in stay on
Supabase; Caddy on the instance serves HTTPS with Let's Encrypt certificates. Nothing deploys on a push: the workflow
is run by hand, like the Vercel one.

```
browser ──https──▶ Cloudflare DNS (grey cloud) ──▶ EC2 Elastic IP
                                                     caddy :443 ─┬─ app.<domain> ──▶ frontend :3000 ─┐
                                                                 └─ api.<domain> ──▶ backend  :8000 ◀┘
                                                                                       │
                                     Supabase (Postgres · Storage · Auth) ◀────────────┘
GitHub Actions ── build ──▶ ghcr.io/…/sangam-backend, sangam-frontend ── ssh ──▶ EC2: docker compose pull && up
```

| File | Role |
|---|---|
| `.github/workflows/deploy-aws.yml` | Builds, pushes, copies the bundle, migrates, restarts, waits for `/health` |
| `deploy/aws/docker-compose.prod.yml` | The three services on the instance |
| `deploy/aws/Caddyfile` | Two hosts, read from `APP_DOMAIN` / `API_DOMAIN` |
| `frontend/Dockerfile` | Production Next.js build, standalone (~260 MB); `NEXT_OUTPUT=standalone` is set only here, so Vercel and local are unchanged |

No domain, host or key is written in the repo. They live in the instance's `.env` and in GitHub **secrets**: the repo
is public, so its Actions logs are too, and Actions variables are printed there in clear.

Throughout, replace:

| Placeholder | Example | What it is |
|---|---|---|
| `<domain>` | `example.org` | The domain on Cloudflare |
| `app.<domain>` | `app.example.org` | Where people open Sangam |
| `api.<domain>` | `api.example.org` | The backend, called by the browser |
| `<ref>` | `abcdefghijklmnop` | Your Supabase project ref (in its URL) |
| `<elastic-ip>` | `13.233.x.x` | The instance's fixed IP |

Do the steps in order: DNS must point at the instance before the first deploy, or Caddy cannot get certificates.

---

## Step 0. Before you start

- [ ] Admin on the AWS account, the Cloudflare zone for `<domain>`, the Supabase project, the Google Cloud project that
      owns the OAuth client, and the GitHub repo.
- [ ] This branch merged to `master`. GitHub lists a `workflow_dispatch` workflow only once it is on the default branch.
- [ ] The Supabase database already migrated and seeded (it is, if Vercel serves it today). The workflow migrates;
      it never seeds.
- [ ] Decide: **same Supabase project as Vercel, or a new one?** This guide assumes the same one. Then both deploys
      share every row, and an Import run from either writes to the data the other serves. For a separate copy,
      create a new project, run `make migrate ENV=staging` and `make seed ENV=staging` against it, and use its keys below.

---

## Step 1. AWS: launch the instance

All in the AWS console, region **Asia Pacific (Mumbai) `ap-south-1`** (top-right region picker), beside Supabase.

### 1.1 Launch

EC2 → **Launch instance**:

| Field | Value |
|---|---|
| Name | `sangam` |
| AMI | **Ubuntu Server 24.04 LTS** (64-bit x86) |
| Instance type | **t3.large** (2 vCPU, 8 GB). `t3.medium` (4 GB) works for light use; a large Import needs the memory |
| Key pair | Create new → `sangam-admin`, ED25519, `.pem`. This is *your* login; the deploy key comes later |
| Network settings → Edit | Create security group `sangam-web` with the rules in 1.2 |
| Storage | **30 GiB gp3** |

→ **Launch instance**.

### 1.2 Security group `sangam-web` (inbound)

| Type | Port | Source | Why |
|---|---|---|---|
| SSH | 22 | `0.0.0.0/0` | GitHub's runners SSH in from changing IPs. Keys only, no passwords (Ubuntu's default). See "Hardening" to narrow it |
| HTTP | 80 | `0.0.0.0/0`, `::/0` | Let's Encrypt challenge, and the redirect to HTTPS |
| HTTPS | 443 | `0.0.0.0/0`, `::/0` | The app |

Nothing else: 3000 and 8000 are reached only through Caddy, inside Docker.

### 1.3 Elastic IP

EC2 → Network & Security → **Elastic IPs** → Allocate → then Actions → **Associate** → instance `sangam`.
Note the address: it is `<elastic-ip>` from here on, and it survives stops and restarts.

### 1.4 Install Docker

From your machine:

```bash
chmod 600 ~/Downloads/sangam-admin.pem
ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip>
```

On the instance:

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y docker.io docker-compose-v2 unattended-upgrades
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
sudo mkdir -p /opt/sangam && sudo chown ubuntu:ubuntu /opt/sangam
exit      # log out and back in so the docker group applies
```

Check: `ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip> 'docker compose version'` prints a version.

### 1.5 Deploy key for GitHub Actions

A separate key, so the workflow never holds your admin key. On your machine:

```bash
ssh-keygen -t ed25519 -C "sangam-github-deploy" -f ~/.ssh/sangam-deploy -N ""
ssh-copy-id -i ~/.ssh/sangam-deploy.pub -o "IdentityFile ~/Downloads/sangam-admin.pem" ubuntu@<elastic-ip>
ssh -i ~/.ssh/sangam-deploy ubuntu@<elastic-ip> 'echo deploy key works'
```

`~/.ssh/sangam-deploy` (the private half, no `.pub`) becomes the `EC2_SSH_KEY` secret in Step 5.

---

## Step 2. Cloudflare: point the domain at the instance

Cloudflare dashboard → your zone `<domain>` → **DNS** → **Records** → Add record, twice:

| Type | Name | IPv4 address | Proxy status | TTL |
|---|---|---|---|---|
| A | `app` | `<elastic-ip>` | **DNS only** (grey cloud) | Auto |
| A | `api` | `<elastic-ip>` | **DNS only** (grey cloud) | Auto |

**Grey cloud, not orange.** Caddy must answer Let's Encrypt itself, and Cloudflare's proxy cuts a response off at about
100 s, which would end a long Import stream mid-run. (To proxy later, see "Hardening".)

If the zone has **CAA** records (DNS → filter by CAA), one must allow `letsencrypt.org`; with none, any CA may issue.

Check from your machine (a minute or two after saving):

```bash
dig +short app.<domain>    # → <elastic-ip>
dig +short api.<domain>    # → <elastic-ip>
```

---

## Step 3. Supabase: collect the values and allow the new domain

Supabase dashboard → your project.

### 3.1 Values to copy (you will paste them in Steps 4 and 5)

| Value | Where in Supabase | Goes to |
|---|---|---|
| Project URL `https://<ref>.supabase.co` | Project Settings → **Data API** (or the **Connect** button) | instance `.env` `SUPABASE_URL`, GitHub secret `AWS_NEXT_PUBLIC_SUPABASE_URL` |
| Publishable key (`sb_publishable_…`, or the legacy `anon` key) | Project Settings → **API Keys** | GitHub secret `AWS_NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| Secret key (`sb_secret_…`, or the legacy `service_role` key) | Project Settings → **API Keys** | instance `.env` `SUPABASE_SERVICE_KEY` only. Never in GitHub, never in the frontend |
| Session pooler connection string | **Connect** → *Connection string* → **Session pooler** (port **5432**) | instance `.env` `DATABASE_URL` |

Use the **session** pooler on 5432. The direct host `db.<ref>.supabase.co` is IPv6-only and Docker cannot reach it
(connections hang rather than fail), and the transaction pooler on 6543 is not supported. Replace `[YOUR-PASSWORD]`
with the database password (Project Settings → Database → Reset database password, if nobody has it). A password with
`@ : / ? #` needs percent-encoding in the URL form, or use the keyword form instead:
`host=aws-0-ap-south-1.pooler.supabase.com port=5432 user=postgres.<ref> password=<pw> dbname=postgres sslmode=require`.

### 3.2 Allow the new domain to sign in

Authentication → **URL Configuration**:

- **Redirect URLs** → Add URL → `https://app.<domain>/**` → Save.
  Sign-in sends people back to `https://app.<domain>/auth/callback?next=…`; without this entry Supabase refuses the
  redirect and falls back to the Site URL (the old host).
- **Site URL**: leave it on the Vercel address while Vercel stays the main deploy. Change it to `https://app.<domain>`
  when this one replaces it. It is only the fallback, and the base of links in auth emails.

### 3.3 Check Google is enabled

Authentication → **Sign In / Providers** → **Google**: *Enabled*, with a Client ID and Client Secret filled in.
If so (sign-in works on Vercel today), **Google needs no change for the new domain**: Google only ever redirects to
Supabase's callback, `https://<ref>.supabase.co/auth/v1/callback`, which has not moved. Skip to Step 4.

If Google is not set up yet, do Step 3.4.

### 3.4 Google OAuth client (only if Google is not enabled)

Google Cloud console (console.cloud.google.com), in the project that should own sign-in:

1. **Google Auth Platform** (formerly *APIs & Services → OAuth consent screen*) → Get started:
   - App name `Sangam`, user support email, audience **External**, contact email → Create.
   - **Branding** → Authorized domains → add `supabase.co`, and `<domain>` if you will link a privacy policy or home
     page on it.
   - **Data access** → scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (non-sensitive; no
     Google review needed).
   - **Audience** → *Publish app* (In production). While it is in *Testing*, only listed test users can sign in.
2. **Clients** (formerly *Credentials → Create credentials → OAuth client ID*) → Create client:
   - Application type **Web application**, name `Sangam (Supabase)`.
   - **Authorized JavaScript origins**: `https://app.<domain>` (and the Vercel URL if it stays).
   - **Authorized redirect URIs**: `https://<ref>.supabase.co/auth/v1/callback`, exactly. This is Supabase's callback,
     never the app's `/auth/callback`. Supabase shows the same URL on its Google provider page; copy it from there.
   - Create → copy the **Client ID** and **Client secret**.
3. Back in Supabase → Authentication → Sign In / Providers → **Google** → Enable, paste Client ID and Client secret → Save.

The Google sign-in page will say "continue to `<ref>.supabase.co`". Showing your own domain there needs a Supabase
custom domain (a paid add-on); it is cosmetic and not needed.

### 3.5 Storage buckets

Nothing to do on the same project: this deploy writes to the buckets the deployed app already uses (`org-vault`,
`source-archive`, `staff-sources`), which is why `STORAGE_BUCKET_SUFFIX` is left empty below. On a new project, create
those three as **private** buckets.

---

## Step 4. The instance: write `/opt/sangam/.env`

The backend reads every variable in this file, and Caddy reads the two domains. On the instance:

```bash
ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip>
nano /opt/sangam/.env
```

```bash
# Caddy: the two hosts it serves and gets certificates for
APP_DOMAIN=app.<domain>
API_DOMAIN=api.<domain>

# Supabase (Step 3.1)
DATABASE_URL=postgresql://postgres.<ref>:<db-password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=<secret key>
STORAGE_BUCKET_SUFFIX=

# Only the app's own origin may call the API from a browser (comma-separated if more than one)
ALLOWED_ORIGINS=https://app.<domain>

# Models and research
ANTHROPIC_API_KEY=<key>
TAVILY_API_KEY=<key>

# Tracing (optional; leave out to disable)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=aws
```

```bash
chmod 600 /opt/sangam/.env
```

Do **not** add:

- `DEV_AUTH`: it would accept `Bearer dev` as a signed-in user.
- `NEO4J_URI`, if you copy from a local `.env`: unset, the graph switches itself off, but set to a host the instance
  cannot reach, the backend fails at startup.
- Anything `STAGING_DB_*` or `LOCAL_DB_*`: local tooling only.

Optional settings (model tiers, `MAX_PARALLEL_RESEARCH`, `DB_POOL_MAX_SIZE`, `FREE_QUESTIONS`…) are in `.env.example`;
unset means the default in `backend/app/core/config.py`. If Vercel stays up on the same database, keep both deploys'
`DB_POOL_MAX_SIZE` together under Supabase's 60-connection limit.

---

## Step 5. GitHub: environment and secrets

Repo → **Settings**.

### 5.1 Environment

**Environments** → New environment → `aws-production` → Configure. Optional but recommended: tick *Required
reviewers* and add yourself, so every deploy waits for an approval click.

### 5.2 Secrets

**Secrets and variables → Actions → Secrets** tab → New repository secret, one per row. Secrets, not variables:
variables appear in the public run logs.

| Secret | Value |
|---|---|
| `EC2_HOST` | `<elastic-ip>` |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | The whole of `~/.ssh/sangam-deploy`, including the `-----BEGIN…` and `-----END…` lines (`pbcopy < ~/.ssh/sangam-deploy` on a Mac) |
| `AWS_NEXT_PUBLIC_API_URL` | `https://api.<domain>` (no trailing slash) |
| `AWS_NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `AWS_NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | The publishable key from Step 3.1 |

The three `NEXT_PUBLIC_*` values are compiled into the frontend at build time, so changing one needs a new deploy, and
any visitor can read them in the page's JavaScript. They are secrets here only to keep them out of the logs.

---

## Step 6. First deploy

1. **Actions** → **Deploy (AWS)** → **Run workflow** → branch `master`.
   - *Apply db/migrations before restarting*: leave ticked for a database only this deploy uses. If Vercel serves the
     same database, untick it and apply migrations yourself after a backup (`make migrate ENV=staging`), as the repo
     does today.
2. Approve it if you set required reviewers.
3. The `build` job takes ~5–10 min the first time (cached afterwards); `deploy` ~1–2 min. It ends with
   `backend healthy at <sha>`, or prints the backend's last 100 log lines and fails.

The first request to each domain makes Caddy fetch its certificate; give it up to a minute.

### 6.1 Make the images private

The first run creates two packages under the org, public by default because the repo is. GitHub → the org →
**Packages** → `sangam-backend` → Package settings → Danger zone → **Change visibility** → Private. Same for
`sangam-frontend`. The workflow logs in with its own token, so deploys keep working.

---

## Step 7. Check it

From your machine:

```bash
curl -s https://api.<domain>/health                  # {"status":"ok","pool":{…}}
curl -sI https://app.<domain>/ | head -1             # HTTP/2 200
curl -sI http://app.<domain>/ | grep -i location     # → https://app.<domain>/
```

In a browser:

1. `https://app.<domain>`: the home page, with the Registry populated.
2. **Sign in** → Google → choose an account → you land back on `https://app.<domain>`, signed in.
   If you land on the Vercel site instead, the redirect URL in Step 3.2 is missing or mistyped.
3. `/ask`: ask "How many organisations are in the registry?" and an answer with citation chips streams back.
4. `/import` opens for staff and stewards.

---

## Everyday

| To | Do |
|---|---|
| Deploy a new version | Actions → Deploy (AWS) → Run workflow on `master` |
| See what is running | `ssh … 'cat /opt/sangam/deployed.txt'` |
| Change a backend setting | Edit `/opt/sangam/.env`, then `docker compose -f docker-compose.prod.yml up -d` in `/opt/sangam` |
| Change a `NEXT_PUBLIC_*` value | Edit the GitHub secret, then re-run the workflow |
| Read logs | `cd /opt/sangam && docker compose -f docker-compose.prod.yml logs -f backend` (or `frontend`, `caddy`) |
| Restart | `docker compose -f docker-compose.prod.yml restart backend` |
| Watch memory during an Import | `docker stats` |

A manual `docker compose pull` on the instance needs a GHCR login once the packages are private: a personal access
token (classic) with `read:packages`, then `echo <token> | docker login ghcr.io -u <github-user> --password-stdin`.

### Rolling back

Every deploy's images stay in GHCR under their commit SHA:

```bash
cd /opt/sangam && TAG=<older-sha> docker compose -f docker-compose.prod.yml up -d
```

or run the workflow from an older commit's branch or tag. Migrations are additive and are not rolled back.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Certificate error for a minute after the first deploy | Caddy is still getting the certificate. Longer: `docker compose … logs caddy`; usually DNS not yet pointing at `<elastic-ip>`, port 80 closed, or an orange cloud |
| `deploy` job: `ssh: handshake failed` | `EC2_SSH_KEY` is not the full private key, or the `.pub` was not added to `~ubuntu/.ssh/authorized_keys` (Step 1.5) |
| `deploy` job: `/opt/sangam/.env is missing` | Step 4 |
| `backend did not become healthy`, logs mention neo4j | `NEO4J_URI` is set in `.env`; remove it |
| …logs mention a missing table or `_verify_sql_catalog` | The database is not migrated; run the workflow with *migrate* ticked, or `make migrate ENV=staging` |
| …connections hang or time out | `DATABASE_URL` uses the direct host or port 6543; use the session pooler on 5432 |
| Sign-in returns to the Vercel site | Step 3.2's redirect URL |
| Google error `redirect_uri_mismatch` | The Google client's redirect URI is not exactly `https://<ref>.supabase.co/auth/v1/callback` |
| "Access blocked: app is in testing" | Publish the consent screen (Step 3.4), or add the user as a test user |
| Pages load but API calls fail with CORS errors in the console | `ALLOWED_ORIGINS` is not exactly `https://app.<domain>` |
| Frontend calls the wrong API host | `AWS_NEXT_PUBLIC_API_URL` was wrong at build time; fix the secret and redeploy |

---

## Differences from Vercel

- No 1800 s ceiling: a long Import runs to the end.
- One instance, one container each: no autoscaling, no cold starts, and no keep-warm cron needed.
- You patch the OS (`unattended-upgrades` handles security updates) and watch the disk; the workflow prunes old images.

## Hardening (optional)

- **Narrow SSH.** Replace the `0.0.0.0/0` rule with your IP and run deploys through AWS SSM (`aws ssm send-command`)
  instead of SSH, or allow GitHub's runner ranges (`curl -s https://api.github.com/meta | jq .actions`; long and
  changing).
- **Cloudflare proxy.** To hide the instance IP behind the orange cloud: set SSL/TLS mode to *Full (strict)*, and know
  that responses over ~100 s are cut, which breaks long Imports.
- **Back up `caddy_data`** if you rebuild the instance often; Let's Encrypt rate-limits re-issuing the same certificate.
- Instance snapshots are not needed for data (it is all in Supabase); the instance is rebuildable from this guide.
