"""One bounded graph; raw proposals exist only in a restricted transcript."""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .contracts import parse_proposal


class State(TypedDict, total=False):
    documents: list[dict]
    raw: str
    proposal: dict
    status: str
    event_id: str


def run_agent(retriever, model, tool, query: str, task: str, transcript: Path) -> dict:
    record = {"query": query, "task": task, "documents": [], "raw_proposal": None}

    def save():
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def retrieve(state):
        try:
            docs = retriever.retrieve(query)
            record["documents"] = docs
            save()
            return {"documents": docs, "status": "RETRIEVED"}
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            return {"status": "RETRIEVAL_FAILED"}

    def generate(state):
        try:
            raw = model.generate(task, state["documents"])
            record["raw_proposal"] = raw
            return {"raw": raw, "status": "GENERATED"}
        except Exception as exc:
            record["raw_proposal"] = getattr(exc, "partial_output", None)
            record["error_type"] = type(exc).__name__
            return {"status": "MODEL_FAILED"}
        finally:
            record["model_digest"] = getattr(model, "digest", None)
            save()

    def validate(state):
        try:
            proposal = parse_proposal(state["raw"])
            record["validated_proposal"] = proposal
            return {"proposal": proposal, "status": "VALIDATED"}
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            return {"status": "INVALID_PROPOSAL"}

    def submit(state):
        try:
            result = tool.submit(state["proposal"])
            return {"status": "SUBMITTED", "event_id": result["event_id"]}
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            return {"status": "SUBMISSION_FAILED"}

    graph = StateGraph(State)
    for name, node in [("retrieve", retrieve), ("generate", generate),
                       ("validate", validate), ("submit", submit)]:
        graph.add_node(name, node)
    graph.add_edge(START, "retrieve")
    for name, success, following in [("retrieve", "RETRIEVED", "generate"),
                                     ("generate", "GENERATED", "validate"),
                                     ("validate", "VALIDATED", "submit")]:
        graph.add_conditional_edges(name, lambda s, expected=success: s["status"] == expected,
                                    {True: following, False: END})
    graph.add_edge("submit", END)
    state = graph.compile().invoke({}, config={"recursion_limit": 8})
    summary = {"status": state["status"], "submission_attempts": tool.attempts,
               "event_id": state.get("event_id")}
    record["summary"] = summary
    save()
    return summary
