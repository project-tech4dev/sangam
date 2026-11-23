# Deploying Sangam on AWS (one EC2 instance)

A self-hosted alternative to the Vercel deploy in `CLAUDE.md`, "Deployment". The instance holds a checkout of this
repo; `deploy/aws/deploy.sh` pulls a ref, builds both images there, migrates and restarts them. Postgres, Storage and
sign-in stay on Supabase; Caddy on the instance serves HTTPS with Let's Encrypt certificates. Nothing deploys on a
push: someone with the server key runs the script.

```
browser ──https──▶ Cloudflare DNS (grey cloud) ──▶ EC2 Elastic IP
                                                     caddy :443 ─┬─ app.<domain> ──▶ frontend :3000 ─┐
                                                                 └─ api.<domain> ──▶ backend  :8000 ◀┘
                                                                                       │
                                     Supabase (Postgres · Storage · Auth) ◀────────────┘
you ── ssh ──▶ EC2: /opt/sangam/deploy/aws/deploy.sh  (git fetch → docker compose build → migrate → up)
```

| File | Role |
|---|---|
| `deploy/aws/deploy.sh` | Checks out a ref, builds, migrates, restarts, reloads Caddy, waits for `/health` |
| `deploy/aws/compose.yaml` | The three services; builds from the checkout |
| `deploy/aws/caddy/Caddyfile` | Two hosts, read from `APP_DOMAIN` / `API_DOMAIN` |
| `frontend/Dockerfile` | Production Next.js build, standalone (~260 MB); `NEXT_OUTPUT=standalone` is set only here, so Vercel and local are unchanged |
| `.github/workflows/deploy-aws.yml` | Phase 2, not in use: the same deploy from GitHub Actions through GHCR (see the end) |

No domain, host or key is written in the repo. They live only in the instance's `deploy/aws/.env`, which git ignores.

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

- [ ] Admin on the AWS account, the Cloudflare zone for `<domain>`, the Supabase project, and the Google Cloud project
      that owns the OAuth client.
- [ ] The code you deploy is on GitHub: `master` by default, or any branch, tag or SHA you pass to the script.
- [ ] The Supabase database already migrated and seeded (it is, if Vercel serves it today). The script migrates;
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
| Instance type | **t3.large** (2 vCPU, 8 GB). It also builds the images, and a large Import needs the memory |
| Key pair | Create new → `sangam-admin`, ED25519, `.pem`. Whoever holds it can deploy |
| Network settings → Edit | Create security group `sangam-web` with the rules in 1.2 |
| Storage | **30 GiB gp3** |

→ **Launch instance**.

### 1.2 Security group `sangam-web` (inbound)

| Type | Port | Source | Why |
|---|---|---|---|
| SSH | 22 | **My IP** (and each deployer's IP) | Only people deploy now, so SSH need not be open to the world. Keys only |
| HTTP | 80 | `0.0.0.0/0`, `::/0` | Let's Encrypt challenge, and the redirect to HTTPS |
| HTTPS | 443 | `0.0.0.0/0`, `::/0` | The app |

Nothing else: 3000 and 8000 are reached only through Caddy, inside Docker. If your IP changes, edit the SSH rule.

### 1.3 Elastic IP

EC2 → Network & Security → **Elastic IPs** → Allocate → then Actions → **Associate** → instance `sangam`.
Note the address: it is `<elastic-ip>` from here on, and it survives stops and restarts.

### 1.4 Install Docker and clone the repo

From your machine:

```bash
chmod 600 ~/Downloads/sangam-admin.pem
ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip>
```

On the instance:

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y docker.io docker-compose-v2 docker-buildx git unattended-upgrades
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu

# 4 GB of swap, so a frontend build beside the running app cannot run out of memory
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# The repo is public, so cloning needs no credentials
sudo mkdir -p /opt/sangam && sudo chown ubuntu:ubuntu /opt/sangam
git clone https://github.com/project-tech4dev/sangam.git /opt/sangam
exit      # log out and back in so the docker group applies
```

Check: `ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip> 'docker compose version && docker buildx version'`
prints two versions.

To let a teammate deploy, add their public key to `~ubuntu/.ssh/authorized_keys` and their IP to the SSH rule.

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

### 3.1 Values to copy (you will paste them in Step 4)

| Value | Where in Supabase | Goes to |
|---|---|---|
| Project URL `https://<ref>.supabase.co` | Project Settings → **Data API** (or the **Connect** button) | `.env` `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL` |
| Publishable key (`sb_publishable_…`, or the legacy `anon` key) | Project Settings → **API Keys** | `.env` `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| Secret key (`sb_secret_…`, or the legacy `service_role` key) | Project Settings → **API Keys** | `.env` `SUPABASE_SERVICE_KEY` only. Never in the frontend, never in a `NEXT_PUBLIC_*` |
| Session pooler connection string | **Connect** → *Connection string* → **Session pooler** (port **5432**) | `.env` `DATABASE_URL` |

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

## Step 4. The instance: write `/opt/sangam/deploy/aws/.env`

Compose reads this file: the backend gets every variable, the frontend build gets the three `NEXT_PUBLIC_*`, and Caddy
the two domains. Git ignores it. On the instance:

```bash
ssh -i ~/Downloads/sangam-admin.pem ubuntu@<elastic-ip>
nano /opt/sangam/deploy/aws/.env
```

```bash
# Caddy: the two hosts it serves and gets certificates for
APP_DOMAIN=app.<domain>
API_DOMAIN=api.<domain>

# Compiled into the frontend at build time; a change needs a redeploy. Public by design.
NEXT_PUBLIC_API_URL=https://api.<domain>
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>

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
chmod 600 /opt/sangam/deploy/aws/.env
```

`NEXT_PUBLIC_API_URL` has no trailing slash. Do **not** add:

- `DEV_AUTH`: it would accept `Bearer dev` as a signed-in user.
- `NEO4J_URI`, if you copy from a local `.env`: unset, the graph switches itself off, but set to a host the instance
  cannot reach, the backend fails at startup.
- Anything `STAGING_DB_*` or `LOCAL_DB_*`: local tooling only.

Optional settings (model tiers, `MAX_PARALLEL_RESEARCH`, `DB_POOL_MAX_SIZE`, `FREE_QUESTIONS`…) are in `.env.example`;
unset means the default in `backend/app/core/config.py`. If Vercel stays up on the same database, keep both deploys'
`DB_POOL_MAX_SIZE` together under Supabase's 60-connection limit.

---

## Step 5. First deploy

On the instance:

```bash
/opt/sangam/deploy/aws/deploy.sh
```

It checks out `origin/master`, builds both images (~5–10 min the first time, faster once layers are cached), applies
`db/migrations`, restarts, and ends with `backend healthy at <sha>`, or prints the backend's last 100 log lines and
fails. The old containers keep serving while it builds.

- **Migrations** run by default. If Vercel serves the same database and you would rather apply them yourself after a
  backup (`make migrate ENV=staging`), run `MIGRATE=0 /opt/sangam/deploy/aws/deploy.sh`.
- **Another ref**: `deploy.sh origin/<branch>`, a tag, or a SHA.
- The script refuses to run if someone edited files in the checkout; `.env` and `deployed.txt` are ignored and fine.

The first request to each domain makes Caddy fetch its certificate; give it up to a minute.

---

## Step 6. Check it

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

All on the instance, in `/opt/sangam/deploy/aws` (plain `docker compose` finds `compose.yaml` there):

| To | Do |
|---|---|
| Deploy a new version | `./deploy.sh` |
| See what is running, and when it went out | `tail deployed.txt` |
| Change a backend setting | Edit `.env`, then `docker compose up -d` |
| Change a `NEXT_PUBLIC_*` value or a domain | Edit `.env`, then `./deploy.sh` (it rebuilds the frontend) |
| Read logs | `docker compose logs -f backend` (or `frontend`, `caddy`) |
| Restart | `docker compose restart backend` |
| Watch memory during an Import | `docker stats` |

**A deploy interrupts running Imports and chats.** The backend gets 30 s to finish on restart; an Import takes
15–20 min. Check nobody is mid-Import before deploying.

### Rolling back

Deploy the older commit; the script rebuilds it, mostly from cached layers:

```bash
./deploy.sh <older-sha>      # deployed.txt lists the SHAs that went out
```

Migrations are additive and are not rolled back, so use `MIGRATE=0` when the older commit has fewer of them.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Certificate error for a minute after the first deploy | Caddy is still getting the certificate. Longer: `docker compose logs caddy`; usually DNS not yet pointing at `<elastic-ip>`, port 80 closed, or an orange cloud |
| `ssh: connect … timed out` | Your IP is not in the SSH rule (Step 1.2) |
| `deploy/aws/.env is missing` | Step 4 |
| `set NEXT_PUBLIC_… in .env` (or `APP_DOMAIN`) | That line is missing from `.env` |
| `the checkout has local changes` | `git -C /opt/sangam status`; discard with `git -C /opt/sangam checkout .` |
| Build killed, or the instance freezes while building | Out of memory: check the swap from Step 1.4 is on (`swapon --show`) |
| `backend did not become healthy`, logs mention neo4j | `NEO4J_URI` is set in `.env`; remove it |
| …logs mention a missing table or `_verify_sql_catalog` | The database is not migrated; run without `MIGRATE=0`, or `make migrate ENV=staging` |
| …connections hang or time out | `DATABASE_URL` uses the direct host or port 6543; use the session pooler on 5432 |
| Sign-in returns to the Vercel site | Step 3.2's redirect URL |
| Google error `redirect_uri_mismatch` | The Google client's redirect URI is not exactly `https://<ref>.supabase.co/auth/v1/callback` |
| "Access blocked: app is in testing" | Publish the consent screen (Step 3.4), or add the user as a test user |
| Pages load but API calls fail with CORS errors in the console | `ALLOWED_ORIGINS` is not exactly `https://app.<domain>` |
| Frontend calls the wrong API host | `NEXT_PUBLIC_API_URL` was wrong at build time; fix `.env` and `./deploy.sh` |
| Disk filling up | `docker system df`; `docker builder prune` clears the build cache |

---

## Differences from Vercel

- No 1800 s ceiling: a long Import runs to the end, unless a deploy restarts the backend under it.
- One instance, one container each: no autoscaling, no cold starts, and no keep-warm cron needed.
- You patch the OS (`unattended-upgrades` handles security updates) and watch the disk; the script prunes old images.

## Hardening (optional)

- **Cloudflare proxy.** To hide the instance IP behind the orange cloud: set SSL/TLS mode to *Full (strict)*, and know
  that responses over ~100 s are cut, which breaks long Imports.
- **Back up `caddy_data`** if you rebuild the instance often; Let's Encrypt rate-limits re-issuing the same certificate.
- Instance snapshots are not needed for data (it is all in Supabase); the instance is rebuildable from this guide.

## Phase 2: deploying from GitHub Actions

`.github/workflows/deploy-aws.yml` is kept for later and is not in use. It builds the images on GitHub, pushes them to
GHCR, and has the instance pull them over SSH, so the instance stops building and deploys gain an approval step and a
log in GitHub. Before switching to it, apply the open review points: run only from `master`, push `:latest` only after
approval (or drop it), pin each action to a commit SHA, give the deploy job `packages: read`, log out of GHCR in a
`trap`, and let the health loop print the logs when `up` fails. It then also needs a deploy key, the SSH rule opened to
GitHub's runners (or AWS SSM instead of SSH), an `aws-production` environment, and the `NEXT_PUBLIC_*` values as
repository secrets.
