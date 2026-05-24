import json
import os
from datetime import datetime


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
