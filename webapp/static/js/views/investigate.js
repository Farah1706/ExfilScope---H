// Investigations: find a case, open it, examine its evidence, reach a supported conclusion.
// The case browser is one navigation index over separate collections. Counts beside each
// filter value describe the listed rows; outcome totals are shown only for a single
// collection, because collections from different experiments are never pooled.
import { h, appendContent, icon, badge, seal, mono, humanize, when, fill, disclosure } from "../dom.js";
import { get, csvUrl, PUBLIC } from "../api.js";
import { helpButton, pipeline, comparisonTable, timeline, coverageList, coverageComplete, hmacExplainer, checklist, kvList, guideDrawer } from "../components.js";

const TYPE_CLASS = { live: "teal", stub: "", lab: "", fault: "fault", trust: "ext" };
const SOURCE_TEXT = { historical: "Committed snapshot", "platform-run": "Platform run", "bundled-sample": "Bundled recording" };
const SITUATION = { allow: "routine-submission", redact: "confidential-request", block: "prohibited-transfer", block_bypass: "transmission-after-rejection",
  destination_divergence: "unexpected-destination", no_observation: "missing-observation" };

function band(outcomes, total) {
  return h("div", { class: "band", role: "img", "aria-label": `${outcomes.MATCH} match, ${outcomes.MISMATCH} mismatch, ${outcomes.UNVERIFIED} unverified` },
    ["MATCH", "MISMATCH", "UNVERIFIED"].map((k) => outcomes[k] ? h("span", { class: k, style: { width: `${(outcomes[k] / total) * 100}%` } }) : null));
}

export async function investigate(page, [collectionId, eventId]) {
  if (collectionId && eventId) return casePage(page, collectionId, eventId);
  if (collectionId === "incomplete") {
    if (!PUBLIC) { location.hash = "#/run"; return; }
    collectionId = null;
  }
  const index = await get("/api/cases");
  index.cases.sort((a, b) => Number(b.type === "trust") - Number(a.type === "trust") || (b.created || 0) - (a.created || 0));
  const f = { q: "", collection: collectionId && collectionId !== "incomplete" ? collectionId : "", type: "", result: "", protocol: "" };
  const types = index.types;
  const collections = [...new Map(index.cases.map((c) => [c.collection, c])).values()];
  const selectsHost = h("div", { class: "filter-selects" });
  const tbody = h("tbody");
  const count = h("p", { class: "small muted", "aria-live": "polite" });
  const scope = h("div");
  const casesPane = h("div");
  const search = h("input", { id: "f-q", type: "search", placeholder: "Trace, label, reason, situation…", oninput: (e) => { f.q = e.target.value; draw(); } });

  const matches = (c, skip = null) => (skip === "collection" || !f.collection || c.collection === f.collection)
    && (skip === "type" || !f.type || c.type === f.type) && (skip === "result" || !f.result || c.result === f.result)
    && (skip === "protocol" || !f.protocol || c.protocol === f.protocol)
    && (!f.q || [c.trace, c.event_id, c.scenario_title, c.collection_title, c.decision, ...c.labels, ...c.diagnostics].join(" ").toLowerCase().includes(f.q.toLowerCase()));
  // Each option shows how many listed cases it would leave; options that would leave none
  // are hidden unless selected, so "All" and a value never silently give the same list.
  const select = (key, label, options) => {
    const counts = new Map();
    for (const c of index.cases) if (matches(c, key)) counts.set(c[key], (counts.get(c[key]) || 0) + 1);
    const total = [...counts.values()].reduce((a, b) => a + b, 0);
    const shown = options.filter(([v]) => counts.get(v) || f[key] === v);
    return h("div", { class: "field" }, h("label", { for: `f-${key}` }, label),
      h("select", { id: `f-${key}`, onchange: (e) => { f[key] = e.target.value; draw(true); } },
        h("option", { value: "" }, `All (${total})`),
        shown.map(([v, t]) => h("option", { value: v, selected: f[key] === v || null }, `${t} (${counts.get(v) || 0})`))));
  };
  const draw = (focus = false) => {
    // Only the menus are rebuilt, so typing in the search field keeps focus and caret.
    const active = document.activeElement?.id;
    fill(selectsHost,
      select("collection", "Collection", collections.map((c) => [c.collection, `${c.collection_title}${c.source === "platform-run" ? ` · ${c.run_id}` : ""}`])),
      select("type", "Case type", Object.entries(types)),
      select("result", "Verifier result", [["MATCH", "Match"], ["MISMATCH", "Mismatch"], ["UNVERIFIED", "Unverified"]]),
      select("protocol", "Protocol", [["http", "HTTP"], ["https", "HTTPS"]]));
    if (focus && active) document.getElementById(active)?.focus();
    const rows = index.cases.filter((c) => matches(c));
    count.textContent = `${rows.length} of ${index.cases.length} validated cases listed${f.collection ? "" : `, from ${collections.length} separate collections`}.`;
    fill(tbody, ...(rows.length ? rows.map((c) => {
      const open = () => { location.hash = `#/investigate/${encodeURIComponent(c.collection)}/${c.event_id}`; };
      return h("tr", { class: "clickable", tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", null, h("div", null, c.scenario_title), mono(c.trace.slice(0, 8))),
        h("td", null, h("div", null, c.collection_title), h("span", { class: "small muted" }, c.created ? `${SOURCE_TEXT[c.source]}, ${when(c.created)}` : SOURCE_TEXT[c.source])),
        h("td", null, h("span", { class: `tag ${TYPE_CLASS[c.type]}` }, types[c.type])),
        h("td", null, h("span", { class: "decision" }, c.decision)), h("td", null, badge(c.result)),
        h("td", null, c.labels.map(humanize).join(", ") || h("span", { class: "muted" }, "None")), h("td", null, c.protocol.toUpperCase()));
    }) : [h("tr", null, h("td", { colspan: 7 }, h("div", { class: "empty" }, "No case matches these filters.")))]));
    drawScope();
  };
  let scoped = null;
  async function drawScope() {
    if (scoped === f.collection) return;
    scoped = f.collection;
    if (!f.collection) {
      fill(scope, h("p", { class: "small soft" }, "Select a collection to see its counts and export."));
      return;
    }
    const id = f.collection;
    let data;
    try { data = await get(`/api/investigations/${encodeURIComponent(id)}`); } catch { fill(scope, null); return; }
    if (f.collection !== id) return;
    const sm = data.summary;
    fill(scope, h("section", { class: "section-rule" },
      h("div", { class: "panel-head" }, h("div", null, h("h2", null, data.title), h("p", null, data.source)),
        h("a", { class: "btn small", href: csvUrl(id), download: "" }, icon("export", 14), "Export CSV")),
      h("div", { class: "stat-line" }, h("div", { class: "stat" }, h("b", null, String(sm.total)), h("span", null, "cases")),
        ["MATCH", "MISMATCH", "UNVERIFIED"].map((k) => h("div", { class: "stat" }, h("b", null, String(sm.outcomes[k])), h("span", null, badge(k))))),
      h("div", { style: { margin: "16px 0 4px" } }, band(sm.outcomes, sm.total)),
      h("p", { class: "small muted", style: { marginTop: "8px" } }, "Counts describe this collection's records only. They are not accuracy metrics and are never research results.")));
  }

  fill(casesPane, scope, h("section", { class: "section-rule" },
    h("div", { class: "filters" }, h("div", { class: "field grow" }, h("label", { for: "f-q" }, "Search"), search), selectsHost), count,
    h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, ["Case", "Collection", "Type", "Decision", "Verifier", "Labels", "Protocol"].map((x) => h("th", null, x)))), tbody))),
  index.issues.length ? h("div", { class: "callout warn" }, h("p", null, index.issues.join(" "))) : null);
  appendContent(page,
    h("div", { class: "page-head" }, h("div", null, h("h1", null, "Investigations"),
      h("p", null, "Find a case and compare what the gateway allowed with what the monitor saw.")), helpButton("compare")),
    casesPane);
  draw();
}

function situationFor(i, data) {
  if (data.run?.scenario_id) return data.run.scenario_id;
  if (i.scenario === "payload_divergence") return i.runtime.decision === "REDACT" ? "redaction-reversed" : "modified-after-approval";
  return SITUATION[i.scenario] || null;
}

async function casePage(page, collectionId, eventId) {
  const data = await get(`/api/investigations/${encodeURIComponent(collectionId)}`);
  const index = data.incidents.findIndex((x) => x.runtime.event_id === eventId);
  if (index < 0) {
    appendContent(page, h("div", { class: "empty" }, h("h3", null, "Case not found in this collection"), h("a", { class: "btn", href: `#/investigate/${encodeURIComponent(collectionId)}` }, "Back to the collection")));
    return;
  }
  const i = data.incidents[index];
  const a = i.runtime, b = i.observation, v = i.verification;
  const go = (k) => { location.hash = `#/investigate/${encodeURIComponent(collectionId)}/${data.incidents[k].runtime.event_id}`; };
  const comp = i.comparison;
  const agreeFields = Object.entries(comp).filter(([, x]) => ["Agrees", "Equal", "Compatible with observed emission"].includes(x)).map(([k]) => k.toLowerCase());
  const differFields = Object.entries(comp).filter(([, x]) => ["Diverges", "Different", "Incompatible with observed emission"].includes(x)).map(([k]) => k.toLowerCase());
  const covered = coverageComplete(i);
  const facts = [
    ["Proposed action", `${a.proposed.method} to ${a.proposed.endpoint_id} / ${a.proposed.route_id}. ${a.hits.length ? `Registered values found: ${a.hits.map((x) => `${x.protected_id} at ${x.location}`).join(", ")}.` : "No registered values in the proposal."}`],
    ["Gateway decision", a.permitted ? `${a.decision}: ${a.permitted.method} to ${a.permitted.endpoint_id} / ${a.permitted.route_id} permitted (${humanize(a.reason)}, policy ${a.policy_version}).` : `${a.decision}: nothing permitted (${humanize(a.reason)}, policy ${a.policy_version}).`],
    ["Runtime claim", `${i.claim_text} (${a.claim})${a.response_status ? `, response ${a.response_status}` : ""}. The runtime's own report, not an observation.`],
    ["Independent observation", b ? `mitmproxy saw ${b.observed.method} to ${b.observed.endpoint_id} / ${b.observed.route_id}, ${i.observed_offset_s.toFixed(3)} s after the decision.` : i.absence_explanation],
    ["Monitoring evidence", covered ? `Complete for the ${i.window_seconds} s window: ${i.health_records} health records, no coverage diagnostics.` : `Not established: ${i.diagnostic_notes.filter((d) => d.code !== "SCOPED_PROXY_ABSENCE").map((d) => d.text).join(" ") || v.evidence_status}`],
    ["Agreement", !b ? "No comparison is possible without a paired observation." : differFields.length ? `Diverge on ${differFields.join(", ")}${agreeFields.length ? `; agree on ${agreeFields.join(", ")}` : ""}.` : `Agree on ${agreeFields.join(", ") || "every compared field"}.`],
  ];
  const tabs = [
    ["compare", "Ledger comparison", () => h("div", null, h("div", { class: "spread", style: { marginBottom: "12px" } }, h("p", { class: "soft small", style: { margin: 0 } }, "Each row pairs one field of the permitted request with the observed one."), helpButton("compare")), comparisonTable(i))],
    ["pipeline", "Evidence pipeline", () => h("div", null, h("div", { class: "spread", style: { marginBottom: "12px" } }, h("p", { class: "soft small", style: { margin: 0 } }, "Proposed, decided, permitted and claimed come from Ledger A; observed from Ledger B. Select a stage."), helpButton("pipeline")), pipeline(i))],
    ["a", "Ledger A", () => kvList([["Event ID", mono(a.event_id)], ["Trace ID", mono(a.trace_id)], ["Session", mono(a.session_id)], ["Proposed", `${a.proposed.method} ${a.proposed.endpoint_id} / ${a.proposed.route_id}`],
      ["Protected hits", a.hits.length ? a.hits.map((x) => `${x.protected_id} (${x.data_type}) from ${x.source_ref} at ${x.location}`).join("; ") : "None"],
      ["Decision", `${a.decision} (${a.reason})`], ["Policy version", a.policy_version], ["Permitted", a.permitted ? `${a.permitted.method} ${a.permitted.endpoint_id} / ${a.permitted.route_id}` : "None"],
      ["Body fingerprint", seal(a.payload_hmac)], ["Key / canonicalization", `${a.key_id} / ${a.canonicalization_version}`], ["Claim", a.claim], ["Error category", a.error_category || "None"],
      ["Response status", a.response_status ?? "None"], ["Decision time", i.recorded_utc], ["Completion time", i.completed_utc], ["Host / clock domain", `${a.host_id} / ${a.clock_domain_id}`]])],
    ["b", "Ledger B", () => b ? kvList([["Event ID", mono(b.event_id)], ["Trace ID", mono(b.trace_id)], ["Observed", `${b.observed.method} ${b.observed.endpoint_id} / ${b.observed.route_id}`],
      ["Body fingerprint", seal(b.payload_hmac)], ["Key / canonicalization", `${b.key_id} / ${b.canonicalization_version}`], ["Request size", `${b.request_size} bytes`],
      ["Response status", b.response_status ?? "None"], ["Anomalies", b.anomalies.join(", ") || "None"], ["Request time", i.observed_utc], ["Offset from decision", `${i.observed_offset_s.toFixed(6)} s (monotonic)`],
      ["Host / clock domain", `${b.host_id} / ${b.clock_domain_id}`]]) : h("div", { class: `callout ${i.observation_withheld ? "warn" : ""}` }, icon(i.observation_withheld ? "withheld" : "info", 18), h("p", null, i.absence_explanation))],
    ["timing", "Timing and coverage", () => h("div", null, h("div", { class: "spread" }, h("h3", null, "Observation window"), helpButton("timeline")), timeline(i), h("h3", { style: { margin: "20px 0 8px" } }, "Monitoring coverage"), coverageList(i),
      h("p", { class: "small soft", style: { marginTop: "12px" } }, "A missing event does not prove a request was blocked or never sent. Absence can be stated only when the verifier itself reports SCOPED_PROXY_ABSENCE under complete coverage."))],
    ["hmac", "Body fingerprints", () => h("div", null, h("div", { class: "spread", style: { marginBottom: "12px" } }, h("p", { class: "soft small", style: { margin: 0 } }, "HMAC-SHA-256(K, CanonicalJSON(body)), computed separately by the gateway and by the proxy."), helpButton("hmac")), hmacExplainer(i))],
    ["tech", "Technical record", () => h("div", null, h("p", { class: "small soft" }, "The validated, minimized record exactly as exported. It holds no protected values, keys or bodies."),
      h("pre", { class: "sunken", style: { fontSize: "12px", maxHeight: "480px", overflow: "auto" } }, JSON.stringify({ trust: trustAttempt, data_mandate: trustAudit?.data_mandate, runtime: a, observation: b, verification: v, window_seconds: i.window_seconds, health_records: i.health_records, monitor_generations: i.monitor_generations, observation_withheld: i.observation_withheld }, null, 2)))],
  ];
  let activeTab = "compare";
  const tabBar = h("div", { class: "tabs", role: "tablist" });
  const tabPanel = h("div", { role: "tabpanel" });
  const showTab = (id) => {
    activeTab = id;
    for (const btn of tabBar.children) btn.setAttribute("aria-selected", String(btn.dataset.id === id));
    fill(tabPanel, tabs.find((t) => t[0] === id)[2]());
  };
  tabs.forEach(([id, label]) => tabBar.append(h("button", { role: "tab", type: "button", dataset: { id }, "aria-selected": "false", onclick: () => showTab(id),
    onkeydown: (e) => { const k = tabs.findIndex((t) => t[0] === activeTab); const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0; if (step) { const n = (k + step + tabs.length) % tabs.length; showTab(tabs[n][0]); tabBar.children[n].focus(); } } }, label)));
  const situation = situationFor(i, data);

  let trustAudit = null;
  if (data.run?.mode === "trust") trustAudit = await get("/api/trust/" + data.run.run_id).catch(() => null);
  const trustAttempt = trustAudit?.attempts.find(x => x.runtime_event_id === eventId);
  const destination = m => m.endpoint_id === "AUTHORIZED" && m.route_id === "COLLECT" ? m.method + " to the approved sandbox collector" : m.method + " " + m.endpoint_id + " / " + m.route_id;
  const comparison = [
    ["Attempt", destination(a.proposed)],
    ["Permission", a.permitted ? a.decision + " · " + destination(a.permitted)
      : a.decision + " · no request permitted"],
    ["Runtime claim", i.claim_text],
    ["Independent observation", b ? destination(b.observed) : i.absence_explanation],
    ["Conclusion", [badge(v.result), " ", i.verdict_sentence]],
  ];
  if (trustAttempt) comparison.splice(2, 0, ["Authority & data check", `Agent ${trustAttempt.grant?.agent_id || trustAudit.agent_id}: signed task permission accepted. ${trustAttempt.grounding_checks?.includes("SOURCE_AND_PAYLOAD_BOUND") ? "Official figures matched the pinned source cells and the exact outgoing brief." : "This earlier recording does not establish structured source binding."} Exact scope and checks are in the technical record.`]);
  appendContent(page,
    h("div", { class: "crumbs" }, h("a", { href: "#/investigate" }, "Investigations"), " / ",
      h("a", { href: "#/investigate/" + encodeURIComponent(collectionId) }, data.title),
      " / Case " + (index + 1) + " of " + data.incidents.length),
    h("div", { class: "page-head" }, h("div", null, h("h1", null, trustAttempt ? "Government Trust · " + (a.decision === "ALLOW" ? "permitted request" : humanize(a.decision)) : i.scenario_title),
      h("p", null, i.display_origin + " · " + i.protocol.toUpperCase()))),
    h("section", { class: "section-rule" }, h("h2", null, "What happened"),
      h("dl", { class: "evidence-rows" }, comparison.map(([label, value]) =>
        h("div", null, h("dt", null, label), h("dd", null, value)))),
      h("p", { class: "small soft" }, "The runtime reports what it did. The independent monitor records what it observed.")),
    disclosure("Technical evidence",
      h("div", { class: "spread" }, h("p", { class: "small soft" }, "Trace ", mono(a.trace_id)),
        h("a", { class: "btn small", href: csvUrl(collectionId), download: "" }, "Export collection CSV")),
      tabBar, tabPanel,
      disclosure("Case facts and coverage",
        h("dl", { class: "evidence-rows" }, facts.map(([label, value]) =>
          h("div", null, h("dt", null, label), h("dd", null, value)))))),
    disclosure("Reasoning and limits",
      h("div", { class: "concl" },
        h("div", null, h("h3", null, "Why this result"), h("ul", null, i.why.map((x) => h("li", null, x)), i.findings.map((x) => h("li", null, x.text)))),
        h("div", null, h("h3", null, "Limits"), h("ul", null, i.limits.map((x) => h("li", null, x)), h("li", null, "Source references identify registry entries."))))),
    disclosure("Guided investigation checklist", helpButton("checklist"), checklist(i)),
    h("div", { class: "spread case-nav" },
      h("button", { class: "btn", type: "button", disabled: index === 0 || null, onclick: () => go(index - 1) }, "Previous case"),
      h("div", { class: "row" },
        situation ? h("a", { class: "btn ghost", href: `#/lab/${situation}/replay/${encodeURIComponent(collectionId)}/${a.event_id}` }, icon("play", 14), "Replay in the Scenario Lab") : null,
        h("button", { class: "btn ghost", type: "button", onclick: () => guideDrawer("interpretation") }, icon("book", 14), "How to interpret evidence"),
        h("a", { href: "#/lab/network" }, "Compare recorded outcomes")),
      h("button", { class: "btn", type: "button", disabled: index === data.incidents.length - 1 || null, onclick: () => go(index + 1) }, "Next case")));
  showTab("compare");
}
