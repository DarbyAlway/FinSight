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

> ⚠️ **Unauthenticated.** This demo has no login (auth is a later plan). Anyone with
> the URL can use the assistant and spend the SambaNova budget. Run the tunnel **only
> while demoing** and press Ctrl-C to tear it down afterward. Use a single uvicorn
> worker (the DuckDB cache + in-process state assume one process).
