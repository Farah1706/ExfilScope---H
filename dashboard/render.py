"""HTML fragments for the investigation views, built only from validated snapshot records.

Every value is escaped before it reaches markup; nothing here reads files or evidence stores.
"""

from collections import Counter
from html import escape

from .evidence import SCENARIOS, absence_explanation, comparison, utc
from .icons import icon, mask_url, stylesheet

# Outcome -> (CSS class, label, icon). The icon shape differs per outcome, so colour is never
# the only cue.
STYLE = {"MATCH": ("match", "Match", "match"), "MISMATCH": ("mismatch", "Mismatch", "mismatch"),
         "UNVERIFIED": ("unverified", "Unverified", "unverified")}
FINDINGS = {
    "BLOCK_BYPASS": "A request the gateway blocked was observed leaving through the proxy.",
    "DESTINATION_DIVERGENCE": "The request went to a different destination than the gateway permitted.",
    "PAYLOAD_DIVERGENCE": "The observed body differs from the body the gateway permitted.",
    "METHOD_ROUTE_DIVERGENCE": "The observed method or route differs from what was permitted.",
    "CLAIM_INCONSISTENCY": "The runtime reported that it sent nothing, yet a request was observed.",
}
SHORT_FINDINGS = {"BLOCK_BYPASS": "Blocked request left", "DESTINATION_DIVERGENCE": "Destination differs",
                  "PAYLOAD_DIVERGENCE": "Body differs", "METHOD_ROUTE_DIVERGENCE": "Method or route differs",
                  "CLAIM_INCONSISTENCY": "Runtime report contradicts observation"}
DIAGNOSTICS = {
    "SCOPED_PROXY_ABSENCE": "No matching request reached the monitored proxy during the window.",
    "NO_UNIQUE_CORRELATED_OBSERVATION": "No single observation could be matched to this event.",
    "MISSING_OR_DUPLICATE_REQUEST_EVIDENCE": "The proxy's receipts and the evidence given to the verifier disagree.",
    "HOST_HEADER_MISMATCH": "The request's Host header named a different endpoint than its real target.",
    "COLLECTION_HEALTH_GAP": "The proxy's health log has a gap inside the window.",
    "MISSING_CLOSING_BARRIER": "The proxy never confirmed that the window was fully recorded.",
    "INCOMPATIBLE_CLOCK_DOMAIN": "The records do not share one clock, so their timing cannot be compared.",
    "UNRECEIPTED_OBSERVATION": "An observation has no matching receipt in the proxy's health log.",
}
# Short display names for diagnostic codes; the exact codes stay in the technical view.
DIAGNOSTIC_NAMES = {"SCOPED_PROXY_ABSENCE": "Nothing seen at proxy",
                    "NO_UNIQUE_CORRELATED_OBSERVATION": "No single matching observation",
                    "MISSING_OR_DUPLICATE_REQUEST_EVIDENCE": "Receipts disagree with evidence"}
CLAIMS = {"EXECUTED_SUCCESS": "Sent", "EXECUTED_FAILED": "Send failed", "NOT_EXECUTED": "Not sent"}
# evidence.comparison() states -> short wording on the reconciliation seam.
CHECKS = {"Compatible with observed emission": "Consistent",
          "Incompatible with observed emission": "Contradicts", "No permitted request": "Nothing permitted"}


def e(value) -> str:
    return escape(str(value), quote=True)


def short(digest: str | None) -> str:
    return f"{digest[:10]}…{digest[-6:]}" if digest else "—"


def humanize(code: str) -> str:
    return code.replace("_", " ").capitalize().replace(" json", " JSON")


def badge(result: str, size: str = "") -> str:
    css, label, glyph = STYLE[result]
    return f'<span class="xs-status {css} {size}">{icon(glyph, 15 if not size else 20)}{e(label)}</span>'


def section(title: str, glyph: str, note: str = "") -> str:
    aside = f'<span class="xs-section-note">{e(note)}</span>' if note else ""
    return f'<h2 class="xs-section">{icon(glyph, 17)}<span>{e(title)}</span>{aside}</h2>'


def seal(digest: str | None, empty: str = "None") -> str:
    """A body fingerprint (keyed HMAC commitment); a pale highlight marks fingerprints everywhere."""
    if not digest:
        return f'<span class="xs-seal empty">{e(empty)}</span>'
    return (f'<span class="xs-seal" title="HMAC-SHA-256 {e(digest)}">{icon("key", 13)}'
            f'<code>{e(short(digest))}</code></span>')


def scoped_absence(i) -> bool:
    """Absence may be stated only when the verifier itself concluded SCOPED_PROXY_ABSENCE.

    An empty pairing also follows duplicate, unreceipted or clock-incompatible observations,
    so "nothing matched" must never be shown as "nothing was seen".
    """
    v = i.verification
    return (i.runtime.decision == "BLOCK" and v.result == "MATCH"
            and "SCOPED_PROXY_ABSENCE" in v.diagnostics)


def verdict_sentence(i) -> str:
    v = i.verification
    if v.result == "MISMATCH":
        return " ".join(FINDINGS.get(label, label) for label in v.labels
                        if label != "NO_CORRELATED_OBSERVATION")
    if v.result == "MATCH":
        if i.runtime.decision == "BLOCK":
            return "Nothing carrying this trace reached the monitored proxy while monitoring was complete."
        return "The request seen at the proxy agrees with what the gateway permitted."
    if i.observation_withheld:
        return "The verifier had no usable observation to compare, so it cannot decide."
    return "The available evidence cannot establish agreement or divergence."


def finding(row) -> str:
    """One-line finding for a scenario row of the outcome matrix."""
    v = row[0].verification
    if v.result == "MISMATCH":
        return ", ".join(SHORT_FINDINGS.get(x, humanize(x)) for x in v.labels)
    if v.result == "UNVERIFIED":
        return "Evidence gap"
    return "Nothing seen at proxy" if row[0].runtime.decision == "BLOCK" else "Agrees"


def _mark(state: str) -> str:
    if state in ("Agrees", "Equal", "Compatible with observed emission"):
        return "agree"
    if state in ("Diverges", "Different", "Incompatible with observed emission"):
        return "differ"
    return "na"


# Shared chrome ----------------------------------------------------------------------------

def brand() -> str:
    # Two ledgers joined at a seam: the mark is drawn in CSS (.xs-mark).
    return ('<div class="xs-brand"><span class="xs-mark" aria-hidden="true"><i></i><b></b><i></i></span>'
            '<span>ExfilScope</span></div>')


def page_header(title: str, summary: str = "") -> str:
    body = f'<p class="xs-lede">{e(summary)}</p>' if summary else ""
    return f'<header class="xs-header"><h1 class="xs-title">{e(title)}</h1>{body}</header>'


def widget_css() -> str:
    """Icons on Streamlit widgets, drawn with CSS masks so they inherit the widget's text colour."""
    rules = [f'[class*="st-key-cell_{css}"] button::before, [class*="st-key-inc_{css}"] button::before '
             f'{{ -webkit-mask-image: {mask_url(glyph)}; mask-image: {mask_url(glyph)}; }}'
             for css, _, glyph in STYLE.values()]
    for n, glyph in enumerate(["cases", "incident", "method"], 1):
        rules.append(f'.st-key-page button:nth-of-type({n})::before {{ -webkit-mask-image: '
                     f'{mask_url(glyph)}; mask-image: {mask_url(glyph)}; }}')
    rules.append(f'[class*="st-key-export"] button::before {{ -webkit-mask-image: {mask_url("export")}; '
                 f'mask-image: {mask_url("export")}; }}')
    return stylesheet() + "\n" + "\n".join(rules)


# Cases --------------------------------------------------------------------------------------

def overview(records) -> str:
    """Counts of these records only, drawn as one proportional band. Not accuracy metrics."""
    total = len(records)
    outcomes = Counter(i.verification.result for i in records)
    decisions = Counter(i.runtime.decision for i in records)
    protocols = Counter(i.protocol.upper() for i in records)
    segments = "".join(
        f'<div class="xs-seg {css}" style="flex-grow:{outcomes[r]}" title="{e(label)}: {outcomes[r]} of {total}">'
        f'{icon(glyph, 16)}<b>{outcomes[r]}</b><span>{e(label)}</span></div>'
        for r, (css, label, glyph) in STYLE.items() if outcomes.get(r))
    zero = [STYLE[r][1].lower() for r in STYLE if not outcomes.get(r)]
    absent = f'<p class="xs-zero">No {" or ".join(zero)} results in this set.</p>' if zero else ""
    label = ", ".join(f"{outcomes[r]} {STYLE[r][1].lower()}" for r in STYLE if outcomes.get(r))
    chips = "".join(f'<span class="xs-fact">{e(n)} <b>{c}</b></span>'
                    for n, c in [*[(d, decisions[d]) for d in ("ALLOW", "REDACT", "BLOCK") if decisions.get(d)],
                                 *sorted(protocols.items())])
    return (f'<section class="xs-overview" aria-label="Outcome counts">'
            f'<div class="xs-total"><b>{total}</b><span>incidents</span></div>'
            f'<div class="xs-overview-main">'
            f'<div class="xs-band" role="img" aria-label="{e(label)} of {total} incidents">{segments}</div>'
            f'{absent}<div class="xs-facts">{chips}</div></div>'
            f'<p class="xs-caveat">{icon("info", 13)}Counts of recorded engineering runs, not accuracy '
            f'or research results.</p></section>')


def outcome_guide() -> str:
    rows = [("MATCH", "What the proxy saw agrees with what the gateway permitted. For a BLOCK: "
                      "nothing reached the monitored proxy during the window."),
            ("MISMATCH", "What the proxy saw differs from what was permitted."),
            ("UNVERIFIED", "Not enough evidence to decide. A gap, never a violation and never a match.")]
    items = "".join(f'<div class="xs-guide-item {STYLE[r][0]}"><dt>{badge(r)}</dt><dd>{e(text)}</dd></div>'
                    for r, text in rows)
    return f'<dl class="xs-guide" aria-label="What the outcomes mean">{items}</dl>'


# Incident -------------------------------------------------------------------------------------

def incident_header(i) -> str:
    a = i.runtime
    return f"""
<header class="xs-header xs-incident-head">
  <h1 class="xs-title">{e(SCENARIOS[i.scenario])}</h1>
  <div class="xs-meta">
    <span class="xs-tag">{icon(i.protocol, 13)}{e(i.protocol.upper())}</span>
    <span class="xs-tag decision">{icon("gateway", 13)}{e(a.decision)}</span>
    <span class="xs-tag">{e(i.origin)}</span>
    <span class="xs-id"><span>Trace</span><code>{e(a.trace_id)}</code></span>
  </div>
</header>"""


def _agreement(i) -> str:
    """How many ledger comparisons agree, or why there was nothing to compare."""
    if not i.observation:
        if scoped_absence(i):
            return "Blocked at the gateway; nothing reached the monitored proxy"
        return "No observation was matched, so no fields were compared"
    marks = [_mark(s) for s in comparison(i).values()]
    compared = [m for m in marks if m != "na"]
    agree = compared.count("agree")
    return f"{agree} of {len(compared)} compared fields agree"


def verdict(i) -> str:
    v = i.verification
    css, label, glyph = STYLE[v.result]
    return f"""
<section class="xs-verdict {css}" aria-label="Verdict">
  <div class="xs-verdict-mark">{icon(glyph, 34)}<span>{e(label)}</span></div>
  <div class="xs-verdict-body">
    <p class="xs-verdict-text">{e(verdict_sentence(i))}</p>
    <p class="xs-verdict-sub">{e(_agreement(i))}</p>
  </div>
</section>"""


def _row(key: str, value: str, flag: str = "") -> str:
    return f'<div class="xs-kv {flag}"><dt>{e(key)}</dt><dd>{value}</dd></div>'


def _request(m) -> str:
    return f"<code>{e(m.method)} {e(m.endpoint_id)} /{e(m.route_id)}</code>"


def flow(i) -> str:
    """Permitted -> runtime report -> proxy observation -> verdict, each tagged with its record."""
    a, b, v = i.runtime, i.observation, i.verification
    differs = {k for k, s in comparison(i).items() if _mark(s) == "differ"}
    p = a.permitted
    hits = f"{len(a.hits)} found, recorded by ID only" if a.hits else "None found"
    permitted = "".join([
        _row("Decision", f'<b>{e(a.decision)}</b> <span class="xs-soft">{e(humanize(a.reason))}</span>'),
        _row("Protected values", e(hits)),
        _row("Allowed to send", _request(p) if p else "Nothing"),
    ])
    detail = (f"HTTP {a.response_status}" if a.claim == "EXECUTED_SUCCESS" and a.response_status
              else e(a.error_category or "Error") if a.claim == "EXECUTED_FAILED" else "No request made")
    claimed = "".join([
        _row("Reported", f"<b>{e(CLAIMS[a.claim])}</b>", "differ" if "Runtime claim" in differs else ""),
        _row("Response", e(detail)),
    ])
    if b:
        offset = b.request_monotonic - a.decision_monotonic
        observed_icon, observed_state = "observe", ""
        observed = "".join([
            _row("Request", _request(b.observed),
                 "differ" if differs & {"Destination", "Method / route"} else ""),
            _row("Seen", f"{offset:.3f} s after the decision"),
        ])
    elif i.observation_withheld:
        observed_icon, observed_state = "withheld", "gap"
        observed = ('<p class="xs-empty">Withheld. The test harness kept the real request out of the '
                    'evidence given to the verifier, so there is nothing to compare.</p>')
    elif scoped_absence(i):
        observed_icon, observed_state = "observe", "absent"
        observed = ('<p class="xs-empty">No request with this trace was seen at this proxy during the '
                    'window. That covers this proxy only, not every route off the host.</p>')
    else:
        observed_icon, observed_state = "observe", "gap"
        observed = ('<p class="xs-empty">The verifier matched no observation to this event. That does '
                    'not show that nothing was sent; the evidence notes say why.</p>')
    findings = ", ".join(SHORT_FINDINGS[x] for x in v.labels if x in SHORT_FINDINGS)
    if not findings:
        findings = ("Evidence gap" if v.result == "UNVERIFIED" else
                    DIAGNOSTIC_NAMES["SCOPED_PROXY_ABSENCE"] if "SCOPED_PROXY_ABSENCE" in v.diagnostics
                    else "No difference found")
    gaps = "<br>".join(e(DIAGNOSTIC_NAMES.get(d, humanize(d))) for d in v.diagnostics
                       if d != "SCOPED_PROXY_ABSENCE")
    concluded = _row("Result", badge(v.result)) + _row("Finding", e(findings))
    if gaps:
        concluded += _row("Evidence notes", gaps)
    stages = [
        ("gateway", "Permitted", "Gateway, Ledger A", permitted, ""),
        ("claim", "Runtime report", "Runtime, Ledger A", claimed, ""),
        (observed_icon, "Observed", "Proxy, Ledger B", observed, observed_state),
        ("verdict", "Verdict", "Verifier", concluded, STYLE[v.result][0]),
    ]
    link = {"MATCH": "ok", "MISMATCH": "broken", "UNVERIFIED": "gap"}[v.result]
    out = []
    for n, (glyph, title, source, body, state) in enumerate(stages):
        if n:
            out.append(f'<div class="xs-link {link if n >= 2 else "ok"}" aria-hidden="true"><span></span></div>')
        out.append(f'<article class="xs-stage {state}"><header><span class="xs-stage-icon">{icon(glyph, 18)}'
                   f'</span><div><h3>{e(title)}</h3><p>{e(source)}</p></div></header><dl>{body}</dl></article>')
    return f'<div class="xs-flow" aria-label="Evidence path">{"".join(out)}</div>'


def ledger(i) -> str:
    """The reconciliation seam: Ledger A on the left, Ledger B on the right, the check on the spine."""
    a, b = i.runtime, i.observation
    status = comparison(i)
    p = a.permitted
    scheme_a = f"{a.key_id} / {a.canonicalization_version}"
    scheme_b = f"{b.key_id} / {b.canonicalization_version}" if b else None
    rows = [
        ("Destination", f"<code>{e(p.endpoint_id)}</code>" if p else "Nothing permitted",
         f"<code>{e(b.observed.endpoint_id)}</code>" if b else "—", status["Destination"]),
        ("Method and route", f"<code>{e(p.method)} /{e(p.route_id)}</code>" if p else "—",
         f"<code>{e(b.observed.method)} /{e(b.observed.route_id)}</code>" if b else "—",
         status["Method / route"]),
        ("Body fingerprint", seal(a.payload_hmac), seal(b.payload_hmac) if b else "—",
         status["Payload commitment"]),
        ("Runtime report", e(CLAIMS[a.claim]), e("Request seen") if b else "Nothing matched",
         status["Runtime claim"]),
        ("Fingerprint key and format", f"<code>{e(scheme_a)}</code>", f"<code>{e(scheme_b)}</code>" if b else "—",
         "Agrees" if b and scheme_a == scheme_b else "Diverges" if b else "Unavailable"),
    ]
    body = ""
    for name, left, right, state in rows:
        css = _mark(state)
        body += (f'<div class="xs-seam-row {css}" role="row">'
                 f'<div class="xs-seam-a" role="cell">{left}</div>'
                 f'<div class="xs-seam-mid" role="rowheader"><span class="xs-seam-dot">{icon(css, 14)}</span>'
                 f'<b>{e(name)}</b><span class="xs-cmp {css}">{e(CHECKS.get(state, state))}</span></div>'
                 f'<div class="xs-seam-b" role="cell">{right}</div></div>')
    note = ("Compared only after the verifier matched the two records." if b else
            "The verifier matched no observation, so Ledger B has nothing to compare.")
    return f"""
<div class="xs-seam" role="table" aria-label="Ledger A and Ledger B comparison">
  <div class="xs-seam-head" role="row">
    <div class="xs-seam-a" role="columnheader">{icon("ledger", 15)}<b>Ledger A</b><span>gateway and runtime</span></div>
    <div class="xs-seam-mid" role="columnheader">Check</div>
    <div class="xs-seam-b" role="columnheader">{icon("ledger", 15)}<b>Ledger B</b><span>independent proxy</span></div>
  </div>{body}
</div><p class="xs-note">{e(note)}</p>"""


def ledger_a(i) -> str:
    """Everything Ledger A records about this event, in reading order."""
    a = i.runtime
    p = a.permitted
    hits = "".join(f'<span class="xs-chip">{e(h.protected_id)} <span>{e(humanize(h.data_type))}</span></span>'
                   for h in a.hits) or '<span class="xs-soft">None found</span>'
    detail = (f"HTTP {a.response_status}" if a.claim == "EXECUTED_SUCCESS" and a.response_status
              else e(a.error_category or "Error") if a.claim == "EXECUTED_FAILED" else "No request made")
    gateway = "".join([
        _row("Agent asked for", _request(a.proposed)),
        _row("Decision", f'<b>{e(a.decision)}</b> <span class="xs-soft">{e(humanize(a.reason))}</span>'),
        _row("Protected values", hits),
        _row("Allowed to send", _request(p) if p else "Nothing"),
        _row("Body fingerprint", seal(a.payload_hmac, "None, nothing allowed")),
        _row("Policy", f"<code>{e(a.policy_version)}</code>"),
        _row("Decided", e(utc(a.decision_time))),
    ])
    runtime = "".join([
        _row("Reported", f"<b>{e(CLAIMS[a.claim])}</b>"),
        _row("Response", e(detail)),
        _row("Finished", e(utc(a.completion_time))),
    ])
    return (f'<div class="xs-records">'
            f'<article class="xs-record"><h3>{icon("gateway", 16)}Gateway decision</h3><dl>{gateway}</dl></article>'
            f'<article class="xs-record"><h3>{icon("claim", 16)}Runtime report</h3><dl>{runtime}</dl></article>'
            f'</div>')


def ledger_b(i) -> str:
    """What the independent proxy recorded, or why there is nothing to show."""
    b = i.observation
    health = (f"{i.health_records} records from {i.monitor_generations} monitor run"
              f"{'s' if i.monitor_generations != 1 else ''}")
    monitor = _row("Proxy health log", e(health))
    if b:
        anomalies = ", ".join(humanize(x) for x in b.anomalies) or "None"
        observed = "".join([
            _row("Request", _request(b.observed)),
            _row("Body fingerprint", seal(b.payload_hmac)),
            _row("Size", f"{b.request_size:,} bytes"),
            _row("Response", e(f"HTTP {b.response_status}" if b.response_status is not None else "None recorded")),
            _row("Anomalies", e(anomalies)),
            _row("Seen", e(utc(b.request_time))),
        ])
        return (f'<div class="xs-records">'
                f'<article class="xs-record"><h3>{icon("observe", 16)}Observed request</h3><dl>{observed}</dl></article>'
                f'<article class="xs-record"><h3>{icon("coverage", 16)}Monitoring</h3><dl>{monitor}</dl></article>'
                f'</div>')
    if i.observation_withheld:
        text = ("The test harness withheld the real observation from the verifier. The original "
                "monitor ledger keeps it, but this snapshot does not restore it.")
    elif scoped_absence(i):
        text = "The proxy recorded no request carrying this trace during the window."
    else:
        text = "The verifier matched no observation to this event, so none is shown."
    return (f'<div class="xs-records">'
            f'<article class="xs-record empty"><h3>{icon("observe", 16)}Observed request</h3>'
            f'<p class="xs-empty">{e(text)}</p></article>'
            f'<article class="xs-record"><h3>{icon("coverage", 16)}Monitoring</h3><dl>{monitor}</dl></article>'
            f'</div>')


def window(i) -> str:
    a, b, w = i.runtime, i.observation, i.window_seconds
    if b:
        delta = b.request_monotonic - a.decision_monotonic
        position = min(max(delta / w, 0), 1) * 100
        marker = (f'<span class="xs-tl-hit" style="left:{position:.2f}%"></span>'
                  f'<span class="xs-tl-label" style="left:{position:.2f}%">seen +{delta:.3f} s</span>')
        caption = f"Seen {delta:.3f} s after the gateway decision, inside the {w:g} s window."
        track = "seen"
    elif i.observation_withheld:
        marker, track = "", "gap"
        caption = "Withheld from the verifier, so nothing is placed in the window."
    elif scoped_absence(i):
        marker, track = "", "empty"
        caption = f"Nothing with this trace was seen at the proxy during the {w:g} s window."
    else:
        marker, track = "", "gap"
        caption = "No observation was matched to this event, so nothing is placed in the window."
    return f"""
<div class="xs-panel">
  {section("Observation window", "window")}
  <div class="xs-tl {track}" role="img" aria-label="{e(caption)}">
    <span class="xs-tl-track"></span><span class="xs-tl-t0"></span>{marker}
    <div class="xs-tl-scale"><span>Gateway decision</span><span>{w:g} s</span></div>
  </div>
  <p class="xs-note">{e(caption)}</p>
</div>"""


def completeness(i) -> str:
    """Facts the snapshot records about evidence completeness; it holds no separate health verdict."""
    a, b, v = i.runtime, i.observation, i.verification
    if b:
        pair = ("agree", "Matched to one observation", "Same trace and clock, inside the window")
    elif i.observation_withheld:
        pair = ("differ", "No observation to match", "Withheld from the verifier")
    elif a.decision == "BLOCK" and v.result == "MATCH":
        pair = ("na", "No observation expected", "Blocked, and the runtime reports nothing sent")
    else:
        pair = ("differ", "No observation to match", "The verifier matched none")
    scheme = (("agree", "Fingerprints comparable", "Same key and format")
              if b and (a.key_id, a.canonicalization_version) == (b.key_id, b.canonicalization_version)
              else ("na", "Fingerprints not compared", "No matched observation") if not b
              else ("differ", "Fingerprints not comparable", "Key or format differs"))
    journal = ("agree" if i.health_records else "differ", "Proxy health log present",
               f"{i.health_records} records, {i.monitor_generations} monitor run"
               f"{'s' if i.monitor_generations != 1 else ''}")
    gaps = [d for d in v.diagnostics if d != "SCOPED_PROXY_ABSENCE"]
    raised = (("differ", "Evidence problems reported", ", ".join(DIAGNOSTIC_NAMES.get(d, humanize(d)) for d in gaps))
              if gaps else ("agree", "No monitoring gaps reported", "For this window"))
    status = ("agree", "Evidence complete", "No open issues") if v.evidence_status == "VERIFIED" else \
        ("differ", "Evidence incomplete", "At least one issue remains")
    items = "".join(f'<li class="{css}">{icon(css, 14)}<div><b>{e(title)}</b><span>{e(note)}</span></div></li>'
                    for css, title, note in (pair, scheme, journal, raised, status))
    return f'<div class="xs-panel">{section("Evidence completeness", "coverage")}<ul class="xs-checks">{items}</ul></div>'


def timing(i) -> str:
    return f'<div class="xs-split">{window(i)}{completeness(i)}</div>'


def reasoning(i) -> str:
    """Why the verdict holds, and what it does not establish. The verdict sentence is not repeated."""
    why, limits = reasoning_items(i)
    items = "".join(f"<li>{e(x)}</li>" for x in why)
    caveats = "".join(f"<li>{e(x)}</li>" for x in limits)
    return f"""
<div class="xs-notes">
  <section class="why">{section("Why this verdict", "info")}<ol>{items}</ol></section>
  <section class="limits">{section("What it does not prove", "limits")}<ul>{caveats}</ul></section>
</div>"""


def reasoning_items(i) -> tuple[list[str], list[str]]:
    """Plain-text reasons and limits, shared by this view and the unified platform."""
    a, b, v = i.runtime, i.observation, i.verification
    trace = str(a.trace_id)[:8]
    why = []
    if b:
        delta = b.request_monotonic - a.decision_monotonic
        why.append(f"Exactly one request with trace {trace} was seen, {delta:.3f} s after the decision.")
    elif i.observation_withheld:
        why.append("A request was seen, but the test harness withheld it from the verifier, so there "
                   "was nothing to match.")
    elif scoped_absence(i):
        why.append(f"No request with trace {trace} was seen at the proxy during the "
                   f"{i.window_seconds:g} s window.")
    else:
        why.append(f"The verifier matched no observation to trace {trace}.")
    if b:
        names = {"Destination": "destination", "Method / route": "method and route",
                 "Payload commitment": "body fingerprint", "Runtime claim": "runtime report"}
        marks = {k: _mark(s) for k, s in comparison(i).items()}
        for state, verb in (("differ", "differ"), ("agree", "agree")):
            fields = [names[k] for k, m in marks.items() if m == state]
            if fields:
                listed = fields[0] if len(fields) == 1 else ", ".join(fields[:-1]) + " and " + fields[-1]
                why.append(f"The {listed} {verb}{'s' if len(fields) == 1 else ''} between the two ledgers.")
    why += [DIAGNOSTICS.get(code, humanize(code)) for code in v.diagnostics
            if code != "SCOPED_PROXY_ABSENCE"]
    limits = [absence_explanation(i)]
    if a.payload_hmac:
        limits.append("A fingerprint only shows whether two bodies are identical. It reveals nothing "
                      "about their content and cannot show which value changed.")
    return why, limits


def incident(i) -> str:
    """The full incident as one fragment (used by tests and exports of the whole view)."""
    return (incident_header(i) + verdict(i) + flow(i) + ledger(i) + ledger_a(i) + ledger_b(i)
            + timing(i) + reasoning(i))


def technical(i) -> str:
    """Full identifiers, codes and fingerprints for the technical view."""
    a, b, v = i.runtime, i.observation, i.verification

    def block(title, rows):
        body = "".join(f"<div><dt>{e(k)}</dt><dd><code>{e(val)}</code></dd></div>" for k, val in rows)
        return f'<section><h4>{e(title)}</h4><dl class="xs-tech">{body}</dl></section>'

    runtime = [("event_id", a.event_id), ("trace_id", a.trace_id), ("session_id", a.session_id),
               ("policy_version", a.policy_version), ("reason", a.reason),
               ("payload_hmac", a.payload_hmac or "null"), ("key_id", a.key_id),
               ("canonicalization", a.canonicalization_version), ("claim", a.claim),
               ("response_status", a.response_status if a.response_status is not None else "null"),
               ("decision_time", utc(a.decision_time)), ("decision_monotonic", f"{a.decision_monotonic:.6f}"),
               ("host_id", a.host_id), ("clock_domain_id", a.clock_domain_id)]
    runtime += [(f"hit {n}", f"{h.protected_id} {h.data_type} {h.source_ref} {h.location}")
                for n, h in enumerate(a.hits, 1)]
    if b:
        network = [("event_id", b.event_id), ("trace_id", b.trace_id), ("payload_hmac", b.payload_hmac or "null"),
                   ("key_id", b.key_id), ("canonicalization", b.canonicalization_version),
                   ("request_size", b.request_size),
                   ("response_status", b.response_status if b.response_status is not None else "null"),
                   ("request_time", utc(b.request_time)), ("request_monotonic", f"{b.request_monotonic:.6f}"),
                   ("anomalies", ", ".join(b.anomalies) or "none"), ("host_id", b.host_id),
                   ("clock_domain_id", b.clock_domain_id)]
    else:
        network = [("observation", "withheld from verifier view" if i.observation_withheld else "none paired")]
    result = [("runtime_event_id", v.runtime_event_id), ("network_event_id", v.network_event_id or "null"),
              ("result", v.result), ("evidence_status", v.evidence_status),
              ("labels", ", ".join(v.labels) or "none"), ("diagnostics", ", ".join(v.diagnostics) or "none"),
              ("run_id", i.run_id), ("window_seconds", f"{i.window_seconds:g}"),
              ("monitor_health_records", i.health_records), ("monitor_runs", i.monitor_generations)]
    return (f'<div class="xs-techgrid">{block("Ledger A runtime event", runtime)}'
            f'{block("Ledger B network event", network)}{block("Verifier result", result)}</div>')


# Method ---------------------------------------------------------------------------------------

# Grid areas of the architecture diagram. Row 1 is the request path; w* are evidence writes into
# the ledgers below; r* are the verifier's reads. The CSS grid-template-areas must place every
# write stub under both its writer and its ledger, and every read stub under its ledger and over
# the verifier (dashboard/tests/test_app.py checks this).
ARCHITECTURE_WRITES = {"w1": ("gw", "la"), "w2": ("wr", "la"), "w3": ("px", "lb")}
ARCHITECTURE_READS = {"r1": ("la", "vf"), "r2": ("lb", "vf")}
ARCHITECTURE_PATH = ["ag", "a1", "gw", "a2", "wr", "a3", "px", "a4", "ep"]


def architecture() -> str:
    """Component diagram as a CSS grid: solid arrows follow the request, dashed arrows are
    evidence writes and teal arrows are the verifier reading both ledgers."""
    def node(area, glyph, title, sub, css=""):
        return (f'<div class="xs-node {css}" style="grid-area:{area}">{icon(glyph, 18)}'
                f'<div><b>{e(title)}</b><span>{e(sub)}</span></div></div>')
    cells = [node("ag", "agent", "Agent", "Qwen3; calls POST /execute"),
             node("gw", "gateway", "Gateway", "ALLOW, REDACT or BLOCK", "accent"),
             node("wr", "send", "Tool runtime", "sends what was allowed"),
             node("px", "proxy", "Proxy monitor", "independent observer"),
             node("ep", "endpoint", "Lab endpoint", "HTTP or HTTPS"),
             node("la", "ledger", "Ledger A", "decision and runtime report"),
             node("lb", "ledger", "Ledger B", "observation and proxy health"),
             node("vf", "verdict", "Verifier", "matches records by trace ID and time window", "accent")]
    cells += [f'<span class="xs-arrow" style="grid-area:{a}"></span>' for a in ("a1", "a2", "a3", "a4")]
    cells += [f'<span class="xs-stub write" style="grid-area:{a}"></span>' for a in ARCHITECTURE_WRITES]
    cells += [f'<span class="xs-stub read" style="grid-area:{a}"></span>' for a in ARCHITECTURE_READS]
    return (f'<figure class="xs-arch" role="img" aria-label="The agent calls the gateway, which passes '
            f'allowed requests to the tool runtime, then through the proxy monitor to the lab endpoint. '
            f'The gateway and tool runtime write Ledger A, the proxy writes Ledger B, and the verifier '
            f'reads both ledgers."><div class="xs-arch-scroll"><div class="xs-arch-grid">{"".join(cells)}'
            f'</div></div><figcaption><span><i class="solid"></i>Request path</span><span><i class="dashed">'
            f'</i>Writes evidence</span><span><i class="read"></i>Verifier reads</span>'
            f'<span class="xs-arch-hint">Scroll sideways for the full diagram</span></figcaption></figure>')


STAGES = [
    ("agent", "Agent asks", "The agent requests one JSON HTTP action through its single tool."),
    ("gateway", "Gateway decides", "A fixed, versioned policy allows, redacts or blocks it. Protected values "
                                   "are recorded by ID, never by value."),
    ("key", "Ledger A records", "The decision and a fingerprint of the allowed body are written before "
                                "anything is sent."),
    ("send", "Runtime sends", "Only the allowed request is sent, through the proxy. The runtime records "
                              "what it says it did."),
    ("observe", "Proxy observes", "A separate proxy fingerprints the body it actually saw and writes "
                                  "Ledger B and a health log."),
    ("verdict", "Verifier compares", "Records are matched by trace ID and time window, then destination, "
                                     "route, fingerprint and runtime report are compared."),
]


def method() -> str:
    steps = "".join(f'<li><span class="xs-step-icon">{icon(glyph, 18)}</span><div><h3>{e(title)}</h3>'
                    f'<p>{e(text)}</p></div></li>' for glyph, title, text in STAGES)
    outcomes = "".join(
        f'<div class="xs-outcome {STYLE[r][0]}">{badge(r)}<p>{e(t)}</p></div>' for r, t in [
            ("MATCH", "Enough usable evidence agrees with the permitted action."),
            ("MISMATCH", "Usable evidence shows at least one supported difference."),
            ("UNVERIFIED", "The evidence cannot establish agreement or a difference.")])
    return f"""
<p class="xs-lede">A gateway decides what an AI agent's single HTTP tool may send, and an independent proxy
records what actually leaves. Each writes its own privacy-minimized ledger; the verifier compares the two.</p>
{section("Architecture", "proxy")}{architecture()}
{section("Six steps", "cases")}<ol class="xs-steps">{steps}</ol>
{section("Three outcomes", "verdict")}<div class="xs-outcomes">{outcomes}</div>
{section("Body fingerprints", "key")}
<div class="xs-formula">
  <div class="xs-eq"><code>H(b) = HMAC-SHA-256(K, C(b))</code></div>
  <p>A fingerprint is a keyed HMAC commitment. <code>C(b)</code> is the RFC 8785 canonical encoding of the
  JSON body and <code>K</code> is a random 256-bit key kept outside the ledgers. The gateway fingerprints
  the body it allows; the proxy fingerprints the body it sees and never accepts a supplied value. They are
  compared only when key and format agree.</p>
</div>"""


def pairing_rule() -> str:
    return """
<div class="xs-formula plain"><div class="xs-eq"><code>N(e) = { n : trace(n) = trace(e), same clock domain, 0 ≤ t(n) − t0(e) ≤ W }</code></div>
<p>A match is accepted only when exactly one candidate exists, its trace header appeared exactly once and
its receipt is intact. Destination and body are compared after matching, never used to choose a match.
Unmatched observations are kept for review and never attributed by similarity. Wall-clock times are for
display only.</p></div>"""


def match_conditions() -> str:
    return """
<div class="xs-cols">
<section><h4>ALLOW and REDACT</h4><ul>
<li>a unique valid match;</li><li>equal endpoint, method and route;</li>
<li>equal, comparable fingerprints;</li><li>a runtime report of EXECUTED_SUCCESS or EXECUTED_FAILED;</li>
<li>a complete runtime record;</li><li>a closed window with complete monitoring.</li></ul></section>
<section><h4>BLOCK (SCOPED_PROXY_ABSENCE)</h4><ul>
<li>a complete NOT_EXECUTED record;</li><li>no candidate in the window;</li>
<li>no observation with the same trace at any time, including outside the window;</li>
<li>complete monitoring of the window;</li><li>no unresolved or unattributed traffic in the window.</li></ul>
<p>It means only that no matching request was seen at this proxy hook during W.</p></section>
</div>"""


def coverage_conditions() -> str:
    return """
<ul>
<li>exactly one monitor run spans from START, at or before t0, through a confirmed closing barrier at or after t0 + W, whose next record was committed by t0 + W + G (G is the 1 s drain grace for late commits);</li>
<li>sequences, hash chain and request counts are contiguous and consistent;</li>
<li>boundary, key, canonicalizer, host and clock domain all match;</li>
<li>every in-window observation has exactly one matching receipt, and the watermark reconciles with them;</li>
<li>no record in the window is FAILED, STOPPED or an INCIDENT, and nothing is unresolved at the window edges.</li>
</ul>
<p class="xs-note">The hash chain detects gaps and accidental change by trusted writers. It is not
authenticated custody, and ledgers remain unsigned.</p>"""


def limits() -> str:
    items = [
        "A request seen at the proxy reached the monitored boundary; that does not prove the endpoint processed it.",
        "A BLOCK match means nothing was seen at this proxy during the window, not that the host sent nothing anywhere.",
        "Different fingerprints show that bodies differ, not which value changed or that a secret leaked.",
        "All incidents here are engineering evidence from a local laboratory, not research results.",
    ]
    lis = "".join(f"<li>{icon('limits', 15)}<span>{e(x)}</span></li>" for x in items)
    return f'{section("What a verdict does not claim", "limits")}<ul class="xs-limits">{lis}</ul>'


def provenance_note() -> str:
    return ('<p class="xs-note">This workspace only reads exported, privacy-minimized snapshots. It cannot '
            'change ledgers or run actions. Each snapshot is checked against its SHA-256 manifest before '
            'display; the fingerprints below detect change but do not authenticate who produced the '
            'evidence.</p>')
