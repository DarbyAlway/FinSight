"""FastAPI backend for the finance chat UI.

CRUD over chats/messages (Postgres) plus an SSE endpoint (next task) that runs a
turn through the orchestrator. No auth in this plan (Plan 4); no ask-back/resume
(Plan 3).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webapp import db
from webapp.turn_runner import stream_turn


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_app_schema()
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


@app.get("/chats")
def list_chats():
    return db.list_chats()


@app.post("/chats")
def create_chat(body: CreateChat):
    return {"id": db.create_chat(title=body.title)}


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    if db.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    db.delete_chat(chat_id)
    return {"ok": True}


@app.post("/chats/{chat_id}/messages")
def send_message(chat_id: str, body: SendMessage):
    """Start a turn for this chat and stream SSE: `stage`* then `answer`/`error`.
    Saves the user message immediately and the assistant message once produced.
    (Resume/ask-back is Plan 3; this always starts a fresh turn.)"""
    if db.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")

    history = db.get_messages(chat_id)
    db.add_message(chat_id, role="user", content=body.content)

    def on_answer(answer: str):
        db.add_message(chat_id, role="assistant", content=answer)

    return StreamingResponse(
        stream_turn(user_input=body.content, history=history, on_answer=on_answer),
        media_type="text/event-stream",
    )
