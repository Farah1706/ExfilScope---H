// Read-only explorer for the demonstration dataset (examples/demo_dataset), opened from the
// Scenario Lab. Registered values arrive from the service already replaced by their registry
// ID; they are shown as markers, never as values.
import { h, appendContent, icon, fill, disclosure } from "../dom.js";
import { get } from "../api.js";

const MARKER = /\[\[(SECRET_[0-9]{3}|registered value)\]\]/g;

function marked(text, categories) {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(MARKER)) {
    parts.push(text.slice(last, m.index));
    parts.push(h("span", { class: "secret-mark", title: "Registered protected value, withheld" }, icon("key", 11), m[1], categories[m[1]] ? ` · ${categories[m[1]]}` : ""));
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

export async function explorer(page, selectedRef) {
  const data = await get("/api/dataset");
  const categories = Object.fromEntries(data.protected.map((p) => [p.protected_id, p.category]));
  const current = data.documents.find((d) => d.source_ref === selectedRef) || data.documents[0];
  const intact = data.integrity.every((x) => x.intact);
  const list = h("nav", { class: "doc-list", "aria-label": "Documents" }, data.documents.map((d) =>
    h("a", { href: `#/lab/data/${encodeURIComponent(d.source_ref)}`, "aria-current": d === current ? "page" : null },
      h("span", { class: "t" }, d.title), h("span", { class: "m" }, `${d.category} · ${d.classification}`))));
  const detail = h("article", { class: "doc" });
  const d = current;
  fill(detail,
    h("div", { class: "doc-head" },
      h("div", null, h("span", { class: "muted small" }, `${d.organisation} · ${d.department}`), h("h2", null, d.title)),
      h("span", { class: "tag" }, d.classification)),
    h("dl", { class: "doc-meta" },
      [["Reference", d.reference], ["Issued", d.issued], ["Prepared by", d.prepared_by], ["Category", d.category], ["Source reference", d.source_ref], ["File", d.file]]
        .map(([k, v]) => h("div", null, h("dt", null, k), h("dd", { class: k === "File" || k === "Source reference" ? "id" : null }, v)))),
    h("p", { class: "soft" }, d.summary),
    d.sections.map((sec) => h("section", { class: "doc-section" }, h("h3", null, sec.heading),
      sec.paragraphs ? sec.paragraphs.map((p) => h("p", null, marked(p, categories))) : null,
      sec.fields ? h("table", { class: "doc-fields" }, h("tbody", null, sec.fields.map(([k, v]) => h("tr", null, h("th", null, k), h("td", null, marked(v, categories)))))) : null)),
    d.corpus_excerpt ? h("section", { class: "doc-section excerpt" },
      h("h3", null, "Retrievable excerpt, corpus v1"),
      h("p", { class: "small soft" }, "The exact chunk the agent's retriever indexes from the frozen corpus, with registered values replaced by their registry ID."),
      h("blockquote", null, marked(d.corpus_excerpt, categories))) : null,
    h("section", { class: "doc-section" }, h("h3", null, "Role in the scenarios"), h("p", null, d.role),
      d.used_by.length ? h("div", { class: "row" }, d.used_by.map((x) => h("a", { class: "btn small", href: `#/lab/${x.id}` }, `Scenario ${x.number}: ${x.title}`))) : h("p", { class: "small muted" }, "No scenario retrieves this record directly.")),
    h("div", { class: "small soft" },
      h("p", null, "Authorized laboratory view of a fictional source record. Forensic evidence never contains this text: Ledger A and Ledger B keep only registry IDs, source references and keyed body fingerprints.")));
  appendContent(page,
    h("div", { class: "crumbs" }, h("a", { href: "#/lab" }, "Scenario Lab"), " / Synthetic data explorer"),
    h("div", { class: "page-head" }, h("div", null, h("h1", null, "Synthetic data explorer"),
      h("p", null, `Demonstration dataset ${data.dataset_version}, in examples/demo_dataset. ${data.notice}`))),
    h("div", { class: "explorer" }, list, detail, h("div", { class: "stack meta" },
      disclosure("Registered value categories",
        h("table", { class: "doc-fields" }, h("tbody", null, data.protected.map((p) => h("tr", null, h("th", { class: "id" }, p.protected_id), h("td", null, `${p.category} (${p.data_type}), from ${p.source_ref}`))))),
        h("p", { class: "small muted" }, "The values stay in the frozen registry and never reach this page.")),
      disclosure("Frozen inputs", h("ul", { class: "plain" }, data.integrity.map((x) =>
        h("li", { class: "ready-item" }, h("span", { class: `dot ${x.intact ? "ok" : "bad"}` }), h("div", null, h("b", { class: "id" }, x.path), h("div", { class: "detail" }, x.role)), h("span", null)))),
        h("p", { class: `small ${intact ? "muted" : "inline-error"}` }, intact ? "SHA-256 of each file equals the value recorded in the dataset manifest." : "A frozen input differs from its recorded SHA-256.")))),
    data.no_document.length ? h("p", { class: "small muted", style: { marginTop: "16px" } }, `No source document: ${data.no_document.map((x) => `scenario ${x.number}`).join(", ")} use a harmless body generated by the laboratory harness.`) : null);
}
