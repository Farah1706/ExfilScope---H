// Animated execution stage for the Scenario Lab.
//
// Eight SVG scenes explain one attempt from task to verifier. Every value a scene shows comes
// from one of three sources, and the stage says which:
//   preview  nothing has run; decisions and results are shown as "decided at run time";
//   live     lifecycle stage records of a running run (webapp/runner.py via runs.py);
//   replay   the validated incident of a finished run or a recorded snapshot case.
// A scene that needs a record the backend has not reported is shown as "awaiting", never
// filled in. Playback controls move through the explanation only; they never touch the run.
import { h, s, icon, humanize, fill, svgBoxLabel, disclosure, OUTCOME_TEXT } from "../dom.js";

const W = 960, H = 440, MID = W / 2;
const C = { ink: "#16243A", soft: "#4F5F75", faint: "#8593A6", line: "#C9D2DE", panel: "#FFFFFF", panel2: "#F1F5FA",
  bg: "#F8FAFC", tealWash: "#EEF7F6", warmWash: "#FFF8EC", visor: "#16243A",
  a: "#2D6CC4", b: "#0B8A82", ok: "#2E7D57", warn: "#A86A0C", bad: "#B5473A", fault: "#B5473A" };
// Stable network layout, shared by the execution and monitoring scenes (proxy exactly centred).
const NET = { gateway: 110, wrapper: 290, proxy: MID, receiver: 840, branch: 668, y: 270, lane: 150, offY: 352,
  bw: 160, rw: 184, bh: 76, chipY: 334 };
const SPEEDS = [["0.5", "Slow"], ["1", "Normal"], ["1.5", "Fast"]];
const BASE = 9000;  // ms per scene at normal speed; deliberately unhurried

const clamp = (k) => Math.min(Math.max(k, 0), 1);
const seg = (t, a, b) => clamp((t - a) / (b - a));
const ease = (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
const lerp = (a, b, k) => a + (b - a) * k;
const short = (hmac) => (hmac ? `${hmac.slice(0, 6)}…${hmac.slice(-4)}` : null);
const move = (el, x, y, scale = 1) => el.setAttribute("transform", `translate(${x} ${y})${scale !== 1 ? ` scale(${scale})` : ""}`);
const show = (el, o) => el.setAttribute("opacity", String(clamp(o)));

// ---- drawing helpers --------------------------------------------------------------------
function text(g, x, y, value, { size = 15, weight = 500, fill: color = C.ink, anchor = "middle", mono = false, cls = "", halo = false } = {}) {
  const el = s("text", { x, y, "text-anchor": anchor, "font-size": size, "font-weight": weight, fill: color,
    class: `${mono ? "mono" : ""} ${cls}`.trim(), stroke: halo ? C.bg : null, "stroke-width": halo ? 6 : null,
    "stroke-linejoin": halo ? "round" : null, "paint-order": halo ? "stroke" : null }, value);
  g.append(el);
  return el;
}
function box(g, x, y, w, hgt, { title, sub, tone = C.line, fillc = C.panel, glyph = null, dashed = false } = {}) {
  const grp = s("g", { class: "node" });
  grp.append(s("rect", { x, y, width: w, height: hgt, rx: 10, fill: fillc, stroke: tone, "stroke-width": 1.6, "stroke-dasharray": dashed ? "5 4" : null }));
  if (glyph) grp.append(glyph);
  if (title || sub) grp.append(svgBoxLabel(x, y, w, hgt, title || "", sub, { compact: hgt <= 76 }));
  g.append(grp);
  return grp;
}
function chip(g, label, tone, { w = null, size = 12 } = {}) {
  const grp = s("g");
  const width = w || Math.max(46, label.length * (size * 0.62) + 22);
  grp.append(s("rect", { x: -width / 2, y: -13, width, height: 26, rx: 13, fill: C.panel, stroke: tone, "stroke-width": 1.6 }));
  text(grp, 0, 4.5, label, { size, weight: 700, fill: tone });
  g.append(grp);
  return grp;
}
function packet(g, label, tone, { dashed = false, w = 144 } = {}) {
  const grp = s("g");
  grp.append(s("rect", { x: -w / 2, y: -17, width: w, height: 34, rx: 6, fill: C.panel, stroke: tone, "stroke-width": 1.6, "stroke-dasharray": dashed ? "5 4" : null }));
  grp.append(s("path", { d: `M${-w / 2 + 9} -8 l9 6 9 -6`, fill: "none", stroke: tone, "stroke-width": 1.4 }));
  const t = text(grp, 13, 4.5, label, { size: 12.5, weight: 600 });
  g.append(grp);
  grp.label = t;
  return grp;
}
function arrow(g, x1, y1, x2, y2, { tone = C.faint, dashed = false, head = true } = {}) {
  const el = s("path", { d: `M${x1} ${y1} L${x2} ${y2}`, stroke: tone, "stroke-width": 1.6, fill: "none",
    "stroke-dasharray": dashed ? "6 5" : null, "marker-end": head ? "url(#xs-head)" : null });
  g.append(el);
  return el;
}
function cylinder(g, cx, y, w, hgt, title, tone) {
  const grp = s("g");
  const rx = w / 2, ry = 10;
  grp.append(s("path", { d: `M${cx - rx} ${y} v${hgt} a${rx} ${ry} 0 0 0 ${w} 0 v${-hgt}`, fill: C.panel, stroke: tone, "stroke-width": 1.6 }));
  grp.append(s("ellipse", { cx, cy: y, rx, ry, fill: C.panel2, stroke: tone, "stroke-width": 1.6 }));
  text(grp, cx, y + hgt / 2 + 10, title, { size: 16, weight: 700, fill: tone });
  g.append(grp);
  return grp;
}
function doc(g, label, tone = C.soft) {
  const grp = s("g");
  grp.append(s("path", { d: "M-16 -21 h22 l10 10 v32 h-32 z", fill: C.panel, stroke: tone, "stroke-width": 1.4 }));
  grp.append(s("path", { d: "M-9 -4 h18 M-9 3 h18 M-9 10 h12", stroke: tone, "stroke-width": 1.2 }));
  text(grp, 0, 40, label, { size: 13, fill: C.soft });
  g.append(grp);
  return grp;
}
// The illustrated agent appears only inside this explanatory canvas.
function agent(g, label) {
  const grp = s("g");
  grp.append(s("rect", { x: -26, y: -40, width: 52, height: 40, rx: 14, fill: C.panel2, stroke: C.a, "stroke-width": 1.8 }));
  grp.append(s("rect", { x: -16, y: -29, width: 32, height: 14, rx: 7, fill: C.visor }));
  grp.append(s("circle", { cx: -7, cy: -22, r: 3, fill: C.b }), s("circle", { cx: 7, cy: -22, r: 3, fill: C.b }));
  grp.append(s("path", { d: "M0 -40 v-8", stroke: C.a, "stroke-width": 1.8 }), s("circle", { cx: 0, cy: -51, r: 3.5, fill: C.a }));
  grp.append(s("rect", { x: -32, y: 4, width: 64, height: 34, rx: 10, fill: C.panel, stroke: C.a, "stroke-width": 1.8 }));
  text(grp, 0, 60, label, { size: 15, weight: 650 });
  g.append(grp);
  return grp;
}
function boundary(g) {
  g.append(s("path", { d: `M${MID} 46 V${H - 34}`, stroke: C.b, "stroke-width": 1.6, "stroke-dasharray": "7 6", opacity: 0.8 }));
  text(g, MID, 36, "Independent activity check", { size: 14, weight: 650, fill: C.b, halo: true });
}
function decisionTone(d) { return d === "BLOCK" ? C.bad : d === "REDACT" ? C.warn : d === "ALLOW" ? C.ok : C.soft; }
function resultTone(r) { return r === "MATCH" ? C.ok : r === "MISMATCH" ? C.bad : r === "UNVERIFIED" ? C.warn : C.soft; }
const decisionLabel = d => ({ ALLOW: "Approved", REDACT: "Private data removed", BLOCK: "Stopped" })[d] || d;

// ---- facts: what is known, and from where ------------------------------------------------
// Builds the scene inputs from a scenario description plus whatever evidence exists.
export function facts(sc, mode, { record = null, incident = null, audit = null } = {}) {
  const st = Object.fromEntries((record?.stages || []).map((x) => [x.id, x]));
  const done = (id) => st[id]?.status === "complete";
  const i = incident, a = i?.runtime, b = i?.observation, v = i?.verification;
  const engine = sc.engine.lab_scenario;
  const decision = a?.decision || st.gateway?.facts?.decision || null;
  const agentic = ["live", "stub"].includes(mode) || i?.display_origin === "LLM run";
  const f = {
    sc, mode, engine, agentic, hasRecord: Boolean(record), trust: mode === "trust" || sc.group === "trust",
    source: i ? "replay" : record ? "live" : "preview",
    running: record?.status === "running",
    stages: st, done,
    decision, reason: a?.reason || st.gateway?.facts?.reason || null,
    policy: a?.policy_version || st.gateway?.facts?.policy || null,
    proposed: a?.proposed || null, permitted: a?.permitted || null,
    hits: a?.hits || null,
    claim: a?.claim || st.execution?.facts?.claim || null,
    hmacA: a?.payload_hmac || null, hmacB: b?.payload_hmac || null,
    observed: b?.observed || null, offset: i?.observed_offset_s ?? null,
    paired: b ? true : st.observation?.facts?.paired ?? null,
    withheld: i?.observation_withheld || false, scopedAbsence: i?.scoped_absence || false,
    health: i?.health_records ?? null, window: i?.window_seconds || st.drain?.facts?.window_seconds || 5,
    result: v?.result || st.verification?.facts?.result || null,
    evidenceStatus: v?.evidence_status || st.verification?.facts?.evidence_status || null,
    labels: v?.labels || st.verification?.facts?.labels || null,
    diagnostics: v?.diagnostics || null, comparison: i?.comparison || null,
    coverage: i ? i.health_records > 0 && v.evidence_status === "VERIFIED" && v.diagnostics.filter((d) => d !== "SCOPED_PROXY_ABSENCE").length === 0 : null,
    fault: sc.group === "fault",
    subtype: engine === "payload_divergence" ? (decision === "REDACT" || sc.engine.payload_subtype?.startsWith("REDACT") ? "restore" : "alter") : null,
    errorCategory: a?.error_category || null,
    diagnosticNotes: i?.diagnostic_notes || [],
    audit,
  };
  f.ev = evidence(f, i, st, done);
  return f;
}

// ---- evidence availability ---------------------------------------------------------------
// Every scene draws only what one of these states establishes. No state is inferred from the
// scenario's design, the gateway decision or the runtime's own claim:
//   attempt      what the runtime claims it did: design | pending | none | attempted | failed
//   observation  what the independent proxy recorded for this trace:
//                design | pending | observed | paired (live record; details arrive with the
//                export) | withheld (Ledger B kept, excluded from the verifier's view: the
//                labelled lab demonstration) | scoped-absence (health-qualified absence the
//                verifier reported) | none (no corresponding observation; transmission can be
//                neither established nor excluded)
//   fault        a verifier label that evidences a controlled fault: design | pending |
//                BLOCK_BYPASS | PAYLOAD_DIVERGENCE | DESTINATION_DIVERGENCE | null
const FAULT_LABELS = ["BLOCK_BYPASS", "PAYLOAD_DIVERGENCE", "DESTINATION_DIVERGENCE"];

function evidence(f, i, st, done) {
  if (f.source === "preview") return { attempt: "design", observation: "design", fault: f.fault ? "design" : null };
  const attempt = f.claim === "EXECUTED_SUCCESS" ? "attempted" : f.claim === "EXECUTED_FAILED" ? "failed"
    : f.claim === "NOT_EXECUTED" ? "none" : "pending";
  let observation;
  if (i) observation = i.observation ? "observed" : i.observation_withheld ? "withheld" : i.scoped_absence ? "scoped-absence" : "none";
  else if (!done("observation")) observation = "pending";
  else observation = st.observation?.facts?.paired === true ? "paired" : "none";
  // A withheld observation is known from the lab design and the incident's own flag; during a
  // live run the lifecycle cannot tell it apart from a missing one, so it stays "none".
  const labels = f.labels;
  const fault = labels ? FAULT_LABELS.find((x) => labels.includes(x)) || null : done("verification") ? null : "pending";
  return { attempt, observation, fault, crossed: ["observed", "paired", "withheld"].includes(observation) };
}

// The lifecycle stage that must be complete before each scene shows recorded values.
// Retrieval happens inside the agent worker's proposal stage, which reports no finer events.
const NEEDS = ["preparation", "proposal", "proposal", "gateway", "execution", "observation", "drain", "verification"];

// ---- scenes --------------------------------------------------------------------------------
// Each returns { tick(t) } for t in [0, BASE]; captions are produced separately.
const SCENES = [
  { id: "task", short: "Task", title: "Task received", build: sceneTask },
  { id: "retrieval", short: "Sources", title: "Find the information", build: sceneSources },
  { id: "proposal", short: "Request", title: "Prepare the request", build: sceneProposal },
  { id: "gateway", short: "Check", title: "Check permission and content", build: sceneGateway },
  { id: "execution", short: "Send", title: "Carry out the decision", build: sceneExecution },
  { id: "monitoring", short: "Observe", title: "Observe what happens", build: sceneMonitoring },
  { id: "evidence", short: "Records", title: "Keep two separate records", build: sceneEvidence },
  { id: "verify", short: "Compare", title: "Compare approval with activity", build: sceneVerify },
];

function sceneTask(g, f) {
  const actor = f.trust ? "Service assistant" : f.agentic ? "AI assistant" : "Test runner";
  const card = s("g");
  card.append(s("rect", { x: -145, y: -46, width: 290, height: 92, rx: 10, fill: C.panel2, stroke: C.a, "stroke-width": 1.6 }));
  text(card, 0, -20, f.trust ? "One approved service task" : f.agentic ? "Task instruction" : "Controlled test", { size: 16, weight: 700 });
  text(card, 0, 2, f.trust ? "Prepare a service brief" : "Prepare one request for review", { size: 14, fill: C.soft });
  text(card, 0, 24, f.trust ? "One use, limited time" : "Sample information only", { size: 13, fill: C.soft });
  g.append(card);
  const who = f.agentic || f.trust ? agent(g, actor) : box(g, -100, -45, 200, 90, { title: actor, sub: "Runs the selected example" });
  arrow(g, 240, 220, 400, 220, { dashed: true });
  const op = box(g, 40, 172, 190, 96, { title: f.trust ? "Service owner" : "Operator", sub: f.trust ? "Approves the task" : "Starts the scenario" });
  return { tick(t) {
    // The card travels from the operator and stops beside the actor, never over it.
    const k = ease(seg(t, 1200, 5200));
    move(card, lerp(360, 540, k), 220);
    show(card, seg(t, 0, 900));
    move(who, 820, f.agentic || f.trust ? 225 : 220, f.agentic || f.trust ? 1.15 : 1);
    show(who, seg(t, 300, 1400));
    show(op, seg(t, 0, 800));
  } };
}

function sceneSources(g, f) {
  if (f.trust) {
    const official = Boolean(f.audit?.data_mandate || f.audit?.official_reference);
    const source = official ? "Official GDRFA figures" : f.audit ? "Sample service notice" : "Official data or sample notice";
    box(g, 65, 155, 240, 120, { title: "Approved source", sub: source, tone: C.b });
    arrow(g, 315, 215, 355, 215);
    box(g, 365, 155, 230, 120, { title: "Task information", sub: official ? "Year, measure and count" : "Details needed for the task" });
    arrow(g, 605, 215, 645, 215);
    box(g, 655, 155, 240, 120, { title: "Brief for review", sub: "Checked before sending", tone: C.b });
    text(g, MID, 335, official ? "Public totals only; no personal records." : "The selected demonstration determines which source is used.", { size: 14, fill: C.soft });
    return { tick() {} };
  }
  const refs = [["Status bulletin", "DOC_PUBLIC:chunk_1"], ["Integration record", "DOC_001:chunk_1"], ["Operations review", "DOC_002:chunk_2"],
    ["Account note", "DOC_003:chunk_1"], ["Staff newsletter", "DOC_GARDEN:chunk_1"]];
  const wanted = new Set(f.sc.sources);
  const shelf = s("g");
  g.append(shelf);
  text(g, 150, 40, "Sample documents", { size: 15, weight: 650, fill: C.soft });
  const docs = refs.map(([label, ref], n) => { const d = doc(shelf, label, wanted.has(ref) && f.agentic ? C.b : C.faint); move(d, 150, 80 + n * 72); return [d, ref]; });
  if (f.agentic) text(g, MID + 100, H - 22, "Highlighted documents are part of the test design; retrieval is not separately recorded.", { size: 13, fill: C.soft });
  if (!f.agentic) {
    box(g, 370, 160, 260, 110, { title: "Prepared test information", sub: "The test runner creates the request", dashed: true, tone: C.faint });
    show(shelf, 0.35);
    const generated = packet(g, "test request", C.soft, { w: 170 });
    return { tick(t) { move(generated, lerp(500, 760, ease(seg(t, 2500, 6000))), 330); show(generated, seg(t, 2200, 3000)); } };
  }
  const retriever = cylinder(g, MID, 170, 140, 90, "Find sources", C.b);
  text(g, MID, 300, "Relevant information for the task", { size: 13, fill: C.soft });
  const who = agent(g, "AI assistant");
  arrow(g, 560, 215, 700, 215);
  const flying = docs.filter(([, ref]) => wanted.has(ref)).map(([d, ref], n) => {
    const copy = doc(g, "", C.b);
    return [copy, 80 + refs.findIndex((r) => r[1] === ref) * 72, n];
  });
  return { tick(t) {
    move(who, 790, 240);
    show(retriever, seg(t, 0, 800));
    for (const [copy, y0, n] of flying) {
      const k1 = ease(seg(t, 900 + n * 500, 3400 + n * 500)), k2 = ease(seg(t, 4300 + n * 400, 6800 + n * 400));
      move(copy, k2 > 0 ? lerp(MID, 790, k2) : lerp(150, MID, k1), k2 > 0 ? lerp(215, 230, k2) : lerp(y0, 215, k1), k2 > 0 ? lerp(1, 0.6, k2) : 1);
      show(copy, seg(t, 900 + n * 500, 1300 + n * 500) * (1 - seg(t, 7000, 7600)));
    }
  } };
}

// Recorded hit locations are positional codes (o = object member, a = array item); Ledger A
// deliberately does not keep field names, so they are shown exactly as recorded.
function bodyLines(f) {
  if (f.hits?.length) return f.hits.slice(0, 2).map((x) => [`body at ${x.location}`, `[[${x.protected_id}]]`]);
  if (f.trust) return [["body.data[0].text", "Scripted notice or live pilot brief"]];
  if (f.hits) return [["body", "no registered values"]];
  // Preview: the shape of the situation's proposal, not a recorded body.
  if (["redact", "payload_divergence"].includes(f.engine) && f.sc.uses_protected_item) return [["body.data[0].text", "[[registered value]]"]];
  if (["block", "block_bypass"].includes(f.engine)) return [["body.text", "[[registered value]]"]];
  return [["body", "harmless text"]];
}

function sceneProposal(host, f) {
  const p = f.proposed;
  const ref = f.audit?.official_reference;
  const cited = f.audit?.attempts?.find((a) => a.trust === "ACCEPTED" && a.citations?.length)?.citations;
  const body = cited ? [["body.data[0].text", "Public figures from the approved GDRFA Dubai source."]]
    : ref ? [["body.data[0].text", `Sandbox pilot brief using the GDRFA Dubai count for ${ref.year}: ${ref.transactions.toLocaleString("en")} residence transactions.`]]
    : bodyLines(f);
  const preview = f.source === "preview";
  const fields = [["Action", preview || p ? "Send one request" : "Awaiting record"],
    ["Destination", p?.endpoint_id === "AUTHORIZED" || preview ? "Approved test destination" : p?.endpoint_id || "Awaiting record"],
    ...body.map(([, value]) => ["Information", value])];
  const rows = fields.map(([key, value]) => h("div", { class: "proposal-row" },
    h("dt", null, key), h("dd", null, value)));
  host.append(h("section", { class: "proposal-card" }, h("h4", null, "Request for review"),
    h("dl", null, rows),
    h("p", { class: "small soft" }, preview ? "Preview only. Recorded results show what was actually proposed."
      : "Summary of the recorded request. Confidential values are represented by reference codes.")));
  return { tick(t) {
    rows.forEach((row, n) => { row.style.opacity = String(0.45 + 0.55 * seg(t, n * 550, n * 550 + 500)); });
  } };
}

function sceneGateway(g, f) {
  const gate = s("g");
  g.append(gate);
  gate.append(s("rect", { x: -100, y: -48, width: 200, height: 96, rx: 12, fill: C.panel, stroke: C.b, "stroke-width": 2 }));
  gate.append(icon_shield(0, -18));
  text(gate, 0, 18, "Security gateway", { size: 16, weight: 700 });
  text(gate, 0, 37, f.policy || "policy from the run", { size: 13, fill: C.soft, mono: !!f.policy });
  const beam = s("rect", { x: -100, y: -48, width: 200, height: 3, fill: C.b, opacity: 0.5 });
  gate.append(beam);
  const proposal = packet(g, "proposal", C.a, { w: 120 });
  const hits = f.hits;
  const checks = [
    ["Is the request in the approved format?", "evaluated"],
    ["Is the destination approved?", "evaluated"],
    [hits ? (hits.length ? "Confidential content found" : "No registered confidential values found") : "Check for confidential information", hits?.length ? "hit" : "evaluated"],
    ["Can confidential content be safely removed?", "evaluated"],
  ];
  const list = s("g");
  g.append(list);
  const rows = checks.map(([label, state], n) => {
    const row = s("g");
    row.append(s("circle", { cx: 0, cy: -4, r: 6, fill: state === "hit" ? C.warn : C.b }));
    text(row, 16, 0, label, { size: 14.5, anchor: "start" });
    move(row, 0, n * 34);
    list.append(row);
    return row;
  });
  const decided = f.decision;
  const outcome = chip(g, decisionLabel(decided) || (f.source === "live" ? "Awaiting record" : "Decision pending"), decisionTone(decided), { size: 13 });
  const reason = text(g, 0, 0, decided ? humanize(f.reason || "") : f.source === "live" ? "Awaiting the gateway's Ledger A record" : "", { size: 13, fill: C.soft });
  return { tick(t) {
    // Phase 1: proposal enters; phase 2: checks run beside the gateway; phase 3: the checks
    // condense into one decision chip that travels with the gateway into the next scene.
    const settle = ease(seg(t, 6600, 8600));
    move(gate, lerp(300, NET.gateway, settle), lerp(220, NET.y, settle), lerp(1, 0.8, settle));
    const kin = ease(seg(t, 200, 1800));
    move(proposal, lerp(60, 140, kin), 220);
    show(proposal, 1 - seg(t, 1700, 2100));
    beam.setAttribute("y", String(lerp(-48, 45, (Math.sin(t / 520) + 1) / 2)));
    show(beam, seg(t, 1800, 2200) * (1 - seg(t, 5600, 6200)));
    move(list, lerp(450, NET.gateway - 40, settle), lerp(170, NET.chipY, settle), lerp(1, 0.2, settle));
    show(list, seg(t, 2000, 2400) * (1 - seg(t, 6600, 7600)));
    rows.forEach((row, n) => show(row, seg(t, 2200 + n * 700, 2600 + n * 700)));
    move(outcome, lerp(560, NET.gateway, settle), lerp(340, NET.chipY, settle));
    show(outcome, seg(t, 5200, 5800));
    move(reason, lerp(560, NET.gateway, settle), lerp(372, NET.chipY + 32, settle));
    show(reason, seg(t, 5400, 6000) * (1 - seg(t, 7000, 7600)));
  }, still: 6300 };
}

function icon_shield(x, y) {
  const g = s("g", { transform: `translate(${x - 14} ${y - 16}) scale(1.2)` });
  g.append(s("path", { d: "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z", fill: "none", stroke: C.b, "stroke-width": 1.8 }),
    s("path", { d: "m9 12 2 2 4-4", fill: "none", stroke: C.b, "stroke-width": 1.8 }));
  return g;
}

// Trust extension: seven attempts, one row each, checked in order by the validator column.
// Outcomes and codes come from the run's trust audit; before a run none is shown.
function sceneTrustGate(host, f) {
  const titles = ["Valid identity, in-scope action", "Replayed capability", "Destination outside the scope",
    "Expired capability", "Capability from an untrusted issuer", "Proof signed by another key", "Revoked agent identity"];
  const attempts = f.audit?.attempts;
  const accepted = attempts?.filter((a) => a.trust === "ACCEPTED") ?? [];
  const rejected = attempts?.filter((a) => a.trust === "REJECTED") ?? [];
  const node = (label, detail, tone = "") => h("div", { class: `trust-node ${tone}` },
    h("strong", null, label), h("div", { class: "small" }, detail));
  const connector = () => h("span", { class: "trust-connector", "aria-hidden": "true" });
  const branches = h("div", { class: "trust-branches" },
    h("div", null, connector(),
      node(attempts ? `Accepted · ${accepted.length}` : "If accepted", "Valid identity and permission", "accept"),
      connector(), node("Content check", "Send, remove confidential content, or stop"),
      connector(), node("Send request", "Only if permitted")),
    h("div", null, connector(),
      node(attempts ? `Rejected · ${rejected.length}` : "If rejected", "Permission check failed", "reject"),
      connector(), node("Stop request", "No approved action to carry out")));
  host.append(h("div", { class: "trust-flow" },
    node("Agent attempt", attempts ? `${attempts.length} recorded attempts` : "Explanatory routing preview"),
    connector(), node("Permission check", "Is this the right agent, with valid permission for this task?"), branches),
    disclosure("Individual test records", h("ol", { class: "trust-attempts" }, (attempts ?? titles.map((title) => ({ title }))).map((attempt) =>
      h("li", null, attempt.title, attempt.code ? h("span", { class: "small soft" }, humanize(attempt.code)) : null)))));
  return { tick(t) { branches.style.opacity = String(0.55 + 0.45 * seg(t, 450, 1700)); } };
}

// What may be drawn leaving the HTTP tool, and whether it may be drawn crossing the proxy.
// Returns null when nothing left according to the evidence (BLOCK, or a NOT_EXECUTED claim
// with no observation). Labels describing an altered, restored or blocked body appear only
// when the verifier's own label evidences that fault; before a run they are the design.
function emission(f) {
  const { attempt, observation, fault, crossed } = f.ev;
  if (observation === "design") {
    if (f.decision === null && !f.fault) return { label: "request, if any", tone: C.soft, dashed: true, design: true };
    if (f.engine === "block_bypass") return { label: "blocked body", tone: C.soft, dashed: true, fault: "Designed fault: the harness emits the blocked body anyway", design: true, bypass: true };
    if (f.subtype === "alter") return { label: "permitted body", tone: C.soft, dashed: true, swap: "altered body", fault: "Designed fault: the harness replaces the body after approval", design: true };
    if (f.subtype === "restore") return { label: "authorized body", tone: C.soft, dashed: true, swap: "original body", fault: "Designed fault: the harness restores the original body", design: true };
    return { label: "request, if any", tone: C.soft, dashed: true, design: true };
  }
  if (attempt === "pending" && !crossed) return { label: "request, if any", tone: C.soft, dashed: true, pending: true };
  if (!crossed && attempt === "none") return null;
  if (!crossed) {
    // The runtime reports an attempt, but no corresponding observation exists: the request
    // is drawn up to the tool's hand-off only, never across the boundary.
    return { label: attempt === "failed" ? "attempt failed" : "attempted request", tone: attempt === "failed" ? C.warn : C.soft, dashed: true, unobserved: true };
  }
  const body = f.decision === "REDACT" ? { label: "sanitized body", tone: C.warn } : { label: "permitted body", tone: C.ok };
  if (fault === "BLOCK_BYPASS") return { label: "blocked body", tone: C.fault, dashed: true, fault: "The harness emitted the blocked body anyway", bypass: true };
  if (fault === "PAYLOAD_DIVERGENCE") return { ...body, swap: f.decision === "REDACT" ? "original body" : "altered body", fault: f.decision === "REDACT" ? "The harness restored the original body" : "The harness replaced the body after approval" };
  if (fault === "DESTINATION_DIVERGENCE") return { ...body, fault: "The harness sent the body to another receiver", divert: true };
  return body;
}

// Components sit on one row of equal boxes. Requests travel on the lane above them: one
// arrow per hop, with a riser into each component they pass through, so a moving packet
// never covers a label and every connector has a single, deliberate route.
function network(g, f, { withReceivers = true, blocked = false } = {}) {
  boundary(g);
  const { lane, y, bw, bh } = NET;
  const hop = (x1, x2, faded) => arrow(g, x1 + 6, lane, x2 - 8, lane, { tone: faded ? C.line : C.faint, dashed: faded });
  hop(NET.gateway, NET.wrapper, blocked);
  hop(NET.wrapper, NET.proxy, blocked);
  // Beyond the proxy the path is drawn solid only when a crossing is evidenced.
  if (withReceivers) hop(NET.proxy, NET.receiver - NET.rw / 2, blocked || (!f.ev.crossed && f.ev.observation !== "design"));
  for (const x of [NET.gateway, NET.wrapper, NET.proxy]) {
    g.append(s("path", { d: `M${x} ${lane} V${y - bh / 2}`, stroke: C.line, "stroke-width": 1.4 }));
    g.append(s("circle", { cx: x, cy: lane, r: 3.5, fill: C.panel, stroke: C.faint, "stroke-width": 1.4 }));
  }
  const node = (x, title, sub, tone, fillc = C.panel) => box(g, x - bw / 2, y - bh / 2, bw, bh, { title, sub, tone, fillc });
  const gate = node(NET.gateway, "Security gateway", f.policy || "decision recorded", C.b);
  const wrap = node(NET.wrapper, "Send request", "Approved action", C.a);
  const proxy = node(NET.proxy, "Activity monitor", "Independent record", C.b, C.tealWash);
  const dchip = chip(g, decisionLabel(f.decision) || (f.source === "live" ? "Awaiting record" : "Decision pending"), decisionTone(f.decision), { size: 13 });
  move(dchip, NET.gateway, NET.chipY);
  let ok = null, off = null;
  if (withReceivers) {
    ok = box(g, NET.receiver - NET.rw / 2, lane - bh / 2, NET.rw, bh, { title: "Test destination", sub: "Approved receiver", tone: C.faint });
    // The unauthorized receiver is drawn only where the verifier evidenced the diversion
    // (or, before a run, as the situation's design).
    const diverted = f.ev.fault === "DESTINATION_DIVERGENCE" || (f.ev.fault === "design" && f.engine === "destination_divergence");
    if (diverted) {
      g.append(s("path", { d: `M${NET.branch} ${lane + 4} V${NET.offY} H${NET.receiver - NET.rw / 2 - 8}`, stroke: C.bad, "stroke-width": 1.4,
        "stroke-dasharray": "6 5", fill: "none", "marker-end": "url(#xs-head)" }));
      off = box(g, NET.receiver - NET.rw / 2, NET.offY - bh / 2, NET.rw, bh, { title: "Wrong destination", sub: "Controlled test", tone: C.bad, dashed: true });
    }
  }
  return { gate, dchip, wrap, proxy, ok, off };
}

function sceneExecution(g, f) {
  const out = emission(f);
  network(g, f, { blocked: !out });  // same layout as the monitoring scene
  const claim = chip(g, f.claim ? humanize(f.claim) : f.source === "live" ? "Awaiting record" : "Claim pending", f.claim ? (f.claim === "EXECUTED_FAILED" ? C.warn : C.a) : C.soft, { size: 13 });
  move(claim, NET.wrapper, NET.chipY);
  const errorNote = f.errorCategory ? text(g, NET.wrapper, NET.chipY + 34, `Runtime error: ${humanize(f.errorCategory)}`, { size: 13, fill: C.warn }) : null;
  if (!out) {
    const bar = s("g");
    bar.append(s("path", { d: `M${NET.gateway + 56} ${NET.lane - 16} v32`, stroke: C.bad, "stroke-width": 4, "stroke-linecap": "round" }));
    text(bar, NET.gateway + 56, NET.lane - 26, f.decision === "BLOCK" ? "No permitted request" : "Runtime reports nothing sent", { size: 13.5, weight: 650, fill: C.bad });
    g.append(bar);
    const note = errorNote ? null : text(g, NET.wrapper, NET.chipY + 40, f.decision === "BLOCK" ? "Wrapper not called: nothing to send" : "No observation contradicts this claim", { size: 13, fill: C.soft });
    return { tick(t) { show(bar, seg(t, 1500, 2300)); show(claim, seg(t, 3200, 3800)); if (note) show(note, seg(t, 3600, 4200)); if (errorNote) show(errorNote, seg(t, 3600, 4200)); }, still: BASE };
  }
  const pk = packet(g, out.label, out.tone, { dashed: out.dashed });
  const faultTag = out.fault ? chip(g, out.design ? "DESIGNED FAULT" : "LAB FAULT", out.design ? C.soft : C.fault, { size: 12 }) : null;
  const faultNote = out.fault && !errorNote ? text(g, NET.wrapper, NET.chipY + 66, out.fault, { size: 13, fill: out.design ? C.soft : C.fault }) : null;
  if (faultTag) move(faultTag, NET.wrapper, NET.chipY + 38);
  const between = (NET.wrapper + NET.proxy) / 2;  // the packet's resting point on the tool → proxy hop
  return { tick(t) {
    const k1 = ease(seg(t, 800, 3200)), k2 = ease(seg(t, 5000, 7600));
    const x = out.bypass || k2 > 0 ? lerp(NET.wrapper, between, k2) : lerp(NET.gateway, NET.wrapper, k1);
    move(pk, x, NET.lane);
    show(pk, out.bypass ? seg(t, 3400, 4000) : seg(t, 600, 1000));
    if (out.swap) {
      const swapped = t > 4200;
      pk.label.textContent = swapped ? out.swap : out.label;
      pk.firstChild.setAttribute("stroke", swapped && !out.design ? C.fault : out.tone);
      pk.firstChild.setAttribute("stroke-dasharray", swapped || out.dashed ? "5 4" : "none");
    }
    if (faultTag) { show(faultTag, seg(t, 3600, 4200)); if (faultNote) show(faultNote, seg(t, 3800, 4400)); }
    if (errorNote) show(errorNote, seg(t, 4800, 5400));
    show(claim, seg(t, 4600, 5200));
  }, still: BASE };
}

// Text for the observation states that draw nothing crossing the boundary.
function noCrossingText(f) {
  const { observation, attempt } = f.ev;
  if (observation === "design") return ["The monitor records requests at this checkpoint.", "This preview does not confirm any activity."];
  if (observation === "scoped-absence") return ["No request for this attempt during the check.", "The monitor was active for the full period."];
  return ["No matching activity record is available.",
    attempt === "none" ? "Incomplete monitoring cannot confirm that nothing was sent." : "The evidence cannot confirm whether a request was sent."];
}

function sceneMonitoring(g, f) {
  const out = emission(f);
  const { observation } = f.ev;
  network(g, f, { blocked: !out });
  const windowBar = s("g");
  windowBar.append(s("rect", { x: -150, y: -5, width: 300, height: 10, rx: 5, fill: C.panel2, stroke: C.line }));
  const fillBar = s("rect", { x: -150, y: -5, width: 0, height: 10, rx: 5, fill: C.b, opacity: 0.55 });
  windowBar.append(fillBar);
  text(windowBar, 0, 28, `Check for ${f.window} seconds; allow 1 more second for records to save.`, { size: 13, fill: C.soft, halo: true });
  g.append(windowBar);
  move(windowBar, MID, H - 42);
  const waiting = (label) => { const p = out ? packet(g, label || out.label, C.soft, { dashed: true }) : null; if (p) move(p, (NET.wrapper + NET.proxy) / 2, NET.lane); return p; };
  if (observation === "pending") {
    const record = s("g");
    record.append(s("rect", { x: -108, y: -15, width: 216, height: 30, rx: 6, fill: C.panel, stroke: C.faint, "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
    text(record, 0, 5, "awaiting observation record", { size: 13, weight: 600, fill: C.faint });
    g.append(record);
    move(record, MID, NET.chipY);
    const p = waiting();
    return { tick(t) { show(record, seg(t, 300, 900)); if (p) show(p, seg(t, 300, 900)); fillBar.setAttribute("width", "0"); }, still: BASE };
  }
  if (!f.ev.crossed) {
    // Nothing is drawn crossing: design (before a run), health-qualified absence, or no
    // corresponding observation. An attempted request rests before the boundary.
    const p = out ? waiting() : null;
    const [line1, line2] = noCrossingText(f);
    const tone = observation === "scoped-absence" ? C.ok : observation === "none" ? C.warn : C.soft;
    const msg1 = text(g, MID, NET.chipY + 2, line1, { size: 14, weight: 600, fill: tone, halo: true });
    const msg2 = text(g, MID, NET.chipY + 24, line2, { size: 13, fill: C.soft, halo: true });
    return { tick(t) {
      fillBar.setAttribute("width", String(300 * seg(t, 500, 7500) * (observation === "scoped-absence" ? 1 : 0)));
      if (p) show(p, seg(t, 300, 900)); show(msg1, seg(t, 1500, 2200)); show(msg2, seg(t, 1900, 2600));
    }, still: BASE };
  }
  const record = s("g");
  const recordTone = observation === "withheld" ? C.warn : C.b;
  record.append(s("rect", { x: -108, y: -15, width: 216, height: 30, rx: 6, fill: C.panel, stroke: recordTone, "stroke-width": 1.5, "stroke-dasharray": observation === "withheld" ? "5 4" : null }));
  text(record, 0, 5, observation === "withheld" ? "kept, withheld from verifier" : f.observed ? `${f.observed.method} ${f.observed.endpoint_id} +${f.offset.toFixed(3)} s` : "paired observation recorded", { size: 13, weight: 600, fill: recordTone });
  g.append(record);
  move(record, MID, NET.chipY);
  const pk = packet(g, out.swap || out.label, out.swap ? C.fault : out.tone, { dashed: out.dashed || !!out.swap });
  const start = (NET.wrapper + NET.proxy) / 2, past = NET.proxy + 105;
  const divert = !!out.divert;
  return { tick(t) {
    // Across the boundary first; then towards the authorized receiver or, where the verifier
    // evidenced a destination divergence, down the branch to the unauthorized one.
    const k1 = ease(seg(t, 400, 2600)), k2 = seg(t, 3400, 6400);
    let x = lerp(start, past, k1), y = NET.lane;
    // The request stops at the receiver's edge and fades there, so it never covers the
    // receiver's labels; the destination fault drops down the branch beside the observation tag.
    if (k2 > 0) x = lerp(past, NET.branch, ease(seg(k2, 0, divert ? 0.4 : 1)));
    if (k2 > 0 && divert) y = lerp(NET.lane, NET.offY, ease(seg(k2, 0.4, 1)));
    move(pk, x, y);
    show(pk, 1 - seg(t, 6400, 7000));
    show(record, seg(t, 2400, 3000));
    fillBar.setAttribute("width", String(300 * seg(t, 500, 7500)));
  }, still: 3000 };
}

function sceneEvidence(g, f) {
  g.append(s("path", { d: `M${MID} 50 V${H - 48}`, stroke: C.line, "stroke-width": 1.2 }));
  text(g, 240, 46, "Approval and the system’s report", { size: 15, weight: 700, fill: C.a });
  text(g, 720, 46, "Independent activity record", { size: 15, weight: 700, fill: C.b });
  box(g, 70, 70, 150, 54, { title: "Safety check", sub: "Decision", tone: C.a });
  box(g, 260, 70, 150, 54, { title: "Send request", sub: "System’s report", tone: C.a });
  box(g, 645, 70, 150, 54, { title: "Activity monitor", sub: "Observed activity", tone: C.b });
  arrow(g, 145, 126, 215, 168, { tone: C.a });
  arrow(g, 335, 126, 265, 168, { tone: C.a });
  arrow(g, 720, 126, 720, 168, { tone: C.b });
  cylinder(g, 240, 180, 150, 64, "Record A", C.a);
  cylinder(g, 720, 180, 150, 64, "Record B", C.b);
  const pending = f.source === "live" ? "awaiting record" : "recorded at run time";
  const { observation } = f.ev;
  const rowsA = [
    `Decision: ${decisionLabel(f.decision) || pending}`,
    `Approved content: ${f.hmacA ? "fingerprint saved" : f.decision === "BLOCK" ? "nothing permitted" : f.source === "replay" ? "not recorded" : pending}`,
    `System report: ${f.claim ? humanize(f.claim) : pending}`,
  ];
  // Ledger B rows describe only the record that exists for this trace.
  const obsRow = { observed: f.observed ? `${f.observed.method} ${f.observed.endpoint_id} / ${f.observed.route_id}` : "recorded",
    paired: "paired by the verifier (details after export)", withheld: "kept, withheld from verifier",
    "scoped-absence": "none during the complete check", none: "no matching record",
    pending, design: "recorded at run time" }[observation];
  const hmacRow = observation === "observed" ? short(f.hmacB) || "not available" : observation === "paired" ? "available after export"
    : observation === "withheld" ? "hidden for this test" : ["none", "scoped-absence"].includes(observation) ? "not available" : observation === "pending" ? pending : "—";
  const rowsB = [`Activity: ${obsRow}`, `Observed content: ${observation === "observed" && f.hmacB ? "fingerprint saved" : hmacRow}`, `Monitoring records: ${f.health !== null ? f.health : pending}`];
  const list = (rows, x0) => rows.map((r, n) => text(g, x0, 300 + n * 26, r, { size: r.includes("HMAC") ? 13 : 14, anchor: "start", mono: r.includes("HMAC") }));
  const la = list(rowsA, 58), lb = list(rowsB, 538);
  const note = text(g, MID, H - 18, "Each record was written as its event happened; this scene summarises them.", { size: 13, fill: C.soft, halo: true });
  return { tick(t) {
    la.forEach((el, n) => show(el, seg(t, 900 + n * 900, 1400 + n * 900)));
    lb.forEach((el, n) => show(el, seg(t, 1350 + n * 900, 1850 + n * 900)));
    show(note, seg(t, 4500, 5200));
  } };
}

function sceneVerify(g, f) {
  cylinder(g, 150, 40, 130, 46, "Record A", C.a);
  cylinder(g, 810, 40, 130, 46, "Record B", C.b);
  arrow(g, 218, 80, 372, 116, { tone: C.a });
  arrow(g, 742, 80, 588, 116, { tone: C.b });
  box(g, MID - 110, 100, 220, 72, { title: "Compare records", sub: "Approval and activity", tone: C.ink });
  const cmp = f.comparison;
  const { observation } = f.ev;
  const pairing = { observed: "Paired by verifier", paired: "Paired by verifier", "scoped-absence": "None, as expected",
    withheld: "Withheld from verifier", none: "No corresponding observation" }[observation];
  const rows = cmp ? [["Same attempt", pairing], ["Destination", cmp.Destination], ["Action and route", cmp["Method / route"]],
    ["Content fingerprint", cmp["Payload commitment"]], ["System’s report", cmp["Runtime claim"]], ["Monitoring complete", f.coverage ? "Yes" : "Not established"]]
    : [["Same attempt", "compared"], ["Destination", "compared"], ["Action and route", "compared"], ["Content fingerprint", "compared"], ["System’s report", "compared"], ["Monitoring complete", "checked"]];
  const tone = (v) => (/Agrees|Equal|Compatible|Paired|Complete|as expected/.test(v) ? C.ok : /Withheld|Unavailable/.test(v) ? C.warn : /Diverges|Different|Incompatible|Not established|No corresponding/.test(v) ? C.bad : C.soft);
  const table = rows.map(([k, v], n) => {
    const row = s("g");
    text(row, 250, 0, k, { size: 14.5, anchor: "start", fill: C.soft });
    text(row, 520, 0, cmp ? v : f.source === "live" ? "awaiting verifier" : "computed at run time", { size: 14.5, anchor: "start", weight: 600, fill: cmp ? tone(v) : C.faint });
    move(row, 0, 262 + n * 26);
    g.append(row);
    return row;
  });
  const verdict = chip(g, OUTCOME_TEXT[f.result] || (f.source === "live" ? "Awaiting comparison" : "Result pending"), resultTone(f.result), { size: f.result ? 16 : 13, w: f.result ? 220 : null });
  move(verdict, MID, 212);
  const footer = f.result === "UNVERIFIED" ? "Verification incomplete: the evidence cannot establish agreement or divergence"
    : f.labels?.length ? f.labels.map(humanize).join(" · ") : null;
  const lab = footer ? text(g, MID, H - 12, footer, { size: 14, weight: 600, fill: resultTone(f.result) }) : null;
  return { tick(t) {
    table.forEach((row, n) => show(row, seg(t, 1200 + n * 600, 1600 + n * 600)));
    show(verdict, seg(t, 5600, 6300));
    if (lab) show(lab, seg(t, 6200, 6800));
  } };
}

// ---- captions: the written explanation under the canvas ----------------------------------
const RECORD_NAMES = { preparation: "preparation", proposal: "proposal", gateway: "gateway decision", execution: "runtime execution",
  observation: "proxy observation", drain: "monitoring-window", verification: "verifier" };

function awaitingCaption(need, f) {
  return `No ${RECORD_NAMES[need]} record has arrived${f.running ? " yet" : ", and the run has ended"}. Until it does, this scene shows only what will be checked; nothing in it is evidence of this run.`;
}

function caption(id, f) {
  switch (id) {
    case "task": return f.trust
      ? "The service owner approves one task for the assistant, with a short time limit and one use."
      : f.agentic ? "The AI assistant receives one task using sample information."
        : "A controlled test prepares one request. No AI model is used in this mode.";
    case "retrieval": return f.trust
      ? "The brief uses the information allowed for this task. Official figures are checked against the saved government source."
      : f.agentic ? "The assistant looks for relevant sample documents. This step is illustrated; no separate retrieval record is available."
        : "The test prepares the information directly, so no document search is needed.";
    case "proposal": return "One request is prepared for review. Preparing it does not give permission to send it.";
    case "gateway": return f.trust
      ? f.audit ? `${f.audit.attempts.filter(x => x.trust === "ACCEPTED").length} of ${f.audit.attempts.length} attempts passed the permission checks. Only accepted attempts could continue to the content check.`
        : "Check the agent’s identity and permission for this task. Refuse requests with invalid or withdrawn permission."
      : f.decision ? ({ ALLOW: "The content check approved this request for sending.", REDACT: "The content check removed confidential values before allowing the request.", BLOCK: "The content check refused this request. Nothing was approved for sending." })[f.decision]
        : "Check the destination and content. Decide whether to send, remove confidential information, or stop.";
    case "execution": {
      const out = emission(f);
      if (!out) return "The system reports that nothing was sent. The independent activity record is checked separately.";
      if (out.design) return "This preview shows the planned test. Recorded results establish what was sent.";
      if (out.unobserved) return "The system reported an attempt, but no matching activity record is available to confirm delivery.";
      return out.fault ? "A controlled test introduced a change after approval. The recorded evidence identifies the difference."
        : "The system reports what it attempted. A separate monitor records what it observed.";
    }
    case "monitoring": {
      const o = f.ev.observation;
      if (o === "design" || o === "pending") return "The independent monitor will record requests at this checkpoint. This preview does not confirm any activity.";
      if (o === "scoped-absence") return "The monitor was active for the full check period and saw no request for this attempt at this checkpoint.";
      if (o === "none") return "No matching activity record is available. The evidence cannot confirm whether a request was sent.";
      if (o === "withheld") return "The monitor recorded the request crossing the boundary. This test deliberately hides that record from the final comparison.";
      return "The independent monitor recorded the request crossing the boundary. This confirms observation at the checkpoint, not processing by a real service.";
    }
    case "evidence": return "Keep the approval and the system’s report in one record, and the independent observations in another. Compare them to check what happened.";
    case "verify": return !f.result ? "Compare approval with observed activity. Missing evidence leaves the result unconfirmed."
      : f.result === "UNVERIFIED" ? "Not confirmed: there is not enough evidence to decide whether activity matched approval."
        : f.result === "MISMATCH" ? "Difference found: the recorded activity did not match the approved action."
          : f.decision === "BLOCK" ? "Matches approval: no request was observed at this checkpoint during the fully monitored period."
            : "Matches approval: the observed request agreed with what was permitted.";
  }
  return "";
}

function technicalCaption(id, f) {
  const d = f.decision, r = f.result;
  switch (id) {
    case "task": return f.trust
      ? "A portal issuer gives the citizen-service assistant one Ed25519-signed capability for a single task: post a scripted RS-1042 notice or a live pilot workload brief to the authorized collector within 120 seconds. The audit identifies whether proposals came from the scripted checks or Qwen3."
      : f.agentic ? `The operator starts the run and the agent worker receives one frozen task (${f.sc.engine.live_case}). In ${f.mode === "live" ? "Live mode the real Qwen3 model" : "stub mode a fixed deterministic proposal"} will answer it.`
        : `The laboratory harness receives the case definition for ${humanize(f.engine)}. No model is involved: the harness constructs the request itself so the condition is exactly reproducible.`;
    case "retrieval": return f.agentic
      ? "The retriever ranks the synthetic corpus and hands the relevant records to the agent. The platform receives no intermediate events from the worker, so retrieval is shown as a step of the proposal stage, not as separately recorded evidence."
      : f.trust ? "Scripted checks use synthetic RS-1042. Live Qwen3 selects the latest year and count from the bundled GDRFA Dubai snapshot. The runner checks both fields before signing the sandbox brief." : "No retrieval in controlled lab mode. The harness generates the request body, choosing a registered value by case number where the situation needs one.";
    case "proposal": return `${f.agentic ? "The agent" : f.trust ? "The assistant" : "The harness"} proposes one structured action. ${f.hits ? (f.hits.length ? `Ledger A records ${f.hits.length} registered value${f.hits.length > 1 ? "s" : ""} by ID (${f.hits.map((x) => x.protected_id).join(", ")}), never the value.` : "Ledger A records no registered values in the proposal.") : "Protected values are only ever shown by registry ID."}`;
    case "gateway": return f.trust
      ? `The trust validator checks identity, signature, scope, expiry, replay and revocation before the research gateway is consulted. ${f.audit ? `${f.audit.attempts.filter((x) => x.trust === "ACCEPTED").length} of ${f.audit.attempts.length} attempts were accepted; only accepted attempts reach the gateway, which decided ${d || "—"}.` : "Each attempt's outcome comes from the trust audit after the run."}`
      : d ? `The gateway evaluated schema, destination, method, route and protected content, and recorded ${d}${f.reason ? ` (${humanize(f.reason)})` : ""} in Ledger A before anything was sent. The checks stay inside the gateway; only the decision travels on.`
        : f.source === "live" ? "Waiting for the gateway's record. In lab mode the harness authorizes, emits and waits out the observation window in one call, so the gateway, execution and monitoring records arrive together when it returns."
          : "The gateway evaluates schema, destination, method, route and protected content against the policy. The decision is computed when the scenario runs; this page cannot choose it.";
    case "execution": { const out = emission(f);
      if (!out) return d === "BLOCK" ? "BLOCK stops normal emission: no permitted request exists, so the wrapper sends nothing and records a NOT_EXECUTED claim."
        : "The runtime reports that it sent nothing (NOT_EXECUTED), and no observation contradicts that claim.";
      if (out.design) return `${out.fault ? `${out.fault}. ` : ""}The tool wrapper sends only what the gateway permits, and the runtime records its own claim. What actually leaves is established only by the proxy's record after a run.`;
      if (out.unobserved) return `The runtime claims ${humanize(f.claim)}${f.errorCategory ? ` (${humanize(f.errorCategory)})` : ""}. A claim is the runtime's own report: no corresponding proxy observation exists, so the request is drawn only as far as the tool's hand-off.`;
      return `${out.fault ? `Controlled laboratory fault, evidenced by the verifier: ${out.fault.toLowerCase()}. ` : ""}${d === "REDACT" && !out.swap ? "The authorized, sanitized body continues, not the original proposal. " : ""}The runtime records its own claim${f.claim ? ` (${humanize(f.claim)})` : ""}. A claim is a report, not an observation.`; }
    case "monitoring": { const o = f.ev.observation;
      if (o === "design") return "Every request that leaves must cross this monitored boundary, where mitmproxy records it and computes its own HMAC of the body it sees. Before a run nothing has crossed, so nothing is drawn crossing.";
      if (o === "scoped-absence") return `Nothing was observed carrying this trace, and the verifier found complete health coverage of the ${f.window} s window. This is scoped to this proxy boundary, not proof of host-wide absence.`;
      if (o === "none") return `No corresponding proxy observation is available${f.diagnosticNotes.length ? `, and the monitoring evidence is incomplete (${f.diagnosticNotes.map((x) => humanize(x.code)).join(", ")})` : ""}. Network transmission can be neither established nor excluded from this evidence${f.claim ? `; the runtime's claim (${humanize(f.claim)}) is its own report, not an observation` : ""}.`;
      if (o === "withheld") return "The request crossed the boundary and the proxy's record is kept in Ledger B, but the laboratory harness withholds it from the verifier's input to demonstrate evidence loss.";
      return `The proxy recorded the request crossing the monitored boundary and computed its own HMAC of the body it saw${f.offset !== null ? `, ${f.offset.toFixed(3)} s after the decision` : ""}. Observation proves the request crossed this boundary; it does not show how the receiver processed it.`; }
    case "evidence": return `Ledger A holds what the gateway decided and what the runtime claimed. Ledger B holds what the independent proxy observed and its health journal${["none", "scoped-absence"].includes(f.ev.observation) ? "; here it holds no observation for this trace" : ""}. Separate writers, separate files, no plaintext bodies: only registry IDs and keyed fingerprints.`;
    case "verify": { if (!r) return "The verifier pairs Ledger A and Ledger B by trace and clock, compares attributes and commitments and checks coverage. It, not this page, produces MATCH, MISMATCH or UNVERIFIED.";
      const o = f.ev.observation;
      const how = ["observed", "paired"].includes(o) ? "The verifier paired the records by trace and monotonic clock and compared destination, method, route, compatible body commitments, the claim and coverage"
        : o === "withheld" ? "The verifier's input held no observation for this trace, so it could not compare the planes"
          : o === "scoped-absence" ? "The verifier found no observation carrying this trace and complete monitoring coverage of the window"
            : "The verifier found no corresponding observation and could not establish complete monitoring coverage";
      const why = r === "UNVERIFIED" ? ` Verification is incomplete${f.diagnosticNotes.length ? ` because of: ${f.diagnosticNotes.map((x) => (x.text && x.text !== x.code ? x.text.replace(/\.$/, "") : humanize(x.code))).join("; ")}` : ""}. UNVERIFIED is an evidence gap, neither a leak nor containment.`
        : r === "MATCH" && d === "BLOCK" ? " BLOCK with MATCH means scoped non-emission at this proxy during the window." : "";
      return `${how}, and concluded ${r}${f.labels?.length ? ` (${f.labels.map(humanize).join(", ")})` : ""}.${why}`; }
  }
  return "";
}

// ---- player ------------------------------------------------------------------------------
export function createStage(sc, mode) {
  let f = facts(sc, mode);
  let index = 0, t = 0, playing = false, speed = 1, raf = 0, last = 0, built = null, builtKey = "";
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const svg = s("svg", { class: "stage-svg", viewBox: `0 0 ${W} ${H}`, role: "img" },
    s("defs", null, s("marker", { id: "xs-head", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
      s("path", { d: "M0 0 L10 5 L0 10 z", fill: C.faint }))),
    s("rect", { x: 0, y: 0, width: W, height: H, fill: C.bg }));
  const layer = s("g");
  const htmlScene = h("div", { class: "stage-html", hidden: true });
  svg.append(layer);
  const kicker = h("span", { class: "stage-kicker" });
  const title = h("h3", null);
  const source = h("span", { class: "stage-source" });
  const steps = h("ol", { class: "stage-steps", "aria-label": "Scenes" });
  const capText = h("p", { class: "stage-caption", "aria-live": "polite" });
  const technicalText = h("p", null);
  const technicalDetails = disclosure("Technical details", technicalText);
  // userPaused records an explicit Pause; backend polling never overrides it.
  let userPaused = false;
  const playBtn = h("button", { class: "btn small", type: "button", onclick: () => { userPaused = playing; if (playing) pause(); else play(); } });
  const prevBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => go(index - 1), "aria-label": "Previous scene" }, icon("chevron", 14), "Previous");
  const nextBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => go(index + 1), "aria-label": "Next scene" }, "Next", icon("chevron", 14));
  const resetBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => { userPaused = false; go(0); play(); } }, "Restart");
  const speedSel = h("select", { "aria-label": "Animation speed", onchange: (e) => { speed = Number(e.target.value); } },
    SPEEDS.map(([v, l]) => h("option", { value: v, selected: v === "1" || null }, `${l} speed`)));
  prevBtn.firstChild.style.transform = "rotate(180deg)";
  SCENES.forEach((x, n) => steps.append(h("li", null, h("button", { type: "button", title: x.title, "aria-label": `Scene ${n + 1}: ${x.title}`, onclick: () => go(n) },
    h("span", { class: "n" }, String(n + 1)), h("span", { class: "t" }, x.short)))));
  const controls = h("div", { class: "stage-controls" }, prevBtn, playBtn, nextBtn, resetBtn, speedSel);
  const presentation = sc.group === "trust";
  const root = h("section", { class: "stage", "aria-label": "Execution walkthrough" },
    h("div", { class: "stage-head" }, h("div", null, kicker, title), source),
    presentation ? controls : null,
    h("div", { class: "stage-canvas" }, svg, htmlScene),
    steps, capText, technicalDetails,
    presentation ? null : controls);
  root.addEventListener("keydown", (e) => {
    if (e.target.closest("select")) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(index + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(index - 1); }
  });

  // The furthest scene the evidence supports. Preview and replay can show all eight.
  const limit = () => {
    if (f.source !== "live") return SCENES.length - 1;
    let n = -1;
    while (n < SCENES.length - 1 && f.done(NEEDS[n + 1])) n++;
    return Math.min(n + 1, SCENES.length - 1);  // the next scene is shown in its awaiting state
  };
  const awaiting = () => f.source === "live" && !f.done(NEEDS[index]);

  function build() {
    const key = `${index}|${JSON.stringify([f.source, f.decision, f.claim, f.ev, f.result, !!f.comparison, !!f.audit])}`;
    if (key === builtKey) return;
    builtKey = key;
    fill(layer);
    const htmlBuilder = index === 2 ? sceneProposal : index === 3 && f.trust ? sceneTrustGate : null;
    htmlScene.hidden = !htmlBuilder;
    svg.style.display = htmlBuilder ? "none" : "";
    fill(htmlScene);
    built = htmlBuilder ? htmlBuilder(htmlScene, f) : SCENES[index].build(layer, f);
    const sceneSource = f.source === "replay" ? "Recorded demonstration" : f.source === "live" ? (awaiting() ? "Awaiting record" : "Current run") : "Preview";
    kicker.textContent = `Scene ${index + 1} of ${SCENES.length}`;
    title.textContent = SCENES[index].title;
    source.textContent = sceneSource;
    source.className = `stage-source ${f.source}${awaiting() ? " awaiting" : ""}`;
    capText.textContent = awaiting() ? awaitingCaption(NEEDS[index], f) : caption(SCENES[index].id, f);
    technicalText.textContent = technicalCaption(SCENES[index].id, f);
    svg.setAttribute("aria-label", `${SCENES[index].title}. ${capText.textContent}`);
    [...steps.children].forEach((li, n) => {
      li.className = n === index ? "current" : n < index ? "seen" : "";
      li.firstChild.disabled = n > limit() || null;
      li.firstChild.setAttribute("aria-current", n === index ? "step" : "false");
    });
    prevBtn.disabled = index === 0 || null;
    nextBtn.disabled = index >= limit() || null;
  }
  function frame(now) {
    const dt = last ? now - last : 0;
    last = now;
    if (playing) {
      t += dt * speed;
      if (t >= BASE) {
        if (index < limit() && !awaiting()) { index++; t = 0; }
        else if (awaiting()) t = BASE;  // hold; the "Awaiting backend record" badge pulses
        else { t = BASE; pause(); }
      }
    }
    build();
    built?.tick(reduced ? built.still ?? BASE : Math.min(t, BASE));
    raf = playing ? requestAnimationFrame(frame) : 0;
  }
  function kick() { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } }
  function play() {
    if (t >= BASE && !awaiting()) {
      if (index >= limit()) index = 0;
      t = 0;
    }
    playing = true;
    playBtn.replaceChildren(icon("pause", 13), "Pause");
    kick();
  }
  function pause() { playing = false; playBtn.replaceChildren(icon("play", 13), "Play"); }
  // Paused stepping shows each scene's key frame (its still), not a blank first frame.
  function go(n) {
    index = Math.max(0, Math.min(n, limit())); builtKey = ""; build();
    t = playing && !reduced ? 0 : built?.still ?? BASE;
    built?.tick(t);
    if (playing) kick();
  }
  pause();
  build();
  t = built.still ?? BASE;
  built.tick(t);

  return {
    root,
    // Feed new evidence. Live records advance the scene the evidence supports; a finished
    // replay starts again from the first scene.
    update(data, { restart = false } = {}) {
      f = facts(sc, mode, data);
      builtKey = "";
      if (restart) { userPaused = false; index = 0; t = 0; builtKey = ""; if (reduced) { pause(); go(0); } else play(); return; }
      if (f.source === "live" && !playing && !userPaused && index < limit()) play();
      build();
      built?.tick(Math.min(t, BASE));
      kick();
    },
    play, pause, destroy() { cancelAnimationFrame(raf); raf = 0; playing = false; },
  };
}
