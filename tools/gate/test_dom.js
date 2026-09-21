// A 150-line fake DOM, so the shipped script can be driven without a browser.
//
// It exists for the claims that are otherwise unverifiable here:
//   * `_rail` — the slider is a *duplicate view* of a box that carries `name`, and
//     the rail itself carries none, so it can never submit a second value;
//   * the log link — every 日志 link used to be taken over by an
//     `onclick="showLog(...);return false"` that drew a tail into a box on the page
//     (`showLog`/`dashLog`/`.logbox`).  The box is gone, so the claim is now about
//     the *link*: the panel row, the activity table row and the finish notice all
//     point at `/runs/<id>/log` (the whole log, `text/plain`) with
//     `target="_blank" rel="noopener"` and no `onclick` at all — the script's own
//     builder and the server's, which have to agree or a refresh re-shapes the row;
//   * the filter bar's fourth control shape — an `<input list="…">` is browsed with
//     the arrow keys exactly like a select, because Firefox opens a datalist on the
//     down arrow, and the `browsing` whitelist left it out;
//   * the filter bar's **fifth** control shape — a multi-valued axis, which
//     `design/ui.py::multi` draws as chips, a menu and one free box
//     (`schema.MULTI_FIELDS`).  It is the one shape whose `change` is *not* a
//     decision ("pick these three, then apply"), so the control and its box carry
//     `data-multi` and the same listener skips them; the assertion also drives the
//     server, because a guard on an attribute nothing renders is a guard that does
//     nothing;
//   * `keepPlace` — a filter bar has to remember the **destination** URL before it
//     navigates, or the page the reader lands on restores nothing and starts at the
//     top (`restorePlace` matches the whole URL).
//
// Run:  node tools/gate/test_dom.js
//
// The script under test is the module that serves it,
// `lib/gui/design/script.py`'s `_JS` **as shipped** - extracted here by
// running `import lib.gui` and printing `_JS`, never copied - because the bugs
// this file exists for (a slider that could submit twice, a log link that did nothing
// without JavaScript) live in that string and nowhere else.  `--check`-style tools
// cannot see either: both are valid JavaScript that does the wrong thing at runtime.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');   // the repository root
const SCRIPT = process.argv[2] || null;

let registry = [];
let byId = {};

function el(tag, attrs = {}) {
  const node = {
    tagName: String(tag).toUpperCase(),
    attrs: { ...attrs },
    children: [],
    value: attrs.value === undefined ? '' : String(attrs.value),
    textContent: '',
    innerHTML: '',
    className: attrs.class || '',
    dataset: {},
    listeners: {},
    hidden: false,
    id: attrs.id || '',
    type: attrs.type || '',
    classList: {
      _set: new Set(String(attrs.class || '').split(/\s+/).filter(Boolean)),
      add(c) { this._set.add(c); node.attrs.class = [...this._set].join(' '); },
      contains(c) { return this._set.has(c); },
    },
    getAttribute(name) { return name in node.attrs ? String(node.attrs[name]) : null; },
    hasAttribute(name) { return name in node.attrs; },
    setAttribute(name, value) { node.attrs[name] = String(value); },
    addEventListener(kind, fn) { (node.listeners[kind] = node.listeners[kind] || []).push(fn); },
    dispatchEvent(event) {
      if (!event.target) { event.target = node; }   // a browser sets this, my stub must too
      (node.listeners[event.type] || []).forEach((fn) => fn(event));
      // The bar's own listener is on the form and bubbles: model that.
      if (event.bubbles && node.parent) { node.parent.dispatchEvent(event); }
    },
    insertAdjacentElement(where, child) { child.parent = node; node.children.push(child); return child; },
    closest(sel) {
      // `#live, #runs` is one selector with two names (`busyHere`), so the comma is
      // split here the way `matches` splits it; every other caller asks for one
      // `.class` and gets the old behaviour.
      const want = sel.split(',').map((s) => s.trim());
      let one = node;
      while (one) {
        for (const s of want) {
          const hit = s.charAt(0) === '#'
            ? one.id === s.slice(1)
            : one.classList.contains(s.replace(/^\./, ''));
          if (hit) { return one; }
        }
        one = one.parent;
      }
      return null;
    },
    append(child) { child.parent = node; node.children.push(child); },
    submit() { node.submitted = (node.submitted || 0) + 1; },
    querySelectorAll(sel) { return all().filter((one) => matches(one, sel)); },
    querySelector(sel) { return node.querySelectorAll(sel)[0] || null; },
  };
  // `rail.className = 'rail'` must be visible to `classList.contains`, or the test
  // would be measuring its own stub instead of the page's script.
  Object.defineProperty(node, 'className', {
    get() { return node.attrs.class || ''; },
    set(value) {
      node.attrs.class = String(value);
      node.classList._set = new Set(String(value).split(/\s+/).filter(Boolean));
    },
  });
  if (node.id) { byId[node.id] = node; }
  registry.push(node);
  return node;
}

function all() { return registry; }

function matches(one, sel) {
  const list = sel.split(',').map((s) => s.trim());
  return list.some((s) => {
    let notClass = null;
    const not = s.match(/:not\(\s*\.([\w-]+)\s*\)/);
    if (not) { notClass = not[1]; s = s.replace(not[0], ''); }
    if (notClass && one.classList.contains(notClass)) { return false; }
    const m = s.match(/^([a-z]*)(\[[\w-]+(?:="[^"]*")?\])?$/);
    if (!m) { return false; }
    if (m[1] && one.tagName !== m[1].toUpperCase()) { return false; }
    if (!m[2]) { return true; }
    const a = m[2].match(/\[([\w-]+)(?:="([^"]*)")?\]/);
    const value = one.getAttribute(a[1]);
    return a[2] === undefined ? value !== null : value === a[2];
  });
}

// --- the page's own listener, copied in shape from `_JS` --------------------
// The form's own `change` listener is NOT registered here: `_JS` registers it
// itself (`document.querySelectorAll('form[data-auto]').forEach(...)`) the moment the
// script is evaluated, and a second copy in this harness would double every count -
// which it did, and reported "release submits twice" for a one-submit script.
//
// `action` is there because a filter bar is a GET form and `barTarget` needs the
// address it is about to load; `#runs` is there because `busyHere` asks whether the
// reader's focus is inside the activity table.
const form = el('form', { 'data-auto': '1', method: 'get', action: '/jobs' });
const runsTable = el('table', { id: 'runs' });
const box = el('input', { id: 'f-days', name: 'days', type: 'number', value: '30',
                          'data-stops': JSON.stringify(['0', '1', '3', '7', '14', '30', '90']) });
box.parent = form;
form.append(box);
// The fourth control shape in a filter bar: a suggestion box (`<input list="…">`),
// which Firefox opens a datalist on.
const named = el('input', { id: 'f-tree', name: 'tree', value: '', list: 'trees' });
named.parent = form;
form.append(named);

// --- the environment the script expects ------------------------------------
// `sessionStorage` is a real one (a Map in a box), so a claim about what the bar
// remembers is a claim about the value it wrote, and `FormData`/`URL`/`URLSearchParams`
// are Node's own - `barTarget` builds the destination URL out of them, and a stub that
// answered differently from a browser would make "the reader lands where the place was
// kept" untestable.
const sandbox = {
  console,
  // The real names, out of `_JS_WORDS` - not copied: `_js` injects exactly these and
  // the log box's two (`loading`, `empty`) are gone with the box.
  I18N: { log: 'log', cancel: 'cancel', sending: 'sending',
          started: 'started', rejected: 'rejected', unreachable: 'unreachable',
          // The pill's and the tally's words, injected by `_js` in a real page: the
          // state cell is written here too, and a missing map must not be the reason a
          // row comes back differently.
          end_word: { '0': 'done', '1': 'tests failed', '3': 'incomplete (infra)' },
          tally: [['pass', 'pass'], ['fail', 'fail']], tally_one: '{n} {word}' },
  DIGEST: 'abc',
  sessionStorage: {
    _map: {},
    getItem(k) { return k in this._map ? this._map[k] : null; },
    setItem(k, v) { this._map[k] = String(v); },
    removeItem(k) { delete this._map[k]; },
  },
  URL,
  URLSearchParams,
  FormData: class FormData {
    // The one half of the real thing `barTarget` uses: the form's named controls, in
    // the order the browser would serialise them.
    constructor(form) {
      this.pairs = [];
      const walk = (one) => {
        (one.children || []).forEach((child) => {
          if (child.getAttribute('name') !== null) {
            this.pairs.push([child.getAttribute('name'), child.value]);
          }
          walk(child);
        });
      };
      walk(form);
    }

    [Symbol.iterator]() { return this.pairs[Symbol.iterator](); }
  },
  fetch() {
    // Nothing here calls it any more: the log box (the only reader of
    // `/api/runs/<id>/log`) is gone, and the poll itself is never started by this
    // harness.  It stays because `_JS` refers to `fetch` and a missing global would
    // be a `ReferenceError` waiting for the next test that does call it.
    return Promise.resolve({ json: () => Promise.resolve({ digest: 'abc', runs: [] }) });
  },
  setInterval() { return 0; },
  setTimeout() { return 0; },
  location: { href: 'http://127.0.0.1:8079/jobs', reload() { sandbox.reloaded = true; } },
  document: {
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => el(tag),
    querySelectorAll: (sel) => all().filter((one) => matches(one, sel)),
    querySelector: (sel) => all().filter((one) => matches(one, sel))[0] || null,
    addEventListener() {},
    activeElement: null,
  },
  window: { addEventListener() {}, },
  Event: class Event {
    constructor(type, opts = {}) { this.type = type; this.bubbles = !!opts.bubbles;
                                   this.key = opts.key || '';
                                   this.target = null; }
  },
};
sandbox.window.document = sandbox.document;
vm.createContext(sandbox);
vm.runInContext(SCRIPT ? fs.readFileSync(SCRIPT, 'utf8') : page_js(), sandbox);

function page_js() {
  // The shipped script, straight out of the module that serves it.
  return execFileSync('python3', ['-c',
    "import sys; sys.path.insert(0, '.'); import lib.gui; sys.stdout.write(lib.gui._JS)"],
    { cwd: ROOT, encoding: 'utf8' });
}

// --- assertions -------------------------------------------------------------
const out = [];
const rail = all().find((one) => one.classList.contains('rail'));
const read = all().find((one) => one.classList.contains('railout'));
out.push(['rail built', !!rail && !!read]);
out.push(['rail carries no name (cannot submit)', rail ? rail.getAttribute('name') === null : false]);
out.push(['readout shows the box value', read ? read.textContent === '30' : false]);

rail.value = '2';
rail.dispatchEvent(new sandbox.Event('input', { bubbles: true }));
out.push(['slide to index 2 -> box value 3', box.value === '3']);
out.push(['slide moves the readout', read.textContent === '3']);
out.push(['slide alone does not submit', !form.submitted]);

rail.dispatchEvent(new sandbox.Event('change', { bubbles: true }));
out.push(['release submits once', form.submitted === 1]);
console.log('   form.submit() calls on release:', form.submitted);

box.value = '45';
box.dispatchEvent(new sandbox.Event('input', { bubbles: true }));
out.push(['a typed value is printed, not refused', read.textContent === '45']);
out.push(['a typed value is marked off-scale', read.dataset.off === '1']);
out.push(['the rail keeps its index', rail.value === 2]);

// --- the fourth control shape: an `<input list="…">` ------------------------
// The operator's 「有时候按某些键下面的会突然跳到头顶」, in the shape the first fix
// missed.  Firefox opens a datalist on the down arrow: the value changes and a
// `change` fires, so an unguarded listener submitted the form and reloaded the page.
const before = form.submitted;
named.dispatchEvent(new sandbox.Event('keydown', { bubbles: true, key: 'ArrowDown' }));
named.dispatchEvent(new sandbox.Event('change', { bubbles: true }));
out.push(['an arrow in a datalist box does not submit', form.submitted === before]);
// …and a mouse-committed change on the same box does, which is the gesture the
// whitelist exists to allow (`mouseup` clears `browsing`).
named.dispatchEvent(new sandbox.Event('mouseup', { bubbles: true }));
named.dispatchEvent(new sandbox.Event('change', { bubbles: true }));
out.push(['a committed change still submits', form.submitted === before + 1]);
// The destination, not the page the reader is leaving: `restorePlace` matches the
// whole URL, and a bar that kept `location.href` restored nothing on the page it
// submitted to.  The fields are the form's own, in the order the browser serialises
// them (`days=45` from the box, `tree=` empty - a GET form sends an empty field).
const place = JSON.parse(sandbox.sessionStorage.getItem('kci.place') || 'null');
out.push(['the bar keeps the destination URL it is about to load',
          !!place && place.url === 'http://127.0.0.1:8079/jobs?days=45&tree=']);
out.push(['and keeps it under the key `restorePlace` reads', !!place && 'at' in place]);

// --- busyHere: the poll may not rewrite what the reader is inside -----------
// Not a keystroke and not a reload, but the same complaint: the panel and the
// activity table are replaced wholesale every 2 s.
const inside = el('td', { class: '' });
inside.parent = runsTable;
sandbox.document.activeElement = inside;
out.push(['a reader focused inside #runs is busy', sandbox.busyHere() === true]);
sandbox.document.activeElement = box;
out.push(['a reader typing in the filter bar is busy too', sandbox.busyHere() === true]);
sandbox.document.activeElement = null;
out.push(['no focus at all leaves the poll free to rewrite', sandbox.busyHere() === false]);

// --- the fifth control shape: several values of one axis at once ------------
// A multi-valued axis (`schema.MULTI_FIELDS`) is a set the reader composes and then
// commits - `design/ui.py::multi` draws the values in force as chips, the rest of the
// candidate list as a menu, and one free box under the axis' own name - and choosing is
// not a decision: the gesture is "pick these three, then apply".  A bar that submitted
// on the first change would reload the page once per pick and pay an API read for each
// of those loads — the same class of waste the `browsing` whitelist above exists to stop.
//
// The free box is the one element of that control the shipped bar's listener can see a
// `change` on (the chips and the menu are `button`s the bridge wires), and it carries the
// attribute the listener reads; so does the control around it, which is what
// `closest('[data-multi]')` finds from any descendant.
const tick = el('input', { id: 'f-tree', name: 'tree', type: 'text', 'data-multi': '1' });
tick.parent = form;
form.append(tick);
const beforeTick = form.submitted;
tick.value = 'riscv';
tick.dispatchEvent(new sandbox.Event('change', { bubbles: true }));
out.push(['a multi-valued box does not submit on its own', form.submitted === beforeTick]);
// A click on the same box clears `browsing` and still must not submit: this control is
// committed by `apply` and by nothing else.
tick.dispatchEvent(new sandbox.Event('mouseup', { bubbles: true }));
tick.dispatchEvent(new sandbox.Event('change', { bubbles: true }));
out.push(['a clicked multi-valued box does not submit either', form.submitted === beforeTick]);
// The other half of the same claim, driven server-side: a guard on an attribute nothing
// renders is a guard that does nothing.  `design/ui.py::multi` is its only writer.
const group = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); " +
  "from lib.gui.design import ui; " +
  "sys.stdout.write(ui.multi('tree', ['riscv'], ['riscv', 'mainline'], " +
  "                          'filter.type_one', 'word.tree', lang='en'))"],
  { cwd: ROOT, encoding: 'utf8' });
out.push(['the server marks the whole control with the attribute the script reads',
          /class="multi"[^>]*data-multi="1"/.test(group)
          && /<input type="text" name="tree"[^>]*data-multi="1"/.test(group)]);
out.push(['and draws the values in force as the chosen ones',
          /data-v="riscv"/.test(group) && !/data-v="mainline"/.test(group)
          && /data-add="mainline"/.test(group)]);
// The free box is still there under the axis' own name: it is where a value the
// candidate list does not carry is typed, and where a value in force that the list does
// not offer comes back to.  With the script off it is the only way to add one.
out.push(['and the free box beside them still takes a name nobody listed',
          /<input type="text" name="tree"/.test(group)]);

// --- the log link: the whole log, in a tab of its own -----------------------
// The box these assertions used to drive is gone.  What replaced it is not "nothing":
// a click on 日志 is now a **navigation** to `/runs/<id>/log`, which serves the whole
// log as `text/plain` (`lib/gui/server.py`, `log_body`) rather than the tail the box
// polled for at `?offset=`.  So the claim to check is the link itself, in both the
// places that write it: the script's own `liveRow` (in the shipped `_JS`, below) and
// the server's `shell.live_row`/`runs._acts_cell` (which draw the panel and the runs
// table the poll only ever *updates* - a link that changed shape on refresh would be a
// second, disagreeing answer to one question).
const opensLog = (html) => /<a href="\/runs\/[^"]+\/log" target="_blank" rel="noopener"/.test(html);
const row = sandbox.liveRow({ id: 'A', kind: 'pull', state: 'running', what: 'x',
                              seconds: 5, exit_code: null, argv: ['x'], started: 1 });
out.push(['the panel row\'s log link is the whole log, in its own tab',
          opensLog(row)]);
out.push(['and nothing intercepts the click any more',
          !/showLog/.test(row) && !/onclick/.test(row)]);
const served = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); " +
  "from lib.gui.design.shell import live_row; " +
  "from lib.gui.design.pages.runs import _acts_cell; " +
  "sys.stdout.write(live_row({'id': 'A', 'state': 'running', 'exit_code': None, " +
  "                           'argv': ['x'], 'started': 1.0, 'seconds': 5, " +
  "                           'what': 'x'}, 'en') + '\\n' + " +
  "                 _acts_cell({'id': 'A', 'state': 'running'}, 'en'))"],
  { cwd: ROOT, encoding: 'utf8' });
const servedLines = served.split('\n');
out.push(['the server writes the same link for the panel row and the runs row',
          servedLines.length === 2 && servedLines.every(opensLog)]);
out.push(['and the server does not draw a log box any more',
          !/logbox|showLog/.test(served)]);

(async () => {
  let bad = 0;
  for (const [name, ok] of out) {
    if (!ok) { bad += 1; }
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}`);
  }
  console.log(bad ? `${bad} failed` : `all ${out.length} passed`);
  process.exit(bad ? 1 : 0);
})();
