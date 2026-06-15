# FinSight frontend

Vite + React + TypeScript chat UI for the FinSight finance assistant. Dark theme,
responsive (off-canvas sidebar drawer on mobile). Talks to the FastAPI backend's
`/chats` REST + SSE endpoints.

## Develop

```bash
npm install
npm run dev      # http://localhost:5173, proxies /chats → http://localhost:8000
npm test         # Vitest
npm run build    # type-check + production bundle into dist/
```

Run the backend in another terminal (`python -m webapp` with `DATABASE_URL` set and
Postgres + Qdrant up). In dev the Vite proxy makes the API same-origin.

## Auth, accounts & quota

The app requires a login (email + password). Registration is **open** — anyone can
create an account. Sessions are server-side opaque tokens delivered as an
`HttpOnly`, `SameSite=Lax` cookie (XSS-safe, revoked on logout). Passwords are
hashed with argon2. Each user's chats are private to them.

Usage is metered per user: a per-user **lifetime cap of 200,000 tokens**, plus a
system-wide **global token kill-switch**. The account whose email matches
`OWNER_EMAIL` is exempt from the per-user cap. Per-turn token usage (with the
requester's IP + User-Agent as soft abuse signals) is recorded in `usage_ledger`.

### Backend env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `OWNER_EMAIL` | *(unset)* | Email (case-insensitive) of the single account exempt from the per-user cap. Matched at registration. |
| `GLOBAL_TOKEN_CAP` | `5000000` | System-wide token ceiling. Once total tokens used reaches it, every turn is rejected with HTTP 503 (kill-switch). |
| `SESSION_TTL_DAYS` | `30` | Session lifetime, in days (cookie max-age + server-side expiry). |
| `SESSION_COOKIE_SECURE` | *(off)* | Set to `"1"` in production (HTTPS) so the session cookie is marked `Secure`. Leave off for local HTTP. |

Raise an individual user's cap by editing the DB (`users.tokens_used` / `is_owner`);
there is no admin UI yet. Email verification, password reset, and rate limiting are
out of scope for this plan.

## Single-server (built bundle)

`npm run build`, then start the backend — FastAPI serves `dist/` at `/` (guarded
`StaticFiles` mount), so the whole app is on `http://localhost:8000`, one origin.

## Live demo via Cloudflare quick tunnel

Expose the single-server setup over an HTTPS URL without deploying:

```bash
# one-time install of cloudflared
winget install --id Cloudflare.cloudflared        # Windows
# (macOS: brew install cloudflared)

cd webapp/frontend && npm run build               # build the SPA
python -m webapp                                  # backend serves it on :8000
cloudflared tunnel --url http://localhost:8000    # prints https://<random>.trycloudflare.com
```

Share the printed `*.trycloudflare.com` URL. It works on phones (the layout is
responsive). The SPA uses relative `/chats` URLs, so no CORS or allowed-hosts config
is needed.

> ⚠️ **Open registration + shared budget.** The app now requires a login, but
> registration is open, so anyone with the URL can sign up and spend the SambaNova
> budget (bounded by the per-user 200k cap and `GLOBAL_TOKEN_CAP`). Set `OWNER_EMAIL`
> to your own account and tune `GLOBAL_TOKEN_CAP` before sharing. Run the tunnel
> **only while demoing** and press Ctrl-C to tear it down afterward. Use a single
> uvicorn worker (the DuckDB cache + in-process state assume one process).
