/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* ===========================================================================
   The prototype's behaviour.  Four things and nothing else:

     1 language   every `[data-i18n]` carries both columns, so the switch moves
                  an attribute instead of asking a server for the page again
     2 theme      auto -> light -> dark, remembered; `auto` is the OS
     3 multi      the chip boxes: add a value, drop a value, filter the menu
     4 buttons    nothing here runs a command, so a click says so once

   No framework, no build step, no fetch: the file is served as it stands, which
   is the same promise `lib/gui/templates.py` makes about the real page.
   =========================================================================== */
(() => {
"use strict";

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* -- 1 language ---------------------------------------------------------- */
function setLang(lang) {
  document.documentElement.lang = lang === "zh" ? "zh" : "en";
  $$("[data-i18n]").forEach((el) => {
    const text = lang === "zh" ? el.dataset.zh : el.dataset.en;
    if (text === undefined) return;
    if (el.dataset.i18n === "html") el.innerHTML = text;
    else el.textContent = text;
  });
  $$('input[name="lang"]').forEach((i) => { i.checked = i.value === lang; });
  try { localStorage.setItem("kci-lang", lang); } catch (e) { /* private window */ }
}

/* -- 2 theme ------------------------------------------------------------- */
const THEMES = ["", "light", "dark"];
const WORDS = { "": "auto", light: "light", dark: "dark" };

function setTheme(theme) {
  /* `auto` is written as *no* attribute, which is what lets the stylesheet's
     `prefers-color-scheme` block win; an explicit choice sets it and wins instead. */
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const word = $("#theme-word");
  if (word) word.textContent = WORDS[theme] || "auto";
  try { localStorage.setItem("kci-theme", theme); } catch (e) { /* private window */ }
}

/* -- 3 the chip boxes ---------------------------------------------------- */
function addValue(box, value) {
  if (!value || box.querySelector(`.tag[data-v="${CSS.escape(value)}"]`)) return;
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.dataset.v = value;
  tag.innerHTML = `<span></span><button type="button" data-drop aria-label="remove">&times;</button>`;
  tag.firstChild.textContent = value;
  box.querySelector(".box").insertBefore(tag, box.querySelector(".box input"));
  const item = box.querySelector(`.menu button[data-add="${CSS.escape(value)}"]`);
  if (item) item.setAttribute("aria-selected", "true");
  const input = box.querySelector(".box input");
  input.value = "";
  renderMenu(box);
}

function dropValue(box, value) {
  const tag = box.querySelector(`.tag[data-v="${CSS.escape(value)}"]`);
  if (tag) tag.remove();
  const item = box.querySelector(`.menu button[data-add="${CSS.escape(value)}"]`);
  if (item) item.removeAttribute("aria-selected");
  renderMenu(box);
}

function renderMenu(box) {
  const menu = box.querySelector(".menu");
  const chosen = new Set($$(".tag", box).map((t) => t.dataset.v));
  const q = box.querySelector(".box input").value.trim().toLowerCase();
  let shown = 0;
  $$("button[data-add]", menu).forEach((b) => {
    const hit = !chosen.has(b.dataset.add) && (!q || b.dataset.add.toLowerCase().includes(q));
    b.hidden = !hit;
    if (hit) shown += 1;
  });
  menu.hidden = shown === 0;
}

function wireMulti(box) {
  const input = box.querySelector(".box input");
  input.addEventListener("focus", () => renderMenu(box));
  input.addEventListener("input", () => renderMenu(box));
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      const first = box.querySelector('.menu button[data-add]:not([hidden])');
      if (first) addValue(box, first.dataset.add);
    } else if (ev.key === "Escape") {
      box.querySelector(".menu").hidden = true;
      input.blur();
    }
  });
  box.addEventListener("click", (ev) => {
    const add = ev.target.closest("[data-add]");
    if (add) { addValue(box, add.dataset.add); return; }
    const drop = ev.target.closest("[data-drop]");
    if (drop) { dropValue(box, drop.closest(".tag").dataset.v); }
  });
}

/* -- 4 buttons that would run something ---------------------------------- */
let said = false;
function sayItIsADemo(what) {
  if (said) return;
  said = true;
  const bar = document.createElement("div");
  bar.className = "note";
  bar.style.cssText = "position:fixed;left:50%;bottom:18px;transform:translateX(-50%);" +
                      "z-index:99;box-shadow:var(--shadow-pop);max-width:620px";
  bar.innerHTML = "<span>&#9432;</span><span></span>";
  bar.lastChild.innerHTML =
    "<b>prototype</b> - <code></code> is a layout, not a command. " +
    "nothing was started and nothing will be; the back end is not wired yet.";
  bar.querySelector("code").textContent = what;
  document.body.appendChild(bar);
  setTimeout(() => bar.remove(), 4200);
}

/* -- boot ---------------------------------------------------------------- */
let lang = "en";
let theme = "";
try {
  lang = localStorage.getItem("kci-lang") || "en";
  theme = localStorage.getItem("kci-theme") || "";
} catch (e) { /* private window: the defaults stand */ }
if (!THEMES.includes(theme)) theme = "";

$$('input[name="lang"]').forEach((i) => i.addEventListener("change", () => setLang(i.value)));
setLang(lang);
setTheme(theme);

const themeBtn = $("#theme");
if (themeBtn) {
  themeBtn.addEventListener("click", () => {
    setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]);
    theme = document.documentElement.dataset.theme;
  });
}

$$(".multi").forEach(wireMulti);
document.addEventListener("click", (ev) => {
  $$(".multi").forEach((box) => {
    if (!box.contains(ev.target)) box.querySelector(".menu").hidden = true;
  });
});

$$("button.btn").forEach((b) => {
  if (b.id === "theme") return;
  b.addEventListener("click", () => sayItIsADemo(b.textContent.trim().slice(0, 40)));
});

/* a link to "#live" or a row's own anchor opens the strip it points at */
if (location.hash === "#live") {
  const strip = $(".live");
  if (strip) strip.open = true;
}
})();
