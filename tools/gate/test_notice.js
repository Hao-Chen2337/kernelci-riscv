#!/usr/bin/env node
// Drive the shipped poll script (`lib/gui/design/script.py`'s `_JS`, **as served** by
// `lib.gui`) under node with a
// fake DOM and canned `/api/state` answers, and count what lands in `#notice`.
//
//     node tools/gate/test_notice.js [en|zh]
//
// Why this exists: R2 ("a finished run announces itself") and the rule behind it are
// invisible to every Python check - they are *when* a notice fires, decided by a
// script the server only ever prints.  The one requirement the brief calls out by name
// is that a **reload must not re-announce an old finish**, and that is a claim about
// time (a run's own `ended` against the page's `data-drawn`), so it can only be tested
// by driving the script.  Each scenario is `(moment the page was drawn, [poll answers])`
// and the assertion is what `#notice` holds afterwards.
//
// The script under test is fetched from the module that serves it, never copied: a
// harness holding its own copy of the poll would keep passing after the page changed.
// The same fake-DOM approach as `test_dom.js`; there is no log box to model any more
// (the 日志 link is a plain link to `/runs/<id>/log`), so only what the notice and the
// panel need is built here.
//
// Scenarios are (pageDrawn, [answers…], digest) and the assertion is the number of
// notice cards afterwards - the same shape 07-shell.md §B5.1 used, because the rules
// are about *when* a notice fires and reading the code cannot prove it.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const LANG = (process.argv[2] || 'en').replace(/[^a-z]/g, '') || 'en';

// The script as the page receives it: `_js(lang, digest)` - the digest is a fixed
// string here because the trigger's own behaviour is scenario S9's subject.
const SCRIPT = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); import lib.gui as g; " +
  `sys.stdout.write(g._js('${LANG}', 'abc123'))`], { cwd: ROOT, encoding: 'utf8' });
const I18N = JSON.parse(SCRIPT.match(/^var I18N = (.*);$/m)[1]);

function el(tag, attrs = {}) {
  const node = {
    tagName: String(tag).toUpperCase(), attrs: { ...attrs }, children: [],
    textContent: '', innerHTML: '', hidden: false, id: attrs.id || '',
    classList: { _set: new Set(String(attrs.class || '').split(/\s+/).filter(Boolean)),
                 add(c) { this._set.add(c); },
                 contains(c) { return this._set.has(c); } },
    getAttribute(n) { return n in node.attrs ? String(node.attrs[n]) : null; },
    setAttribute(n, v) { node.attrs[n] = String(v); },
    addEventListener() {},
    appendChild(c) { c.parentNode = node; node.children.push(c); return c; },
    removeChild(c) { node.children = node.children.filter((o) => o !== c); return c; },
    closest(sel) {
      const want = sel.replace(/^\./, '').replace(/^\[|\]$/g, '');
      let one = node;
      while (one) {
        if (one.classList.contains(want) || want in one.attrs) { return one; }
        one = one.parentNode;
      }
      return null;
    },
    querySelectorAll(sel) { return all().filter((o) => matches(o, sel)); },
    querySelector(sel) { return node.querySelectorAll(sel)[0] || null; },
    insertAdjacentElement() { return null; },
    scrollIntoView() {},
  };
  Object.defineProperty(node, 'className', {
    get() { return node.attrs.class || ''; },
    set(v) { node.attrs.class = String(v);
             node.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
  });
  registry.push(node);
  return node;
}
let registry = [];
function all() { return registry; }
function parsePart(s) {
  const out = { tag: null, id: null, cls: [], attr: null, val: undefined };
  let rest = s, m;
  if ((m = rest.match(/^([a-zA-Z]+)/))) { out.tag = m[1].toUpperCase(); rest = rest.slice(m[1].length); }
  if ((m = rest.match(/^#([\w-]+)/))) { out.id = m[1]; rest = rest.slice(m[0].length); }
  while ((m = rest.match(/^\.([\w-]+)/))) { out.cls.push(m[1]); rest = rest.slice(m[0].length); }
  if ((m = rest.match(/^\[([\w-]+)(?:="([^"]*)")?\]/))) {
    out.attr = m[1]; out.val = m[2]; rest = rest.slice(m[0].length);
  }
  return rest.trim() === '' ? out : null;
}
function matchesOne(one, part) {
  if (!part) { return false; }
  if (part.tag && one.tagName !== part.tag) { return false; }
  if (part.id && one.id !== part.id) { return false; }
  if (part.cls.some((c) => !one.classList.contains(c))) { return false; }
  if (part.attr) {
    const v = one.getAttribute(part.attr);
    if (part.val === undefined ? v === null : v !== part.val) { return false; }
  }
  return true;
}
function matches(node, sel) {
  return sel.split(',').map((s) => s.trim()).filter(Boolean).some((s) => {
    const parts = s.split(/\s+/).map(parsePart);
    if (parts.some((p) => !p)) { return false; }
    if (!matchesOne(node, parts[parts.length - 1])) { return false; }
    let up = node.parentNode;
    for (let i = parts.length - 2; i >= 0; i--) {
      let ok = false;
      while (up) { if (matchesOne(up, parts[i])) { ok = true; up = up.parentNode; break; } up = up.parentNode; }
      if (!ok) { return false; }
    }
    return true;
  });
}

// A page as the server draws it: the panel, the header chip, the body's data-drawn.
function build(pageDrawn, storage, tableRows, digest) {
  registry = [];
  const body = el('body', { 'data-drawn': String(pageDrawn) });
  const panel = el('details', { class: 'live', id: 'live' });
  el('summary', { class: 'live-tab' }).parentNode = panel;
  const liveWord = el('span', { class: 'live-word' });
  liveWord.textContent = 'nothing running';
  const bodyBox = el('div', { class: 'live-body' });
  const headWord = el('b', { class: 'live-headword' });
  const count = el('span', { class: 'live-count' });
  const list = el('ul', { class: 'live-list' });
  const empty = el('p', { class: 'live-empty' });
  bodyBox.appendChild(list);
  panel.appendChild(liveWord); panel.appendChild(bodyBox);
  bodyBox.appendChild(headWord); bodyBox.appendChild(count); bodyBox.appendChild(empty);
  body.appendChild(panel);
  const noticeBox = el('div', { id: 'notice' });
  body.appendChild(noticeBox);
  if (tableRows !== undefined && tableRows !== null) {
    const table = el('table', { id: 'runs', 'data-rows': tableRows, 'data-kinds': '' });
    const tbody = el('tbody');
    table.appendChild(tbody);
    body.appendChild(table);
  }
  const sandbox = {
    console,
    I18N: I18N,
    LIVE_KEPT: 3,
    DIGEST: digest || 'base',
    fetch: (url) => Promise.resolve({ json: () => Promise.resolve(sandbox.__answer) }),
    setInterval() { return 0; }, setTimeout() { return 0; },
    location: { reload() { sandbox.reloaded = (sandbox.reloaded || 0) + 1; } },
    encodeURIComponent,
    document: {
      title: 'kernelci-riscv runs', hidden: false, activeElement: null,
      getElementById: (id) => all().find((o) => o.id === id) || null,
      createElement: (tag) => el(tag),
      querySelectorAll: (sel) => all().filter((o) => matches(o, sel)),
      querySelector: (sel) => all().filter((o) => matches(o, sel))[0] || null,
      addEventListener() {}, body,
    },
    window: { addEventListener() {}, sessionStorage: storage },
  };
  sandbox.window.document = sandbox.document;
  vm.createContext(sandbox);
  vm.runInContext(SCRIPT, sandbox);
  return { sandbox, digest: sandbox.DIGEST, notices: () => noticeBox.children.length,
           noticeText: () => noticeBox.children.map((o) => o.className + ': ' + o.innerHTML).join(' | '),
           listHtml: () => list.innerHTML };
}
function store() {
  const map = new Map();
  return { getItem: (k) => (map.has(k) ? map.get(k) : null),
           setItem: (k, v) => map.set(k, String(v)),
           removeItem: (k) => map.delete(k) };
}
const drain = () => new Promise((r) => setImmediate(r));
const run = (r) => ({ id: r.id, kind: r.kind || 'pull', state: r.state,
                      what: r.what || 'x', age: '1m', seconds: r.seconds || 5,
                      log: '/tmp/log', exit_code: r.exit_code === undefined ? null : r.exit_code,
                      argv: ['/bin/sh', '-c', 'x'],
                      started: r.started === undefined ? 100 : r.started,
                      ended: r.ended === undefined ? 0 : r.ended });

const out = [];
function check(name, ok, note) { out.push([name, ok, note]); }

(async () => {
  // S1: watched a run from running -> done, ended after the page was drawn.
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    const live1 = dom.listHtml();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1005 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S1 watched running->done: one notice, panel keeps the ended row',
          dom.notices() === 1 && /live-row running/.test(live1) && /live-row ended/.test(dom.listHtml()),
          `notices=${dom.notices()} firstPollHasRunningRow=${/live-row running/.test(live1)}`);
  }
  // S2: a reload after the fact - already done, ended BEFORE this page was drawn.
  {
    const dom = build(2000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 900, ended: 1500 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S2 reload after the fact: no notice', dom.notices() === 0,
          `notices=${dom.notices()}`);
  }
  // S3: finished between two polls - never seen running, but ended after the draw.
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'B', state: 'done', exit_code: 3, started: 1001, ended: 1002 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S3 finish between two polls: one notice (truth 2, `ended`)',
          dom.notices() === 1, `notices=${dom.notices()} text=${dom.noticeText()}`);
  }
  // S4: old JSON without `ended`/`started` - truth 1 only.
  {
    const dom = build(1000, store(), '');
    const THIS = dom;
    const bare = (state, code) => ({ id: 'C', kind: 'run', state, what: 'x', age: '1s',
                                     seconds: 2, log: '/tmp/l', exit_code: code,
                                     argv: ['/bin/sh'] });
    dom.sandbox.__answer = { digest: THIS.digest, runs: [bare('running', null)] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [bare('done', 0)] };
    await dom.sandbox.livePoll(); await drain();
    check('S4 finish while watching, no started/ended fields: one notice',
          dom.notices() === 1, `notices=${dom.notices()}`);
  }
  // S5: two runs, one ends - only that one.
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 }),
                                                    run({ id: 'B', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 }),
                                                    run({ id: 'B', state: 'failed', exit_code: 3, started: 1001, ended: 1003 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S5 two running, one ends: exactly one notice', dom.notices() === 1,
          `notices=${dom.notices()} text=${dom.noticeText()}`);
  }
  // S6: a reused id in the same second must not be swallowed (key is id@started).
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1002 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1002 }),
                                                    run({ id: 'A', state: 'done', exit_code: 1, started: 1060, ended: 1061 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S6 same id, new `started`: announced as its own finish', dom.notices() === 2,
          `notices=${dom.notices()}`);
  }
  // S7: an exit code that was never seen is NOT announced as failed.
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'failed', exit_code: null, started: 1001, ended: 1004 })] };
    await dom.sandbox.livePoll(); await drain();
    const text = dom.noticeText();
    check('S7 no exit code seen: notice says so, is not the failed colour',
          dom.notices() === 1 && /^notice unknown/.test(text) && !/notice failed/.test(text),
          text.slice(0, 170));
  }
  // S8: an id that vanished was deleted, not finished.
  {
    const dom = build(1000, store(), ''); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'G', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'Z', state: 'done', ended: 500, started: 400 })] };
    await dom.sandbox.livePoll(); await drain();
    // Language-independent on purpose: this test runs in either language, so it
    // asserts the *shape* (a warn card whose text is not the done/failed sentence)
    // and leaves the wording to `lib/i18n.py`'s own check.
    const goneText = dom.noticeText();
    check('S8 a vanished id is "no longer on disk", not done/failed',
          dom.notices() === 1 && /^notice unknown/.test(goneText)
          && /\bG\b/.test(goneText) && !/exit \d/.test(goneText),
          goneText.slice(0, 170));
  }
  // S9: the digest trigger still reloads, and the notice survives that reload.
  {
    const storage = store();
    const dom = build(1000, storage, ''); const THIS = dom;
    const moved = dom.digest + '-moved';
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: moved, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1005 })] };
    await dom.sandbox.livePoll(); await drain();
    const carriedRaw = storage.getItem('kci-notice');
    const second = build(1100, storage, '');                 // the reloaded page
    second.sandbox.__answer = { digest: second.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1005 })] };
    await second.sandbox.livePoll(); await drain();
    const third = build(1200, storage, '');                  // and a manual reload later
    third.sandbox.__answer = { digest: third.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, started: 1001, ended: 1005 })] };
    await third.sandbox.livePoll(); await drain();
    const carriedCard = second.noticeText();
    // The card's own log link, and the *form* of it that counts: `/runs/<id>/log` is
    // the whole log as `text/plain` (`lib/gui/server.py`, `log_body`) and the notice
    // opens it in a tab of its own.  What stood here was `/\/log\?offset=0/` - the
    // query string of the JSON tail endpoint the removed log box polled - and it was
    // stale for as long as nobody ran this file (`verify.py` never listed it): the
    // string `offset=0` appears nowhere in `lib/gui` and `server.py` ignores query
    // params on that route, so the assertion could never have passed again.
    check('S9 digest change reloads once, the notice rides across it with its own controls, and a later reload does not repeat it',
          dom.sandbox.reloaded === 1 && !!carriedRaw && second.notices() === 1 && third.notices() === 0
          && /data-dismiss/.test(carriedCard)
          && /<a href="\/runs\/A\/log" target="_blank" rel="noopener">/.test(carriedCard),
          `reloads=${dom.sandbox.reloaded} carried=${!!carriedRaw} afterReload=${second.notices()} thirdLoad=${third.notices()} card=${carriedCard.slice(0, 130)}`);
  }
  // S10: no digest change -> no reload; the table is patched only with data-rows=all.
  {
    const dom = build(1000, store(), 'all'); const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, ended: 1, started: 1 })] };
    await dom.sandbox.livePoll(); await drain();
    const patched = dom.sandbox.document.querySelector('#runs tbody').innerHTML;
    // The same answer on a page whose table was drawn from a filter: `data-rows` is
    // absent, so the poll must leave the reader's rows alone (N2).
    const filtered = build(1000, store(), '');
    filtered.sandbox.__answer = { digest: filtered.digest, runs: [run({ id: 'A', state: 'done', exit_code: 0, ended: 1, started: 1 })] };
    await filtered.sandbox.livePoll(); await drain();
    const untouched = filtered.sandbox.document.querySelector('#runs tbody').innerHTML;
    check('S10 table patched only when data-rows="all" (N2); no reload without a digest change',
          dom.sandbox.reloaded === undefined && patched.length > 0 && untouched === '',
          `reloads=${dom.sandbox.reloaded} allRowsPatched=${patched.length}B filteredPatched=${untouched.length}B`);
  }

  // S11: a cancel is announced as a cancel, not as a failure with exit -15.
  {
    const dom = build(1000, store(), '');
    const THIS = dom;
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'running', started: 1001 })] };
    await dom.sandbox.livePoll(); await drain();
    dom.sandbox.__answer = { digest: THIS.digest, runs: [run({ id: 'A', state: 'cancelled', exit_code: -15, started: 1001, ended: 1003 })] };
    await dom.sandbox.livePoll(); await drain();
    check('S11 a cancelled run is announced as cancelled',
          dom.notices() === 1 && /^notice cancelled/.test(dom.noticeText())
          && /cancelled/.test(dom.noticeText()) && !/failed/.test(dom.noticeText()),
          dom.noticeText().slice(0, 120));
  }

  let bad = 0;
  for (const [name, ok, note] of out) {
    if (!ok) { bad += 1; }
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${note ? '   [' + note + ']' : ''}`);
  }
  console.log(bad ? `${bad} failed` : `all ${out.length} passed`);
  process.exit(bad ? 1 : 0);
})();
