import json
import os
from datetime import datetime

# Keep test runs out of the production checkpoint store: orchestrator opens
# its SqliteSaver connection at import time, so the env var must be set
# before any test imports it.
os.environ.setdefault("CHECKPOINT_DB", ":memory:")


def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "test": report.nodeid,
            "error": str(report.longrepr),
        }
        log_path = os.path.join(os.path.dirname(__file__), "failure_log.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
