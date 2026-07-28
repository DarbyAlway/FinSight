"""FastAPI backend for the finance chat UI.

CRUD over chats/messages (Postgres) plus an SSE endpoint (next task) that runs a
turn through the orchestrator. No auth in this plan (Plan 4); no ask-back/resume
(Plan 3).
"""
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from webapp import accounts, auth, db
from webapp.title_gen import generate_title
from webapp.turn_runner import stream_turn


def _edgar_identity() -> str:
    """SEC/EDGAR requires a real contact string in prod; placeholder for local dev."""
    return os.environ.get("EDGAR_IDENTITY", "yourname@email.com")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_app_schema()
    accounts.init_accounts_schema()
    # Heavy orchestrator warmup (Qdrant, anchor vectors, SEC identity) is only
    # needed for real turns; skip it under tests (which mock the turn) via
    # WEBAPP_SKIP_WARMUP=1 so the API suite needs no Qdrant container.
    if os.environ.get("WEBAPP_SKIP_WARMUP") != "1":
        from edgar import set_identity
        from tools.vector import init_qdrant
        from tools.search_guardrails import _get_anchor_vecs
        set_identity(_edgar_identity())
        init_qdrant()
        _get_anchor_vecs()
    yield


app = FastAPI(title="FinSight API", lifespan=lifespan)

_PER_USER_TOKEN_CAP = 200_000


def _global_cap() -> int:
    return int(os.environ.get("GLOBAL_TOKEN_CAP", "5000000"))


class CreateChat(BaseModel):
    title: str = "New chat"


class SendMessage(BaseModel):
    content: str


class Credentials(BaseModel):
    email: str
    password: str


def _public_user(u: dict) -> dict:
    return {"id": u["user_id"], "email": u["email"], "is_owner": u["is_owner"],
            "tokens_used": u["tokens_used"]}


@app.post("/auth/register")
def register(body: Credentials, response: Response):
    if accounts.get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    is_owner = body.email.lower() == os.environ.get("OWNER_EMAIL", "").lower() and bool(
        os.environ.get("OWNER_EMAIL"))
    uid = accounts.create_user(body.email, auth.hash_password(body.password), is_owner=is_owner)
    token = accounts.create_session(uid, ttl_days=auth.SESSION_TTL_DAYS)
    auth.set_session_cookie(response, token)
    return _public_user(accounts.get_user_by_id(uid))


@app.post("/auth/login")
def login(body: Credentials, response: Response):
    user = accounts.get_user_by_email(body.email)
    if user is None or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = accounts.create_session(user["user_id"], ttl_days=auth.SESSION_TTL_DAYS)
    auth.set_session_cookie(response, token)
    return _public_user(user)


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(auth.COOKIE_NAME)
    if tok:
        accounts.delete_session(tok)
    auth.clear_session_cookie(response)
    return {"ok": True}


@app.get("/auth/me")
def me(user: dict = Depends(auth.current_user)):
    return _public_user(user)


@app.get("/chats")
def list_chats(user: dict = Depends(auth.current_user)):
    return db.list_chats(user["user_id"])


@app.post("/chats")
def create_chat(body: CreateChat, user: dict = Depends(auth.current_user)):
    return {"id": db.create_chat(user["user_id"], title=body.title)}


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str, user: dict = Depends(auth.current_user)):
    chat = db.get_chat(chat_id, user["user_id"])
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, user: dict = Depends(auth.current_user)):
    if db.get_chat(chat_id, user["user_id"]) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    db.delete_chat(chat_id, user["user_id"])
    return {"ok": True}


@app.post("/chats/{chat_id}/messages")
def send_message(chat_id: str, body: SendMessage, request: Request,
                 user: dict = Depends(auth.current_user)):
    """Start a turn for this chat and stream SSE: `stage`* then `answer`/`error`.
    Saves the user message immediately and the assistant message once produced.

    On a turn error, the stream emits an `error` event and on_answer is never
    called, so the user message persists with no assistant reply — intentional,
    so the user can retry without re-typing. (Resume/ask-back is Plan 3; this
    always starts a fresh turn.)

    Quota: the global kill-switch (everyone) is checked first, then the per-user
    lifetime cap (owner exempt). Token usage is metered after the turn via the
    orchestrator's on_usage callback (recorded against the user + a per-turn row
    carrying soft IP/User-Agent abuse signals)."""
    if db.get_chat(chat_id, user["user_id"]) is None:
        raise HTTPException(status_code=404, detail="chat not found")

    # Global kill-switch (everyone), then per-user lifetime cap (owner exempt).
    if accounts.global_tokens_used() >= _global_cap():
        raise HTTPException(status_code=503, detail="The service is temporarily paused (budget cap reached).")
    if not user["is_owner"] and user["tokens_used"] >= _PER_USER_TOKEN_CAP:
        raise HTTPException(status_code=429, detail="You've reached your usage limit.")

    history = db.get_messages(chat_id)
    db.add_message(chat_id, role="user", content=body.content)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    def on_answer(answer: str):
        db.add_message(chat_id, role="assistant", content=answer)

    def on_usage(total_tokens: int):
        accounts.add_user_tokens(user["user_id"], total_tokens)
        accounts.record_usage(user["user_id"], total_tokens, ip, ua)

    # On the chat's very first message, generate a short title in the background so it never slows down the main answer.
    # Errors are caught here so a DB blip can't kill the thread or lose the title's token count.
    if not history:
        def generate_and_save_title():
            try:
                title, tokens = generate_title(body.content)
                db.update_chat_title(chat_id, title)
                if tokens:
                    on_usage(tokens)
            except Exception:
                logging.exception("Background title generation failed for chat %s", chat_id)
        threading.Thread(target=generate_and_save_title, daemon=True).start()

    return StreamingResponse(
        stream_turn(user_input=body.content, history=history,
                    on_answer=on_answer, on_usage=on_usage),
        media_type="text/event-stream",
    )


_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")


def mount_frontend(target_app, dist_dir: str = _FRONTEND_DIST) -> None:
    """Serve the built React bundle at '/' if it exists. Mounted AFTER the API
    routes so '/chats*' still hits the API; the catch-all only serves the SPA.
    A no-op when the build dir is absent (dev / API-only test setups)."""
    if os.path.isdir(dist_dir):
        target_app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")


# Serve the SPA when a production build is present (skipped in dev/tests).
mount_frontend(app)
