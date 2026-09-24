# SPDX-License-Identifier: LGPL-2.1-or-later
"""One value as a page prints it, and the values an axis offers to be asked with.

The small formatters several tables share - `3s`/`2m`/`1h`, `2.4MB`, `deadbeef`,
`pulled` - each one used by more than one page and each one small enough that a
second copy would be invisible until the two disagreed on screen.

`_vocabulary` answers the other half of the same question: not how a value is printed
but which values an axis offers to be asked with.  It is decided out of the config this
tree vendors (`TREES_KNOWN`, `ARCH_KNOWN`, `_branches_from_config`) and the rows the
caller has already read, so it is a question about *values* with no I/O of its own - it
lived in `fields.py` only because a filter bar happens to be what drew the answer, and
it would have been deleted with that module while `design/data.py` still asked it.  No
I/O is also what keeps it here rather than in `reads.py`: reading a request is that
module's subject, and nothing is read for this one.
"""

import os
import time
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ..i18n import DEFAULT_LANG, t
from ..poller import parse_iso
from ..re import Records
from .forms import _names, _token
from .schema import (
    ARCH_KNOWN,
    BRANCH_SEEDS,
    DEFAULT_TZ,
    EVIDENCE,
    TREES_KNOWN,
    _branches_from_config,
)

if TYPE_CHECKING:
    from .models import Filter, Local


# What each state of the record means, as the catalogue key
# that holds the sentence.  The six sentences moved into `lib/i18n` with every
# other sentence the page prints: one catalogue, one place a translator looks.  The
# *keys* here are the record's own vocabulary (`Local.state`), which is compared in
# code and never translated; only what each one means is.
def _host(url: str) -> str:
    """The host an artifact URL names, or nothing when it names none.

    Nothing, and not the URL itself: `_host` used to answer the whole string when it
    had no netloc, so `file:///home/hao/kernelci-riscv/var/serve/Image` was printed in
    a column called `hosts` as if a path were a machine (`03-structure.md` §A3.4).  A
    locally published copy has no host, and the empty cell says that.
    """
    return urllib.parse.urlsplit(url).netloc


def _ago(seconds: float) -> str:
    """A number of seconds as the coarse value a page prints in a pill: `3s`, `2m`, `1h`."""
    for unit, size in (("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def _clock(seconds: float, tz: str = DEFAULT_TZ, shape: str = "%H:%M:%S") -> str:
    """An epoch float as the clock the reader chose; a falsy stamp is no time.

    `run.json` holds `started`/`ended` as epoch floats (`lib/run.py`), and `ended`
    is `0.0` while a run is going - which is why this answers `""` for a falsy
    stamp instead of `1970-01-01 00:00:00`, and why a caller can read "no end yet"
    off the same field it prints.

    `tz` is `Filter.tz` and **only the printing moves**: every stamp this console
    reads is UTC on disk and every stamp it writes stays UTC.  The two clocks are
    `utc`, which is the value as stored, and `local`, which is the machine this
    console runs on and what a reader comparing a page against their own watch wants.
    """
    if not seconds:
        return ""
    return time.strftime(shape, time.gmtime(seconds) if tz == "utc"
                         else time.localtime(seconds))


def _in_clock(stamp: str, tz: str = DEFAULT_TZ, shape: str = "%Y-%m-%d %H:%M") -> str:
    """A stored UTC stamp in the reader's chosen clock, in the shape asked for.

    The same choice `_clock` makes, for the stamps that arrive as text rather than as
    epoch floats - and the same rule, that **only the printing moves**.  A stamp nobody
    can read comes back untouched, because a page's job is to print what the file says
    and `parse_iso` is the poller's own reader: the page and the loop that wrote the
    stamp agree about what the value means rather than each having a spelling of its
    own.
    """
    parsed = parse_iso(stamp)
    return _clock(parsed, tz, shape) if parsed else stamp


def _human(size: int) -> str:
    """A byte count as a page prints it (binary units, one decimal)."""
    for unit, limit in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if size >= limit:
            return f"{size / limit:.1f} {unit}"
    return f"{size} B"


def _short(text: str, keep: int = 12) -> str:
    """The first `keep` characters of an id - a page shows the rest on hover."""
    return (text or "")[:keep]


def _dirs(path: str) -> list[str]:
    """The subdirectory names under `path`; a missing directory is an empty list."""
    try:
        return sorted(one for one in os.listdir(path) if os.path.isdir(os.path.join(path, one)))
    except OSError:
        return []


def _tally(rows: Iterable["Local"], remote_ids: set[str]) -> dict[str, int]:
    """How many local copies sit in each state, and how many have no remote counterpart."""
    counts = {state: 0 for state in EVIDENCE if state != "any"}
    counts["no remote counterpart"] = 0
    for one in rows:
        counts[one.state] = counts.get(one.state, 0) + 1
        if one.build_id not in remote_ids:
            counts["no remote counterpart"] += 1
    return counts


def _last_verdict(records: Records, test: str) -> str:
    """One test's most recent verdict, from the ledger (`Records.last`)."""
    found = records.last(test)
    return found.verdict if found is not None else ""


def _short_state(state: str, lang: str = DEFAULT_LANG) -> str:
    """The state as a table cell says it, in words rather than a key."""
    return {"pulled": t(lang, "state.pulled_recorded"),
            "unrecorded": t(lang, "state.bytes_no_pull"),
            "registered": t(lang, "state.card_only"),
            "made-here": t(lang, "state.made_here"),
            "empty": t(lang, "state.empty"),
            }.get(state, state)


def _field_of(one: Any, name: str) -> str:
    """One value of a card, a row dict or a filter - the three shapes a page mixes."""
    if isinstance(one, Mapping):
        return str(one.get(name) or "")
    return str(getattr(one, name, "") or "")


def _seen_names(kind: str, rows: Iterable[Any], table: Iterable[Any] = ()) -> set[str]:
    """The names a page has actually seen: its own rows, and the local table's cards.

    "Seen" is the honest word for it, and it is what the page says: these are not
    the trees or branches that exist, they are the ones this deployment has met.
    """
    return {one for one in (_field_of(any_one, kind)
                            for any_one in list(rows) + list(table)) if one}


def _vocabulary(kind: str, check: "Filter", rows: Iterable[Any],
                table: Iterable[Any] = ()) -> list[str]:
    """The candidates a name field offers: the fixed list, plus what we have seen.

    Order matters: the fixed list is the floor (the page has to work on a machine
    that has never queried this API), the values the rows carry are the ceiling,
    and the one in force comes last so a list still offers it if it is in neither.
    Everything passes `_token()`: only a name that could reach a command line is
    worth suggesting.

    **Four axes, three different sources, and each one is a file or a fact rather
    than a preference:**

    * `tree` - the names `trees.yaml` lists (`TREES_KNOWN`);
    * `arch` - the architectures `jobs*.yaml` declares as `params.arch`
      (`ARCH_KNOWN`).  This is the axis the operator noticed was stuck on
      `riscv`: it had no seed list at all and derived its candidates from the
      rows, and every row this deployment reads comes from one job name
      (`KBUILD_JOB`), so it offered exactly one value - the "架构目前只填一个
      riscv 的怪状".  The value a node's `data.arch` carries is a copy of that
      job's `params.arch`, so the config is the honest source and not a list
      invented to fill the box;
    * `branch` - *this tree's* own branches, from `trees/<tree>.yaml`.  The six
      seeds are the fallback for a checkout without `config/trees/`, not the set:
      offering `net-next`'s branch names beside `tree=riscv` is not an incomplete
      list, it is a wrong one (`02-filters.md` §A4);
    * `defconfig` and `compiler` - **nothing static, on purpose.**  Both have a
      config of their own (`params.defconfig`, `params.compiler`), and both are
      bound to another axis the way a branch is bound to a tree: a defconfig
      belongs to an arch, so `_combo` offers what this deployment has actually
      built and lets the free box take anything else.
    """
    if kind == "tree":
        seeds: Iterable[str] = TREES_KNOWN
    elif kind == "arch":
        seeds = ARCH_KNOWN
    elif kind == "branch":
        seeds = _branch_stops(check)
    else:
        seeds = ()
    # The one in force, split like any other multi-valued answer: a box that did not
    # offer `riscv,mainline` as its two names would print the pair as one candidate.
    seen = _seen_names(kind, rows, table) | set(_names(_field_of(check, kind)))
    found = [one for one in seeds if _token(one)]
    found += sorted(one for one in seen if one and _token(one) and one not in found)
    return found


def _branch_stops(check: "Filter") -> list[str]:
    """The branches the trees in force bind to, in the order the config lists them.

    One tree is the ordinary case (`_branches_from_config(tree)`).  `tree` is a
    multi-valued axis now, and with several trees on, the branches in force could be
    any of theirs - so the candidates are the union of those trees' own, which is the
    most a per-tree source can say honestly (`_vocabulary`'s third bullet).

    No tree at all keeps its old answer: `_branches_from_config("")` is every branch
    name the vendored trees declare (76 of them), and `BRANCH_SEEDS` is the floor for
    a checkout without them.  The empty result of a checkout that has the directory
    but no matching file falls back the same way, because a box with no candidates and
    no rail is a box the reader has to guess at.
    """
    trees = _names(check.tree)
    if not trees:
        found = list(_branches_from_config(""))
    else:
        found = []
        for tree in trees:
            for one in _branches_from_config(tree):
                if one not in found:
                    found.append(one)
    return found or list(BRANCH_SEEDS)
