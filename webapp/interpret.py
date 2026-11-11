"""Browser-facing incident records: the validated snapshot fields plus the dashboard's own
interpretation (comparison states, verdict sentence, reasons and limits)."""

from dashboard.evidence import SCENARIOS, absence_explanation, comparison, utc
from dashboard.render import (CLAIMS, DIAGNOSTICS, FINDINGS, reasoning_items, scoped_absence,
                              verdict_sentence)


# The verifier has one PAYLOAD_DIVERGENCE class; the research separates its two subtypes,
# which the recorded gateway decision distinguishes.
PAYLOAD_SUBTYPES = {"ALLOW": "Payload divergence: body altered after approval",
                    "REDACT": "Payload divergence: original body restored after redaction"}


def title(i) -> str:
    if i.scenario == "payload_divergence":
        return PAYLOAD_SUBTYPES.get(i.runtime.decision, SCENARIOS[i.scenario])
    return SCENARIOS[i.scenario]


def incident_view(i, display_origin: str | None = None) -> dict:
    """``display_origin`` labels a run type the snapshot schema does not name (the trust
    extension); the snapshot's own ``origin`` is kept unchanged alongside it."""
    record = i.model_dump(mode="json")
    a, b = i.runtime, i.observation
    why, limits = reasoning_items(i)
    record.update({
        "identifier": i.identifier,
        "scenario_title": title(i),
        "display_origin": display_origin or i.origin,
        "comparison": comparison(i),
        "verdict_sentence": verdict_sentence(i),
        "why": why, "limits": limits,
        "absence_explanation": absence_explanation(i),
        "scoped_absence": scoped_absence(i),
        "findings": [{"label": x, "text": FINDINGS.get(x, x)}
                     for x in i.verification.labels if x != "NO_CORRELATED_OBSERVATION"],
        "diagnostic_notes": [{"code": d, "text": DIAGNOSTICS.get(d, d)}
                             for d in i.verification.diagnostics],
        "claim_text": CLAIMS.get(a.claim, a.claim),
        "recorded_utc": utc(a.decision_time),
        "completed_utc": utc(a.completion_time),
        "observed_utc": utc(b.request_time) if b else None,
        "observed_offset_s": round(b.request_monotonic - a.decision_monotonic, 6) if b else None,
        "fingerprints_comparable": bool(b) and (a.key_id, a.canonicalization_version) ==
        (b.key_id, b.canonicalization_version),
    })
    return record


def summary(incidents, display_origin: str | None = None) -> dict:
    outcomes = {"MATCH": 0, "MISMATCH": 0, "UNVERIFIED": 0}
    for i in incidents:
        outcomes[i.verification.result] += 1
    return {"total": len(incidents), "outcomes": outcomes,
            "protocols": sorted({i.protocol for i in incidents}),
            "origins": sorted({display_origin or i.origin for i in incidents}),
            "scenarios": sorted({i.scenario for i in incidents})}
