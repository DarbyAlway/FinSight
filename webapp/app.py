"""FastAPI backend for the finance chat UI.

CRUD over chats/messages (Postgres) plus an SSE endpoint (next task) that runs a
turn through the orchestrator. No auth in this plan (Plan 4); no ask-back/resume
(Plan 3).
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from webapp import accounts, auth, db
from webapp.turn_runner import stream_turn


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
        set_identity("yourname@email.com")
        init_qdrant()
        _get_anchor_vecs()
    yield


app = FastAPI(title="FinSight API", lifespan=lifespan)


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
def send_message(chat_id: str, body: SendMessage, user: dict = Depends(auth.current_user)):
    """Start a turn for this chat and stream SSE: `stage`* then `answer`/`error`.
    Saves the user message immediately and the assistant message once produced.

    On a turn error, the stream emits an `error` event and on_answer is never
    called, so the user message persists with no assistant reply — intentional,
    so the user can retry without re-typing. (Resume/ask-back is Plan 3; this
    always starts a fresh turn.) Quota enforcement + usage recording is added in
    Task 6."""
    if db.get_chat(chat_id, user["user_id"]) is None:
        raise HTTPException(status_code=404, detail="chat not found")

    history = db.get_messages(chat_id)
    db.add_message(chat_id, role="user", content=body.content)

    def on_answer(answer: str):
        db.add_message(chat_id, role="assistant", content=answer)

    return StreamingResponse(
        stream_turn(user_input=body.content, history=history, on_answer=on_answer),
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
