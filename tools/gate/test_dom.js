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
//     top (`restorePlace` matches the whole URL);
//   * `buildFolds` — the 更多筛选 row's open state (the operator's 「更多筛选这里好像
//     也没有持久化」) and every other fold's, kept by name in `localStorage`.  Both
//     halves are here: the script's read and write, driven on folds that were on the
//     page before it ran, and the `data-fold` names the server writes, driven by
//     rendering `ui.more`/`ui.panel`/`shell.live` — an attribute nothing renders is a
//     memory that remembers nothing;
//   * the row ticks (`tickSave`/`tickRestore`) — a tick lives outside its form
//     (`form="pull-now"`), so nothing in the URL carries it, and the column is drawn
//     by the server on the way back from a filter change, which knows nothing about
//     anything ticked (the operator's 「两个东西勾好了，我去改了其他的东西，它刷新
//     界面两个勾也没有」).  Both halves again: what the script writes and puts back,
//     and the `input[form]` shape `ui.checkbox(form=…)` is the only writer of;
//   * the action POST's **body**, and the one field in it that is a button's own: the
//     re-run button carries `redo=1` on itself (`ui.action_form`'s `also`), which a
//     browser adds to the form's data and `new FormData(form)` does not - so a script
//     that kept that spelling would run the plain command over this path and the re-run
//     over the no-script one (「难道就不能默认增加重跑？」).  Driving it is what made the
//     stub grow `Element.matches`, compound attribute selectors and `document`'s own
//     listeners: the delegated `submit` listener opens with a two-group selector and is
//     reached by bubbling, and without them it returned before its first line.
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
    // `Element.matches`, which the script's delegated `submit` listener asks with: the
    // action POST is that listener's, and without this method it returned before its
    // first line - a body nothing could assert on.
    matches(sel) { return matches(node, sel); },
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
  // A `<details>`'s `open`, reflected the way a browser reflects it: the element with
  // no `open` attribute answers `false` and not `undefined`, which is what the fold
  // memory reads before it writes, and what a fold left alone is asserted against.
  if (String(tag).toLowerCase() === 'details') { node.open = attrs.open !== undefined; }
  if (node.id) { byId[node.id] = node; }
  registry.push(node);
  return node;
}

function all() { return registry; }

// A selector is a tag and **any number** of attribute groups, which is one group more
// than this used to read: `form[method="post"][action^="/api/actions/"]` - the guard the
// delegated `submit` listener opens with, and therefore the action POST - is two, and
// the old one-group regex answered `false` for it, so that listener returned before its
// first line and the body it builds could not be asserted on at all.  The operators are
// the ones `_JS` uses: `=`, `^=` and `$=`, and a bare `[attr]` (present at all).
function matches(one, sel) {
  const list = sel.split(',').map((s) => s.trim());
  return list.some((s) => {
    let notClass = null;
    const not = s.match(/:not\(\s*\.([\w-]+)\s*\)/);
    if (not) { notClass = not[1]; s = s.replace(not[0], ''); }
    if (notClass && one.classList.contains(notClass)) { return false; }
    const m = s.match(/^([a-z]*)((?:\[[\w-]+(?:[~^$*|]?="[^"]*")?\])*)$/);
    if (!m) { return false; }
    if (m[1] && one.tagName !== m[1].toUpperCase()) { return false; }
    return (m[2].match(/\[[\w-]+(?:[~^$*|]?="[^"]*")?\]/g) || []).every((group) => {
      // The operator group takes the `=` with it (`^=` and not `^`), so the comparison
      // below is one string per case rather than a character plus a look at the next.
      const a = group.match(/^\[([\w-]+)(?:([~^$*|]?=)("([^"]*)")?)?\]$/);
      const value = one.getAttribute(a[1]);
      if (value === null) { return false; }
      if (a[2] === undefined) { return true; }
      const want = a[4] === undefined ? '' : a[4];
      if (a[2] === '^=') { return value.startsWith(want); }
      if (a[2] === '$=') { return value.endsWith(want); }
      return value === want;
    });
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

// --- the folds, on the page before the script runs --------------------------
// Three of the shapes `data-fold` is written on, drawn the way the server draws them:
// the activity panel out because something is running (`shell.live`), a panel a page is
// about, and a panel nobody has touched.  They exist before the sandbox is built
// because the server's own answer is what the script reads first - the stored one is
// applied over it, not instead of it.
const foldLive = el('details', { class: 'live', id: 'live', 'data-fold': 'live', open: 'open' });
const foldLedger = el('details', { class: 'panel',
                                   'data-fold': 'page.correspondence.ledger_title' });
const foldRecord = el('details', { class: 'panel',
                                   'data-fold': 'page.correspondence.record_title',
                                   open: 'open' });

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
  // The fold memory's own store, seeded the way a returning reader's browser has it:
  // one stored answer *against* the server's - `live` is drawn open because something
  // is running, and this reader closed it - and nothing at all for the other two.
  // `localStorage` and not `sessionStorage` because that is the one the script uses,
  // and a stub for the wrong one would make a claim about nothing.
  localStorage: {
    _map: { 'kci-folds': JSON.stringify({ live: false }) },
    getItem(k) { return k in this._map ? this._map[k] : null; },
    setItem(k, v) { this._map[k] = String(v); },
    removeItem(k) { delete this._map[k]; },
  },
  URL,
  URLSearchParams,
  FormData: class FormData {
    // The half of the real thing `barTarget` and the action POST use: the form's named
    // controls, in the order the browser would serialise them, plus - when the caller
    // names one - the **pressed button**, whose own `name`/`value` a browser adds to
    // the form's data.  That button is not part of the walk: a `<button>` is never
    // serialised by virtue of being there, only by being the one pressed, which is the
    // whole reason `script.py` passes `e.submitter` and the reason a stub ignoring the
    // second argument would make the re-run button's field untestable.
    constructor(form, submitter) {
      this.pairs = [];
      const walk = (one) => {
        (one.children || []).forEach((child) => {
          if (child.getAttribute('name') !== null && child.tagName !== 'BUTTON') {
            this.pairs.push([child.getAttribute('name'), child.value]);
          }
          walk(child);
        });
      };
      walk(form);
      if (submitter && submitter.tagName === 'BUTTON'
          && submitter.getAttribute('name') !== null) {
        this.pairs.push([submitter.getAttribute('name'), submitter.value]);
      }
    }

    [Symbol.iterator]() { return this.pairs[Symbol.iterator](); }
  },
  fetch(url, opts) {
    // The poll is never started by this harness, so nothing here needs an answer; the
    // one caller is the delegated `submit` listener below, and what is under test is
    // the **body** it built - which fields the pressed button's press sends - so the
    // body is kept where the assertion can read it.
    if (opts && opts.body) { sandbox.posted = { url, body: String(opts.body) }; }
    // The answer this hands back says `note`, which is the branch of the listener that
    // writes the server's own sentence into the form's status and returns: the rest of
    // the chain is about an *activity*, and this stub starts none.
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ digest: 'abc', runs: [] }),
                             text: () => Promise.resolve('{"note":"started"}') });
  },
  setInterval() { return 0; },
  setTimeout() { return 0; },
  // `pathname`/`search` are what `logHref` reads to spell the 日志 link's `?back=` -
  // the page the log's own tab leads back to.  They have to be here for the same
  // reason `href` is: `_JS` refers to them, and a missing one is a `TypeError` that
  // fires only in the test that clicks a log link.
  location: { href: 'http://127.0.0.1:8079/jobs', pathname: '/jobs', search: '',
              reload() { sandbox.reloaded = true; } },
  document: {
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => el(tag),
    querySelectorAll: (sel) => all().filter((one) => matches(one, sel)),
    querySelector: (sel) => all().filter((one) => matches(one, sel))[0] || null,
    // The script's *delegated* listeners are registered here - the action POST's
    // `submit` and the row ticks' `change` - and this used to be a no-op, which made
    // every one of them undrivable: an element can only reach them by bubbling, and
    // there was nothing at the top to catch it.  An element joins that chain by
    // setting `parent` to this object, which is what the action form below does.
    _listeners: {},
    addEventListener(kind, fn) {
      (this._listeners[kind] = this._listeners[kind] || []).push(fn);
    },
    dispatchEvent(event) { (this._listeners[event.type] || []).forEach((fn) => fn(event)); },
    activeElement: null,
  },
  window: { addEventListener() {}, },
  Event: class Event {
    constructor(type, opts = {}) { this.type = type; this.bubbles = !!opts.bubbles;
                                   this.key = opts.key || '';
                                   this.target = null; }
    // A listener that opens with `e.preventDefault()` (the delegated `submit` does,
    // because the POST replaces the navigation) must not be the reason a test crashes:
    // this stub dispatches, it does not navigate, so there is nothing to prevent.
    preventDefault() {}
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
// log as a page (`lib/gui/server.py`, `log_body`) rather than the tail the box polled
// for at `?offset=`.  So the claim to check is the link itself, in both the places that
// write it: the script's own `liveRow` (in the shipped `_JS`, below) and the server's
// `shell.live_row`/`runs._acts_cell` (which draw the panel and the runs table the poll
// only ever *updates* - a link that changed shape on refresh would be a second,
// disagreeing answer to one question).
//
// The link carries `?back=` now, which is the page the click was made in: the log opens
// in a tab of its own, so the browser's Back button does not lead there, and the log
// page draws this value as its one way out (`server.log_body`).  The script reads the
// page from `location`; the server is *given* it (`View.url()`).  Both must produce the
// same href for the same page, which is what the two assertions below compare - not a
// regex, the string.
const HREF = '<a href="/runs/A/log?back=%2Fjobs" target="_blank" rel="noopener"';
const opensLog = (html) => html.includes(HREF);
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
  "                           'what': 'x'}, 'en', '/jobs') + '\\n' + " +
  "                 _acts_cell({'id': 'A', 'state': 'running'}, 'en', '/jobs'))"],
  { cwd: ROOT, encoding: 'utf8' });
const servedLines = served.split('\n');
// The same page, spelled by the script out of `location` and by the server out of
// `View.url()`: one href, or the row re-shapes the moment the poll rewrites it.
out.push(['the server writes the same link for the panel row and the runs row',
          servedLines.length === 2 && servedLines.every(opensLog)]);
out.push(['and the server does not draw a log box any more',
          !/logbox|showLog/.test(served)]);

// --- a fold the reader opened or closed stays that way ----------------------
// The operator's 「更多筛选这里好像也没有持久化」, and the same complaint about every
// other fold: the panel a page folds away, the activity panel.  The server draws each
// fold the way the facts say, which is right for a reader who has never touched it; a
// stored answer is that reader overruling the fact, and this is the whole of what keeps
// it.  Both halves matter and both are asserted here - the attributes the server writes
// (driven below) and the script's read/write of them (driven above, on the three folds
// that were on the page before it ran).
out.push(['a fold the reader closed comes back closed, whatever the facts say',
          foldLive.open === false]);
out.push(['a fold nobody has touched keeps the server\'s own answer',
          foldRecord.open === true]);
const fresh = () => JSON.parse(sandbox.localStorage.getItem('kci-folds') || '{}');
out.push(['the reader\'s answer is stored under the fold\'s own name',
          fresh().live === false]);
// Opening one stores the opening, and stores it *beside* the answers already there:
// `foldSave` rewrites the whole map, so a save that started from an empty object would
// silently drop every other fold's answer - a bug no single-fold assertion can see.
foldLedger.open = true;
foldLedger.dispatchEvent(new sandbox.Event('toggle'));
out.push(['opening a fold stores the opening', fresh()['page.correspondence.ledger_title'] === true]);
out.push(['and does not forget the folds saved before it', fresh().live === false]);
out.push(['a fold nobody has touched is not stored at all',
          !('page.correspondence.record_title' in fresh())]);
// The closed answer is `false` and not "nothing", which is the one shape a truthiness
// test would lose: `kept[name]` reads `false` as no answer and the fold springs back
// open on the next load.
foldRecord.open = false;
foldRecord.dispatchEvent(new sandbox.Event('toggle'));
out.push(['closing a fold stores the closing and not "no answer"',
          fresh()['page.correspondence.record_title'] === false]);
// A reload, in one line: the server draws its own answer again and the script applies
// the stored one over it.  `foldLive` is the case that matters - it is drawn open by
// the facts on every load, so a memory that did not outrank them would never be seen.
foldRecord.open = true;
foldLedger.open = false;
sandbox.buildFolds();
out.push(['a reload puts the stored answer back over the server\'s own',
          foldRecord.open === false && foldLedger.open === true]);
out.push(['including over a fold the server draws open every time',
          foldLive.open === false]);
out.push(['a fold is remembered once, not once per run',
          foldLive.listeners.toggle.length === 1]);

// The other half of the claim, driven server-side: a guard on an attribute nothing
// renders is a guard that does nothing.  `ui.more`, `ui.panel(collapsible=True)` and
// `shell.live` are its only writers.
const folds = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); " +
  "from lib.gui.design import ui; " +
  "from lib.gui.design import shell; " +
  "from types import SimpleNamespace as N; " +
  "v = N(lang='en', rows={'activities': []}, url=lambda: '/jobs'); " +
  "sys.stdout.write('\\n'.join([" +
  "    ui.more('m', 'b', fold='more.jobs'), " +
  "    ui.more('m', 'b'), " +
  "    ui.panel('page.builds.acts_title', 'b', collapsible=True, lang='en'), " +
  "    ui.panel('page.builds.acts_title', 'b', lang='en'), " +
  "    shell.live(v)]))"],
  { cwd: ROOT, encoding: 'utf8' });
const folded = folds.split('\n');
out.push(['the server names a filter bar\'s second row',
          /<details class="more" data-fold="more\.jobs">/.test(folded[0])]);
out.push(['and a bar that names nothing is never remembered',
          !/data-fold/.test(folded[1])]);
out.push(['a collapsible panel is remembered by its own title',
          /<details class="panel" data-fold="page\.builds\.acts_title"/.test(folded[2])]);
out.push(['while a panel that cannot be folded carries no name at all',
          !/data-fold/.test(folded[3])]);
out.push(['and the activity panel is the one fold every page shares',
          /<details class="live" id="live" data-fold="live">/.test(folded[4])]);

// --- the row ticks, kept across the reloads this console is made of ---------
// The operator's 「两个东西勾好了，我去改了其他的东西，它刷新界面两个勾也没有」.  A filter
// bar's `change` is a navigation, and the tick column is drawn by the *server* on the way
// back, which knows nothing about anything ticked; the boxes live outside their form
// (`form="pull-now"`), so nothing in the URL carries them either.  The script keeps them,
// per page, and this drives both halves: what it writes when the reader clicks, and what it
// puts back on a load that never saw that click.
//
// The page is `/jobs` (`location.pathname` below) with one tick-driven bar and a select-all
// header, seeded the way a returning tab has it - `A` ticked, `B` not - so the restore has
// something to disagree with.
const ticks = el('input', { id: 't-A', name: 'selected', type: 'checkbox', form: 'run-now', value: 'A' });
const ticksB = el('input', { id: 't-B', name: 'selected', type: 'checkbox', form: 'run-now', value: 'B' });
const tickAll = el('input', { id: 't-all', name: 'all', type: 'checkbox', 'data-all-for': 'run-now' });
const ticksOther = el('input', { id: 't-other', name: 'selected', type: 'checkbox', form: 'pull-now', value: 'A' });
const storedTicks = () => JSON.parse(sandbox.sessionStorage.getItem('kci.ticks') || '{}');
const seedTicks = (said) => sandbox.sessionStorage.setItem('kci.ticks', JSON.stringify(said));
seedTicks({ '/jobs': { 'run-now': ['A'] }, '/analysis': { 'pair-now': ['X'] } });
sandbox.tickRestore();
out.push(['a ticked row comes back ticked after the reload', ticks.checked === true]);
out.push(['and the row nobody ticked comes back empty', ticksB.checked === false]);
out.push(['and the select-all header says so, rather than unticking them on the next press',
          tickAll.checked === false]);
// A tick names a row of *this* page: the same ids on another page are other rows.  The rule
// `Filter.to_query()` already keeps by leaving `tick` out of every link.
out.push(['a tick made on one page is not a tick on another',
          ticksOther.checked === false]);
// What the reader clicked, read back off the boxes rather than tracked as a diff: a save
// that remembered "changes" rather than "the ticks" would drift the moment a page redrew.
ticksB.checked = true;
sandbox.tickSave();
out.push(['ticking a second row stores both', JSON.stringify(storedTicks()['/jobs']['run-now']) === '["A","B"]']);
// …and saves *beside* the answers already there: `tickSave` rewrites the whole map, so one
// that started from an empty object would silently drop every other page's ticks - the same
// bug the fold memory keeps its `fresh()` map for.
out.push(['a save does not forget the other page\'s ticks',
          storedTicks()['/analysis']['pair-now'][0] === 'X']);
// Unticking everything is an answer and not the absence of one: `[]` is what must be stored,
// or the restore reads "no answer" and the two ticks spring back on the next load - the
// `false`-versus-nothing distinction the fold memory keeps for the same reason.
ticks.checked = false;
ticksB.checked = false;
sandbox.tickSave();
out.push(['unticking both stores "nothing ticked" and not "no answer"',
          Array.isArray(storedTicks()['/jobs']['run-now'])
          && storedTicks()['/jobs']['run-now'].length === 0]);
// …and an empty answer is *applied* rather than skipped: a stored `[]` read as "no answer"
// would leave whatever the page drew, which is the same bug from the other side.
ticks.checked = true;
ticksB.checked = true;
sandbox.tickRestore();
out.push(['so the load after it comes back with nothing ticked',
          ticks.checked === false && ticksB.checked === false]);
// An id the filter has since hidden is forgotten rather than left to reappear: the restore
// is followed by a save, so what is stored is always what this page is drawing.
seedTicks({ '/jobs': { 'run-now': ['A', 'GONE'] } });
ticks.checked = false;
sandbox.tickRestore();
out.push(['a tick whose row the filter has hidden is dropped, not kept for later',
          JSON.stringify(storedTicks()['/jobs']['run-now']) === '["A"]']);
// …and with every box of the bar back, the header agrees again - which is how two ticked
// rows and an empty select-all cannot coexist.
ticksB.checked = true;
sandbox.tickSave();
sandbox.tickRestore();
out.push(['with the whole bar ticked the header follows it', tickAll.checked === true]);

// The other half of the claim, driven server-side: a script that remembers boxes nothing
// draws remembers nothing.  `ui.checkbox(form=…)` is the only writer of the `form=` this
// keys on, and the box a *filter* is asked with must not carry one - a filter's answer rides
// in the URL, and a second owner for it here would be a second answer.
const boxes = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); " +
  "from lib.gui.design import ui; " +
  "sys.stdout.write('\\n'.join([" +
  "    ui.checkbox('selected', '', value='A', form='run-now', lang='en'), " +
  "    ui.checkbox('origin', 'x', lang='en'), " +
  "    ui.checkbox('all', 'x', all_for='run-now', lang='en')]))"],
  { cwd: ROOT, encoding: 'utf8' });
const drawn = boxes.split('\n');
out.push(['the server draws a row tick as a checkbox naming its bar',
          /type="checkbox"/.test(drawn[0]) && /form="run-now"/.test(drawn[0])]);
out.push(['and a filter\'s own box carries no bar name to be remembered under',
          !/form=/.test(drawn[1])]);
out.push(['while the select-all names the bar it is the select-all of, and not itself',
          /data-all-for="run-now"/.test(drawn[2]) && !/ form=/.test(drawn[2])]);

// --- a button's own field: the re-run button, and the one place it can be lost ------
// The operator's 「难道就不能默认增加重跑？」.  `--redo` is one command's other mode, and the
// re-run button is the button beside 跑 with a field of its own (`redo=1`) - **on the
// button**, because a hidden input belongs to the form and the 跑 beside it would send
// that too, which is the difference between 跑 and 重跑 decided by a field neither button
// owns.  A browser adds the pressed button's own name and value to the form's data;
// `new FormData(form)` does not, so a script that kept that spelling would post the plain
// run over this path and the re-run over the no-script path - one press, two commands.
//
// The claim needs the **body the script posts**, so it needs an action form and the two
// pieces of stub machinery added for it above: an element's `matches`, and `document`
// catching a bubbling `submit`.
const actForm = el('form', { method: 'post', action: '/api/actions/run' });
const actBox = el('input', { name: 'selected', type: 'checkbox', value: '6aad:boot' });
const actRun = el('button', { class: 'btn primary sm' });
const actRedo = el('button', { class: 'btn primary sm', formaction: '/api/actions/run',
                               name: 'redo', value: '1' });
actBox.parent = actForm;
actForm.append(actBox);
actForm.append(actRun);
actForm.append(actRedo);
actForm.parent = sandbox.document;   // the delegated `submit` listener is the document's
const press = (button) => {
  const event = new sandbox.Event('submit', { bubbles: true });
  event.submitter = button;
  actForm.dispatchEvent(event);
  return sandbox.posted;
};
const plain = press(actRun);
out.push(['the run button posts the form\'s own fields',
          plain.url === '/api/actions/run' && plain.body.includes('selected=6aad%3Aboot')]);
out.push(['and nothing that belongs to a button nobody pressed',
          !/redo/.test(plain.body)]);
const rerun = press(actRedo);
out.push(['the re-run button posts its own field beside the form\'s',
          /(^|&)redo=1(&|$)/.test(rerun.body)
          && rerun.body.includes('selected=6aad%3Aboot')]);
// The endpoint is the form's own for both, so the field is the whole of the difference
// between them - if the two posted to two endpoints, the flag and the endpoint could
// disagree, and one of them would be the wrong command.
out.push(['and to the same endpoint, so the field is the whole difference',
          rerun.url === plain.url]);

// The other half, driven server-side: the field has to be *drawn* on the button, and
// `ui.action_form`'s `also` is its only writer.  A script that posts a field nothing
// renders posts nothing.
const bars = execFileSync('python3', ['-c',
  "import sys; sys.path.insert(0, '.'); " +
  "from lib.gui.design import ui; " +
  "sys.stdout.write(ui.action_form('run', 'run', fields=[('api', 'local')], " +
  "                               also=(('run', 'redo', 'a title', '', (('redo', '1'),)),), " +
  "                               form_id='run-now', lang='en'))"],
  { cwd: ROOT, encoding: 'utf8' });
out.push(['the server draws the re-run button\'s field on the button',
          /<button[^>]*name="redo" value="1"[^>]*>/.test(bars)]);
// …and on the *button* and not in the form: a hidden input with this name would be sent
// by the 跑 button too, and the two buttons would stop being two commands.
out.push(['and not as a field of the form',
          !/<input type="hidden" name="redo"/.test(bars)]);
out.push(['while the button beside it carries no such field',
          (bars.match(/<button/g) || []).length === 2
          && (bars.match(/name="redo"/g) || []).length === 1]);

(async () => {
  let bad = 0;
  for (const [name, ok] of out) {
    if (!ok) { bad += 1; }
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}`);
  }
  console.log(bad ? `${bad} failed` : `all ${out.length} passed`);
  process.exit(bad ? 1 : 0);
})();
