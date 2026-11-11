import { h } from "../dom.js";

const SNAPSHOT_URL = new URL("../../government-data.json", import.meta.url);
const BASE = "https://www.gdrfad.gov.ae";

function validSnapshot(data) {
  return data?.publisher === "GDRFA Dubai" && data.metric === "RES Transactions"
    && data.unit === "transactions" && data.reuse_url === BASE + "/en/open-data-policy"
    && /^\d{4}-\d{2}-\d{2}$/.test(data.retrieved) && Number.isFinite(Date.parse(data.retrieved))
    && Array.isArray(data.rows) && data.rows.length > 0
    && data.rows.every((row, i, rows) => Number.isInteger(row?.year) && row.year >= 2000
      && row.year <= 2099 && row.year < Number(data.retrieved.slice(0, 4))
      && (!i || row.year > rows[i - 1].year)
      && Number.isInteger(row.transactions) && row.transactions > 0 && row.transactions <= 1000000000
      && /^[0-9a-f]{64}$/.test(row.sha256)
      && row.source_url === `${BASE}/sites/default/files/gdrfa_tables/statistics/GDRFAD-Statistics${row.year}-en.pdf`);
}
const DISPATCH_P50_MS = 0.1726;

export function pilotWorkload() {
  const counts = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });
  const decimal = new Intl.NumberFormat("en", { maximumFractionDigits: 3 });
  const number = (value, min, max, step = 1) => h("input", {
    type: "number", min, max, step, value, oninput: update,
  });
  const share = h("input", { type: "range", id: "pilot-share", min: 0.01, max: 1,
    step: 0.01, value: 0.1, oninput: update });
  share.value = "0.10";
  const actions = number(1, 1, 10);
  const days = number(90, 1, 90);
  const peak = number(2, 1, 20, 0.1);
  const denied = number(5, 0, 100, 0.1);
  const costs = [
    "Integration engineering", "Security review and testing", "Compute and hosting",
    "Network monitoring", "Evidence storage and retention", "Maintenance and support",
  ].map((title) => [title, number(0, 0, 100000000, 0.01)]);
  const workload = h("output", { "aria-live": "polite" });
  const mix = h("p");
  const estimate = h("p");
  const budget = h("output", { "aria-live": "polite" });
  const workloadInputs = [share, actions, days, peak, denied];

  let snapshot;
  const reference = h("p", null, "Loading official data…");
  const provenance = h("p", { class: "small" });
  const year = h("select", { disabled: true, onchange: update });
  const retry = h("button", { type: "button", class: "btn small", hidden: true, onclick: load }, "Retry loading official data");

  function update() {
    const row = snapshot?.rows.find((item) => String(item.year) === year.value);
    if (row) {
      const previous = snapshot.rows.find((item) => item.year === row.year - 1);
      const comparison = previous ? ` · ${counts.format((row.transactions / previous.transactions - 1) * 100)}% calculated change from ${previous.year}` : "";
      reference.textContent = `OFFICIAL DATA · GDRFA Dubai reported ${counts.format(row.transactions)} residence transactions in ${row.year}${comparison}.`;
      const age = (Date.now() - Date.parse(snapshot.retrieved)) / 86400000;
      provenance.replaceChildren(h("a", { href: row.source_url }, `${row.year} transaction table (PDF)`),
        " · ", h("a", { href: snapshot.reuse_url }, "GDRFA Dubai reuse terms"),
        ` · Retrieved ${snapshot.retrieved}. ${age > 365 ? "Snapshot is over one year old." : "Fixed snapshot, not a live feed."}`,
        h("details", null, h("summary", null, "Source verification"), `PDF SHA-256 ${row.sha256}`));
    }
    if (!row) {
      workload.textContent = "No official baseline is available for workload estimates.";
      mix.textContent = estimate.textContent = "";
    } else if (workloadInputs.some((input) => !input.validity.valid || input.value === "")) {
      workload.textContent = "Enter a value within the stated range.";
      mix.textContent = estimate.textContent = "";
    } else {
      const daysInYear = (Date.UTC(row.year + 1, 0, 1) - Date.UTC(row.year, 0, 1)) / 86400000;
      const daily = row.transactions * share.valueAsNumber / 100 / daysInYear * actions.valueAsNumber;
      const total = daily * days.valueAsNumber;
      const unauthorized = total * denied.valueAsNumber / 100;
      const peakDay = daily * peak.valueAsNumber;
      workload.textContent = `${share.value}% coverage · ${counts.format(daily)} actions/day · ${counts.format(total)} actions in ${days.value} days`;
      mix.textContent = `Plan a synthetic peak-day test of ${Math.ceil(peakDay).toLocaleString("en")} actions. Model ${counts.format(total - unauthorized)} permitted and ${counts.format(unauthorized)} unauthorized attempts over the trial. Test both classes even when the model rounds one to zero.`;
      estimate.textContent = `Applying the measured median dispatch increment to modeled permitted attempts gives ${decimal.format((total - unauthorized) * DISPATCH_P50_MS / 1000)} seconds of summed dispatch increment across the trial. This illustration is neither wall-clock delay nor a sizing guarantee.`;
    }
    const values = costs.map(([, input]) => input.valueAsNumber);
    const valid = costs.every(([, input]) => input.validity.valid && input.value !== "");
    budget.textContent = valid && values.some((value) => value > 0)
      ? `Entered trial cost · AED ${new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(values.reduce((sum, value) => sum + value, 0))}`
      : valid ? "Enter estimates to calculate the trial cost." : "Enter valid nonnegative cost estimates.";
  }

  function preset(values) {
    workloadInputs.forEach((input, i) => { input.value = values[i]; });
    update();
  }

  async function load() {
    retry.hidden = true;
    year.disabled = true;
    year.replaceChildren(h("option", null, "Loading reference years…"));
    reference.textContent = "Loading official data…";
    update();
    try {
      const response = await fetch(SNAPSHOT_URL, { cache: "no-cache" });
      if (!response.ok) throw new Error("Snapshot unavailable");
      const data = await response.json();
      if (!validSnapshot(data)) throw new Error("Invalid snapshot");
      snapshot = data;
      year.replaceChildren(...data.rows.map((row) => h("option", { value: row.year }, String(row.year))));
      year.value = String(data.rows.at(-1).year);
      year.disabled = false;
    } catch {
      snapshot = undefined;
      year.replaceChildren(h("option", null, "Reference years unavailable"));
      reference.textContent = "The bundled official snapshot could not be loaded or verified. Workload estimates require that file.";
      retry.hidden = false;
    }
    update();
  }

  load();
  return h("section", { class: "planner-content", id: "government-pilot" },
    h("h2", { tabindex: "-1" }, "Government Pilot Planner"),
    h("label", { class: "field" }, "Official reference year", year), reference, retry, provenance,
    h("h3", null, "MODELED ASSUMPTIONS · Trial workload"),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn", onclick: () => preset([0.05, 1, 30, 2, 5]) }, "Small sandbox"),
      h("button", { type: "button", class: "btn", onclick: () => preset([0.10, 1, 90, 2, 5]) }, "90-day pilot"),
      h("button", { type: "button", class: "btn", onclick: () => preset([0.25, 2, 90, 4, 10]) }, "Burst rehearsal")),
    h("div", { class: "field" }, h("label", { for: "pilot-share" }, "Assumed transaction share, 0.01–1%"), share),
    h("div", { class: "row" },
      h("label", { class: "field" }, "Actions per transaction", actions),
      h("label", { class: "field" }, "Trial days", days),
      h("label", { class: "field" }, "Peak-day multiplier", peak),
      h("label", { class: "field" }, "Unauthorized share (%)", denied)),
    workload, mix,
    h("p", { class: "small soft" }, "Daily actions = official annual total × assumed share × actions per transaction ÷ calendar days in the selected year. Trial workload = daily actions × trial days. A daily multiplier does not estimate per-second concurrency. The source is a residence transaction aggregate, with no renewal-only or population inference."),
    h("h3", null, "MEASURED EXPERIMENT · Dispatch overhead"),
    h("p", { class: "small soft" }, "300 paired in-process Windows trials. Added dispatch p50 0.1726 ms and p95 0.1908 ms, with mocked gateway and transport. Network, model and ledger I/O were excluded."),
    estimate,
    h("p", { class: "small soft" }, "Measure burst latency and evidence retention in the target sandbox. Require zero unauthorized deliveries, a paired observation for permitted trial cases, and explicit UNVERIFIED when evidence is incomplete."),
    h("h3", null, "MODELED ASSUMPTIONS · Trial cost in AED"),
    h("p", { class: "small soft" }, "Enter costs for the entire trial. No quotations, agency budgets or savings are assumed. A zero entry contributes zero to the total."),
    h("div", { class: "row" }, costs.map(([title, input]) => h("label", { class: "field" }, title, input))),
    budget,
    h("h3", null, "Proposed 90-day adoption plan"),
    h("p", null, "Scope one sandbox route with the workload and AED inputs above. The government service sponsor owns the decision to proceed."),
    h("ol", { class: "list" },
      h("li", null, h("strong", null, "Days 1–30 · Government service sponsor. "), "Agree the workflow, endpoint allowlist, policy, baseline and rollback plan."),
      h("li", null, h("strong", null, "Days 31–60 · Platform integration owner. "), "Integrate one route, exercise authorization and measure overhead."),
      h("li", null, h("strong", null, "Days 61–90 · Security and evidence reviewer. "), "Repeat trials, test recovery, review evidence completeness and document a go/no-go recommendation.")),
    h("p", { class: "small soft" }, "Proposed exit gates: zero unauthorized deliveries, paired independent evidence for every permitted test delivery, explicit UNVERIFIED on evidence gaps, and a successful rollback rehearsal."));
}
