// Shared visual components, built only from validated API records.
import { h, s, icon, badge, seal, mono, humanize, clear, fill, svgBoxLabel } from "./dom.js";
import { HELP, GUIDE_BY_ID, COMPONENTS, CHECKLIST } from "./content.js";

// ---- Contextual help drawer -----------------------------------------------------------
let lastFocus = null;
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

export function openDrawer(content) {
  const root = document.getElementById("drawer-root");
  const shell = document.querySelector(".shell");
  if (!root.firstChild) lastFocus = document.activeElement;
  clear(root);
  const close = () => {
    clear(root);
    shell.inert = false;
    document.removeEventListener("keydown", onKey, true);
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab") return;
    const items = [...drawer.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!drawer.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey, true);
  const closeBtn = h("button", { class: "btn small close", type: "button", onclick: close, "aria-label": "Close guide" }, icon("close", 14), "Close");
  const drawer = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": "Guide" }, closeBtn, content);
  root.append(h("div", { class: "drawer-backdrop", onclick: close }), drawer);
  shell.inert = true;  // the page behind the dialog cannot be reached by keyboard or pointer
  // Links inside the drawer navigate away, so they close it first.
  for (const link of drawer.querySelectorAll("a[href]")) link.addEventListener("click", close);
  closeBtn.focus();
}

export function helpButton(key) {
  const entry = HELP[key];
  return h("button", { class: "help", type: "button", "aria-label": `Explain: ${entry.title}`, title: `Explain: ${entry.title}`,
    onclick: () => openDrawer(helpContent(key)) }, icon("help", 14));
}

function helpContent(key) {
  const e = HELP[key];
  const guide = GUIDE_BY_ID[e.guide];
  return h("div", null,
    h("h2", null, e.title),
    h("div", { class: "qa" },
      h("div", null, h("h4", null, "What am I looking at?"), h("p", null, e.what)),
      h("div", null, h("h4", null, "Why does it matter?"), h("p", null, e.why)),
      h("div", null, h("h4", null, "What does this result mean?"), h("p", null, e.means)),
      h("div", { class: "mistake" }, h("h4", null, "A common interpretation mistake"), h("p", null, e.mistake))),
    guide ? h("p", { style: { marginTop: "24px" } }, h("a", { href: `#/learn/${guide.id}`,
      onclick: () => clear(document.getElementById("drawer-root")) }, `Read the full guide: ${guide.title}`)) : null);
}

export function guideDrawer(id) {
  const g = GUIDE_BY_ID[id];
  openDrawer(h("div", { class: "guide-body" }, h("p", { class: "muted small" }, `Guide ${g.n} of 20`),
    h("h2", null, g.title), guideBody(g),
    h("p", null, h("a", { href: `#/learn/${g.id}`, onclick: () => clear(document.getElementById("drawer-root")) }, "Open in Help and guides"))));
}

export function guideBody(g) {
  return h("div", null,
    h("div", { class: "simple" }, g.simple.map((p) => h("p", null, p))),
    g.figure ? h("div", { class: "example" }, figure(g.figure)) : null,
    h("details", { class: "more" }, h("summary", null, icon("chevron", 14), "Technical explanation"),
      h("div", { style: { marginTop: "12px" } }, g.technical.map((p) => h("p", null, p)))));
}

function figure(kind) {
  if (kind === "hmac") return hmacExplainer();
  if (kind === "decisions") return decisionsFigure();
  if (kind === "outcomes") return outcomesFigure();
  if (kind === "window") return timelineExample();
  if (kind === "pipeline") return pipelineExample();
  return null;
}

// ---- Architecture diagram -------------------------------------------------------------
const NODES = [
  ["operator", 16, 34, "Human approval", "Approve, stop, restore"],
  ["identity", 188, 34, "Agent identity", "Check who is acting"],
  ["permission", 360, 34, "Task permission", "One approved task"],
  ["official", 532, 34, "Official figures", "Check source and year"],
  ["rag", 16, 150, "Sample documents", "For security tests"],
  ["agent", 188, 150, "AI assistant", "Proposes an action"],
  ["gateway", 360, 150, "Safety check", "Send, remove, or stop"],
  ["tool", 532, 150, "Send request", "Approved content"],
  ["proxy", 704, 150, "Activity monitor", "Independent record"],
  ["endpoint", 876, 150, "Test destination", "Receives the request"],
  ["ledgerA", 446, 264, "Approval record", "Decision and report", "plane-a"],
  ["ledgerB", 704, 264, "Activity record", "What was observed", "plane-b"],
  ["verifier", 575, 370, "Compare records", "Check for differences"],
  ["investigation", 876, 370, "Review result", "Evidence for a person"],
];

export function architecture(onSelect, selected) {
  const W = 150, H = 62;
  const pos = Object.fromEntries(NODES.map(([id, x, y]) => [id, { x, y }]));
  const cx = id => pos[id].x + W / 2;
  const edge = (points, cls = "") => s("path", {
    d: "M" + points.map(p => p.join(" ")).join(" L"),
    class: `edge ${cls}`, "marker-end": "url(#arrow)",
  });
  const right = (a, b) => edge([[pos[a].x + W, pos[a].y + H / 2], [pos[b].x - 4, pos[b].y + H / 2]]);
  const svg = s("svg", { class: "arch", viewBox: "0 0 1042 464", role: "group",
    "aria-label": "ExfilScope architecture: Trust controls, request flow, and independent evidence. Select a component to read about it." },
    s("defs", null, s("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
      s("path", { d: "M0 0 L10 5 L0 10 z", fill: "#6A7586" }))),
    s("text", { class: "zone-label", x: 16, y: 18 }, "GOVERNMENT TRUST CONTROLS"),
    s("text", { class: "zone-label", x: 704, y: 58 }, "Government checks happen"),
    s("text", { class: "zone-label", x: 704, y: 76 }, "before anything is sent."),
    s("line", { class: "arch-divider", x1: 16, y1: 112, x2: 1026, y2: 112 }),
    s("text", { class: "zone-label", x: 16, y: 136 }, "REQUEST FLOW"),
    s("text", { class: "zone-label", x: 188, y: 136 }, "Government example: official GDRFA figures. Security tests: sample documents."),
    right("rag", "agent"), right("agent", "gateway"), right("gateway", "tool"),
    right("tool", "proxy"), right("proxy", "endpoint"),
    s("text", { class: "zone-label", x: 16, y: 254 }, "INDEPENDENT EVIDENCE"),
    edge([[cx("gateway"), 212], [cx("gateway"), 236], [cx("ledgerA") - 30, 236], [cx("ledgerA") - 30, 260]], "evidence"),
    edge([[cx("tool"), 212], [cx("tool"), 236], [cx("ledgerA") + 30, 236], [cx("ledgerA") + 30, 260]], "evidence"),
    edge([[cx("proxy"), 212], [cx("proxy"), 260]], "evidence"),
    edge([[cx("ledgerA"), 326], [cx("ledgerA"), 348], [cx("verifier") - 30, 348], [cx("verifier") - 30, 366]], "evidence"),
    edge([[cx("ledgerB"), 326], [cx("ledgerB"), 348], [cx("verifier") + 30, 348], [cx("verifier") + 30, 366]], "evidence"),
    right("verifier", "investigation"),
  );
  for (const [id, x, y, title, sub, cls] of NODES) {
    const g = s("g", { class: `node ${cls || ""}`, tabindex: 0, role: "button",
      "aria-pressed": String(selected === id), "aria-label": `${title}: ${sub}` },
      s("rect", { x, y, width: W, height: H, rx: 9 }),
      svgBoxLabel(x, y, W, H, title, sub, { compact: true }));
    g.addEventListener("click", () => onSelect(id));
    g.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(id); }
    });
    svg.append(g);
  }
  svg.append(s("text", { class: "zone-label", x: 16, y: 456 },
    "Solid arrows: the request. Dashed arrows: the records used to check it."));
  return svg;
}

export function componentDetail(id) {
  const c = COMPONENTS[id];
  const facts = rows => h("dl", { class: "arch-detail" }, rows.map(([k, v]) =>
    h("div", null, h("dt", null, k), h("dd", null, v))));
  return h("div", null,
    h("div", { class: "spread" }, h("h3", null, c.title), h("span", { class: "tag teal" }, c.plane)),
    facts([["What it is", c.what], ["Why it matters", c.why]]),
    h("details", { class: "component-technical" }, h("summary", null, "Inputs, outputs and technical details"),
      facts([["Receives", c.receives], ["Produces", c.produces], ["Trust boundary", c.trust], ["Role in ExfilScope", c.role]])),
    h("button", { class: "btn ghost", onclick: () => guideDrawer(c.guide) }, "Read guide"));
}

// ---- Evidence pipeline: Proposed → Decided → Permitted → Claimed → Observed → Verified ----
function meta(m) { return m ? `${m.method} ${m.endpoint_id} / ${m.route_id}` : "None"; }

export function pipelineStages(i) {
  const a = i.runtime, b = i.observation, v = i.verification, cmp = i.comparison;
  const divergent = v.result === "MISMATCH";
  return [
    { id: "proposed", k: "Proposed", plane: "Ledger A", cls: "plane-a", v: meta(a.proposed),
      s: a.hits.length ? `${a.hits.length} protected hit${a.hits.length > 1 ? "s" : ""}` : "No protected values",
      detail: () => h("div", null, h("p", null, "What the agent (or the lab case) proposed, as safe metadata. Protected values appear only as registry IDs."),
        kvList([["Endpoint", a.proposed.endpoint_id], ["Method / route", `${a.proposed.method} / ${a.proposed.route_id}`],
          ["Protected hits", a.hits.length ? a.hits.map((x) => `${x.protected_id} (${x.data_type}, ${x.source_ref}) at ${x.location}`).join("; ") : "None"]])) },
    { id: "decided", k: "Decided", plane: "Ledger A", cls: "plane-a", v: a.decision, s: humanize(a.reason),
      detail: () => h("div", null, h("p", null, "The gateway's decision, written to Ledger A before anything was sent."),
        kvList([["Decision", a.decision], ["Reason", a.reason], ["Policy version", a.policy_version], ["Recorded", i.recorded_utc]])) },
    { id: "permitted", k: "Permitted", plane: "Ledger A", cls: "plane-a", v: a.permitted ? meta(a.permitted) : "Nothing permitted",
      s: a.payload_hmac ? "Body fingerprint recorded" : "No body", gap: !a.permitted,
      detail: () => h("div", null, h("p", null, a.permitted ? "The request the gateway allowed out, with an HMAC commitment of its canonical body." : "BLOCK: the gateway permitted no request and recorded no body fingerprint."),
        kvList([["Permitted", meta(a.permitted)], ["Body fingerprint", seal(a.payload_hmac)], ["Key / canonicalization", `${a.key_id} / ${a.canonicalization_version}`]])) },
    { id: "claimed", k: "Claimed", plane: "Ledger A", cls: "plane-a", v: i.claim_text, s: a.claim,
      differ: cmp["Runtime claim"] === "Incompatible with observed emission",
      detail: () => h("div", null, h("p", null, "What the runtime says it did. This is a claim, not an observation."),
        kvList([["Claim", a.claim], ["Error category", a.error_category || "None"], ["Response status", a.response_status ?? "None"], ["Completed", i.completed_utc]])) },
    { id: "observed", k: "Observed", plane: "Ledger B", cls: "plane-b", v: b ? meta(b.observed) : (i.observation_withheld ? "Withheld from verifier" : i.scoped_absence ? "Nothing seen at proxy" : "No paired observation"),
      s: b ? `+${i.observed_offset_s.toFixed(3)} s after decision` : "", gap: !b,
      differ: ["Destination", "Method / route", "Payload commitment"].some((k) => ["Diverges", "Different"].includes(cmp[k])),
      detail: () => h("div", null, h("p", null, b ? "What the independent proxy recorded, with its own fingerprint of the body it received." : i.absence_explanation),
        b ? kvList([["Observed", meta(b.observed)], ["Body fingerprint", seal(b.payload_hmac)], ["Size / status", `${b.request_size} bytes / ${b.response_status ?? "none"}`], ["Anomalies", b.anomalies.join(", ") || "None"], ["Observed", i.observed_utc]]) : null) },
    { id: "verified", k: "Verified", plane: "Verifier", cls: "verdict", v: badge(v.result), s: v.labels.map(humanize).join(", ") || humanize(v.diagnostics[0] || v.evidence_status),
      differ: divergent,
      detail: () => h("div", null, h("p", null, i.verdict_sentence),
        kvList([["Result", v.result], ["Evidence status", v.evidence_status], ["Labels", v.labels.join(", ") || "None"], ["Diagnostics", v.diagnostics.join(", ") || "None"]])) },
  ];
}

export function pipeline(i, { selectedId = null } = {}) {
  const stages = pipelineStages(i);
  const wrap = h("div");
  const detail = h("div", { class: "pdetail", "aria-live": "polite" });
  const row = h("div", { class: "pipeline", role: "group", "aria-label": "Evidence pipeline" });
  const select = (id) => {
    for (const btn of row.querySelectorAll(".pstage")) btn.setAttribute("aria-pressed", String(btn.dataset.id === id));
    const st = stages.find((x) => x.id === id);
    fill(detail, h("div", { class: "spread" }, h("h3", null, st.k), h("span", { class: "tag" }, st.plane)), st.detail());
  };
  for (const st of stages) {
    row.append(h("button", { class: `pstage ${st.cls}${st.gap ? " gap" : ""}${st.differ ? " differ" : ""}`, dataset: { id: st.id },
      "aria-pressed": "false", type: "button", onclick: () => select(st.id) },
      h("span", { class: "k" }, st.k), h("span", { class: "v" }, st.v), h("span", { class: "s" }, st.s),
      h("span", { class: "plane" }, st.plane)));
  }
  wrap.append(row, detail);
  select(selectedId || (i.verification.result === "MATCH" ? "verified" : (stages.find((x) => x.differ)?.id || "verified")));
  return wrap;
}

export function kvList(rows) {
  return h("dl", { class: "kv", style: { marginTop: "8px" } }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v instanceof Node ? v : String(v))]));
}

// ---- Ledger A / B comparison ------------------------------------------------------------
const SEAM = { Agrees: "agree", Equal: "agree", "Compatible with observed emission": "agree",
  Diverges: "differ", Different: "differ", "Incompatible with observed emission": "differ", "Paired by verifier": "pair" };
const SEAM_TEXT = { "Compatible with observed emission": "Consistent", "Incompatible with observed emission": "Contradicts",
  "No permitted request": "Nothing permitted", "Not applicable": "Not applicable", "Paired by verifier": "Paired by verifier" };

export function comparisonTable(i) {
  const a = i.runtime, b = i.observation, cmp = i.comparison;
  const none = (text) => h("span", { class: "absent" }, text);
  const cell = (field, value, state) => h("div", { class: `cell${state === "differ" ? " differ" : ""}` }, h("span", { class: "f" }, field), value);
  const seamCell = (state) => h("div", { class: `cell seam ${SEAM[state] || "na"}` }, SEAM[state] === "agree" ? icon("agree", 14) : SEAM[state] === "differ" ? icon("differ", 14) : icon("na", 14), SEAM_TEXT[state] || state);
  const missingB = i.observation_withheld ? "Withheld from verifier" : "No paired observation";
  const rows = [
    ["Event ID", mono(a.event_id), b ? "Paired by verifier" : "Unavailable", b ? mono(b.event_id) : none(missingB)],
    ["Trace ID", mono(a.trace_id), b ? (b.trace_id === a.trace_id ? "Agrees" : "Diverges") : "Unavailable", b ? mono(b.trace_id) : none(missingB)],
    ["Destination", a.permitted ? a.permitted.endpoint_id : none("Nothing permitted"), cmp.Destination, b ? b.observed.endpoint_id : none(missingB)],
    ["Method / route", a.permitted ? `${a.permitted.method} / ${a.permitted.route_id}` : none("Nothing permitted"), cmp["Method / route"], b ? `${b.observed.method} / ${b.observed.route_id}` : none(missingB)],
    ["Body fingerprint", seal(a.payload_hmac, "No body"), cmp["Payload commitment"], b ? seal(b.payload_hmac, "No body") : none(missingB)],
    ["Key / canonicalization", `${a.key_id} / ${a.canonicalization_version}`, b ? (i.fingerprints_comparable ? "Agrees" : "Diverges") : "Unavailable", b ? `${b.key_id} / ${b.canonicalization_version}` : none(missingB)],
    ["Execution", `${a.claim}${a.response_status ? ` (${a.response_status})` : ""}`, cmp["Runtime claim"], b ? `Request seen${b.response_status ? `, ${b.response_status} returned` : ""}` : none(missingB)],
    ["Decision / policy", `${a.decision} under ${a.policy_version}`, null, none("Not recorded by the monitor")],
    ["Protected IDs", a.hits.length ? a.hits.map((x) => `${x.protected_id} ← ${x.source_ref}`).join(", ") : "None", null, none("Not recorded by the monitor")],
  ];
  const grid = h("div", { class: "compare", role: "table", "aria-label": "Ledger A and Ledger B comparison" },
    h("div", { class: "head a", role: "columnheader" }, "Ledger A: permitted and claimed"),
    h("div", { class: "head seam", role: "columnheader" }, "Verifier check"),
    h("div", { class: "head b", role: "columnheader" }, "Ledger B: observed"));
  for (const [field, left, state, right] of rows) {
    const css = SEAM[state] === "differ" ? "differ" : "";
    grid.append(cell(`${field} (A)`, left, css), state ? seamCell(state) : h("div", { class: "cell seam na" }, "Not compared"), cell(`${field} (B)`, right, css));
  }
  return grid;
}

// ---- Timing and coverage ---------------------------------------------------------------
// Complete coverage: health records exist, the verifier qualified the evidence and raised no
// coverage or correlation diagnostic. Pairing an observation is not coverage.
export function coverageComplete(i) {
  const gaps = i.verification.diagnostics.filter((d) => d !== "SCOPED_PROXY_ABSENCE");
  return i.health_records > 0 && i.verification.evidence_status === "VERIFIED" && gaps.length === 0;
}

export function timeline(i, { illustrative = false } = {}) {
  const W = i.window_seconds, G = 1, span = W + G;
  const covered = coverageComplete(i);
  const pct = (t) => `${Math.min(Math.max(t / span, 0), 1) * 100}%`;
  const a = i.runtime, b = i.observation;
  const completion = a.completion_time ? a.completion_time - a.decision_time : null;
  const caption = illustrative
    ? `Illustrative timings, not a recorded incident: a decision at 0 s and an observation at +${i.observed_offset_s.toFixed(3)} s inside a ${W} s window. Real incidents show their own recorded values.`
    : `${timelineCaption(i)} ${covered ? "The verifier reported complete, health-qualified coverage for this window." : "Coverage is not established for this window, so the track is shown as a gap."}`;
  // Ticks only on the track; their values go in a legend, so near-coincident events never
  // overlap and nothing is positioned outside the track at narrow widths.
  const el = h("div", { class: "timeline", role: "img", "aria-label": caption },
    h("div", { class: `track${covered ? "" : " gap"}`, style: { right: `${(G / span) * 100}%` } }),
    h("div", { class: "drain", style: { left: pct(W), right: "0" } }),
    h("div", { class: "tick", style: { left: "0" } }),
    h("div", { class: "tick bound", style: { left: pct(W) } }),
    completion !== null && completion >= 0 ? h("div", { class: "tick done", style: { left: pct(completion) } }) : null,
    b ? h("div", { class: "tick obs", style: { left: pct(i.observed_offset_s) } }) : null,
    h("span", { class: "scale start" }, "0 s"), h("span", { class: "scale end" }, `${span} s`));
  const legend = h("ul", { class: "timeline-legend" },
    h("li", null, h("span", { class: "swatch decision" }), "Gateway decision, 0 s"),
    b ? h("li", null, h("span", { class: "swatch obs" }), `Observed at the proxy, +${i.observed_offset_s.toFixed(3)} s`) : null,
    completion !== null && completion >= 0 ? h("li", null, h("span", { class: "swatch done" }), `Runtime completed, +${completion.toFixed(3)} s (wall clock)`) : null,
    h("li", null, h("span", { class: `swatch window${covered ? "" : " gap"}` }), `Observation window W = ${W} s, ${covered ? "coverage complete" : "coverage not established"}`),
    h("li", null, h("span", { class: "swatch drain" }), `Drain grace G = ${G} s`));
  return h("div", null, illustrative ? h("span", { class: "tag" }, "Illustrative example") : null, el, legend, h("p", { class: "small soft" }, caption));
}

function timelineCaption(i) {
  const b = i.observation;
  if (b) return `The proxy observed the request ${i.observed_offset_s.toFixed(3)} s after the gateway decision, inside the ${i.window_seconds} s window. Completion is wall-clock; the observation offset uses the shared monotonic clock.`;
  if (i.observation_withheld) return "The harness withheld the observation from the verifier, so nothing is placed in the window.";
  if (i.scoped_absence) return `Nothing carrying this trace was seen at the proxy during the ${i.window_seconds} s window, with complete health coverage.`;
  return "No observation was paired with this event, so nothing is placed in the window.";
}

export function coverageList(i) {
  const v = i.verification;
  const gaps = v.diagnostics.filter((d) => d !== "SCOPED_PROXY_ABSENCE");
  const item = (ok, title, note) => h("li", { class: "ready-item" }, h("span", { class: `dot ${ok === true ? "ok" : ok === false ? "bad" : ""}` }), h("div", null, h("b", null, title), h("div", { class: "detail" }, note)), h("span"));
  return h("ul", { class: "plain" },
    item(i.health_records > 0, "Monitor health journal", `${i.health_records} records from ${i.monitor_generations} monitor run${i.monitor_generations === 1 ? "" : "s"}`),
    item(i.observation ? true : i.scoped_absence ? null : false, "Observation pairing", i.observation ? "Exactly one observation paired by trace and clock domain" : i.observation_withheld ? "Withheld from the verifier by the harness" : i.scoped_absence ? "None expected: blocked and claimed not sent" : "The verifier paired none"),
    item(i.observation ? i.fingerprints_comparable : null, "Fingerprints comparable", i.observation ? (i.fingerprints_comparable ? "Same key ID and canonicalization" : "Key or canonicalization differs") : "No observation to compare"),
    item(gaps.length === 0, "Correlation diagnostics", gaps.length ? i.diagnostic_notes.filter((d) => d.code !== "SCOPED_PROXY_ABSENCE").map((d) => d.text).join(" ") : "No monitoring gaps reported for this window"),
    item(v.evidence_status === "VERIFIED", "Evidence status", v.evidence_status));
}

// ---- HMAC commitment explainer ---------------------------------------------------------
export function hmacExplainer(i = null) {
  const step = (title, body, code) => h("div", { class: "step-card" }, h("h4", null, title), h("p", { class: "small soft" }, body), code ? h("pre", null, code) : null);
  const grid = h("div", { class: "hmac" },
    step("1. A JSON body", "The request body, written in any formatting.", '{ "text" : "status green",\n  "case":0 }'),
    step("2. Canonical form", "RFC 8785 fixes key order, spacing and escapes, so equal content gives equal bytes.", '{"case":0,"text":"status green"}'),
    step("3. Keyed fingerprint", "HMAC-SHA-256 with a secret per-run key K. Not encryption: nothing can be decrypted.", "HMAC-SHA-256(K, bytes)\n= 3f9c…a1e7"),
    step("4. Compare", "Gateway and proxy each compute their own. Equal supports identical bodies; different proves only that they differ.", "A: 3f9c…a1e7\nB: 3f9c…a1e7"));
  const parts = [grid, h("p", { class: "small muted", style: { marginTop: "12px" } }, "The example body and fingerprints above are illustrative. The key is never displayed or exported.")];
  if (i) {
    const a = i.runtime, b = i.observation;
    parts.push(h("div", { class: "sunken", style: { marginTop: "12px" } }, h("h4", null, "This incident"),
      kvList([["Gateway (Ledger A)", seal(a.payload_hmac, "No permitted body")], ["Proxy (Ledger B)", b ? seal(b.payload_hmac, "No body") : h("span", { class: "muted" }, i.observation_withheld ? "Withheld from verifier" : "No paired observation")],
        ["Comparison", i.comparison["Payload commitment"]],
        ["What it supports", i.comparison["Payload commitment"] === "Equal" ? "The observed canonical body is identical to the permitted one." : i.comparison["Payload commitment"] === "Different" ? "The bodies differ. It does not show which value changed or prove a secret leaked." : "No body comparison is possible for this incident."]])));
  }
  return h("div", null, parts);
}

function decisionsFigure() {
  const col = (name, cls, text, example) => h("div", { class: "claim-card" }, h("h4", { class: "decision" }, name), h("p", null, text), h("pre", { class: "small", style: { marginTop: "8px" } }, example), h("span", { class: `tag ${cls}` }, cls === "teal" ? "Sent" : "Not sent"));
  return h("div", { class: "grid-3" },
    col("ALLOW", "teal", "Nothing protected; fits the policy.", '{"text":"status green"}'),
    col("REDACT", "teal", "Protected value only in a redactable field.", '{"data":[{"text":"[REDACTED]"}]}'),
    col("BLOCK", "", "Protected value where redaction is not allowed.", '{"text":"<SECRET_001>"}  → refused'));
}

function outcomesFigure() {
  return h("div", { class: "grid-3" },
    h("div", null, badge("MATCH"), h("p", { class: "small soft", style: { marginTop: "8px" } }, "Health-qualified evidence agrees with what was permitted, or a BLOCK with complete coverage and nothing seen.")),
    h("div", null, badge("MISMATCH"), h("p", { class: "small soft", style: { marginTop: "8px" } }, "Usable evidence shows a supported divergence label.")),
    h("div", null, badge("UNVERIFIED"), h("p", { class: "small soft", style: { marginTop: "8px" } }, "An evidence gap. Not a leak, not containment.")));
}

function timelineExample() {
  return timeline({ window_seconds: 5, runtime: { decision_time: 0, completion_time: 0.03 }, observation: { request_monotonic: 0 },
    observed_offset_s: 0.021, observation_withheld: false, scoped_absence: false, health_records: 1,
    verification: { diagnostics: [], evidence_status: "VERIFIED" } }, { illustrative: true });
}

function pipelineExample() {
  return h("div", { class: "pipeline", "aria-label": "Evidence pipeline stages" },
    [["Proposed", "plane-a", "Agent's request"], ["Decided", "plane-a", "Gateway decision"], ["Permitted", "plane-a", "Allowed request + HMAC"],
      ["Claimed", "plane-a", "Runtime's report"], ["Observed", "plane-b", "Proxy's record + HMAC"], ["Verified", "verdict", "Verifier result"]]
      .map(([k, cls, sub]) => h("div", { class: `pstage ${cls}`, style: { cursor: "default" } }, h("span", { class: "k" }, k), h("span", { class: "s" }, sub), h("span", { class: "plane" }, cls === "plane-a" ? "Ledger A" : cls === "plane-b" ? "Ledger B" : "Verifier"))));
}

// ---- Guided investigation checklist ---------------------------------------------------
export function checklist(i) {
  const key = `xs-check:${i.identifier}`;
  let ticks = [];
  try { ticks = JSON.parse(sessionStorage.getItem(key) || "[]"); } catch { ticks = []; }
  const save = () => { try { sessionStorage.setItem(key, JSON.stringify(ticks)); } catch { /* storage unavailable */ } };
  return h("div", { class: "checklist" }, CHECKLIST.map(([question, where], index) => {
    const box = h("input", { type: "checkbox", checked: ticks.includes(index) || null, onchange: (e) => {
      ticks = e.target.checked ? [...new Set([...ticks, index])] : ticks.filter((t) => t !== index); save(); } });
    return h("details", { class: "check-q" }, h("summary", null, h("span", { class: "n" }, `Q${index + 1}`), question),
      h("p", { class: "where" }, `Where to look: ${where}`), h("label", null, box, "I have answered this from the evidence"));
  }));
}
