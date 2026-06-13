"""Run the API:  python -m webapp   (reads DATABASE_URL from env/.env).

Requires DATABASE_URL pointing at Postgres. Real turns also need Qdrant running
and SEC identity; the app's lifespan warms those unless WEBAPP_SKIP_WARMUP=1.
"""
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit(
            "DATABASE_URL is not set. Example:\n"
            "  set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/finsight"
        )
    uvicorn.run("webapp.app:app", host="127.0.0.1", port=8000, reload=False)
