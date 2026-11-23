# Deploying Sangam on AWS (one EC2 instance)

An alternative to the Vercel deploy in `CLAUDE.md`, "Deployment". A GitHub Actions workflow builds both images,
pushes them to GHCR, and restarts them on one EC2 instance over SSH. Postgres stays on Supabase; Caddy in front
serves HTTPS. Nothing deploys on a push: the workflow is run by hand, like the Vercel one.

```
GitHub Actions ── build ──▶ ghcr.io/…/sangam-backend, sangam-frontend   (tag = commit SHA, and latest)
      │
      └─ ssh ──▶ EC2: /opt/sangam
                    caddy :80/:443 ──▶ frontend :3000 ──▶ backend :8000 ──▶ Supabase Postgres
```

| File | Role |
|---|---|
| `.github/workflows/deploy-aws.yml` | Builds, pushes, copies the bundle, migrates, restarts, waits for `/health` |
| `deploy/aws/docker-compose.prod.yml` | The three services on the instance |
| `deploy/aws/Caddyfile` | Two hosts, read from `APP_DOMAIN` / `API_DOMAIN` |
| `frontend/Dockerfile` | Production Next.js build (`Dockerfile.dev` stays for local) |

No domain, host or key is written in the repo. They live in the instance's `.env` and in GitHub **secrets**:
the repo is public, so its Actions logs are too, and variables are printed there in clear.

## 1. The instance (once)

1. Launch Ubuntu 24.04 in **ap-south-1**, beside Supabase. `t3.large` (8 GB) is comfortable; `t3.medium` works.
   30 GB disk. Attach an Elastic IP.
2. Security group: **22** from your IP (or GitHub's runner ranges, see "Hardening"), **80** and **443** from anywhere.
   Nothing else; 3000 and 8000 are reached only through Caddy.
3. Install Docker and make the deploy folder:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2
   sudo usermod -aG docker ubuntu && newgrp docker
   sudo mkdir -p /opt/sangam && sudo chown ubuntu:ubuntu /opt/sangam
   ```
4. Make a deploy key and authorise it:
   ```bash
   ssh-keygen -t ed25519 -f sangam-deploy -N ""          # on your machine
   ssh-copy-id -i sangam-deploy.pub ubuntu@<elastic-ip>
   ```
   The private half, `sangam-deploy`, becomes the `EC2_SSH_KEY` secret below.

## 2. DNS (Cloudflare)

Two `A` records to the Elastic IP, one for the app and one for the API. Set both **DNS only** (grey cloud):
Caddy needs to answer the certificate challenge itself, and Cloudflare's proxy cuts a response at ~100 s,
which would end a long Import stream.

## 3. `/opt/sangam/.env` on the instance

The backend reads every variable in this file. Start from `.env.example` and keep only what the backend needs:

```bash
APP_DOMAIN=app.<your-domain>
API_DOMAIN=api.<your-domain>

# Supabase session pooler on 5432 (not the direct host, not the 6543 transaction pooler)
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres

ANTHROPIC_API_KEY=
TAVILY_API_KEY=
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=
STORAGE_BUCKET_SUFFIX=                    # empty: the Storage project's own buckets
ALLOWED_ORIGINS=https://app.<your-domain>

LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=aws
```

Never set `DEV_AUTH` here. Leave `NEO4J_URI` unset and the graph switches itself off. `chmod 600 .env`.

## 4. GitHub (once)

Settings → Environments → **New environment** `aws-production` (add required reviewers if you want a second pair of
eyes on each deploy). Then Settings → Secrets and variables → Actions → **secrets**:

| Secret | Value |
|---|---|
| `EC2_HOST` | The Elastic IP |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | The private deploy key from step 1.4 |
| `AWS_NEXT_PUBLIC_API_URL` | `https://api.<your-domain>` |
| `AWS_NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `AWS_NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key |

The `NEXT_PUBLIC_*` values are compiled into the frontend bundle, so a visitor can see them; they are secrets here
only to keep them out of the public logs.

## 5. Supabase Auth (once)

Authentication → URL Configuration: add `https://app.<your-domain>` to the redirect URLs (and as the site URL if this
replaces Vercel). Without it sign-in bounces back to the old host.

## 6. Deploy

Actions → **Deploy (AWS)** → Run workflow, on `master`. The run:

1. builds both images and pushes them as `:<sha>` and `:latest`;
2. copies the compose file, Caddyfile and `db/migrations/` to `/opt/sangam`;
3. runs `python -m app.db.migrate` when **migrate** is ticked (the default);
4. `docker compose up -d`, then waits up to 150 s for the backend's `/health`, printing its logs if it never comes up.

After the first run, set both packages private: the org's **Packages** → `sangam-backend` / `sangam-frontend` →
Package settings → Change visibility. The deploy logs in with the job's token, so pulls keep working.

Check it:

```bash
curl -s https://api.<your-domain>/health
open https://app.<your-domain>
```

**Migrations write to the shared database.** If Vercel still serves the same Supabase project, untick *migrate* and
apply them yourself after a backup (`make migrate ENV=staging`), as the repo's rule is today. The first time, seed data
must already be there; `make seed` is not part of this workflow.

## On the instance

```bash
cd /opt/sangam
c="docker compose -f docker-compose.prod.yml"
cat deployed.txt                          # which commit is running
$c ps
$c logs -f backend
$c restart backend
```

A manual `pull` needs a GHCR login once the packages are private: a personal access token with `read:packages`,
`echo <token> | docker login ghcr.io -u <you> --password-stdin`.

## Rolling back

Every deploy's image stays in GHCR under its commit SHA:

```bash
cd /opt/sangam && TAG=<older-sha> docker compose -f docker-compose.prod.yml up -d
```

or re-run the workflow from that commit (Run workflow → pick the branch or tag). A migration is not rolled back; they
are additive.

## Differences from Vercel

- No 1800 s ceiling: a long Import runs to the end.
- One instance, one process each: no autoscaling and no cold starts. Watch memory during a large Import
  (`docker stats`); move up an instance size before raising `MAX_PARALLEL_RESEARCH`.
- Vercel's keep-warm cron (`backend/vercel.json`) is not needed: the containers never sleep.
- Supabase allows 60 connections across every instance: if Vercel and AWS both run, their `DB_POOL_MAX_SIZE` add up.

## Hardening (optional)

- Restrict port 22 to GitHub's runner ranges (`curl https://api.github.com/meta | jq .actions`), or replace the SSH
  step with AWS SSM `send-command` and close 22 entirely.
- Unattended upgrades: `sudo apt install -y unattended-upgrades`.
- Back up `caddy_data` if you redeploy often; Let's Encrypt rate-limits re-issuing the same certificate.
