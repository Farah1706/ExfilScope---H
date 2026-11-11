import { h, appendContent, disclosure, fill } from "../dom.js";
import { architecture, componentDetail, helpButton } from "../components.js";
import { statusPanel, refreshStatus } from "../app.js";
import { PUBLIC } from "../api.js";

export async function overview(page, _args, state) {
  let selected = "gateway";
  const diagramHost = h("div", { class: "architecture-canvas", tabindex: 0, role: "region", "aria-label": "Interactive architecture diagram" });
  const detailHost = h("div", { class: "architecture-detail", "aria-live": "polite" });
  const draw = (focus = false) => {
    fill(diagramHost, architecture((id) => { selected = id; draw(true); }, selected));
    fill(detailHost, componentDetail(selected));
    if (focus) diagramHost.querySelector('[aria-pressed="true"]')?.focus();
  };
  draw();

  const readiness = h("div", null, statusPanel());
  appendContent(page,
    h("section", { class: "hero intro" },
      h("h1", null, "Keep government AI actions under control"),
      h("p", { class: "lede" }, "Check who is acting, limit what they can do, and stop further actions when needed. ExfilScope checks official figures before sending and uses a separate activity record to verify what happened."),
      h("div", { class: "row" },
        h("a", { class: "btn primary", href: "#/lab/government-trust/demo" }, "See the government example"),
        h("a", { href: "#/lab" }, "Explore the Scenario Lab"))),
    h("section", { class: "section-rule", id: "architecture" },
      h("div", { class: "panel-head" }, h("div", null, h("h2", null, "How a request is checked"),
        h("p", null, "Select a box for a short explanation.")), helpButton("architecture")),
      diagramHost, detailHost),
    PUBLIC ? null : disclosure("System readiness", readiness,
      h("button", { class: "btn small", type: "button", onclick: async () => {
        await refreshStatus();
        fill(readiness, statusPanel());
      } }, "Check again")),
  );
}
