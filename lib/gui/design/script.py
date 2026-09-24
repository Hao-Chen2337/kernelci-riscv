# SPDX-License-Identifier: LGPL-2.1-or-later
"""The shipped script, and the words it writes: the old layer's one survivor.

`_JS` is the console's interaction: the two-second poll, the finish notice, the POST
take-over, the value rails, the select-all boxes, the multi-valued axis' boxes, and the
row ticks a reload would otherwise forget.  It is
**the script that ships**, byte for byte out of the module that used to serve it, and
it does not belong to a presentation layer: the markup it drives is the same markup
either way - `body[data-drawn]`, `details.live#live`, `#notice` beside it,
`table#runs[data-rows]`, `form[data-auto]`, `input[data-stops]`,
`input[data-all-for]`, `input[data-multi]`, `input[form]` (a row's tick, which
`ui.checkbox(form=…)` is the only writer of), `[data-status]`, and the
`details[data-fold]` folds whose open state is the reader's and not the load's - so
the screens of `lib/gui/design/` are drawn *for* it rather than rebuilt in a script
of their own.

**Nothing in here is retyped.**  `_JS`, `_JS_WORDS` and `_js` were lifted out of
`lib/gui/templates.py` line for line when that module was retired, because the two
node suites read `_js()`'s answer back out of it with a regular expression
(`test_notice.js` parses `var I18N = ...;`) and run the script itself against a DOM
stub (`test_dom.js`).  One character moved is a browser that stops polling and a gate
that still passes; the move was proved by rendering `_js(lang, digest)` for both
languages before and after and comparing the two strings byte for byte.

`_tally_words` came with it and stayed: it exists for one reader, `_js`, which injects
it as `I18N.tally` so the ledger counts the script prints are the words the server
prints.  Its one other caller (the old `/runs` table) went with the layer.

The names `_JS`'s own comments use for the cells it rewrites - `_runs_table`,
`_live_row` - are the old layer's.  Those cells are `design/pages/runs.py::_acts_cell`
and `design/shell.py::live_row` now, and the mapping is stated here rather than edited
into the string: `_JS`'s bytes are what the script under test is, and a comment inside
it is one more byte to diff.

`_js`'s body calls the pill's word by the name the old module gave it (`_end_word`),
which is `ui.end_word` here - the import below is aliased for exactly that reason, so
the spliced function needed no edit at all.
"""

import json

from ... import errors, layout
from ...i18n import DEFAULT_LANG, t
from ..schema import LIVE_KEPT, PILL_WORDS
from .ui import end_word as _end_word

# The two polls: `/api/state` every 2s (the activities *and* the digest of the local
# files a page was drawn from), and the log of the one activity being watched (1s).
#
# The 2s poll does three things and they stop in different places.
#
#  * **The live panel** (`drawLive`) is updated on every page, because it is in the
#    shell: what is running now is the one fact a reader needs wherever they are.
#  * **The trigger** (`location.reload()` on a digest change) runs on every page too,
#    because it is the operator's 触发式: an activity that finished wrote something,
#    so the page re-reads itself rather than waiting for a manual refresh.  It is why
#    a finish the reader was watching can both be announced *and* leave the page up
#    to date - see the `notice`/`carry` pair below, which is what keeps the message
#    from being wiped by the reload the message is about.
#  * **The history table** is rewritten only where there is an activity table *and*
#    that table is showing every activity (`data-rows="all"`, `_table`):
#    `/api/state` answers the unfiltered question, so writing its answer into a
#    filtered `tbody` would replace the reader's rows with rows they did not ask for
#    - `/pull` drew one row and showed fifty two seconds later (`07-shell.md` §A2).
#
# The table re-render writes the same cells with the same classes as `_runs_table`:
# a table that changes shape when it refreshes is a table nobody can read while
# something is running.  `esc()` is what keeps a run's own text from becoming
# markup.  The `change` listener is progressive enhancement - with JavaScript off
# the form's apply button still submits, and the toolbar says so in a `<noscript>`
# note.
#
# The words this script writes (`I18N.log`, `I18N.cancel`, `I18N.sending`, …) are the
# catalogue's, injected as a small object by `_js()`: `_runs_table` and `_live_row`
# read the same ones server-side, so neither the table nor the panel can come back
# in another language than the one it was drawn in.
_JS = """
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
// The 日志 link, the script's three copies of it (`liveRow`, `notice`, the table
// re-render) and the server's three (`ui.log_link`, which draws the panel and the two
// activity tables the poll only *updates*).  Both halves have to agree, or a refresh
// re-shapes a row the reader is looking at.
//
// `back` is this page - where the log's own tab leads when the reader presses "回到列表".
// The log opens in a tab of its own, so the browser's Back button leads to whatever was
// open before the tab and not to the table the click was made in; this is the address
// that fixes it.  `location.pathname + location.search` is the page as it stands, which
// is what `View.url()` answers server-side - the filter, the api key, the window.
function logHref(id) {
  return '/runs/' + encodeURIComponent(id) + '/log?back=' +
    encodeURIComponent(location.pathname + location.search);
}
// A filter bar submits itself when a control *commits*, and a keyboard reader browses
// with the arrow keys first.  On a `<select>` and on a number box every arrow press is a
// `change`, so browsing submitted the form, reloaded the page and put the reader back at
// the top of it - the operator's 「有时候按某些键下面的会突然跳到头顶」.  So one-step keys
// set `browsing` for a moment and the submit waits for a committed gesture (Enter,
// Escape, Tab or a click); a mouse click still submits at once, because that is already
// a decision.
//
// The fourth control shape in a bar is the `<input list="…">` box `_name_field` draws
// (the `api` / `tree` / `branch` fields), and it was the one the whitelist missed:
// **Firefox opens a datalist on the down arrow**, so an arrow key changes the value and
// fires a `change` - the same browse-then-submit as a select, with `browsing` never set.
// `hasAttribute('list')` is the whole test: the box is the browser's own widget
// whatever the list is called.
//
// The **fifth** control shape is the tick-box group a multi-valued axis is asked with
// (`_check_group`: `tree`, `arch`, `defconfig`, `compiler`), and it is the one shape
// whose `change` is not a decision.  The gesture there is "tick these three, then
// apply": submitting on the first tick would reload the page once per box and pay the
// API's read once per reload.  So those boxes carry `data-multi` and the listener
// below leaves them alone; `apply` is beside them, and with the script off it is the
// only way out of the bar either way, which is what every other control here promises.
var browsing = 0;
document.querySelectorAll('form[data-auto]').forEach(function (f) {
  f.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === 'Escape') { browsing = 0; return; }
    var one = (e.key || '').indexOf('Arrow') === 0 ||
              e.key === 'PageUp' || e.key === 'PageDown' ||
              e.key === 'Home' || e.key === 'End';
    if (one && (e.target.tagName === 'SELECT' || e.target.type === 'range' ||
                e.target.type === 'number' || e.target.hasAttribute('list'))) {
      browsing = Date.now();
    }
  });
  f.addEventListener('change', function (e) {
    if (browsing && Date.now() - browsing < 1200) { return; }
    if (e.target.getAttribute && e.target.getAttribute('data-multi')) { return; }
    if (e.target.type !== 'submit' && e.target.type !== 'button') {
      keepPlace(barTarget(f));
      f.submit();
    }
  });
  // Every other way this bar leaves the page is a *native* submission, and it fires a
  // `submit` event that `f.submit()` above does not.  Both paths remember the place,
  // because both land on a page the reader did not ask to start at the top: the Apply
  // button and Enter in a box are the two gestures a filter bar offers, and until this
  // listener only the digest reload stored anything (`restorePlace` returned to the
  // top of every filtered page - the operator's 「跳到头顶」).
  f.addEventListener('submit', function () { keepPlace(barTarget(f)); });
  f.addEventListener('mouseup', function () { browsing = 0; });
  f.addEventListener('blur', function () { browsing = 0; }, true);
});
// Where the reader is in the page, kept for the load about to happen.  Two callers and
// one shape: the digest reload keeps the URL it is reloading, and a filter bar keeps the
// **destination** - the URL the browser is about to put in the address bar, which is
// what `restorePlace` matches on.  Its test is the whole URL on purpose: a position is
// only a position in the row set it was read in, and a path-only match would restore a
// scroll from one filtered table into another.  No storage, no place, no crash.
function keepPlace(url) {
  if (!url) { return; }
  try {
    sessionStorage.setItem('kci.place', JSON.stringify(
      {url: url, top: window.scrollY || 0, at: Date.now()}));
  } catch (err) {}
}
// The URL a filter bar is about to navigate to: a GET form's fields *are* the query,
// in the form's own order, which is what the browser will serialise too.  `URLSearchParams`
// for the same reason the action bars use it (`_form_body` reads what this encoding
// says), and the whole thing is guarded because a place that cannot be computed must
// still let the navigation happen.
function barTarget(f) {
  try {
    var url = new URL(f.getAttribute('action') || '', location.href);
    url.search = new URLSearchParams(new FormData(f)).toString();
    return url.href;
  } catch (err) { return ''; }
}
// An action button is an ordinary `<form method="post" action="/api/actions/<name>">`,
// so a browser's own behaviour would be to navigate to the JSON answer
// (`{started, kind, argv}`) - the reader asked for a build to be
// registered and got a page of JSON.  That answer is the contract and does not
// change; this listener is what keeps the reader where they were.
//
// Delegated on `document` on purpose: `drawLive` replaces the panel's rows every 2
// seconds, and a listener bound per form would be thrown away with them.  Three POST
// shapes are taken over: `/api/actions/**`, whose answer is the JSON contract,
// `/api/runs/<id>/cancel`, whose answer is JSON too - a reader who cancelled an
// activity should stay on the page that shows it ending rather than be navigated to
// `{"cancelled": …}` - and the two that write `var/state/` without starting anything
// (`/api/worker/forget/<id>`, `/api/worker/callback`), whose answer *is* the sentence
// the reader asked for and would otherwise replace the queue they were reading it
// against.  The filter bar's GET (which submits itself from the `change` listener
// above, and must navigate) is not touched.
function barStatus(form, text, bad) {
  var spot = form.querySelector('[data-status]');
  if (!spot) { return; }
  spot.textContent = text;
  spot.className = bad ? 'status bad' : 'status';
}
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!form || !form.matches
      || !form.matches('form[method="post"][action^="/api/actions/"], '
                       + 'form[method="post"][action$="/cancel"], '
                       + 'form[method="post"][action$="/callback"], '
                       + 'form[method="post"][action$="/forget"]')) {
    return;
  }
  e.preventDefault();
  // **The button that was pressed, not the form's first one.**  A form may hold
  // several commands over the same fields and the same ticks (`ui.action_form`'s
  // `also`): the builds bar's *pull the selected* and *index, then pull the selected*
  // post the same body to two different endpoints, and the tick box that feeds both
  // names the form, not a button.  `e.submitter` is that button, and its `formaction`
  // is the endpoint it was drawn for; the form's own `action` is the answer for a
  // submit that came from somewhere else (Enter in a text box), which is why the
  // fallback stays.  Reading `form.querySelector('button')` posted the first button's
  // endpoint for every press, so the third button would have run the first one's
  // command with its own fields - a silent wrong command, not a refusal.
  var button = e.submitter || form.querySelector('button');
  if (button) { button.disabled = true; }
  barStatus(form, I18N.sending, false);
  // `URLSearchParams`, not `new FormData(form)`: this posts what the server reads.
  // `FormData` serialises to `multipart/form-data`, and the reader took the body with
  // `parse_qs`, so no field arrived at all - every action ran on its defaults and the
  // ones needing a ticked row were refused with "needs at least one ticked build"
  // however many were ticked.  The server now reads both encodings (`_form_body`), so
  // a page already open in a browser keeps working; this is the spelling it should
  // have had.  Repeated names survive: `new URLSearchParams(formData)` keeps all 17
  // `selected` values, which is what `_ticks()` reads.
  //
  // **`e.submitter`, because a button's own field is not the form's.**  `new
  // FormData(form)` leaves the pressed button out, so a button carrying `name`/`value`
  // (`ui.action_form`'s `also`) would post that field over the no-script path - where
  // the browser adds the submitter itself - and drop it here: one press, two commands,
  // decided by whether JavaScript ran.  The re-run button is the field that exists, and
  // the difference between it and the button beside it is exactly this value.  The
  // press may have come from nowhere (`Enter` in a text box), so the fallback stays.
  var body = new URLSearchParams(new FormData(form, e.submitter || undefined));
  // The pressed button's own `formaction` wins over the form's `action` (`ui.action_form`
  // draws both spellings): the body is the form's either way, only the endpoint differs.
  var where = (e.submitter && e.submitter.getAttribute('formaction'))
              || form.getAttribute('action');
  fetch(where, { method: 'POST', body: body })
    .then(function (answer) {
      return answer.text().then(function (text) {
        return { ok: answer.ok, status: answer.status, text: text };
      });
    })
    .then(function (answer) {
      if (button) { button.disabled = false; }
      if (!answer.ok) {
        barStatus(form, I18N.rejected.replace('{reason}', answer.text.trim()), true);
        return;
      }
      var started = null;
      try { started = JSON.parse(answer.text); } catch (err) { started = null; }
      // A *forget* answers with the sentence and no activity: it starts nothing, so
      // there is no id to name and `started {id}` would say `started ?` about a
      // button that started nothing.  The server's own `note` is printed instead -
      // it knows whether the node was in `seen`, whether a worker held the file, or
      // whether the file was readable at all, and those are four different things
      // the reader has to be able to tell apart.
      if (started && started.note) {
        barStatus(form, started.note, started.ok === false);
        return;
      }
      var id = (started && started.started) || '?';
      barStatus(form, I18N.started.replace('{id}', id)
        .replace('{argv}', ((started && started.argv) || []).join(' ')), false);
      livePoll();
      // **The panel is what opens the new activity.**  This used to fill the page's
      // log box with `<id>`'s tail; there is no box any more, and the re-point is the
      // `livePoll()` above - the activity that just started is the panel's first row,
      // and its 日志 link is a real link to the whole log in a tab of its own.  Nothing
      // is opened here on the reader's behalf: a script-opened tab is a pop-up, and a
      // start the reader has just confirmed does not need one.
    })
    .catch(function (err) {
      if (button) { button.disabled = false; }
      barStatus(form, I18N.unreachable.replace('{error}', err), true);
    });
});
// Is the reader typing into something on this page?  A reload that throws away a
// half-typed filter is worse than a table that is two seconds stale, so the trigger
// below waits for the next tick instead of firing under their hands.
function typing() {
  var one = document.activeElement;
  return !!one && (one.tagName === 'INPUT' || one.tagName === 'SELECT' ||
                   one.tagName === 'TEXTAREA');
}
// Is the reader busy inside something this poll would rewrite?  `#live` is the panel
// and `#runs` the activity table, and both are replaced wholesale (`drawLive`,
// `drawTable`) - the replacement drops the row under the cursor and can move the page
// under it, which is one more way the viewport jumps while nothing was clicked.
// `typing()` is the other half and is older: a reload that throws away a half-typed
// filter is worse than a page two seconds stale.  The finish notice is outside both
// regions on purpose - it is a card in its own corner, and dismissing it is not a
// reason to freeze the table beside it.
function busyHere() {
  if (typing()) { return true; }
  var one = document.activeElement;
  return !!(one && one.closest && one.closest('#live, #runs'));
}
// --- the live panel and the finish notice ---------------------------------
//
// One poll feeds three readers: the panel (what is running, on every page), the
// notice (what just ended, once each), and the history table (only where that table
// is the whole activity list - `data-rows="all"`).
var liveSeen = {}, liveNoticed = {}, liveTableAll = false;
var baseTitle = document.title;
// `data-drawn` is the moment the server drew this answer, and it is half of the
// notice's rule: a run carrying `ended > pageDrawn` ended *while this page was
// open*, whatever the poll happened to see.  Read defensively, because a page
// without it (an older answer, a test harness with a smaller DOM) must degrade to
// the other half of the rule rather than throw at load.
var pageDrawn = parseFloat((document.body && document.body.getAttribute
  ? document.body.getAttribute('data-drawn') : '') || '0');

// An id is a second-resolution stamp plus the kind, so two activities of one kind
// started in the same second shared it until `Run._free_id` suffixed the collision
// (`07-shell.md` §A3).  The key the memory and the notice are kept under is
// therefore `id@started`: keyed on the id alone, a reused id would swallow a finish
// and mis-attribute the one before it.
function liveKey(r) { return r.id + '@' + (r.started || 0); }

function liveTime(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  var m = Math.floor(sec / 60);
  return m ? (m + 'm' + (sec % 60 < 10 ? '0' : '') + (sec % 60) + 's') : (sec + 's');
}

// What an activity's pill *says*, which is not the same thing as its colour.
// `I18N.end_word` is the server's `_end_word` answered for the three codes
// `lib/errors.py` defines (0 pass / 1 a test failed / 3 infrastructure), built
// server-side and injected - the script holds no copy of those numbers, and the
// class it prints is still `r.state`'s, because that is what the stylesheet colours
// and what the state filter box offers.  A state the map has no code for is printed
// as itself, which is what the panel did before: "the pill says what is on disk".
function endWord(r) {
  if (r.state === 'cancelled') { return r.state; }
  // `+r.exit_code` and not `String`: a code that arrived as a string ("3") and one
  // that arrived as a number (3) are the same code, and only one of them is a key in
  // the map.
  var code = (r.exit_code === null || r.exit_code === undefined) ? ''
             : String(Number(r.exit_code));
  return (I18N.end_word || {})[code] || r.state;
}

// The ledger's counts for the builds a row's argv named, as words: `50 pass / 9 fail`.
// `I18N.tally` is `(verdict value, its word)` in the order the server prints them
// (`_tally_words`), and only the counts that happened are printed - the same rule
// `_tally_word` follows, because these two write one cell.
function tallyWord(t) {
  if (!t) { return ''; }
  var order = I18N.tally || [], parts = [], i, n;
  for (i = 0; i < order.length; i++) {
    n = t[order[i][0]];
    if (n) {
      parts.push((I18N.tally_one || '{n} {word}')
        .replace('{n}', n).replace('{word}', order[i][1]));
    }
  }
  return parts.join(' / ');
}
function tallyChip(r) {
  var said = tallyWord(r.tally);
  return said ? '<span class="tally">' + esc(said) + '</span>' : '';
}

// The same cells, the same classes and the same words as `_live_row`: the panel is
// rewritten every 2 s, and a row that changed shape or language when it refreshed
// would be a second, disagreeing answer to one question.
function liveRow(r) {
  var ended = r.state !== 'running';
  var code = (r.exit_code === null || r.exit_code === undefined) ? null : r.exit_code;
  var exitText = code === null ? esc(I18N.exit_unknown)
                               : esc(I18N.exit.replace('{code}', code));
  var argv = (r.argv || []).join(' ');
  var id = esc(r.id);
  return '<li class="live-row ' + (ended ? 'ended' : 'running') + '"' +
    ' data-id="' + id + '" data-started="' + esc(r.started || 0) + '"' +
    ' data-state="' + esc(r.state) + '">' +
    '<div class="live-line">' + (ended ? '' : '<span class="spin" aria-hidden="true"></span>') +
    '<span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) + '</span>' +
    '<code class="live-id">' + id + '</code>' +
    '<span class="live-time num">' + esc(liveTime(r.seconds)) + '</span></div>' +
    // `_live_row` prints What as `[:80]`, so this does too: the two answers to "what
    // is running" must differ in their values only, never in their shape.
    '<div class="live-what">' + esc(String(r.what || '').slice(0, 80)) + '</div>' +
    '<code class="live-argv" title="' + esc(argv) + '">' + esc(argv) + '</code>' +
    '<div class="live-act">' + (ended ? '<span class="live-exit">' + exitText + '</span>' : '') +
    // The whole log, in a tab of its own: `/runs/<id>/log` answers the file as a page
    // (`lib/gui/server.py`, `log_body`), and nothing takes the click over any more -
    // `target`/`rel` are the pairing that opens a new tab without handing it a handle
    // back into this page.  `ui.log_link` (the server's own copy of this row) writes
    // the same href, because the panel is drawn by the server and only *updated* here.
    '<a href="' + esc(logHref(r.id)) + '"' +
    ' target="_blank" rel="noopener">' + esc(I18N.log) + '</a>' +
    (ended ? '' : '<form method="post" action="/api/runs/' +
      encodeURIComponent(r.id) + '/cancel"><button class="btn">' +
      esc(I18N.cancel) + '</button></form>') +
    '</div></li>';
}

// One finish, said once.  Three different truths and three different words:
//
//   * an exit code the run really reported - `notice_done` / `notice_failed`;
//   * no code at all - `notice_nocode`.  `Run._settle` maps a code it never learned
//     to `failed`, so a notice that repeated the run's state would claim a failure
//     nobody can check (`07-shell.md` §A3).  The pill says what is on disk; the
//     sentence says what was seen;
//   * an id that is simply gone - `notice_gone`.  Deleted by `prune`, not finished.
//
// Nothing is remembered between tabs, and nothing is remembered between *loads*
// except the carry below: a tab the operator opens after coming back was not
// watching, so it must not announce (that is the rule that makes a reload safe).
function notice(r, gone, quiet) {
  var box = document.getElementById('notice');
  if (!box) { return; }
  var code = (r.exit_code === null || r.exit_code === undefined) ? null : r.exit_code;
  // A cancellation is neither a success nor a failure, and it is the one finish the
  // reader caused themselves: `-15` under "failed" would be the page blaming the
  // reader for pressing its own button.
  var cancelled = (r.state === 'cancelled');
  var line = gone ? I18N.notice_gone.replace('{kind}', r.kind).replace('{id}', r.id)
    : cancelled ? I18N.notice_cancelled.replace('{kind}', r.kind)
    : code === null ? I18N.notice_nocode.replace('{kind}', r.kind)
    : (code === 0 ? I18N.notice_done : I18N.notice_failed)
        .replace('{kind}', r.kind).replace('{code}', code);
  var cls = (gone || code === null) ? 'unknown' : (code === 0 ? '' : 'failed');
  if (cancelled) { cls = 'cancelled'; }
  var el = document.createElement('p');
  // The colour is decided by the *exit code*, never by the run's own `state`: a state
  // class would fight this one on the rows where `_settle` guessed "failed" for a
  // code it never saw, and the pill inside prints the code's own word over the state's
  // class (`endWord` - "incomplete (infra)" beside "exit 3", not "failed").
  el.className = ('notice ' + cls).replace(/ +$/, '');
  el.setAttribute('data-key', liveKey(r));
  el.innerHTML = '<span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) + '</span> ' +
    esc(line) + ' <a href="' + esc(logHref(r.id)) + '"' +
    ' target="_blank" rel="noopener">' +
    esc(I18N.log) + '</a><button class="btn" type="button" data-dismiss="1">' +
    esc(I18N.dismiss) + '</button>';
  box.appendChild(el);
  // At most five on screen: a burst of finishes must not turn the corner into a wall
  // that hides the page it is reporting on.
  while (box.children.length > 5) { box.removeChild(box.firstChild); }
  // `quiet` is the carried card drawn on the page that lands after the reload: the
  // title and the desktop notification already happened, on the page that saw the
  // finish, and firing them a second time would be the same finish announced twice.
  if (!quiet) {
    document.title = '\u2713 ' + line + ' \u2014 ' + baseTitle;
    // The third channel, and the only one that works with the window unfocused.  Used
    // only when the reader has already granted it (`data-notify` asks); nothing here
    // ever prompts, and a page without permission is the page it was.
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      try { new Notification('kernelci-riscv: ' + line); } catch (err) { /* silence */ }
    }
  }
}

// **The notice has to survive the reload it is about.**  A finish changes the local
// digest, and the trigger in `livePoll` reloads the page on that change - so a message
// shown and then reloaded away would be a message nobody ever reads.  What is carried
// across *that* reload is therefore the **fact** (the activity, and whether it
// vanished), not a rendered string: the page that lands rebuilds the card with the
// same markup, so the carried notice has its log link and its dismiss button like any
// other, and it is written only by a page that just detected a finish, read and
// deleted by the page that lands, and ignored when older than 30 s.
//
// This is not the "already announced" set `07-shell.md` §B3 rejects: that would
// *suppress* a notice, while this only *retains* one, in the one tab that saw it, for
// the one reload the poll itself caused.  A tab the operator opens later carries
// nothing, so a finish from before the load is still never announced - and a manual
// reload after that reads nothing, because the entry was deleted when it was read.
var CARRY = 'kci-notice';
function carried() {
  var kept = [];
  try {
    var raw = window.sessionStorage.getItem(CARRY);
    window.sessionStorage.removeItem(CARRY);   // read once: a reload of a reload
    var seen = JSON.parse(raw || '[]');        // must not repeat it either
    for (var i = 0; i < seen.length; i++) {
      if (Date.now() - (seen[i].at || 0) < 30000) { kept.push(seen[i]); }
    }
  } catch (err) { kept = []; }                 // no storage: no carry, no crash
  return kept;
}
function carry(said) {
  try {
    window.sessionStorage.setItem(CARRY, JSON.stringify(said.map(function (one) {
      var r = one[0];
      return { at: Date.now(), gone: !!one[1],
               r: { id: r.id, kind: r.kind, state: r.state, exit_code: r.exit_code } };
    })));
  } catch (err) { /* a page that cannot store still shows the notice */ }
}
function drawCarried() {
  var kept = carried(), i;
  if (!document.getElementById('notice')) { return; }
  for (i = 0; i < kept.length; i++) { notice(kept[i].r, kept[i].gone, true); }
}

// The panel, rewritten in place.  The server drew it, so everything the script does
// here is an update: the rows, the tab's word and count, the header's ring and chip.
// No live region anywhere near it - it is rewritten every 2 s, and a screen reader
// pointed at it would never stop talking (`#notice` is the live region).
function drawLive(live, ended) {
  var panel = document.getElementById('live');
  if (!panel) { return; }
  var list = panel.querySelector('.live-list');
  if (list) {
    list.innerHTML = live.map(liveRow).join('') +
      ended.slice(0, LIVE_KEPT).map(liveRow).join('');
  }
  var word = live.length ? I18N.tab_running.replace('{n}', live.length) : I18N.tab_idle;
  document.querySelectorAll('.live-word').forEach(function (one) {
    one.textContent = word;
  });
  var count = panel.querySelector('.live-count');
  if (count) { count.textContent = live.length; }
  var headword = panel.querySelector('.live-headword');
  if (headword) {
    headword.textContent = live.length ? I18N.head_running : I18N.head_recent;
  }
  // The ring is the same fact as the number, so it follows the number: no live row,
  // no ring.  The panel's tab and the header's chip carry the same two elements, so
  // one rule keeps both in step.
  document.querySelectorAll('.live .spin, .live-chip .spin').forEach(function (one) {
    one.hidden = !live.length;
  });
  var empty = panel.querySelector('.live-empty');
  if (empty) { empty.hidden = !!(live.length + ended.length); }
}

// The count in the window title, which is the only channel that reaches a reader
// whose attention is elsewhere.  Restored on focus, so it cannot become permanent
// clutter that hides the page's own name.
function drawTitle(n) {
  document.title = (n ? '\u25cc ' + I18N.tab_running.replace('{n}', n) + ' \u2014 '
                      : '') + baseTitle;
}

function livePoll() {
  // One request, three answers: the activities, the local digest, and (through the
  // two fields `run_rows` now carries) when each of them started and ended.
  fetch('/api/state').then(function (r) { return r.json(); }).then(function (answer) {
    var runs = answer.runs || [];
    var now = {}, live = [], ended = [], i, r, was, key, key2, said = [];
    for (i = 0; i < runs.length; i++) {
      r = runs[i];
      key = liveKey(r);
      now[key] = r;
      if (r.state === 'running') {
        live.push(r);
        liveSeen[key] = r;
        continue;
      }
      ended.push(r);
      if (liveNoticed[key]) { continue; }
      was = liveSeen[key];
      // Two independent truths, and the notice needs one of them:
      //
      //   1. this page SAW it running and now it is not - a transition inside this
      //      page's own lifetime, which needs no new field on the server at all;
      //   2. the run says it ended *after this page was drawn* - `ended` is the run
      //      writing a fact about itself, and `pageDrawn` is the server writing one
      //      about the page, so it cannot be true of anything that ended earlier.
      //      This is the half that survives a throttled hidden tab, where the poll
      //      may run once a minute and truth 1 can miss a short activity entirely.
      if ((was && was.state === 'running') || (r.ended && r.ended > pageDrawn)) {
        said.push([r, false]);
        notice(r, false);
        liveNoticed[key] = 1;
      }
    }
    // An id that was running and is simply gone was deleted (`prune`), not finished:
    // it is announced as "no longer on disk" and never as done or failed.
    for (key2 in liveSeen) {
      if (!now[key2] && !liveNoticed[key2]) {
        said.push([liveSeen[key2], true]);
        notice(liveSeen[key2], true);
        liveNoticed[key2] = 1;
      }
    }
    liveSeen = {};
    for (i = 0; i < live.length; i++) { liveSeen[liveKey(live[i])] = live[i]; }
    // **Not under the reader's hands.**  `busyHere()` is the guard the digest reload
    // already had (`typing()`), extended to the two regions this poll rewrites: the
    // panel and the activity table are replaced wholesale, which moves whatever the
    // reader was reading the moment their cursor is in them - and a `cancel` button
    // under the cursor is a control they are about to press.  The cost is stated the
    // way it really is: `drawLive`/`drawTable` are skipped on **every** tick the cursor
    // stays inside those regions, not for one tick - and each tick is what makes the
    // numbers in them advance (`live-time`'s "2m" is `Run.seconds()` re-read on every
    // `/api/state` answer and written into the row here), so a reader who parks the
    // cursor on the panel reads a frozen elapsed time and frozen tally chips until they
    // move it away.  That is the trade, and it is the right way round: a control that
    // moves under the cursor is worse than a number a minute behind.  Nothing is lost
    // when something *does* write: the reload below is guarded by `typing()` alone, so
    // a write still changes the digest, still reloads the page, and the numbers come
    // back counted.
    if (!busyHere()) { drawLive(live, ended); }
    drawTitle(live.length);
    // The trigger: something wrote while this page was open - an activity that
    // settled its run.json, a record under var/results, a pull's provenance - so the
    // page re-reads itself with the question it was asked, which is the operator's
    // 触发式.  A half-typed filter waits for the next tick (`typing()`): throwing away
    // what the reader is writing is worse than a page two seconds stale.
    if (answer.digest && DIGEST && answer.digest !== DIGEST && !typing()) {
      carry(said);
      // **A reload is not a new visit.**  The trigger fires because *something wrote*,
      // and the reader was usually reading a row halfway down the page: reloading from
      // the top loses their place, which is the same complaint as a keystroke jumping
      // the viewport.  The position rides in `sessionStorage` beside the finish notice
      // (`carry`), with the same shelf life and the same "no storage, no crash" rule.
      keepPlace(location.href);
      location.reload();
      return;
    }
    if (liveTableAll && !busyHere()) { drawTable(runs); }
  }).catch(function () {});
}

// The history table, and only where it is the whole activity list (`data-rows="all"`,
// which `_table` emits exactly while the rows on screen are every activity).  A page
// whose table was drawn from a filter keeps its own rows: `/api/state` answers the
// unfiltered question, and writing that into a folded `tbody` would put the 37
// `table` rows back two seconds after the page said they were folded - the
// "silently undone filter" the operator met as "为什么拉取或者这里就 run 也会显示".
function drawTable(runs) {
  var body = document.querySelector('#runs tbody');
  var table = document.querySelector('#runs[data-rows="all"]');
  if (!body || !table) { return; }
  // The group captions are part of the table, so the refresh draws them too: the
  // order came from the server in `data-kinds` when it drew the rows, and a
  // re-render that dropped them would be a different table two seconds later.
  var order = (table.getAttribute('data-kinds') || '').split(',').filter(Boolean);
  var kinds = [], i;
  for (i = 0; i < runs.length; i++) {
    if (kinds.indexOf(runs[i].kind) < 0) { kinds.push(runs[i].kind); }
  }
  kinds.sort(function (a, b) {
    var ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib);
  });
  var html = '';
  for (i = 0; i < kinds.length; i++) {
    var group = runs.filter(function (r) { return r.kind === kinds[i]; });
    if (order.length) {
      html += '<tr class="kind-group"><td class="group">' +
        esc(group.length ? kinds[i] + ' (' + group.length + ')' : kinds[i]) + '</td></tr>';
    }
    html += group.map(function (r, at) {
      var code = (r.exit_code === null ? '-' : r.exit_code);
      var argv = (r.argv || []).join(' ');
      var exitCell = (r.kind === 'drift'
        ? '<span title="' + esc(I18N.drift_hint) + '">' + esc(code) + '</span>' : esc(code));
      // The caption sits in the first cell of its group's first row, exactly as
      // `_runs_table` draws it - not a row of its own, so the number of `<tr>`s on
      // this page keeps meaning "activities" (S6 counts them).
      var caption = (order.length && at === 0
        ? '<span class="kind-group">' + esc(r.kind + ' (' + group.length + ')') + '</span>'
        : '');
      return '<tr><td class="id' + (caption ? ' group-first' : '') + '">' + caption +
        '<code title="' + esc(I18N.dir_title.replace('{dir}', I18N.runs + r.id)) + '">' +
        esc(r.id) + '</code></td><td>' + esc(r.kind) +
        '</td><td><span class="' + esc(r.state) + ' pill">' + esc(endWord(r)) +
        '</span>' + tallyChip(r) + '</td>' +
        '<td class="num">' + esc(r.age) + '</td><td class="num">' + exitCell + '</td>' +
        '<td class="wrap">' + esc(r.what) + '</td>' +
        '<td class="wrap"><code title="' + esc(argv) + '">' + esc(argv.slice(0, 60)) +
        '</code></td><td class="act"><span class="cell-actions">' +
        // The same link `_runs_table` writes: the whole log, served as a page of its
        // own (`lib/gui/server.py`), opened in a new tab with this page as its `back`.
        '<a href="' + esc(logHref(r.id)) + '" target="_blank" rel="noopener">' +
        esc(I18N.log) + '</a>' +
        '<form method="post" action="/api/runs/' + esc(r.id) + '/cancel">' +
        '<button class="btn">' + esc(I18N.cancel) + '</button></form></span></td></tr>';
    }).join('');
  }
  body.innerHTML = html;
}

// Dismiss a notice, and ask for the desktop permission only when the reader presses
// the button that offers it - `Notification.requestPermission()` on load is an
// unprompted permission prompt, which every browser discourages and Safari refuses
// without a user gesture.
document.addEventListener('click', function (e) {
  var one = e.target;
  if (!one || !one.closest) { return; }
  var card = one.closest('[data-dismiss]');
  if (card) {
    var box = card.closest('.notice');
    if (box && box.parentNode) { box.parentNode.removeChild(box); }
    return;
  }
  var ask = one.closest('[data-notify]');
  if (!ask || typeof Notification === 'undefined') { return; }
  if (Notification.permission === 'granted') {
    ask.textContent = I18N.notify_on;
    return;
  }
  Notification.requestPermission().then(function (state) {
    ask.textContent = (state === 'granted') ? I18N.notify_on : I18N.notify_off;
  });
});
document.addEventListener('visibilitychange', function () {
  if (!document.hidden) { drawTitle(Object.keys(liveSeen).length); }
});
window.addEventListener('focus', function () {
  drawTitle(Object.keys(liveSeen).length);
});
liveTableAll = !!document.querySelector('#runs[data-rows="all"]');
// The desktop-notice button is server-rendered `hidden` and unhidden here only where
// the browser really has the API: `window.Notification` is absent outside a secure
// context (a LAN address, unlike 127.0.0.1), and a button that does nothing is a
// worse lie than no button.
(function () {
  var ask = document.querySelector('[data-notify]');
  if (!ask || typeof Notification === 'undefined') { return; }
  ask.hidden = false;
  ask.textContent = (Notification.permission === 'granted') ? I18N.notify_on
                                                           : I18N.notify_off;
})();
drawCarried();
// A rail is a duplicate *view* of a box that is already a real control: the box
// carries `name`, the rail does not, so the rail can never submit a value of its own
// and a page with this script off is exactly the page it was before the rail existed.
//
// `data-stops` is the suggestion set in the order the server offered it, and the
// rail's min/max are *indices* into it: what the reader slides through is the
// suggestions, and what the form sends is always the value in the box.  Typing a
// value the set does not name is the point ("滑条式可以给你选…但你可以自己填"): the
// readout prints it, the rail stays where it was, and the field is never refused.
var RAIL_MAX = 24;      // more stops than this and the dropdown beats the rail
function railStops(box) {
  try { return JSON.parse(box.getAttribute('data-stops') || '[]'); }
  catch (err) { return []; }
}
function railFor(box, stops) {
  var rail = document.createElement('input');
  rail.type = 'range';
  rail.className = 'rail';
  rail.min = 0;
  rail.max = Math.max(0, stops.length - 1);
  rail.step = 1;
  rail.tabIndex = -1;
  rail.setAttribute('aria-hidden', 'true');   // the box is the control, not this
  var read = document.createElement('output');
  read.className = 'railout';
  read.setAttribute('for', box.id);
  function show() {
    var at = stops.indexOf(box.value);
    if (at >= 0) { rail.value = at; }
    read.textContent = (box.value === '' ? '\\u2014' : box.value);
    read.dataset.off = (at < 0 ? '1' : '0');  // typed, and not one of the hints
  }
  rail.addEventListener('input', function () {         // sliding: read, do not send
    box.value = stops[Number(rail.value)];
    show();
  });
  // No synthetic `change` here, and that is a correction to the plan's `_rail`
  // (`02-filters.md` §B3): a native `change` on a range input **bubbles**, so the
  // bar's own listener (`form[data-auto]`) already picks the release up and submits
  // the box's value once.  Re-dispatching a change on the box as well made it submit
  // twice - the Node fake-DOM test in this round counts exactly two `form.submit()`
  // calls with that line and one without (`nodes()`-style counting in
  // `docs/gui-rework/09-step34-verification.md`).  Two submits of one form is two
  // page loads on an API where a load costs seconds.
  box.addEventListener('input', show);                 // typing moves the readout
  box.addEventListener('change', show);
  box.insertAdjacentElement('afterend', rail);
  rail.insertAdjacentElement('afterend', read);
  box.classList.add('has-rail');
  show();
}
// The other half of the reload: put the reader back where they were, once, if the
// stored place is this URL and it is fresh.  `scrollTo` is called nowhere else in this
// script on purpose - a page that moves the viewport on its own is the bug, and the one
// place it is wanted is undoing a reload the page itself asked for.
function restorePlace() {
  var raw = null;
  try { raw = sessionStorage.getItem('kci.place'); sessionStorage.removeItem('kci.place'); }
  catch (err) { return; }
  if (!raw) { return; }
  var place = null;
  try { place = JSON.parse(raw); } catch (err) { return; }
  if (!place || place.url !== location.href || Date.now() - place.at > 30000) { return; }
  if (place.top) { window.scrollTo(0, place.top); }
}
restorePlace();
window.addEventListener('load', restorePlace);

function buildRails(root) {
  (root || document).querySelectorAll('input[data-stops]:not(.has-rail)')
    .forEach(function (box) {
      var stops = railStops(box);
      if (stops.length < 2 || stops.length > RAIL_MAX) { return; }
      railFor(box, stops);
    });
}
buildRails();
window.addEventListener('load', function () { buildRails(); });
setInterval(livePoll, 2000);
window.addEventListener('load', function () { livePoll(); });

// One box that ticks every box a form will post.  The operator asked for it in so
// many words (「无论是跑测试还是 pull 等等能不能加一个全选功能」), and the whole of it is
// this listener: the boxes live outside their form (`form="pull-now"`, `form="run-now"`,
// which is how a row a page did not draw can still feed the bar it belongs to), so the
// header box names the form it is the select-all *of*, and nothing here submits
// anything - the bar's own button still posts the ticks, which is what keeps every
// command coming from `Gui.command()`.  The control itself is rendered `hidden` and
// unhidden here, the same progressive-enhancement rule the notify button follows.
function buildSelectAll(root) {
  (root || document).querySelectorAll('input[data-all-for]').forEach(function (all) {
    if (all.dataset.allReady) { return; }
    all.dataset.allReady = '1';
    all.hidden = false;
    var label = all.closest('label');
    if (label) { label.hidden = false; }
    all.addEventListener('change', function () {
      var want = all.checked;
      document.querySelectorAll('input[name="selected"][form="' +
        all.getAttribute('data-all-for') + '"]').forEach(function (box) {
        box.checked = want;
      });
    });
  });
}
buildSelectAll();
window.addEventListener('load', function () { buildSelectAll(); });
window.addEventListener('DOMContentLoaded', function () { buildSelectAll(); });

// The row ticks, kept across a reload.  The operator's 「两个东西勾好了，我去改了其他的
// 东西，它刷新界面两个勾也没有」: a filter bar's `change` is a *navigation*, and a box that
// lives outside its form (`form="pull-now"`, `form="run-now"` - how a row a page did not
// draw still feeds the bar it belongs to) is drawn by the **server** on the way back, which
// knows nothing about anything ticked.  So the tick column came back empty on every load,
// whether the reader had changed a filter or merely pressed apply.
//
// The population is exactly the boxes `ui.checkbox(form=…)` writes and nothing else: only
// that helper puts a `form=` on an input, and a tick that names its bar is the whole shape.
// The type is checked too because a *filter*'s boxes are a different thing - they ride in
// the URL (`data-multi`, `Filter`) and remembering them here would be a second owner for
// the same answer - and so is the select-all header box, which is a gesture and not a value.
//
// `sessionStorage`, the store the scroll place uses, and not the `localStorage` the folds
// use: "which rows am I about to act on" is a selection *in this sitting*, and a **pull**
// ticked on Monday and still ticked on Tuesday would be a command waiting to be pressed.
// It is scoped by pathname, because a tick names a row of *this* page - the next page's ids
// are different ids, which is the rule `Filter.to_query()` already keeps by leaving `tick`
// out of every link.  One list per form, so a page with two tick-driven bars keeps them
// apart.
//
// The restore is followed by a save, so an id the filter has since hidden is forgotten
// rather than left to come back: what is stored is always what this page is drawing.  A
// reader with the script off keeps today's behaviour, and no button's body changes - the
// bar still posts the boxes that are on the page (`_form_body` reads exactly those).
var TICKS = 'kci.ticks';
function tickStore() {
  try { return JSON.parse(sessionStorage.getItem(TICKS) || '{}') || {}; }
  catch (err) { return {}; }
}
function tickBoxes() {
  return Array.prototype.slice.call(document.querySelectorAll('input[form]'))
    .filter(function (one) { return one.type === 'checkbox'; });
}
function tickSave() {
  var said = {};
  tickBoxes().forEach(function (one) {
    var bar = one.getAttribute('form');
    if (!said[bar]) { said[bar] = []; }
    if (one.checked) { said[bar].push(one.value); }
  });
  var all = tickStore();
  all[location.pathname] = said;
  try { sessionStorage.setItem(TICKS, JSON.stringify(all)); } catch (err) {}
}
function tickRestore() {
  var said = tickStore()[location.pathname];
  if (!said) { return; }
  tickBoxes().forEach(function (one) {
    one.checked = (said[one.getAttribute('form')] || []).indexOf(one.value) >= 0;
  });
  // The header box ticks every box of its form, so it has to agree with what just came
  // back: two ticked rows under an empty select-all would untick them on the next press.
  document.querySelectorAll('input[data-all-for]').forEach(function (all) {
    var bar = all.getAttribute('data-all-for');
    var boxes = tickBoxes().filter(function (one) {
      return one.getAttribute('form') === bar;
    });
    all.checked = boxes.length > 0 && boxes.every(function (one) { return one.checked; });
  });
  tickSave();   // forget an id this page no longer draws
}
// Delegated, not per box: the tick column is redrawn whenever the page is, and a listener
// bound to one element would be a listener the next load does not have.
document.addEventListener('change', function (e) {
  if (e.target && e.target.type === 'checkbox' && e.target.getAttribute('form')) {
    tickSave();
  }
});
tickRestore();
window.addEventListener('load', tickRestore);

// How the page is laid out is the reader's and not the load's.  Every fold the server
// draws with a name - 更多筛选 (a filter bar's second row), the panels a page folds away
// (`ui.panel(collapsible=True)`) and the activity panel (`shell.live`) - carries
// `data-fold`, and this is the one place the reader's answer to it is kept.
//
// An absent entry means "no answer given", and that is not the same as "closed": the
// server draws each fold the way the *facts* say (the activity panel is out while
// something runs, a panel the page is about is out), and that stays the answer for a
// reader who has never touched it.  A stored entry is the reader overruling the fact,
// and it wins on every load after it, on whichever page draws the fold.
//
// `localStorage` and not the `sessionStorage` the scroll place uses: a place is where
// the reader was a moment ago and means nothing in the next tab, while a fold is how
// they want the page laid out - the same kind of choice as the theme, which the bridge
// keeps the same way.  It is the one choice here meant to outlive the tab: a panel
// folded away on Monday is still folded away on Tuesday.
//
// `toggle` is the only event a `<details>` fires, and it fires for a click on the
// summary and for Enter or Space on it alike - which is why the listener is on that and
// not on `click`.  Restoring above sets `open` and so fires a `toggle` of its own, but
// a change to the value it already has fires nothing, and where it does fire it stores
// the value just read: the two cannot disagree.  A fold with nothing stored is never
// written, so a reader who has touched nothing keeps the server's own answer, and
// `dataset.foldReady` is `buildSelectAll`'s guard for the same reason - this runs again
// on `load`, and a second listener would store the same answer twice.
var FOLDS = 'kci-folds';
// No storage, no memory, no crash: a browser that refuses `localStorage` keeps the
// server's answer for every fold, which is exactly what a first visit gets anyway.
function foldMap() {
  try { return JSON.parse(localStorage.getItem(FOLDS) || '{}') || {}; }
  catch (err) { return {}; }
}
function foldSave(name, open) {
  var all = foldMap();
  all[name] = !!open;
  try { localStorage.setItem(FOLDS, JSON.stringify(all)); } catch (err) {}
}
function buildFolds(root) {
  var kept = foldMap();
  (root || document).querySelectorAll('details[data-fold]').forEach(function (fold) {
    var name = fold.getAttribute('data-fold');
    // `hasOwnProperty` and not a truthiness test: the closed answer is stored as
    // `false`, which `kept[name]` would read as "nothing stored" and let the fold
    // spring back open on the next load - the bug this line exists to not have.
    if (Object.prototype.hasOwnProperty.call(kept, name)) {
      fold.open = !!kept[name];
    }
    if (fold.dataset.foldReady) { return; }
    fold.dataset.foldReady = '1';
    fold.addEventListener('toggle', function () { foldSave(name, fold.open); });
  });
}
buildFolds();
window.addEventListener('load', function () { buildFolds(); });
"""


# The catalogue key of every word this script writes -> the name it reads it by.
# Two spellings on purpose: the catalogue's keys are dotted and shared with the page
# (`js.cancel` is looked up server-side by the runs row too), while the script wants
# `I18N.cancel` in the middle of a line of JavaScript.  A missing entry here is a
# word the script reads as `undefined`, so the list is one object and not two.
_JS_WORDS = {"link.log": "log", "js.cancel": "cancel",
             "runs.dir_title": "dir_title",
             "analysis.drift_hint": "drift_hint",
             "action.sending": "sending", "action.started": "started",
             "action.rejected": "rejected", "action.unreachable": "unreachable",
             # The live panel and the finish notice.  `tab_*`, `head_*` and `exit*`
             # are read server-side too (`_live_panel`, `_live_chip`), so the panel the
             # poll rewrites cannot come back in another language than the one it was
             # drawn in - the same rule the table's three words follow.
             "live.tab_running": "tab_running", "live.tab_idle": "tab_idle",
             "live.head_running": "head_running", "live.head_recent": "head_recent",
             "live.exit": "exit", "live.exit_unknown": "exit_unknown",
             "live.notify_on": "notify_on", "live.notify_off": "notify_off",
             "notice.done": "notice_done", "notice.failed": "notice_failed",
             "notice.nocode": "notice_nocode", "notice.gone": "notice_gone",
             "notice.cancelled": "notice_cancelled",
             "notice.dismiss": "dismiss"}


# The verdicts a tally prints, in the order it prints them: the value a record carries
# and the catalogue key of its word.  Taken from `PILL_WORDS["verdict"]` rather than
# spelled again, so a verdict the code grows is a verdict this line counts.
_TALLY_WORDS = tuple((one, f"verdict.label.{one}") for one in PILL_WORDS["verdict"])


def _tally_words(lang: str = DEFAULT_LANG) -> list[tuple[str, str]]:
    """`(verdict value, its word)` in the order a tally prints them.

    The script's copy of the tally reads this list (`_js` injects it as `I18N.tally`),
    so the two writers of one cell cannot disagree about the order or the word.
    """
    return [(one, t(lang, key)) for one, key in _TALLY_WORDS]


def _js(lang: str = DEFAULT_LANG, digest: str = "") -> str:
    """The poll script, with the words it writes in front of it as `I18N`.

    A JSON object rather than string literals, because the words have to be escaped
    for the element they sit in: `ensure_ascii=False` keeps the Chinese readable in a
    page that is UTF-8 anyway, and every `</` is broken up so that no run's own text
    (or a translation) can ever close the `<script>` it lives in.

    Most of them are also read server-side (`runs.py`'s `_acts_cell` for the log link
    and the cancel button, `shell.py`'s `live_row` for the panel's cells), so neither the
    panel can come back in another language when the poll rewrites it.  The rest are
    this script's own: the action bar's status line
    (`action.sending` / `action.started` / `action.rejected` / `action.unreachable`)
    and the finish notice (`notice.*`).  Everything goes through `textContent` or an
    `esc()`-ed interpolation, so unlike a page's HTML none of it carries markup - the
    ellipses and colons here are the characters themselves, and that is also what
    makes a translation unable to inject any.

    `digest` is the local state this page was drawn from (`_state_digest`), and it
    travels in the script because that is the only place the poll can compare it:
    `livePoll` re-reads the page when the server reports a different one.
    """
    words = {short: t(lang, key) for key, short in _JS_WORDS.items()}
    # `runs` is the activity directory itself, not a catalogue string: the refreshed
    # row prints the same `title=` on its id cell that `runs.py`'s `_id_cell` prints
    # (`runs.dir_title` is `{dir}/run.json + run.log`), and a path is not a word to
    # translate.  Without it a refreshed row would lose a tooltip the drawn row has,
    # which is the "the table changes shape when it refreshes" rule this file keeps.
    words["runs"] = layout.runs("")
    # Three entries that are not single words either, for the same reason `runs` is not
    # a catalogue string: they are what the script needs to write the state cell the
    # server drew (`_end_cell`), and a second copy of it in JavaScript would be the
    # drift the whole of `_JS_WORDS` exists to prevent.
    #
    #   * `end_word` - `_end_word`'s answer for the three exit codes `lib/errors.py`
    #     defines, keyed by the code as a string (a JSON object's keys are strings).
    #     The numbers themselves do not travel: the map is built where the constants
    #     live, so a `3` in this script is impossible.
    #   * `tally` / `tally_one` - the verdict vocabulary in print order and the format
    #     of one count (`_tally_words`, `run_end.tally_one`).
    words["end_word"] = {str(code): _end_word(state, code, lang)
                         for code, state in ((errors.EXIT_PASS, "done"),
                                             (errors.EXIT_TEST_FAIL, "failed"),
                                             (errors.EXIT_INFRA, "failed"))}
    words["tally"] = _tally_words(lang)
    words["tally_one"] = t(lang, "run_end.tally_one")
    blob = json.dumps(words, ensure_ascii=False).replace("</", "<\\/")
    # `LIVE_KEPT` rides with the words: the cap the panel was rendered with and the
    # slice `livePoll` writes back are the same number, and two spellings of it would
    # drift the day one of them changed.
    return (f"var I18N = {blob};\n"
            f"var LIVE_KEPT = {LIVE_KEPT};\n"
            f"var DIGEST = {json.dumps(digest)};\n" + _JS)
