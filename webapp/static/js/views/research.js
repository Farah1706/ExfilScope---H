import { GROUNDING_RETEST } from "../engineering-evidence.js";
import { h, appendContent, badge, disclosure } from "../dom.js";
import { get } from "../api.js";

const COLORS = { MATCH: "var(--match)", MISMATCH: "var(--mismatch)", UNVERIFIED: "var(--unverified)" };

function bars(outcomes, denominator) {
  return h("div", { class: "stack" }, Object.entries(outcomes).map(([k, n]) => h("div", { class: "bar-row" }, badge(k),
    h("div", { class: "bar", role: "img", "aria-label": `${n} of ${denominator}` }, h("span", { style: { width: `${(n / denominator) * 100}%`, background: COLORS[k] } })),
    h("span", { class: "num" }, String(n)))));
}

const prov = (...parts) => h("p", { class: "provenance" }, parts.filter(Boolean).join(". ") + ".");

export async function research(page) {
  const r = await get("/api/research");
  const cases = (await get("/api/cases")).cases;
  const evidence = [];
  const recordings = [];
  for (const id of new Set(cases.filter(c => c.type === "trust").map(c => c.run_id))) {
    const audit = await get("/api/trust/" + id).catch(() => null);
    if (audit?.data_mandate?.binding !== "structured-cells-v1") continue;
    const row = cases.find(c => c.run_id === id);
    recordings.push({ audit, row });
    evidence.push(h("tr", null, h("th", { scope: "row" }, audit.operator_events?.length ? "Qwen3 · revocation and recovery" : "Qwen3 · source-bound brief"),
      h("td", null, `Receiver counts by attempt: [${audit.attempts.map(a => a.receiver_requests).join(", ")}]. ${audit.attempts.filter(a => a.verification === "MATCH").length} MATCH; rejected attempts have no forensic verdict.`),
      h("td", null, h("a", { href: "#/lab/government-trust/replay/" + encodeURIComponent(row.collection) + "/" + row.event_id }, id))));
  }
  const e1 = r.experiment_1, d = r.diagnostics, l = r.latency;
  const findings = [
    ["Experiment 1 · primary cases", e1.primary.correct + " of " + e1.primary.denominator + " correct conclusions", e1.source],
    ["Experiment 1 · supplementary cases", e1.supplementary.correct + " of " + e1.supplementary.denominator + " correct, scored separately", e1.source],
    ["Fault diagnostics", d.correct + " of " + d.denominator + " expected conclusions", d.source],
    ["Latency", l.valid_pairs + " of " + l.scheduled_pairs + " valid pairs. Median added latency " + l.median_added_ms.low + "–" + l.median_added_ms.high + " ms per stratum", l.source],
    ["Live-agent privacy", "Corrected campaign accepted. Earlier campaign failed.", r.privacy.latest.source],
    ["Human assessment", r.fas.status.replaceAll("_", " ").toLowerCase(), r.fas.source],
  ];
  const technical = h("div");
  appendContent(technical,
    h("section", { class: "section-rule" }, h("h2", null, "Hackathon engineering evidence · v7 source binding"),
      h("p", null, "Actual local HTTPS runs with Qwen3, signed task permissions and a separate proxy observer. Each row is a separate engineering run, not a research accuracy total."),
      h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, ["Check", "Recorded result", "Open evidence"].map(x => h("th", null, x)))), h("tbody", null, evidence))),
      disclosure("Signed grounding attack matrix · 17 rejected, zero receiver requests",
        h("p", null, "Executed 10 November 2026 through the actual HTTPS protected dispatch with fresh valid signatures. The legitimate control reached the receiver once. All 17 invalid claims were rejected before dispatch. This is an engineering test, not a real-world attack success rate."),
        h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Signed case", "Dispatch", "Receiver requests"].map(x => h("th", null, x)))),
          h("tbody", null, Object.entries(GROUNDING_RETEST.results).map(([name, row]) => h("tr", null,
            h("th", { scope: "row" }, name.replaceAll("_", " ")), h("td", null, row.dispatch_code || row.dispatch), h("td", null, String(row.receiver_requests))))))),
        h("p", { class: "small soft" }, "Source record SHA-256: ", h("span", { class: "id" }, GROUNDING_RETEST.source_sha256))),
      h("p", { class: "small soft" }, "The source-bound mandate ties counts to the publisher, workbook hash, dataset digest, year, measure and unit. Altered counts and wrong destinations are rejected before dispatch. Real receiver counts are laboratory truth, separate from the proxy verdict.")),
    h("section", { class: "section-rule" }, h("h2", null, "Not yet measured"),
      h("p", null, "First-time human understanding in 60 seconds, agency deployment impact and end-to-end service latency. No government deployment or organizational identity integration has been validated.")),
    h("section", { class: "section-rule" }, h("h2", null, "Original academic research · measured findings"),
      h("p", { class: "soft" }, "The counts apply to designed test conditions. Government deployment performance remains unmeasured."),
      h("div", { class: "table-wrap" }, h("table", { class: "findings-table" },
        h("thead", null, h("tr", null, ["Evaluation", "Measured result", "Source record"].map((label) => h("th", { scope: "col" }, label)))),
        h("tbody", null, findings.map(([label, value, source]) =>
          h("tr", null, h("th", { scope: "row" }, label), h("td", null, value), h("td", { class: "small soft" }, h("a", { href: "#/learn/threat-model", title: source }, "Source and study limits"), h("div", null, source)))))))),
    h("p", { class: "soft" }, "Hackathon demonstrations and engineering recordings are separate from these totals. ",
      h("a", { href: "#/lab" }, "Open the Scenario Lab"), " · ", h("a", { href: "#/investigate" }, "Find recorded evidence")),
    disclosure("Technical details and research history",
    h("section", { class: "section-rule" }, h("h2", null, "Research design"),
      h("div", { class: "grid-3", style: { marginTop: "16px" } },
        h("div", null, h("h4", null, "Conditions"), h("p", { class: "small soft" }, "Normal ALLOW, REDACT and BLOCK, and fault-injected bypass, payload, destination and evidence-loss cases, under HTTP and HTTPS.")),
        h("div", null, h("h4", null, "Two evidence planes"), h("p", { class: "small soft" }, "Gateway authorization (Ledger A) against independent proxy observation (Ledger B), with health-qualified coverage.")),
        h("div", null, h("h4", null, "Matched study design"), h("p", { class: "small soft" }, "FAS compares minimized evidence, minimized plus observation, and fuller content across matched triplets."))),
      h("p", { class: "small soft", style: { marginTop: "12px" } }, `Fixed parameters: W = ${r.parameters.W}; G = ${r.parameters.G}; h = ${r.parameters.h}.`), prov(r.parameters.source)),

    h("div", { class: "grid-2", style: { marginTop: "16px" } },
      h("section", { class: "section-rule" }, h("h2", null, "Experiment 1: primary cases"),
        h("div", { class: "stat-line", style: { margin: "12px 0 16px" } }, h("div", { class: "stat" }, h("b", null, `${e1.primary.correct} / ${e1.primary.denominator}`), h("span", null, "correct conclusions"))),
        bars(e1.primary.outcomes, e1.primary.denominator),
        h("details", { class: "more" }, h("summary", null, "Allocation by class"),
          h("div", { class: "table-wrap" }, h("table", { style: { marginTop: "8px" } }, h("thead", null, h("tr", null, h("th", null, "Class"), h("th", { class: "num" }, "Cases"), h("th", null, "Pre-registered conclusion"))),
            h("tbody", null, e1.classes.map((c) => h("tr", null, h("td", null, c.class), h("td", { class: "num" }, String(c.cases)), h("td", null, c.expected))))))),
        prov(`Run ${e1.run_id}`, `commit ${e1.commit} (${e1.tag})`, e1.source)),
      h("section", { class: "section-rule" }, h("h2", null, "Experiment 1: supplementary cases"),
        h("div", { class: "stat-line", style: { margin: "12px 0 16px" } }, h("div", { class: "stat" }, h("b", null, `${e1.supplementary.correct} / ${e1.supplementary.denominator}`), h("span", null, "correct, scored separately"))),
        bars(e1.supplementary.outcomes, e1.supplementary.denominator),
        h("p", { class: "small soft", style: { marginTop: "12px" } }, e1.supplementary_detail, " Never pooled with the 42 primary cases."),
        prov(`Run ${e1.run_id}`, e1.source))),

    h("section", { class: "section-rule" }, h("h2", null, "Fault diagnostics"),
      h("div", { class: "stat-line", style: { margin: "12px 0" } }, h("div", { class: "stat" }, h("b", null, `${d.correct} / ${d.denominator}`), h("span", null, "conditions concluded as pre-registered (12 conditions, once per protocol)"))),
      h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, h("th", null, "Condition"), h("th", null, "Pre-registered interpretation"))),
        h("tbody", null, d.conditions.map((c) => h("tr", null, h("td", null, c.condition), h("td", null, c.expected)))))),
      prov(`Run ${d.run_id}`, `commit ${d.commit}`, d.source)),

    h("section", { class: "section-rule" }, h("h2", null, "Latency and overhead"),
      h("div", { class: "stat-line", style: { margin: "12px 0" } },
        h("div", { class: "stat" }, h("b", null, `${l.median_added_ms.low}–${l.median_added_ms.high} ms`), h("span", null, "median added latency per stratum")),
        h("div", { class: "stat" }, h("b", null, `${l.valid_pairs} / ${l.scheduled_pairs}`), h("span", null, "valid pairs")),
        h("div", { class: "stat" }, h("b", null, String(l.measured_requests)), h("span", null, `measured requests, plus ${l.warmups} warm-ups excluded`))),
      h("p", { class: "small soft" }, `${l.design}. ${l.statistic}.`),
      prov(`Run ${l.run_id}`, `commit ${l.commit} (${l.tag})`, l.source)),

    h("section", { class: "section-rule" }, h("div", { class: "spread" }, h("h2", null, "Live-agent privacy: latest documented outcome"), h("span", { class: "tag teal" }, "Accepted after correction")),
      h("p", { class: "soft small", style: { margin: "8px 0 16px" } }, "Routine evidence must not contain registered synthetic values. This is the post-remediation campaign, the latest accepted live result."),
      h("div", { class: "stat-line" },
        h("div", { class: "stat" }, h("b", null, "6 / 6"), h("span", null, "expected gateway decisions")),
        h("div", { class: "stat" }, h("b", null, "6 / 6"), h("span", null, "MATCH")),
        h("div", { class: "stat" }, h("b", null, "0"), h("span", null, "routine privacy findings reported"))),
      h("p", { class: "small soft", style: { marginTop: "12px" } }, `${r.privacy.latest.acceptance}. ${r.privacy.latest.scope}`),
      prov(`Campaign ${r.privacy.latest.campaign}`, `commit ${r.privacy.latest.commit} (${r.privacy.latest.tag})`, r.privacy.latest.source),
      h("details", { class: "more" }, h("summary", null, "Remediation history, including the failed campaign"),
        h("ol", { class: "timeline-v", style: { marginTop: "12px" } }, r.privacy.history.map((p) => h("li", { class: p.status }, h("div", { class: "spread" }, h("b", null, p.campaign), h("span", { class: `tag ${p.status === "FAILED" ? "fault" : "teal"}` }, p.status.replace(/_/g, " ").toLowerCase())),
          h("p", { class: "small soft", style: { margin: "4px 0" } }, p.summary), prov(`Commit ${p.commit}`, p.source)))))),

    h("section", { class: "section-rule" }, h("div", { class: "spread" }, h("h2", null, "Forensic Assessment Study"), h("span", { class: "tag fault" }, `Status: ${r.fas.status.toLowerCase()}`)),
      h("p", { class: "soft", style: { margin: "8px 0 16px" } }, r.fas.summary),
      h("h3", { style: { margin: "0 0 8px" } }, "Custodian workstation records"),
      h("p", { class: "small soft", style: { margin: "0 0 8px" } }, "Verified read-only on 1 November 2026. These records stay on the custodian workstation; the platform does not read them."),
      h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, h("th", null, "Item"), h("th", null, "Value"), h("th", null, "State"), h("th", null, "Note"))),
        h("tbody", null, r.fas.workstation.map((x) => h("tr", null, h("td", null, x.label), h("td", null, h("b", null, x.value)), h("td", null, x.state), h("td", { class: "small soft" }, x.note)))))),
      h("h3", { style: { margin: "16px 0 8px" } }, "In a source checkout"),
      h("p", { class: "small soft", style: { margin: 0 } }, r.fas.checkout),
      h("p", { class: "small soft", style: { marginTop: "12px" } }, r.fas.engineering, " ", r.fas.design, " The Investigations checklist uses the same ten questions as a practice aid; it is not study data."),
      prov(r.fas.source)),

    h("section", { class: "section-rule" }, h("h2", null, "Known limitations"),
      h("ul", { class: "list", style: { marginTop: "12px" } }, r.limitations.map((x) => h("li", null, x))))));
  const invalid = Object.entries(GROUNDING_RETEST.results).filter(([name]) => name !== "valid_two_cells");
  const figuresStopped = invalid.length > 0 && invalid.every(([, x]) => x.dispatch === "REJECTED" && x.receiver_requests === 0);
  const lifecycle = recordings.find(x => x.audit.operator_events?.length);
  const withdrawn = lifecycle?.audit.attempts.filter(x => x.code === "AGENT_REVOKED") || [];
  const recovered = lifecycle?.audit.attempts.filter(x => x.trust === "ACCEPTED" && x.verification === "MATCH") || [];
  const permissionChecked = withdrawn.length >= 2 && withdrawn.every(x => x.receiver_requests === 0) && recovered.length >= 2;
  const observed = recordings.find(x => x.audit.attempts.some(a => a.verification === "MATCH" && a.observation_paired && a.receiver_requests === 1));
  const proofRow = (title, description, url, label) => h("div", { class: "proof-item" },
    h("div", null, h("h2", null, title), h("p", null, description)), h("a", { href: url }, label));
  appendContent(page,
    h("div", { class: "page-head" }, h("div", null, h("h1", null, "Test results"),
      h("p", null, "Three practical checks, demonstrated in the local prototype."))),
    h("section", { class: "proof-summary" },
      proofRow("Incorrect figures are stopped", figuresStopped
        ? `All ${invalid.length} invalid test briefs were blocked before sending. None reached the receiver.`
        : "Open the recorded checks to inspect which requests were blocked.", "#/lab/government-trust/demo", "See the data check"),
      proofRow("Access can be withdrawn", permissionChecked
        ? "After access was withdrawn, the next request was blocked. A new identity could proceed; the old identity stayed blocked."
        : "No validated permission-recovery recording is available in this installation.", "#/lab/permissions", "See the permission check"),
      proofRow("The delivery can be checked", observed
        ? "A separate network observer confirmed that the request matched what the agent was permitted to send."
        : "No matched delivery recording is available in this installation.", observed
          ? "#/investigate/" + encodeURIComponent(observed.row.collection) + "/" + observed.row.event_id : "#/lab/network", "View the evidence")),
    h("p", { class: "proof-scope soft" }, "These are controlled local tests using published GDRFA statistics and synthetic confidential records. Agency deployment and a first-time human usability study have not been validated."),
    disclosure("Technical evidence and original research", technical));

}
