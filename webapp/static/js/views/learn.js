import { h, appendContent, disclosure } from "../dom.js";
import { GUIDES, GUIDE_BY_ID } from "../content.js";
import { guideBody } from "../components.js";

// Reference material. Workspaces open single guides in a drawer beside the component they
// explain; this page lists and searches all of them.
export async function learn(page, [guideId]) {
  const g = GUIDE_BY_ID[guideId] || GUIDE_BY_ID.what;
  const text = (x) => [x.title, ...x.simple, ...x.technical].join(" ").toLowerCase();
  const links = GUIDES.map((x, i) => h("a", { href: `#/learn/${x.id}`, "aria-current": x.id === g.id ? "page" : null, dataset: { text: text(x) } }, h("span", { class: "n" }, String(i + 1)), x.title));
  const none = h("p", { class: "small muted", hidden: true }, "No guide mentions that.");
  const search = h("input", { type: "search", placeholder: "Search the guides…", "aria-label": "Search the guides", oninput: (e) => {
    const q = e.target.value.trim().toLowerCase();
    let shown = 0;
    for (const a of links) { a.hidden = q && !a.dataset.text.includes(q); if (!a.hidden) shown++; }
    none.hidden = shown > 0;
  } });
  const nav = h("nav", { class: "guide-list", "aria-label": "Guides" }, search, links, none);
  const guidePicker = disclosure("Choose or search guides", nav);
  guidePicker.open = matchMedia("(min-width: 901px)").matches;
  const prev = GUIDES[g.n - 2], next = GUIDES[g.n];
  appendContent(page,
    h("div", { class: "page-head" }, h("div", null, h("h1", null, "Help and guides"),
      h("p", null, "Find a guide on how ExfilScope works and how to read its evidence."))),
    h("div", { class: "learn" }, guidePicker,
      h("article", { class: "guide-body" }, h("p", { class: "muted small" }, `Guide ${g.n} of ${GUIDES.length}`), h("h2", { style: { margin: "4px 0 16px" } }, g.title), guideBody(g),
        g.related?.length ? h("div", { style: { marginTop: "24px" } }, h("h4", { style: { marginBottom: "8px" } }, "Related"),
          h("div", { class: "row" }, g.related.map((id) => h("a", { href: `#/learn/${id}` }, GUIDE_BY_ID[id].title)))) : null,
        h("hr"), h("div", { class: "spread" },
          prev ? h("a", { class: "btn ghost", href: `#/learn/${prev.id}` }, `Previous: ${prev.title}`) : h("span"),
          next ? h("a", { class: "btn ghost", href: `#/learn/${next.id}` }, `Next: ${next.title}`) : h("span")))));
}
