# SPDX-License-Identifier: LGPL-2.1-or-later
"""The worker page (`/worker`): the jobs a pull-lab worker can claim.

The queue as the API has it (`job_rows`, `job_node_rows`), the (platform, runtime)
pairs it actually holds (`_claim_pairs` - biggest first, because those are the ones
worth running), and the command line `pull_worker.py` will run, printed by `command()`
and never written out twice.  `_empty_queue` says why the table is empty in the queue's
own words, which are not `/`'s: a worker page with nothing to claim is a normal answer."""

import html
from collections.abc import Iterable, Mapping
from typing import Any

from ... import layout
from ...i18n import DEFAULT_LANG, t
from ...tests import DEFAULT_DEVICE, DEFAULT_LAB
from ..fields import _quick
from ..forms import _iso_stamp
from ..models import Filter
from ..schema import (
    JOB_STATES,
    MODES,
    QUEUE_ROWS,
    _labels,
    _platform_refusal,
    _runtime_refusal,
)
from ..urls import _url
from ..values import _short
from ..widgets import (
    _action_bar,
    _badge,
    _cell,
    _filter_bar,
    _h2,
    _pill,
    _row,
    _select,
    _table,
)


class WorkerMixin:
    # --- /worker ------------------------------------------------------------

    def _worker(self, check: Filter, lang: str = DEFAULT_LANG, state: str = "", mode: str = "",
                platform: str = "", runtime: str = "", since: str = "") -> str:
        """The queue the worker claims from, what it has handled, and the commands to start it.

        The worker's own four arguments (mode, platform, runtime, since) are page keys
        rather than boxes inside the button's form: a box the command line cannot
        show is a box that can disagree with the command line.  They are offered
        as one link per value (`_quick`), so the URL always says which command the
        button below it will run.  `since` is not a claim filter but the window the
        worker's own cursor starts from (`--since`, `poller.start_cursor()`), and its
        rail offers the queue's own oldest job - the value that reaches the rows this
        table is showing (`_since_rail`; the badge beside it says what the flag can
        and cannot do).

        **Its bar is `_filter_bar` and its controls are its own, which is a decision
        and not an oversight.**  `/`, `/jobs` and `/analysis` draw `_build_axes` because
        they all select *builds*: same rows, same predicate (`Filter.accepts`), same
        fourteen questions.  This page selects what a **resident process claims** - the
        queue this host can take work out of - and its four keys are not filter fields
        at all (`ROUTE_KEYS["/worker"]` is state, job, text, limit, mode, platform,
        runtime, since, api): a tree, an arch or a day window is not a property of a
        claimable job, and the API paths for those axes are declared for `kind=kbuild`
        alone (`API_FILTERS`), so asking a `kind=job` query for `data.arch` is a full
        scan this page must never send.  So it stays a lesser copy of nothing: the same
        `_filter_bar`, the same strip, the same hidden-field rule, with the four
        controls the page really reads.

        The platform rail prints every name the queue has and links only the ones a
        worker started here could run: a platform it would claim a job for and then
        boot with the wrong device is marked with that reason (`_platform_refusal`,
        `_quick(off=…)`) instead of being a link to a run that fails later, and a URL
        that names one anyway gets the reason in the button's place
        (`_action_bar(blocked=…)`).  The runtime needs no such marking - it is a claim
        filter and nothing more - so its rail only withholds names the vendored config
        does not declare, which `command()` would refuse.
        """
        # One read, two uses - which is what the comment above always claimed.  The
        # table is the first `check.limit` rows of the same ordered answer the boxes
        # are built from (`getjob(limit=50)` returns exactly `getjob(limit=200)[:50]`,
        # because the order is the API's and nothing between them sorts), so the
        # second read bought nothing and cost a second `/count?kind=job` - 4,786,841
        # nodes - plus a second 340 KB page (`docs/gui-rework/01-perf.md` §F4).  With
        # no `?state=` in force the two reads really were the byte-identical query,
        # which is why the page paid twice.
        #
        # What the boxes offer is now the rows this page is showing, state filter and
        # all, instead of the whole unfiltered queue: the same answer feeds both, so
        # a name can no longer be offered that the table below it would not draw.
        # The failure travels as `note` for the one read there is, and an API that
        # did not answer is still not a queue that is empty (`_empty_queue`).
        # **One read, and the page's own question is about the work.**  `state` with no
        # value in the URL read the *whole* queue, so `/worker` listed 200 nodes whose
        # state was `done` - the history of a pipeline that has been running for months -
        # and "现在可领取 0 个" beside a `200 rows` line was both true and useless.  What a
        # worker page is about is what a worker can claim, so the read is
        # `state=available` unless the reader asked for another state, and the claim
        # count below is taken from that same answer with the engine's own predicate.
        all_nodes, note = self.job_node_rows(check, state, QUEUE_ROWS)
        nodes = all_nodes[:check.limit]
        worker_state = self.worker_state()
        # `remote.rows` is the "&mdash; rows {n}" tail of a query line, spelled once
        # for every page that asks one; a failure replaces it with a whole sentence,
        # and the dash in front of either is the line's own punctuation.  The noun and
        # the number are separate words because the catalogue has no plural rule that
        # could agree `row` with an arbitrary count, and `row(s)` is not a word in
        # either language (`05-i18n-prose.md` §A.4; `accept.py`'s W3 greps for it).
        asked = ("&mdash; " + t(lang, "worker.no_answer", note=html.escape(note))
                 if note else t(lang, "remote.rows", n=len(nodes)))
        picked = {
            "mode": mode if mode in MODES else MODES[0],
            "platform": platform or DEFAULT_DEVICE,
            "runtime": runtime or DEFAULT_LAB,
            # **Normalised here, refused below.**  `since` is a page key, so every link
            # on this page carries it and every link must carry a value the worker can
            # really be started from: the canonical stamp `_iso_stamp()` returns, or
            # nothing at all.  What the URL said is kept one line down - a value the
            # page drops *and does not report* is the silent `?test=kbuild` of
            # `04-actions.md` §5a, and this is the same failure with a hand-typed date.
            "since": _iso_stamp(since),
        }
        # The worker page is the one screen that can show two queues at once: the table
        # below is drawn from this request's `?api=` key, and the live panel beside it
        # lists the activities with their own argv - among them a `pull_worker.py` that
        # named another base.  The two are not contradictory, and nothing on the page
        # said so: the operator read `asked the API: https://api.kernelci.org … rows 0`
        # above a worker started with `--api-url http://127.0.0.1:8001` as "the worker
        # never claimed anything", when the queue it was claiming from is simply not
        # the one on screen.  `worker_bases` is the fact; `_other_api` is the note and
        # the link that re-points this page's key at it.
        here = self.api_base(check)
        others = [(one, self.apis.key(one)) for one in self.worker_bases() if one != here]
        # The two rails are the rows this page is showing (`all_nodes`), which is the
        # floor: a name the queue really carries is worth printing even when the
        # vendored config does not declare it, and a name neither carries is not this
        # page's business (`_offered` still refuses it if a URL brings one).  What is
        # offered as a *link* is decided per name by `_platform_refusal` /
        # `_runtime_refusal`, which are built on the very lists `command()` accepts -
        # so a pill and the button behind it cannot disagree, and the platform a
        # worker started here would boot with the wrong device is shown and not
        # clickable (`worker.platform_off`), instead of being a run that fails later.
        platforms = sorted({one["platform"] for one in all_nodes if one["platform"]}
                           | {DEFAULT_DEVICE})
        runtimes = sorted({one["runtime"] for one in all_nodes if one["runtime"]} | {DEFAULT_LAB})
        off_platforms = {one: reason for one in platforms
                         if (reason := _platform_refusal(one, lang))}
        off_runtimes = {one: reason for one in runtimes
                        if (reason := _runtime_refusal(one, lang))}
        # What the button below would claim, and whether it may be pressed at all: the
        # refusal is about the *platform* the bar is holding, so it is asked once here
        # and used for both the rail and the bar - and `?since=` is the same kind of
        # fact for the window's own value.  `poller.iso_ago()` treats a stamp it cannot
        # parse as "now", so a value passed through would be *silently* replaced by the
        # 15-minute window the flag exists to widen: refused here, in the button's own
        # slot (`_action_bar(blocked=…)`), rather than printed into an argv that ignores
        # it.  Both reasons live in one slot because a bar has one button: the first
        # condition that cannot work is the one that takes its place.
        held = (_platform_refusal(picked["platform"], lang)
                or (t(lang, "error.not_a_stamp", key="since", value=repr(since))
                    if since and not picked["since"] else ""))
        # The queue's own query line, written the way `<remote_query>` writes the
        # build one: the API this page is on first, then the machine-readable
        # question.  `/worker` composes its own because its keys are not a `Filter`.
        queue = t(lang, "remote.query_from", api=html.escape(self.api_base(check)),
                  query=f'kind=job state={html.escape(state or "any")} '
                        f'name={html.escape(check.job or "any")}')
        body = [
            ('<p class="query">' + t(lang, "remote.asked") + ": "
             + f"<code>{queue}</code> {asked}</p>"),
            _filter_bar("/worker", [self._api_field(check, lang=lang),
                                    _select("state", JOB_STATES, state, t(lang, "word.state"),
                                            labels=_labels("job_state", lang), lang=lang),
                                    _select("job", ("", *sorted({one["name"] for one in all_nodes
                                                                 if one["name"]})),
                                            check.job, t(lang, "filter.name"), lang=lang),
                                    self._limit_field("/worker", check,
                                                      keep=sorted(picked.items()), lang=lang)],
                        check, rendered=("api", "state", "job", "limit"),
                        # `since` rides with the claim filters and not with the four
                        # controls: it is not a property of the query the box submits
                        # (it selects no rows), it is an argument of the command the
                        # button below will run - and a form that dropped it would
                        # hand the worker a different window than the bar promised.
                        keep=[("mode", picked["mode"]), ("platform", picked["platform"]),
                              ("runtime", picked["runtime"]), ("since", picked["since"])],
                        # The note sits here and not in the shell's banner list: it is
                        # not a failure of this request (`_shell`'s notes are), it is a
                        # fact about the queue below it - and it goes *inside* the bar
                        # area, directly over the table it is about.
                        notes=[_other_api(others, check, lang)], lang=lang),
            _table((t(lang, "word.node_id"), t(lang, "filter.name"), t(lang, "word.state"),
                    t(lang, "word.result"), t(lang, "word.platform"), t(lang, "word.runtime"),
                    t(lang, "word.created"), t(lang, "col.definition"), t(lang, "col.claimed")),
                   [_row((_cell(f'<code>{html.escape(_short(one["node_id"]))}</code>', "id"),
                          _cell(html.escape(one["name"]), "wrap"),
                          _cell(_pill(one["state"], "job")),
                          _cell(_pill(one["result"], "idle")),
                          _cell(html.escape(one["platform"] or "-")),
                          _cell(html.escape(one["runtime"] or "-")),
                          _cell(html.escape((one["created"] or "-")[:16])),
                          _cell(t(lang, "state.yes") if one["definition"]
                                else t(lang, "state.no")),
                          _cell(t(lang, "state.yes") if one["claimed"] else t(lang, "state.no"))))
                         for one in nodes],
                   empty=_empty_queue(note, check, state, lang), cls="queue"),
            _h2(t(lang, 'page.worker.state_title'), hint=t(lang, 'page.worker.state_sub')),
            _table((t(lang, "col.file"), t(lang, "col.cursor"), t(lang, "col.seen"),
                    t(lang, "col.pending")), [
                _row((_cell(f'<code>{html.escape(layout.worker_state())}</code>', "wrap"),
                      _cell(html.escape(str(worker_state.get("timestamp") or "-"))),
                      _cell(str(len(worker_state.get("seen") or [])), "num"),
                      _cell(str(len(worker_state.get("pending") or {})), "num")))]),
            _h2(t(lang, 'page.worker.start_title'), t(lang, 'page.worker.start_sub')),
            # **Where the work actually is.**  The default machine pair claims nothing on
            # this queue (every available job is on another lab), so a reader who starts
            # the worker here is told `nothing to claim` - true, and no help at all in
            # finding the pair that *would* work.  This line counts the available queue by
            # (platform, runtime), biggest first, and every count is a link that sets both
            # boxes: the reader sees there is work, and one press points the worker at it.
            _claim_pairs(all_nodes, check, picked, "/worker", lang),
            _action_bar("worker", picked, t(lang, "btn.start_worker"),
                        # **The argv is given the value the page refused, not the empty one
                        # it normalised to.**  `picked` is what every link and hidden field
                        # must carry - a value a worker can really be started from - so a
                        # stamp this page cannot honour leaves it and is reported by the
                        # button's own slot.  The command line is the other half of that
                        # promise: it prints what the button would run, and an argv with
                        # the flag quietly dropped under a bar that is refusing it is a
                        # command the URL did not ask for.  Handing `command()` the raw
                        # value makes it raise the same refusal `platform` raises, which
                        # `_argv_of` prints in this slot - so both refusals read the same
                        # way, and neither can print a command it will not run.
                        argv=self._argv_of("worker",
                                           {**picked, "since": picked["since"] or since},
                                           lang, api=check.api),
                        # **What this button would claim, before it is pressed.**  The
                        # claim rule lives in the engine (`Kjob.claimable` + the platform
                        # test), so this is the same predicate the worker applies, counted
                        # over the rows this page already read - and when it is zero the
                        # reader has not started a worker that will find nothing and then
                        # be told it `failed` (the operator's 「轮转方面 worker 不能用」 was
                        # partly that: a run that claimed nothing looked like a run that
                        # broke).  `hint` carries the sentence the badge replaces.
                        note=_badge(t(lang, "worker.would_claim",
                                      n=sum(1 for one in all_nodes
                                            if one["platform"] == picked["platform"]
                                            and one["runtime"] == picked["runtime"]
                                            and one["state"] == "available")),
                                    title=t(lang, "worker.start_hint")),
                        inner=(_quick("mode", "/worker", check, picked["mode"],
                                      [(t(lang, "mode.label." + one), one) for one in MODES],
                                      lead=t(lang, "filter.mode"),
                                      keep=[("platform", picked["platform"]),
                                            ("runtime", picked["runtime"]),
                                            ("since", picked["since"])], lang=lang)
                               + _quick("platform", "/worker", check, picked["platform"],
                                        [(one, one) for one in platforms],
                                        lead=t(lang, "word.platform"),
                                        keep=[("mode", picked["mode"]),
                                              ("runtime", picked["runtime"]),
                                              ("since", picked["since"])], lang=lang,
                                        off=off_platforms)
                               + _quick("runtime", "/worker", check, picked["runtime"],
                                        [(one, one) for one in runtimes],
                                        lead=t(lang, "word.runtime"),
                                        keep=[("mode", picked["mode"]),
                                              ("platform", picked["platform"]),
                                              ("since", picked["since"])], lang=lang,
                                        off=off_runtimes)
                               # The window last, because it is not a claim filter: the
                               # three rails above say *what* this worker would take, and
                               # this one says *how far back* it looks for it.
                               + _since_rail(all_nodes, picked, check, lang)),
                        # A bar whose own conditions are a command that cannot work is
                        # not a button: the reason takes its place (`_action_bar`'s
                        # `blocked`), and the argv stays printed under it.  This is the
                        # only path left to a refused platform - the rail does not link
                        # it - and it is a hand-edited URL, which this page answers with
                        # an explanation rather than with a run that claims an x86 job
                        # and boots it as riscv64; `?since=` is the second such value
                        # (above).
                        blocked=held, lang=lang, api=check.api),
        ]
        return self._shell("worker", "".join(body), check, [note], lang, route="/worker",
                           lang_keep=[("state", state), *picked.items()])


def _since_rail(rows: Iterable[dict[str, Any]], picked: Mapping[str, str], check: "Filter",
                lang: str = DEFAULT_LANG) -> str:
    """`--since` as a rail: no flag, or the queue's own oldest job - and the badge that says why.

    **The escape hatch the page did not offer.**  A worker's window is
    `[poller.start_cursor() - 900s, now]`, and `start_cursor()` is `--since` when the
    operator gave one, else the cursor in the state file, else now.  `deploy/stack.sh
    --seed` writes job nodes carrying the *upstream build's* timestamps - nodes show
    `created=2026-09-20T08:20` while the stack's containers started `2026-09-21T05:03`
    - so on a seeded stack the `available` jobs sit behind the cursor the state file
    already holds, the API still lists every one of them, and the table shows them as
    `claimed: no` for ever: the worker's feed is asked from a window that opens after
    them.  Widening that window is what `--since` is for (`start_cursor` reads it
    *first*, so it is the argument and not the file that decides), and until now the
    only way to pass it was to hand-edit an argv.

    Two choices and not a free box, for the reason this page's other three arguments
    are rails: a control that is not in the URL cannot be printed in the command line
    under the button, and a command line that cannot show what the box holds is the
    one thing a bar here may not do.  What the second choice *is* comes from the rows
    this page already read - the oldest `created` in the queue's own answer, which is
    the value that puts the whole table inside the worker's window - and never from a
    clock: a stamp this page invented (`now - 1 day`) would reach jobs the reader
    cannot see and cannot select.

    The stamp is normalised (`_iso_stamp`) before it is offered, because what a link
    carries is what `command()` will accept: the API's nodes carry microseconds in
    their `created`, and a pill whose value the button below refused - or worse, a
    value the worker's own `iso_ago()` would read as "now" - would be a link that
    cannot keep its promise.

    `_claim_pairs`' rule for "nothing to add": a rail whose only choice is the one in
    force is not drawn.  Here that is an empty queue with no `since` in the URL - a
    page with no job to reach and no window stated has nothing to say about windows -
    and the badge goes with it, so the tooltip cannot outlive the control it explains.
    """
    stamps = set()
    for one in rows:
        stamp = _iso_stamp(str(one.get("created") or ""))
        if stamp:
            stamps.add(stamp)
    choices = [(t(lang, "worker.since_cursor"), "")]
    if stamps:
        choices.append((min(stamps), min(stamps)))
    # A `?since=` the rail does not offer is still in force: printed as its own pill so
    # the reader can see what the button will run, and so the link that sets it is not
    # the only way back to "no --since" (a value in force is `_quick`'s `current`).
    if picked.get("since") and all(picked["since"] != value for _, value in choices):
        choices.append((picked["since"], picked["since"]))
    if len(choices) < 2:
        return ""
    return (_quick("since", "/worker", check, picked.get("since", ""), choices,
                   lead=t(lang, "filter.since"),
                   keep=[("mode", picked["mode"]), ("platform", picked["platform"]),
                         ("runtime", picked["runtime"])], lang=lang)
            # **What the flag outranks**, in the tooltip the badge exists for: the
            # window opens at `--since`, so a cursor already on disk does not win -
            # which is the whole reason the pill can reach a job the cursor walked
            # past, and the whole reason a reader wants to know it (`05-i18n-prose.md`
            # §B.1 class 4: a limitation belongs in the `title=`).
            + _badge(t(lang, "worker.since_badge"), title=t(lang, "worker.since_hint")))


def _other_api(others: Iterable[tuple[str, str]], check: "Filter",
               lang: str = DEFAULT_LANG) -> str:
    """The note that says a worker is claiming from another API - `""` when they agree.

    `others` is `(base, key)` per base the live panel's worker rows name and this page
    does not read (`Gui.worker_bases`), and each one becomes a link that re-points this
    page's `api` key at it - so the queue table below then shows the queue that worker
    is really taking jobs out of, with the rest of the reader's conditions kept.

    The link's *text* is the base and its `title=` is what pressing it does: a note
    that has to explain a control is prose, and the fact a reader needs on every look
    is which queue they are looking at.  The `key` and not the base goes into the URL
    (`Apis.key`), so a named base stays named in the address bar exactly as the filter
    box would have written it, and an unnamed one is spelled out - the two spellings
    `Apis.base()` resolves back to the same base.

    Several bases are joined and not summarised: they are what the panel shows, and
    "one of these" would be a sentence the reader has to go back to the panel to
    resolve.  When the bases agree with the page there is nothing here at all - the
    whole point of the note is the disagreement, and a note that always appears is a
    note nobody reads.
    """
    links = " ".join(
        f'<a href="{html.escape(_url("/worker", check, lang=lang, api=key))}"'
        f' title="{html.escape(t(lang, "worker.other_api_act"))}">'
        f'<code>{html.escape(base)}</code></a>'
        for base, key in others)
    return t(lang, "worker.other_api", link=links) if links else ""


def _claim_pairs(rows: Iterable[dict[str, Any]], check: "Filter", picked: Mapping[str, str],
                 route: str, lang: str = DEFAULT_LANG) -> str:
    """Which (platform, runtime) pairs the available queue actually has, biggest first.

    `/worker` defaults to `qemu-riscv64` × `pull-labs-riscv` - this deployment's own
    machine - and on the public queue that pair claims nothing: every available job belongs
    to another lab.  The page said so honestly (`现在可领取 0 个`) and left the reader with a
    list of sixty platform names and ten lab names to search by hand for the one that has
    work.  This is that search, done: the available rows counted by pair, and each count a
    link that sets both boxes (`_url` with the worker's own two page keys), so one press
    points the worker at a queue that has something in it - where this host could run that
    pair at all (the last paragraph).

    Rows the page already read - the same answer the table and the badge use, so the three
    cannot disagree.  `mode` and `since` ride along like any other page key: pressing a
    pair is a choice about *which queue*, and it must not quietly reset *what window* the
    worker the reader is about to start will look back through.

    A pair whose platform this host cannot boot is **shown and not linked**: the count is
    true (the queue really has that work) and the link is a promise this deployment cannot
    keep (`_platform_refusal`, the same reason the platform rail carries).  Dropping the
    row would hide work that is there; linking it would be the button that fails later.
    """
    counts: dict[tuple[str, str], int] = {}
    for one in rows:
        if str(one.get("state") or "") != "available":
            continue
        pair = (str(one.get("platform") or ""), str(one.get("runtime") or ""))
        if all(pair):
            counts[pair] = counts.get(pair, 0) + 1
    if not counts:
        return ""
    wanted = (picked.get("platform", ""), picked.get("runtime", ""))
    if list(counts) == [wanted]:
        return ""                      # the pair in force is the only one: nothing to add
    parts = []
    for (platform, runtime), many in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        text = t(lang, "worker.pair", platform=html.escape(platform),
                 runtime=html.escape(runtime), n=many)
        reason = _platform_refusal(platform, lang)
        if reason:
            parts.append(f'<span class="off" aria-disabled="true" '
                         f'title="{html.escape(reason)}">{text}</span>')
            continue
        current = " aria-current=\"true\"" if (platform, runtime) == wanted else ""
        href = _url(route, check, lang=lang, platform=platform, runtime=runtime,
                    mode=picked.get("mode", ""), since=picked.get("since", ""))
        parts.append(f'<a href="{html.escape(href)}"{current}>{text}</a>')
    return ('<p class="quick"><span class="lead">'
            + html.escape(t(lang, "worker.pairs_lead")) + ":</span>"
            + " ".join(parts) + "</p>")


def _empty_queue(note: str, check: Filter, state: str, lang: str = DEFAULT_LANG) -> str:
    """Why the queue table is empty: same two facts as `_empty_remote`, in the queue's words."""
    if note:
        return t(lang, "empty.queue_no_answer", note=html.escape(note))
    return t(lang, "empty.queue_empty", state=html.escape(state or "any"),
             job=html.escape(check.job or "any"))
