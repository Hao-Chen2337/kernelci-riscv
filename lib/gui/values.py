# SPDX-License-Identifier: LGPL-2.1-or-later
"""One value as a page prints it: an age, a size, an id, a state.

The small formatters several tables share - `3s`/`2m`/`1h`, `2.4MB`, `deadbeef`,
`pulled` - each one used by more than one page and each one small enough that a
second copy would be invisible until the two disagreed on screen."""

import os
import urllib.parse
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..i18n import DEFAULT_LANG, t
from ..re import Records
from .schema import EVIDENCE

if TYPE_CHECKING:
    from .models import Local

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
