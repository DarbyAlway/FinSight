"""Bridge a blocking process_turn into an SSE event stream.

A worker thread runs the turn; its on_stage callback and final answer/error are
pushed onto a queue that the (generator) consumer drains into SSE frames. This
keeps the turn off the request/event-loop thread, so a client disconnect never
kills an in-flight turn.
"""
import json
import queue
import threading
from typing import Iterator

from orchestrator import process_turn

_SENTINEL = object()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream_turn(
    user_input: str,
    history: list[dict],
    persona_system: str | None = None,
    on_answer=None,
) -> Iterator[str]:
    """Yield SSE frames for one turn: zero or more `stage` events, then exactly
    one terminal `answer` or `error`. If on_answer is given it is called with the
    final answer markdown (used by the API to persist the assistant message)."""
    events: "queue.Queue" = queue.Queue()

    def worker():
        try:
            def on_stage(stage, detail=""):
                events.put(("stage", {"stage": stage, "detail": detail}))

            answer, _ = process_turn(
                user_input, history, persona_system=persona_system, on_stage=on_stage
            )
            if on_answer is not None:
                on_answer(answer)
            events.put(("answer", {"markdown": answer}))
        except Exception as exc:  # surface as a terminal error event
            events.put(("error", {"message": str(exc)}))
        finally:
            events.put(_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = events.get()
        if item is _SENTINEL:
            break
        event, data = item
        yield _sse(event, data)
