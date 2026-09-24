# SPDX-License-Identifier: LGPL-2.1-or-later
"""The worker screen (`/worker`): what the poll loop is doing, what it claimed, what came back.

Five panels, and each one answers a question the others cannot:

* the **status line and the start bar** say what the poll loop *is* - its state, its
  pid, when it started, how long it has been up - and print the command the button
  will really run.  That line is `Gui.command`'s own argv (`Gui._argv_of`), built from
  the same values the form posts, so the printed line and the process behind it cannot
  drift; and the sentence under it says where the results will land, because a button
  whose effect the reader has to guess at is a button that gets pressed twice.
* the **queue** is the API's job nodes with `claimed` answered against that same `seen`
  list: `Gui.job_node_rows` is the reader, and it is what makes the column mean
  something.  A pair the loop never saw and a pair it claimed and finished are one
  word apart in the API's own answer, and that word is the whole question here.
  *where in the pipeline each node is* is the `route` column, and the bar's `text` box
  is the search over node name, id, state and result - the page's way of finding one
  node among fifty without reading fifty rows.
* the **claimable pairs** count the available queue by (platform, runtime), biggest
  first, and each count is a link that points the page - and therefore the button below
  it - at that pair.  A pair whose platform a worker started from this page could not
  boot is drawn with its reason and **not as a link** (`_platform_refusal`, the same
  reader `pull_worker.py`'s own argv goes through): a link that opens a run which can
  only end in an infrastructure failure is worse than no link.
* the **ledger's `source == "worker"` rows** are the panel that answers "did it do
  anything" without reading a cursor at all.  It costs no new storage - the records are
  already in `var/results/` - and it is the one panel the old page did not have, which
  is why the answer to that question used to be a timestamp that moves either way.

**What this page deliberately does not copy from the board.**  The board links a
node id to `?job=<node id>`, and the engine's `job` filter matches a job's *name*
(`activities.job_node_rows`), so the link answers with an empty table; the id is drawn
as data here.  The board's `definition` column is a `json` button pointing at the
worker page itself, and a button that returns the page it is on is not a view of
anything; the cell says whether the node carries a definition.  The board's ledger
panel links `log` to `/runs#<build id>`, but a ledger row names no run - `data.py`'s
`ledger` rows are `build_id/test/verdict/exit/source/when/detail`, and the id in the
link is a build id, so the link would open the runs page at a row that does not exist
(the fake log viewer `00-BRIEF.md` §9 refuses).  The column is dropped and the record's
own `detail` - the text the run wrote - carries what came back.

**Page state is not a filter condition.**  `mode`, `platform`, `runtime` and `since` are
the worker's own arguments: they select no row of the queue, they decide which queue the
*command* claims from, and the old page keeps them as page keys for exactly that reason
(a box the command line cannot show is a box that can disagree with the command line).
They are read off this request's check, carried by every link this page writes
(`keep=`), and hidden in both forms - so an `apply`, a rail and the start button all
answer about the same worker.

**One sentence the board's own second revision deleted and this console keeps**: the one
under the start button saying where the results will land (`worker.where_results`), kept
because the operator asked for it by name - a start button whose effect the reader has to
guess at is the button `00-BRIEF.md` §5 refuses.

**The state-file panel is gone** (「它自己的状态文件其实我觉得可以不显示」).  It printed
the poller's own document - the path, the cursor, `seen`/`pending` as counts - and every
number on it needed a footnote to be honest: `cursor` moves on every poll with any event
in the window, so a healthy idle loop and a stuck one looked the same on it, and `refused`
is absent from any state file written before the field existed.  The panel that answers
"did it do anything" without a footnote is the ledger's `source == "worker"` rows below,
which cost no new storage and need no such explanation.  The state file is still there,
and still the worker's own; it is just no longer this page's business to narrate it.
"""

import time
import urllib.parse

from .... import sink
from ....tests import DEFAULT_DEVICE, DEFAULT_LAB
from ...forms import _iso_stamp
from ...schema import (
    FILTER_ORDER,
    JOB_STATES,
    LIMITS,
    LOCAL_FATES,
    MAX_LIMIT,
    MODES,
    ROUTE_KEYS,
    _platform_refusal,
    _runtime_refusal,
)
from .. import ui, words
from ..data import fate_of
from ..words import both

# What `lib/poller.py` writes into a record's `source=` field (`source="worker"`,
# `poller.py:245`), and therefore the one word that separates the rows this poll loop
# wrote from the rows `runday`/`table` wrote next to them.  The page does not own the
# word: it is the writer's, and the ledger's `source` column prints it as stored.
WORKER_SOURCE = "worker"

# The four arguments of the worker command that are page state and not filter fields
# (`ROUTE_KEYS["/worker"]` names all four next to `state`/`job`/`limit`).  Named once
# so that every link, every hidden field and the rails below carry one list.
PAGE_KEYS = ("mode", "platform", "runtime", "since")

# The queue's own axis: what *this machine* did with a node, as against `state`,
# which is what the API says about it.  Page state like the four above and carried
# beside them, but deliberately **not** in `PAGE_KEYS`: that tuple is the arguments
# of the command this page starts, and `_argv` must never print this one - a filter
# on what the table shows is not a flag the worker takes.  Keeping it out means
# `_keep`'s "the other arguments" stays true and the argv stays honest.
LOCAL_KEY = "local"

# Everything this screen keeps across a link or a form: the command's arguments and
# the table's own axis.  `_keep` and `_hidden` both walk this rather than `PAGE_KEYS`,
# because a rail that dropped `local` would answer about a different table than the
# page it was pressed on.
KEYS = (*PAGE_KEYS, LOCAL_KEY)

# Every key this screen reads: the route's own (`ROUTE_KEYS`) and the five above.  It
# is the list a link is allowed to carry, and it is stated rather than read off the
# request because `_url`'s route whitelist is defeated for *every* route by
# `ROUTE_KEYS["/"]` - a trailing slash matches every path, so a link written from a
# check that holds `origin=any` puts that condition in the address bar of a page that
# reads none of it.
READS = ("api", "state", "job", "text", "limit", *KEYS)


def worker(view) -> str:
    """The `/worker` screen: the loop, where its reports go, the queue, and what it finished.

    **The state-file panel is gone** (「它自己的状态文件其实我觉得可以不显示」).  It printed
    `var/state/worker-state.json`, its cursor, and three counts, with two long notes
    apologising for what the numbers do not mean - `cursor` is not the last claim time,
    `refused` is empty on a worker older than the field, `seen` counts ids and not runs.
    A panel that needs two paragraphs to say what its numbers are *not* is a panel whose
    numbers were the wrong ones, and the operator read it exactly that way (「什么是 seen
    重捡就是为什么要搞这种呢」).  The file is still written where it always was, and
    `python3 -c 'import lib.layout as l; print(l.worker_state())'` still names it; the one
    fact of it the page acts on - the reports written and not delivered - is its own table
    in the return-path panel, named rather than counted.
    """
    w = view.rows["worker"]
    queue = list(view.rows["queue"])
    picked = _picked(view)
    state = _state_in_force(view)
    mine = [one for one in view.rows["ledger"] if one["source"] == WORKER_SOURCE]
    return (
        _asked(view, queue, state)
        + _bar(view, queue, picked, state)
        + _other_api(view, picked)
        + _start(view, w, queue, picked)
        + _return_path(view)
        + _queue(view, queue)
        + _done(view, mine)
    )


# --------------------------------------------------------------- what was asked
def _asked(view, queue, state) -> str:
    """The query line: the base this page read, the question it put there, and the count.

    The keys are the wire's own and a key with no condition on it is **left out** rather
    than spelled `name=any`: "the absence of `created__gte` is no window" is the rule the
    builds page's line follows, and a line that invents a value for a filter nobody set
    is a paraphrase of the question rather than the question.

    The count is `remote.rows` and it is rendered in one language on purpose: that row
    carries `&mdash;`, and `words.both()` refuses a value with an entity in it (the swap
    has no `html` mode).  The head of the line is `remote.asked` and stays bilingual.
    """
    query = " ".join(part for part in ("kind=job", f"state={state}",
                                       f"name={view.check.job}" if view.check.job else "")
                     if part)
    return ui.hint(f'{both(view.lang, "remote.asked")}: '
                   f'<code>{ui.esc(_base(view))}: {ui.esc(query)}</code> '
                   f'<span class="muted">{view.t("remote.rows", n=len(queue))}</span>')


# ------------------------------------------------------------------ the filter bar
def _bar(view, queue, picked, state) -> str:
    """The one GET form: api, state, local, job, limit, and the mode the command will run in.

    Three of the four controls the old page had are here unchanged, and the fourth
    (`job`) is a select over the names this answer carries rather than the board's free
    box: `job_node_rows` matches a job's *name*, so a box whose placeholder promises
    "node id or name" would silently answer nothing for half of what it offers.  The
    names come from the rows the page is showing (the old page's rule), so a name can
    never be offered that the table below it would not draw.

    `state` and `local` are the two axes the operator asked to be able to ask
    separately (「能筛选本地的跑没跑…也能筛选按照 api 哪里的状态…两个是反开的」), and
    they sit next to each other because they are the same kind of thing: `state` is
    what the API says, `local` is what this machine did, and a box left at `any` is a
    box that asks nothing.  Neither depends on the other - `state` narrows the API
    read and `local` narrows the rows that come back - so any combination of the two
    is a question this page can answer.

    `text` is the search box, and it is new: the key was always read by this route
    (`READS`) and applied by the reader (`job_node_rows` matches it against a node's
    name, id, state and result), but no control drew it, so the only way to search this
    queue was to hand-edit the address bar.  The operator's own question about this page
    was 「像 worker 我感觉它缺少一点检索」 - and the search was never missing, only
    invisible.  The placeholder names the four fields the reader really matches, taken
    from that code rather than guessed: a box that promised "node id" and answered
    nothing for it would be the `job` box's old bug a second time.

    `mode` is the board's segmented radio, and it is in this bar rather than inside the
    action form for the reason the argv under the button is printed from the URL: the
    two must agree.  Flipping the segment re-answers this question (`data-auto` submits
    the bar), so what is printed under the button is what the button will run.

    Every key this route reads and this bar does not draw rides as a hidden field
    (`ui.filters`' `hidden=`, which is the same rule: the form is this page's): an
    `apply` is a GET, and a GET replaces the whole query string, so a key left out is a
    condition silently dropped.  `mode`/`platform`/`runtime`/`since` are page state and
    are carried the same way - here and through every link (`view.url(keep=...)`).
    """
    names = sorted({one["name"] for one in queue if one["name"]})
    fields = (
        ui.field(both(view.lang, "filter.api"), _api_box(view), "w-md")
        + ui.field(both(view.lang, "word.state"), ui.select(
            "state", [(value, ui.esc(value)) for value in JOB_STATES if value], state), "w-md")
        + ui.field(both(view.lang, "filter.local"), ui.select(
            LOCAL_KEY, [(value, _fate_label(view, value)) for value in LOCAL_FATES],
            _local_in_force(view)), "w-lg")
        + ui.field(both(view.lang, "filter.name"), ui.select(
            "job", [("", both(view.lang, "state.any"))] + [(one, ui.esc(one)) for one in names],
            view.check.job), "w-lg")
        + ui.field(both(view.lang, "filter.text"), ui.text_input(
            "text", view.check.text, placeholder="worker.text_hint",
            label="filter.text", lang=view.lang), "w-lg")
        + ui.field(both(view.lang, "filter.rows"), ui.number_input(
            "limit", view.check.limit, 1, MAX_LIMIT, stops=LIMITS), "w-sm")
        + ui.field(both(view.lang, "filter.mode"),
                   ui.seg("mode", [(value, both(view.lang, f"mode.label.{value}"))
                                   for value in MODES], picked["mode"])
                   + ui.hint(view.t("worker.mode_note.once") + "<br>"
                             + view.t("worker.mode_note.resident")),
                   "w-xl")
    )
    buttons = (ui.link_btn(both(view.lang, "btn.reset"), _reset(view), lang=view.lang)
               + '<button type="submit" class="btn primary sm">' + both(view.lang, "btn.apply")
               + "</button>")
    return ui.filters(fields, buttons, action=view.route, hidden=_hidden(view, picked))


def _api_box(view) -> str:
    """Which API this page reads: one box, whose value is the key a URL carries.

    An empty `?api=` is a real choice and not a missing one - it is the base this process
    started on - and the box shows that choice under the *name* of that base (the rule
    `analysis._api_field` keeps too), so the value in force is one of the options rather
    than a word like "any".  The labels are addresses and the values are keys: the short
    form the address bar and every link carry, with the address beside it, so picking one
    is not picking a name the reader has to guess at.
    """
    entries = [(name, base) for name, base in view.rows.get("apis") or ()]
    launch = _launch_base(view)
    chosen = view.check.api or _launch_name(view, launch) or launch
    options = entries if any(name == chosen for name, _base in entries) \
        else [(chosen, launch), *entries]
    return ui.select("api", [(value, ui.esc(label)) for value, label in options], chosen)


def _launch_name(view, base: str) -> str:
    """The name this deployment gave the base an empty `?api=` stands for, or `""`."""
    apis = view.apis if view.apis is not None else getattr(view.gui, "apis", None)
    return apis.name(base) if apis is not None else ""


def _launch_base(view) -> str:
    """The address an empty `?api=` stands for, as `_api_box` prints it."""
    if view.gui is None:
        return view.check.api_base
    return view.gui.launch_base()


def _whole_question(view, picked) -> list:
    """Every key this page's answers are made of, with the value in force: `(key, value)`.

    A GET form has no whitelist - the browser submits exactly the fields it holds - so a
    form that is not the filter bar has to state this page's whole question itself, or
    pressing it answers about a different queue.  The two sources are the route's own
    filter keys (from the request's query) and the worker's four arguments plus `local`
    (from the page state read above, by name: what that dict holds beside them is this
    page's own bookkeeping - the raw `?since=` a refusal is reported from - and not a key
    any route reads).
    """
    allowed = set(ROUTE_KEYS.get("/worker", ()))
    found = {key: value for key, value in view.check.to_query() if key in allowed}
    # The page state wins where both carry a key: the route's own keys are handed to the
    # check (`serve._with_route_keys`), so `mode` and `local` arrive by both roads, and a
    # name written twice in one form is two answers to one question.
    found.update({key: picked[key] for key in KEYS if picked.get(key)})
    return list(found.items())


def _hidden(view, picked) -> list:
    """`_whole_question`, minus the keys the bar draws a control for.

    A hidden field under a name the bar also renders a box for would be a second answer
    to one question: the browser sends both, and which one wins is the reader's browser's
    decision rather than this page's.
    """
    drawn = {"api", "state", "job", "text", "limit", "mode", LOCAL_KEY}
    return [(key, value) for key, value in _whole_question(view, picked) if key not in drawn]


def _page_url(view, route: str = "", **over) -> str:
    """One link on this screen: `view.url`, minus every key this route does not read.

    `view.url` is still the only writer of an address - this only takes away what the
    route whitelist failed to (`READS` says why).  Every link here is a link on `/worker`
    or a rail that sets one of its arguments, so what is left is exactly the reader's
    question about this queue.
    """
    loose = tuple(key for key in (*FILTER_ORDER, "delta") if key not in READS)
    return view.url(route, *loose, **over)


def _reset(view) -> str:
    """The "start over" link: this route with the reader's whole question dropped.

    Everything the route reads is dropped by name rather than the two or three keys this
    page happens to draw: a filter the reader set by hand (a `?text=`) is part of the
    question, and a "start over" that kept it would be a link to the page they are on.
    """
    return _page_url(view, "", **{key: "" for key in READS})


# ------------------------------------------------------------- the page state
def _named(check, name: str, options=()) -> str:
    """One page-state key off this request's check, or `""` when the check has none.

    `mode`/`platform`/`runtime`/`since` are not columns of a `Filter`, so a check built
    by an older read of this console simply does not carry them: the design's own
    default stays in force, which is the same answer a URL with no such key means.  Read
    through one function so the four cannot be spelled two ways, and never guessed from
    the rows: what the *live* worker was started with is a fact about a process, not the
    argument this page's button will pass.
    """
    value = str(getattr(check, name, "") or "")
    if options and value not in options:
        return ""
    return value


def _picked(view) -> dict:
    """The worker arguments and the table's own axis, as the form and the command read them.

    `since` is normalised through `forms._iso_stamp`, the one judge of that flag's shape
    (`Gui.command` refuses a stamp it cannot read, and `poller.iso_ago()` would silently
    read one it cannot parse as "now" - the 15-minute window the flag exists to widen).  The
    raw value is kept beside it so the button can be blocked by the sentence the POST
    would have answered with, instead of quietly running a narrower window.

    `local` is carried here because it has to survive the same journeys the four
    arguments do, not because it is one of them: it is left out of `_argv` by name,
    and its empty value is kept empty rather than spelled `any`, so a form or a link
    that has nothing to say about it says nothing (`_hidden` drops it, and the box
    shows the catalogue's own "any" for the absence).
    """
    since = _named(view.check, "since")
    return {
        "mode": _named(view.check, "mode", MODES) or MODES[0],
        "platform": _named(view.check, "platform") or DEFAULT_DEVICE,
        "runtime": _named(view.check, "runtime") or DEFAULT_LAB,
        "since": _iso_stamp(since),
        "since_raw": since,
        LOCAL_KEY: _named(view.check, LOCAL_KEY, LOCAL_FATES),
    }


def _state_in_force(view) -> str:
    """Which queue state this page is about: the URL's, or the one a worker can claim from.

    `data._queue` reads `available` when the URL names no state, and that is the page's
    own question - "what can this host claim" - so the box, the query line and the count
    below it all read this one answer rather than each deciding for itself.
    """
    return view.check.state or JOB_STATES[1]


# ------------------------------------------------------------------ the start bar
def _start(view, w, queue, picked) -> str:
    """What the loop is, what the button would run, and where the results will land.

    The rails come first because they are the command's own arguments, then the button
    whose body they are, then the argv the button will really exec, then the board's
    sentence - so the panel reads as one promise from "which queue" to "where the answer
    appears".  A refused platform (or a `?since=` the poller could not read) takes the
    button's place rather than being printed into an argv nobody will run: a control that
    fails after it is pressed is worse than one that explains itself.
    """
    blocked = (_platform_refusal(picked["platform"], view.lang)
               or (view.t("error.not_a_stamp", key="since", value=repr(picked["since_raw"]))
                   if picked["since_raw"] and not picked["since"] else ""))
    return ui.panel("", "".join((
        _facts(view, w),
        ui.action_form("worker", both(view.lang, "btn.start_worker"),
                       fields=[("api", view.check.api), ("mode", picked["mode"]),
                               ("platform", picked["platform"]),
                               ("runtime", picked["runtime"]), ("since", picked["since"])],
                       inner=_rails(view, queue, picked),
                       argv=_argv(view, picked), hint="worker.start_hint", blocked=blocked,
                       lang=view.lang),
        _claim_badge(view, queue, picked),
        ui.hint(view.t("worker.where_results")),
    )), lang=view.lang)


def _facts(view, w) -> str:
    """The board's status row: the state, the pid, the start, the uptime, and a way out.

    The four facts are `data._worker`'s, which is the newest worker activity on this
    machine, running or not - so an idle page still names the pid and the uptime of the
    last loop, and the pill is what says whether it is still going.  A value the disk
    does not hold prints the design's dash rather than a zero: `pid` is `0` when no
    worker activity exists at all, and a row reading `process 0` would claim a process
    that does not exist.

    The stop button is a real `POST /api/runs/<id>/cancel`, drawn only while something is
    running, and it carries its own `[data-status]`: the shipped script takes that POST
    over and writes the answer into the form it came from, so the row says whether the
    cancellation was accepted instead of navigating to the JSON.
    """
    pid = ui.esc(w["pid"]) if w["pid"] else ui.DASH
    uptime = ui.esc(w["uptime"]) if w["uptime"] else ui.DASH
    started = ui.esc(w["started"]) if w["started"] else ui.DASH
    stop = ""
    # Which mode the worker that is *actually running* is in, read off its own argv
    # (`data._worker`'s `argv` is `Run.argv` as started, not this page's `mode` box).
    # The two are different questions and the page used to answer only the second: the
    # segment says what the next press would run, and an operator watching a loop that
    # would not stop had no way to tell a `resident` from an `once` that had wedged.
    # `--once` is looked for as a whole word, because a path containing it
    # (`.../pull_worker.py --once-job`) is not the flag.
    words_argv = str(w.get("argv") or "").split()
    mode = ("" if not words_argv else
            (both(view.lang, "mode.label.once") if "--once" in words_argv
             else both(view.lang, "mode.label.resident")))
    mode_hint = ("worker.mode_once" if "--once" in words_argv else "worker.mode_running")
    fact = ("" if not words_argv else
            f'<span class="q" title="{ui.esc(view.t(mode_hint))}">'
            + both(view.lang, "worker.mode_label") + f' <b>{mode}</b></span>')
    if w["running"] and w["run_id"]:
        stop = ('<form method="post" action="/api/runs/'
                + ui.esc(urllib.parse.quote(str(w["run_id"]), safe="")) + '/cancel">'
                + f'<button class="btn sm danger">{both(view.lang, "js.cancel")}</button>'
                + ui.status() + "</form>")
    return ('<div class="row" style="gap:14px;align-items:baseline">'
            + ui.pill("running" if w["running"] else "idle", lang=view.lang)
            + f'<span class="q">{both(view.lang, "worker.pid")} <b>{pid}</b></span>'
            + f'<span class="q">{both(view.lang, "worker.since")} <b>{started}</b></span>'
            + f'<span class="q">{both(view.lang, "worker.uptime")} <b>{uptime}</b></span>'
            + fact
            + ui.spread() + stop + "</div>")


def _rails(view, queue, picked) -> str:
    """The command's three other arguments, one row of links each.

    A rail and not a select box, and that is the old page's argument kept: the value has
    to be visible in the URL, because the argv printed under the button is built from the
    URL - a box whose value lived only in the browser could show one command and run
    another.  A value in force that the rows do not carry is offered as its own link
    (`ui.select`'s `(current)` rule): a reader who arrived on a hand-edited URL has to be
    able to see, and to leave, the value their button will use.

    **`off` is built from the choices and not from the queue**, and that is the whole of
    the fix this page needed.  It used to be keyed by the platforms the *queue* carried
    (`| {DEFAULT_DEVICE}`), while the choices are the queue's plus the value in force -
    so the one value the rail had no verdict for was exactly the one a hand-edited URL
    puts in force.  `?platform=mynonsense-123` drew as `<a aria-current="true">`, a live
    link with no reason on it, for a name `_platform_refusal` has a whole branch for
    (`worker.platform_unknown`) and `actions._offered` refuses outright - so the link
    re-asked the same bad question, and the Start button under it would have answered
    409.  A blocked value is only blocked if the rail was asked about it, and the rail
    only draws the choices.
    """
    platforms = _choices(sorted({one["platform"] for one in queue if one["platform"]}
                                | {DEFAULT_DEVICE}), picked["platform"])
    runtimes = _choices(sorted({one["runtime"] for one in queue if one["runtime"]}
                               | {DEFAULT_LAB}), picked["runtime"])
    return (
        _rail(view, "word.platform", platforms,
              picked["platform"], "platform", _keep(picked, "platform"),
              off={value: _platform_refusal(value, view.lang) for _label, value in platforms})
        + _rail(view, "word.runtime", runtimes,
                picked["runtime"], "runtime", _keep(picked, "runtime"),
                off={value: _runtime_refusal(value, view.lang) for _label, value in runtimes})
        + _since(view, queue, picked)
        + _pairs(view, queue, picked)
    )


def _choices(values, current) -> list:
    """One `(label, value)` per name, with the value in force added when it is absent."""
    found = [(ui.esc(one), one) for one in values]
    if current and current not in values:
        found.append((ui.esc(current), current))
    return found


def _local_in_force(view) -> str:
    """Which local fate this table is showing; `any` when the URL names none."""
    return _named(view.check, LOCAL_KEY, LOCAL_FATES) or LOCAL_FATES[0]


def _fate_label(view, value: str) -> str:
    """One option of the `local` box, as bilingual markup.

    `any` is not one of the four answers - it is the absence of a question - so it
    takes the catalogue's own `state.any`, which is the word every other box on this
    console uses for "no condition" (`_bar`'s name select does the same).  Giving it
    a `local.label.*` of its own would be a fifth answer to a four-answer question.
    """
    key = "state.any" if value == LOCAL_FATES[0] else f"local.label.{value}"
    return both(view.lang, key)


def _keep(picked, name: str) -> list:
    """The page keys a rail link has to carry: the others, and nothing else.

    A rail sets one argument of the command; a link that dropped the rest would
    answer about a different worker than the page it was pressed on, which is the
    whole reason these keys are page state rather than boxes inside a button's form.
    `local` rides along with them for the same reason: it is not an argument, but it
    is part of the question the table below answers, and a rail link that cleared it
    would change what the reader is looking at as a side effect of changing which
    queue the button would claim from.
    """
    return [(key, picked[key]) for key in KEYS if key != name and picked.get(key)]


def _rail(view, label_key: str, choices, current, name: str, keep, off=None,
          width: str = "w-lg", badge: str = "") -> str:
    """One page-state key as a row of links: the value in force is marked.

    A value this deployment must not offer is drawn where it was, under its own name, as
    a `<span>` with the reason in its `title=` and `aria-disabled` for a screen reader -
    never as a link.  That is `_platform_refusal`'s answer and not a second opinion: the
    same reader decides what `pull_worker.py` will accept, so a pill and the button
    behind it cannot disagree.
    """
    blocked = {value: why for value, why in (off or {}).items() if why}
    links = []
    for label, value in choices:
        if value in blocked:
            links.append(f'<span class="muted" aria-disabled="true" '
                         f'title="{ui.esc(blocked[value])}">{label}</span>')
            continue
        mark = ' aria-current="true"' if value == current else ""
        href = _page_url(view, "", keep=keep, **{name: value})
        links.append(f'<a href="{ui.esc(href)}"{mark}>{label}</a>')
    return ui.field(both(view.lang, label_key),
                    f'<span class="seg">{"".join(links)}</span>{badge}', width, tag="div")


def _since(view, queue, picked) -> str:
    """`--since`, which is how far back the window opens - not a claim filter.

    **Two buttons and a box**, because the two answers a reader actually has are
    "everything the queue has" and "from here on".  The second button writes the stamp
    of the moment the page was drawn, which is what "from here on" means to a reader
    pressing it; the box is for the third answer, a date they have in mind.

    The rail this replaced offered *the oldest `created` in this answer*, which is a
    stamp that moves every time the window moves and says nothing a reader can act on:
    the operator's report was that the control was unreadable (「我不明白你那个起于那个
    有什么意义」), and a value which is a property of the answer rather than a choice
    cannot be explained into being one.

    A `?since=` neither button produced is still printed, as its own marked segment, so
    the reader can see - and leave - the value their button will really use: a hand-typed
    stamp that the page silently replaced would be an argv the child ignores.  The badge
    beside it says what the flag outranks, which is the one thing worth knowing before
    pressing it.  Nothing here validates: the judge is `forms._iso_stamp`, and a box it
    refuses is reported by `_warnings`, not by this rail.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    choices = [(both(view.lang, "worker.since_all"), ""),
               (both(view.lang, "worker.since_now"), now)]
    if picked["since"] and all(picked["since"] != value for _label, value in choices):
        choices.append((ui.esc(picked["since"]), picked["since"]))
    links = []
    for label, value in choices:
        mark = ' aria-current="true"' if value == picked["since"] else ""
        href = _page_url(view, "", keep=_keep(picked, "since"), since=value)
        links.append(f'<a href="{ui.esc(href)}"{mark}>{label}</a>')
    # The box is its own GET form over the same question, and it is **not** the filter
    # bar: the bar's `api` and `mode` controls are not inside it, so every key this page
    # reads rides along as a hidden field (`_whole_question`, not `_hidden` - the latter
    # is the bar's own list, and reusing it here dropped `api` and `mode`, which made
    # typing a stamp also reset which API the worker would be started against).  With the
    # script off this is the only way to set a third value, which is why it is a form and
    # not a link.
    hidden = "".join(f'<input type="hidden" name="{ui.esc(key)}" value="{ui.esc(value)}">'
                     for key, value in _whole_question(view, picked) if key != "since")
    box = (f'<form method="get" action="{ui.esc(view.route)}" class="inline">'
           + hidden
           + ui.text_input("since", picked["since"], placeholder="worker.since_ph",
                           label="filter.since", lang=view.lang)
           + f'<button class="btn sm">{both(view.lang, "btn.apply")}</button></form>')
    badge = (f'<span class="pill idle" {words.attr(view.lang, "title", "worker.since_hint")}>'
             f'{both(view.lang, "worker.since_badge")}</span>')
    return ui.field(both(view.lang, "filter.since"),
                    f'{box}<span class="seg">{"".join(links)}</span>{badge}',
                    "w-lg", tag="div")


def _pairs(view, queue, picked) -> str:
    """Where the work is: the available queue counted by (platform, runtime), biggest first.

    The page's default pair claims nothing on a queue that belongs to another lab, and the
    reader was left with a list of platform names to search by hand.  This is that search
    done: each count is one press that points the page at a pair that has work in it, and
    the count is over the rows this answer carries - the same answer the table above draws,
    so the two cannot disagree.

    A pair whose platform this host cannot boot is shown and **not linked**: the count is
    true and the link is a promise this deployment cannot keep.  A rail whose only choice
    is the pair in force is not drawn at all - there is nothing to choose.
    """
    counts: dict = {}
    for one in queue:
        if str(one.get("state") or "") != JOB_STATES[1]:
            continue
        pair = (str(one.get("platform") or ""), str(one.get("runtime") or ""))
        if all(pair):
            counts[pair] = counts.get(pair, 0) + 1
    if not counts:
        return ""
    wanted = (picked["platform"], picked["runtime"])
    if list(counts) == [wanted]:
        return ""
    links = []
    for (platform, runtime), many in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        label = both(view.lang, "worker.pair", platform=ui.esc(platform), runtime=ui.esc(runtime), n=many)
        reason = _platform_refusal(platform, view.lang)
        if reason:
            links.append(f'<span class="muted" aria-disabled="true" '
                         f'title="{ui.esc(reason)}">{label}</span>')
            continue
        mark = ' aria-current="true"' if (platform, runtime) == wanted else ""
        href = _page_url(view, "", keep=_keep(picked, "platform"),
                         platform=platform, runtime=runtime)
        links.append(f'<a href="{ui.esc(href)}"{mark}>{label}</a>')
    return ui.field(both(view.lang, "worker.pairs_lead"), f'<span class="seg">{"".join(links)}</span>',
                    "w-xl", tag="div")


def _claim_badge(view, queue, picked) -> str:
    """What this button would claim, before it is pressed.

    The rows are the API's own `available` nodes for this page's question and the pair is
    the one the button will pass, so this is what that command can take - not a second
    claim rule: `Kjob.claimable` is what the worker itself applies when it claims.  The
    point is the operator's "a worker that finds nothing then reports itself failed" - so
    the count is printed *before* the start rather than discovered after it, and the tone
    says whether there is anything to claim at all.
    """
    n = sum(1 for one in queue
            if one["state"] == JOB_STATES[1]
            and one["platform"] == picked["platform"] and one["runtime"] == picked["runtime"])
    return ui.hint(ui.pill("info", tone_override="info" if n else "idle",
                           label=both(view.lang, "worker.would_claim", n=n), lang=view.lang))


def _argv(view, picked) -> str:
    """The command line the start button will run, from the engine that builds it.

    `Gui.command` is the only source: a page that assembled its own argv would drift from
    the process the button starts, and the printed line is the promise the whole bar
    makes.  A refused combination comes back as the engine's own sentence rather than as
    an invented command line (`_argv_of` catches `KciError`), and the raw `?since=` is
    what it is handed - a stamp this page normalised away must still be *reported* in the
    line the reader is looking at, not quietly dropped from it.
    """
    if view.gui is None:
        return ""
    fields = {"mode": picked["mode"], "platform": picked["platform"],
              "runtime": picked["runtime"], "since": picked["since"] or picked["since_raw"]}
    return view.gui._argv_of("worker", fields, view.lang, api=view.check.api)


# --------------------------------------------------------------- where reports go
def _return_path(view) -> str:
    """Where a finished job's report goes, and what signs it: three rows and a table.

    The panel the operator needed and the page did not have.  The question it answers
    is the one that cost them an afternoon - a job runs, the ledger gets its row, and
    the API still says the node was never reported - and every fact needed to answer it
    was already on this machine in four different places.  `data._return_path` is the
    reader; this is the drawing of it.

    **One row for the destination, not two.**  The panel used to draw the definition's
    `callback.url` and *this deployment sends to* as separate rows, which made the
    reader do the resolution themselves from a pair of hints - and the operator asked
    for the merge in as many words (「callback.url 和这个部署改发到这两个不能合并一下
    吗」).  The row now prints `sink.delivery_url`'s own answer, the value a delivery
    will really use, and the box under it is how it is changed.  Nothing is decided
    here: the reader's `destination` is the same call `poller.handle` makes.

    The two rows that went with it: `token_name`, which this tree has never read and
    which sent the operator looking for a token by a name no header carries; and the
    state-file panel beside this one, whose counts needed two notes to say what they
    do *not* mean (`worker()` has the whole of that).

    **The token's value is never printed** - the row says which of the two places it
    *would* come from instead.  A page is screenshotted; a token on a page is a token
    leaked.
    """
    path = view.rows.get("return_path") or {}
    if not path:
        return ""
    source = str(path.get("token_source") or "")
    read = str(path.get("definition") or "")
    pairs = [
        (both(view.lang, "worker.return_definition"),
         f"<code>{ui.esc(read)}</code>" if read else ui.hint(view.t("worker.return_definition_none"))),
        (both(view.lang, "worker.return_destination"), _destination(view, path)),
        (both(view.lang, "worker.return_token"),
         view.t(f"worker.return_token.{source or 'none'}")),
    ]
    # The subtitle follows the read: the ordinary one claims the panel *cannot disagree
    # with what the worker will really send*, which is only true of a panel that got a
    # definition.  Without one it would be the same dashes the reader cannot interpret,
    # under a sentence telling them to trust it.
    return ui.panel("page.worker.return_title",
                    ui.kv(pairs) + _pending_table(view, path.get("pending") or ()),
                    sub=view.t("page.worker.return_sub" if read
                               else "page.worker.return_sub_empty"),
                    lang=view.lang)


def _destination(view, path) -> str:
    """The merged row: where a report goes, and the one control that changes it.

    Three states, and the row says which one it is in words rather than by the shape of
    a box: the definition's `callback.url`, a URL this deployment set instead, or
    `off` - nothing is posted anywhere.  An empty box cannot tell those apart, which is
    what the two rows used to cost the reader.

    **The box holds the override and nothing else.**  With no override it is empty and
    the value above it is the definition's; with one it holds that URL, which is also
    the value above it - the same string twice, and that is the merge working rather
    than a duplication: what is written and what is in force are one thing whenever an
    override is in force.

    Clearing it is the same button as setting it: an empty box saved means "back to the
    definition's" (`sink.set_callback_override` removes the file), and `off` means
    "nowhere".  One control, three meanings, and every one of them is written on the
    page under it.
    """
    override = str(path.get("override") or "")
    destination = str(path.get("destination") or "")
    if path.get("why") and not destination:
        # The definition could not be read *and* this deployment has said nothing: the
        # only honest value is the reason, which is what the old `callback.url` row
        # printed.  An override on its own is a destination regardless of the read.
        where = f'<span class="muted">{ui.esc(str(path["why"]))}</span>'
    elif destination == sink.OFF:
        where = both(view.lang, "worker.return_where_off_value")
    elif not destination:
        where = ui.DASH
    else:
        where = f"<code>{ui.esc(destination)}</code>"
    if override == sink.OFF:
        hint = view.t("worker.return_where_off")
    elif override:
        hint = view.t("worker.return_where_override")
    else:
        hint = view.t("worker.return_where_definition")
    return ('<form method="post" action="/api/worker/callback">'
            '<div class="inline">' + where + "</div>"
            '<span class="inline">'
            + ui.text_input("url", override if override != sink.OFF else sink.OFF,
                            placeholder="worker.return_override_ph",
                            label="worker.return_destination", lang=view.lang)
            + f'<button class="btn sm">{both(view.lang, "btn.apply")}</button>'
            + ui.status()
            + "</span>"
            + ui.hint(hint)
            + "</form>")


def _pending_table(view, pending) -> str:
    """The reports written and not delivered: one row each, or one sentence saying none."""
    if not pending:
        return ui.hint(view.t("worker.return_pending_none"))
    cols = [
        ui.Col("word.node_id", draw=lambda one: ui.code(one["node_id"])),
        ui.Col("col.callback", draw=lambda one: ui.code(one["callback"]) if one["callback"] else ui.DASH),
        ui.Col("col.verdict", kind="c",
               draw=lambda one: ui.pill(one["verdict"], lang=view.lang) if one["verdict"] else ui.DASH),
        ui.Col("col.detail", draw=lambda one: ui.esc(one["detail"]) or ui.DASH),
    ]
    return ui.hint(view.t("worker.return_pending_lead")) + ui.table(cols, pending, lang=view.lang)


# --------------------------------------------------------------------- the queue
def _queue(view, queue) -> str:
    """The API's job nodes: one row each, with what this machine did behind `local`.

    Twelve columns and no `key` on any of them: `key` is what the header *sorts by*, and
    `/worker` reads no `sort` (`ROUTE_KEYS`), so a header drawn `sortable` here would
    promise an order that no link can ask for.  The order is the data layer's and it is
    **newest first** (`data._queue` sorts, and says why the reader hands them over the
    other way round) - the operator's own default (「默认跑最新的」).

    The `local` column is the one this panel exists for: `Gui.job_node_rows` answers it
    against the state file's `seen`/`pending`/`refused`, which is why the page prints
    the row's own word instead of comparing anything itself.  The header is `col.local`
    and not the old `col.claimed?` - a question mark over a column whose cells say
    "ran", "put down" and "never looked at" was asking about only one of them, and the
    operator asked for the mark to go (「领过? 的问号去掉」).

    `word.build` is the node's `parent` linked to `/local/<build_id>`: it is the one
    field on a job node that says which build the job was dispatched for, and the
    builds page's single-build view is where the artifact, the card and the ledger for
    that id already are.  A node with no `parent` gets the design's dash, not a link to
    a build that is not there.

    `word.route` is the column beside it and it is the other half of the same fact:
    `build` is the id, and a route is the names (`_route_cell`).  Both are drawn because
    they answer different questions - the id is what `/local/<id>` and the API's own
    answers are keyed by, and the names are what a reader recognises.  On their own the
    ids left the operator saying 「worker 这个构建路线…你写 woker 里面写太少」: a page
    of hex digits never says that the build step happened upstream of this table.

    The empty message is chosen, not fixed: `data._queue` hands over the reader's own
    reason, and a page that printed "the API answered, and its queue holds nothing"
    over a read that never arrived was telling the operator the queue is empty at the
    exact moment nothing was known about it - the one sentence this panel must never
    get wrong, because "there is nothing to claim" is what sends someone home.
    """
    cols = [
        ui.Col("word.node_id", draw=lambda one: ui.code(one["node_id"])),
        ui.Col("col.name", draw=lambda one: ui.code(one["name"])),
        ui.Col("word.build", draw=lambda one: _build_link(view, one)),
        ui.Col("word.route", draw=lambda one: _route_cell(view, one)),
        ui.Col("word.state", kind="c", draw=lambda one: ui.pill(one["state"], lang=view.lang)),
        ui.Col("word.result", kind="c",
               draw=lambda one: ui.pill(one["result"], lang=view.lang) if one["result"] else ui.DASH),
        ui.Col("word.platform", draw=lambda one: ui.code(one["platform"])),
        ui.Col("word.runtime", draw=lambda one: ui.code(one["runtime"])),
        ui.Col("word.created", kind="n",
               draw=lambda one: ui.stamp(one["created"], view.check.tz)),
        ui.Col("col.local", kind="c", draw=lambda one: _fate(view, one)),
        ui.Col("col.definition", kind="c",
               draw=lambda one: both(view.lang, "state.yes") if one["definition"] else both(view.lang, "state.no")),
        ui.Col("col.forget", kind="c", draw=lambda one: _forget_button(view, one)),
    ]
    why = str(view.rows.get("queue_why") or "")
    empty = (view.t("empty.queue_no_answer", note=ui.esc(why)) if why else
             view.t("empty.queue_empty", state=ui.esc(_state_in_force(view)),
                    job=ui.esc(view.check.job or view.t("state.any"))))
    return ui.panel("worker.queue", ui.table(cols, queue, empty=empty, lang=view.lang),
                    sub=view.t("worker.queue_sub"),
                    flush=True, lang=view.lang)


def _build_link(view, one) -> str:
    """One node's build id as a link to that build's own page, or the design's dash.

    Built like `_build_cell` below and for the same reason - `/local/<id>` reads a
    build id and the API and nothing else, so this page's conditions are dropped
    rather than printed onto an answer that has no use for them - but it is not the
    same cell: that one is a ledger record's build and carries the record's own
    correspondence, while this is the build a *queue node* was dispatched for, and a
    node whose build never arrived here is exactly the row an operator is looking for.
    """
    build = str(one.get("build_id") or "")
    if not build:
        return ui.DASH
    short = f"{build[:16]}&hellip;" if len(build) > 16 else ui.esc(build)
    href = view.url("/local/" + urllib.parse.quote(build, safe=""),
                    *(key for key in (*FILTER_ORDER, "delta") if key != "api"))
    return f'<a href="{ui.esc(href)}" title="{ui.esc(build)}">{short}</a>'


def _route_cell(view, one) -> str:
    """Where this node sits in the pipeline: the API's own `path`, as a breadcrumb.

    The row already says which *build* it belongs to, and that cell is an id - sixteen
    hex digits and an ellipsis, which is what a link needs and not what a reader needs.
    The route is where the names are, and it is the API's answer rather than this page's
    guess (`activities._path_of` reads the node's own `path`):

        checkout &rsaquo; kbuild-gcc-14-riscv &rsaquo; baseline-riscv-pull-labs

    The path's **last element is the row's own `name`**, and it is not drawn here: the
    `name` column sits immediately to the left with the same string in it, and repeating
    it cost every row fifteen pixels of height for a wrap that said nothing new
    (measured: the cell wanted 300px and wrapped to two lines, against 74px for the
    chain above it).  So this cell is the chain *up to* this node - what a reader
    cannot already see - and the whole path, tail included, is in the `title=` for the
    case where a reader wants to read it as a whole.

    `path[-1] != name` is drawn in full rather than trimmed, because the trim is a fact
    about these nodes and not a rule: a node whose path ends somewhere else would
    otherwise lose the only element that says where it ended.

    What the cell adds over the `build` column is the same fact spelled as a name rather
    than an id, and above all the middle element - the `kbuild` node the job was
    dispatched for.  That is the operator's 「worker 这个构建路线」: every row here is a
    **job** node (`getjob` reads `kind="job"`), so the build step is upstream of this
    table and is named on these paths rather than by a row of its own.

    A node that names no path gets the design's dash, and not a route assembled from the
    columns around it: half a breadcrumb reads as a whole one.
    """
    path = [str(part) for part in (one.get("path") or []) if str(part)]
    if not path:
        return ui.DASH
    drawn = path[:-1] if path[-1] == str(one.get("name") or "") and len(path) > 1 else path
    return (f'<span class="route" title="{ui.esc(" / ".join(path))}">'
            + " &rsaquo; ".join(ui.esc(part) for part in drawn) + "</span>")


def _fate(view, one) -> str:
    """One row's local fate: what this machine did with this node, in one word.

    Four words for four facts, and the words are the reason this column replaced a
    tick: `claimed` was true of a node the loop ran *and* of a node it refused, so a
    green tick said "ran" about six nodes this deployment never ran - the operator's
    「这六个到底是跑了还是没跑」, which no file on the disk could answer because
    nothing wrote the refusal down.  `poller.refuse` writes it now, and this cell
    prints it in the `title=` of the cell that reports it.

    The two cells that are not a pill are deliberate. `never` is muted text, because
    a node the loop has not reached is the normal case and a column of pills would
    make it look like one; and `refused` is `plain` rather than `bad`, because a job
    another lab claimed, or one already done, is the queue working, not a fault - the
    sentence in the tooltip is where the difference between the three reasons lives.

    `fate_of` is the single judge (`data.fate_of`, which the `local` filter also
    reads), so the box and the cells it selects cannot disagree.
    """
    fate = fate_of(one)
    if fate == "never":
        return f'<span class="muted">{both(view.lang, "local.cell.never")}</span>'
    tone = {"held": "warn", "ran": "ok", "refused": "plain"}[fate]
    label = both(view.lang, f"local.cell.{fate}")
    if fate == "refused":
        reason = str(one.get("refused") or "")
        title = f' title="{ui.esc(reason)}"' if reason else ""
        return f'<span class="pill {tone}"{title}>{label}</span>'
    return ui.pill(tone, tone_override=tone, label=label, lang=view.lang)


def _forget_button(view, one) -> str:
    """The one way back out of `seen`, drawn on the rows that have one.

    On `refused` and on `ran` - the two fates where this loop has a memory of the node
    - and on neither of the others.  `never` has nothing to undo.  `held` is a job that
    really ran with its report still undelivered, and forgetting *that* would let the
    next poll run it again: it is the one thing `seen` exists to prevent, and the new
    run would overwrite the ledger record of the run that already happened.

    `ran` is the row this button mostly exists for (`seen` is forever, `_drain` skips a
    seen id before `handle` is reached, and before `refused` existed the six nodes the
    operator was asking about were exactly these), and it is also the row it cannot be
    sure about: `fate_of` says `ran` is "in `seen` with nothing recorded against it",
    which is one fact covering two situations.  The tooltip says so, because the two
    outcomes do not cost the same - picking up a node the loop never ran costs one run,
    and picking up one it did run overwrites the record of that run.
    """
    fate = fate_of(one)
    if fate not in ("refused", "ran"):
        return ui.DASH
    node = str(one.get("node_id") or "")
    if not node:
        return ui.DASH
    hint = view.t("worker.forget_warn" if fate == "ran" else "worker.forget_hint")
    action = "/api/worker/forget/" + urllib.parse.quote(node, safe="")
    return ('<form method="post" action="' + ui.esc(action) + '">'
            + f'<button class="btn sm" title="{ui.esc(hint)}">'
            + both(view.lang, "btn.forget") + "</button>" + ui.status() + "</form>")


def _other_api(view, picked) -> str:
    """The note that says a live worker is claiming from somewhere else - `""` when they agree.

    The queue above is drawn from this page's `?api=` and the live panel lists a worker
    with its own `--api-url`, and nothing said the two need not be the same base: an
    operator read `rows 0` beside a worker that had run against the local stack as "the
    worker never claimed anything", when the queue it was claiming from was simply not the
    one on screen.  Each base becomes a link that moves this page's `api` key there, so
    the table below becomes the queue that worker is really taking jobs out of.

    `Gui.worker_bases()` is the reader and is reached for by name: it is a fact about the
    live panel's own rows, and `data.rows` has no key for it.
    """
    base = _base(view)
    if view.gui is None or not base:
        return ""
    links = []
    for one in view.gui.worker_bases():
        if one == base:
            continue
        key = view.apis.key(one) if view.apis is not None else one
        # `_keep(picked, "api")` is all five: `api` is a filter key and not page state,
        # so it is in none of `KEYS` and nothing is excluded - which is the point, this
        # link sets `api` itself and must carry the reader's whole question beside it.
        links.append(f'<a href="{ui.esc(_page_url(view, "", keep=_keep(picked, "api"), api=key))}" '
                     f'{words.attr(view.lang, "title", "worker.other_api_act")}><code>{ui.esc(one)}</code></a>')
    if not links:
        return ""
    return ui.hint(view.t("worker.other_api", link=" ".join(links)))


def _base(view) -> str:
    """The address this page is really reading - the one the query line prints."""
    if view.gui is None:
        return view.check.api_base
    return view.gui.api_base(view.check)


# --------------------------------------------------------------- what it finished
def _done(view, mine) -> str:
    """The ledger's `source=worker` rows: what this loop actually claimed and ran.

    The panel that answers "did it do anything" without a cursor: every row here is a
    record `pull_worker.py` wrote, with the verdict `lib/judge.py` gave it and the run's
    own `detail` printed as stored.  `took` is the board's column and it prints the
    design's dash - a record carries no duration (`data.py`'s ledger rows are
    `build_id/test/verdict/exit/source/when/detail`), and a cell nothing measured says so
    rather than showing a zero.

    Not capped: a silent `[:8]` would hide exactly the rows the panel exists to count, and
    on this workspace the ledger holds five of them.  What replaces the cap is the pager
    below the table, on a key of this panel's own (`done`): the ledger is the longest
    thing on this screen and `limit` is the queue's page size, so one shared offset would
    turn the queue and the finished list to the same page at once.
    """
    cols = [
        ui.Col("col.when", kind="n",
               draw=lambda one: ui.stamp(one["when"], view.check.tz, seconds=True)),
        ui.Col("word.build", draw=lambda one: _build_cell(view, one)),
        ui.Col("word.test", draw=lambda one: ui.code(one["test"])),
        ui.Col("col.verdict", kind="c", draw=lambda one: ui.pill(one["verdict"], lang=view.lang)),
        ui.Col("col.took", kind="n", draw=lambda one: ui.DASH),
        ui.Col("col.detail", kind="wrapc", draw=lambda one: ui.esc(one["detail"])),
    ]
    return ui.list_panel(view, "worker.done_here", cols, mine,
                         offset=view.check.list_offset("done"),
                         limit=view.check.limit, key="done", lang=view.lang)


def _build_cell(view, one) -> str:
    """One record's build, linked to the page that holds its whole correspondence.

    `/local/<build_id>` is the route the console's own ledger table links to, and it is
    the one page that shows a build by id whether or not the local table still carries a
    card for it.  The id is quoted into the path and the whole of it is in the `title=`:
    the cell truncates, and a truncated id with nothing behind it is a value the reader
    has to retype.

    The filter keys are dropped, because that page reads none of them: it reads a build
    id and the API (which it keeps, `_url`'s own rule), so a link carrying `?limit=` and
    `?origin=` would be this page's question printed onto an answer that has no use for
    it.  That is what the old layer's `_records_table` did by building a fresh `Filter`
    for the link.
    """
    build = str(one["build_id"] or "")
    short = f"{build[:16]}&hellip;" if len(build) > 16 else ui.esc(build)
    href = view.url("/local/" + urllib.parse.quote(build, safe=""),
                    *(key for key in (*FILTER_ORDER, "delta") if key != "api"))
    return f'<a href="{ui.esc(href)}" title="{ui.esc(build)}">{short}</a>'
