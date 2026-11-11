"""Paired local CPU benchmark, excluding model, network and ledger I/O."""

import argparse
import csv
import json
import math
from pathlib import Path
import platform
import time
from types import SimpleNamespace

import rfc8785

from exfilscope.contracts import ProposedAction
from webapp.trust.capability import AgentIdentity, Issuer, Rejected, Scope, Validator
from webapp.trust.dispatch import ProtectedDispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    allowed = root / "artifacts"
    out = args.out.resolve()
    if allowed not in out.parents:
        parser.error("Output must be a new directory inside this project's artifacts")
    out.mkdir(parents=True, exist_ok=False)
    scope = Scope("notice", "http_post", "AUTHORIZED", "POST", "COLLECT")
    action = {**scope.__dict__, "body": {"data": [{"text": "Synthetic pilot notice"}]}}
    issuer = Issuer()
    identity = AgentIdentity("bench-client")
    validator = Validator(issuer.public_key)
    validator.register(identity.agent_id, identity.public_key)
    lab = SimpleNamespace(allowed_url="http://127.0.0.1:8701/collect",
                          gateway=SimpleNamespace(authorize=lambda proposal: proposal),
                          runtime=SimpleNamespace(execute=lambda authorization: authorization))
    dispatch = ProtectedDispatch(lab, validator, scope)

    def measure(fn):
        started = time.perf_counter_ns()
        fn()
        return time.perf_counter_ns() - started

    def baseline():
        return lab.runtime.execute(lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url, method="POST",
            body=rfc8785.dumps(action["body"]).decode("utf-8"))))

    rows = []
    for i in range(330):
        cap = issuer.issue(identity.agent_id, identity.public_key, scope)
        proof = identity.prove(cap, action)
        validation_cap = issuer.issue(identity.agent_id, identity.public_key, scope)
        validation_proof = identity.prove(validation_cap, action)

        def protected():
            dispatch.execute(cap, proof, action)

        def reject():
            try:
                dispatch.execute(cap, proof, action)
            except Rejected as exc:
                if exc.code == "CAPABILITY_REPLAYED":
                    return
                raise
            raise AssertionError("Replay accepted")

        if i % 2:
            protected_ns, baseline_ns = measure(protected), measure(baseline)
        else:
            baseline_ns, protected_ns = measure(baseline), measure(protected)
        validation_ns = measure(lambda: validator.check(validation_cap, validation_proof, action))
        rejected_ns = measure(reject)
        if i >= 30:
            rows.append({"pair": i - 29, "baseline_ns": baseline_ns, "protected_ns": protected_ns,
                         "delta_ns": protected_ns - baseline_ns, "validation_ns": validation_ns,
                         "replay_rejected_ns": rejected_ns})

    def nearest_rank(values, fraction):
        return round(sorted(values)[math.ceil(len(values) * fraction) - 1] / 1000, 2)

    with (out / "samples.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"system": platform.platform(), "python": platform.python_version(),
               "pairs": len(rows), "warmup": 30, "unit": "microseconds",
               "scope": "single process, mocked gateway and runtime, no model/network/SQLite"}
    for key in list(rows[0])[1:]:
        values = [row[key] for row in rows]
        summary[key.removesuffix("_ns")] = {"p50": nearest_rank(values, 0.5),
                                            "p95": nearest_rank(values, 0.95)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()