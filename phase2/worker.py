"""Unprivileged agent entry point; stdin is trusted launcher configuration."""

import json
import os
from pathlib import Path
import sys

from .fixtures import CASES, stub_response


def main():
    os.environ.update(LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false",
                      ANONYMIZED_TELEMETRY="False")
    config = json.load(sys.stdin)
    task = CASES[config["case"]]
    restricted = Path(config["restricted"])
    try:
        from .agent import run_agent
        from .model import LocalModel
        from .rag import Retriever
        from .tool import GatewayTool
        retriever = Retriever(Path(config["documents"]), Path(config["embedding_cache"]))
        if config["mode"] == "stub":
            class Stub:
                def generate(self, task, documents):
                    return stub_response(config["case"], retriever.documents)
            model = Stub()
        else:
            model = LocalModel()
        tool = GatewayTool(config["gateway_url"], config["target_url"], config["session_id"])
        summary = run_agent(retriever, model, tool, task["query"], task["instruction"],
                            restricted / "attempt.json")
    except Exception as exc:
        # No raw exception string: it may contain protected model/input content.
        summary = {"status": "SETUP_FAILED", "submission_attempts": 0,
                   "error_type": type(exc).__name__}
        restricted.mkdir(parents=True, exist_ok=True)
        (restricted / "setup-failure.json").write_text(json.dumps(summary), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
