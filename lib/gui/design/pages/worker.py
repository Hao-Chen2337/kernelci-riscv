# SPDX-License-Identifier: LGPL-2.1-or-later
"""The worker screen (`/worker`): what the poll loop is doing, what it claimed, what came back.

Five panels, and each one answers a question the others cannot:

* the **status line and the start bar** say what the poll loop *is* - its state, its
  pid, when it started, how long it has been up - and print the command the button
  will really run.  That line is `Gui.command`'s own argv (`Gui._argv_of`), built from
  the same values the form posts, so the printed line and the process behind it cannot
  drift; and the sentence under it says where the results will land, because a button
  whose effect the reader has to guess at is a button that gets pressed twice.
* the **state file** panel prints the poller's own document as it stands: the path, the
  cursor, and `seen`/`pending` as counts.  Two numbers, and the panel has to say which
  one means "this loop really claimed something", because `cursor` moves on every poll
  that has *any* event in the window - including events already seen - so a healthy
  idle loop and a stuck one look identical on it (`worker.cursor_note`, the board's own
  sentence, kept word for word).
* the **queue** is the API's job nodes with `claimed` answered against that same `seen`
  list: `Gui.job_node_rows` is the reader, and it is what makes the column mean
  something.  A pair the loop never saw and a pair it claimed and finished are one
  word apart in the API's own answer, and that word is the whole question here.
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

**Two sentences the board's own second revision deleted and this console keeps**, both
because the operator asked for them by name: the warning beside the cursor
(`worker.cursor_note`) and the one under the start button saying where the results will
land (`worker.where_results`).  V2 dropped them and V2 dropped every panel's `sub` with
them; the words are the board's own, in both languages, and a start button with no such
line is the button `00-BRIEF.md` §5 refuses.
"""

import urllib.parse

from ....tests import DEFAULT_DEVICE, DEFAULT_LAB
from ...forms import _iso_stamp
from ...schema import (
    FILTER_ORDER,
    JOB_STATES,
    LIMITS,
    MAX_LIMIT,
    MODES,
    ROUTE_KEYS,
    _platform_refusal,
    _runtime_refusal,
)
from .. import ui, words
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

# Every key this screen reads: the route's own (`ROUTE_KEYS`) and the four above.  It is
# the list a link is allowed to carry, and it is stated rather than read off the request
# because `_url`'s route whitelist is defeated for *every* route by `ROUTE_KEYS["/"]` -
# a trailing slash matches every path, so a link written from a check that holds
# `origin=any` puts that condition in the address bar of a page that reads none of it.
READS = ("api", "state", "job", "text", "limit", *PAGE_KEYS)


def worker(view) -> str:
    """The `/worker` screen: the loop, its file, the queue, and what it finished."""
    w = view.rows["worker"]
    queue = list(view.rows["queue"])
    picked = _picked(view)
    state = _state_in_force(view)
    mine = [one for one in view.rows["ledger"] if one["source"] == WORKER_SOURCE]
    return (
        _asked(view, queue, state)
        + _bar(view, queue, picked, state)
        + _other_api(view)
        + _start(view, w, queue, picked)
        + _state_file(view, w)
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
    """The one GET form: api, state, job, limit, and the mode the command will run in.

    Three of the four controls the old page had are here unchanged, and the fourth
    (`job`) is a select over the names this answer carries rather than the board's free
    box: `job_node_rows` matches a job's *name*, so a box whose placeholder promises
    "node id or name" would silently answer nothing for half of what it offers.  The
    names come from the rows the page is showing (the old page's rule), so a name can
    never be offered that the table below it would not draw.

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
        + ui.field(both(view.lang, "filter.name"), ui.select(
            "job", [("", both(view.lang, "state.any"))] + [(one, ui.esc(one)) for one in names],
            view.check.job), "w-lg")
        + ui.field(both(view.lang, "filter.rows"), ui.number_input(
            "limit", view.check.limit, 1, MAX_LIMIT, stops=LIMITS), "w-sm")
        + ui.field(both(view.lang, "filter.mode"), ui.seg(
            "mode", [(value, both(view.lang, f"mode.label.{value}")) for value in MODES], picked["mode"]),
            "w-md")
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


def _hidden(view, picked) -> list:
    """Every key the bar submits without drawing a control for it.

    Two sources, and neither is optional.  The route's own filter keys that this bar
    draws no box for (`text`, and any the reader set by hand) come from the request's
    query; the worker's four arguments come from the page state read above - by name,
    because what that dict holds beside them is this page's own bookkeeping (the raw
    `?since=` a refusal is reported from) and not a key any route reads.  A GET form has
    no whitelist - the browser submits what is in the form - so the page states the keys
    rather than handing over everything it happens to hold.
    """
    allowed = set(ROUTE_KEYS.get("/worker", ()))
    drawn = {"api", "state", "job", "limit", "mode"}
    found = [(key, value) for key, value in view.check.to_query()
             if key in allowed and key not in drawn]
    found += [(key, picked[key]) for key in PAGE_KEYS if key not in drawn and picked.get(key)]
    return found


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
    """The four worker arguments this request states, as the form and the command read them.

    `since` is normalised through `forms._iso_stamp`, the one judge of that flag's shape
    (`Gui.command` refuses a stamp it cannot read, and `poller.iso_ago()` would silently
    read one it cannot parse as "now" - the 15-minute window the flag exists to widen).  The
    raw value is kept beside it so the button can be blocked by the sentence the POST
    would have answered with, instead of quietly running a narrower window.
    """
    since = _named(view.check, "since")
    return {
        "mode": _named(view.check, "mode", MODES) or MODES[0],
        "platform": _named(view.check, "platform") or DEFAULT_DEVICE,
        "runtime": _named(view.check, "runtime") or DEFAULT_LAB,
        "since": _iso_stamp(since),
        "since_raw": since,
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
            + ui.spread() + stop + "</div>")


def _rails(view, queue, picked) -> str:
    """The command's three other arguments, one row of links each.

    A rail and not a select box, and that is the old page's argument kept: the value has
    to be visible in the URL, because the argv printed under the button is built from the
    URL - a box whose value lived only in the browser could show one command and run
    another.  A value in force that the rows do not carry is offered as its own link
    (`ui.select`'s `(current)` rule): a reader who arrived on a hand-edited URL has to be
    able to see, and to leave, the value their button will use.
    """
    platforms = sorted({one["platform"] for one in queue if one["platform"]} | {DEFAULT_DEVICE})
    runtimes = sorted({one["runtime"] for one in queue if one["runtime"]} | {DEFAULT_LAB})
    return (
        _rail(view, "word.platform", _choices(platforms, picked["platform"]),
              picked["platform"], "platform", _keep(picked, "platform"),
              off={one: _platform_refusal(one, view.lang) for one in platforms})
        + _rail(view, "word.runtime", _choices(runtimes, picked["runtime"]),
                picked["runtime"], "runtime", _keep(picked, "runtime"),
                off={one: _runtime_refusal(one, view.lang) for one in runtimes})
        + _since(view, queue, picked)
        + _pairs(view, queue, picked)
    )


def _choices(values, current) -> list:
    """One `(label, value)` per name, with the value in force added when it is absent."""
    found = [(ui.esc(one), one) for one in values]
    if current and current not in values:
        found.append((ui.esc(current), current))
    return found


def _keep(picked, name: str) -> list:
    """The page keys a rail link has to carry: the other three, and nothing else.

    A rail sets one argument of the command; a link that dropped the other two would
    answer about a different worker than the page it was pressed on, which is the whole
    reason these keys are page state rather than boxes inside a button's form.
    """
    return [(key, picked[key]) for key in PAGE_KEYS if key != name and picked.get(key)]


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

    Two choices and a free box is not one of them: the flag is read by
    `poller.start_cursor()` *before* the cursor in the state file, and a stamp the poller
    cannot parse would be read as "now" - the fifteen-minute window the flag exists to
    widen.  So the rail offers the flag left out, or the oldest `created` in this answer
    (the value that puts the whole queue inside the window), and a `?since=` the rail does
    not offer is printed as its own pill so the reader can see - and leave - the value
    their button will use.  The badge beside it says what the flag outranks, which is the
    one thing worth knowing before pressing it.
    """
    stamps = sorted({one for one in (_iso_stamp(str(row["created"] or "")) for row in queue)
                     if one})
    choices = [(both(view.lang, "worker.since_cursor"), "")]
    if stamps:
        choices.append((ui.esc(stamps[0]), stamps[0]))
    if picked["since"] and all(picked["since"] != value for _label, value in choices):
        choices.append((ui.esc(picked["since"]), picked["since"]))
    badge = (f'<span class="pill idle" {words.attr(view.lang, "title", "worker.since_hint")}>'
             f'{both(view.lang, "worker.since_badge")}</span>')
    return _rail(view, "filter.since", choices, picked["since"], "since",
                 _keep(picked, "since"), badge=badge)


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


# ------------------------------------------------------------------ the state file
def _state_file(view, w) -> str:
    """The poller's own file, displayed and not interpreted.

    The path is the row's first label (the board draws it that way: the file *is* the
    subject), and the warning under the table is `worker.cursor_note` - the board's
    sentence, which this console keeps word for word because it is the difference between
    two numbers a reader will otherwise read as one.
    """
    pairs = [
        (ui.code(w["state_file"]), ""),
        (both(view.lang, "col.cursor"), ui.esc(w["cursor"]) if w["cursor"] else ui.DASH),
        (both(view.lang, "col.seen"), f'<b>{ui.esc(w["seen"])}</b>'),
        (both(view.lang, "col.pending"), ui.esc(w["pending"])),
    ]
    return ui.panel("page.worker.state_title",
                    ui.kv(pairs) + ui.hint(view.t("worker.cursor_note")), lang=view.lang)


# --------------------------------------------------------------------- the queue
def _queue(view, queue) -> str:
    """The API's job nodes: one row each, with the loop's own `seen` behind `claimed`.

    Nine columns and no `key` on any of them: `key` is what the header *sorts by*, and
    `/worker` reads no `sort` (`ROUTE_KEYS`), so a header drawn `sortable` here would
    promise an order that no link can ask for.  `claimed` is the column this panel exists
    for - `Gui.job_node_rows` answers it against the state file's `seen` list, which is
    why the page prints the row's own word instead of comparing anything itself.
    """
    cols = [
        ui.Col("word.node_id", draw=lambda one: ui.code(one["node_id"])),
        ui.Col("col.name", draw=lambda one: ui.code(one["name"])),
        ui.Col("word.state", kind="c", draw=lambda one: ui.pill(one["state"], lang=view.lang)),
        ui.Col("word.result", kind="c",
               draw=lambda one: ui.pill(one["result"], lang=view.lang) if one["result"] else ui.DASH),
        ui.Col("word.platform", draw=lambda one: ui.code(one["platform"])),
        ui.Col("word.runtime", draw=lambda one: ui.code(one["runtime"])),
        ui.Col("word.created", kind="n", draw=lambda one: _stamp(one["created"])),
        ui.Col("col.claimed", kind="c", draw=lambda one: _claimed(view, one)),
        ui.Col("col.definition", kind="c",
               draw=lambda one: both(view.lang, "state.yes") if one["definition"] else both(view.lang, "state.no")),
    ]
    empty = view.t("empty.queue_empty", state=ui.esc(_state_in_force(view)),
                   job=ui.esc(view.check.job or view.t("state.any")))
    return ui.panel("worker.queue", ui.table(cols, queue, empty=empty, lang=view.lang),
                    flush=True, lang=view.lang)


def _claimed(view, one) -> str:
    """One row's claim state: the design's green word, or the muted one.

    The words are the column's own (`col.claimed`, `state.no`): the board's cells say
    "claimed" and "not claimed", and the catalogue carries the header's word for one of
    them and the plain negative for the other, which under a header that already asks
    "claimed?" reads as the same answer.  What the cell must not do is decide: `claimed`
    is `Gui.job_node_rows`'s own comparison against the loop's `seen` list.
    """
    if one["claimed"]:
        return ui.tick(True, label_html=both(view.lang, "col.claimed"), lang=view.lang)
    return f'<span class="muted">{both(view.lang, "state.no")}</span>'


def _other_api(view) -> str:
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
        links.append(f'<a href="{ui.esc(_page_url(view, "", api=key))}" '
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
    on this workspace the ledger holds five of them.
    """
    cols = [
        ui.Col("col.when", kind="n", draw=lambda one: _stamp(one["when"], seconds=True)),
        ui.Col("word.build", draw=lambda one: _build_cell(view, one)),
        ui.Col("word.test", draw=lambda one: ui.code(one["test"])),
        ui.Col("col.verdict", kind="c", draw=lambda one: ui.pill(one["verdict"], lang=view.lang)),
        ui.Col("col.took", kind="n", draw=lambda one: ui.DASH),
        ui.Col("col.detail", kind="wrapc", draw=lambda one: ui.esc(one["detail"])),
    ]
    return ui.panel("worker.done_here", ui.table(cols, mine, lang=view.lang),
                    flush=True, lang=view.lang)


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


def _stamp(text, seconds: bool = False) -> str:
    """A record's ISO-8601 stamp as the design's two-tone cell: the day, then the time.

    Split rather than reprinted: the value on screen is the value on disk (`05-i18n-prose`'s
    rule for a child process's own words), and the two tones are the board's own markup -
    the day in the cell's ink, the clock muted beside it.  An empty stamp is the design's
    dash, because a record with no timestamp is not a record at midnight.
    """
    whole = str(text or "")
    if not whole:
        return ui.DASH
    day, _sep, rest = whole.partition("T")
    clock = rest.rstrip("Z")[:8 if seconds else 5]
    if not clock:
        return ui.esc(day)
    return (f'<span class="nowrap">{ui.esc(day)}'
            f'<span class="muted"> {ui.esc(clock)}</span></span>')
