// DOM helpers. All text goes through textContent; nothing from the API is parsed as HTML.

const SVG_NS = "http://www.w3.org/2000/svg";
let ICONS = {};

export async function loadIcons() {
  try { ICONS = await (await fetch("icons.json")).json(); } catch { ICONS = {}; }
}

function apply(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && (attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs))) {
    children.unshift(attrs);
  } else apply(el, attrs);
  append(el, children);
  return el;
}

export function disclosure(title, ...content) {
  return h("details", { class: "disclosure" },
    h("summary", null, title), h("div", { class: "disclosure-body" }, content));
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

// HTML inside an SVG box wraps naturally at the box's actual width, including
// after fonts load or the user changes text size. Keep all content as text nodes.
export function svgBoxLabel(x, y, width, height, title, subtitle = "", { compact = false } = {}) {
  return s("foreignObject", { x, y, width, height, class: "svg-box-content" },
    h("div", { xmlns: "http://www.w3.org/1999/xhtml", class: `svg-box-label${compact ? " compact" : ""}` },
      h("strong", null, title), subtitle ? h("span", null, subtitle) : null));
}

// Lucide path data comes from the server as a fixed, committed table (dashboard/icons.py);
// it is parsed with DOMParser into an isolated SVG document, never into the page as HTML.
export function icon(name, size = 16, label = "") {
  const svg = s("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round",
    "stroke-linejoin": "round", class: "icon", "aria-hidden": label ? null : "true",
    role: label ? "img" : null, "aria-label": label || null });
  const paths = ICONS[name];
  if (paths) {
    const doc = new DOMParser().parseFromString(`<svg xmlns="${SVG_NS}">${paths}</svg>`, "image/svg+xml");
    for (const node of [...doc.documentElement.children]) {
      if (["path", "circle", "rect", "line", "polyline", "polygon", "ellipse"].includes(node.localName)) {
        svg.append(document.importNode(node, true));
      }
    }
  }
  return svg;
}

export const OUTCOME_ICON = { MATCH: "match", MISMATCH: "mismatch", UNVERIFIED: "unverified" };
export const OUTCOME_TEXT = { MATCH: "Matches approval", MISMATCH: "Difference found", UNVERIFIED: "Not confirmed" };

export function badge(result, large = false) {
  if (!result) return h("span", { class: "tag" }, "No result");
  return h("span", { class: `badge ${result}${large ? " large" : ""}` },
    icon(OUTCOME_ICON[result], large ? 18 : 14), OUTCOME_TEXT[result]);
}

export function seal(digest, empty = "None") {
  if (!digest) return h("span", { class: "seal empty" }, empty);
  return h("span", { class: "seal", title: `HMAC-SHA-256 ${digest}` }, icon("key", 12),
    `${digest.slice(0, 10)}…${digest.slice(-6)}`);
}

export function mono(text) { return h("span", { class: "id" }, text ?? "—"); }

export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }

export function humanize(code) {
  if (!code) return "";
  const text = code.replace(/_/g, " ").toLowerCase();
  return (text.charAt(0).toUpperCase() + text.slice(1)).replace(/\bjson\b/g, "JSON").replace(/\bhttps?\b/g, (m) => m.toUpperCase());
}

export function when(seconds) {
  if (!seconds) return "—";
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

// Replace an element's children, skipping null, undefined and false like h() does.
export function appendContent(el, ...children) { append(el, children); return el; }

export function fill(el, ...children) { clear(el); append(el, children); return el; }
