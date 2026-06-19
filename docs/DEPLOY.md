# FinSight — Hetzner Deployment Runbook

One-time setup. After this, `git push` to the deploy branch redeploys automatically.

## 1. Create the server
- Hetzner Cloud Console → create a **CX33** (x86, 4 vCPU / 8 GB / 80 GB), Ubuntu 24.04.
- Add your SSH public key during creation. Note the public IPv4.

## 2. Base setup (as root, then a deploy user)
```bash
ssh root@<BOX_IP>
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
# Docker Engine + compose plugin
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
```
(Optional: a UFW firewall is not required for ingress because Cloudflare Quick Tunnel is outbound-only. If you enable UFW, allow only SSH: `ufw allow 22 && ufw enable`.)

## 3. Tailscale auth key
- Tailscale admin console → Settings → Keys → generate an **auth key** (reusable, optionally ephemeral). This becomes the `TS_AUTHKEY` in `.env`.
- Make sure your **PC** is on the same tailnet and Langfuse is running on it (`docker compose up` of the existing local `docker-compose.yml`, which exposes Langfuse on `:3000`). Note your PC's tailnet IP (`tailscale ip -4`).

## 4. Clone the repo on the box
```bash
su - deploy
git clone <REPO_URL> ~/NYSE-analysis
cd ~/NYSE-analysis
git checkout master   # the deploy branch
```

## 5. Create the server `.env`
```bash
cp .env.prod.example .env
nano .env   # fill in real values
```
Set: `SAMBANOVA_API_KEY`, `TAVILY_API_KEY`, `POSTGRES_PASSWORD` (and the matching password in `DATABASE_URL`), `EDGAR_IDENTITY`, `OWNER_EMAIL`, the three `LANGFUSE_*` (host = your PC's tailnet IP, e.g. `http://100.x.y.z:3000`), and `TS_AUTHKEY`.

## 6. First boot
```bash
docker compose -f docker-compose.prod.yml up -d --build
```
- First build is slow (torch + fastembed). First boot also downloads ML models into the `model_cache` volume — watch progress:
  `docker compose -f docker-compose.prod.yml logs -f app`
- Get the public URL:
  `docker compose -f docker-compose.prod.yml logs cloudflared | grep trycloudflare`

## 7. Verify end-to-end
- Open the `https://*.trycloudflare.com` URL → the app loads.
- Register a user, log in (HTTPS cookie works).
- Ask a real stock question → a financial answer returns (SambaNova + SEC live).
- Confirm a trace appears in your PC's Langfuse UI (`http://localhost:3000`).
- Reachability check:
  `docker compose -f docker-compose.prod.yml exec app curl -fsS http://100.x.y.z:3000/api/public/health`

## 8. Wire up auto-deploy
- GitHub repo → Settings → Secrets and variables → Actions → add:
  - `DEPLOY_HOST` = `<BOX_IP>`
  - `DEPLOY_USER` = `deploy`
  - `DEPLOY_SSH_KEY` = the **private** key matching the box's `authorized_keys`
- Push a trivial commit to the deploy branch → the `deploy` workflow runs → the box rebuilds.

## Operations
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f <service>`
- **New tunnel URL after restart:** re-run the `grep trycloudflare` command (the Quick Tunnel URL changes on restart — upgrade to a Named Tunnel + cheap domain later for stability).
- **Restart:** `docker compose -f docker-compose.prod.yml restart`
- **Update manually:** `git pull && docker compose -f docker-compose.prod.yml up -d --build`
