// Browser regression checks for the Scenario Lab stage and run view (audit findings F1-F3).
// Loaded by webapp/tests/test_ui_regressions.py in headless Edge or Chrome against the real
// modules; results are written as JSON into #result. No network: fetch is replaced.
import { createStage } from "../views/stage.js";

const realFetch = window.fetch.bind(window);

const STAGES = ["environment", "preparation", "proposal", "gateway", "execution", "observation", "drain", "verification", "export"];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const record = (done, status = "running") => ({
  run_id: "run-20261101-000000-0000abcd", scenario_id: "transmission-after-rejection", scenario_title: "Transmission after an authorization rejection",
  mode: "lab", protocol: "http", protected_item: null, claim_mode: "plausible", origin: "Controlled fault injection",
  status, created: Date.now() / 1000, finished: status === "running" ? null : Date.now() / 1000, error: null,
  stages: STAGES.map((id) => ({ id, label: id, status: done.includes(id) ? "complete" : "pending", detail: "",
    facts: id === "gateway" && done.includes(id) ? { decision: "BLOCK" } : {} })),
});
const BYPASS = { id: "transmission-after-rejection", number: 4, title: "Transmission after an authorization rejection", group: "fault",
  origin: "Controlled fault injection", story: "", question: "", policy: "", components: [], evidence: [], modes: ["lab"],
  uses_protected_item: true, protected_items: [], claim_mode_supported: true, note: "", guides: ["block-bypass"],
  sources: ["DOC_001:chunk_1"], engine: { lab_scenario: "block_bypass", live_case: null, payload_subtype: null } };
// Only text a viewer can see counts: an element faded to opacity 0 is not a claim.
const visible = (el, stop) => { for (let n = el; n && n !== stop; n = n.parentNode) if (n.getAttribute && Number(n.getAttribute("opacity") ?? 1) < 0.05) return false; return true; };
const svgText = (stage) => { const svg = stage.root.querySelector("svg"); return [...svg.querySelectorAll("text")].filter((t) => visible(t, svg)).map((t) => t.textContent).join(" | "); };
const scene = (stage, n) => stage.root.querySelectorAll(".stage-steps button")[n].click();
const playButton = (stage) => [...stage.root.querySelectorAll(".stage-controls button")].find((b) => /Play|Pause/.test(b.textContent));
const FAULT = /blocked body|LAB FAULT|harness emits/i;

async function f1() {
  const out = {};
  const stage = createStage(BYPASS, "lab");
  document.body.append(stage.root);
  stage.update({ record: record(["environment", "preparation", "proposal", "gateway"]) });
  scene(stage, 4);
  out.execution_pending_badge = stage.root.querySelector(".stage-source").textContent;
  out.execution_pending_asserts_fault = FAULT.test(svgText(stage));
  out.execution_pending_caption_names_record = /No runtime execution record/.test(stage.root.querySelector(".stage-caption").textContent);
  stage.update({ record: record(["environment", "preparation", "proposal", "gateway", "execution"]) });
  scene(stage, 5);
  out.observation_pending_asserts_crossing = /POST |withheld from verifier|own HMAC/.test(svgText(stage));
  // A fault is evidenced by the verifier's label, not by the execution record: before the
  // verification record it must not be asserted; with BLOCK_BYPASS it is shown.
  scene(stage, 4);
  out.fault_shown_before_verifier_label = /LAB FAULT|blocked body/.test(svgText(stage));
  const verified = record(["environment", "preparation", "proposal", "gateway", "execution", "observation", "drain", "verification"]);
  verified.stages.find((x) => x.id === "observation").facts = { paired: true };
  verified.stages.find((x) => x.id === "verification").facts = { result: "MISMATCH", evidence_status: "VERIFIED", labels: ["BLOCK_BYPASS"] };
  stage.update({ record: verified });
  stage.pause();
  scene(stage, 4);
  out.fault_shown_after_verifier_label = /LAB FAULT/.test(svgText(stage)) && /blocked body/.test(svgText(stage));
  stage.destroy();
  const failed = createStage(BYPASS, "lab");
  document.body.append(failed.root);
  failed.update({ record: record(["environment", "preparation", "proposal", "gateway"], "failed") });
  scene(failed, 4);
  out.failed_run_asserts_fault = FAULT.test(svgText(failed));
  failed.destroy();
  out.pass = out.execution_pending_badge === "Awaiting record" && !out.execution_pending_asserts_fault
    && out.execution_pending_caption_names_record && !out.observation_pending_asserts_crossing
    && !out.fault_shown_before_verifier_label && out.fault_shown_after_verifier_label && !out.failed_run_asserts_fault;
  return out;
}

async function f2() {
  const out = {};
  const stage = createStage(BYPASS, "lab");
  document.body.append(stage.root);
  const early = record(["environment", "preparation", "proposal"]);
  stage.update({ record: early });
  const button = playButton(stage);
  out.autoplay = button.textContent;
  button.click();
  out.after_user_pause = button.textContent;
  for (let i = 0; i < 3; i++) stage.update({ record: early });
  out.after_identical_polls = button.textContent;
  stage.update({ record: record(["environment", "preparation", "proposal", "gateway"]) });
  out.after_new_stage_record = button.textContent;
  button.click();
  out.after_user_play = button.textContent;
  stage.destroy();
  out.pass = out.autoplay === "Pause" && out.after_user_pause === "Play" && out.after_identical_polls === "Play"
    && out.after_new_stage_record === "Play" && out.after_user_play === "Pause";
  return out;
}

// ---- evidence-state matrix ------------------------------------------------------------------
// Each case is real (or explicitly derived) evidence written by the test into fixtures.json.
// Scenes 5-8 must never claim more than the evidence establishes.
function packetBeyondBoundary(stage) {
  return [...stage.root.querySelectorAll("svg rect[width='144'][height='34']")].some((r) => {
    const g = r.parentNode;
    if (Number(g.getAttribute("opacity") ?? 1) < 0.05) return false;
    const m = /translate\(([-\d.]+)/.exec(g.getAttribute("transform") || "");
    return m && Number(m[1]) > 480;
  });
}

async function matrix() {
  const data = await (await realFetch("fixtures.json")).json();
  const results = [];
  for (const c of data.cases) {
    const sc = data.scenarios.find((x) => x.id === c.scenario_id);
    const stage = createStage(sc, c.mode);
    document.body.append(stage.root);
    stage.update(c.data);
    stage.pause();
    const at = (n) => { scene(stage, n); return { svg: svgText(stage), caption: stage.root.querySelector(".stage-caption").textContent, beyond: packetBeyondBoundary(stage) }; };
    const s5 = at(4), s6 = at(5), s7 = at(6), s8 = at(7);
    stage.destroy(); stage.root.remove();
    const got = {
      crossed: s6.beyond || /POST |GET |own HMAC|paired observation recorded|kept, withheld/.test(s6.svg),
      captionCrossed: /crossed the boundary|recorded the request crossing/.test(s6.caption),
      hmacB: /Observed content: fingerprint saved/.test(s7.svg),
      scoped: /No request for this attempt/.test(s6.svg),
      noObs: /No matching activity record/.test(s6.svg),
      labFault: /LAB FAULT/.test(s5.svg),
      incomplete: /Not confirmed:/.test(s8.caption),
    };
    const mismatches = Object.entries(c.expect).filter(([k, v]) => got[k] !== v).map(([k, v]) => `${k}: expected ${v}, got ${got[k]}`);
    results.push({ name: c.name, pass: mismatches.length === 0, mismatches });
  }
  return { cases: results.length, failed: results.filter((r) => !r.pass), pass: results.length > 0 && results.every((r) => r.pass) };
}

async function f3() {
  // The real #/run/<id> route: lab() renders the run view; state.cleanup is what the router
  // calls on leaving. Intervals and timeouts are counted while it runs.
  const live = new Set(), timeouts = new Set();
  const realSet = window.setInterval, realClear = window.clearInterval;
  const realTimeout = window.setTimeout, realClearTimeout = window.clearTimeout;
  window.setInterval = (fn, ms) => { const id = realSet(fn, ms); live.add(id); return id; };
  window.clearInterval = (id) => { live.delete(id); realClear(id); };
  window.setTimeout = (fn, ms) => { const id = realTimeout(() => { timeouts.delete(id); fn(); }, ms); timeouts.add(id); return id; };
  window.clearTimeout = (id) => { timeouts.delete(id); realClearTimeout(id); };
  const running = record(["environment", "preparation"]);
  window.fetch = async (url) => {
    const body = String(url).startsWith("/api/runs/") ? running : String(url) === "/api/cases" ? { cases: [], types: {}, incomplete: [], issues: [] } : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const { lab } = await import("../views/lab.js");
  const out = { visits: [] };
  const state = { scenarios: { scenarios: [BYPASS], groups: [] }, status: { modes: { lab: { ready: true } }, run_owner: true }, cleanup: null };
  for (let visit = 1; visit <= 3; visit++) {
    const page = document.createElement("div");
    document.body.append(page);
    await lab(page, ["run", running.run_id], state);
    await wait(1500);
    const viewing = live.size;
    state.cleanup();
    state.cleanup = null;
    page.remove();
    await wait(1500);
    out.visits.push({ visit, intervals_while_viewing: viewing, intervals_after_leaving: live.size, poll_timers_after_leaving: timeouts.size });
  }
  window.setInterval = realSet; window.clearInterval = realClear;
  window.setTimeout = realTimeout; window.clearTimeout = realClearTimeout;
  out.pass = out.visits.every((v) => v.intervals_while_viewing === 1 && v.intervals_after_leaving === 0 && v.poll_timers_after_leaving === 0);
  return out;
}

async function routes() {
  const responses = await (await realFetch("routes.json")).json();
  window.fetch = async url => {
    const key = decodeURIComponent(String(url));
    if (!(key in responses)) throw new Error("Unrecorded API: " + key);
    return new Response(JSON.stringify(responses[key]), {status:200,headers:{"Content-Type":"application/json"}});
  };
  const { lab } = await import("../views/lab.js");
  const { overview } = await import("../views/overview.js");
  const { investigate } = await import("../views/investigate.js");
  const { research } = await import("../views/research.js");
  const { learn } = await import("../views/learn.js");
  const state = {scenarios:responses["/api/scenarios"],status:{modes:{lab:{ready:true}},items:[]}};
  const { state: appState } = await import("../app.js");
  appState.status = state.status;
  const broken = [];
  const checks = [[overview,[]],[lab,[]],[lab,["permissions"]],[lab,["network"]],[lab,["government-trust","demo"]],[investigate,[]],[research,[]],[learn,[]]];
  for (const sc of state.scenarios.scenarios) checks.push([lab,[sc.id]]);
  const id = "run-20261110-061514-a6a55157";
  checks.push([lab,["run",id]]);
  let outcomeBeforeStage = false, retryHidden = false;
  for (const [view,args] of checks) {
    const page = document.createElement("div"); document.body.append(page);
    await view(page,args,state);
    const walker = document.createTreeWalker(page,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()) if (/^(null|false|undefined)$/.test(walker.currentNode.textContent.trim())) broken.push([view.name,args]);
    if(args[0] === "run") {
      const summary=page.querySelector(".government-brief"), stage=page.querySelector(".stage");
      outcomeBeforeStage=Boolean(summary && summary.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING);
      retryHidden=!page.querySelector(".government-brief").textContent.includes("Earlier version");
    }
    state.cleanup?.(); state.cleanup=null; page.remove();
  }
  return {pass:broken.length===0 && outcomeBeforeStage && retryHidden, broken, outcomeBeforeStage, currentBinding:retryHidden, routes:checks.length};
}

async function architectureChecks() {
  const {architecture,componentDetail}=await import("../components.js");
  let selected=null;
  const diagram=architecture(id=>{selected=id;componentDetail(id);},null);
  document.body.append(diagram);
  const nodes=[...diagram.querySelectorAll('[role="button"]')];
  let passed=0;
  for(const node of nodes) {
    selected=null;node.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter"}));
    const keyboard=Boolean(selected);selected=null;node.dispatchEvent(new MouseEvent("click"));
    if(keyboard && selected && node.getAttribute("tabindex")==="0") passed++;
  }
  diagram.remove();return {pass:passed===14,passed,total:nodes.length};
}

const result = {};
for (const [name, check] of [["F1", f1], ["F2", f2], ["MATRIX", matrix], ["F3", f3], ["ROUTES", routes], ["ARCHITECTURE", architectureChecks]]) {
  try { result[name] = await check(); } catch (error) { result[name] = { pass: false, error: String(error && error.stack || error) }; }
}
document.getElementById("result").textContent = JSON.stringify(result);
