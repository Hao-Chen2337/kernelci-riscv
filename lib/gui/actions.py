# SPDX-License-Identifier: LGPL-2.1-or-later
"""The buttons: the command line each one runs, and the activity it starts.

`command()` is the only place an argv is built in this program, and it builds exactly
what an operator would type: every value comes from a select box or a ticked row, every
flag is one the entry point's own parser declares, and the two clamps the page's own
query went through are applied again because these values become the argv of a real
process.  `start()` runs it as a `Run` (`lib/run.py`) under the one-writer lock
(`WRITERS`), and the activity's own label is read off that argv (`_what_of`) and never
off the form.

`_argv_of`/`_argv_of_ticked` print the same argv under the button, so the bar and the
process cannot disagree; `cancel`, `log` and `status`/`state_poll` are what the page's
poll reads while something runs.

`_one_tree` is the other side of the same knowledge: a button whose command takes one
tree (`run_latest.py`, `runday.py` and `table.py index` each declare a single `--tree`,
which `command()` reads with `_named`) cannot be offered honestly against a filter that
names two, so it says why in its `title=` instead of being clickable and refusing.  It
moved here from the retired filter-bar module because the fact it states is about this
argv."""

import os
import sys
import time
from collections.abc import Iterable, Mapping
from typing import Any

from .. import errors, poller, repo_root, sink
from .. import run as run_mod
from ..i18n import DEFAULT_LANG, t
from ..tests import DEFAULT_DEVICE, DEFAULT_LAB, DEFAULT_TESTS, TESTS
from .forms import (
    _chosen,
    _clamp,
    _first,
    _flag,
    _iso_stamp,
    _named,
    _names,
    _numbers,
    _offered,
    _pairs,
    _parameter_url,
    _ticks,
    _token,
)
from .models import Filter
from .schema import (
    ACTIONS,
    KINDS,
    MAX_DAYS,
    MAX_LIMIT,
    MODES,
    NO_WINDOW,
    WRITERS,
    _worker_platforms,
    _worker_runtimes,
)
from .server import _state_digest
from .values import _short

# The action that does each of the three steps a smart press can take, by the step a
# ticked row is in (`_smart` reads the step off the copy).  These are `ACTIONS`' own
# names and not a second spelling of the commands: `command()` stays the only place an
# argv is built, so the line this press runs is byte for byte the line the bar's own
# buttons would have run for the same rows.
SMART_STEPS = {1: "index_pull", 2: "pull", 3: "run"}

# The clauses a smart press's answer can put a ticked row in, in the order they are
# printed: the rows it acts on first (register, pull, run), then the one that says a
# pull is being retried, then the rows that wait.  One tuple, so the order cannot be
# decided twice - the answer is one line and its shape is the whole of what it says.
#
# `will_run` and `will_rerun` are one slot and not two: `_smart_group` answers one or
# the other for a phase-3 row (`redo`), never both, so a row cannot be in a clause this
# tuple does not name - which is exactly what printed nothing at all the first time
# `will_rerun` was added and left out of here.
SMART_ORDER = ("smart.will_register", "smart.will_pull", "smart.pull_failed",
               "smart.will_run", "smart.will_rerun", "smart.waits_run")

# The first sentence of that answer, by the step this press takes - the number in it
# is this press's own rows and not the ticks': "2 of 10" is what tells a reader that
# the other eight are waiting rather than forgotten, before the list says which.
SMART_PLANS = {1: "smart.plan_register", 2: "smart.plan_pull", 3: "smart.plan_run"}


def _smart_group(step: int, phase: int, failed: bool, redo: bool = False) -> str:
    """Which clause one ticked row belongs in - `_smart`'s steps and phase.

    `step` is what the row needs (1: a card, 2: bytes, 3: a run), `phase` is the step
    this press takes (the earliest any ticked row needs) and `failed` is the newest
    act's own `error`, which is why a retry reads differently from a first pull.

    Three steps and one phase make five clauses and not nine.  A step-1 row is always
    in a phase-1 press - it is what chose that phase.  A step-2 row is acted on by
    phases 1 and 2 alike (`index-pull` pulls the carded ids it is handed).  A step-3
    row is run by phase 3, and under the other two it is the row that waits - said, so
    that a reader who ticked it knows the press saw it.

    `redo` is the one thing that changes what *running* a row means, so a phase-3 row
    of a redo press is in a clause of its own: `smart.will_run` promises the ledger
    decides what still has to run, and under `--redo` nothing decides - the pair runs.
    """
    if step == 3:
        if phase != 3:
            return "smart.waits_run"
        return "smart.will_rerun" if redo else "smart.will_run"
    if step == 2:
        return "smart.pull_failed" if failed else "smart.will_pull"
    return "smart.will_register"


def _smart_note(rows: list[tuple], phase: int, run_id: str, lang: str,
                redo: bool = False) -> str:
    """One line: what this press takes on, then every ticked row under its own clause.

    One line and not a paragraph: the answer is written into the bar's `status` span
    (`script.py`'s `barStatus`), which is a `textContent` write, so a tag here would be
    printed as characters and a newline would collapse.  The ids are `_short`'d - a
    status line is not the place for forty hexadecimal characters - and each row
    appears exactly once, under the clause that says what happens to it.

    `redo` picks the first sentence and the run clause too (`_smart_group`): the
    sentence `smart.plan_run` writes says the ledger is consulted, and on a redo press
    it is not.
    """
    plan = "smart.plan_rerun" if redo and phase == 3 else SMART_PLANS[phase]
    groups: dict[str, list[str]] = {}
    for build_id, step, failed in rows:
        groups.setdefault(_smart_group(step, phase, failed, redo), []).append(_short(build_id))
    said = [t(lang, plan, n=len(rows) - len(groups.get(
        "smart.waits_run", ())), total=len(rows))]
    for key in SMART_ORDER:
        if groups.get(key):
            said.append(f"{t(lang, key)}: {', '.join(groups[key])}")
    said.append(t(lang, "smart.activity", id=run_id))
    return "; ".join(said)


class ActionsMixin:
    @staticmethod
    def actions() -> tuple[str, ...]:
        """The action names, in the order the pages offer them (view.hpp §19)."""
        return ACTIONS

    # --- actions -----------------------------------------------------------

    def command(self, name: str, form: Mapping[str, list[str]],
                lang: str = DEFAULT_LANG) -> list[str]:
        """The command line one action runs - exactly what an operator would type.

        Every value comes from a select box or a ticked row, and every flag is one
        the entry point's own parser declares.  A page that ran anything else would
        be a second interface, and this one would stop being a record of truth.

        `lang` reaches only the refusals: the argv itself is a command line, and a
        command line is spelled the same in every language.

        `api` is read out of `form` like every other value, because the form is where
        a button's conditions live: the page puts this page's API into it (`api=`, a
        name or an address) and a hand-made POST may put another one there, and both
        go through `Apis.base()` - so a value no page offered reaches no command line.
        An absent or refused value is the base this deployment started on, which is
        what makes a POST with no `api` field (and every argv printed today) byte for
        byte what it was.
        """
        if name not in ACTIONS:
            raise errors.ConfigError(t(lang, "error.unknown_action", name=repr(name),
                                       known=", ".join(ACTIONS)))
        # The root is `repo_root()` and never a count of `dirname()` levels: the file
        # this method was written in sat one level higher, and a fixed count would now
        # point at `lib/` - every argv would name a script that is not there.
        root = repo_root()

        def entry(script: str) -> list[str]:
            return [sys.executable, os.path.join(root, script)]

        base = self.apis.base(_first(form, "api")) or self.launch_base()
        api = ["--api-url", base]
        # The same two clamps the page's own query went through, because these
        # values become the argv of a real process: `--limit -1` reached
        # `[:limit]` and cut the newest builds off, and a `--days` past the
        # platform's range was an OSError inside the child.
        days = str(_clamp(_numbers(form, "days", NO_WINDOW), NO_WINDOW, MAX_DAYS))
        limit = str(_clamp(_numbers(form, "limit", self.rows), 1, MAX_LIMIT))
        tree = _named(form, "tree", lang)
        # `branch` is a name like `tree` (the API filters by it and cannot list it,
        # `_branches_from_config` is where the page's candidates come from), and both
        # one-shot lines take it: `runday.py --branch` and `run_latest.py --branch`
        # are read as the *third* argument of `Kbuilds.getdays`/`getnew`, so a page
        # that never emitted the flag could not ask either of them for one branch.
        branch = _named(form, "branch", lang)
        test = _chosen(form, "test", TESTS, "", lang)
        builds = _ticks(form)

        if name == "index":
            # `table.py index` *does* ask an API (`config.client(args)`, table.py:60),
            # and without the flag it asks `$KCI_API_URL` or the local stack - on a
            # production view the "record this window" button read the local stack
            # and registered the wrong builds, so the cards never arrived.  It is
            # also the only button that writes cards, so this is the one place the
            # note's promise matters most.
            return entry("table.py") + ["index", *api, "--days", days, "--limit", limit,
                                        *_flag("--tree", tree)]
        if name == "index_pull":
            # The bar's third button: register the window *this page is showing*, then
            # pull the ticked rows.  `--days`/`--limit`/`--tree` are `index`'s own three
            # conditions and are read here exactly as `index` reads them, because the
            # registering half is that same command - a window spelled differently on
            # the two buttons would register one set of builds and pull another.
            #
            # No ticks is the same refusal `pull` makes, and not a quiet downgrade to
            # `index`: this button promises both halves, so a press that can only do
            # the first must say so rather than do half of what it said.
            if not builds:
                raise errors.ConfigError(t(lang, "error.pull_needs_build"))
            return entry("table.py") + ["index-pull", *api, "--days", days,
                                        "--limit", limit, *_flag("--tree", tree),
                                        *_pairs("--build", builds)]
        if name == "pull":
            if not builds:
                raise errors.ConfigError(t(lang, "error.pull_needs_build"))
            return entry("table.py") + ["pull", *_pairs("--build", builds)]
        if name == "run":
            # `--redo` is the re-run button's flag and nothing else's: absent from every
            # form that does not carry it, so the argv of the button beside it - "run
            # the tests this copy has no record for" - is byte for byte what it was.
            # `_switch` says why a `store_true` flag needs its own reader.
            #
            # **The ticks are the pairs, not the builds.**  A tick box is drawn on one
            # row of `/jobs`, and a row is one (build, test): the id a box sends is
            # `<build_id>:<test>` (`jobs._tick_cell`) and it goes to `table.py run
            # --pair`, which runs exactly that pair.  It used to be a build id plus one
            # `--test` from the bar, and the two are not the same question: `--build A
            # --build B --test boot --test kvm` is the *cross product* (both tests on
            # both builds), so the page could only ever let a reader tick the rows of
            # the one test it was filtered to - the operator's
            # 「test 有些好像有但是不能勾选跑不了」.  A pair names what was ticked.
            if not builds:
                raise errors.ConfigError(t(lang, "error.run_needs_build"))
            return entry("table.py") + ["run", *api, *_switch(form, "--redo"),
                                        *_pairs("--pair", builds)]
        if name == "runday":
            # `--tree` and `--branch` are emitted only when this page holds one, exactly
            # as `index` does it.  The literal `riscv` that used to stand here was a
            # **second copy of `runday.py`'s own default** (`--tree`, default "riscv"),
            # and a page that spells an entry point's default out can only drift from
            # it; the tree a reader picks is the page's tree box (`_tree_field`, whose
            # candidates are `TREES_KNOWN` - the config's names), and with none picked
            # the argv says nothing and `runday.py` decides, which is why the printed
            # line still cannot disagree with the process behind it.
            return entry("runday.py") + ["--days", days, "--limit", limit,
                                         *_flag("--tree", tree), *_flag("--branch", branch),
                                         *_flag("--test", test), *api]
        if name == "fetch":
            return entry("run_latest.py") + [*_flag("--tree", tree),
                                             *_flag("--branch", branch),
                                             *_flag("--test", test), *api]
        if name == "provision":
            # **The card's own facts, as `--parameter k=v`.**  `publish_local()` reads
            # `run.params` and never `args.tree` (`build/publish.py::_fact`), so the
            # `--tree riscv` this line used to carry reached a flag the provision path
            # does not look at: the button published a card with an empty tree, and the
            # id - which is the artifact URL's own 24-hex suffix, else the first 12
            # characters of the commit - had nothing to fall back on, so every press in a
            # workspace whose environment carries no `KCI_BUILD_COMMIT` was refused by
            # `_published_id()`.  That is the whole of what the panel's boxes are: the
            # facts only the reader knows.  An empty box is **not passed** - the command
            # then falls back to `$KCI_BUILD_*` and to this deployment's own served file,
            # which is what the panel says its boxes do.
            facts = [("tree", _named(form, "tree", lang)),
                     ("branch", _named(form, "branch", lang)),
                     ("commit", _named(form, "commit", lang)),
                     ("describe", _named(form, "describe", lang)),
                     ("defconfig", _named(form, "defconfig", lang))]
            url = _parameter_url(_first(form, "kernel_url"), "kernel_url", lang)
            if url:
                facts.append(("kernel_url", url))
            return entry("run_latest.py") + [
                "--provision-only",
                *_pairs("--parameter", [f"{key}={value}" for key, value in facts if value]),
                *api]
        if name == "worker":
            mode = _chosen(form, "mode", MODES, "once", lang)
            # The two claim filters, offered and validated from **one** list each
            # (`schema._worker_platforms` / `_worker_runtimes`, the vendored
            # `scheduler*.yaml` plus this deployment's own default).  They used to be
            # hand-written pairs here - `("", DEFAULT_DEVICE)` - and a pair that is not
            # the page's offer list is a live refusal: `_chosen` raises for any value
            # the tuple does not name, so the page could not offer what this line would
            # not accept, and `qemu-x86_64` - the platform `scheduler-pull-labs.yaml`
            # lists - could be neither selected nor submitted.
            platform = _offered(form, "platform", ("", *_worker_platforms()),
                                DEFAULT_DEVICE, lang)
            runtime = _offered(form, "runtime", ("", *_worker_runtimes()), DEFAULT_LAB, lang)
            # **`--since` is where the window opens, and only the poller may decide
            # what that means.**  `deploy/stack.sh --seed` writes job nodes carrying the
            # upstream build's own timestamps (`created=2026-09-20T08:20` while the
            # containers started `2026-09-21T05:03`), and a worker's window *used to be*
            # `[cursor - 900s, now]` - so those seeded `available` jobs sat behind the
            # cursor, `/worker` showed them as `claimed: no` for ever, and this flag was
            # the only way to reach them short of hand-editing an argv.
            #
            # **That is fixed at the other end now** (`poller.start_cursor`): the cursor
            # is no longer a floor and the worker asks for the whole `available` queue,
            # so seeded work is reached with no flag at all.  What is left here is the
            # flag's second job, which it keeps: narrowing the run to a window the
            # operator names.  It is still the only argument that bounds the query - the
            # state file cannot overrule it, and cannot widen it either.
            #
            # Refused rather than repaired, and refused *here* rather than at the page:
            # `poller.iso_ago()` reads the API's own stamp shapes (`poller.parse_iso`)
            # and treats every other value as "now", so a stamp of another shape is not
            # an error the worker reports - it silently scans the last 15 minutes,
            # which is the window the reader was trying to widen.  `_iso_stamp` is the
            # one judge, and an empty value is simply the flag left out (the page's
            # "(no `--since`)" choice).
            since = _first(form, "since")
            if since and not _iso_stamp(since):
                raise errors.ConfigError(t(lang, "error.not_a_stamp", key="since",
                                           value=repr(since)))
            return entry("pull_worker.py") + (["--once"] if mode == "once" else []) + [
                *_flag("--platform", platform), *_flag("--runtime", runtime),
                *_flag("--since", _iso_stamp(since)), *api]
        if name == "results":
            # The page's choose-a-build box is named `build`, and this action read
            # `selected` - a name that form never sends, so the box was dead and
            # the ledger always came out in full.  Ticks still work, for a form
            # that sends them (GUI.md §3: the value comes from the select box).
            chosen = _token(_first(form, "build")) or (builds[0] if builds else "")
            return entry("results.py") + _flag("--build", chosen) + _flag("--test", test)
        if name == "drift":
            older, newer = _token(_first(form, "older")), _token(_first(form, "newer"))
            if not (older and newer):
                raise errors.ConfigError(t(lang, "error.drift_needs_two"))
            return entry("drift.py") + ["--older", older, "--newer", newer, *api]
        raise errors.ConfigError(t(lang, "error.unknown_action", name=repr(name),
                                   known=", ".join(ACTIONS)))

    def _one_tree(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Why a one-shot bar cannot be offered here - `""` when this filter names one tree.

        `--tree` is single-valued in every entry point these bars start
        (`run_latest.py`, `runday.py` and `table.py index` each declare one `--tree`,
        none with `action="append"`), and `command()` reads it with `_named`, which
        refuses a comma-joined value as the non-name it is.  So a filter that names two
        trees cannot be handed to a one-shot button honestly, and the button must say
        so rather than be clickable and refuse: that is `_action_bar(blocked=…)`'s
        rule, and the reader's own gesture (unticking a box) is the way out.

        This is the one string in the bar and it is a `title=`, not a paragraph: the
        fact is about this button, and `05-i18n-prose.md` §B.1 puts a fact like that
        where the button is.  The list is spelled out because it is short by
        construction - the reader chose it two controls above.
        """
        named = _names(check.tree)
        if len(named) <= 1:
            return ""
        return t(lang, "filter.one_tree", trees=", ".join(named))


    def start(self, name: str, form: Mapping[str, list[str]],
              lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Start one action as a `Run`; a second writer is refused while one is running.

        `smart` is answered before the rest and is not in `ACTIONS`, for the reason
        `forget` is not: it is not one command but a choice between three, and the
        choice is made from the ticked rows (`_smart`).  What it starts is one of the
        commands the bar already offers, so the activity carries that command's own
        `kind` (`KINDS[phase]`) and its own `what` - nothing here invents a kind, and
        `/runs` shows the press as the `table.py` line it really ran.
        """
        if name == "smart":
            return self._smart(form, lang)
        argv = self.command(name, form, lang)
        busy = self.busy() if name in WRITERS else []
        if busy:
            raise errors.ConfigError(t(lang, "error.writer_busy", writer=busy[0]))
        # `what` is the page's one-line label for an activity (the `what` column of
        # /runs), so it is drawn in the reader's language; `argv` beside it is the
        # command and stays exactly what it is.  The label is read off that argv and
        # never off the form (`_what_of`): three form keys - `_ticks(form) or
        # [test, older, tree]` - named nothing at all for the six actions that carry
        # none of them, which is how 38 of 50 rows came to say `这个部署`, including an
        # `index` whose own `run.json` records `--days 30 --limit 200` and a `runday`
        # whose records `--tree riscv --days 1` (`04-actions.md` §4).  A label that is
        # read off the command cannot disagree with the process, which is the whole
        # rule this page's buttons follow.
        run = run_mod.Run.start(KINDS[name], argv, what=_what_of(name, argv, lang)[:120])
        return {"started": run.id, "kind": KINDS[name], "argv": argv}

    # The three steps a smart press can take are `SMART_STEPS`, at the top of this
    # module: they name actions, and an action's name is what `command()` reads.

    def _smart(self, form: Mapping[str, list[str]],
               lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One press over the ticked rows: the earliest step any of them needs, and a
        per-row account of what this press does and does not do.

        **A press is one command, so it takes one step** (`lib/run.py` starts one
        process, and one command per activity is the rule this console keeps).  The
        three steps are three commands - `table.py index-pull` (register the window,
        then pull), `table.py pull` (the bytes) and `table.py run` (the tests) - and a
        press takes the earliest of them that any ticked row still needs: the reader's
        own sequence, done in the order the rows need it, with the answer naming every
        row.  A row this press does not touch is in that answer with the reason it
        waits; nothing is skipped silently, which is the failure this page makes
        elsewhere.

        Each row's step is read off the same three facts the table draws - `Local.card`,
        `Local.present` and the newest act's own `error` - so the rows grouped here are
        the rows the reader ticked, and not a second query's idea of them.

        The three steps and their phases make exactly five clauses (`_smart_group`),
        and the counts in the first sentence are of this press's own rows: `{n}` of
        `{total}`, so a reader who ticked ten and had two acted on can see that in the
        sentence and not only in the list under it.

        **`redo` rides through the form.**  The bar's re-run button is this action with
        `redo=1` on the button itself (`ui.action_form`'s `also`), so the value is
        already in `form` when the phase-3 command is built - `command()` reads it with
        `_switch`, and nothing here spells `--redo` a second time.  What this method
        owes it is the *words*: only phase 3 can re-run anything (the other two phases
        put bytes on disk, and running without them is not a press that could work), so
        the flag is worth reading exactly when phase is 3, and `_smart_note` says so.
        """
        builds = _ticks(form)
        if not builds:
            raise errors.ConfigError(t(lang, "error.smart_needs_build"))
        held = self.all_locals()
        rows: list[tuple[str, int, bool]] = []
        for build_id in builds:
            copy = held.get(build_id)
            # 1: no card (the register half is what this row needs), 2: carded but
            # nothing on disk, 3: carded and on disk.  `present` is the same
            # `os.path.isfile` reading the resource column draws, so a row the page
            # shows as 没有 is a row this press treats as needing bytes - one reading,
            # two readers.
            rows.append((build_id, 1 if copy is None or copy.card is None
                         else 3 if copy.present else 2,
                         bool(copy is not None and copy.latest.get("error"))))
        phase = min(one[1] for one in rows)
        # Which rows this press acts on.  Phases 1 and 2 both take the rows through
        # step 2, and phase 1 takes the step-2 rows as well: `index-pull` pulls exactly
        # the ids it is given, and a carded id is one `table.get()` can hand it, so the
        # download those rows are waiting for is part of the same command - the reader
        # does not press twice for one window.  A step-3 row is the one that waits, and
        # that is the same in both: running it before its card and its bytes exist is
        # not a press that could work.  Once the press itself is a run, every ticked row
        # is acted on (`phase == 3` means no row needs anything else).
        acted = [one[0] for one in rows if one[1] <= (3 if phase == 3 else 2)]
        # Phase 3's ticks are (build, test) pairs, one per test the console runs
        # (`tests.DEFAULT_TESTS`, the same set `/jobs` draws a row per) - `command()`
        # reads the pair spelling, and `table.py` skips the pairs the ledger already
        # holds, so pressing this twice does not re-run what has run.
        selected = ([f"{build_id}:{test}" for build_id in acted for test in DEFAULT_TESTS]
                    if phase == 3 else acted)
        action = SMART_STEPS[phase]
        redo = phase == 3 and bool(_switch(form, "--redo"))
        argv = self.command(action, {**form, "selected": selected}, lang)
        busy = self.busy() if action in WRITERS else []
        if busy:
            raise errors.ConfigError(t(lang, "error.writer_busy", writer=busy[0]))
        run = run_mod.Run.start(KINDS[action], argv, what=_what_of(action, argv, lang)[:120])
        return {"started": run.id, "kind": KINDS[action], "argv": argv, "ok": True,
                "note": _smart_note(rows, phase, run.id, lang, redo=redo)}

    def set_callback(self, url: str, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Point this deployment's job reports at *url*, nowhere (`off`), or at the definition's.

        The second thing on this console that edits `var/state/` instead of running a
        program, and the same division of labour as `forget`: the write belongs to
        `lib/sink.py` (`set_callback_override`), which is where the file and the rule
        about what a callback URL may be live, and this is the HTTP edge of it that
        turns the answer into one sentence for the page.

        **A URL it will not write is a refusal and not a note**, so `ConfigError` is left
        to the caller (`_route_post` answers 409): the operator typed this value into a
        box and is the only one who can correct it, and a green "saved" over a URL that
        every delivery will fail on is the page lying about a setting.

        Three sentences, one per answer, because the page's note is the only thing that
        says which of the three happened - and one of them is not a URL, so the
        `"now sending results to {url}"` template would have printed "…to off".
        """
        try:
            written = sink.set_callback_override(url)
        except errors.ConfigError:
            # The rule belongs to `sink` (it is the one that has to read the file back),
            # the sentence belongs here: this is the layer that knows what language the
            # operator is reading in, and a 409 body is printed inside a translated
            # frame (`script.py`'s `action.rejected`).
            raise errors.ConfigError(t(lang, "error.callback_url", url=url)) from None
        if written == sink.OFF:
            note = t(lang, "worker.override.off")
        elif written:
            note = t(lang, "worker.override.set", url=written)
        else:
            note = t(lang, "worker.override.cleared")
        return {"url": written, "override": bool(written), "ok": True, "note": note}

    def cancel(self, run_id: str, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Stop one activity and everything it started."""
        run = run_mod.Run.load(_token(run_id) or run_id)
        if run is None:
            raise errors.ConfigError(t(lang, "error.no_activity", run_id=repr(run_id)))
        return {"cancelled": run_id, "stopped": run.cancel()}

    def forget(self, node_id: str, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Take one job node back out of the worker's `seen`, so the next poll re-reads it.

        Not a command and so not in `ACTIONS`: nothing is started and no argv is
        printed - this is the one thing on this console that edits `var/state/` rather
        than running a program that does.  It is here rather than in the page because
        the write itself belongs to `lib/poller.py` (`forget_node`), which is where the
        file's shape, its lock and its eviction rules live; this method is the HTTP
        edge of it: check the id, hand it over, and turn the four outcomes into one
        sentence the page can print next to the button that was pressed.
        """
        wanted = _token(node_id)
        if not wanted:
            raise errors.ConfigError(t(lang, "error.no_node", node_id=repr(node_id)))
        outcome = poller.forget_node(wanted)
        # `ok` is the script's styling and not a second opinion: "nothing remembered it"
        # is a successful answer to "forget it" (the reader's intent already holds), and
        # only the two that stopped the write short are refusals.  The script cannot
        # work this out from `forgotten`, which is False in both cases.
        return {"node_id": wanted, "forgotten": outcome["forgotten"],
                "reason": outcome["reason"],
                "ok": outcome["reason"] not in ("locked", "unreadable"),
                "note": t(lang, f"worker.forget.{outcome['reason'] or 'done'}", node_id=wanted)}

    def log(self, run_id: str, offset: Any = 0, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """The bytes appended to one activity's log since `offset`."""
        run = run_mod.Run.load(_token(run_id) or run_id)
        if run is None:
            raise errors.ConfigError(t(lang, "error.no_activity", run_id=repr(run_id)))
        run.reap()          # a finished process must not be reported as still running
        try:
            start = int(offset or 0)
        except (TypeError, ValueError):
            start = 0
        text, next_offset = run.log_since(start)
        return {"id": run_id, "text": text, "offset": next_offset,
                "state": run.state, "exit_code": run.exit_code}

    def status(self, kind: str = "", state: str = "") -> list[dict[str, Any]]:
        """Every activity's state - what the page polls while something runs."""
        return self.run_rows(kind, state)

    def state_poll(self, kind: str = "", state: str = "") -> dict[str, Any]:
        """What the page's 2s poll asks for: the activities, and the local digest.

        One answer and not two requests (`/api/state`): the poll already fetched
        `/api/runs` every two seconds, and the digest is the fact that turns that
        fetch into the trigger the operator asked for - a finished activity has
        written something, so the page must re-read rather than wait for F5.

        The runs are read **before** the digest is taken, and that order is the whole
        mechanism: `Run.load_all()` resolves a `running` whose process has gone
        (`reap()` → `_settle` → `run.json`), so the write that says "this activity
        ended" is already inside the digest this answers with - the page sees the
        change on the tick it happened, not two seconds later.
        """
        runs = self.status(kind, state)
        return {"digest": _state_digest(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "runs": runs}

    def _argv_of(self, action: str, fields: Mapping[str, str],
                 lang: str = DEFAULT_LANG, api: str = "") -> str:
        """The command line one button will run, in words - `command()` is the only source.

        A bar that printed its own idea of the argv would drift from the process
        the button starts, and the whole point of the bar is that the two are the
        same thing.  When `command()` refuses - a pull with nothing ticked - the
        bar says what is missing: "nothing to run" is an answer, an invented
        command line is not.

        `api` is this page's API key (`Filter.api`), and it is put into the same form
        dict the button will post (`_action_bar`), so the printed argv and the process
        the button starts agree about which API they mean.  Both callers pass it or
        neither does - a bar that said `production` while the button ran against the
        local stack would be worse than either.

        A field's value is one string, or a sequence of them where the command takes
        a flag more than once (`_values`): `/builds`' run button names a copy's three
        (build, test) pairs itself, and a form is a name to a *list* of values because
        that is what a repeated field is.
        """
        form = {key: _values(value) for key, value in fields.items()}
        if api:
            form["api"] = [api]
        try:
            argv = self.command(action, form, lang)
        except errors.KciError as exc:
            return t(lang, "action.refused", reason=exc)
        return _short_argv(argv)

    # What a tick-driven bar prints in place of the ids it cannot know until a box is
    # ticked.  A token, so `_token()` lets it through the same door a real build id
    # does, and printed as the words that stand for it (`action.ticked_build`).
    TICKED = "TICKED"

    def _argv_of_ticked(self, action: str, fields: Mapping[str, str],
                        lang: str = DEFAULT_LANG, api: str = "",
                        tick_word: str = "action.ticked_build") -> str:
        """The command a button whose ticks *are* the selection will run, ids left open.

        `_argv_of` prints what a button will run from the page's own fields, and a
        tick-driven button has a value that does not exist until a box is ticked - so
        the bar printed **its own refusal** there instead: `/jobs`' run bar carried
        `<code class="argv">no command to run: run needs at least one ticked build</code>`
        on every single load, in the `title` and in the text, next to 17 tick boxes and
        under a heading that promised a command.  The operator read it as his ticks
        having been refused, and reported it in those words
        (`没有可跑的命令：跑至少要勾一个 build`), which is a *design* bug and not a
        body bug: nothing had been clicked yet (`04-actions.md` §2).

        Here the missing value is named rather than refused: the flag is printed with
        the words that stand for the boxes, and every condition that *is* known - the
        API, the test - is printed as itself.  Nothing here is a promise about the ids:
        only the boxes can make that one, and `_action_bar` still sends exactly the
        fields it always did.

        `tick_word` is what those words are, and it is the caller's because two bars
        tick two different things: `/builds`' pull ticks builds (`action.ticked_build`,
        one `--build` each), and `/jobs`' run ticks (build, test) pairs
        (`action.ticked_pair`, one `--pair` each).  The token in the argv is the same;
        only the words that stand for it differ, and a bar that said "build" over a
        `--pair` line would name the wrong thing.
        """
        form = {key: _values(value) for key, value in fields.items()}
        form["selected"] = [self.TICKED]
        if api:
            form["api"] = [api]
        try:
            argv = self.command(action, form, lang)
        except errors.KciError as exc:
            return t(lang, "action.refused", reason=exc)
        return _short_argv(argv).replace(self.TICKED, t(lang, tick_word))


def _switch(form: Mapping[str, list[str]], flag: str) -> list[str]:
    """`--flag` when the form carried it, nothing when it did not - for a `store_true` flag.

    `_flag` spells `--name value`, which a `store_true` parser reads as a stray word
    after the flag, so a flag that takes no value needs its own reader.  `table.py
    --redo` is the one `command()` sends (`runday.py` has one too, and no page sends
    it), and it is a `store_true`: the whole meaning of the flag is that it is there.

    **A tick box's own rule decides what "carried" is.**  A ticked box submits its value
    and an unticked one submits nothing at all, so the key's presence in the form is the
    tick and the value is deliberately left unread - there is no spelling of `1` this
    line could prefer over `on` or `yes` without inventing a vocabulary nothing else in
    this tree has.  A form that carries the key with an empty value is not a tick
    (`_first` answers `""` for it), which is what a hand-made POST that meant "no" would
    most likely send.
    """
    return [flag] if _first(form, flag.lstrip("-")) else []


def _values(value) -> list:
    """One field of a form, in the shape `command()` reads: a list of strings.

    `command()` takes `Mapping[str, list[str]]` because a form may carry one name more
    than once - `--pair a --pair b` is one field with two values, which is what a
    repeated flag is - and the two `_argv_of` helpers are its only callers.  A page
    that knows one value passes the string; one that knows several (`/builds`' run
    button, which names a copy's three (build, test) pairs) passes the sequence.  The
    values are not validated here: `command()` is the door that refuses, and a second
    opinion about which ids are allowed is how the printed argv and the process behind
    it come apart.
    """
    if isinstance(value, (list, tuple)):
        return [str(one) for one in value]
    return [str(value)]


def _short_argv(argv: Iterable[str]) -> str:
    """An argv as a page prints it: `python3 table.py index --days 30`.

    The interpreter's path and the checkout's path are noise on a page that is
    already inside the checkout; the flags and their values are the command.  The
    full line is in the element's title, and in the activity's own `run.json`.
    """
    parts = [str(one) for one in argv]
    if parts:
        parts[0] = os.path.basename(parts[0])
    if len(parts) > 1:
        parts[1] = os.path.basename(parts[1])
    return " ".join(parts)


def _what_of(name: str, argv: Iterable[str], lang: str = DEFAULT_LANG) -> str:
    """One activity's `what` column: the selector, read off the command it will run.

    The interpreter, the script and `--api-url <base>` are dropped - they are the same
    for every activity this page starts, and the base is already in the page's own
    query line - and a flag repeated more than twice collapses to `<flag> ×<n>`, so
    "run twenty builds" is a line and not a page (17 ticked boxes would be ~440
    characters of hex in a column that prints 60).

    Nothing is invented and nothing is guessed from the form: a flag the command does
    not carry cannot appear here, and an argv with nothing left after the base says
    `run.this_deployment`.  That is the point - the row in `/runs` and the process
    behind it cannot disagree, because they are the same list
    (`docs/gui-rework/04-actions.md` §D4).
    """
    parts = [str(one) for one in argv][2:]                 # python3, table.py
    # `--api-url <base>` is dropped wherever it appears, not only at the front: a
    # `table.py` argv carries its subcommand first (`run --api-url … --build …`), so
    # the flag that is the same for every activity here is not always the first one.
    kept: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i] == "--api-url":
            i += 2
            continue
        kept.append(parts[i])
        i += 1
    if kept and not kept[0].startswith("-"):
        kept = kept[1:]                                    # the subcommand, already in `name:`
    counts: dict[str, int] = {}
    for one in kept:
        if one.startswith("--"):
            counts[one] = counts.get(one, 0) + 1
    out: list[str] = []
    i = 0
    while i < len(kept):
        flag = kept[i]
        value = (kept[i + 1] if i + 1 < len(kept) and not kept[i + 1].startswith("-")
                 else "")
        if flag.startswith("--") and counts[flag] > 2:
            out.append(t(lang, "run.n_of", flag=flag, n=counts[flag]))
            # Every occurrence goes, not one: `<flag> ×17` is one clause, and a loop
            # that consumed two tokens would print it seventeen times.
            while i < len(kept) and kept[i] == flag:
                i += 2
            continue
        elif flag.startswith("--"):
            out.append(f"{flag} {value}".strip())
        else:
            out.append(flag)                               # a positional value
        i += 2 if (flag.startswith("--") and value) else 1
    return f"{name}: " + (" ".join(out) or t(lang, "run.this_deployment"))
