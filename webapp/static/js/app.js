// Shell, routing and the global health indicator.
import { h, icon, clear, loadIcons, fill } from "./dom.js";
import { bootstrapSession, get, explain, isSessionError, ERRORS, PUBLIC } from "./api.js";
import { openDrawer } from "./components.js";
import { overview } from "./views/overview.js";
import { lab } from "./views/lab.js";
import { investigate } from "./views/investigate.js";
import { research } from "./views/research.js";
import { learn } from "./views/learn.js";

// Each workspace owns one responsibility. Help is reference material, not a step.
document.querySelector(".skip-link")?.addEventListener("click", (event) => { event.preventDefault(); document.getElementById("main").focus(); });

const WORKSPACES = [
  ["overview", "Overview", "home", overview],
  ["lab", "Scenario Lab", "flask", lab],
  ["investigate", "Investigations", "incident", investigate],
  ["research", "Test results", "chart", research, true],
  ["learn", "Help and guides", "book", learn, true],
];
// Earlier routes that now live inside a workspace: #/run/<id> is a run in the Scenario Lab.
const ALIASES = { run: ["lab", (rest) => ["run", ...rest]] };

export const state = { status: null, scenarios: null, cleanup: null };

function brand(el) {
  fill(el, h("img", { src: "static/img/mark.svg", width: 26, height: 26, alt: "" }), "ExfilScope");
}

function nav(current) {
  const el = clear(document.getElementById("nav"));
  WORKSPACES.forEach(([id, label, glyph, , reference], index) => {
    if (reference && !WORKSPACES[index - 1]?.[4]) el.append(h("div", { class: "nav-sep", role: "presentation" }));
    el.append(h("a", { href: `#/${id}`, "aria-current": id === current ? "page" : null,
      onclick: () => document.getElementById("rail").classList.remove("open") },
      icon(glyph, 17), label));
  });
}

export async function refreshStatus() {
  const dot = document.getElementById("health-dot"), text = document.getElementById("health-text");
  if (PUBLIC) {
    state.status = null;
    return null;
  }
  try {
    state.status = await get("/api/status");
    const modes = state.status.modes;
    const live = modes.live.ready, labReady = modes.lab.ready;
    dot.className = `dot ${live && labReady ? "ok" : labReady ? "warn" : "bad"}`;
    text.textContent = live && labReady ? "All modes available" : labReady ? "Live agent unavailable" : "Lab unavailable";
    if (state.status.active_run) text.textContent = "Run in progress";
  } catch (error) {
    if (isSessionError(error)) { showRecovery(error.message); return null; }
    dot.className = "dot bad";
    text.textContent = "Service unreachable";
  }
  return state.status;
}

export function statusPanel() {
  if (PUBLIC) return h("p", null, "This site shows recorded laboratory evidence. Use the local application to start a new run.");
  const st = state.status;
  if (!st) return h("p", null, "Status is unavailable.");
  return h("div", { class: "readiness" }, st.items.map((item) => h("div", { class: "ready-item" },
    h("span", { class: `dot ${["missing", "unhealthy"].includes(item.state) ? "bad" : item.state === "not_required" ? "" : "ok"}` }),
    h("div", null, h("b", null, item.label), h("div", { class: "detail" }, item.detail)),
    h("span", { class: `state ${item.state}` }, item.state.replace("_", " ")))));
}

async function route() {
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  let [, name = "overview", ...rest] = (location.hash || "#/overview").split("/");
  if (ALIASES[name]) [name, rest] = [ALIASES[name][0], ALIASES[name][1](rest)];
  const workspace = WORKSPACES.find(([id]) => id === name) || WORKSPACES[0];
  nav(workspace[0]);
  const main = clear(document.getElementById("main"));
  const page = h("div", { class: "page" });
  main.append(page);
  try {
    await workspace[3](page, rest.map(decodeURIComponent), state);
  } catch (error) {
    if (isSessionError(error)) { showRecovery(error.message); return; }
    fill(page, h("div", { class: "empty" }, h("h3", null, "This view could not load"), h("p", null, explain(error)),
      h("button", { class: "btn", onclick: route }, "Try again")));
  }
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// Shown for a missing, stale, expired or already-used session; nothing else is loaded.
export function showRecovery(reason) {
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  window.removeEventListener("hashchange", route);
  nav("");
  const dot = document.getElementById("health-dot"), text = document.getElementById("health-text");
  if (dot) dot.className = "dot bad";
  if (text) text.textContent = "No session";
  const main = fill(document.getElementById("main"), h("div", { class: "page" }, h("section", { class: "empty recovery", role: "alert" },
    h("h1", { style: { fontSize: "26px" } }, "Start ExfilScope with the launcher"),
    h("p", null, ERRORS[reason] || "This page has no session for the ExfilScope service now running."),
    h("ol", { class: "list", style: { textAlign: "left", maxWidth: "52ch", margin: "16px auto" } },
      h("li", null, "Go to the ExfilScope launcher window. If it is closed, double-click Start-ExfilScope.cmd in the repository folder."),
      h("li", null, "Use the browser tab the launcher opens. Each launch creates a new, single-use link."),
      h("li", null, "To start again, press Enter in the launcher window and run it once more.")),
    h("p", { class: "small muted" }, "For safety, a session cannot be created from this page."))));
  main.focus({ preventScroll: true });
}

async function start() {
  if (PUBLIC) document.getElementById("health")?.remove();
  await loadIcons();
  brand(document.getElementById("brand"));
  brand(document.getElementById("brand-top"));
  const menu = document.getElementById("menu");
  menu.addEventListener("click", () => {
    const open = document.getElementById("rail").classList.toggle("open");
    menu.setAttribute("aria-expanded", String(open));
  });
  document.getElementById("health")?.addEventListener("click", async () => {
    await refreshStatus();
    openDrawer(h("div", null, h("h2", null, PUBLIC ? "About this site" : "System health"), PUBLIC ? null : h("p", { class: "soft" }, "Probed just now. Docker is not used by local demonstrations."), statusPanel()));
  });
  let reason;
  try { reason = await bootstrapSession(); } catch { reason = "SERVICE_UNREACHABLE"; }
  if (reason) { showRecovery(reason); return; }
  if (PUBLIC) {
    document.body.classList.add("public");
    document.getElementById("rail-note").hidden = true;
  }
  try {
    state.scenarios = await get("/api/scenarios");
  } catch (error) {
    showRecovery(isSessionError(error) ? error.message : "SERVICE_UNREACHABLE");
    return;
  }
  await refreshStatus();
  window.addEventListener("hashchange", route);
  route();
}

start();
