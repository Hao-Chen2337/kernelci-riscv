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
poll reads while something runs."""

import os
import sys
import time
from collections.abc import Iterable, Mapping
from typing import Any

from .. import errors, repo_root
from .. import run as run_mod
from ..i18n import DEFAULT_LANG, t
from ..tests import DEFAULT_DEVICE, DEFAULT_LAB, TESTS
from .forms import (
    _chosen,
    _clamp,
    _first,
    _flag,
    _iso_stamp,
    _named,
    _numbers,
    _offered,
    _pairs,
    _ticks,
    _token,
)
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
        if name == "pull":
            if not builds:
                raise errors.ConfigError(t(lang, "error.pull_needs_build"))
            return entry("table.py") + ["pull", *_pairs("--build", builds)]
        if name == "run":
            if not builds:
                raise errors.ConfigError(t(lang, "error.run_needs_build"))
            return entry("table.py") + ["run", *api, *_pairs("--build", builds),
                                        *_flag("--test", test)]
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
            return entry("run_latest.py") + ["--provision-only", "--tree", tree or "riscv", *api]
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
            # containers started `2026-09-21T05:03`), and a worker's window is
            # `[cursor - 900s, now]` - so the seeded `available` jobs sit *behind* the
            # cursor and `/worker` shows them as `claimed: no` for ever.  `--since` is
            # the flag `config.parse_poll` already declares for exactly this, and the
            # page did not offer it, which left hand-editing an argv as the only way.
            # It is also the one argument that *outranks* the state file
            # (`poller.start_cursor()` reads this before the persisted cursor), so a
            # reader who presses it is asking for a window the file cannot overrule.
            #
            # Refused rather than repaired, and refused *here* rather than at the page:
            # `poller.iso_ago()` reads one shape of stamp and treats every other value
            # as "now", so a stamp of another shape is not an error the worker reports -
            # it silently scans the last 15 minutes, which is the window the reader was
            # trying to widen.  `_iso_stamp` is the one judge, and an empty value is
            # simply the flag left out (the page's "(no `--since`)" choice).
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

    def start(self, name: str, form: Mapping[str, list[str]],
              lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Start one action as a `Run`; a second writer is refused while one is running."""
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

    def cancel(self, run_id: str, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """Stop one activity and everything it started."""
        run = run_mod.Run.load(_token(run_id) or run_id)
        if run is None:
            raise errors.ConfigError(t(lang, "error.no_activity", run_id=repr(run_id)))
        return {"cancelled": run_id, "stopped": run.cancel()}

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
        """
        form = {key: [str(value)] for key, value in fields.items()}
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
                        lang: str = DEFAULT_LANG, api: str = "") -> str:
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
        the words that stand for the boxes (`<each ticked build>`), and every
        condition that *is* known - the API, the test - is printed as itself.  Nothing
        here is a promise about the ids: only the boxes can make that one, and
        `_action_bar` still sends exactly the fields it always did.
        """
        form = {key: [str(value)] for key, value in fields.items()}
        form["selected"] = [self.TICKED]
        if api:
            form["api"] = [api]
        try:
            argv = self.command(action, form, lang)
        except errors.KciError as exc:
            return t(lang, "action.refused", reason=exc)
        return _short_argv(argv).replace(self.TICKED, t(lang, "action.ticked_build"))


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
