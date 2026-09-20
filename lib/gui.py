# SPDX-License-Identifier: LGPL-2.1-or-later
"""The GUI: three things kept apart - what the API has, what we hold, and the record.

The old page merged the first two into one table of `build_id`s, which quietly
claimed that a local copy and a remote build with the same id are the same thing.
They are two equal *values*; sameness has to be established.  So this page shows
three separate facts and never derives one from another:

* **remote** - the answer to one API query (`Kbuilds.getdays`), always a window
  (or `days=0`, which asks for the whole history), so the page prints the query
  it asked *and* how much of the answer it is showing;
* **local** - a card registered in the table (`Builds`) and bytes on disk
  (`Build.present()`), which are two facts even about the same directory;
* **the correspondence** - `var/downloads/<build-id>/provenance.json`, written by
  `Build.make()` when the bytes are pulled: which URL every artifact came from,
  how many bytes were proven, and when.  No record means "not recorded", never a
  guess from a matching id.

Every button runs the command an operator would type (`Gui.command()`), as a `Run`
(see `lib/run.py`); one writer at a time; and the page computes nothing - a verdict
comes from `judge`, a tally from `Records`, a gap from `todo()`, a regression from
`transitions()`, a difference from `Drift`.

接口形状（C++，只有声明）：include/kci/view.hpp §16 Filter、§17 账本、§18 Drift、§19 GUI。
"""

import hashlib
import html
import itertools
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import api as api_mod
from . import errors, layout, repo_root
from . import re as re_mod
from . import run as run_mod
from .build import ARTIFACTS, Build, Builds
from .drift import Drift

# The page's own words, in two languages (`lib/i18n.py`).  `t` is imported by name
# so `python3 lib/i18n.py --check lib/gui.py` can see every key this file reads.
from .i18n import DEFAULT_LANG, LANGS, pick_lang, t
from .kbuild import KBUILD_JOB, SCAN, Kbuild, Kbuilds
from .kjob import Kjobs
from .re import Records
from .tests import DEFAULT_DEVICE, DEFAULT_LAB, DEFAULT_TESTS, TESTS

# A page waits this long for ONE API call - not the client's default 60s.  It is a
# wall-clock bound on that call and not the per-socket setting `requests` applies: a
# client configured for 5s waited 19.32s and returned happily, because that number
# bounded the gap between two packets and nothing else
# (docs/gui-rework/01-perf.md §F4b.1; `api._read` is where it became a deadline).
API_TIMEOUT = 10

# ... and this is what a whole page may spend on the API, in total.
#
# The comment above used to promise a page and deliver a call.  Two things were
# wrong with that, and both are measurements: `/worker` made *four* reads under this
# setting and took 39.2s, and any one of those reads could overrun the setting
# without raising.  The duplicate reads are gone (`api.begin_request`'s memo, and
# `Gui.job_node_rows` reading the queue once), so a page makes two API reads where
# it made four; and this number is one deadline per request, shared by every read
# that request makes, which is what "a slow upstream costs one slow page" has to
# mean to be true.
#
# It is 45s and not 10s because the API's own cost is what it is: `/count` costs
# 1.4-3.8s on its own, a `/nodes` page of 50 rows is 175 KB at 20-35 KB/s with a
# 1.2-3.7s floor even when it returns *nothing*, and `/remote` therefore "cannot be
# made under 1s cold, and no design should promise it" (§R4).  A page that gave up
# at 10s would show an empty table on every load.  The heaviest legitimate page
# measured 43.5s cold (BASELINE.md: /analysis, and 18s of that is two `.config`
# fetches from files.kernelci.org that step 6 caches on disk) - so this number has
# to come down with that cache, and it is written here rather than left for a
# reader to assume.  What it bounds is the tail: no page can now spend more than
# this plus one socket read already in flight.
API_BUDGET = 45
# How long the page reuses an API answer by default: `?ttl=`, and the value `?fresh=1`
# overrides.  Longer than `lib/api.py`'s `DEFAULT_TTL` (5 s) on purpose, and the
# measurement is in `_ttl_of`: an entry is stamped when it is *written*, so a cold
# page that took longer than 5 s left its own `/count` already stale and the next load
# paid for it again (carry-over C2: `/analysis` 4.44 s, `/worker` 1.81 s, where the
# third load is 0.012 s).  The local files are never cached at any value of this knob.
API_TTL_DEFAULT = 20
HOST = "127.0.0.1"
PORT = 8079
ROWS = 25
# How much of the worker's queue one read of it may look at.  `/worker` builds its
# platform/runtime/name boxes out of the same answer its table shows, so the read is
# as wide as the widest use of it and the *table* is the first `check.limit` rows of
# that one answer - asking `check.limit` and then asking `QUEUE_ROWS` is two reads of
# the largest collection in the API for one question (`01-perf.md` §F4).
QUEUE_ROWS = 200
REFRESH = 0

# **Which API a page reads is a condition of its question, not a preference.**  It
# decides which of the two statements ("what the API has") is being made, exactly as
# `tree` and `days` do, so it is one more URL key (`?api=`) - read per request, and
# carried by every link the way `tree` is.  It is deliberately *not* a cookie:
# `lang` is how this reader wants to be spoken to and may follow them from page to
# page, while "which data am I looking at" has to be visible in the address bar, or
# a bookmarked page answers a question its reader cannot see.  One piece of client
# state in this GUI, not two (`src/GUI.md` §4, §6).
API_LOCAL = "local"
API_PRODUCTION = "production"
API_LAUNCH = "launch"
# The two bases that have a name on every machine, taken from `lib/api.py`'s own
# constants rather than retyped: a second copy of an address is a second thing to
# keep in step.  `launch` - whatever `--api-url` / `$KCI_API_URL` / `LOCAL` resolved
# to for *this* process - is added by `Apis.entries()`, and only when it is neither
# of these two, so the box never offers the same address twice under two names.
API_NAMES = ((API_LOCAL, api_mod.LOCAL), (API_PRODUCTION, api_mod.PRODUCTION))
# The longest `?api=` this page will read.  A base is a scheme, a host and a path;
# 200 characters is past every host anyone runs, and an address nobody can read is
# not one an operator meant to type.
API_MAX = 200

# The buttons, by name.  Every one of them runs the command an operator would
# type; a page that runs something the runbook does not is a second interface.
# Reading a table needs no button: the page already is that table.
ACTIONS = ("index", "pull", "run", "runday", "fetch", "worker", "provision",
           "results", "drift")

# The `Run` kind each action starts (the vocabulary is `run.KINDS`; `table.py`
# covers the table's own writes, which is what index and provision are).
KINDS = {"index": "table", "provision": "table", "pull": "pull", "run": "run",
         "runday": "runday", "fetch": "fetch", "worker": "worker",
         "results": "results", "drift": "drift"}

# One write at a time: the ledger, the download tree and the table have one
# writer each, and two concurrent writers are how all three get corrupted.
WRITERS = ("index", "pull", "run", "runday", "fetch", "worker", "provision", "drift")
WRITE_KINDS = tuple(sorted({KINDS[one] for one in WRITERS}))

# The activity kinds that are bookkeeping rather than an answer to something the
# reader asked for: `table` is `index`/`provision` (the two "record this window"
# buttons), which run on a timer and are 37 of the 50 rows on this deployment.
# Folded by default, counted, and one click away - never filtered out: the fold is
# the page's own `kind` filter state (`04-actions.md` §P8a), so the box, the axes
# strip, `rows_of` and the 2 s poll all answer the same question.
FOLDED_KINDS = ("table",)
# The order the group captions are drawn in: the kinds an operator starts on purpose
# first, then the bookkeeping, then the ledger reads.  One tuple, so a kind this page
# has not heard of lands somewhere deliberate (last, not dropped) instead of
# alphabetically between two things that mean something.
KIND_ORDER = ("run", "runday", "pull", "fetch", "worker", "table", "results", "drift")

# The pages, in navigation order: (route, what it answers).
#
# Five words, and `/` is **builds**: one row per build id over the API's window
# and this machine's disk.  `/remote`, `/local` and `/pull` left the bar because
# they were three renderings of that one question - *for each build id, what does
# the API say, what do I hold, and what does the record claim?* - and the bar is a
# list of the questions this console answers, not of the tables it can draw.
PAGES = (("/", "builds"), ("/jobs", "jobs"), ("/runs", "runs"),
         ("/worker", "worker"), ("/analysis", "analysis"))

# The three pages that were the same question as `/`, and the key that says which
# side of it they were asking about.  A redirect and not a deletion: the operator's
# address bar, his bookmarks and every `?api=` link in his history still land on a
# page that answers - and the *key* is what carries the question, because `origin`
# was always the union's three sides (`ORIGINS`, `Filter.accepts`), so the merge
# needed no new query key at all.  `/pull` was the rows we could still fetch from
# that window, which is `origin=remote` plus the artifacts that are missing.
REDIRECTS = {
    "/remote": ("/", {"origin": "remote"}),
    "/local": ("/", {"origin": "local"}),
    "/pull": ("/", {"origin": "remote", "missing": "kernel,modules,kselftest"}),
}

# Every value a select box may offer.  Choosing is clicking: a page never asks
# for an id, a tree, a test or a number it could have offered.
#
# The last candidate of each numeric box IS the bound a hand-typed URL is
# clamped with, and both come from `lib/api.py`'s two constants: a box and a
# clamp written in two places drift apart, and these did - the box offered 500,
# the code allowed 500, and a URL could ask for 10**12.
MAX_LIMIT = api_mod.MAX_ROWS
MAX_DAYS = api_mod.MAX_WINDOW_DAYS
LIMITS = (25, 50, 100, 200, 500, MAX_LIMIT)
DAYS = (1, 3, 7, 14, 30, 90, 180, 365, 1095)
# `days=0` is a real choice, not a missing value: ask the API for this job's
# whole history (no `created__gte` at all).  It is spelled `all` in the box,
# because "(any)" on a number that means 30 days is a lie.
NO_WINDOW = 0
DAY_CHOICES = (NO_WINDOW, *DAYS)
DAY_LABELS = {"0": "all"}
ORIGINS = ("any", "local", "remote", "both", "card")
RANS = ("any", "never", "ever", "failing")
# `bytes` is the one value here that is not a `Local.state`: it is the only honest
# way to ask for "the artifacts are on disk, whatever the record says", which is
# what the numbers strip's `with bytes` chip counts and links to.  `pulled` needs
# an act and `unrecorded` is its complement *among rows that have bytes*, so
# neither of them can select that set over the union the page now draws.
EVIDENCE = ("any", "pulled", "unrecorded", "registered", "made-here", "empty", "bytes")
MODES = ("once", "resident")
JOB_STATES = ("", "available", "done", "running", "reserved", "closing")
VERDICTS = ("", errors.VERDICT_PASS, errors.VERDICT_FAIL,
            errors.VERDICT_INFRA, errors.VERDICT_ERROR)

# The trees the KernelCI pipeline's own config lists
# (`kernelci-pipeline/config/trees.yaml`, 50 entries at the time of writing).
# A floor, not a ceiling: the page must offer the same names on a machine that
# has never queried this API, and it must still accept a name typed by hand.
# The count is in this comment so a drift between the two lists is one diff away
# from being visible.
def _trees_from_config() -> tuple[str, ...]:
    """The tree names the vendored pipeline config lists, in its own order.

    Read with a regex instead of a YAML parser: one list is not worth a
    dependency, and a file that changed shape degrades to "no extra names"
    rather than an exception at import time.  The hard-coded list above is what
    the page needs to work at all; this is what keeps it honest when the
    checkout has the file.
    """
    path = os.path.join(repo_root(), "kernelci-pipeline", "config", "trees.yaml")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ()
    section = re.search(r"^trees:[ \t]*$", text, re.MULTILINE)
    if section is None:
        return ()
    found = []
    for line in text[section.end():].splitlines():
        if line.strip() and not line.startswith(" "):
            break                                   # the next top-level key
        name = re.match(r"^  ([A-Za-z0-9._+-]{1,64}):[ \t]*$", line)
        if name:
            found.append(name.group(1))
    return tuple(found)


def _branches_from_config(tree: str = "") -> tuple[str, ...]:
    """The branch names the vendored pipeline config binds to a tree, in its own order.

    `trees.yaml` names the trees; `trees/<tree>.yaml` names *that tree's* branches,
    and the binding is the whole point - it is the only place in this checkout where
    the two are connected, and it is what the branch box needs, because the API can
    filter by branch but cannot enumerate them (`02-filters.md` §A4).

    Read with a regex rather than a YAML parser, like `_trees_from_config` and for the
    same reason: one list is not worth a dependency, and a file that changed shape
    degrades to "no extra names" (`BRANCH_SEEDS`, the floor) rather than to an
    exception on a page.  For `tree=riscv` this returns `('fixes', 'for-next')` - the
    two names the API itself answered with (38 and 42 rows) - where the six seeds
    offered `main`, `master` and `linux-6.12.y`, none of which that tree has ever had.
    With no tree it returns the 76 distinct names of the config's 126 bindings.
    """
    base = os.path.join(repo_root(), "kernelci-pipeline", "config", "trees")
    if tree:
        names = [tree]
    else:
        try:
            names = sorted(one[:-5] for one in os.listdir(base) if one.endswith(".yaml"))
        except OSError:
            return ()                    # no vendored config: `BRANCH_SEEDS` is the floor
    found: list[str] = []
    for name in names:
        try:
            with open(os.path.join(base, f"{name}.yaml"), encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        for one in re.findall(r"^\s+branch:\s*['\"]?([A-Za-z0-9._+-]{1,64})['\"]?\s*$",
                              text, re.MULTILINE):
            if one not in found:
                found.append(one)
    return tuple(found)


TREES_FIXED = (
    "aaptel", "amlogic", "android", "ardb", "arm64", "arnd", "broonie-misc",
    "broonie-regmap", "broonie-regulator", "broonie-sound", "broonie-spi", "cip",
    "clk", "collabora-next", "efi", "hyperv", "kernelci", "khilman", "krzysztof",
    "kselftest", "lee-backlight", "lee-mfd", "linusw", "linux-pci", "mainline",
    "media", "media-committers", "mediatek", "net-next", "netdev-testing", "next",
    "omap", "padovan", "pm", "qcom", "qcom-next", "renesas", "riscv", "robh",
    "rppt", "sashal-next", "soc", "stable", "stable-rc", "stable-rt", "tegra",
    "thermal", "tip", "ulfh", "vireshk",
)

# What a name field offers before anything has been queried here: the fixed list
# plus whatever the vendored config adds.  Both are floors; the rows a page is
# showing are the ceiling, and `_vocabulary()` is where the two are merged.
TREES_KNOWN = TREES_FIXED + tuple(one for one in _trees_from_config()
                                 if one not in TREES_FIXED)

# Branches cannot be enumerated: `Api.nodes()` filters by branch but has no way
# of listing them (`lib/api.py`).  These are a typing convenience for the trees
# this deployment reads, and the page says so instead of pretending they are all.
# The mapping, so the next reader does not have to guess: `main` is what this
# deployment's cards carry, `master` the mainline and linux-next trees, `for-next`
# the riscv/arm64/soc ones, `linux-X.Y.y` the stable ones.
BRANCH_SEEDS = ("main", "master", "for-next", "linux-next", "linux-6.6.y",
                "linux-6.12.y")

# The one order filter keys are written in, so two links that mean the same thing
# look the same.  `offset` is deliberately absent: it is page state, not a
# condition, and every link but a pager starts the list over.  `api` is first
# because it is the widest condition there is - it says which API the other
# thirteen are asked of - and because a URL reads better when it opens with the
# answer to "where is this page looking".
FILTER_ORDER = ("api", "tree", "branch", "arch", "defconfig", "compiler",
                "state", "result", "days", "limit", "test",
                "ran", "verdict", "evidence", "origin", "missing", "has", "text",
                "sort")

# The orders `/analysis` can put its two lists in, as the values a URL carries.
#
# **The sort is a condition, not page state.**  The operator's model: "筛选决定了
# 下面的构建是哪些，排序决定了这个构件以什么样的方式排序…排序决定了它以前一个序和后
# 一个序进行一个比较" - the adjacent delta of a row is *defined by* the order, so a link
# that dropped the sort would compare two other builds than the URL states.  That is
# the class of bug `_tick_link` exists to prevent, so `sort` is a `Filter` field (every
# link, chip and command carries it for free) and is read by `/analysis` alone.
#
# `""` is the page's own default order and means "newest first" (`date`), which is the
# order a reader picks the newest builds from.  `date-asc` is the same list the other
# way round, which a timeline reads forward in.
#
# **`delta` is deliberately not a sort key**, although `06-analysis.md` §B lists one:
# "sort by how much the configs differ" would have to read N-1 config pairs *before*
# there is an order to read them in, and the order is what decides which pairs those
# are - a circular dependency, and an unbounded cost (four rows cost ~41 s cold, §D2).
# `same-branch` is the cheap version of the same question: it puts the rows a
# comparison means something between next to each other, which is the fact §A7
# measured (two branches of one tree drift 363/538/92; adjacent builds of one branch
# drift 0/0/0).
SORTS = ("", "date", "date-asc", "same-branch", "verdict", "build")

# The keys an order may be built from, in the order the control offers them, each with
# the direction it defaults to and the field it reads.  This is the *vocabulary*: the
# operator's ask this round was 「排序功能可能会有多个这种排序日期分支什么那些数啊」 -
# several keys at once, each with its own direction - and one table is what keeps the
# parser, the control, the labels and the sorter from inventing three vocabularies.
#
# `tree-branch` is the operator's 总分支 (tree, then branch) as one key, because "which
# tree, and inside it which branch" is how he groups builds; `series` is the kernel
# series a describe string names (`_series_of`).
SORT_KEYS = {
    "date": ("desc", "date"),
    "tree": ("asc", "tree"),
    "branch": ("asc", "branch"),
    "tree-branch": ("asc", "tree-branch"),
    "series": ("asc", "series"),
    "verdict": ("asc", "verdict"),
    "id": ("asc", "id"),
}

# What a URL that names no order means, and what the round-1 spellings mean.  A
# bookmark written against the old control keeps working, which is the same promise
# `REDIRECTS` makes for the old routes.
SORT_ALIASES = {
    "": (("date", "desc"),),
    "date": (("date", "desc"),),
    "date-asc": (("date", "asc"),),
    "build": (("id", "asc"),),
    "same-branch": (("tree-branch", "asc"), ("date", "desc")),
    "verdict": (("verdict", "asc"), ("date", "desc")),
}

# How many rows of that order may spend a config read on their neighbours: three by
# default, twelve at most.  Clamped on the server, never trusted from the URL.
#
# **The cap follows a measurement taken for this round, not round 1's estimate.**
# `09-VERIFY.md` K14 found the two documents disagreeing by ~20x about what one comparison
# costs (`05-regression.md` inherited 7.5-12.5 s / ~194 KB from round-1 `06-analysis.md`
# §D2; `04-analysis.md` F4 measured 0.4 s cold), so it was re-measured on today's artifact
# store before either number was used: **2.17 s cold for a pair** (two `.config` files
# fetched over the public API, first time - the network, not the parse) and **0.04 s** the
# second time, because `var/configs/` then holds both files (42 of them on this workspace).
# So a row's `delta` buys `delta - 1` pairs and a page pays 2 x delta cold reads at most:
# the default 3 is ~6 s worst case and 12 is ~26 s, which is the largest value still inside
# the budget the page's own API read already lives in.  Round 1's number would have argued
# for 24 (~52 s cold), which is why the measurement mattered.
DEFAULT_DELTA = 3
MAX_DELTA = 12

# What each route reads.  A self-link (`×` on a chip, a preset, a filter
# re-submitted) must carry all of it: dropping a key nobody asked to drop is how
# a page starts answering a question its URL does not state.  `/runs` reads two
# keys that are not `Filter` fields at all, and says so here.
# `api` rides along on every route, including the two that never ask the API
# (`/runs`): it is the one condition a reader must not lose by walking through a
# page that has no use for it - the merged builds page on production, one click into
# `/runs` and back, used to land on the local stack again.
ROUTE_KEYS = {
    "/": FILTER_ORDER + ("lang",),
    "/jobs": FILTER_ORDER + ("lang",),
    "/runs": ("kind", "state", "api", "lang"),
    "/worker": ("state", "job", "text", "limit", "mode", "platform", "runtime",
                "api", "lang"),
    "/analysis": ("test", "limit", "older", "newer", "pick", "point", "delta", "api",
                  "lang", "sort"),
    # The single-build view is the same page's keys plus `vs` and the build id in the
    # path.  It is spelled with a trailing slash because `_url` resolves a route by
    # longest prefix: a link from a comparison carries **the order and the filter it was
    # made under**, which is what makes its two neighbour doors mean what the row meant.
    "/analysis/": ("test", "limit", "pick", "point", "delta", "api", "lang", "sort", "vs"),
}

# What a page hands on when the reader leaves it.  Smaller than `ROUTE_KEYS` on
# purpose: whoever moves from `/jobs` to the merged builds page wants the window,
# not the verdict they typed on the jobs page.  This is the §2 carry table.
#
# `/` carries the union of the three pages it replaced - the conditions the three
# of them read are now the conditions of one table, and a nav link that dropped
# `origin` or `evidence` would land the reader on a different question than the
# one they were looking at.
#
# **Nothing may index this dict outside a function body.**  A default argument is
# evaluated at *import*, so `def link(..., carry=NAV_KEYS["/remote"])` - which is
# what the deleted `/pull` link used to be - does not fail when it is called: it
# fails when the module is loaded, and it takes every route in both languages down
# with a `KeyError: '/remote'`.  `compileall` cannot see it (a default is not
# compiled away, it is evaluated) and a browser cannot see it either, because the
# still-running process holds the previous module.  `python3 -c "import lib.gui"`
# is the check, and `docs/gui-rework/tools/test_form_body.py` imports the module,
# so it is a canary for exactly this.  Reading one of these tables inside a
# function - `NAV_KEYS.get(route, ())`, `ROUTE_KEYS.get(route, ())` - is a value
# looked up when it is wanted, which is what a table that pages are removed from
# needs.  (`WRITE_KINDS` below is the deliberate opposite: `KINDS` and `WRITERS`
# are one hand-written pair, and an inconsistent pair must fail loudly at startup
# rather than quietly let a write action bypass the one-writer lock.)
#
# The other half of the same lesson, learned twice in one merge: a call to a helper
# that does not exist *yet* compiles and imports perfectly - the helpers in this file
# are defined below the methods that call them, which is fine at runtime because the
# call happens inside a function body - so a page that calls a half-written helper is
# fine until a request arrives, and the module still starts.  `ruff`'s `F821` is what
# sees that one (`_job_tick` was undefined on `/jobs` for a few edits while the module
# imported cleanly), which is why both checks run after every edit and before any
# restart, together with `docs/gui-rework/tools/test_form_body.py` - that file imports
# this module *and* exercises it, so it is a canary for both failures at once.
NAV_KEYS = {
    "/": ("tree", "branch", "days", "limit", "api", "origin", "missing", "has",
          "evidence", "lang"),
    "/jobs": ("tree", "branch", "days", "limit", "test", "api", "lang"),
    "/runs": ("api", "lang"),
    "/worker": ("tree", "limit", "api", "lang"),
    "/analysis": ("tree", "limit", "test", "api", "lang"),
}

# The words the stylesheet has a colour for, one entry per pill kind.  The value
# itself is never translated: `pass`, `running`, `pulled` are the values the code
# compares, and the class is the value - a second vocabulary would drift.
PILL_WORDS = {
    "verdict": (errors.VERDICT_PASS, errors.VERDICT_FAIL, errors.VERDICT_INFRA,
                errors.VERDICT_ERROR),
    "run": ("running", "done", "failed", "cancelled"),
    "evidence": tuple(one for one in EVIDENCE if one != "any"),
    "job": tuple(one for one in JOB_STATES if one),
}

# What the numbers mean, said once instead of implied by a box: `rows` is what
# this page prints, the window is what chooses the rows.  Two different things, and
# the page that confused them is why the numbers strip prints both as numbers
# (`{n} of {kept}` and `rows={limit}`) instead of as a sentence about itself.  The
# sentence that used to live here (`ROWS_NOTE`) was printed under four tables and
# read by nothing; `05-i18n-prose.md` §B.1 is the rule it broke.

# The presets `_quick` writes as links.  Its two numeric callers are gone: `days` and
# `rows` carry their sets in `data-stops` now, so the page's script builds one rail per
# field instead of printing ten and six buttons under them (the operator's "而不是多个
# 直接列出来").  What is left is the API box's two names and the worker's mode,
# platform and runtime, where a link per value is still the right shape - each of those
# is a *choice about a command line*, and a URL is the state.
# `DAY_LABELS` renames one value for a reader ("0" -> "all"); every other preset is its
# own label, which is what a reader expects on a number.
DAY_PICK = tuple((DAY_LABELS.get(str(one), str(one)), str(one)) for one in DAY_CHOICES)

# Every word list a select box offers, as `value -> catalogue key of its label`.
#
# The value is what the code compares and what the stylesheet colours, so it is
# never translated; the label is what a reader sees and is.  Every list is here,
# including the four whose two columns are deliberately identical (`pass`, `done`,
# `running`, ...): `judge`'s verdicts and the API's job states are one vocabulary
# spoken by `Records` and `publish`, and a page that re-spelled them would be the
# second implementation of a verdict src/GUI.md §5 forbids - the pill next to the
# label shows the same word on purpose.  `any` is shared, because "no condition at
# all" is one word wherever it is offered.
_LABELS: dict[str, dict[str, str]] = {
    "evidence": {"any": "state.any", "pulled": "evidence.label.pulled",
                 "unrecorded": "evidence.label.unrecorded",
                 "registered": "evidence.label.registered",
                 "made-here": "evidence.label.made_here", "empty": "evidence.label.empty",
                 "bytes": "evidence.label.bytes"},
    "origin": {"any": "state.any", "local": "origin.label.local",
               "remote": "origin.label.remote", "both": "origin.label.both",
               "card": "origin.label.card"},
    "ran": {"any": "state.any", "never": "ran.label.never", "ever": "ran.label.ever",
            "failing": "ran.label.failing"},
    "verdict": {"pass": "verdict.label.pass", "fail": "verdict.label.fail",
                "incomplete": "verdict.label.incomplete", "error": "verdict.label.error"},
    "mode": {"once": "mode.label.once", "resident": "mode.label.resident"},
    "job_state": {"available": "job_state.label.available", "done": "job_state.label.done",
                  "running": "job_state.label.running",
                  "reserved": "job_state.label.reserved", "closing": "job_state.label.closing"},
    "run_state": {"running": "run_state.label.running", "done": "run_state.label.done",
                  "failed": "run_state.label.failed", "cancelled": "run_state.label.cancelled"},
}


def _labels(kind: str, lang: str) -> dict[str, str]:
    """One word list's labels in `lang`: `{"pulled": "有拉取记录", ...}`.

    A value the list does not name falls back to the value itself (`_option` does
    that), so an API that grows a state loses its translation and not its box.
    """
    return {value: t(lang, key) for value, key in _LABELS[kind].items()}


def _day_choices(lang: str) -> tuple[tuple[str, str], ...]:
    """`DAY_PICK` with `0` spelled in this language - the value stays `0`.

    `no window at all` is a real choice rather than a missing value, and a reader
    choosing it reads a word, not a number (`filter.day_all` is `all` in English).
    """
    return tuple((t(lang, "filter.day_all") if value == str(NO_WINDOW) else label, value)
                 for label, value in DAY_PICK)


# ---------------------------------------------------------------------------
# Reading forms and queries
# ---------------------------------------------------------------------------

# What may reach a command line: a name this tree could have offered itself.
# `_named()` and `_token()` both go through it, so a tree, a branch, a test name
# and a build id are held to the same alphabet.
TOKEN = re.compile(r"[A-Za-z0-9._+-]{1,64}")


def _first(form: Mapping[str, list[str]], key: str, default: str = "") -> str:
    """One value of a form or a query string, or the default when it is absent."""
    values = form.get(key) or []
    return values[0] if values and values[0] else default


def _numbers(form: Mapping[str, list[str]], key: str, default: int) -> int:
    """One integer out of a form or a query string, or the default when it is not one.

    The bound is the caller's: `Filter` knows what a window and a row cap may be,
    and `command()` clamps with the same two, so neither has to guess.
    """
    try:
        return int(_first(form, key, str(default)))
    except ValueError:
        return default


def _clamp(value: int, low: int, high: int) -> int:
    """A number inside its bound: a hand-edited URL is a value to fix, not a 500."""
    return min(high, max(low, int(value)))


def _tests_of(check: "Filter") -> tuple[str, ...]:
    """The tests a page's rows are one per: the chosen one, or the catalogue's default set.

    One spelling of the rule, so the rows a page prints and the `re.todo()` count
    it quotes against are about the same pairs.
    """
    return (check.test,) if check.test in TESTS else DEFAULT_TESTS


def _ticks(form: Mapping[str, list[str]]) -> list[str]:
    """The ticked rows as build ids - the only ids a page sends, and they were clicked."""
    return [one for one in (_token(one) for one in (form.get("selected") or [])) if one]


def _token(value: str) -> str:
    """A value that may reach a command line: short, ASCII, and only boring characters.

    The character class is spelled out rather than asked of `str.isalnum()`, which
    is Unicode-aware: it answered True for `树`, so a name that is not ASCII went
    through this check and into an argv.  Nothing here needs a non-ASCII name, and
    `/` stays out, so `../../etc` is refused too.
    """
    value = str(value or "")
    return value if TOKEN.fullmatch(value) else ""


def _chosen(form: Mapping[str, list[str]], key: str, options: Iterable[str], default: str,
            lang: str = DEFAULT_LANG) -> str:
    """A select box's value: one of the options, or the default, never something typed."""
    value = _first(form, key)
    if not value:
        return default
    if value not in options:
        raise errors.ConfigError(t(lang, "error.not_an_option", key=key, value=repr(value),
                                   options=", ".join(one or t(lang, "state.any_paren")
                                                     for one in options)))
    return value


def _named(form: Mapping[str, list[str]], key: str, lang: str = DEFAULT_LANG) -> str:
    """A free-ish field (a tree, a branch): its value, refused when it is not a plain name."""
    value = _first(form, key)
    if value and not _token(value):
        raise errors.ConfigError(t(lang, "error.not_a_name", key=key, value=repr(value)))
    return value


def _artifacts(value: str) -> tuple[str, ...]:
    """A query's artifact list: our artifact names, comma or space separated, unknown ones dropped."""
    return tuple(name for name in (one.strip() for one in (value or "").replace(",", " ").split())
                 if name in ARTIFACTS)


def _flag(name: str, value: str) -> list[str]:
    """`--name value`, or nothing at all when the value is empty."""
    return [name, value] if value else []


def _pairs(name: str, values: Iterable[str]) -> list[str]:
    """`--name v` for every value - how one flag carries a whole selection."""
    return [part for value in values for part in (name, value)]


def _api_url(value: str) -> str:
    """One `?api=` value as an API base URL - `""` when this page refuses it.

    Refused, and why each one is refused rather than repaired:

    * **only `http` and `https`**: a base is an address a client is pointed at, and
      a scheme this page cannot talk is not one.  `file:///etc/passwd`,
      `javascript:alert(1)` and `ftp://x/` all die on the scheme, which is the only
      thing any of them has in common with an API;
    * **a non-empty host**: `http://` alone names nothing, so it is nothing;
    * **at most `API_MAX` characters**, and **printable ASCII only**: an address
      with a newline, a space or a non-ASCII host is not an address an operator
      typed, and this string ends up in an argv (`--api-url`) where a stray
      whitespace is a second argument.

    A refusal is *not* an error page: the caller falls back to the base this
    deployment started on and the page answers 200, because a hand-edited URL is a
    normal way of asking and a page that dies on one tells its reader nothing.  The
    value is also **not** remembered - `Filter.api_raw` carries it only far enough
    for the clamp note to say it was dropped.

    The name form (`local`, `production`, `launch`) is not a URL and never reaches
    here: `Apis.base()` looks a name up first and asks this only about a literal.
    """
    value = str(value or "")
    if not value or len(value) > API_MAX:
        return ""
    if any(one <= " " or one > "~" for one in value):
        return ""
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return value.rstrip("/")


@dataclass(frozen=True)
class Apis:
    """The API bases one page can name, and the base this process started on.

    One object because three lookups have to agree: a `?api=` value may be a *name*
    (`local`, `production`, `launch`) or a literal `http(s)` URL; turning either into
    "the base this page reads" and back into "the value its links carry" is one
    question, and a link that answered it differently from the page it points at is
    a link that lies.

    `launch` is `Api.url()`'s answer for this process (`--api-url`, `$KCI_API_URL`,
    else `lib/api.py`'s `LOCAL`), and it is what an *empty* `api` key means - which
    is why `key(launch) == ""`.  A page whose URL carries no `api=` therefore
    renders, link for link, byte for byte what it rendered before this key existed,
    and `?api=local` on a machine that started on the local stack is that same page
    rather than a second one.

    Frozen and built per call: it is a value derived from the process's own startup,
    so nothing may write to it and no request may leave anything in it.
    """

    launch: str = ""
    names: tuple[tuple[str, str], ...] = API_NAMES

    def entries(self) -> tuple[tuple[str, str], ...]:
        """Every base a box may offer, in offer order: the two names, then `launch`.

        `launch` is left out when it is one of the other two, so the same address
        never appears twice under two names - `local` on a machine that started on
        the local stack is the launch base, and that is the whole of it.
        """
        if self.launch and self.launch not in [base for _, base in self.names]:
            return (*self.names, (API_LAUNCH, self.launch))
        return self.names

    def name(self, base: str) -> str:
        """This base's name here, or `""` for a base we have no name for."""
        for name, one in self.entries():
            if one == base:
                return name
        return ""

    def base(self, value: str) -> str:
        """A name or a literal URL as a base URL; `""` when this page knows neither.

        An *empty* value is the base this process started on - that is what an absent
        `api` key means, and it is why `api_base(check)` can be asked about a filter
        that never mentioned an API.  A value that is neither empty nor resolvable is
        a different thing and stays `""`: the caller has to be able to tell "nothing
        asked" from "something refused", or the clamp note cannot say which.

        Names first, so `?api=production` and `?api=https://api.kernelci.org` are the
        same request - which is what lets the page *print* the address and *write*
        the short name without the two ever drifting apart.

        `launch` is answered even on a machine where it is not *offered* (a box that
        listed it beside `local` would be offering one address under two names): a
        reader who guessed the third name meant the base this process started on, and
        that is what they get - the default, not a complaint.
        """
        if not value:
            return self.launch
        if value == API_LAUNCH and self.launch:
            return self.launch
        for name, one in self.entries():
            if name == value:
                return one
        return _api_url(value)

    def key(self, base: str) -> str:
        """A base as the value a URL carries: its name, else the URL itself.

        `""` for the launch base (and for no base at all): the key is left out of a
        URL when it says nothing the URL does not already mean.
        """
        if not base or base == self.launch:
            return ""
        return self.name(base) or base

    def of(self, value: str) -> str:
        """A `?api=` value as the canonical key a page carries - one call, one answer.

        Every spelling of one base comes back the same: `production` and
        `https://api.kernelci.org` both become `production`, `?api=local` on the
        local stack becomes `""`, and a value this page refuses becomes `""` too
        (the fallback is `launch`, and `launch` is what an empty key means).
        """
        return self.key(self.base(value))


# The API's own filter vocabulary, as `Filter` key -> `{node kind: the path the key
# has on the wire}`.  **Only what is here may reach a query.**  The API answers an
# unknown key with `0` and HTTP 200 - `tree=riscv`, `sort=created`, `arch=riscv` and
# `debug.foo` were all measured at 0 with no error - so a typo and an empty answer are
# the same response, and this table is the only thing that tells them apart
# (`docs/gui-rework/02-filters.md` §A1.3, §B7).
#
# A kind absent from a row is a kind this page must never send that key to:
# `data.arch` against `kind=job` is a 90-second full scan (measured, the `node`
# collection has no indexes), not a filter.  The entries are the ones measured on
# this deployment: `kind=kbuild` answers `data.kernel_revision.tree` (80 of 1782),
# `data.kernel_revision.branch` (44), `data.arch`/`data.compiler`/`data.defconfig`
# (1771 each - real, and nearly a no-op), `result` (1715 pass) and `state`.
API_FILTERS: dict[str, dict[str, str]] = {
    "tree": {"kbuild": "data.kernel_revision.tree"},
    "branch": {"kbuild": "data.kernel_revision.branch"},
    "arch": {"kbuild": "data.arch"},
    "defconfig": {"kbuild": "data.defconfig"},
    "compiler": {"kbuild": "data.compiler"},
    # `state` is a real top-level node field, and its offer list has to come from the
    # *kind*: every one of the 170 780 kbuild nodes on production is `state=done`, and
    # `state=available` - the state the scheduler parks a job in for pull-lab workers
    # to claim (`kernelci-pipeline/src/scheduler.py:995-998`) - answers **0** there.
    # One global list is how `available` became a choice that silently answered 0.
    "state": {"kbuild": "state", "job": "state"},
    "result": {"kbuild": "result"},
}

# `state`'s offer list per kind, from the measurement above: a kbuild is `done` for
# the whole of its finished life and `running` while it is being built, and it is
# never `available`; a job is the opposite (that is what the worker claims).
KBUILD_STATES = ("", "done", "running")
# `ResultValues` (`kernelci-core/kernelci/api/models.py:55`), the vocabulary a node's
# `result` is drawn from.  Offered as a select so an invented value cannot answer 0.
RESULTS = ("", "pass", "fail", "skip", "incomplete")

# The page's own axes (page state rather than `Filter` fields) -> the catalogue key of
# the word the strip prints for them.  A name that is not here prints as itself, which
# is the rule `word.*` already follows for the page's own vocabulary: `kind`, `state`
# and `mode` are the code's words, and a second spelling of them would drift.
AXIS_LABELS = {"kind": "word.kind", "state": "word.state", "mode": "filter.mode",
               "platform": "word.platform", "runtime": "word.runtime",
               "job": "filter.name", "older": "filter.older", "newer": "filter.newer",
               "test": "word.test", "ran": "filter.ran", "verdict": "filter.verdict",
               "evidence": "filter.evidence", "origin": "filter.origin",
               "missing": "filter.missing", "point": "filter.point", "delta": "delta.cap"}

# How many value axes may have their own `/count` on one page (`Gui._axis_counts`).
# The count is what makes `arch=riscv` visibly a near-no-op instead of a filter that
# looks like it worked, and it is not free: one `/count` per axis in force, on the one
# API this deployment has (0.4-4.4 s measured, 20-35 KB/s).  Past this many axes the
# strip prints values with no badges - fewer numbers, never a made-up one.
MAX_AXIS_COUNTS = 3


def _iso_days(days: int) -> str:
    """The ISO-8601 timestamp `days` days back (UTC, seconds) - the window's own value.

    The same rule as `lib/kbuild.py::_iso_ago`, written here because this is the file
    that *prints* the query: the page shows `created__gte=<this>`, and a line that
    quotes a window it did not send would be the paraphrase `02-filters.md` §A3 is
    about.  The clamp is the second guard and not decoration: an absurd `days` reaches
    `time.gmtime` as an epoch outside the platform's range and comes back as
    `OSError: [Errno 75]`, which on a page is an HTTP 500.
    """
    days = _clamp(int(days), NO_WINDOW, MAX_DAYS)
    if days <= 0:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))


def _api_query(check: "Filter", kind: str = "kbuild") -> list[tuple[str, str]]:
    """The key/value pairs this page really sends, in the order it sends them.

    One function, three readers: the read itself (`Gui.remote_rows`, which hands these
    pairs to `Kbuilds.getdays(extra=…)`), the line the page
    prints as its question (`Gui.remote_query`), and the per-axis counts the axes strip
    badges (`Gui._axis_counts`).  They used to be a paraphrase plus a read: the line
    said `job=` where the key is `name=`, `tree=` where it is
    `data.kernel_revision.tree=`, and `no window (all)` where the query simply had no
    `created__gte` - and an operator who copied `tree=riscv` out of it got **0**,
    because `tree` is not a key the API has (`02-filters.md` §A3).  This line is the
    query an operator copies into a command (`src/GUI.md` §1.5), so it prints the
    wire's own spelling.

    Only keys in `API_FILTERS` for this `kind` are emitted, in `FILTER_ORDER`, so a
    value this deployment has no verified path for is never sent and never printed:
    the API's silent `0` is the failure mode a whitelist exists to prevent.
    """
    pairs: list[tuple[str, str]] = [("kind", kind), ("name", KBUILD_JOB)]
    window = _iso_days(check.days)
    if window:
        pairs.append(("created__gte", window))
    for name in FILTER_ORDER:
        path = API_FILTERS.get(name, {}).get(kind, "")
        value = str(getattr(check, name, "") or "")
        if path and value:
            pairs.append((path, value))
    return pairs


def _query_text(pairs: Iterable[tuple[str, str]]) -> str:
    """`_api_query`'s pairs as the one line a reader can paste into a command."""
    return " ".join(f"{key}={value}" for key, value in pairs)


@dataclass
class Filter:
    """The tables' filter: every column can be one, and every one of them is chosen."""

    tree: str = ""
    branch: str = ""
    arch: str = ""
    defconfig: str = ""
    compiler: str = ""
    # The node's own two value fields, offered with the offer list their *kind*
    # answers for (`API_FILTERS`, and `docs/gui-rework/02-filters.md` §A2).  They are
    # not in `VERDICTS`/`JOB_STATES`: a kbuild node's `state` and its `result` are the
    # API's own vocabulary, and `state=available` - a value that exists on `kind=job`
    # and answers **0** on `kind=kbuild` - is why one global list was the wrong shape.
    state: str = ""
    result: str = ""
    job: str = ""
    days: int = NO_WINDOW             # 0 = no window: the job's whole history
    origin: str = "any"              # any | local | remote | both
    has: tuple[str, ...] = ()        # artifacts the row must have (of ARTIFACTS)
    missing: tuple[str, ...] = ()    # artifacts the row must be missing
    ran: str = "any"                 # any | never | ever | failing
    test: str = ""                   # narrows ran and verdict to one test
    verdict: str = ""                # the most recent verdict is this one
    evidence: str = "any"            # what the pull record says (EVIDENCE)
    text: str = ""
    limit: int = 50
    offset: int = 0
    # The order `/analysis` puts its rows in, and the reason it is a `Filter` field
    # and not page state like `pick` (see `SORTS`): a row's adjacent delta is defined
    # by the order, so every link that keeps the row has to keep this too.  `""` is
    # the page's own default, decided by the renderer and not by the filter.
    sort: str = ""
    # What the query string asked for, when it asked at all (`None` = it carried
    # no such key).  The clamped `days`/`limit` above are what every reader uses;
    # these two exist so a clamp can be *printed* instead of quietly obeyed.
    asked_days: int | None = None
    asked_limit: int | None = None
    # Which API this page reads, as the value a URL carries: `""` for the base this
    # process started on, else a name (`local`, `production`, `launch`) or a literal
    # `http(s)` URL.  A condition like `tree`, and the first one in `FILTER_ORDER`:
    # it decides which API the other thirteen are asked of.
    api: str = ""
    # The base `api` resolves to here, **default included**: the address this page
    # really reads, which is what the axes strip's `api` axis prints.  `api` is the
    # *key* a URL carries and is empty on the startup base by design (`Apis.key`), so
    # a strip built from the key could not say which API is in force - which is how
    # `?api=production` came to render byte-identically to no `api` key at all when
    # the process started on production (`02-filters.md` §A5).  It never enters a URL:
    # `to_query()` does not read it.
    api_base: str = ""
    # What `?api=` said on the one occasion this page threw it away - a name nobody
    # here has, or a string that is not an address (`_api_url`).  Kept only so the
    # clamp note can say so out loud: a value silently swapped for the default is how
    # a reader ends up looking at another API without being told.
    api_raw: str = ""
    # What `?api=` said *whenever it said anything*, resolvable or not.  `api` is
    # empty for the base this process started on (that is `Apis.key`'s design, and it
    # is right: it keeps today's URLs unchanged), so `?api=production` on a production
    # process and a URL with no `api` key at all are one filter - and the axes strip
    # then printed one page for two different requests.  The reader *did* state which
    # API they meant; this remembers that they did, so the strip can mark the axis as
    # stated and offer to drop it.  It never enters a URL (`to_query()` does not read
    # it) and it is not a condition: the base in force is `api_base`.
    api_given: str = ""
    # The same fact for `?test=`: `one_of` below drops a value that is not one of
    # `TESTS`, and until this field existed it did it in *silence* - `?test=kbuild`
    # rendered as if nothing had been asked for at all, with no banner and the box
    # back on "(any)" (`04-actions.md` §5a, reproduced).  A value the page cannot
    # honour is a fact about the reader's URL, so it is reported, never swallowed.
    test_raw: str = ""
    # The same fact again for `?sort=`: an order is a *list* of keys now (`_sort_keys`),
    # and a component nobody knows is dropped rather than obeyed - so the raw value is
    # kept, to be printed by `clamps`.  A URL that named a round-1 spelling
    # (`same-branch`) is not a refusal: that is an alias and means what it always meant.
    sort_raw: str = ""
    # How many rows of the order may spend a config read on their neighbours.  It was
    # read by the renderer alone (`_clamp(_numbers(query, "delta", DEFAULT_DELTA), 0,
    # MAX_DELTA)`), so it was in no `Filter` and therefore in no link - and the walls
    # between the list and one comparison (`_compare_url`) are built from a `Filter`.
    # A comparison read out of the context it was made in is a different comparison.
    delta: int = 0
    # Page state that is not a filter: the two builds to compare (`/analysis`), and
    # the rows a link asked to pre-tick on the pull page.
    pick: tuple[str, ...] = ()
    tick: tuple[str, ...] = ()

    @classmethod
    def from_query(cls, query: Mapping[str, list[str]], lang: str = DEFAULT_LANG,
                   apis: "Apis | None" = None) -> "Filter":
        """A query string as a filter; unknown keys are ignored, numbers clamped.

        `lang` is here for one reason: a value nothing offered is refused with a
        sentence, and a page that refuses in English while showing Chinese is a page
        that changed language halfway through.  `?lang=` itself is not a filter.

        `apis` is here for the same kind of reason: `?api=` may name a base
        (`production`) or spell it out (`https://api.kernelci.org`), and only this
        deployment knows which names mean which addresses.  Both spellings land on
        the same `api` key, and a value nobody here recognises - or one that is not
        an address at all - is *ignored*: the filter comes back on the startup base,
        with `api_raw` remembering what was dropped so the page can say so instead of
        quietly answering a question nobody asked.
        """
        apis = apis if apis is not None else Apis()
        raw_api = _first(query, "api")
        api_base = apis.base(raw_api)

        def one_of(key: str, options: Iterable[str], default: str) -> str:
            value = _first(query, key)
            return value if value in options else default

        def asked(key: str) -> int | None:
            """The number the query carried, or None when it carried none at all."""
            return _numbers(query, key, 0) if _first(query, key) else None

        # The clamp is what keeps `?days=1000000000000` from reaching
        # `time.gmtime` (an OSError there was an HTTP 500) and `?limit=-1` from
        # reaching `[:limit]` (which cut the *newest* rows off the list).
        raw_days, raw_limit = asked("days"), asked("limit")
        days = _clamp(raw_days if raw_days is not None else NO_WINDOW, NO_WINDOW, MAX_DAYS)
        limit = _clamp(raw_limit if raw_limit is not None else 50, 1, MAX_LIMIT)
        return cls(tree=_named(query, "tree", lang), branch=_named(query, "branch", lang),
                   arch=_named(query, "arch"), defconfig=_named(query, "defconfig"),
                   compiler=_named(query, "compiler"), state=_named(query, "state"),
                   result=_named(query, "result"),
                   job=_first(query, "job"), days=days,
                   # **The cards are what `/` shows when nothing is asked.**  The
                   # operator's ask this round was 「专门搞一个存卡片的地方，就是默认显示
                   # 全部卡片」, and the page that holds every card is this one with
                   # `origin=card` - so that is the default, and `?origin=any` is how a
                   # reader asks for the union (the API's window and this disk together).
                   # The three union readers that are *not* pages pin it themselves:
                   # `summary`, `remote_query` and every internal `Filter(…, origin="any")`
                   # fallback, so the machine interface keeps its contract and the gap the
                   # strip counts is still counted over everything.
                   origin=one_of("origin", ORIGINS, "card"),
                   has=_artifacts(_first(query, "has")),
                   missing=_artifacts(_first(query, "missing")),
                   ran=one_of("ran", RANS, "any"),
                   test=one_of("test", TESTS, ""),
                   verdict=one_of("verdict", VERDICTS, ""),
                   evidence=one_of("evidence", EVIDENCE, "any"),
                   text=_first(query, "text"), limit=limit,
                   offset=max(0, _numbers(query, "offset", 0)),
                   sort=_sort_spec(_first(query, "sort")),
                   sort_raw=_sort_refused(_first(query, "sort")),
                   delta=_clamp(_numbers(query, "delta", DEFAULT_DELTA), 0, MAX_DELTA),
                   asked_days=raw_days, asked_limit=raw_limit,
                   api=apis.key(api_base), api_base=api_base, api_given=raw_api,
                   api_raw=raw_api if (raw_api and not api_base) else "",
                   test_raw=(_first(query, "test")
                             if _first(query, "test") not in TESTS else ""),
                   pick=tuple(_token(one) for one in (query.get("pick") or []) if _token(one)),
                   # `tick` is a comma list and not a repeated key for the same reason
                   # `missing`/`has` are (`_url` collapses a repeated key through a dict):
                   # "re-tick the rows whose pull failed" is one link, and one link that
                   # carries forty ids has to be one value.
                   tick=tuple(one for value in (query.get("tick") or [])
                              for one in (_token(part) for part in str(value).split(","))
                              if one))

    def clamps(self, lang: str = DEFAULT_LANG) -> list[str]:
        """The values this query asked for and did not get, in words.

        Empty when nothing was clamped.  A page that silently shows 1000 rows
        where 5000 were asked for has changed the operator's question without
        saying so, which is the one thing a filter may never do.  An `?api=` this
        deployment cannot resolve is the same kind of fact: the page reads the base
        it started on, and the reader is told which value was dropped.

        The dropped value is escaped here and not by the caller because it is the one
        entry in this list that is not a number: it is whatever a hand-typed URL said.
        """
        notes = []
        if self.asked_limit is not None and self.asked_limit != self.limit:
            notes.append(t(lang, "filter.capped_rows", limit=self.limit,
                           asked=self.asked_limit))
        if self.asked_days is not None and self.asked_days != self.days:
            notes.append(t(lang, "filter.capped_days", days=self.days,
                           asked=self.asked_days))
        if self.api_raw:
            notes.append(t(lang, "filter.api_refused", value=html.escape(self.api_raw)))
        if self.test_raw:
            notes.append(t(lang, "filter.test_refused", value=html.escape(self.test_raw),
                           options=", ".join(sorted(TESTS))))
            # The one value an operator is most likely to type here is the name of
            # the *build* job every row on these pages comes from, and `kbuild` is not
            # a test at all: `TESTS` is `boot`/`kselftest-riscv`/`kselftest-kvm`, and
            # `KBUILD_JOB` is `kbuild-gcc-14-riscv`.  Saying so is the difference
            # between a reader learning the vocabulary and re-typing the same name
            # (`04-actions.md` §5, "我选的 kbuild 它不给我运行").
            if self.test_raw in ("kbuild", KBUILD_JOB):
                notes.append(t(lang, "filter.test_is_job", value=html.escape(self.test_raw)))
        if self.sort_raw:
            # `?sort=tree-branch,banana` used to be reduced to whatever `one_of` made of
            # it - i.e. to the default - with nothing said, so a page that had been asked
            # for one order rendered another.  The keys that survive are still applied;
            # this names what was dropped.
            notes.append(t(lang, "filter.sort_refused", value=html.escape(self.sort_raw),
                           options=", ".join(SORT_KEYS)))
        return notes

    def to_query(self) -> list[tuple[str, str]]:
        """This filter as a copyable query, defaults left out.

        One place decides the key order and which value is "the default": the
        pages, the links and the commands all read the same answer.  A default is
        left out because `?days=0&limit=50&origin=any` says four times what the
        reader did not ask for, and because a link that spells a default out
        cannot be told apart from a link that asked for it by hand.

        `pick`/`tick` are page state rather than conditions and stay out: the
        ticks of one page must not follow the reader to the next.

        `api` follows the same rule with the one default it has - the base this
        process started on.  A page reading that base carries nothing, which is why
        today's URLs are unchanged; a page reading another API says which one, and
        says it first.
        """
        wanted = (("api", self.api, ""),
                  ("tree", self.tree, ""), ("branch", self.branch, ""),
                  ("arch", self.arch, ""), ("defconfig", self.defconfig, ""),
                  ("compiler", self.compiler, ""),
                  ("state", self.state, ""), ("result", self.result, ""),
                  ("days", str(self.days), str(NO_WINDOW)),
                  ("limit", str(self.limit), "50"),
                  ("test", self.test, ""), ("ran", self.ran, "any"),
                  ("verdict", self.verdict, ""), ("evidence", self.evidence, "any"),
                  ("origin", self.origin, "card"),
                  ("missing", ",".join(self.missing), ""),
                  ("has", ",".join(self.has), ""), ("text", self.text, ""),
                  ("sort", self.sort, ""),
                  # The comparison cap travels with the order for the same reason the
                  # order does: a row's `±` is defined by *both*, so a link into one
                  # comparison has to carry both or it opens a differently-built page.
                  # It is a `Filter` field and not a `FILTER_ORDER` axis, so it is
                  # returned here in `FILTER_ORDER`'s tail position (`FILTER_ORDER` has
                  # no `delta`; the extra keys come after it in dict order).
                  ("delta", str(self.delta), str(DEFAULT_DELTA)))
        found = {key: value for key, value, default in wanted if value != default}
        return [(key, found[key]) for key in FILTER_ORDER if key in found] + (
            [("delta", found["delta"])] if "delta" in found else [])

    def accepts(self, kbuild: Kbuild | None, records: Records, local: "Local | None",
                test: str = "") -> bool:
        """Is this row in?  A value nobody knows is permissive, never a silent drop.

        `test` narrows the two record checks to one test, which is what a row of
        the jobs table is about; without it they are about the build as a whole.
        """
        wanted_fields = (("tree", self.tree), ("branch", self.branch),
                         ("arch", self.arch), ("defconfig", self.defconfig),
                         ("compiler", self.compiler), ("state", self.state),
                         ("result", self.result))
        if kbuild is None:
            # A row with no card has no tree to compare: a value filter EXCLUDES it.
            # Showing it is how "I filtered by tree=x" looks like nothing happened.
            if any(wanted for _, wanted in wanted_fields) or self.text:
                return False
        else:
            for field_name, wanted in wanted_fields:
                if wanted and getattr(kbuild, field_name) != wanted:
                    return False
            if self.text:
                haystack = " ".join(str(getattr(kbuild, name, "") or "") for name in
                                    ("build_id", "tree", "branch", "describe", "node_id")).lower()
                commit = str((kbuild.revision or {}).get("commit") or "")
                if self.text.lower() not in f"{haystack} {commit.lower()}":
                    return False
        if self.origin != "any":
            here, remote = bool(local and (local.present or local.card)), kbuild is not None
            if self.origin == "local" and not here:
                return False
            if self.origin == "remote" and not remote:
                return False
            if self.origin == "both" and not (here and remote):
                return False
            # `carded`: this machine has a card for it, which is neither "local" (a
            # card *or* bytes) nor "remote".  It exists because it is the one set the
            # numbers strip's `cards` chip counts, and a chip whose link cannot
            # reproduce its number is a number the reader cannot check - the 52 cards
            # and the 53 directories differ by exactly the copies no card names
            # (`_numbers_strip`, and `accept.py`'s S6).
            if self.origin == "card" and not (local is not None and local.card is not None):
                return False
        if self.has or self.missing:
            held = set(local.present) if local is not None else {
                name for name in ARTIFACTS if kbuild is not None and kbuild.artifact(name)}
            if any(name not in held for name in self.has) or any(name in held for name in self.missing):
                return False
        if self.evidence == "bytes":
            # Not a `Local.state`: "the artifacts are on disk" is a fact about the
            # download tree, and the two states around it need the record or the
            # absence of it.  The numbers strip's `with bytes` chip is this value.
            if local is None or not local.present:
                return False
        elif self.evidence != "any" and local is not None and local.state != self.evidence:
            return False
        if kbuild is None:
            return True
        if self.ran != "any" or self.verdict:
            found = records.for_test(test or self.test) if (test or self.test) else records
            verdicts = [one.verdict for one in found.for_build(kbuild.build_id)]
            if self.ran == "never" and verdicts:
                return False
            if self.ran == "ever" and not verdicts:
                return False
            if self.ran == "failing" and errors.VERDICT_FAIL not in verdicts:
                return False
            if self.verdict and (not verdicts or verdicts[-1] != self.verdict):
                return False
        return True


# ---------------------------------------------------------------------------
# One local copy, and what the record does (not) say about it
# ---------------------------------------------------------------------------

@dataclass
class Local:
    """One local copy as three separate facts: the card, the bytes, and the pull record.

    None of the three is derived from the others, and none of them is derived from
    a build id: that is the whole point.  A directory named like a remote build is
    a directory named like a remote build - `state()` says what can be claimed.
    """

    build_id: str
    card: Kbuild | None = None
    present: dict[str, str] = field(default_factory=dict)
    pull: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        """`var/downloads/<build-id>/` - where this copy's bytes (and its record) live."""
        return layout.downloads(self.build_id)

    @property
    def acts(self) -> list[dict]:
        """The recorded pull acts, newest first - `Build.provenance()`'s shape."""
        found = self.pull.get("acts")
        if not isinstance(found, list):
            return []
        return [one for one in found if isinstance(one, dict)]

    @property
    def latest(self) -> dict:
        """The newest recorded act, or `{}` - the one that describes the copy as it is."""
        return self.acts[0] if self.acts else {}

    @property
    def entries(self) -> list[dict]:
        """The artifact entries of the newest act: what that pull actually did."""
        found = self.latest.get("entries")
        if not isinstance(found, list):
            return []
        return [one for one in found if isinstance(one, dict)]

    @property
    def state(self) -> str:
        """What the facts allow: pulled | unrecorded | registered | made-here | empty.

        A `file://` artifact is this deployment's own `var/serve/`: an act that
        fetched one proves the bytes and says nothing about a remote build, so it is
        the one act that means `made-here` rather than `pulled`.  Without this,
        `made-here` was unreachable for the single copy it was written for
        (`deadbeef1234`, published from `var/serve/Image`): it read `pulled … from
        file:///home/hao/kernelci-riscv/var/serve/Image`, and `?evidence=made-here`
        selected nothing on any machine, ever (`03-structure.md` §A3.3).
        """
        if self.entries:
            local_only = all(str(one.get("url") or "").startswith("file:")
                             for one in self.entries)
            return "made-here" if local_only else "pulled"
        if self.present:
            return "unrecorded"
        if self.card is None:
            return "empty"
        return "registered" if self.card.node_id else "made-here"

    @property
    def node_id(self) -> str:
        """The remote node this copy is tied to: the card's, or the one the pull recorded."""
        return (self.card.node_id if self.card is not None else "") or str(self.pull.get("node_id") or "")

    def size(self) -> int:
        """How many bytes of artifacts are on disk here."""
        total = 0
        for path in self.present.values():
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
        return total

    def hosts(self) -> list[str]:
        """The hosts the recorded pull fetched from, in the order the entries name them."""
        found = []
        for entry in self.entries:
            host = _host(str(entry.get("url") or ""))
            if host and host not in found:
                found.append(host)
        return found

    def state_text(self, lang: str = DEFAULT_LANG) -> str:
        """One sentence, saying what the record does say and what it does not."""
        if self.state == "pulled":
            moved = sum(1 for entry in self.entries if entry.get("transferred"))
            said = t(lang, "evidence.pulled_text", n=len(self.entries),
                     hosts=", ".join(self.hosts()) or "?",
                     size=_human(self.pulled_bytes()), at=self.latest.get("at") or "?",
                     moved=moved, whole=len(self.entries) - moved)
            failed = str(self.latest.get("error") or "")
            return t(lang, "evidence.failed", said=said, error=failed) if failed else said
        if self.state == "unrecorded":
            where = (t(lang, "evidence.card_in_table") if self.card is not None
                     else t(lang, "state.no_card_in_table"))
            return t(lang, "evidence.unrecorded_text", where=where)
        if self.state == "registered":
            return t(lang, "evidence.registered_text", node=_short(self.card.node_id))
        if self.state == "made-here":
            return t(lang, "evidence.made_here_text")
        return t(lang, "evidence.empty_text")

    def pulled_bytes(self) -> int:
        """The bytes the newest recorded pull proved."""
        return sum(int(entry.get("bytes") or 0) for entry in self.entries)


# ---------------------------------------------------------------------------
# One API answer, and the three counts that must not be confused
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Remote:
    """What one API query answered, and how much of it this page is showing.

    Three different numbers live in one answer and they are not interchangeable:
    what the page prints (`shown`, capped by the row limit), what the window plus
    this filter kept (`kept`), and what the API itself says the query's size is
    (`total` - quoted, never counted here).  A page that printed one number for
    all three is how "2 rows" came to look like "the API has 2 builds".
    """

    query: str = ""
    shown: tuple[Kbuild, ...] = ()
    kept: int = 0                    # rows the fetched window kept, before the display cap
    total: int | None = None         # the API's own count for the query, when it says
    limit: int = 0                   # the row cap that was asked for
    note: str = ""                   # why there are no rows, when the API did not answer

    def __iter__(self):
        return iter(self.shown)

    def __len__(self) -> int:
        return len(self.shown)

    def coverage(self, lang: str = DEFAULT_LANG) -> str:
        """How complete this answer is, in words - a cap that hides rows says so.

        Two different things can keep a row out of the table and they are named
        separately: the API's own size against the cap this page asked for, and
        this page's filter over the rows the cap did return.
        """
        if self.total is None:
            return t(lang, "remote.coverage_unknown")
        said = t(lang, "remote.coverage_base", total=self.total)
        if self.total <= self.limit:
            said += t(lang, "remote.coverage_all")
        else:
            said += t(lang, "remote.coverage_capped", n=self.total - self.limit,
                       limit=self.limit)
        dropped = min(self.total, self.limit) - self.kept
        if dropped > 0:
            said += t(lang, "remote.coverage_filtered", n=dropped)
        return said


# ---------------------------------------------------------------------------
# 19. Gui (view.hpp §19)
# ---------------------------------------------------------------------------

# What one request has already read off this machine, and nothing more.
#
# The local reads (`Builds.load()`, `Records.load()`, the download tree) are the
# page's own facts, and they change while it is running: a `run`/`pull`/`index`
# button writes them from a subprocess, and the next page load has to show it
# without a restart.  So they are read per *request* - and a page that asked for
# 200 local rows must not parse the ledger 200 times to do it, which is what makes
# this a cache at all.
#
# It lives in a `threading.local()`, and the handler *clears it at the start of
# every request*.  That second half is not decoration: `protocol_version` is
# `HTTP/1.1`, so one keep-alive connection carries many requests on the *same*
# thread - "one thread, one request" is not true here, and a cache that outlived a
# request would show the state from before the last write.  It is also why this is
# not a field on `Gui`: two threads, one field, whichever wrote last - the
# `self.note` race, and `_shell`'s docstring says what that cost.
_LOCAL = threading.local()


def _request_scratch() -> dict[str, Any]:
    """This request's own scratch space; created on first use, cleared per request.

    Only ever read through `Gui._state()`, `Gui.all_locals()`, `Gui.runs()` and
    `Gui.todo()`, which are the reads that are asked for many times in one render.
    """
    found = getattr(_LOCAL, "scratch", None)
    if found is None:
        found = {}
        _LOCAL.scratch = found
    return found


def _ttl_of(query: Mapping[str, list[str]]) -> float:
    """How long an API answer this request may reuse one: `?ttl=`, `?fresh=1`.

    `?fresh=1` is the manual refresh spelled as a URL: it asks the API again *now*.
    That is what makes the refresh control (`_refresh`) a real re-read and not a
    decoration - the local side was never cached, so a refresh has always re-read
    the files, and this is the API half of the same promise (`01-perf.md` §D2).
    `?fresh=0` is not fresh, so a link can carry the key and mean "no".

    A `?ttl=` nobody can read, or one past `api_mod.MAX_TTL`, falls back rather
    than refusing: this is a knob for a reader tuning one page, not a condition of
    the question, so it is not a `Filter` key and it never reaches a command line.

    **The default is `API_TTL_DEFAULT` and not `lib/api.py`'s 5 s.  Carry-over C2,
    decided here.**  An entry is stamped when its answer is *written*, so a cold page
    whose own `/count` took longer than the TTL left that answer already stale: the
    very next load re-read it (`/analysis` 4.44 s, `/worker` 1.81 s, where the load
    after that is 0.012 s).  Since the alternative - stamping an entry with its
    request's *start* - is a change to `lib/api.py`, the page's own default covers the
    read instead.  It is the page's decision to make because it is the page that knows
    what its loads cost, and it is *stated* rather than silent: `_refresh` prints the
    age of what was read (`read 3s ago`), `?fresh=1` bypasses the cache entirely, and
    every local file the page draws from is read fresh on every request whatever this
    number is - the operator's "我刷新一次界面起码我运行时候能够在外重新读文件".
    """
    if _first(query, "fresh") not in ("", "0"):
        return 0.0
    raw = _first(query, "ttl")
    if not raw:
        return float(API_TTL_DEFAULT)
    try:
        return float(_clamp(int(float(raw)), 0, api_mod.MAX_TTL))
    except ValueError:
        return float(API_TTL_DEFAULT)


def _begin_request(query: Mapping[str, list[str]]) -> None:
    """Start this request's API scope: an empty memo, this freshness, this deadline.

    Called from the handler, because the handler is the one thing that knows a new
    request has begun - and it has to be called for every request the console
    serves, not only the pages: one keep-alive connection carries many requests on
    one thread (`_request_scratch` above), so a memo that outlived its request would
    answer the next one with what the last one read.

    The budget is the page's, and it is shared by every read of this request
    (`API_BUDGET`), so no page can spend it once per call the way `/worker` did.
    """
    api_mod.begin_request(ttl=_ttl_of(query), budget=API_BUDGET)


def _mark(path: str) -> str:
    """One file as `path:mtime:size`, or `path:-` when it is not there yet."""
    try:
        info = os.stat(path)
    except OSError:
        return f"{path}:-"                 # absent is a fact as well: it may appear
    return f"{path}:{info.st_mtime_ns}:{info.st_size}"


def _dir_marks(directory: str, suffix: str) -> list[str]:
    """`path:mtime:size` for every `<directory>/*/<suffix>` - one level, never recursive.

    `suffix` and not a file name: `var/results/<build>/` holds one `<test>.json` per
    recorded verdict and the page does not know their names in advance, while
    `var/runs/<id>/` holds exactly one `run.json`.  A name still matches itself, so
    one spelling covers both; a half-written `.tmp` beside its file matches neither,
    which is what a reader wants.

    A directory that is not there is not a failure: each of these is made by the
    first thing that writes it, and a page that refused to draw on a fresh machine
    would be a page nobody could use.  The same is true of a directory removed
    while it is being walked, which is what a cancelled activity leaves behind.
    """
    found = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_dir():
                    continue
                try:
                    with os.scandir(entry.path) as inner:
                        found += [_mark(one.path) for one in inner
                                  if one.name.endswith(suffix)]
                except OSError:
                    continue
    except OSError:
        return found
    return found


def _state_digest() -> str:
    """A hash of the local facts a page reads, from mtime and size, never content.

    This is what the 2s poll compares (`Gui.state_poll`, `_JS`'s `dashPoll`): when
    an activity finishes, its `run.json` is settled, the record it wrote appears
    under `var/results`, its `provenance.json` under `var/downloads` - and this
    number moves, so the page re-reads them with nobody pressing anything.  That is
    the operator's 我这个东西运行完了，他可能是要改某些东西 wired to the poll that
    already existed (`docs/gui-rework/01-perf.md` §D3).

    `(mtime, size)` and not the bytes: these are the cards, the ledger and the pull
    records, some of them megabytes, and a page may not read them twice to decide
    whether it has to read them once.  One `scandir` per directory, which is the
    same walk `all_locals()` already makes for the downloads, so this is not a new
    cost class - and it is the *page's own inputs*, not a guess about them: nothing
    an activity writes is outside this list.

    `worker-state.json` is in it although the worker rewrites it after every event
    it handles: each of those rewrites is a real change to what `/worker` shows.
    """
    marks = [_mark(layout.index()), _mark(layout.worker_state())]
    marks += _dir_marks(layout.results(), ".json")
    marks += _dir_marks(layout.downloads(), "provenance.json")
    marks += _dir_marks(layout.runs(), "run.json")
    return hashlib.sha256("\n".join(sorted(marks)).encode("utf-8")).hexdigest()[:16]


def _part_name(head: str) -> str:
    """The `name="…"` of one multipart part's `Content-Disposition`, or `""`."""
    for line in head.splitlines():
        if not line.lower().startswith("content-disposition:"):
            continue
        match = re.search(r'name="([^"]*)"', line)
        if match:
            return match.group(1)
    return ""


def _multipart(body: bytes, boundary: str) -> dict[str, list[str]]:
    """A `multipart/form-data` body as the same shape `parse_qs` returns.

    Repeated names accumulate in order, which is what a bar of tick boxes sends and
    what `_ticks()` reads.
    """
    found: dict[str, list[str]] = {}
    marker = b"--" + boundary.encode("utf-8")
    for part in body.split(marker):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue                       # the preamble and the closing marker
        head, separator, value = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        name = _part_name(head.decode("utf-8", "replace"))
        if name:
            found.setdefault(name, []).append(value.decode("utf-8", "replace"))
    return found


def _form_body(content_type: str, body: bytes, lang: str = DEFAULT_LANG) -> dict[str, list[str]]:
    """One POST body as form fields, in both encodings a browser can send.

    A page's own `<form>` posts `application/x-www-form-urlencoded`, and
    `parse_qs` reads exactly that.  The script this page serves did not: it took the
    form over and posted `new FormData(form)`, which is `multipart/form-data` - so
    `parse_qs` was handed a body it could not read and returned *no fields at all*.

    That was not a missing value but a silent one.  Every action fell back to its
    defaults, and the ones that need a ticked row - `run` and `pull` - were refused
    with "needs at least one ticked build" however many rows the operator ticked,
    which is the report this function exists to answer.  Worse, an action that needs
    nothing ticked still ran, but on the *default* tree and window rather than the
    ones in the filter bar, because `_first(form, "tree")` was reading an empty
    form.

    So the body is read for what it says it is, and a body that is neither encoding
    is refused loudly instead of being parsed into silence.
    """
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind == "multipart/form-data":
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise errors.ConfigError(t(lang, "error.body_no_boundary"))
        return _multipart(body, match.group(1).strip())
    if kind in ("", "application/x-www-form-urlencoded"):
        return urllib.parse.parse_qs(body.decode("utf-8"))
    raise errors.ConfigError(t(lang, "error.body_not_a_form", kind=kind))


@dataclass
class Gui:
    """The pages: what the API has, what we hold, and the record that ties the two."""

    host: str = HOST
    port: int = PORT
    rows: int = ROWS
    refresh: int = REFRESH
    api_url: str = ""
    # Explicit overrides for tests and for anything that wants to hand the page a
    # fixed table and ledger (`/tmp/**`'s probes do exactly that).  Left as `None`
    # by the entry point: a page that froze its two local reads at startup showed
    # yesterday's ledger until it was restarted.
    builds: object = None
    records: object = None
    api: object = None
    # No `note` here on purpose: the server is threaded, so a failure kept on the
    # instance would be printed by whichever request was rendering at that moment.
    # Every read returns its own reason instead (see `Remote.note`).

    # --- serving -----------------------------------------------------------

    def serve(self) -> int:
        """Serve until interrupted; a taken port is reported, never silently swapped."""
        gui = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            # The language a URL asked for and the page will remember: `""` until a
            # request really carried `?lang=`, so `_send` can decide the header.
            _remember = ""

            def do_GET(self) -> None:
                try:
                    self._route_get()
                except errors.ConfigError as exc:
                    self._send(404, "text/plain; charset=utf-8", f"{exc}\n")
                except Exception as exc:  # noqa: BLE001 - a page that dies silently is worse
                    self._fail(exc)

            def do_HEAD(self) -> None:
                """The same answers, headers only.

                `BaseHTTPRequestHandler` answers 501 to a HEAD, and a link a reader
                opens by hand is preceded by a HEAD in several clients (and in every
                link checker).  Routing it through the GET path and suppressing the body
                is what `http.server`'s own contract asks for, and it is cheaper than a
                reader concluding that the log address is dead.
                """
                self._head = True
                try:
                    self._route_get()
                except errors.ConfigError as exc:
                    self._send(404, "text/plain; charset=utf-8", f"{exc}\n")
                except Exception as exc:  # noqa: BLE001
                    self._fail(exc)

            def _route_get(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                # This request's API scope: what it has already asked, how fresh a
                # repeated answer may be (`?ttl=`, `?fresh=1`) and the one deadline
                # its reads share.  Before any read, and on every route: the memo
                # must not survive into the next request on this connection.
                _begin_request(query)
                lang = self._lang(query)
                if parsed.path == "/summary.json":
                    self._json(gui.summary(_first(query, "api")))
                elif parsed.path == "/api/runs":
                    self._json(gui.status(_first(query, "kind"), _first(query, "state")))
                elif parsed.path == "/api/state":
                    # What the page's own 2s poll asks: the activities it draws, and
                    # the digest of the local facts it was drawn from.
                    self._json(gui.state_poll(_first(query, "kind"), _first(query, "state")))
                elif parsed.path == "/api/analysis/drift":
                    self._json(gui.drift(_first(query, "older"), _first(query, "newer"),
                                         api=_first(query, "api")))
                elif parsed.path == "/api/analysis/trend":
                    self._json(gui.trend(_first(query, "test", DEFAULT_TESTS[0]),
                                         _numbers(query, "scope", 20)))
                elif parsed.path.startswith("/runs/") and parsed.path.endswith("/log"):
                    # The log as a *page*, not as this program's own polling endpoint.
                    # The activity table's 日志 link used to point at
                    # `/api/runs/<id>/log`, which answers JSON - so a reader who clicked
                    # it, or copied the address into a new tab, got something that did
                    # not look like a log and would not open like one ("日志点击之后拉到
                    # 下面给个地址也打开不了我要的是类似自己打开那种").  `text/plain` is
                    # the file, opened: monospace, selectable, searchable, and the same
                    # bytes for `curl`.  The JSON endpoint stays for the page's script.
                    run_id = urllib.parse.unquote(parsed.path[len("/runs/"):-len("/log")])
                    self._send(200, "text/plain; charset=utf-8",
                               log_body(gui.log(run_id, 0, lang), lang))
                elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/log"):
                    run_id = parsed.path[len("/api/runs/"):-len("/log")]
                    self._json(gui.log(run_id, _first(query, "offset", "0")))
                elif parsed.path in REDIRECTS:
                    # Merging three pages must not break a link somebody wrote down.
                    # The condition rides along as a key `/` already reads (`origin`,
                    # `missing`) and it is only added when the URL did not carry that
                    # key already: `/remote?origin=local` was a filter the reader set,
                    # and a redirect that overwrote it would answer a question nobody
                    # asked - the one thing `Filter.from_query` refuses to do.
                    #
                    # The `Location` is built by `_url`, the one function every link
                    # on every page goes through, so the `api` key is canonicalised by
                    # `Apis.key` and not by hand: `?api=production` is the startup
                    # base here and must come back as no key at all, while the same
                    # URL on a machine started on the local stack must keep it.  A
                    # hand-built query string could not know that.
                    to, over = REDIRECTS[parsed.path]
                    check = Filter.from_query(query, lang, gui.apis)
                    where = _url(to, check, lang=lang,
                                 **{key: value for key, value in over.items()
                                    if not _first(query, key)})
                    self._send(302, "text/html; charset=utf-8", where + "\n")
                else:
                    self._send(200, "text/html; charset=utf-8",
                               gui.render(parsed.path, query, lang))

            def do_POST(self) -> None:
                try:
                    self._route_post()
                except errors.KciError as exc:
                    # A refused writer, an unknown action, a bad value: an answer,
                    # not a page that half worked.
                    self._send(409, "text/plain; charset=utf-8", f"{exc}\n")
                except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                    self._fail(exc)

            def _route_post(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                _begin_request(query)
                # A refused action answers in the language the reader is reading; the
                # cookie is not written from here, because this is the machine
                # interface (`/api/actions/...`), not a page.  Read before the body,
                # because a body this cannot read is refused in that language too.
                lang = self._lang(query, remember=False)
                form = _form_body(self.headers.get("Content-Type") or "",
                                  self.rfile.read(length), lang)
                if parsed.path.startswith("/api/actions/"):
                    self._json(gui.start(parsed.path[len("/api/actions/"):], form, lang))
                elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
                    run_id = parsed.path[len("/api/runs/"):-len("/cancel")]
                    self._json(gui.cancel(run_id, lang))
                else:
                    self._send(404, "text/plain; charset=utf-8",
                               f"{t(lang, 'error.no_such_action')}\n")

            def _fail(self, exc: Exception) -> None:
                print(f"! {self.path}: {type(exc).__name__}: {exc}", flush=True)
                self._send(500, "text/plain; charset=utf-8", f"{type(exc).__name__}: {exc}\n")

            def _json(self, payload: Any) -> None:
                self._send(200, "application/json", json.dumps(payload, indent=1))

            def _lang(self, query: Mapping[str, list[str]], remember: bool = True) -> str:
                """Which language this answer is drawn in, and whether to remember it.

                The order is `i18n.pick_lang`'s: `?lang=` -> the `kci_lang` cookie ->
                `Accept-Language` (`zh-CN` and `zh-TW` are both `zh`) -> the default.
                A `?lang=` nobody knows is skipped rather than refused, so
                `?lang=fr` draws a page instead of a 500.
                """
                lang = pick_lang(_first(query, "lang"), self._cookie("kci_lang"),
                                 self.headers.get("Accept-Language") or "")
                self._remember = lang if remember and "lang" in query else ""
                return lang

            def _cookie(self, name: str) -> str:
                """One cookie of the request, or `""` when it is not there."""
                for item in (self.headers.get("Cookie") or "").split(";"):
                    key, _, value = item.partition("=")
                    if key.strip() == name:
                        return value.strip()
                return ""

            # Set by `do_HEAD` for the length of one request: the headers are the
            # answer and the body is dropped (`_send`).  A class attribute so `_send`
            # never has to guess whether it was set.
            _head = False

            def _send(self, code: int, kind: str, text: str) -> None:
                blob = text.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(blob)))
                if code in (301, 302, 303, 307, 308):
                    # A 302 and not a 301: this mapping is a decision of *this*
                    # version of the page, and a permanent redirect is cached in the
                    # browser for as long as the reader keeps it - a merge that later
                    # changes its mind could not be undone in a tab that remembered.
                    self.send_header("Location", text.strip())
                if self._remember:
                    # Only a URL that really carried `?lang=` writes this, and there is
                    # no `Secure`: the page listens on 127.0.0.1 over http.  It is the
                    # one piece of client state this GUI keeps (src/GUI.md §6).
                    self.send_header("Set-Cookie", f"kci_lang={self._remember}; Path=/; "
                                                   "Max-Age=31536000; SameSite=Lax; HttpOnly")
                self.end_headers()
                if not self._head:
                    self.wfile.write(blob)

            def log_message(self, *args: Any) -> None:
                pass                                            # one person is reading this

            def log_request(self, code: Any = "-", size: Any = "-") -> None:
                """Every request leaves one line: a slow page must be visible, not felt."""
                took = time.time() - getattr(self, "_started", time.time())
                note = "  <-- slow" if took > 2 else ""
                print(f"  {self.command} {self.path} -> {code}  {took:.2f}s{note}", flush=True)

            def handle_one_request(self) -> None:
                # A request starts having read nothing: whatever the last writer
                # wrote is what this page must show, and a keep-alive connection
                # serves several requests from this same thread.
                _request_scratch().clear()
                self._started = time.time()
                super().handle_one_request()

        try:
            server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            # No request, so no language: this one is drawn in the default one.  The
            # sentence still comes from the catalogue, so the day a `--lang` flag
            # exists, this line needs no change.
            raise errors.ConfigError(t(DEFAULT_LANG, "error.port_taken", host=self.host,
                                       port=self.port, why=exc)) from exc
        print(f"kernelci-riscv pages on http://{self.host}:{self.port}  (Ctrl-C stops it)",
              flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped", flush=True)
        finally:
            server.server_close()
        return errors.EXIT_PASS

    # --- the reads behind the pages ----------------------------------------

    def _state(self) -> tuple[Builds, Records]:
        """The two local reads: the table and the ledger, read once per request.

        Read *per request* and not once at startup: the buttons on these pages start
        subprocesses (`table.py index`, `pull`, `run`, `runday`, `worker`) that write
        the table and the ledger, and a page whose reads were taken at startup kept
        showing six records after a seventh was written - the operator's "I ran boot
        and nothing changed", with the run's own `boot.json` on disk.  A restart is
        not a refresh (src/GUI.md §5: the page may state what it read, so it has to
        read).

        Once per request, and not once per caller: `/local` asks for 200 rows and
        `local_row()` wants the ledger for each of them, so this is where one parse
        of `var/results` per page load comes from.  The scratch space is the
        handler's, cleared at the start of every request (`_request_scratch`).

        `self.builds` / `self.records` are test overrides, not a cache: when one is
        set it is that object and never the disk.  The entry point passes neither.
        """
        held = _request_scratch()
        if "table" not in held:
            held["table"] = (self.builds if self.builds is not None else Builds.load(),
                             self.records if self.records is not None else Records.load())
        return held["table"]

    def launch_base(self) -> str:
        """The API this process started on: `--api-url`, `$KCI_API_URL`, else `LOCAL`.

        Asked of the client the entry point built when there is one - it is the one
        that carries whatever `config.client()` decided - and of `lib/api.py`'s own
        `Api.url()` otherwise, which is the very call `Api.__init__` makes to fill in
        `base`.  One answer either way, so "the startup value" is never a guess.
        """
        if self.api is not None:
            return str(getattr(self.api, "base", "") or "")
        return api_mod.Api.url(self.api_url or None).rstrip("/")

    @property
    def apis(self) -> Apis:
        """The base names this page can offer, built from the one startup value.

        A property and not a field: a field would be one more thing a request could
        set, and this round exists because a request's API must live in its URL and
        nowhere else.  `launch_base()` cannot change while the process runs, so there
        is nothing here to keep in step.
        """
        return Apis(launch=self.launch_base())

    def _client(self, base: str = "") -> api_mod.Api:
        """The API client one read goes through, for the base *this* request chose.

        The base is an argument and never a field of `Gui`.  The server is threaded,
        so a base kept on the instance would be the `self.note` race over again: a
        page asking production and a page asking the local stack, rendered at the same
        moment, would each read whichever base was written last.  Passing it means
        every read of one request builds its client from the same string, and no
        request can see another's - which is what the page A / page B check in
        src/GUI.md §8 asks about.

        The client the entry point built is reused for the base it was built for
        (same session, same timeout, whatever token it carries); a switch to another
        base builds a fresh `Api`, which is a `requests.Session` and three attributes.
        """
        base = base or self.launch_base()
        if self.api is not None and base == self.launch_base():
            return self.api
        return api_mod.Api(base or None, timeout=API_TIMEOUT)

    def api_base(self, check: "Filter | None" = None) -> str:
        """The base one page reads - what its queries go to and what its `--api-url`
        carries.  One function for both, so a page's command line and its reads can
        never name two different APIs."""
        return self.apis.base(check.api if check is not None else "")

    def remote_query(self, check: "Filter | None" = None, lang: str = DEFAULT_LANG) -> str:
        """The question this page really asked, in the API's own spelling.

        It opens with the API it was put to and not with the flags: "showing 2 of 2"
        reads very differently once the line says the page asked the local stack, and
        this is the one place a page states the address it actually used.  The name a
        URL carries (`api=production`) is deliberately *not* what is printed here -
        the address is - so the short form in the address bar hides nothing.

        **The keys are the wire's keys, not ours.**  The line used to read
        `kind=kbuild job=kbuild-gcc-14-riscv tree=riscv branch=any no window (all)`,
        which is a paraphrase in three places at once: the key is `name=`, the tree is
        `data.kernel_revision.tree=`, and "no window" is the *absence* of
        `created__gte`.  `remote_query`'s own docstring has always promised that the
        flags and values "stay as they are in both languages: this line is a query an
        operator copies into a command" - and an operator who copied `tree=riscv` into
        `curl` got **0**, because the API has no `tree` field
        (`docs/gui-rework/02-filters.md` §A3).  So it is built by `_api_query`, the
        same function `remote_rows` sends, and the two cannot drift.

        Only the opening "asked &lt;base&gt;:" is a sentence, and only it is translated.
        Which axes are in force, *including the ones at their default*, is the axes
        strip's job (`_axes`) and not this line's: a query elides its defaults, and
        "window is all" is exactly the kind of fact a key/value strip can carry and a
        query line cannot.
        """
        check = check or Filter(limit=self.rows, origin="any")
        return t(lang, "remote.query_from", api=self.api_base(check),
                 query=_query_text(_api_query(check, "kbuild")))

    def _axis_counts(self, check: Filter, total: "int | None" = None,
                     kind: str = "kbuild") -> dict[str, int]:
        """What each axis in force matched **on its own**, as the axes strip's badge.

        A filter that removed 11 rows of 1782 has to *look* like one that removed 11
        rows: `arch=riscv`, `compiler=gcc-14` and `defconfig=defconfig` each match 1771
        of the 1782 nodes this page's query holds, and offered as ordinary controls
        they read as filters that worked (`02-filters.md` §A1, §B4).  The number is the
        API's own count for `kind`+`name`+window **plus this one axis**, and `_total` is
        the same query with no value axis at all - the denominator the strip greys a
        badge against.

        Two things keep this from being a licence to spend: only axes **in force** get a
        count (never the offers, never prefetched), and past `MAX_AXIS_COUNTS` axes the
        strip prints no number at all rather than a guess.  Each count is one `/count`,
        which the request's TTL answers from cache on a reload - and on a page nobody
        has filtered, this makes **no call at all**: the strip then shows values with no
        badges, which is exactly right, because nothing is being claimed about them.

        `total` is the read's own `Remote.total` and is quoted, not used: the count for
        the *whole* question is the number the axes strip compares against nothing.
        """
        axes = [name for name in FILTER_ORDER
                if API_FILTERS.get(name, {}).get(kind)
                and str(getattr(check, name, "") or "")]
        if not axes or len(axes) > MAX_AXIS_COUNTS:
            return {}
        client = self._client(self.api_base(check))
        base = dict(_api_query(Filter(days=check.days), kind))
        found: dict[str, int] = {}
        for name in [*axes, "_total"]:
            filters = dict(base)
            if name != "_total":
                filters[API_FILTERS[name][kind]] = str(getattr(check, name))
            counted = client.count(kind=kind, filters=filters)
            if counted is None:
                # No `/count` (or a budget that ran out) means no number: the strip
                # prints fewer badges, never an invented one.
                return {}
            found[name] = int(counted)
        return found

    def remote_rows(self, check: "Filter | None" = None, held: dict | None = None,
                    lang: str = DEFAULT_LANG) -> Remote:
        """What the API answers for this filter: the newest rows, and the counts.

        The read is capped at `check.limit` (the API has no sort parameter, so the
        newest rows are its tail - one count plus one page instead of the whole
        window), which is exactly why the answer carries three counts instead of
        one.  A failure is kept in `note` and shown on the page: an empty remote
        table and "the API did not answer" are different answers, and the page
        must not let one look like the other.

        **The whole question is built once, by `_api_query`.**  The tree, the window
        and the branch used to be `getdays()`'s three arguments and every other value
        key was applied afterwards; now `getdays()` is asked for the job's rows and
        `extra=` carries *the same pairs the page prints* into the read, so the line
        under the table and the request behind it cannot disagree - which is what
        `02-filters.md` §A3 found them doing.

        `held` is the local copies the `origin`/`evidence` filters judge; without
        it the page's own `{build_id: Local}` is read here.  It must be the real
        one: `accepts()` reads `local=None` as "we hold nothing", so
        `origin=local` matched no row at all - which is how /pull reported zero
        candidates while /local listed four copies.

        The failure reason travels in the returned `Remote.note`, never on `Gui`:
        the server is threaded, so a note kept on the instance would be printed on
        whichever page happened to be rendered at the same moment.
        """
        check = check or Filter(limit=self.rows, origin="any")
        # The question, once, as the pairs `_api_query` built: the line printed under
        # the table and the keys the read is handed are the same object, which is what
        # `02-filters.md` §A3 found them not being (`job=` on the page, `name=` on the
        # wire).  `extra=` is how a read that takes three arguments carries eighteen
        # keys: applying the difference *after* the row cap made `arch=riscv` a sample
        # of 50 rows instead of an answer (`02-filters.md` §P7), and wrapping the whole
        # client to avoid it (`_Narrowed`) was the wrong seam.
        pairs = _api_query(check, "kbuild")
        catalogue = Kbuilds(self._client(self.api_base(check)))
        try:
            found = catalogue.getdays("", NO_WINDOW, None, limit=check.limit,
                                      extra=dict(pairs))
        except errors.KciError as exc:
            return Remote(query=t(lang, "remote.query_from", api=self.api_base(check),
                                  query=_query_text(pairs)),
                          limit=check.limit, note=str(exc))
        records = self._state()[1]
        held = self.all_locals() if held is None else held
        kept = [one for one in found if check.accepts(one, records, held.get(one.build_id))]
        return Remote(query=t(lang, "remote.query_from", api=self.api_base(check),
                              query=_query_text(pairs)),
                      shown=tuple(kept[:check.limit]),
                      kept=len(kept), total=catalogue.total, limit=check.limit)

    def local_of(self, build_id: str, card: Kbuild | None = None) -> "Local":
        """The facts about one local copy, read from disk: the bytes and the pull record."""
        local = Local(build_id=build_id, card=card)
        disk = Build(path=local.path)
        local.present = disk.present()
        local.pull = disk.provenance()
        return local

    def all_locals(self) -> dict[str, Local]:
        """Every local copy by build_id: the table's cards plus whatever is under var/downloads/.

        The union is the honest local side: a directory that no card names is still
        bytes we hold (a fetch or a worker left it there), and a card with no
        directory is still something we registered.

        Cached for this request like the ledger (`_state`), because walking the
        download tree reads one `provenance.json` and `os.path.isfile` per artifact;
        a page asks for it once per table *and* once per filter, and the answer
        cannot change between those while one request is being rendered (nothing
        this process does writes them - the writes come from the subprocesses a
        button starts, and the next request sees those).
        """
        held = _request_scratch()
        if "locals" not in held:
            table = self._state()[0]
            found = {build.build_id: self.local_of(build.build_id, build.kbuild)
                     for build in table}
            for name in _dirs(layout.downloads()):
                # Not `found.setdefault(name, self.local_of(name))`: that evaluates
                # its argument whether or not the key is there, so every directory
                # that already had a card was read a second time - `provenance.json`
                # parsed and every artifact stat'ed again, 31 reads of 27 copies on
                # this machine (`06-analysis.md` §A0's instrumented render).  The two
                # sets overlap by design (a pulled build has both a card and a
                # directory), so the old line was always going to re-read the
                # majority of them.
                if name not in found:
                    found[name] = self.local_of(name)
            held["locals"] = found
        return held["locals"]

    def filtered_locals(self, check: "Filter | None" = None) -> list[Local]:
        """Every local copy this filter keeps, newest first, **uncapped**.

        Kept apart from `local_rows` because the merged builds page has to cap the
        union once, after the two halves are merged: a page that capped the local half
        at `limit` rows and *then* merged it with the API's `limit` rows would print
        twice what it promised, and one that capped before sorting would drop the
        newest rows.  The numbers strip reads this too - a number a link reproduces
        cannot be a slice.

        The order is the newest thing anybody knows about the copy: its card's
        `created`, else its newest pull act.  A directory no card names has no
        `created` at all, and sorting those last is how a build that was pulled and
        run fell off the end of the row cap and became invisible on the one page that
        lists local copies.
        """
        check = check or Filter(limit=self.rows, origin="any")
        records = self._state()[1]
        kept = [one for one in self.all_locals().values()
                if check.accepts(one.card, records, one)]
        kept.sort(key=lambda one: (self.when_of(one), one.build_id), reverse=True)
        return kept

    @staticmethod
    def when_of(local: Local) -> str:
        """When a local copy became known: its card's `created`, else the newest act's `at`."""
        if local.card is not None and local.card.created:
            return local.card.created
        return str(local.latest.get("at") or "")

    def local_rows(self, check: "Filter | None" = None) -> list[Local]:
        """The local table's rows: every copy, filtered, newest first, capped."""
        check = check or Filter(limit=self.rows, origin="any")
        return self.filtered_locals(check)[check.offset:check.offset + check.limit]

    def local_row(self, local: Local, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One local row as data: the card, the bytes and the record, kept apart."""
        card = local.card
        records = self._state()[1]
        return {"build_id": local.build_id,
                "describe": card.describe() if card is not None else local.build_id,
                "tree": card.tree if card is not None else "",
                "branch": card.branch if card is not None else "",
                "arch": card.arch if card is not None else "",
                "defconfig": card.defconfig if card is not None else "",
                "compiler": card.compiler if card is not None else "",
                "created": card.created if card is not None else "",
                "in_table": card is not None, "node_id": local.node_id,
                "state": local.state, "state_text": local.state_text(lang),
                "present": sorted(local.present), "size": local.size(),
                "acts": len(local.acts), "pulled_at": str(local.latest.get("at") or ""),
                "hosts": local.hosts(), "path": local.path,
                "verdicts": {test: (records.last(test, local.build_id).verdict
                                    if records.last(test, local.build_id) else "")
                             for test in DEFAULT_TESTS}}

    def remote_row(self, kbuild: Kbuild, local: Local | None,
                   lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One remote row as data: what the API says, and what we hold under that id."""
        return {"build_id": kbuild.build_id, "tree": kbuild.tree, "branch": kbuild.branch,
                "arch": kbuild.arch, "defconfig": kbuild.defconfig,
                "compiler": kbuild.compiler, "created": kbuild.created,
                "state": kbuild.state, "result": kbuild.result, "node_id": kbuild.node_id,
                "describe": kbuild.describe(), "artifacts": dict(kbuild.artifacts),
                "here": local.state if local is not None else "",
                "here_text": (local.state_text(lang) if local is not None
                              else t(lang, "state.not_held_here")),
                "here_short": (_short_state(local.state, lang) if local is not None
                               else t(lang, "state.not_here"))}

    def todo(self, check: "Filter | None" = None) -> list[Any]:
        """`re.todo()` for this request, walked once per set of tests.

        **Carry-over C1, measured.**  `08-PLAN.md` handed this step "`job_rows`
        computes `build.missing(test)` inside its double loop, so `/jobs` makes 579
        `os.path.isfile` calls for ~10 distinct artifacts; one dict before the loop is
        enough".  Instrumented on this revision, the shape is different and the fix is
        therefore a different one: `/jobs` made **603 `Build.missing()` calls**, and
        only **156** of them (52 cards x 3 tests, one per pair) came from `job_rows` -
        the other **447** came from `re.todo()`, which asks the same 156 pairs and was
        walked **three times in one render**: once by `job_rows` for the gap set, once
        by `_jobs` for the `whole` count, once by `_numbers_strip`.  `/` walked it
        twice.  A dict inside `job_rows` cannot touch those 447, because `job_rows`
        already computes each pair exactly once.

        So the memo is `re.todo()` itself, keyed by the set of tests - the same
        technique `_state()`, `all_locals()` and `runs()` already use, and safe for the
        same reason: nothing this process does writes the ledger during a render (the
        writers are the subprocesses a button starts), so two answers to one question
        inside one request could only differ by a bug.

        The engine still owns the rule - `re.todo()` is `Records` + `Build.missing()`,
        and this method counts nothing (`00-BRIEF.md` §2).
        """
        check = check or Filter(limit=self.rows, origin="any")
        tests = _tests_of(check)
        held = _request_scratch()
        key = ("todo", tests)
        if key not in held:
            table, records = self._state()
            held[key] = re_mod.todo(table, tests, records)
        return held[key]

    def job_rows(self, check: "Filter | None" = None) -> list[dict[str, Any]]:
        """One row per (build, test): the local table minus the ledger, vizualised."""
        check = check or Filter(limit=self.rows, origin="any")
        table, records = self._state()
        held = self.all_locals()
        tests = _tests_of(check)
        gap = {(build.build_id, test) for build, test, _ in self.todo(check)}
        rows = []
        for build in table:
            local = held.get(build.build_id) or self.local_of(build.build_id, build.kbuild)
            if not check.accepts(build.kbuild, records, local):
                continue
            # One reason per (build, test), looked up rather than recomputed: the
            # column is `build.missing(test)`, which stats every artifact the test
            # needs, and the same pair is reachable from more than one row of this
            # page (`_tests_of` returns all three when no test is chosen).
            reasons = {test: "; ".join(build.missing(test)) for test in tests}
            for test in tests:
                if not check.accepts(build.kbuild, records, local, test=test):
                    continue
                record = records.last(test, build.build_id)
                rows.append({"build_id": build.build_id, "test": test,
                             "tree": build.kbuild.tree if build.kbuild else "",
                             "describe": build.describe(),
                             "needs": ", ".join(TESTS.get(test, {}).get("needs", ())),
                             "reason": reasons[test],
                             "runs": len(records.for_build(build.build_id).for_test(test)),
                             "verdict": record.verdict if record else "",
                             "when": record.timestamp if record else "",
                             "source": record.source if record else "",
                             "gap": (build.build_id, test) in gap})
        return rows[check.offset:check.offset + check.limit]

    def job_node_rows(self, check: "Filter | None" = None, state: str = "",
                      limit: int = 0) -> tuple[list[dict[str, Any]], str]:
        """The API's queue as `(rows, why there are none)`.

        The reason is returned rather than kept on `Gui`: this server is threaded,
        and an instance attribute would put one request's failure on another
        request's page.  An empty string means the API answered.

        `limit` is how wide *this caller* wants the read to be, and the read is as
        wide as the widest caller of one page needs: `Filter.limit` (50 by default)
        is a table's print cap, and reading the queue at that width and then reading
        it *again* at `QUEUE_ROWS` is what made `/worker` pay four calls and 680,254
        bytes for one answer (`docs/gui-rework/01-perf.md` §F4).  The rows come back
        in the API's own order and only the row filters `check.job`/`check.text` are
        applied, so a caller that wants the first `check.limit` of them slices this
        answer rather than asking for it twice.
        """
        check = check or Filter(limit=self.rows, origin="any")
        try:
            found = Kjobs(self._client(self.api_base(check))).getjob(
                state=state or None, limit=max(limit, check.limit))
        except errors.KciError as exc:
            return [], str(exc)
        seen = set(self.worker_state().get("seen") or [])
        rows = []
        for job in found:
            if check.job and job.name != check.job:
                continue
            if check.text and check.text.lower() not in \
                    f"{job.name} {job.node_id} {job.state} {job.result}".lower():
                continue
            rows.append({"node_id": job.node_id, "name": job.name, "state": job.state,
                         "result": job.result, "platform": job.platform, "runtime": job.runtime,
                         "created": job.created, "definition": bool(job.definition_url),
                         "claimed": job.node_id in seen})
        return rows[:limit or check.limit], ""

    def worker_state(self) -> dict[str, Any]:
        """The worker's own state file, read as the document `poller.py` wrote it.

        Displayed, never interpreted: the cursor/seen/pending rules belong to
        `poller.py`, and this page only shows what that file says.
        """
        try:
            with open(layout.worker_state(), encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def runs(self) -> list[Any]:
        """Every activity on disk, read once per request.

        `Run.load_all()` walks `var/runs` and parses every `run.json`, and one
        `/analysis` render asked for it **104 times** - 104 opens over ~50 activity
        directories for a page that shows none of them, because `_shell` wants the
        count, `busy()` wants the writers and `/runs` wants both
        (`docs/gui-rework/01-perf.md` §F2.3, BASELINE.md).  Cheap in absolute terms
        and still wrong: it is one fact read over and over inside one render, and it
        grows with every activity ever run, which nothing prunes.

        Cached like `_state()` and `all_locals()`, and in the request's scratch
        rather than on `Gui`, for the reason the `_LOCAL` comment gives: the next
        request has to see what the last writer wrote.
        """
        held = _request_scratch()
        if "runs" not in held:
            held["runs"] = run_mod.Run.load_all()
        return held["runs"]

    def run_rows(self, kind: str = "", state: str = "") -> list[dict[str, Any]]:
        """Every activity on disk - the workflow monitor's table.

        `kind` is a **comma list** as well as one name.  The page's own default is a
        *set* of kinds ("everything but the bookkeeping", `FOLDED_KINDS`) and a set
        that the URL can carry is a set the URL can be reloaded with, the poll's guard
        can compare, and the filter box can show - which is why the fold is filter
        state and not a trick of the renderer (`_runs`, `04-actions.md` §P8a).
        """
        wanted = {one for one in str(kind or "").split(",") if one}
        return [{"id": one.id, "kind": one.kind, "state": one.state, "what": one.what,
                 "age": one.age(), "seconds": round(one.seconds(), 1), "log": one.log,
                 "exit_code": one.exit_code, "argv": list(one.argv),
                 # `started` and `ended` are epoch floats the activity writes about
                 # itself (`lib/run.py:82-83`; `ended` is 0.0 while it runs), and they
                 # are what make the finish notice truthful.  Without them the only
                 # signal a page has is "the id I saw running is not running now",
                 # which cannot tell a finish that happened *while the reader watched*
                 # from one that happened before the page was drawn - so a reload
                 # re-announced an old finish for ever, which is the lie the notice
                 # exists to avoid.  With them the shell stamps the moment it drew the
                 # page (`data-drawn`) and `ended > drawn` is a fact about the run
                 # rather than an inference about the poll (`07-shell.md` §C1).
                 #
                 # `started` is also half the notice's key: the id is a
                 # second-resolution stamp plus the kind, and two activities of one
                 # kind started in the same second shared it until `Run._free_id`
                 # (`lib/run.py:89`) suffixed the collision.
                 "started": one.started, "ended": one.ended}
                for one in self.runs()
                if (not wanted or one.kind in wanted) and (not state or one.state == state)]

    def busy(self, rows: "list[dict[str, Any]] | None" = None) -> list[str]:
        """The writers running right now - one at a time, and the page says which.

        `rows` is an answer `run_rows()` already gave, and it is what lets the shell
        read the activities once: it needs them three times in one render - the live
        panel, this banner, and the counts - and the answer to "what is running" is
        the same list every time.  Left out, it reads them itself, because the writer
        gate in `start()` asks this question on its own.

        "Something is running" and "writes are refused" are **two different facts**
        and this method is only the second: a running `results` or `trend` shuts no
        gate, so a page that showed it here would refuse work nobody is holding
        (`07-shell.md` §A4).  The live panel is where the first fact lives.
        """
        found = self.run_rows() if rows is None else rows
        return [one["id"] for one in found
                if one["state"] == run_mod.RUNNING and one["kind"] in WRITE_KINDS]

    def pull_acts(self) -> list[dict[str, Any]]:
        """Every pull act recorded on this machine, newest first - what was pulled, and when."""
        found = []
        for local in self.all_locals().values():
            for act in local.acts:
                found.append({"build_id": local.build_id, "at": str(act.get("at") or ""),
                              "error": str(act.get("error") or ""),
                              "entries": list(act.get("entries") or []),
                              "node_id": str(local.pull.get("node_id") or ""),
                              "entries_count": len(act.get("entries") or []),
                              "bytes": sum(int(one.get("bytes") or 0)
                                           for one in (act.get("entries") or [])
                                           if isinstance(one, dict))})
        found.sort(key=lambda one: (one["at"], one["build_id"]), reverse=True)
        return found

    def summary(self, api: str = "") -> dict[str, Any]:
        """Everything the first screen shows - also the `/summary.json` contract.

        `api` is the raw `?api=` of the request (a name, an address, or nothing), so
        the machine interface can ask the same question the page can.  It goes through
        `self.apis.of()` exactly like a page's own query does: one spelling per base,
        and a value nobody knows falls back to the startup base.
        """
        table, records = self._state()
        check = Filter(limit=self.rows, origin="any", api=self.apis.of(api))
        remote = self.remote_rows(check)
        rows = self.local_rows(check)
        return {"remote": {"query": self.remote_query(check),
                           # The three counts, kept apart here too: the JSON is the
                           # same data the page prints, so it must not flatten them.
                           "shown": len(remote), "kept": remote.kept,
                           "total": remote.total, "limit": check.limit,
                           "coverage": remote.coverage(),
                           "rows": [self.remote_row(one, self.all_locals().get(one.build_id))
                                    for one in remote]},
                "local": [self.local_row(one) for one in rows],
                "correspondence": _tally(rows, {one.build_id for one in remote}),
                "pulls": self.pull_acts(),
                "jobs": self.job_rows(check),
                "runs": self.status(),
                "ledger": {"records": len(records), "tally": records.tally(),
                           "builds": len(Records.builds()), "dir": layout.results()},
                "table": {"builds": len(table), "file": layout.index()},
                "note": remote.note, "actions": list(ACTIONS)}

    def drift(self, older: str, newer: str, lang: str = DEFAULT_LANG,
              api: str = "", catalogue: "Kbuilds | None" = None) -> dict[str, Any]:
        """The config difference between two builds, by id - `{}` with a reason when unreadable.

        `api` is the request's raw `?api=`, read through the same `Apis.of()` the
        pages use, so `/api/analysis/drift?api=production` and the `/analysis` page
        with the box on `production` are one question (src/GUI.md §4).

        `catalogue` is the builds the caller has *already* read - on the page, the
        very rows its list offers (`_known_builds`).  `Drift` needs both builds
        to fetch their `.config`, and the API cannot be asked for a build id: without
        them it scans the window once per id.  On production, where
        `kbuild-gcc-14-riscv` answers nearly two thousand nodes, that was two scans of
        a thousand nodes on top of the read the page had already made - the reason
        `/analysis` took over fifty seconds.

        A caller with no page behind it (the `/api/analysis/drift` endpoint) gets one
        read made here instead, used for both ids: one read rather than two scans.
        """
        older, newer = _token(older), _token(newer)
        if not (older and newer):
            return {"error": t(lang, "error.two_build_ids"), "older": older, "newer": newer}
        base = self.apis.base(self.apis.of(api))
        client = self._client(base)
        if catalogue is None:
            # As wide as the scan it replaces (`kbuild.SCAN`), and made once.
            catalogue = Kbuilds(client, items=self.remote_rows(
                Filter(limit=SCAN, api=self.apis.of(api)), lang=lang))
        try:
            # `job` is the storage fallback's directory prefix (`drift._config_url`),
            # and it used to be `""` here: that built `kbuild-<id>/.config` where this
            # deployment's storage serves `kbuild-gcc-14-riscv-<id>/.config`, so the
            # fallback the docstring promises could only ever answer 404 - and the
            # refusal message named a URL nobody would have asked for
            # (`06-analysis.md` §A7.2, page-only: the CLI always passed its default).
            report = Drift.between(client, KBUILD_JOB, older, newer, catalogue=catalogue)
        except errors.KciError as exc:
            return {"error": str(exc), "older": older, "newer": newer,
                    "older_ref": _ref_of(catalogue, older),
                    "newer_ref": _ref_of(catalogue, newer),
                    "same": _same_branch(catalogue, older, newer)}
        return {"older": older, "newer": newer, "drifted": report.drifted(),
                "added": report.added, "removed": report.removed, "changed": report.changed,
                # The two sides as a reader names a build (tree/branch · describe), and
                # whether this is one kernel's drift at all: the numbers are the same
                # either way, but 616/618/99 across two trees must not be read as one
                # kernel moving (`06-analysis.md` §D1).  Both come from the catalogue
                # the caller already read - one dict scan, no request.
                "older_ref": _ref_of(catalogue, older),
                "newer_ref": _ref_of(catalogue, newer),
                # The raw artifacts, for the reader who wants the file rather than our
                # reading of it: the URL is already on the `Kbuild`, so this is a dict
                # lookup and not a read (`06-analysis.md` §A10.4's `可以打开一个文本查看`).
                "older_url": _artifact_of(catalogue, older, "_config"),
                "newer_url": _artifact_of(catalogue, newer, "_config"),
                "same": _same_branch(catalogue, older, newer),
                "summary": {"added": len(report.added), "removed": len(report.removed),
                            "changed": len(report.changed)}}

    def trend(self, test: str, scope: int = 20) -> dict[str, Any]:
        """One test's timeline: the series, and where it went pass -> fail.

        **Every field the record has, not five of them.**  A point used to carry
        `build_id`, `timestamp`, `verdict`, `source` and whether it is a regression -
        so the four facts a reader could see were in a `title=` and nothing else, and
        the `exit_code`, the `detail`, the log path and the TAP counts the record holds
        (`lib/out.py: RECORD_FIELDS`) never reached the page that had the file open.
        The selected run's block (`_record_block`) is what reads them, and a cell
        carries enough to name *one* record: `(build_id, timestamp)` is unique in the
        ledger (`var/results/<build>/<test>.json` is one file per pair, and the file's
        own timestamp is the record's).

        `/api/analysis/trend` is a contract (src/GUI.md §4): fields are added here and
        none are removed.
        """
        records = self._state()[1]
        series = records.series(test)[-max(1, int(scope)):]
        pairs = re_mod.transitions(records, test)
        marks = {one.build_id for pair in pairs for one in pair}
        return {"test": test,
                "points": [{"build_id": one.build_id, "timestamp": one.timestamp,
                            "verdict": one.verdict, "source": one.source,
                            "exit_code": one.exit_code, "detail": one.detail,
                            "results": dict(one.results or {}),
                            "log": one.log, "artifacts_dir": one.artifacts_dir,
                            "revision": dict(one.revision or {}), "job": one.job,
                            "regression": one.build_id in marks} for one in series],
                "transitions": len(pairs)}

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
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
            return entry("runday.py") + ["--days", days, "--limit", limit,
                                         *_flag("--tree", tree), *_flag("--test", test), *api]
        if name == "fetch":
            return entry("run_latest.py") + ["--tree", tree or "riscv",
                                             *_flag("--test", test), *api]
        if name == "provision":
            return entry("run_latest.py") + ["--provision-only", "--tree", tree or "riscv", *api]
        if name == "worker":
            mode = _chosen(form, "mode", MODES, "once", lang)
            platform = _chosen(form, "platform", ("", DEFAULT_DEVICE), DEFAULT_DEVICE, lang)
            runtime = _chosen(form, "runtime", ("", DEFAULT_LAB), DEFAULT_LAB, lang)
            return entry("pull_worker.py") + (["--once"] if mode == "once" else []) + [
                *_flag("--platform", platform), *_flag("--runtime", runtime), *api]
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

    # --- the pages ---------------------------------------------------------

    def render(self, page: str = "/", query: "Mapping[str, list[str]] | None" = None,
               lang: str = DEFAULT_LANG) -> str:
        """One page as HTML: the route decides which, the query string is its state.

        `lang` is the language this answer is drawn in, negotiated by the handler
        (`Handler._lang`) and carried by every link the page writes.  The pages
        themselves, and every machine endpoint (`/summary.json`, `/api/*`), read it:
        those two are contracts and stay English whatever the reader asked for.

        `?api=` is read here, once per request, through `self.apis`: it may name a
        base or spell one out, and every page draws from the filter that comes back.
        Nothing about it is kept on `Gui` - the request's URL is the whole of its
        state, which is what lets two requests in two threads read two APIs.
        """
        query = query or {}
        check = Filter.from_query(query, lang, self.apis)
        if page in ("", "/", "/index.html"):
            return self._builds(check, lang)
        if page.startswith("/local/"):
            # The one route that is not in `PAGES`, and deliberately so: it is a
            # *detail* page for one build, not a station.  It stays where it was
            # (`03-structure.md` §d.6): it is where the operator reads a build's
            # whole record, and `_lang_links`'s `route=` argument is what keeps its
            # build id through a language switch.
            return self._correspondence(urllib.parse.unquote(page[len("/local/"):]), lang,
                                        check.api)
        if page == "/jobs":
            return self._jobs(check, lang)
        if page == "/runs":
            # `/runs` reads no API of its own, but it still carries the key: see
            # `_runs`, which hands `check.api` on as the page's own state.
            return self._runs(_first(query, "kind"), _first(query, "state"), lang, check.api)
        if page == "/worker":
            # The worker's three arguments are read from the URL, so the command
            # line under its button is the one the URL states - nothing else can
            # change between the page being drawn and the button being pressed.
            # **The queue's own state, when the URL names none.**  A worker page is about
            # what a worker can claim, so its default question is `state=available` -
            # spelled here rather than only in `_worker`, because the filter bar, the
            # table and the "现在可领取 N 个" badge all read the same query and must agree
            # about it (`_worker`'s own comment says why the *boxes* come from the rows).
            return self._worker(check, lang, state=_first(query, "state", "available"),
                                mode=_first(query, "mode"),
                                platform=_first(query, "platform"),
                                runtime=_first(query, "runtime"))
        if page.startswith("/analysis/"):
            # The single-build view the operator asked for (「单个那种也可能还要专门开发
            # 一个」), and the place the whole comparison is printed: `/analysis` names a
            # pair and shows its arithmetic, this route shows the pair.
            return self._one_build(urllib.parse.unquote(page[len("/analysis/"):]), check,
                                   _token(_first(query, "vs")), lang)
        if page == "/analysis":
            picks = [one for one in check.pick if one][:2]
            older = _token(_first(query, "older")) or (picks[0] if len(picks) == 2 else "")
            newer = _token(_first(query, "newer")) or (picks[1] if len(picks) == 2 else "")
            # Two page keys, read like `older`/`newer` so the state stays in the URL:
            #   `point` - the run a timeline cell selected (A6: the cells were inert
            #             `<span>`s, so `这个不能选` was literal);
            #   `delta` - how many rows of the order may spend a config read on their
            #             neighbours, clamped here because a URL is hand-editable and
            #             `?delta=600` would be a two-hour request (D3).
            point = _token(_first(query, "point"))
            delta = _clamp(_numbers(query, "delta", DEFAULT_DELTA), 0, MAX_DELTA)
            return self._analysis(check, older, newer, lang, point=point, delta=delta)
        raise errors.ConfigError(t(lang, "error.no_page", page=repr(page),
                                   routes=", ".join(route for route, _ in PAGES)))

    # --- the controls every page is asked with -----------------------------

    def _api_field(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Which API this page reads: one open box, and its candidates.

        **One control, not two.**  This field used to draw the same three choices twice
        on one line - a `<datalist>` of both spellings and a `_quick` pill per base -
        and the operator said what that is worth: 「api: local production 这个也没必要
        就是又很多东西重复了就是有一个框就行了」.  The pills are gone; the box and its
        list stay, so every value the pills could set is still one keystroke away.

        The same shape the rest of the bar uses for a free value (`_datalist` +
        `_name_field`, like `tree`).  The value stays open because
        the set of KernelCI APIs is not something this deployment gets to decide -
        `http://127.0.0.1:9/` is a base whether or not anybody listed it.

        The box holds the *key* (`production`), not the address, because the key is
        what the URL and every link carry; the address it stands for is printed in the
        page's own query line (`remote_query`), so the short form hides nothing.  The
        candidates offer both spellings, so typing either is one keystroke away.

        An empty box means "the base this process started on", and the placeholder
        says which one that is: "empty" is then a readable answer rather than a
        missing one, and the page's URL stays the one it had before this key existed.
        """
        apis = self.apis
        entries = apis.entries()
        launch = self.launch_base()
        labels = {name: base for name, base in entries}
        labels.update({base: name for name, base in entries})
        # What the box shows as "current": the key itself, or - when the key is empty
        # - the name of the base an empty key stands for, so the value in force is
        # what the box says rather than nothing.
        here = check.api or apis.name(launch) or launch
        # One option per API, whose *value* is the address and whose *label* is the
        # short name, so the list is two rows for two APIs instead of four rows for
        # two APIs.  Neither spelling is lost: `Apis.base()` resolves names first and
        # `Apis.of()` canonicalises both to the same key, so typing or picking either
        # still lands on `?api=production`.
        return (_datalist("apis", tuple(base for _, base in entries), labels)
                + _name_field("api", check.api, t(lang, "filter.api"), "apis", lang,
                              placeholder=here))

    def _build_axes(self, route: str, check: Filter, answer: "Remote | None" = None,
                    rows: Iterable[Any] = (), lang: str = DEFAULT_LANG) -> list[str]:
        """The kbuild filter axes, once, for every page that selects builds.

        `/` built these fourteen controls inline and `/analysis` drew five of the same
        kind, so the page the operator calls 分析 had a *lesser copy* of the filter bar he
        already knew: no `arch`, no `compiler`, no `origin`, no `missing`, and no way to
        say "only the ones with bytes on disk".  He asked for one template
        (「应该有类似统一的分析就是模板」), and the axes are the template - the pages differ
        in what they *do* with the list (compare neighbours, chart a test), not in how the
        list is chosen.

        `answer` is optional: a page that has no API answer to count passes none, and the
        two `_combo` controls fall back to the values they have seen.
        """
        known = () if answer is None else answer
        return [self._api_field(check, lang=lang),
                self._tree_field(check, known, lang=lang),
                self._branch_field(check, known, lang=lang),
                # The rest of the API's vocabulary for a kbuild node, every key verified
                # against a `/count` before it was offered (`API_FILTERS`).  `tree` and
                # `branch` narrow (80 and 44 of 1782); `arch`, `defconfig` and `compiler`
                # are real and nearly never selective (1771 each), which is what the number
                # beside each axis in the strip is for.
                self._combo("arch", check, known, t(lang, "word.arch"), lang),
                self._combo("defconfig", check, known, t(lang, "word.defconfig"), lang),
                self._combo("compiler", check, known, t(lang, "word.compiler"), lang),
                # `state`'s offer list comes from the kind, and it is short on purpose.
                _select("state", ("", *KBUILD_STATES[1:]), check.state,
                        t(lang, "word.state"), lang=lang),
                _select("result", ("", *RESULTS[1:]), check.result,
                        t(lang, "word.result"), lang=lang),
                _select("origin", ORIGINS, check.origin, t(lang, "filter.origin"),
                        placeholder=False, labels=_labels("origin", lang), lang=lang),
                _select("evidence", EVIDENCE, check.evidence, t(lang, "filter.evidence"),
                        placeholder=False, labels=_labels("evidence", lang), lang=lang),
                _select("missing", ("", *ARTIFACTS), ",".join(check.missing),
                        t(lang, "filter.missing"), lang=lang),
                self._days_field(route, check, lang=lang),
                self._limit_field(route, check, lang=lang)]

    def _tree_field(self, check: Filter, rows: Iterable[Any] = (),
                    lang: str = DEFAULT_LANG) -> str:
        """The tree field and its candidates: a name the API accepts, not a box of two.

        A select box could only offer the trees this deployment had already seen,
        which is how `/remote` came to offer two names out of the fifty the
        pipeline config knows.
        """
        return (_datalist("trees", _vocabulary("tree", check, rows, self._state()[0]))
                + _name_field("tree", check.tree, t(lang, "word.tree"), "trees", lang))

    def _branch_field(self, check: Filter, rows: Iterable[Any] = (),
                      lang: str = DEFAULT_LANG) -> str:
        """The branch field: this tree's own branches, plus a free hand.

        The candidates are **per tree**, which is the difference between a suggestion
        and a lie.  `BRANCH_SEEDS` offered six names to every tree at once, so
        `tree=riscv` - whose only two branches are `fixes` and `for-next` - was offered
        `main`, `master` and `linux-6.12.y`, names that live on `net-next`,
        `stable-rc` and `mainline`; the live overview's branch box held 12 names and
        every one of them belonged to another tree (`02-filters.md` §A4).  The API
        cannot enumerate branches, but the vendored pipeline config binds them to a
        tree (`kernelci-pipeline/config/trees/<tree>.yaml`, 126 bindings over 76
        names), and for `riscv` it yields exactly the two the API itself answered with.

        A rail is offered here and not for `tree`: two stops is precisely what a
        slider is for, and the operator's "滑条式可以给你选，这样你但你可以自己填"
        wants both halves - the two names to slide through and a box that still takes
        one nobody listed.
        """
        stops = _branches_from_config(check.tree) or BRANCH_SEEDS
        return (_datalist("branches", _vocabulary("branch", check, rows, self._state()[0]))
                + _name_field("branch", check.branch, t(lang, "word.branch"), "branches",
                              lang, stops=stops,
                              note=(t(lang, "filter.branch_of_tree", tree=check.tree)
                                    if check.tree else "")))

    def _combo(self, name: str, check: Filter, rows: Iterable[Any] = (),
               label: str = "", lang: str = DEFAULT_LANG) -> str:
        """One value axis as a box with candidates: `arch`, `defconfig`, `compiler`.

        The shape the rest of the bar already uses (`_datalist` + `_name_field`),
        built from what this page's own answer carries rather than from a constant:
        the API has no endpoint that lists the values a field takes, so "what has
        answered here" is the only honest source, and a value nobody has seen must
        still be typeable (`_named` accepts any plain name).

        Small sets get a rail (`arch` is seven names on production); long ones do not
        - a defconfig is `x86_64_defconfig+allnoconfig`, and twenty of those on a
        slider is unreadable, which is why `_rail` takes the set and refuses past
        `RAIL_MAX` on its own.

        **No count beside the label.**  The axes strip already prints, for each axis in
        force, the number of *rows* that axis matched (`_axis_counts`), and a second
        number next to the same name - the size of the suggestion set - would be read
        as the same fact and would often contradict it (`arch` has one suggestion here
        and matched 1771 rows).  The strip's number is the one that means something.
        `branch` is the exception and says so in its own title: its set is per tree and
        two stops is what the rail exists for.
        """
        stops = sorted(one for one in _seen_names(name, rows, self._state()[0]) if one)
        return (_datalist(name + "s", stops)
                + _name_field(name, str(getattr(check, name, "") or ""), label,
                              name + "s", lang, stops=stops))

    def _days_field(self, route: str, check: Filter,
                    keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG) -> str:
        """The window: a free number of days, its ten presets, and `all` for no window.

        Ten buttons was the wrong shape for ten numbers - the operator asked for
        "有一些可以滑下来的选项，而不是多个直接列出来" - so the set is a hint the rail
        steps through, and the box still takes any number of days he types.
        """
        return (_datalist("days", [str(one) for one in DAYS])
                + _num("days", str(check.days), t(lang, "filter.window"), NO_WINDOW,
                       MAX_DAYS, "days", stops=[str(one) for one in DAY_CHOICES]))

    def _limit_field(self, route: str, check: Filter,
                     keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG) -> str:
        """The row cap: how many this page prints - and the one control that costs bytes.

        `01-perf.md` §D1c measured ~3.5 KB per row over a 20-35 KB/s link, so the six
        stops are six costs and `_coverage` prints the one in force beside the box.
        The last of the preset links (`_quick`, six values, each also a datalist
        option beneath it) became these stops.
        """
        return (_datalist("limits", [str(one) for one in LIMITS])
                + _num("limit", str(check.limit), t(lang, "filter.rows"), 1, MAX_LIMIT,
                       "limits", stops=[str(one) for one in LIMITS]))

    def _shell(self, name: str, body: str, check: "Filter | None" = None,
               notes: Iterable[str] = (), lang: str = DEFAULT_LANG, route: str = "",
               lang_keep: Iterable[tuple[str, str]] = ()) -> str:
        """The one template every page is drawn in: navigation, the numbers, the banners.

        **The counts line is gone.**  It said `27 build(s) in /home/…/builds.json, 7
        record(s) in /home/…/var/results, 50 activit(ies) in /home/…/var/runs` - three
        absolute paths, two machine plurals, and the three numbers the operator called
        "多余" - and `_numbers_strip` replaces it with the seven numbers the console
        actually has, each one a link to the rows it counts and each one read uncapped.
        Nothing about the paths is lost: each is now the `title=` of the number that
        counts it.  What stays on this line is the two things that are about *this*
        request and nothing else: the values a hand-edited URL asked for and did not
        get (a clamped number, an `?api=` nobody here knows), and the refresh control
        with the age of what was last read.

        It no longer names the API either: which API a page reads is set in its filter
        bar and stated in its own query line (`remote_query`), and a third place saying
        it again would be one more thing to keep in step with the two that decide it.

        `notes` are the failures *this* request ran into, and only those: the
        banner is about this page load, so it is built from what the page's own
        reads returned (the server answers requests in threads).

        `name` is the route's *name* (`builds`, `jobs`, ...) and stays English: it
        picks the navigation word (`nav.builds`) and marks the current page in the
        bar, and a bar that compared translated titles would stop marking anything
        the day a translation changed.  `route` is the path to come back to for the
        language switch (`/local/<id>` is not in `PAGES`), and `lang_keep` is the
        page's own state that is not a filter field (the /runs and /worker keys) -
        the same two things the refresh control needs, because it is the same URL.

        The digest is taken last, once the page's own reads are done, and it is what
        the poll compares (`state_poll`): a page drawn from one set of files that
        then re-reads itself the moment one of them changes.

        **The live panel is here and not on `/runs`.**  What is running now is the one
        fact a reader needs on *every* page, and a side panel that only exists on the
        page you are not looking at answers nothing: the operator's "有个任务运行最好
        把它放在动态的侧栏".  It is rendered by the server, so it is there with
        JavaScript off, before any fetch, and on an API that is answering slowly -
        which is also why the poll script does not build it, only updates it.

        The activities are read **once** for the three readers that want them (the
        panel, `busy`'s writer banner, the numbers strip's count), and the moment this
        answer was drawn rides to the page as `data-drawn`: the finish notice compares
        a run's own `ended` against it, so a reload cannot re-announce an old finish
        (`run_rows`, `_PAGE`, `07-shell.md` §C1).
        """
        rows = self.run_rows()
        running = [one for one in rows if one["state"] == run_mod.RUNNING]
        banners = ['<p class="banner bad">' + t(lang, "header.api_down", note=html.escape(one))
                   + "</p>" for one in notes if one]
        busy = self.busy(rows)
        if busy:
            banners.append('<p class="banner busy">'
                           + t(lang, "header.busy", writers=html.escape(", ".join(busy)))
                           + "</p>")
        capped = "".join(f' <span class="capped">{html.escape(one)}</span>'
                         for one in (check.clamps(lang) if check is not None else []))
        return _PAGE.format(
            lang=lang, title=t(lang, "nav." + name), nav=_nav(check, name, lang),
            langs=_lang_links(check, name, lang, route, lang_keep),
            live_chip=_live_chip(len(running), lang),
            drawn=f"{time.time():.3f}",
            live=_live_panel(rows, lang, kept=LIVE_KEPT),
            meta=(self._numbers_strip(check, lang) + capped + " "
                  + _refresh(_route_of(name, route), check, lang_keep, lang)),
            banners="".join(banners), body=body, css=_CSS,
            js=_js(lang, _state_digest()),
            # **One log box, on every page.**  It used to be drawn by the three pages that
            # remembered to ask (`/`, `/runs`, `/local/<id>`), while the log links exist on
            # six - so `showLog` looked for `#log` on a page that never drew one and the
            # click did nothing at all, which is part of 「日志点击之后…打开不了」.  The box is
            # rendered `hidden` and costs one empty `<section>`; the route
            # (`/runs/<id>/log`) is what a reader who copies the address gets.
            logbox=_log_box(lang),
            tagline=t(lang, "header.tagline"))

    # --- / : the merged builds page ----------------------------------------

    def _builds(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """Every build id this machine and this API know, one row each, three facts to a row.

        `/`, `/remote`, `/local` and `/pull` were four renderings of one question -
        *for each build id, what does the API say, what do I hold, and what does the
        record claim?* - and each page made one of the three facts its subject, which
        is why the four of them disagreed.  The merge needs no new query key: `origin`
        was always the union's three sides (`ORIGINS`), so `/?origin=local` is the page
        `/local` was, and the three old routes are 302s onto here (`REDIRECTS`).

        **The three adjacent cells are the design.**  `card`, `bytes` and `act` state
        the three facts separately and each of them may be `-`, because none of the
        three is derived from the others: a row that reads `card - / bytes 30.4 MiB /
        acts 1` is the operator's bug ("拉了运行了还是显示卡片没拉取") told as data
        instead of as the paragraph (`page.overview.sub`) and the six-sentence glossary
        that used to explain it.  A row's *shape* is the diagnosis.

        **Two action bars, and none per row.**  `/jobs`' 51 `run` buttons are one bar
        over that page's own ticks; here the table's ticks feed one `pull`.  A form
        cannot submit another page's checkboxes, so the boxes are associated with a
        form of this page (`form="pull-now"`, `_pull_form`'s proven shape) - which is
        what keeps the bar working with JavaScript off, and why it lives above the
        table rather than under it (one id, one owner).

        **The tick column is the command's condition, not this page's.**  `table.py
        pull --build` reads the local table (`Builds.get`, build.py:676), so a row
        without a card is not tickable and says why: the box that used to be drawn
        there fed a command that refused with `no build '…' in builds.json`
        (`03-structure.md` §A3).  How many such rows there are is a number under the
        bar, not a paragraph.

        The activity table is not printed here.  It was 32,407 of the landing page's
        65,311 characters and it is the same fifty rows `/runs` already prints, so
        this page links to it (`counts.activities`) and keeps its own log box.
        """
        table, records = self._state()
        held = self.all_locals()
        answer = self.remote_rows(check, held, lang)
        rows = self.build_rows(check, held, answer, lang)
        window = (("tree", check.tree), ("days", str(check.days)), ("limit", str(check.limit)))
        serve_image = layout.serve("Image")
        record = _action_bar("index", window, t(lang, "btn.record_window"),
                            argv=self._argv_of("index", dict(window), lang, api=check.api),
                            note="", hint=t(lang, "remote.index_hint"), lang=lang,
                            api=check.api)
        parts = [
            _remote_line(t(lang, "remote.asked"), answer, check, lang=lang),
            _filter_bar("/", [*self._build_axes("/", check, answer, lang=lang),
                              # What the cap costs and what it hides, in the form and
                              # beside the two fields it is about (§B5).  It replaces
                              # `filter.rows_note`, the 45-word sentence that used to
                              # sit under four tables.
                              _coverage(answer, check, lang)],
                        check, rendered=("api", "tree", "branch", "arch", "defconfig",
                                         "compiler", "state", "result", "days", "limit",
                                         "origin", "evidence", "missing"),
                        lang=lang, counts=self._axis_counts(check, answer.total)),
            # The view this page is showing, named and switchable, and no caption.  The
            # sub-line used to say what the page *is* ("the API's window and this disk,
            # one row per build id") - which is a sentence about the section, and a
            # sub-line is data or it is absent.  What a reader needs instead is which of
            # the three sets is in front of them and how big each one is, so the numbers
            # are the control: one press switches the view and keeps the filter.
            _h2(t(lang, "page.builds.title"),
                _view_presets("/", check, table, answer, lang)),
            record,
            _action_bar("pull", (), t(lang, "btn.pull_selected"), form_id="pull-now",
                        note=self._no_card_badge(rows, lang) + _tick_missing(rows, check, lang),
                        hint=t(lang, "pull.pull_hint"), lang=lang),
            _table((_tick_all("pull-now", len(rows), lang)
                    + _action_bar("pull", (), "", form_id="pull-one", lang=lang),
                    t(lang, "word.build_id"), t(lang, "word.tree_branch"),
                    t(lang, "word.created"), t(lang, "col.card"), t(lang, "col.bytes"),
                    t(lang, "col.act"), t(lang, "col.api_says"), t(lang, "filter.ran")),
                   [_row((_cell(self._tick_box(one, check, lang)),
                          # This one cell keeps the bare `<td><code title=…>` shape: the
                          # row probe an operator's own acceptance script counts this
                          # table by that prefix.
                          _cell(f'<code title="{html.escape(one["build_id"])}">'
                                f'{html.escape(one["build_id"][:16])}</code>'),
                          _cell(html.escape(_tree_branch(one)), "wrap"),
                          _cell(_created_cell(one, lang)),
                          _cell(_registered_cell(one, lang), "wrap"),
                          _cell(_bytes_cell(one)),
                          _cell(_act_cell(one, lang), "wrap"),
                          # Not escaped here: `_remote_cell` returns markup the same way
                          # `_registered_cell` and `_act_cell` do, and it escapes every
                          # value it interpolates itself.  Escaping its output printed the
                          # tags as text - `&lt;span title=…&gt;窗口外（上限 50）&lt;/span&gt;`.
                          _cell(_remote_cell(one, one["remote"], answer, lang), "wrap"),
                          _cell(_ran_cell(one), "act")))
                         for one in rows],
                   empty=_empty_builds(answer, held, lang),
                   cls="builds remote local"),
            _h2(t(lang, "page.builds.ledger_title")),
            self._ledger_numbers(table, records, lang),
            _h2(t(lang, "page.builds.acts_title"),
                # The retry, where the failure is reported: this page's own filter plus
                # the failed rows pre-ticked, so the reader lands on the same view with
                # the boxes already on and presses pull once.  `tick` is page state and
                # never leaves this URL (`Filter.to_query` excludes it), so the link
                # cannot smuggle a tick into another page.
                (_tick_failed(rows, check, lang) or t(lang, "page.builds.acts_sub")),
                id="acts"),
            _pulls_table(self.pull_acts(), api=check.api,
                         empty=t(lang, "empty.nothing_pulled",
                                 provenance=html.escape(
                                     os.path.basename(layout.provenance("x"))),
                                 downloads=html.escape(layout.downloads())), lang=lang),
            _h2(t(lang, "page.builds.image_title"),
                hint=t(lang, "page.builds.image_sub")),
            _action_bar("provision", [("tree", check.tree or "riscv")],
                        t(lang, "btn.publish_image"),
                        argv=self._argv_of("provision", {"tree": check.tree or "riscv"}, lang,
                                           api=check.api),
                        note=(t(lang, "local.image_state",
                                path=f'<code>{html.escape(serve_image)}</code>')
                              if os.path.isfile(serve_image)
                              else t(lang, "local.image_state_missing",
                                     path=f'<code>{html.escape(serve_image)}</code>')),
                        lang=lang, api=check.api),
        ]
        return self._shell("builds", "".join(parts), check, [answer.note], lang, route="/")

    def build_rows(self, check: Filter, held: dict[str, "Local"], answer: Remote,
                   lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
        """One row per build id over the API's window and this disk, newest first, capped once.

        The union is the honest page: a build the API answered and we hold is one row
        carrying both halves, a build only the API knows shows `card -`, and a copy
        only this machine knows (a directory no card names) is the row the operator
        could not see anywhere before the merge.  Both halves arrive already filtered
        (`remote_rows` judges every API row against the real `{build_id: Local}`, and
        `filtered_locals` judges every copy), so this is a set union and not a second
        pass of the same question.

        The cap is applied **after** the merge, once: a page that capped both halves
        and then merged would print twice the rows it promised.

        The order is `created`, with two fallbacks that matter.  A card-less copy has
        no `created`, and its newest pull act is the newest thing anybody knows about
        it - without that fallback every such copy sorted to the bottom and fell off
        the end of the row cap, which is exactly how the build the operator pulled and
        ran became invisible on the page that lists local copies (`accept.py`'s S7
        read "not on the local listing page at all").
        """
        remote = {one.build_id: one for one in answer}
        found = [one.build_id for one in answer]
        for local in self.filtered_locals(check):
            if local.build_id not in remote:
                found.append(local.build_id)
        rows = [self.build_row(remote.get(build_id), held.get(build_id), lang)
                for build_id in found]
        rows.sort(key=lambda one: (one["created"], one["build_id"]), reverse=True)
        # **In card mode the cap is not the page's to apply.**  `accepts()` lets
        # nothing but a carded row through when `origin=card`, so the row count *is* the
        # local table - and capping it meant the operator's own view of his cards hid
        # the oldest ones (`?origin=card` at the default `limit` showed 50 of 52, with
        # three cards missing entirely from `/`).  A cap on the disk is not a cap on a
        # query.  `limit` keeps its other job in that mode: the width of the API read.
        cap = check.limit if check.origin != "card" else MAX_LIMIT
        return rows[check.offset:check.offset + cap]

    def build_row(self, kbuild: "Kbuild | None", local: "Local | None",
                  lang: str = DEFAULT_LANG) -> dict[str, Any]:
        """One row's three facts, kept apart: the card, the bytes and the pull record.

        The dict is what the cells read, and its keys say which fact each value came
        from - `in_table`/`node_id`/`act_node_id` are three different answers to "what
        do we know about this build", and `Local.node_id` collapses two of them on
        purpose (`node_id` falls back to the record).  The `card` cell needs to know
        *which* of the two spoke, so both are here.
        """
        card = local.card if local is not None else None
        records = self._state()[1]
        said = [card.created if card is not None else "",
                kbuild.created if kbuild is not None else "",
                str(local.latest.get("at") or "") if local is not None else ""]
        # Which of the three spoke, so the cell can say when the date is the pull's and
        # not the build's: a copy whose card we do not have has no `created` at all, and
        # the newest thing anybody knows about it is when it was pulled.
        when = next((one for one in said if one), "")
        build_id = (kbuild.build_id if kbuild is not None
                    else local.build_id if local is not None else "")
        # `Records.last` once per test, for every row: the ledger is keyed by build id
        # and does not care whether a card, a directory or only the API named this
        # build, so a row the API answered and we do not hold still shows what has been
        # run against that id - which is half of what `/jobs` computes its gap from.
        verdicts = {}
        for test in DEFAULT_TESTS:
            found = records.last(test, build_id)
            verdicts[test] = found.verdict if found is not None else ""
        return {
            "build_id": build_id,
            "describe": (card.describe() if card is not None
                         else kbuild.describe() if kbuild is not None else ""),
            "tree": (card.tree if card is not None
                     else kbuild.tree if kbuild is not None else ""),
            "branch": (card.branch if card is not None
                       else kbuild.branch if kbuild is not None else ""),
            "created": when,
            "created_from_act": bool(when) and not (card.created if card is not None else "")
                                 and not (kbuild.created if kbuild is not None else ""),
            "in_table": card is not None,
            "node_id": local.node_id if local is not None else "",
            "act_node_id": str(local.pull.get("node_id") or "") if local is not None else "",
            "local": local, "remote": kbuild,
            "state": local.state if local is not None else "",
            "present": sorted(local.present) if local is not None else [],
            "size": local.size() if local is not None else 0,
            "acts": len(local.acts) if local is not None else 0,
            "act_at": str(local.latest.get("at") or "") if local is not None else "",
            "act_hosts": local.hosts() if local is not None else [],
            "act_error": str(local.latest.get("error") or "") if local is not None else "",
            # How many artifacts are on disk *right now* (`Local.present` is an
            # `os.path.isfile` read per artifact), which is what a retry message owes the
            # reader: the act's own `entries` count says what that attempt did.
            "here_n": len(local.present) if local is not None else 0,
            "pull_failed": bool(local is not None and local.latest.get("error")),
            "state_text": local.state_text(lang) if local is not None else "",
            "verdicts": verdicts,
        }

    def _tick_box(self, one: dict[str, Any], check: "Filter",
                  lang: str = DEFAULT_LANG) -> str:
        """The tick box of one row - or the reason this row cannot be ticked at all.

        The reason is the cell's `title=` and the cell itself is the word for it
        (`pull.not_tickable`): the imperative that used to be printed here ("no card:
        record the window first") was fourteen characters of instruction in a column
        whose whole job is a checkbox, and the button that fixes it is already on the
        page, one hover away.
        """
        local = one["local"]
        if local is None or local.card is None:
            return (f'<span title="{html.escape(t(lang, "pull.no_card_title"))}">'
                    + t(lang, "pull.not_tickable") + "</span>")
        build_id = str(one["build_id"])
        checked = " checked" if build_id in check.tick else ""
        # **A button per row, and it is not a second interface**: it posts exactly one
        # `selected` to the same action the bar posts many to, so the command it runs is
        # `python3 table.py pull --build <this id>` - the same argv the row's own detail
        # page prints (`_argv_of("pull", …)`).  The operator's ask was 「就是想拉取卡片就轻松
        # 一点」: pulling one card should not require ticking a box, finding the bar, and
        # pressing a button that is also holding somebody else's ticks.
        return (f'<input type="checkbox" form="pull-now" name="selected" '
                f'value="{html.escape(build_id)}"{checked}>'
                f'<button class="btn" form="pull-one" name="selected" '
                f'value="{html.escape(build_id)}" '
                f'title="{html.escape(t(lang, "pull.one_title", build=build_id))}">'
                f'{html.escape(t(lang, "pull.one"))}</button>')

    def _no_card_badge(self, rows: Iterable[dict[str, Any]], lang: str = DEFAULT_LANG) -> str:
        """How many of these rows cannot be ticked, as the number the bar owes the reader."""
        without = sum(1 for one in rows
                      if one["local"] is None or one["local"].card is None)
        if not without:
            return ""
        return " " + _badge(t(lang, "counts.without_card", n=without),
                            t(lang, "pull.no_card_title"))

    def _ledger_numbers(self, table: "Builds", records: Records,
                        lang: str = DEFAULT_LANG) -> str:
        """The ledger's four numbers, with the code that produced each one in its title.

        `Records.tally()`, `re.todo()` and `re.transitions()` used to be a whole column
        of `<code>` cells beside these numbers - the page telling the reader which
        function it called, which is a mechanism and therefore a `title=`
        (`05-i18n-prose.md` §B.1).  The engine still owns every one of them: this
        method counts nothing (`00-BRIEF.md` §2).
        """
        return _number_row([
            _number_chip(t(lang, "label.records_in_ledger"), str(len(records)),
                         title=layout.results()),
            _number_chip(t(lang, "label.verdicts"),
                         ", ".join(f"{one}: {many}"
                                   for one, many in sorted(records.tally().items())) or "-",
                         title="Records.tally()"),
            _number_chip(t(lang, "counts.gap"), str(len(self.todo())),
                         title=t(lang, "label.gap") + " - re.todo()"),
            _number_chip(t(lang, "label.regressions"),
                         ", ".join(f"{test}: {len(re_mod.transitions(records, test))}"
                                   for test in DEFAULT_TESTS),
                         title="re.transitions()"),
        ])

    def _numbers_strip(self, check: "Filter | None", lang: str = DEFAULT_LANG) -> str:
        """The counts line, as seven numbers - every one of them a link to the rows it counts.

        The line it replaces said `27 build(s) in /home/…/builds.json, 7 record(s) in
        /home/…/var/results, 50 activit(ies) in /home/…/var/runs`: three absolute paths
        and a plural rule this catalogue does not have, around numbers two of which
        came from `local_rows(check)` - which slices `[offset:offset+limit]`, so a
        hand-typed `?limit=20` rewrote a number that describes this disk and the page
        printed two inventories of one machine that disagreed
        (`03-structure.md` §A2).  Every number here is read **uncapped** - the whole
        table, the whole download tree, every act, the whole ledger, `re.todo()` over
        the whole table, every activity - and every chip links to the rows it counted,
        with the count carried as the target's `limit` where the target caps rows: a
        number a link reproduces cannot be a cap in disguise.

        Two of the seven count a *file* rather than a set any page lists (`cards` is
        `var/state/builds.json`, `records` is `var/results`), so their link is the page
        that is about those rows and their `title` names the file - which is where the
        three paths of the counts line went.  A path is a fact about a number, and a
        fact about a number is a tooltip.
        """
        table, records = self._state()
        held = self.all_locals()
        local_rows = len(held)
        with_bytes = sum(1 for one in held.values() if one.present)
        acts = len(self.pull_acts())
        gap = len(self.todo())
        runs = len(self.runs())
        # The local chips carry the row count as the target's `limit`: `/` caps how
        # many rows it prints, and a chip that counted 53 copies but linked to a
        # 50-row page would be the same lie in a smaller size.  The remote/API chips
        # do not need it - `/runs` and `/jobs` read no API, and `limit` is capped by
        # `MAX_LIMIT` on the way in anyway.
        here = _url("/", check, lang=lang, origin="local",
                    limit=str(min(max(local_rows, 1), MAX_LIMIT)))
        # `cards` gets its own link and not `here`'s: the two numbers are different
        # sets as soon as one directory has no card (52 cards, 53 directories on this
        # workspace), and a chip that counted one set while linking at the other was
        # the one number on the page a reader could not check (`accept.py`'s S6).
        carded = _url("/", check, lang=lang, origin="card",
                      limit=str(min(max(len(table), 1), MAX_LIMIT)))
        kinds = sorted({one.kind for one in self.runs()})
        return _number_row([
            _number_chip(t(lang, "counts.cards"), str(len(table)), href=carded,
                         title=layout.index()),
            _number_chip(t(lang, "counts.here"), str(local_rows), href=here,
                         title=layout.downloads()),
            # `origin="any"` is not decoration: "has bytes on disk" is true of a
            # directory no card names, so a link that inherited `origin=card` from the
            # page it was drawn on printed **8** rows under a chip reading **9**
            # (`6a986b26e41d7f97d6f470bf` is pulled, has two artifacts and no card).
            # The count is `Local.present` over the whole download tree; the link has to
            # be the same set, which is what `accepts` decides once the origin stops
            # narrowing it.
            _number_chip(t(lang, "counts.bytes"), str(with_bytes),
                         href=_url("/", check, lang=lang, origin="any", evidence="bytes",
                                   limit=str(min(max(local_rows, 1), MAX_LIMIT))),
                         title=t(lang, "counts.title_bytes")),
            _number_chip(t(lang, "counts.acts"), str(acts), href="#acts",
                         title=t(lang, "counts.title_acts",
                                 provenance=layout.provenance("x"))),
            _number_chip(t(lang, "counts.records"),
                         str(min(len(records), MAX_LIMIT)),
                         href=_url("/jobs", check, lang=lang,
                                   limit=str(min(max(len(records), 1), MAX_LIMIT))),
                         title=t(lang, "counts.title_records", n=len(records),
                                 dir=layout.results())),
            _number_chip(t(lang, "counts.gap"), str(gap),
                         href=_url("/jobs", check, lang=lang,
                                   limit=str(min(max(gap, 1), MAX_LIMIT))),
                         title=t(lang, "label.gap") + " - re.todo()"),
            _number_chip(t(lang, "counts.activities"), str(runs),
                         # The kinds are spelled out, because `/runs` folds the `table`
                         # activities by default and this number counts **every**
                         # activity on disk: a link that landed on the folded page would
                         # show fewer rows than the chip says, which is the same lie in
                         # a smaller size.  `kind=<every kind>` is the page's own filter
                         # state (`_runs`), so the target is the unfolded /runs.
                         href=_url("/runs", check, lang=lang, kind=",".join(kinds)) if kinds else "",
                         title=layout.runs()),
        ])

    def _correspondence(self, build_id: str, lang: str = DEFAULT_LANG,
                        api: str = "") -> str:
        """One local copy's page: the card, the bytes, the record, the remote row, the ledger.

        `api` is the request's `?api=` key: this page asks the API for the build's
        remote counterpart, so it reads the one the URL names and nothing else.
        """
        build_id = _token(build_id)
        held = self.all_locals()
        if build_id not in held:
            raise errors.ConfigError(t(lang, "error.no_local_copy", build_id=repr(build_id)))
        local = held[build_id]
        check = Filter(limit=self.rows, origin="any", api=api)
        answer = self.remote_rows(check, held, lang)
        remote = next((one for one in answer if one.build_id == build_id), None)
        records = self._state()[1]
        search = build_id[:12]
        runs = [one for one in self.run_rows() if any(search in part for part in one["argv"])]
        body = [
            _h2(t(lang, 'page.correspondence.card_title'),
                hint=t(lang, 'page.correspondence.card_sub')),
            _table((t(lang, "col.field"), t(lang, "col.value")), [
                _row((_cell(t(lang, "word.build_id"), "id"),
                      _cell(f"<code>{html.escape(build_id)}</code>"))),
                _row((_cell(t(lang, "word.describe")),
                      _cell(html.escape(local.card.describe()) if local.card else "-", "wrap"))),
                _row((_cell(t(lang, "word.node_id")),
                      _cell(f"<code>{html.escape(local.card.node_id)}</code>"
                            if local.card and local.card.node_id
                            else (t(lang, "state.no_node_id") if local.card
                                  else t(lang, "state.not_in_table")), "wrap"))),
                _row((_cell(t(lang, "word.tree_branch")),
                      _cell(html.escape(f"{local.card.tree} / {local.card.branch}")
                            if local.card else "-"))),
                _row((_cell(t(lang, "word.arch_defconfig_compiler")),
                      _cell(html.escape(" / ".join(one for one in (local.card.arch,
                                                                   local.card.defconfig,
                                                                   local.card.compiler) if one))
                            if local.card else "-", "wrap"))),
                _row((_cell(t(lang, "word.created")),
                      _cell(html.escape((local.card.created if local.card else "") or "-")))),
                _row((_cell(t(lang, "label.artifact_urls")),
                      _cell("<br>".join(f"<code>{html.escape(name)}: {html.escape(url)}</code>"
                                        for name, url in (local.card.artifacts.items()
                                                          if local.card else [])) or "-", "wrap"))),
            ], cls="card-fields"),
            _h2(t(lang, 'page.correspondence.bytes_title'),
                hint=t(lang, 'page.correspondence.bytes_sub')),
            _table((t(lang, "col.artifact"), t(lang, "col.file"), t(lang, "col.bytes")), [
                _row((_cell(html.escape(name)), _cell(f"<code>{html.escape(path)}</code>", "wrap"),
                      _cell(f"{os.path.getsize(path)} ({_human(os.path.getsize(path))})"
                            if os.path.isfile(path) else "-", "num")))
                for name, path in sorted(local.present.items())],
                empty=t(lang, "empty.no_bytes", path=html.escape(local.path)), cls="bytes"),
            # The path is a fact about this section, and a fact about a section is a
            # tooltip (`02-dedupe.md` §C.0): a heading whose sub-line is
            # `/home/…/var/downloads/<id>/provenance.json` tells a reader the machine's
            # layout where it should be telling them what the section holds.  The row
            # count is the data, and the file is one hover away.
            _h2(t(lang, "page.correspondence.record_title"),
                t(lang, "count.acts_in_record", n=len(local.acts)),
                hint=layout.provenance(local.build_id)),
            _acts_table(local, empty=t(lang, "empty.no_pull_record"), lang=lang),
            _h2(t(lang, "page.correspondence.remote_title"),
                t(lang, "page.correspondence.remote_sub",
                  query=html.escape(self.remote_query(check, lang)))),
            _remote_detail(local, remote, self.remote_query(check, lang), answer.note, lang),
            # The literal used to be the sub-line.  A function name on screen is not a
            # sentence for a reader (`05-i18n-prose.md` §A.4's `Records / todo() /
            # transitions()` complaint); it is where the numbers come from, which is a
            # tooltip's job.
            _h2(t(lang, "page.correspondence.ledger_title"),
                hint="Records.for_build()"),
            _records_table(sorted(records.for_build(build_id),
                                  key=lambda one: one.timestamp or "", reverse=True),
                           empty=t(lang, "empty.no_ledger_record"), lang=lang),
            _h2(t(lang, 'page.correspondence.activities_title'),
                hint=t(lang, 'page.correspondence.activities_sub')),
            _runs_table(runs, empty=t(lang, "empty.no_activity_match"), lang=lang),
            _action_bar("pull", [("selected", build_id)], t(lang, "btn.pull_recheck"),
                        argv=self._argv_of("pull", {"selected": build_id}, lang),
                        hint=t(lang, "correspondence.pull_hint"), lang=lang),
            _action_bar("run", [("selected", build_id)], t(lang, "btn.run_pending"),
                        argv=self._argv_of("run", {"selected": build_id}, lang, api=api),
                        lang=lang, api=api),
        ]
        return self._shell("local", "".join(body), check, [answer.note], lang,
                           route="/local/" + urllib.parse.quote(build_id))

    # --- /jobs --------------------------------------------------------------

    def _jobs(self, check: Filter, lang: str = DEFAULT_LANG) -> str:
        """The gap: what the table minus the ledger leaves, one row per (build, test).

        **One action bar, not one button per row.**  Fifty-one `run` buttons down the
        last column became one bar that owns this table's tick boxes (`form="run-now"`,
        the association `_pull_form` proved, so the bar works with JavaScript off).
        That is a simplification and not a fix: the shape the operator's bug was made
        of - a row button carrying `selected` *and* `test` while the bar beside it
        carried neither - is gone, but the body reader (`_form_body`) is what makes any
        of these POSTs readable, and it stays (`CHANGELOG.md` §1).

        **The bar carries a `test` select, and the select never offers "any".**  That is
        why the test is a control *inside* the bar rather than a value the filter bar
        hands over: `Gui.command` reads `test` out of the body, and a body with no
        `test` at all makes `table.py run` fall back to all three tests, silently.  With
        `placeholder=False` the box always names one test, so the POST always carries
        one, and the box opens on the test in force in the URL.

        The ticks are per **build** and not per (build, test) row: the bar has one test,
        so two ticks of one build would be one command twice.  A box is drawn on the
        first row of each build and the rest of the group shows a dash; the argv under
        the bar is the argv for the test the box is holding.
        """
        table, records = self._state()
        rows = self.job_rows(check)
        gap = [one for one in rows if one["gap"]]
        # The rows are capped; the gap is not.  `re.todo()` owns the number and is asked
        # directly, so the page can show how much of the real gap it is showing.
        whole = len(self.todo(check))
        tests = sorted({one["test"] for one in rows})
        seen: set[str] = set()
        found = []
        for one in rows:
            first = one["build_id"] not in seen
            seen.add(one["build_id"])
            found.append(_row((
                _cell(f'<code>{html.escape(one["build_id"][:16])}</code>', "id"),
                _cell(html.escape(one["tree"])), _cell(html.escape(one["test"])),
                _cell(html.escape(one["needs"]), "wrap"),
                _cell(html.escape(one["reason"] or t(lang, "state.ready")), "wrap"),
                _cell(str(one["runs"]), "num"),
                _cell(_pill(one["verdict"], "verdict")),
                _cell(html.escape((one["when"] or "-")[:16])),
                _cell(t(lang, "state.yes") if one["gap"]
                      else t(lang, "state.already_recorded")),
                # One box per (build, test) row when the page has chosen a test, and one
                # per build when it has not: with no test chosen the bar runs all three
                # tests for every ticked build, so a box per row would be three boxes
                # for one command (`_first` would silently decide which of the three
                # counted).  The operator's 「test 有些好像有但是不能勾选跑不了」 is exactly
                # this column: rows whose test was not the bar's printed a dash.
                _cell(_job_tick(one["build_id"])
                      if ((one["test"] == check.test) if check.test else first)
                      else _other_test_tick(one, check, lang)))))
        body = [
            # The gap as two numbers, where it used to be one sentence carrying four
            # machine plurals ("{shown} row(s) … {whole} (build, test) pair(s) … {cards}
            # card(s) and {records} record(s)").  The numbers stay - how much of the gap
            # this page is showing is the one thing a reader needs - and the code that
            # produced them (`re.todo()`) is the tooltip.
            ('<p class="query">'
             + _number_chip(t(lang, "counts.gap"), str(whole),
                            title=t(lang, "jobs.gap_title", cards=len(table),
                                    records=len(records), limit=check.limit))
             + " " + _number_chip(t(lang, "counts.shown"), str(len(gap))) + "</p>"),
            _filter_bar("/jobs", [self._api_field(check, lang=lang),
                                  self._tree_field(check, rows, lang=lang),
                                  _select("test", ("", *tests), check.test, t(lang, "word.test"),
                                          lang=lang),
                                  _select("ran", RANS, check.ran, t(lang, "filter.ran"),
                                          placeholder=False,
                                          labels=_labels("ran", lang), lang=lang),
                                  _select("verdict", VERDICTS, check.verdict,
                                          t(lang, "filter.verdict"),
                                          labels=_labels("verdict", lang), lang=lang),
                                  self._limit_field("/jobs", check, lang=lang)],
                        check, rendered=("api", "tree", "test", "ran", "verdict", "limit"),
                        lang=lang),
            # The sub-line said what the section *is* ("one command, so one test and any
            # builds"); the true rule is about the control above ("the test chosen there,
            # times every ticked build"), so it is the heading's tooltip and the heading
            # keeps its title.
            _h2(t(lang, 'page.jobs.run_title'), hint=t(lang, 'page.jobs.run_sub')),
            _action_bar("run", [("test", check.test)] if check.test else [],
                        t(lang, "btn.run_ticked"),
                        # Describe, never refuse: the ids do not exist until a box is
                        # ticked, so they are printed as the words that stand for them
                        # (`_argv_of_ticked`) instead of as this bar's own refusal.
                        #
                        # **The bar has no test box of its own any more.**  It used to
                        # carry a `<select name="test">` beside the filter bar's own
                        # `test` box, and the two could disagree: the table was drawn for
                        # one test while the command ran another, and a row for a test the
                        # bar was not holding printed `-` in the tick column - which is
                        # the operator's 「test 有些好像有但是不能勾选跑不了」.  One control now
                        # decides it (the filter's `test`, which is also what filters the
                        # rows), and with no test chosen the command runs all of
                        # `DEFAULT_TESTS` for every ticked build, which is what the bar
                        # says out loud.
                        argv=self._argv_of_ticked("run", {"test": check.test}, lang=lang,
                                                  api=check.api),
                        # A badge, not a sentence (`05-i18n-prose.md` §B.2): what the
                        # command does about the ledger is three words on screen and the
                        # escape hatch is the tooltip.  It replaces a sentence that was
                        # also *false* until `table.py run` learned to skip
                        # (`CHANGELOG.md` §4, `04-actions.md` item 3).
                        note=_badge(t(lang, "jobs.skips_badge"),
                                    title=t(lang, "jobs.run_hint")),
                        form_id="run-now",
                        lang=lang, api=check.api),
            _table((t(lang, "word.build_id"), t(lang, "word.tree"), t(lang, "word.test"),
                    t(lang, "col.needs"), t(lang, "col.ready"), t(lang, "label.runs"),
                    t(lang, "label.last"), t(lang, "col.when"), t(lang, "col.in_gap"),
                    # One box per *build* is drawn, so the select-all counts builds and
                    # not rows: `len({one["build_id"] for one in rows})`.
                    _tick_all("run-now", len({one["build_id"] for one in rows}), lang)),
                   found, empty=t(lang, "empty.no_gap"), cls="jobs"),
            # **The ledger's own rows.**  A gap is a difference between two sets, and
            # this page listed only one of them: the reader could see what is missing
            # and never what is there.  It is also why the numbers strip's `records`
            # chip was the one chip that reproduced nothing - it counted the ledger and
            # pointed here, where no ledger row was drawn (`accept.py`'s S6, added after
            # the merge).  The rows are `Records`' own, newest first, capped by this
            # page's `limit` like every other table; the chip's link carries that same
            # number as `limit`, so the count it prints is the count a reader finds.
            _h2(t(lang, "page.jobs.ledger_title"), hint="Records.load()", id="ledger"),
            _records_table(sorted(records, key=lambda one: one.timestamp or "",
                                  reverse=True)[:check.limit],
                           empty=t(lang, "empty.no_ledger_record"), lang=lang,
                           title=True, api=check.api),
            _h2(t(lang, "page.jobs.day_title"), hint="runday"),
            _action_bar("runday", [("tree", check.tree or "riscv"), ("days", str(check.days)),
                                   ("limit", str(check.limit))],
                        t(lang, "btn.run_day"),
                        argv=self._argv_of("runday", {"tree": check.tree or "riscv",
                                                      "days": str(check.days),
                                                      "limit": str(check.limit)}, lang,
                                           api=check.api),
                        hint=t(lang, "jobs.runday_hint"),
                        inner=_quick("days", "/jobs", check, str(check.days),
                                     _day_choices(lang), lead=t(lang, "filter.days"),
                                     lang=lang), lang=lang, api=check.api),
            _h2(t(lang, 'page.jobs.elsewhere_title'),
                hint=t(lang, 'page.jobs.elsewhere_sub')),
            _action_bar("fetch", [("tree", check.tree or "riscv"), ("test", check.test)],
                        t(lang, "btn.run_newest"),
                        argv=self._argv_of("fetch", {"tree": check.tree or "riscv",
                                                     "test": check.test}, lang, api=check.api),
                        lang=lang, api=check.api),
            _action_bar("results", [("test", check.test)], t(lang, "btn.ledger_full"),
                        argv=self._argv_of("results", {"test": check.test}, lang),
                        hint=t(lang, "jobs.results_hint"), lang=lang),
        ]
        return self._shell("jobs", "".join(body), check, (), lang, route="/jobs")

    # --- /runs --------------------------------------------------------------

    def _runs(self, kind: str = "", state: str = "", lang: str = DEFAULT_LANG,
              api: str = "") -> str:
        """What is happening right now: every Run on disk, its log, and the cancel button.

        `/runs` reads two keys that are not filter fields at all, so its bar is
        the whole page state: no window is carried here, because an activity is
        not a build and a window would be a condition nothing reads.

        `api` is the one key this page carries without reading it.  An activity is
        not a build either - but the commands an operator runs *from* here are, and
        walking `/remote` (production) -> `/runs` -> `/remote` used to land back on
        the startup base with nothing said.  So the key rides as page state through
        the navigation and the language switch, and through this page's own form as
        a hidden field (`_form` writes any `ROUTE_KEYS` entry the page has no control
        for), and it is shown as a chip - a page that carries a condition says so.
        """
        # `api_base` is filled even when the URL carries no `api` key: this page hands
        # the key on without reading the API, and the strip's `api` axis has to name the
        # stack that key *means* - "any" beside a page that is carrying `api=local` into
        # every link would be the same under-reporting the F3 complaint is about.
        carried = Filter(api=api, api_base=self.apis.base(api))
        runs = self.run_rows()
        kinds = sorted({one["kind"] for one in runs})
        # **The bookkeeping is folded, and the fold is this page's filter state.**
        # 37 of the 50 activities here are `table.py index`, and they were interleaved
        # with the run the reader was watching - the operator's "为什么拉取或者这里就
        # run 也会显示".  `kind` arrives empty from a plain `/runs` and is filled with
        # the kinds the page shows, so everything downstream - the select box, the axes
        # strip, `rows_of`, and the 2 s poll's own guard - sees one answer to one
        # question.  A fold applied inside the renderer would be undone by the poll two
        # seconds later, which is the failure this whole file is about
        # (`docs/gui-rework/04-actions.md` §P8a).
        every = ",".join(kinds)
        asked = kind                       # what the URL said, before the fold fills it in
        folded = kind == "" and bool(FOLDED_KINDS)
        if folded:
            kind = ",".join(one for one in kinds if one not in FOLDED_KINDS)
        shown = self.run_rows(kind, state)
        body = [
            _filter_bar("/runs", [_select("kind", ("", *kinds), kind, t(lang, "word.kind"),
                                          lang=lang),
                                  _select("state", ("", run_mod.RUNNING, run_mod.DONE,
                                                    run_mod.FAILED, run_mod.CANCELLED),
                                          state, t(lang, "word.state"),
                                          labels=_labels("run_state", lang), lang=lang)],
                        carried, rendered=("kind", "state"),
                        keep=[("kind", kind), ("state", state)], lang=lang),
            # No intro sentence: it was four facts with no number, column or link in
            # them ("every activity is a directory with run.json and run.log; the argv
            # column is the exact command an operator would type; drift exits 1 when the
            # configs differ"), and accept.py's W1 found it after the first prose pass.
            # Each one is a `title=` now - the directory on the id cell, the full argv
            # on the argv cell (which always had it), the drift exit code on a drift
            # row's exit cell (`_runs_table`) - which is where `05-i18n-prose.md` §B.1
            # puts a fact a reader wants once, and never a paragraph over the table.
            # `rows_of="all"` only while the rows on screen are the whole list.  This is
            # the one activity table the 2 s poll may re-render, and the poll fetches
            # `/api/runs` with no filter at all: re-rendering a folded table would put
            # the 37 `table` rows back two seconds after the page said they were folded
            # - the "silently undone filter" `04-actions.md` §d.1 warns about, one level
            # up, and the same bug as `/pull` drawing one row and showing fifty.
            _runs_table(_by_kind(shown), empty=t(lang, "empty.no_activity"), lang=lang,
                        group=True,
                        rows_of="all" if (kind == every and not state) else ""),
            # A default that hides rows has to be *stated*, and undone in one click: the
            # count is in the group captions below and the box above, so this is the
            # link and nothing else (`05-i18n-prose.md` §B.1's four allowed classes).
            # The link spells **every** kind out.  Dropping `kind` instead would land on
            # a URL with no `kind` key, which is the *folded* page - a "show everything"
            # that shows the same rows is worse than no link at all.
            ('<p class="note">' + t(lang, "runs.folded_note",
                                    link=f'<a href="{html.escape(_url("/runs", carried, kind=every, lang=lang))}">'
                                         f'{html.escape(t(lang, "runs.show_all"))}</a>')
             + "</p>" if folded and kind else ""),
        ]
        return self._shell("runs", "".join(body), carried, (), lang, route="/runs",
                           # `asked`, not the folded `kind`: the language switch, the
                           # refresh control and the nav links are the same URL this
                           # page was reached by, so a bare `/runs` stays a bare
                           # `/runs` (folded, with its note) instead of turning into an
                           # explicit six-kind filter the reader never chose.
                           lang_keep=(("kind", asked), ("state", state)))

    # --- /worker ------------------------------------------------------------

    def _worker(self, check: Filter, lang: str = DEFAULT_LANG, state: str = "", mode: str = "",
                platform: str = "", runtime: str = "") -> str:
        """The queue the worker claims from, what it has handled, and the commands to start it.

        The worker's own three arguments (mode, platform, runtime) are page keys
        rather than boxes inside the button's form: a box the command line cannot
        show is a box that can disagree with the command line.  They are offered
        as one link per value (`_quick`), so the URL always says which command the
        button below it will run.
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
        }
        platforms = sorted({one["platform"] for one in all_nodes if one["platform"]}
                           | {DEFAULT_DEVICE})
        runtimes = sorted({one["runtime"] for one in all_nodes if one["runtime"]} | {DEFAULT_LAB})
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
                        keep=[("mode", picked["mode"]), ("platform", picked["platform"]),
                              ("runtime", picked["runtime"])], lang=lang),
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
                        argv=self._argv_of("worker", picked, lang, api=check.api),
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
                                            ("runtime", picked["runtime"])], lang=lang)
                               + _quick("platform", "/worker", check, picked["platform"],
                                        [(one, one) for one in platforms],
                                        lead=t(lang, "word.platform"),
                                        keep=[("mode", picked["mode"]),
                                              ("runtime", picked["runtime"])], lang=lang)
                               + _quick("runtime", "/worker", check, picked["runtime"],
                                        [(one, one) for one in runtimes],
                                        lead=t(lang, "word.runtime"),
                                        keep=[("mode", picked["mode"]),
                                              ("platform", picked["platform"])], lang=lang)),
                        lang=lang, api=check.api),
        ]
        return self._shell("worker", "".join(body), check, [note], lang, route="/worker",
                           lang_keep=[("state", state), *picked.items()])

    # --- /analysis ----------------------------------------------------------

    def _analysis(self, check: Filter, older: str = "", newer: str = "",
                  lang: str = DEFAULT_LANG, point: str = "",
                  delta: int = DEFAULT_DELTA) -> str:
        """One model for both halves: select, sort, list with a `±`, chart.

        The operator's own design, and the whole page follows it:

        > 首先我通过筛选构建…下面是一个列表…还有就是一个排序…筛选决定了下面的构建是哪些，
        > 排序决定了这个构件以什么样的方式排序…排序决定了它以前一个序和后一个序进行一个比
        > 较…旁边可以写成那种加减…还可以画出一个图…回归分析也应该是类似一样搞

        **Selection decides the content; the order decides the comparison.**  The
        filter bar chooses the rows (`Filter.accepts`, plus `older`/`newer`/`test`),
        `sort` decides their order (a `Filter` field, so every link carries it), the
        list is in that order with an adjacent `±` against the row before *and* the row
        after, and a horizontal chart is drawn in the same order underneath.  The
        regression half is the same shape with the `test` chosen first.

        Costs, because this page has two expensive things and one of them is new:

        * the two builds the drift block names are read through `var/configs/`
          (`lib/drift.py`): the first look at a pair downloads two ~194 KB configs and
          every look after that is a file read (measured 15.92 s cold, 0.01 s warm,
          0 HTTP - `CHANGELOG.md` §2).  The comparison is eager, and *not* gated behind
          `?drift=1` as `06-analysis.md` §B4 proposed: with the cache in place the
          second load of this page costs nothing for it, a gate would put the only
          answer a reader came for behind a click (§D3's "hidden click"), and
          `accept.py`'s X2 asks a named pair for its detail *without* any such key -
          the check is right to, because the capability is what the operator asked for.
        * the `±` column reads **at most `delta` rows'** configs (`?delta=`, 0..6,
          default 3), one read per build, all of them from the cache after the first
          time.  `06-analysis.md` §D2 prices a pair at 7.5-12.5 s and ~194 KB cold,
          which is why the cap exists, why it is clamped here and not in the URL, and
          why the number in force is printed on the page.

        The trend half costs nothing: the ledger is on disk and read once per request.
        """
        records = self._state()[1]
        held = self.all_locals()
        # One read, two uses: the ids are the list the page can name, the `Kbuild`s are
        # what `Drift` needs - it must not scan the window for ids this page is showing.
        known, builds = self._known_builds(check.api, check.limit)
        catalogue = Kbuilds(self._client(self.api_base(check)), items=builds)
        rows = _build_rows(known, builds, check, records, held, lang)
        # The order, once: the list, the deltas and the chart all read this one answer.
        ordered = _sort_rows(rows, check.sort)[:check.limit]
        # The pair: what the URL named, else the page's own choice (`_chosen_pair`),
        # made against the *date* order - "the newest" is a fact about time, not about
        # the view the reader happens to have chosen.
        older, newer = _chosen_pair(_sort_rows(rows, "date"), older, newer)
        # **An id this page did not read is refused, never looked up.**  `older`/`newer`
        # are free text now, and `Drift.between` finds a build it was not handed by
        # asking the API for it - and the API can only be asked by *scanning* the newest
        # `SCAN` nodes, once per id: measured at 116.8 s and 137.9 s on production, and
        # it fails outright when one page of that scan comes back truncated
        # (`06-analysis.md` §A7.1, §D3).  A GET may not start that.  So the pair is
        # checked against the builds `_known_builds` already read (cards plus the rows
        # the API just answered), the refusal names the id, and `run drift.py` - an
        # activity, with its cost printed beside it - stays the way to go and look.
        unread = [one for one in (older, newer) if one and one not in set(known)]
        if unread:
            report = {"error": t(lang, "analysis.not_read", build=unread[0]),
                      "older": older, "newer": newer}
        elif older and newer:
            report = self.drift(older, newer, lang, check.api, catalogue=catalogue)
        else:
            report = {}
        # The compared head of the order, and its comparisons: `delta` rows at most, so
        # `delta`-1 adjacent pairs, and the ends of *that* are the ends the list prints.
        head = ordered[:max(0, int(delta))]
        edges = (self._config_edges(head, catalogue, check, lang) if len(head) > 1 else [])
        # Which configs this render read at all: the pair's two, plus the ones the
        # `±` column needed.  A number, not a sentence about caching - and the one a
        # reader weighing a reload or a bigger `delta` is looking for.
        edge_builds = {older, newer} | {row["build_id"] for row in head if row["config"]}
        page_keys = [("older", older), ("newer", newer), ("point", point),
                     ("delta", str(delta))]
        test = check.test or DEFAULT_TESTS[0]
        trends = {one: self.trend(one, check.limit)["points"] for one in DEFAULT_TESTS}
        trend_rows = _sort_rows(_trend_rows(trends[test], held, lang), check.sort)
        trend_edges = _trend_edges(trend_rows)
        # The chart's slots, once: one ledger lookup per position of the page's order.
        wave = _wave_slots(ordered, records, test)
        selected = next((one["point"] for one in trend_rows
                         if point and one["build_id"] == point), None)
        order_label = _sort_label(_sort_keys(check.sort), lang)
        body = [
            _filter_bar("/analysis", [
                # **The same axes the builds page has** - one template, as asked
                # (`像前面学习就是应该有类似统一的分析就是模板`).  The page's own three controls
                # follow: which test, the order, and how many rows may spend a config
                # read on their neighbours.
                *self._build_axes("/analysis", check, lang=lang),
                _select("test", DEFAULT_TESTS, test, t(lang, "word.test"), lang=lang),
                # The control is `limit`, which is the field `trend()` reads and the one
                # `Filter` has always had.  The page used to offer `scope`, which nothing
                # read: `?scope=10` did nothing while `?limit=10` worked.
                # (`/api/analysis/trend` keeps `scope` - that is its own contract,
                # GUI.md §4, and it is not this control.)  On this page it caps both
                # lists, which is what its label says it does.
                self._limit_field("/analysis", check, keep=page_keys, lang=lang),
                _sort_control("/analysis", check, _sort_keys(check.sort), keep=page_keys,
                              lang=lang),
                _datalist("deltas", [str(one) for one in range(MAX_DELTA + 1)]),
                _num("delta", str(delta), t(lang, "delta.cap"), 0, MAX_DELTA, "deltas",
                     stops=[str(one) for one in range(MAX_DELTA + 1)]),
                # The free hand: one input per key, and a candidate list that suggests
                # without constraining.  A typed id this page did not read is refused
                # (`drift()` hands `Drift` the catalogue, and an id outside it would be
                # a 1 000-node scan *inside a GET* - §D3), which the datalist is here to
                # make unnecessary: pasting the id of a row on this page always works.
                _datalist("builds", [row["build_id"] for row in ordered],
                          {row["build_id"]: row["ref"] for row in ordered}),
                _name_field("older", older, t(lang, "filter.older"), "builds", lang),
                _name_field("newer", newer, t(lang, "filter.newer"), "builds", lang)],
                check,
                # `sort` is deliberately **not** in `rendered`: its control is a row of
                # *links* (`_quick`), and a link is not a form field - so `_form` has to
                # carry it as a hidden input, or pressing `apply` after typing an id
                # would silently drop the order and compare neighbours the reader never
                # chose.  The six names here are the six real inputs/selects above.
                rendered=("api", "test", "limit", "delta", "older", "newer"),
                keep=page_keys, lang=lang),
            _h2(t(lang, "page.analysis.picks_title"),
                t(lang, "page.analysis.picks_sub", shown=len(ordered), pool=len(rows),
                  order=order_label)),
            _picks_table(ordered, check, older, newer, page_keys, len(head), edges, lang),
            (_h2(t(lang, "chart.title"), t(lang, "chart.sub", n=len(edges), order=order_label))
             + _bar_chart(edges, lang)) if edges else "",
            _h2(t(lang, "page.analysis.drift_title"),
                self._pair_line(report, older, newer, edge_builds, lang)),
            # **The full diff is not printed here.**  It was 265 KB of the page's 394 KB
            # (67 %), i.e. hundreds of `CONFIG_` names under a page whose question is
            # *which builds* - and the operator said what to do with it: 「就不用列一大串了」.
            # The badge above carries the arithmetic, the two raw `.config` links open the
            # files themselves, and the detail route prints the whole comparison for the
            # pair the reader actually wants to read.
            (_pair_doors(report, older, newer, check, lang) if report else
             "<p>" + t(lang, "analysis.choose_two",
                       link=_link("/local", Filter(api=check.api), (), "/local", lang)) + "</p>"),
            _action_bar("drift", [("older", older), ("newer", newer)],
                        t(lang, "btn.run_drift"),
                        argv=self._argv_of("drift", {"older": older, "newer": newer}, lang,
                                           api=check.api),
                        hint=t(lang, "analysis.drift_hint"), lang=lang, api=check.api),
            _h2(t(lang, "page.analysis.trend_title"),
                t(lang, "page.analysis.trend_sub", test=html.escape(test),
                  n=len(trends[test]), order=order_label)),
            _table((t(lang, "word.test"), t(lang, "label.runs"), t(lang, "label.last"),
                    t(lang, "label.regressions"), t(lang, "col.timeline")), [
                _row((_cell(html.escape(one)),
                      _cell(str(len(records.series(one))), "num"),
                      _cell(_pill(_last_verdict(records, one), "verdict")),
                      _cell(str(len(re_mod.transitions(records, one))), "num"),
                      _cell(_timeline(trends[one], check, page_keys, point, one, lang),
                            "wrap")))
                for one in DEFAULT_TESTS], cls="timeline-rows"),
            _h2(t(lang, "page.analysis.runs_title", test=html.escape(test)),
                t(lang, "page.analysis.runs_sub", n=len(trend_rows), cap=check.limit)),
            _trend_table(trend_rows, check, page_keys, point, test, len(trend_rows),
                         trend_edges, lang),
            # **The chart** (the operator's own ask: 回归分析还要加一个图，坐标就是排序的
            # 坐标).  It is drawn over the page's whole order - every row the list can name,
            # gaps included - because a chart that quietly dropped the positions with no
            # record would hide the one thing a reader looks for: a test that stopped.
            # The two numbers on its heading are counted from the same slots the chart
            # drew (`_wave_slots`), so the sentence and the picture cannot disagree.
            (_h2(t(lang, "chart.band_title", test=html.escape(test), order=order_label),
                 t(lang, "chart.band_sub", n=len(wave),
                   ran=sum(1 for one in wave if not one["gap"]),
                   gap=sum(1 for one in wave if one["gap"])), id="wave")
             + _wave_chart(wave, check, page_keys, point, test, lang)) if wave else "",
            _record_block(selected, held, next((row["ref"] for row in rows
                                                if row["build_id"] == point), ""),
                          lang) if selected else
            # A `point` the chosen test's list does not hold (a hand-made URL, or a
            # `point` left over from another test): the heading and its hint, rather
            # than silence.  A page that says nothing about a key it was given is the
            # silent no-op this whole rework is against.
            (_h2(t(lang, "page.analysis.point_title"), t(lang, "page.analysis.point_sub"))
             if point else ""),
        ]
        return self._shell("analysis", "".join(body), check, (), lang, route="/analysis",
                           lang_keep=tuple(page_keys))

    def _one_build(self, build_id: str, check: Filter, versus: str = "",
                   lang: str = DEFAULT_LANG) -> str:
        """One build, and — when `?vs=` names another — the whole comparison between them.

        This is the route the operator asked for twice: the single view (「单个那种也可能
        还要专门开发一个」) and the place the differences actually live (「点击会看到它那个
        比较…就不用列一大串了」).  A list of five hundred builds cannot print five hundred
        diffs; it can print five hundred numbers, and every one of those numbers is a
        door to here.

        The neighbours are recomputed rather than trusted from the URL: the filter and
        the order ride in the link (`_compare_url`), so this page runs the same
        `_known_builds` → `_build_rows` → `_sort_rows` pipeline the list ran and finds
        this build's position in it.  That is what makes "its neighbours" mean the
        neighbours *in the order the reader was looking at* - which is the operator's
        whole model: 排序决定了它以前一个序和后一个序进行一个比较.

        Nothing is fetched that the page did not already need: the same one API read,
        the same local table, the same ledger.  The comparison itself is the pair's two
        configs, and its cost is printed beside it (`page.analysis.drift_sub`).
        """
        records, held = self._state()[1], self.all_locals()
        known, builds = self._known_builds(check.api, check.limit)
        catalogue = Kbuilds(self._client(self.api_base(check)), items=builds)
        rows = _sort_rows(_build_rows(known, builds, check, records, held, lang),
                          _sort_keys(check.sort))
        here = next((at for at, row in enumerate(rows) if row["build_id"] == build_id), None)
        row = rows[here] if here is not None else next(
            (one for one in _build_rows(known, builds, check, records, held, lang)
             if one["build_id"] == build_id), None)
        order_label = _sort_label(_sort_keys(check.sort), lang)
        body = [_h2(t(lang, "page.one.title"),
                    t(lang, "page.one.sub", build=html.escape(_short(build_id, 16))))]
        if row is None:
            body.append("<p>" + t(lang, "one.no_neighbours") + "</p>")
        else:
            body.append(f'<p class="query">{row["line"]}<br>{row["marks"]}</p>')
        # The two neighbour comparisons of the order this build was clicked from.
        if here is not None:
            doors = []
            for at, name in ((here - 1, "delta.before"), (here + 1, "delta.after")):
                if 0 <= at < len(rows):
                    other = str(rows[at].get("build_id") or "")
                    doors.append(f'<a href="{html.escape(_compare_url(build_id, other, check, lang))}">'
                                 f'{html.escape(t(lang, name))} {html.escape(other[:12])}</a>')
            body.append(_h2(t(lang, "one.neighbours"),
                            t(lang, "page.analysis.picks_sub", shown=len(rows),
                              pool=len(known), order=order_label))
                        + ('<p class="query">' + " &middot; ".join(doors) + "</p>" if doors
                           else ""))
        # The comparison itself: the pair the URL names, or the one the operator picked.
        pair_older, pair_newer = (build_id, versus) if versus else ("", "")
        if pair_older and pair_newer:
            unread = [one for one in (pair_older, pair_newer) if one not in set(known)]
            report = ({"error": t(lang, "analysis.not_read", build=unread[0])}
                      if unread else
                      self.drift(pair_older, pair_newer, lang, check.api,
                                 catalogue=catalogue))
            configs = {one for one in (pair_older, pair_newer) if one}
            body.append(_h2(t(lang, "one.compare_title"),
                            self._pair_line(report, pair_older, pair_newer, configs, lang),
                            id="drift")
                        + _drift_block(report, lang)
                        + _action_bar("drift", [("older", pair_older), ("newer", pair_newer)],
                                      t(lang, "btn.run_drift"),
                                      argv=self._argv_of("drift",
                                                         {"older": pair_older,
                                                          "newer": pair_newer},
                                                         lang, api=check.api),
                                      hint=t(lang, "analysis.drift_hint"), lang=lang,
                                      api=check.api))
        else:
            body.append(_h2(t(lang, "one.compare_title"),
                            t(lang, "one.compare_line", older=html.escape(build_id[:12]),
                              newer="&mdash;")))
            # The chooser is the same page with `?vs=` filled in: the reader types the
            # other id into the one form above (which carries `vs` through `lang_keep`),
            # so this only has to name the key.  A link that guessed a build would be
            # comparing something nobody asked for.
            body.append("<p>" + t(lang, "one.vs_choose",
                                  link='<code>?vs=&lt;build_id&gt;</code>') + "</p>")
        body.append('<p class="query"><a href="'
                    + html.escape(_url("/analysis", check, "older", "newer", lang=lang))
                    + '">' + t(lang, "one.back") + "</a></p>")
        return self._shell("analysis", "".join(body), check, (), lang,
                           route="/analysis/" + urllib.parse.quote(build_id),
                           lang_keep=(("vs", versus),) if versus else ())

    def _pair_line(self, report: dict[str, Any], older: str, newer: str,
                   configs: "set[str]", lang: str = DEFAULT_LANG) -> str:
        """The pair's own line: which two builds, what kind of pair, how much drift, what it cost.

        The **badge** this page was missing.  Asked for two builds that differ by
        hundreds of options it renders hundreds of `CONFIG_` names; asked for nothing in
        particular it used to render one, because the default pair differed by a single
        option - honest, and read as `显示太少了` (`08-PLAN.md`, step 6's own finding).
        So the pair is named, the numbers are printed *before* the detail, and a pair
        that moved nothing says `+0 −0 ~0` here rather than leaving the reader to
        conclude the comparison is broken.

        The kind word is not decoration either: the engine refuses nothing on tree or
        branch, so 616/618/99 across two trees is a real number that must not be read as
        one kernel moving (`06-analysis.md` §D1).  The last number is `page.analysis.drift_sub`:
        how many builds' configs this render actually read, which is the fact that makes
        a reload cheap or expensive.
        """
        if not (older and newer):
            return ""
        same = report.get("same")
        kind = (t(lang, "drift.same_branch") if same else
                t(lang, "drift.cross_tree") if same is False else "")
        counts = (t(lang, "drift.badge", added=report["summary"]["added"],
                    removed=report["summary"]["removed"],
                    changed=report["summary"]["changed"])
                  if report and not report.get("error") else
                  t(lang, "delta.cannot") if report.get("error") else "")
        refs = " &rarr; ".join(html.escape(one) for one in
                               (report.get("older_ref") or older[:12],
                                report.get("newer_ref") or newer[:12]))
        cost = t(lang, "page.analysis.drift_sub", n=len([one for one in configs if one]))
        return " · ".join(part for part in (refs, kind, counts, cost) if part)

    def _config_edges(self, rows: list[dict[str, Any]], catalogue: Kbuilds,
                      check: Filter, lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
        """The comparisons between consecutive rows of the page's own order.

        One `Drift.series` call per **contiguous run of comparable rows**, so each
        build's config is read once and the six-millisecond difference is not the point -
        *one read per build, N-1 comparisons* is a sentence a reader can check
        (`lib/drift.py`).  Every read goes through `var/configs/`, so the first look at
        a pair downloads it and every look after that is a file read; nothing here
        fetches in a loop beyond the cap the reader set.

        A row with no card (`var/downloads/<id>/` and nothing in the table) has no
        `Kbuild` at all, so it cannot be a side of a comparison and it breaks the run:
        the two edges around it are recorded as refusals rather than skipped, because a
        list whose adjacency silently jumped a row would compare the wrong two builds
        (`这个为什么比不了` has to be answerable *per row*).

        A refused pair keeps its place and carries the engine's own words.
        """
        client = self._client(self.api_base(check))
        edges: list[dict[str, Any]] = []
        at = 0
        while at < len(rows) - 1:
            if rows[at]["kbuild"] is None or rows[at + 1]["kbuild"] is None:
                edges.append({"older": rows[at]["kbuild"], "newer": rows[at + 1]["kbuild"],
                              "report": None,
                              "error": t(lang, "state.no_card_in_table"),
                              "why": t(lang, "state.no_card_in_table")})
                at += 1
                continue
            run = [rows[at]]
            while at + 1 < len(rows) and rows[at + 1]["kbuild"] is not None:
                run.append(rows[at + 1])
                at += 1
            found = Drift.series(client, [row["kbuild"] for row in run],
                                 job=KBUILD_JOB, catalogue=catalogue)
            for older, newer, outcome in found:
                if isinstance(outcome, errors.KciError):
                    edges.append({"older": older, "newer": newer, "report": None,
                                  "error": str(outcome), "why": ""})
                else:
                    edges.append({"older": older, "newer": newer, "report": outcome,
                                  "error": "", "why": ""})
        return edges

    def _known_builds(self, api: str = "", rows: int = 0) -> tuple[list[str], list[Kbuild]]:
        """The builds a page can name: their ids, and the builds themselves.

        Two sources, and both are reads this page was going to make anyway:

        * **what we hold** (`all_locals()`): the table's cards, plus the directories
          under `var/downloads/` that no card names - a directory is still bytes, and
          its id may still be worth offering.  A card carries its own `Kbuild`
          (`Build.kbuild`, the row the API answered when it was registered), and that
          is the object to hand on: it is the row the artifacts were pulled from.
        * **what the API just answered** (`remote_rows`, capped like every read of a
          page).  Its rows are `Kbuild` objects already.

        The ids come out in one stable order - what we hold first, then the API's
        answers - deduplicated: the same list the page has always offered, from the same
        two reads (step 6 draws it as a table of links rather than as two `<select>`es,
        and sorts it for display; this is the *pool*, so a row that is off the end of a
        sort is still an id the page can name and compare).  The objects are what
        `/analysis` hands to `Drift` - it needs both builds' artifacts, and it must not
        scan the window again for ids this page is looking at right now (`drift()`, and
        `lib/kbuild.py: SCAN` for what that scan costs).

        `api` is the page's key: which API the box offers ids from is the same
        decision as which one the page reads - a box built from the local stack while
        the page asks production would offer two ids nobody there has heard of.

        `rows` is how many the API read may return, and it is the *reader's* `rows`
        and not a constant.  It used to be a hard `200`, and on this page that was
        the single most expensive line in the whole program: `/analysis` renders
        about 190 ids whether the reader asked for 50 rows or 500, and the API's
        cost is per row, not per query (`06-analysis.md` §A0 measured a 189-row
        read at 687 565 B and 31.14s where the same offset at `limit=50` answered
        the *identical page* in 153 651 B and 2.01s).  So the cap here is the one
        the reader chose, and a reader who wants a long chooser asks for more rows -
        which is exactly the control `rows` is.
        """
        ids: list[str] = []
        items: list[Kbuild] = []
        for build_id, local in self.all_locals().items():
            ids.append(build_id)
            if local.card is not None:
                items.append(local.card)
        for kbuild in self.remote_rows(Filter(limit=rows or self.rows, origin="any", api=api)):
            if kbuild.build_id not in ids:
                ids.append(kbuild.build_id)
                items.append(kbuild)
        return ids, items


# ---------------------------------------------------------------------------
# Rendering only
# ---------------------------------------------------------------------------

_CSS = """
/* The one stylesheet.  No @import, no CDN, no web font, no image: the page has
   to open on a machine with no network.  Fonts come from the system stack.
   Chrome / Firefox / Safari of 2026; `position: sticky` is used, `:has()` is not.
   Comments here are English like the rest of the tree; the numbers are measured,
   not eyeballed - see the contrast note under the tokens. */

/* ---------------------------------------------------------------------------
   1. Tokens: every colour is named here and nowhere else.  The dark theme swaps
   tokens only, never a selector: a selector missed in one theme is one unreadable
   element with no second way to notice it.

   Measured contrast (ink on background), light: ok 7.95  bad 7.48  warn 6.62
   err 7.39  info 7.22  idle 8.09  body 15.31  muted 6.00 - all above AA 4.5:1,
   which the 11.5px pill needs.  Dark: ok 9.82  bad 9.27  warn 9.59  err 9.21
   info 8.83  idle 8.12  body 14.90.  Changing a colour means recomputing these.
   A manual theme switch would be a second thing to persist; not this round.
   --------------------------------------------------------------------------- */
:root {
  color-scheme: light dark;

  /* Body text in a sans stack, anything a machine reads in a mono one.  The CJK
     fallbacks are spelled out: some systems pick a very ugly CJK mono first. */
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
          "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;

  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  --r: 6px;             /* the one corner radius; pills use 999px, nothing else */
  --max: 1500px;        /* reading width: eleven columns fit without folding */
  --head-h: 96px;       /* the sticky header's height; thead sticks below it.
                           Change this whenever .site-head changes height, or the
                           header row slides under the navigation. */

  --bg: #f5f6f8; --fg: #1b1f24; --muted: #5a6472; --line: #d7dce2;
  --card: #ffffff; --card-2: #f1f3f6; --hl: #eaf1fd;
  --link: #0b4a8f; --focus: #1a5fb4;

  --ok-ink: #0f5132;   --ok-bg: #dbf2e4;   --ok-bd: #93d3ae;
  --bad-ink: #842029;  --bad-bg: #fbdede;  --bad-bd: #f0a9a9;
  --warn-ink: #7a4b00; --warn-bg: #fdf1d8; --warn-bd: #e6c583;
  --err-ink: #6d2a86;  --err-bg: #f3e3fa;  --err-bd: #d4aee4;
  --info-ink: #0b4a8f; --info-bg: #ddeafc; --info-bd: #a9c9ef;
  --idle-ink: #41474d; --idle-bg: #eceef1; --idle-bd: #c9ced4;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131619; --fg: #e6e9ec; --muted: #9aa4af; --line: #2b3138;
    --card: #1a1e22; --card-2: #22272c; --hl: #1d2b3f;
    --link: #7cb0f0; --focus: #7cb0f0;

    --ok-ink: #8ff0b4;   --ok-bg: #13351f;   --ok-bd: #2f6b45;
    --bad-ink: #ffb4b4;  --bad-bg: #3a1a1a;  --bad-bd: #7a3a3a;
    --warn-ink: #ffd28a; --warn-bg: #3a2c10; --warn-bd: #7a5c22;
    --err-ink: #e2b6f5;  --err-bg: #2f1a3a;  --err-bd: #6b3f80;
    --info-ink: #a8cdf7; --info-bg: #122a45; --info-bd: #2f5a86;
    --idle-ink: #c3c8ce; --idle-bg: #2a2e33; --idle-bd: #474d54;
  }
}

/* ---------------------------------------------------------------------------
   2. The ground: body text in sans, ids and paths and commands in mono
   --------------------------------------------------------------------------- */
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 14px/1.5 var(--sans); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

code, .mono { font-family: var(--mono); }
code { padding: 0 4px; font-size: .92em; background: var(--card-2);
       border: 1px solid var(--line); border-radius: 4px; white-space: nowrap; }
.id, td.id code { font-size: 12.5px; white-space: nowrap; }
.argv { display: inline-block; padding: 2px 6px; }

:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }

/* ---------------------------------------------------------------------------
   3. Header / meta line / main / sections
   --------------------------------------------------------------------------- */
.site-head { position: sticky; top: 0; z-index: 20;
             background: var(--card); border-bottom: 1px solid var(--line); }
.site-head .in { display: flex; flex-wrap: wrap; align-items: baseline;
                 gap: var(--s1) var(--s4); max-width: var(--max);
                 margin: 0 auto; padding: var(--s2) var(--s4); }
.site-head h1 { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: -.01em; }
.site-head h1 .sub { font-size: 13px; font-weight: 400; color: var(--muted); }

nav.pages { display: flex; flex-wrap: wrap; gap: 2px; }
nav.pages a, nav.pages b { padding: 3px 9px; font-size: 13px; border-radius: var(--r); }
nav.pages b { background: var(--hl); font-weight: 650; }
nav.pages a:hover { background: var(--card-2); text-decoration: none; }

/* The language slot is empty until the bilingual round wires it up: the space is
   reserved here so that round changes nothing about this layout. */
.lang { display: flex; gap: 6px; margin: 0 0 0 auto; font-size: 12.5px; }
.lang a[aria-current="true"] { font-weight: 700; text-decoration: underline; }

.meta { max-width: var(--max); margin: 0 auto; padding: var(--s2) var(--s4) 0;
        color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap;
        align-items: baseline; gap: var(--s1) var(--s3); }
main { max-width: var(--max); margin: 0 auto; padding: var(--s2) var(--s4) var(--s6); }

/* ---------------------------------------------------------------------------
   3b. The numbers: one chip per number, and the chip is the link.

   The counts line was three sentences with three absolute paths in them; this is
   the same information as seven pressable numbers.  `.k` is the noun, `.n` is the
   number: two elements and not one string, because no plural rule in this
   catalogue could agree `row`/`rows` with an arbitrary count, and the number has
   to line up under the number (that is what `tabular-nums` is for).
   --------------------------------------------------------------------------- */
.numbers { display: flex; flex-wrap: wrap; align-items: baseline;
           gap: var(--s1) var(--s3); margin: 0; }
.numbers .chip { display: inline-flex; align-items: baseline; gap: 5px;
                 padding: 1px 8px; border: 1px solid var(--line);
                 border-radius: 999px; background: var(--card); color: var(--fg); }
.numbers .chip .k { color: var(--muted); font-size: 11.5px; }
.numbers .chip .n { font-variant-numeric: tabular-nums; }
a.chip:hover { background: var(--hl); text-decoration: none; border-color: var(--focus); }

/* A badge: one short fact, its explanation in the tooltip.  This is the shape the
   page uses where it used to print a sentence (docs/gui-rework/05-i18n-prose.md
   §B.2), and `{n} without a card` under the pull bar is the first one. */
.badge { display: inline-block; padding: 0 7px; font-size: 11.5px; line-height: 1.6;
         border: 1px dashed var(--idle-bd); border-radius: 999px;
         background: var(--idle-bg); color: var(--idle-ink);
         font-variant-numeric: tabular-nums; }

h2 { margin: var(--s5) 0 var(--s2); font-size: 15px; font-weight: 650; }
h2 span { margin-left: var(--s2); font-size: 12.5px; font-weight: 400;
          color: var(--muted); }

.card { margin: 0 0 var(--s4); padding: var(--s3) var(--s4);
        background: var(--card); border: 1px solid var(--line);
        border-radius: var(--r); }

footer.site { max-width: var(--max); margin: var(--s5) auto 0;
              padding: var(--s3) var(--s4); font-size: 12px; color: var(--muted);
              border-top: 1px solid var(--line); }

/* ---------------------------------------------------------------------------
   4. The filter bar: one row, label above control, wrapping on a narrow screen.
      It is the page's only GET form.
   --------------------------------------------------------------------------- */
.toolbar { display: flex; flex-wrap: wrap; align-items: flex-end;
           gap: var(--s2) var(--s3); margin: 0 0 var(--s3);
           padding: var(--s2) var(--s3); background: var(--card);
           border: 1px solid var(--line); border-radius: var(--r); }

.field { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.field > label { font-size: 11px; color: var(--muted); letter-spacing: .02em; }
.field input, .field select { height: 30px; padding: 0 6px; font: inherit;
           font-size: 13px; color: var(--fg); background: var(--card);
           border: 1px solid var(--line); border-radius: 4px; }
.field.w-name input, .field.w-name select { min-width: 15ch; }
.field.w-num input { width: 8ch; text-align: right;
                     font-variant-numeric: tabular-nums; }
.field input::placeholder { color: var(--muted); opacity: .7; }

.toolbar .spacer { flex: 1 1 auto; }
.quick { display: flex; align-items: center; gap: 4px; font-size: 12px; }
.quick .lead { color: var(--muted); }
.quick a { padding: 2px 8px; color: var(--muted);
           border: 1px solid var(--line); border-radius: 999px; }
.quick a:hover { background: var(--card-2); text-decoration: none; }
.quick a[aria-current="true"] { color: var(--fg); background: var(--hl);
                                border-color: var(--focus); }

button, .btn { height: 30px; padding: 0 12px; font: inherit; font-size: 13px;
       cursor: pointer; color: var(--fg); background: var(--card-2);
       border: 1px solid var(--line); border-radius: 4px; }
button:hover, .btn:hover { border-color: var(--muted); text-decoration: none; }
button.primary { color: #fff; background: var(--focus); border-color: var(--focus); }
button[disabled] { opacity: .5; cursor: not-allowed; }
td .btn, td button { height: 24px; padding: 0 8px; font-size: 12px; }

/* A write action: the conditions it sends are visible as a command line and as a
   name/value list, so the button and the command cannot disagree. */
.actionbar { display: flex; flex-wrap: wrap; align-items: center;
             gap: var(--s2) var(--s3); margin: 0 0 var(--s3);
             padding: var(--s2) var(--s3); background: var(--card);
             border: 1px solid var(--line); border-radius: var(--r); }
.actionbar .field { flex: 1 1 auto; }
.actionbar details { flex: 1 1 100%; }

/* What the button's own POST answered.  One per form (`[data-status]`), written by
   the delegated submit listener in `_JS` - so two action bars on one page never
   share a line, and an empty one takes no room. */
.status { font-size: 12px; color: var(--muted); }
.status:empty { display: none; }
.status.bad { color: var(--bad-ink); }

/* ---------------------------------------------------------------------------
   5. What is in force: the axes strip, one `key: value` per axis a page reads -
      **including the ones at their default**, which is the whole point (`_axes`).
      The `×` is a rebuilt URL, not a handler; the number beside a value is how
      many rows that axis matched, and `dim` means it matched nearly all of them.
   --------------------------------------------------------------------------- */
.axes { display: flex; flex-wrap: wrap; align-items: baseline;
        gap: 0 var(--s3); margin: 0 0 var(--s2); font-size: 12px; }
.axes .ax { display: inline-flex; align-items: baseline; gap: 5px; padding: 1px 4px;
            border-bottom: 2px solid transparent; }
.axes .ax.set { border-bottom-color: var(--line); }   /* this axis is doing work */
.axes .k { color: var(--muted); }
.axes .v { font-variant-numeric: tabular-nums; }
.axes .v.any { color: var(--muted); }                 /* a default reads grey */
.axes .n { font-size: 11px; color: var(--ok-ink); font-variant-numeric: tabular-nums; }
.axes .n.dim { color: var(--muted); }                 /* matched almost everything */
.axes .x { padding: 0 3px; color: var(--muted); text-decoration: none;
           border-radius: 999px; }
.axes .x:hover { color: var(--bad-ink); background: var(--bad-bg); }

/* The cap's own cost, beside the cap.  Four numbers instead of the 45-word
   sentence that used to sit under four tables: `175 KB / 50 rows`, the API's own
   total, what no cap can show, and what this page's own filter dropped. */
.ofnum, .gap { display: inline-flex; flex-direction: column; line-height: 1.15;
               padding-bottom: 4px; }
.ofnum b, .gap b { font-size: 13px; font-variant-numeric: tabular-nums; }
.ofnum .sub, .gap .sub { font-size: 10.5px; color: var(--muted); }
.gap b { color: var(--warn-ink); }

/* `_rail`: a duplicate *view* of a control that is already a real box.  The box
   carries `name`, the rail does not, so the rail can never submit a second value
   and a page with this script off is exactly the page it was before the rail
   existed - there is no class to gate on, because the script creates the element. */
.field input.has-rail { border-top-right-radius: 0; border-bottom-right-radius: 0; }
.rail { width: 9ch; height: 30px; padding: 0; accent-color: var(--focus);
        background: transparent; border: 1px solid var(--line); border-left: 0;
        border-radius: 0 4px 4px 0; }
.railout { min-width: 4ch; padding-left: 4px; font-size: 12px;
           font-variant-numeric: tabular-nums; }
.railout[data-off="1"] { color: var(--warn-ink); }   /* typed, not a suggestion */
@media (max-width: 700px) { .rail, .railout { display: none; } }   /* box remains */

.chip { display: inline-flex; align-items: center; gap: 4px;
        padding: 1px 3px 1px 8px; font-size: 12px; background: var(--card);
        border: 1px solid var(--line); border-radius: 999px; }
.chip code { padding: 0; background: none; border: 0; }
.chip a { padding: 0 5px; color: var(--muted); border-radius: 999px; }
.chip a:hover { color: var(--bad-ink); background: var(--bad-bg);
                text-decoration: none; }

/* The activity table's group captions (`_runs_table(group=True)`, and the same
   markup in the script's re-render): the kind and its count, drawn as a block inside
   the first cell of each group's first row.  Not a `<tr>` of its own, so the number of
   rows on this page still means the number of activities. */
.kind-group { display: block; font-size: 11.5px; font-weight: 600; color: var(--muted);
              letter-spacing: .02em; }
td.group-first { border-top: 2px solid var(--line); }

/* ---------------------------------------------------------------------------
   6. Banners / query lines / empty states
   --------------------------------------------------------------------------- */
p.query, p.note { margin: 0 0 var(--s3); padding: var(--s1) var(--s3);
        font-size: 12.5px; color: var(--muted); background: var(--card-2);
        border-left: 3px solid var(--line); border-radius: 0 4px 4px 0; }
p.query code { padding: 0; background: none; border: 0; }

.banner { margin: 0 0 var(--s2); padding: var(--s2) var(--s3); font-size: 13px;
          border: 1px solid var(--line); border-radius: var(--r); }
.banner.bad { color: var(--bad-ink); background: var(--bad-bg);
              border-color: var(--bad-bd); }
.banner.busy { color: var(--info-ink); background: var(--info-bg);
               border-color: var(--info-bd); }
.bad { color: var(--bad-ink); }
.busy { color: var(--info-ink); }

.empty { margin: 0 0 var(--s3); padding: var(--s3) var(--s4); font-size: 13px;
         color: var(--muted); background: var(--card);
         border: 1px dashed var(--line); border-radius: var(--r); }
.empty b { color: var(--fg); }

details { margin: var(--s1) 0 0; }
summary { cursor: pointer; font-size: 12px; color: var(--muted); }
details table { margin-top: var(--s2); font-size: 12px; }

/* A clamped number is said out loud and is not an error: a hand-edited URL is a
   normal way of asking.  The class name is part of the page's contract. */
.capped { color: var(--warn-ink); }

/* ---------------------------------------------------------------------------
   7. Tables.  No scroll wrapper on purpose: `overflow-x` would make the wrapper
      the scroll container and the sticky `thead` would stop sticking to the
      page.  Wide columns wrap (`td.wrap`), they do not scroll sideways.
   --------------------------------------------------------------------------- */
table { width: 100%; border-collapse: separate; border-spacing: 0;
        font-size: 13px; background: var(--card);
        border: 1px solid var(--line); border-radius: var(--r); }

thead th { position: sticky; top: var(--head-h); z-index: 10;
        padding: var(--s2); font-size: 11.5px; font-weight: 600;
        color: var(--muted); text-align: left; white-space: nowrap;
        background: var(--card); border-bottom: 1px solid var(--line); }

tbody td { padding: 3px var(--s2); border-bottom: 1px solid var(--line);
        vertical-align: top; white-space: nowrap; max-width: 34ch;
        overflow: hidden; text-overflow: ellipsis; }
tbody tr:nth-child(even) td { background: var(--card-2); }
tbody tr:hover td { background: var(--hl); }   /* after the zebra rule, so it wins */
tbody tr:target td { box-shadow: inset 3px 0 0 var(--focus); }
tbody tr:last-child td { border-bottom: 0; }

td.wrap, th.wrap { min-width: 22ch; max-width: 52ch; white-space: normal;
        overflow: visible; text-overflow: clip; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.act { white-space: nowrap; }
.cell-actions { display: flex; align-items: center; gap: var(--s1); }

/* Column shape, by table name and position: one place decides it, so a caller
   does not have to put a class on every cell.  `td.wrap`/`td.num` are for the
   odd cell that differs from its column. */
table.jobs td:nth-child(1), table.queue td:nth-child(1),
table.pulls td:nth-child(2), table.ledger td:nth-child(1),
table.runs td:nth-child(1) { font-family: var(--mono); }
table.jobs td:nth-child(5), table.queue td:nth-child(2), table.remote-detail td:nth-child(6),
table.card-fields td:nth-child(2), table.pulls td:nth-child(7), table.bytes td:nth-child(2) {
    white-space: normal; overflow: visible; text-overflow: clip; max-width: 52ch; }

/* The merged builds table, and the trap this block exists for: the three tables it
   replaces are gone, so *their* `nth-child` rules would point at the wrong columns -
   `table.local td:nth-child(6)` was that table's correspondence cell and is this
   one's bytes cell, and `table.remote td:nth-child(1)` is the tick box here, not an
   id.  A column is a shape by position, and the positions changed.  Walked against
   the nine cells `_builds` draws:

     1 tick (a box: no shape)        2 build_id (mono, nowrap - a `code` that wraps
     loses the alignment the short ids are read by)   3 tree / branch (wraps)
     4 created (nowrap)              5 card (wraps: `act: node …` is a fragment)
     6 bytes (nowrap: `.artifacts` keeps the artifact set on one line)
     7 act (wraps: hosts, a time and a `failed` pill)
     8 api says (wraps)              9 ran (pills, nowrap)

   The old class names stay on the table as *aliases* (`cls="builds remote local"`,
   because the row probe of the operator's own acceptance script counts this table by
   its class) and an alias carries no shape - which is why `remote`, `local` and
   `pull` are absent from the two rules above: an alias that carried shape would
   fight this block, which is exactly the trap the plan recorded. */
table.builds td:nth-child(2) { font-family: var(--mono); }
table.builds td:nth-child(3), table.builds td:nth-child(5), table.builds td:nth-child(7),
table.builds td:nth-child(8) {
    white-space: normal; overflow: visible; text-overflow: clip; max-width: 52ch; }
table.builds td:nth-child(6), table.builds td:nth-child(9) { white-space: nowrap; }
table.timeline-rows td:nth-child(5) { min-width: 24ch; }
/* A URL is one long word: inside a wrapping cell it has to be allowed to break,
   or `code`'s own `nowrap` would push the table wider than the screen. */
td.wrap code { white-space: normal; overflow-wrap: anywhere; }

/* ---------------------------------------------------------------------------
   8. States and verdicts: pills.  The second class is the word the code already
      uses (pass / running / pulled …), so JavaScript keeps no second vocabulary
      and both themes colour it from the tokens.
   --------------------------------------------------------------------------- */
.pill { display: inline-block; padding: 0 7px; font-size: 11.5px; line-height: 1.6;
        white-space: nowrap; font-variant-numeric: tabular-nums;
        border: 1px solid var(--idle-bd); border-radius: 999px;
        background: var(--idle-bg); color: var(--idle-ink); }

/* verdict pass / run done / evidence pulled / job available */
.pill.pass, .pill.done, .pill.pulled, .pill.available {
        border-color: var(--ok-bd); background: var(--ok-bg); color: var(--ok-ink); }
/* verdict fail / run failed */
.pill.fail, .pill.failed {
        border-color: var(--bad-bd); background: var(--bad-bg); color: var(--bad-ink); }
/* verdict incomplete / evidence unrecorded / job reserved, closing */
.pill.incomplete, .pill.unrecorded, .pill.reserved, .pill.closing {
        border-color: var(--warn-bd); background: var(--warn-bg); color: var(--warn-ink); }
/* verdict error: it must not look like fail, or the two are not told apart */
.pill.error {
        border-color: var(--err-bd); background: var(--err-bg); color: var(--err-ink); }
/* run running / evidence registered */
.pill.running, .pill.registered {
        border-color: var(--info-bd); background: var(--info-bg); color: var(--info-ink); }
/* run cancelled / evidence made-here, empty, bytes / a value with no word of its own.
   `bytes` is the one evidence value that is not a `Local.state`: it is a filter over
   the download tree (`?evidence=bytes`), and it is coloured as a plain fact rather
   than as a verdict - having bytes is neither good nor bad news. */
.pill.cancelled, .pill.made-here, .pill.empty, .pill.none, .pill.idle, .pill.bytes {
        border-color: var(--idle-bd); background: var(--idle-bg); color: var(--idle-ink); }
.pill.empty { border-style: dashed; }
.pill.none { color: var(--muted); background: none; }

/* The artifacts a copy holds, and the ones it does not: one line, no commas. */
.artifacts { display: inline-flex; gap: var(--s2); white-space: nowrap; }
.artifacts .no { color: var(--muted); opacity: .7; }

/* The regression timeline: one block per run, a pass -> fail point ringed.
   Each block is a link now (`_timeline`), because a `<span>` with a `title` is inert
   with JavaScript on *and* off - `这个不能选` was literal.  The link is stripped of its
   underline and takes the surrounding colour, so the strip of squares still reads as
   one chart and not as a row of links; the hover/focus outline is what says it can be
   clicked, and the selected one is marked by `aria-current`. */
.timeline { display: inline-flex; align-items: center; gap: 3px; }
.timeline .point { font-size: 12px; line-height: 1; }
.timeline a.point { text-decoration: none; color: inherit; cursor: pointer; }
.timeline a.point:hover, .timeline a.point:focus { outline: 1px solid var(--focus); }
.timeline a.point[aria-current] { background: var(--hl); border-radius: 2px; }
.timeline .point.regressed { outline: 2px solid currentColor; outline-offset: 1px;
        border-radius: 2px; }

/* The regression chart (`_wave_chart`): one column per position of the page's order,
   three lanes under it.  The verdict colours are the `.pill` ones, so a pass is the
   same green in the chart and in the table - two verdict palettes would be two
   verdicts.  A gap is dashed and empty, the convention `table.bars .bar.gap` already
   uses for a comparison that was not made.  Widths are classes, never inline styles;
   `min-width` keeps 50 slots readable and the wrapper scrolls on a narrow screen
   rather than wrapping, because a wrapped strip stops being an axis. */
.wave-wrap { overflow-x: auto; }
table.wave { border-collapse: collapse; width: 100%; min-width: 640px;
        table-layout: fixed; }
table.wave th { font-size: 11px; font-weight: 600; text-align: right; color: var(--muted);
        padding: 0 6px 0 0; width: 6ch; }
table.wave td { padding: 0; border: 0; text-align: center; font-size: 12px;
        border-bottom: 0; }
table.wave td.num { color: var(--muted); white-space: nowrap; }
table.wave .point { display: block; line-height: 1.35; text-decoration: none;
        color: inherit; }
table.wave .point.pass       { background: var(--ok-bg);   color: var(--ok-ink); }
table.wave .point.fail       { background: var(--bad-bg);  color: var(--bad-ink); }
table.wave .point.incomplete { background: var(--warn-bg); color: var(--warn-ink); }
table.wave .point.error      { background: var(--err-bg);  color: var(--err-ink); }
table.wave .point.gap, table.wave td.empty { border: 1px dashed var(--line);
        background: none; color: var(--muted); }
table.wave .point[aria-current] { outline: 2px solid var(--focus); outline-offset: -2px; }
table.wave .point:hover, table.wave .point:focus { outline: 2px solid var(--focus);
        outline-offset: -2px; }
/* A delta that opens the comparison it names: the number is the door, so it has to
   look pressable without becoming a second colour in a cell full of numbers. */
a.delta-door { text-decoration: none; color: inherit; cursor: pointer; }
a.delta-door:hover, a.delta-door:focus { outline: 1px solid var(--focus); }
a.delta-door.none { color: var(--muted); }

/* ---------------------------------------------------------------------------
   8b. `/analysis`: one list, its sort, its +/-, and its chart.
      The list is a table whose rows are links (`table.picks`), so the two things the
      old select boxes could not do - two lines per row, and a `title` on the full id -
      are possible; and the delta column is a column of *values*, so it wraps instead
      of being clipped by the 34ch rule on `tbody td`.
   --------------------------------------------------------------------------- */
table.picks td, table.delta-list td, table.drift td { white-space: normal;
        overflow: visible; text-overflow: clip; max-width: 60ch; }
table.picks td.num, table.picks td.act, table.picks td.delta { white-space: nowrap; }
table.picks tr.nocfg td { color: var(--muted); }
/* A group break in `sort=same-branch`, drawn as a rule rather than as a caption row:
   the row already names its own tree/branch, so the break is the only thing missing. */
table.picks tr.group td { border-top: 2px solid var(--line); }

/* The delta: `+added` is a green figure and `-removed` a red one, because that is what
   the two mean to a reader comparing two configs; `~changed` is neither.  A refusal is
   muted with a dotted underline - it is a fact about the pair, not an error of ours -
   and the two regression arrows say "more failing" / "fewer" rather than "plus/minus",
   because for failures the sign and the verdict point opposite ways. */
.delta, .delta-list .delta { font-variant-numeric: tabular-nums; }
.delta .plus { color: var(--ok-ink); }
.delta .minus { color: var(--bad-ink); }
.delta .tilde, .delta .zero { color: var(--muted); }
.delta .none, .delta .bad { color: var(--muted); }
.delta .bad { border-bottom: 1px dotted var(--warn-bd); }
.delta-up { color: var(--bad-ink); }
.delta-down { color: var(--ok-ink); }

/* The chart of the list above: one row per comparison, in the same order, so the eye
   can walk down both.  The width is a class (`w0`..`w20`, a 5% step) and never an
   inline style: the quantum is decided once here, the exact number is printed in the
   last cell, and a third colour would be a third class. */
table.bars { width: 100%; font-size: 12px; }
table.bars th { text-align: left; font-weight: 400; font-family: var(--mono);
        white-space: nowrap; }
table.bars td { border-bottom: 0; padding: 2px var(--s2); }
table.bars .bar { display: inline-block; height: 10px; vertical-align: middle;
        background: var(--info-bg); border: 1px solid var(--info-bd); border-radius: 2px; }
table.bars .bar.gap { background: none; border-style: dashed; }
.w0 { width: 0 }     .w1 { width: 5% }    .w2 { width: 10% }   .w3 { width: 15% }
.w4 { width: 20% }   .w5 { width: 25% }   .w6 { width: 30% }   .w7 { width: 35% }
.w8 { width: 40% }   .w9 { width: 45% }   .w10 { width: 50% }  .w11 { width: 55% }
.w12 { width: 60% }  .w13 { width: 65% }  .w14 { width: 70% }  .w15 { width: 75% }
.w16 { width: 80% }  .w17 { width: 85% }  .w18 { width: 90% }  .w19 { width: 95% }
.w20 { width: 100% }

/* The two-line label of a row, the three marks beside it, and the run's own row. */
.marks { display: inline-flex; gap: var(--s2); font-size: 11.5px; color: var(--muted);
        white-space: nowrap; }
.marks .yes { color: var(--ok-ink); }
.marks .no { color: var(--muted); opacity: .8; }
table.runs-list td.wrap, table.record-fields td { white-space: normal;
        overflow: visible; text-overflow: clip; max-width: 60ch; }
table.runs-list tr.selected td { background: var(--hl); }
table.record-fields th { width: 10ch; font-weight: 600; color: var(--muted);
        vertical-align: top; white-space: nowrap; }

/* ---------------------------------------------------------------------------
   9. The log box.  Rendered `hidden` and unhidden by `showLog()`: a page with no
      activity being watched must not sit above an empty grey box.
   --------------------------------------------------------------------------- */
.logbox { margin: var(--s3) 0 0; background: var(--card); overflow: hidden;
          border: 1px solid var(--line); border-radius: var(--r); }
.logbox[hidden] { display: none; }
.logbox .head { display: flex; align-items: center; gap: var(--s2);
          padding: var(--s1) var(--s3); font-size: 12px; color: var(--muted);
          border-bottom: 1px solid var(--line); }
#log { margin: 0; padding: var(--s2) var(--s3); max-height: 28em; overflow: auto;
          font-family: var(--mono); font-size: 12px; line-height: 1.45;
          white-space: pre-wrap; word-break: break-word; background: var(--card-2); }

/* ---------------------------------------------------------------------------
   10. Narrow screens: fields go to one column, the header grows, and --head-h
       grows with it (the sticky thead depends on that number).
   --------------------------------------------------------------------------- */
@media (max-width: 900px) {
  :root { --head-h: 120px; }
  .field { flex: 1 1 44%; }
  .field.w-num { flex: 0 0 auto; }
  .field.w-name input { width: 100%; min-width: 0; }
  .site-head .in { gap: 2px var(--s3); }
  .meta { font-size: 11.5px; }
}

@media (max-width: 600px) {
  :root { --head-h: 168px; }
  .field { flex: 1 1 100%; }
  body { font-size: 13.5px; }
  table { font-size: 12.5px; }
  .actionbar { gap: var(--s1) var(--s2); }
}

/* ---------------------------------------------------------------------------
   11. The live panel: what is running now, and what just ended (`_live_panel`).
       A `<details>`, because opening and closing it has to work with JavaScript
       off and because a `<summary>` is a disclosure a keyboard and a screen
       reader already know.  Two fixed boxes: the summary is the tab that stays
       put, `.live-body` is the part that slides out from the right.

       Nothing between `.live-body` and `<body>` may carry a `transform` or a
       `filter`: that would make `position: fixed` mean "fixed to that ancestor",
       and the tab would slide away with the panel it is supposed to be the
       handle of (`_PAGE` says the same thing on the markup side).

       The tab wears the `running` pill's own two tokens (section 8): "there is a
       live activity" is one fact, so it is one colour, and the spinner beside it
       is the same fact again - which is why neither is a new palette entry.
   --------------------------------------------------------------------------- */
.live > summary { position: fixed; z-index: 30; top: var(--head-h); right: 0;
        display: flex; align-items: center; gap: 6px; list-style: none;
        padding: var(--s1) var(--s3); font-size: 12px;
        color: var(--info-ink); background: var(--info-bg);
        border: 1px solid var(--info-bd); border-right: 0;
        border-radius: var(--r) 0 0 var(--r); cursor: pointer; }
.live > summary::-webkit-details-marker { display: none; }
.live > summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
.live[open] > summary { border-bottom: 0; }

.live-body { position: fixed; z-index: 29; top: var(--head-h); right: 0; bottom: 0;
        width: min(380px, 92vw); display: flex; flex-direction: column;
        background: var(--card); border-left: 1px solid var(--line);
        box-shadow: -8px 0 24px rgba(0, 0, 0, .08); overflow: hidden; }
.live[open] > .live-body { animation: live-in .18s ease-out both; }
@keyframes live-in { from { transform: translateX(100%); } to { transform: none; } }

.live-head { display: flex; align-items: center; gap: var(--s2);
        padding: var(--s2) var(--s3); font-size: 13px;
        border-bottom: 1px solid var(--line); }
.live-head .live-count { margin-left: auto; color: var(--muted);
        font-variant-numeric: tabular-nums; }
.live-list { flex: 1 1 auto; overflow: auto; margin: 0; padding: 0; list-style: none; }
.live-row { padding: var(--s2) var(--s3); border-bottom: 1px solid var(--line); }
.live-row.ended { color: var(--muted); }
.live-line { display: flex; align-items: center; gap: var(--s2); }
.live-id { font-size: 12px; }
.live-time { margin-left: auto; color: var(--muted);
        font-variant-numeric: tabular-nums; font-size: 12px; }
.live-what { margin: 2px 0; font-size: 12.5px; }
.live-argv { display: block; max-width: 100%; font-size: 12px; white-space: nowrap;
        overflow: hidden; text-overflow: ellipsis; }
.live-act { display: flex; align-items: center; gap: var(--s2); margin-top: var(--s1); }
.live-act .btn { height: 22px; padding: 0 6px; font-size: 12px; }
.live-exit { font-size: 12px; }
.live-body .note { margin: var(--s2) var(--s3); }

/* The panel is an overlay, so on a wide screen the page makes room for it rather
   than sitting under it.  Below 1100px it covers content on purpose: the tab
   closes it, and a 380px column beside a twelve-column table helps nobody. */
@media (min-width: 1100px) {
  .live[open] ~ main, .live[open] ~ footer.site {
        padding-right: calc(min(380px, 92vw) + var(--s4)); }
}

/* The header's live chip: the same fact as the panel's tab, one line, always
   visible.  Tokens are the `running` pill's, so the chip and the panel agree
   without a second palette entry. */
.live-chip { display: inline-flex; align-items: center; gap: 6px; padding: 1px 8px;
        font-size: 12px; color: var(--info-ink); background: var(--info-bg);
        border: 1px solid var(--info-bd); border-radius: 999px; }
.live-chip:hover { text-decoration: none; border-color: var(--focus); }
.live-chip.idle { color: var(--muted); background: none; border-color: var(--line); }
.live-chip .live-word { font-variant-numeric: tabular-nums; }
/* Below 900px the header is already two rows deep (section 10 raises `--head-h`
   there), and a chip that pushed it to three would slide the sticky `thead` under
   the header.  The fact is not lost: the panel's own tab is fixed to the same
   corner and prints the same count, and the panel is where the chip points. */
@media (max-width: 900px) { .live-chip { display: none; } }

/* The spinner: a ring in the `running` pill's own two tokens, so "spinning" and
   "running" are one fact rather than two.  It is decoration - the pill and the
   counter carry the meaning - hence `aria-hidden` on the three places it is
   drawn.  Stopping it costs the reader nothing: the number beside it is still
   moving, and with JavaScript off the panel says that the number is a snapshot. */
.spin { display: inline-block; width: 12px; height: 12px; flex: 0 0 auto;
        border: 2px solid var(--info-bd); border-top-color: var(--info-ink);
        border-radius: 999px; animation: spin 1s linear infinite; }
.spin[hidden] { display: none; }
/* The desktop-notice button is rendered `hidden` and unhidden by the script only
   where the browser really has the API.  Spelled out for the same reason
   `.logbox[hidden]` and `.spin[hidden]` are: the `hidden` attribute loses to any
   author rule that gives the element a `display`, whatever its specificity. */
.live-notify[hidden] { display: none; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------------------------------------------------------------------------
   12. The finish notice: what ended while this page was open, announced once
       (`notice` in `_JS`).  NOT inside `.live-body`: that element is transformed
       while it slides in, and a transform makes `position: fixed` mean "fixed to
       the transformed box", so a toast in there would fly in with the panel.
       Empty means absent, so a quiet page carries no box and no gap.
   --------------------------------------------------------------------------- */
#notice { position: fixed; z-index: 31; right: var(--s4); bottom: var(--s4);
        display: flex; flex-direction: column; gap: var(--s2);
        width: min(380px, 92vw); }
#notice:empty { display: none; }
/* The panel and the notice want the same corner.  A sibling combinator and not
   `:has()` (which this stylesheet does not use): `#notice` is a sibling of `.live`
   precisely so the two can be told about each other with no JavaScript at all. */
.live[open] ~ #notice { right: calc(min(380px, 92vw) + var(--s4)); }
.notice { display: flex; align-items: center; gap: var(--s2); margin: 0;
        padding: var(--s2) var(--s3); font-size: 12.5px; line-height: 1.4;
        color: var(--ok-ink); background: var(--ok-bg);
        border: 1px solid var(--ok-bd); border-radius: var(--r);
        box-shadow: 0 4px 16px rgba(0, 0, 0, .10); }
/* Three colours, three truths: an exit code the run really reported (ok/bad by
   its value), a code that was never seen, and an activity that is no longer on
   disk.  The last two are `warn`, never `failed` - `Run._settle` maps a code it
   never learned to `failed`, and a notice may not repeat a claim nobody can
   check (`07-shell.md` §A3). */
.notice.failed { color: var(--bad-ink); background: var(--bad-bg);
        border-color: var(--bad-bd); }
.notice.unknown, .notice.cancelled { color: var(--warn-ink); background: var(--warn-bg);
        border-color: var(--warn-bd); }
.notice .btn { margin-left: auto; height: 22px; padding: 0 6px; font-size: 12px; }
.notice a { margin-left: var(--s1); }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
  /* The spinner is the one thing that has to keep reading as "in progress": the
     global rule above would leave a plain ring that says nothing at all, so
     reduced motion gets a ring with one quadrant picked out instead of a
     frozen circle.  It says "in progress" without moving. */
  .spin { animation: none !important; border-top-color: var(--info-bd);
          border-left-color: var(--info-ink); }
}
"""

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
# The words this script writes (`I18N.loading`, `I18N.log`, `I18N.cancel`, …) are the
# catalogue's, injected as a small object by `_js()`: `_runs_table` and `_live_row`
# read the same ones server-side, so neither the table nor the panel can come back
# in another language than the one it was drawn in.
_JS = """
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
// A filter bar submits itself when a control *commits*, and a keyboard reader browses
// with the arrow keys first.  On a `<select>` and on a number box every arrow press is a
// `change`, so browsing submitted the form, reloaded the page and put the reader back at
// the top of it - the operator's 「有时候按某些键下面的会突然跳到头顶」.  So one-step keys
// set `browsing` for a moment and the submit waits for a committed gesture (Enter,
// Escape, Tab or a click); a mouse click still submits at once, because that is already
// a decision.
var browsing = 0;
document.querySelectorAll('form[data-auto]').forEach(function (f) {
  f.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === 'Escape') { browsing = 0; return; }
    var one = (e.key || '').indexOf('Arrow') === 0 ||
              e.key === 'PageUp' || e.key === 'PageDown' ||
              e.key === 'Home' || e.key === 'End';
    if (one && (e.target.tagName === 'SELECT' || e.target.type === 'range' ||
                e.target.type === 'number')) {
      browsing = Date.now();
    }
  });
  f.addEventListener('change', function (e) {
    if (browsing && Date.now() - browsing < 1200) { return; }
    if (e.target.type !== 'submit' && e.target.type !== 'button') { f.submit(); }
  });
  f.addEventListener('mouseup', function () { browsing = 0; });
  f.addEventListener('blur', function () { browsing = 0; }, true);
});
// An action button is an ordinary `<form method="post" action="/api/actions/<name>">`,
// so a browser's own behaviour would be to navigate to the JSON answer
// (`{started, kind, argv}`, src/GUI.md §4) - the reader asked for a build to be
// registered and got a page of JSON.  That answer is the contract and does not
// change; this listener is what keeps the reader where they were.
//
// Delegated on `document` on purpose: `drawLive` replaces the panel's rows every 2
// seconds, and a listener bound per form would be thrown away with them.  Two POST
// shapes are taken over: `/api/actions/**`, whose answer is the JSON contract, and
// `/api/runs/<id>/cancel`, whose answer is JSON too - a reader who cancelled an
// activity should stay on the page that shows it ending rather than be navigated to
// `{"cancelled": …}`.  The filter bar's GET (which submits itself from the `change`
// listener above, and must navigate) is not touched.
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
                       + 'form[method="post"][action$="/cancel"]')) {
    return;
  }
  e.preventDefault();
  var button = form.querySelector('button');
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
  var body = new URLSearchParams(new FormData(form));
  fetch(form.getAttribute('action'), { method: 'POST', body: body })
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
      var id = (started && started.started) || '?';
      barStatus(form, I18N.started.replace('{id}', id)
        .replace('{argv}', ((started && started.argv) || []).join(' ')), false);
      livePoll();
      // A cancel answers `{"cancelled": …}`, which names no activity that just
      // started: without this guard the box would be filled with "loading ?" and a
      // request for an id called `?`.  The panel is what shows a cancel's effect, and
      // `livePoll` has just redrawn it.
      if (started && started.started && document.getElementById('log')) { showLog(id); }
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
    '<span class="' + esc(r.state) + ' pill">' + esc(r.state) + '</span>' +
    '<code class="live-id">' + id + '</code>' +
    '<span class="live-time num">' + esc(liveTime(r.seconds)) + '</span></div>' +
    // `_live_row` prints What as `[:80]`, so this does too: the two answers to "what
    // is running" must differ in their values only, never in their shape.
    '<div class="live-what">' + esc(String(r.what || '').slice(0, 80)) + '</div>' +
    '<code class="live-argv" title="' + esc(argv) + '">' + esc(argv) + '</code>' +
    '<div class="live-act">' + (ended ? '<span class="live-exit">' + exitText + '</span>' : '') +
    '<a href="/runs/' + encodeURIComponent(r.id) + '/log"' +
    ' onclick="showLog(\\'' + id + '\\');return false">' + esc(I18N.log) + '</a>' +
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
  // code it never saw, and the pill inside already prints the state.
  el.className = ('notice ' + cls).replace(/ +$/, '');
  el.setAttribute('data-key', liveKey(r));
  el.innerHTML = '<span class="' + esc(r.state) + ' pill">' + esc(r.state) + '</span> ' +
    esc(line) + ' <a href="/runs/' + encodeURIComponent(r.id) + '/log">' +
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
    drawLive(live, ended);
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
      try {
        sessionStorage.setItem('kci.place', JSON.stringify(
          {url: location.href, top: window.scrollY || 0, at: Date.now()}));
      } catch (err) {}
      location.reload();
      return;
    }
    if (liveTableAll) { drawTable(runs); }
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
        '</td><td><span class="' + esc(r.state) + ' pill">' + esc(r.state) + '</span></td>' +
        '<td class="num">' + esc(r.age) + '</td><td class="num">' + exitCell + '</td>' +
        '<td class="wrap">' + esc(r.what) + '</td>' +
        '<td class="wrap"><code title="' + esc(argv) + '">' + esc(argv.slice(0, 60)) +
        '</code></td><td class="act"><span class="cell-actions">' +
        '<a href="/runs/' + esc(r.id) + '/log" onclick="showLog(\\'' + esc(r.id) +
        '\\');return false">' + esc(I18N.log) + '</a>' +
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
var logOffset = 0, logId = '', logFresh = false;
// Every click resets, not only a click on a *different* activity.  The box is
// overwritten with the loading word right here, so a re-read that started at the
// offset of the text just thrown away answered "" and the box said "loading ..."
// for ever - which is the operator's "某些日志点不开", and the row it failed on was
// the row he had already looked at (driving the shipped script: click A -> 3451
// chars, click A again -> 32 chars, and nothing else ever arrived).
function showLog(id) {
  logOffset = 0; logId = id; logFresh = true;
  var box = document.getElementById('log');
  var section = box && box.closest('.logbox');
  if (section) { section.hidden = false; }
  // The box is drawn under a 50-row table and nothing used to bring it into view:
  // the link worked and the reader saw no change at all.
  if (section && section.scrollIntoView) { section.scrollIntoView({ block: 'nearest' }); }
  var label = document.getElementById('logid');
  if (label) { label.textContent = id; }
  if (box) { box.textContent = I18N.loading.replace('{id}', id); }
  dashLog();
}
function dashLog() {
  if (!logId) { return; }
  // The id this request is about, carried with it: `logId` may name another activity
  // by the time the answer lands, and a stale answer written into the box mixes two
  // logs and leaves the offset pointing into the wrong file - the 1s chain of a
  // running activity makes that the normal case, not the rare one.
  var asked = logId;
  fetch('/api/runs/' + asked + '/log?offset=' + logOffset).then(function (r) {
    return r.json();
  }).then(function (d) {
    if (asked !== logId) { return; }
    var box = document.getElementById('log');
    if (!box) { return; }
    if (logFresh) { box.textContent = ''; logFresh = false; }
    logOffset = d.offset;
    if (!d.text && d.state !== 'running') { box.textContent = I18N.empty; }
    box.textContent += d.text;
    box.scrollTop = box.scrollHeight;
    if (d.state === 'running') { setTimeout(dashLog, 1000); }
  }).catch(function () {});
}
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
"""


# The catalogue key of every word this script writes -> the name it reads it by.
# Two spellings on purpose: the catalogue's keys are dotted and shared with the page
# (`js.cancel` is looked up server-side by `_runs_table` too), while the script wants
# `I18N.cancel` in the middle of a line of JavaScript.  A missing entry here is a
# word the script reads as `undefined`, so the list is one object and not two.
_JS_WORDS = {"js.loading": "loading", "link.log": "log", "js.cancel": "cancel",
             "js.empty": "empty", "runs.dir_title": "dir_title",
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


def _js(lang: str = DEFAULT_LANG, digest: str = "") -> str:
    """The poll script, with the words it writes in front of it as `I18N`.

    A JSON object rather than string literals, because the words have to be escaped
    for the element they sit in: `ensure_ascii=False` keeps the Chinese readable in a
    page that is UTF-8 anyway, and every `</` is broken up so that no run's own text
    (or a translation) can ever close the `<script>` it lives in.

    Most of them are also read server-side (`_runs_table` for the log link and the
    cancel button, `_live_row` for the panel's cells, `js.loading` for the log box),
    so neither the table nor the panel can come back in another language when the
    poll rewrites it.  The rest are this script's own: the action bar's status line
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
    # row prints the same `title=` on its id cell that `_runs_table` prints
    # (`runs.dir_title` is `{dir}/run.json + run.log`), and a path is not a word to
    # translate.  Without it a refreshed row would lose a tooltip the drawn row has,
    # which is the "the table changes shape when it refreshes" rule this file keeps.
    words["runs"] = layout.runs("")
    blob = json.dumps(words, ensure_ascii=False).replace("</", "<\\/")
    # `LIVE_KEPT` rides with the words: the cap the panel was rendered with and the
    # slice `livePoll` writes back are the same number, and two spellings of it would
    # drift the day one of them changed.
    return (f"var I18N = {blob};\n"
            f"var LIVE_KEPT = {LIVE_KEPT};\n"
            f"var DIGEST = {json.dumps(digest)};\n" + _JS)

# The page: identity, the one live fact, the panel, the numbers, the body.
#
# Three things about this markup are load-bearing and are easy to undo by accident:
#
#  * **`<details id="live">` is a direct child of `<body>`.**  Its `.live-body` is
#    `position: fixed`, and a `transform`/`filter` on any ancestor re-anchors a fixed
#    element to that ancestor: the panel would slide with the page and the tab would
#    slide away with the panel it is the handle of.  Nothing may be inserted between
#    it and `<body>`, and no wrapper may gain a transform.
#  * **`#notice` is a sibling of the panel**, not a child of `.live-body` - for the
#    same reason (`.live-body` animates with `transform`), and because a closed
#    `<details>` renders nothing but its summary, so a notice inside it would be
#    invisible exactly when nothing is running.  `role="status"` +
#    `aria-live="polite"` is the whole screen-reader story; the panel itself is *not*
#    a live region, because it is rewritten every 2s.
#  * **`data-drawn` is on `<body>`** and is the moment this answer was drawn.  The
#    notice compares a run's own `ended` against it, so a page reloaded an hour later
#    cannot re-announce an hour-old finish (`_live_panel`, `run_rows`).
_PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kernelci-riscv {title}</title>
<style>{css}</style></head><body data-drawn="{drawn}">
<header class="site-head"><div class="in">
<h1>kernelci-riscv &mdash; <span class="sub">{title}</span></h1>
<nav class="pages">{nav}</nav>
{live_chip}
<p class="lang">{langs}</p>
</div></header>
{live}
<p class="meta">{meta}</p>
<main>
{banners}
{body}
</main>
{logbox}
<footer class="site"><a href="/summary.json">summary.json</a>
   &mdash; {tagline}</footer>
<div id="notice" role="status" aria-live="polite"></div>
<script>{js}</script>
</body></html>
"""

# What each state of the record means (see src/GUI.md §1.4), as the catalogue key
# that holds the sentence.  The six sentences moved into `lib/i18n.py` with every
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


def _registered_cell(one: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """Where this copy is known from: a card, the pull record's own node id, or nothing.

    "No card in the local table" was the answer for a copy that had been pulled and
    run by `runday` - 30.4 MiB on disk and two entries in `provenance.json` - and the
    cell said the table had never heard of it *while the record it was reading carried
    the `node_id` the cell wanted* (`03-structure.md` §A3).  The old cell asked one
    question, "is there a card", and returned before looking at anything else:
    `not one["in_table"]` came first, so the record's node id was unreachable.

    A copy with no card is still a copy somebody knows something about, and the cell
    now says which of the two facts spoke.  When neither did, it is a `-` and not a
    sentence about a table: the row's *shape* is the diagnosis.
    """
    if one["in_table"] and one["node_id"]:
        return t(lang, "state.node", node=_short(one["node_id"]))
    if one["in_table"]:
        return t(lang, "state.no_node_id_made_here")
    if one.get("act_node_id"):
        return t(lang, "state.node_from_act", node=_short(one["act_node_id"]))
    return "-"


def _tree_branch(one: Mapping[str, Any]) -> str:
    """A row's tree and branch, or `-`: a copy the API never named has neither."""
    return " / ".join(one for one in (str(one.get("tree") or ""),
                                      str(one.get("branch") or "")) if one) or "-"


def _created_cell(one: Mapping[str, Any], lang: str = DEFAULT_LANG) -> str:
    """When this row's build was created - or when it was pulled, and it says so.

    A card-less copy has no `created`; the newest fact about it is the timestamp of its
    pull record, and that is what the column shows because it is also what the rows are
    ordered by (a copy with no date sorted to the bottom of every page).  The `title=`
    is the one word that has to be said about it, and a tooltip is where a word about a
    number belongs.
    """
    said = str(one.get("created") or "")
    if not said:
        return "-"
    if one.get("created_from_act"):
        return (f'<span title="{html.escape(t(lang, "created.from_act"))}">'
                f'{html.escape(said[:16])}</span>')
    return html.escape(said[:16])


def _bytes_cell(one: Mapping[str, Any]) -> str:
    """What is on disk here - the artifacts and their size, never what a record claims.

    The set and the size come from `Local.present`/`Local.size()`, which are
    `os.path.isfile` and `os.path.getsize`; the act beside it is the record.  Keeping
    the two apart is the point of the row: one build's newest act named a single
    artifact while three were whole on disk (`03-structure.md` §A3.1), and a page that
    printed the record as the bytes told the reader the copy was smaller than it was.
    """
    if not one["present"]:
        return "-"
    return ('<span class="artifacts">'
            + "".join(f"<span>{html.escape(name)} \u2713</span>" for name in one["present"])
            + (f"<span>{_human(int(one['size']))}</span>" if one["size"] else "")
            + "</span>")


def _act_cell(one: Mapping[str, Any], lang: str = DEFAULT_LANG) -> str:
    """The pull record, short: how many acts, from where, when, and whether one failed.

    The whole record is a click away on `/local/<id>` (`_acts_table`), so this cell
    carries the four facts a row can: a count, the hosts, the newest time, and
    `failed` - which is a verdict about *that attempt* and not a state of the copy,
    because the bytes may be perfectly whole.  The full sentence `Local.state_text`
    builds is this cell's `title=`, which is where a definition belongs
    (`05-i18n-prose.md` §B.1).
    """
    if not one["acts"]:
        return "-"
    parts = [f'<span>{html.escape(t(lang, "counts.act_n", n=one["acts"]))}</span>']
    if one["act_hosts"]:
        parts.append(f'<span>{html.escape(", ".join(one["act_hosts"]))}</span>')
    if one["act_at"]:
        parts.append(f'<span>{html.escape(str(one["act_at"])[:16])}</span>')
    if one["act_error"]:
        # The verdict **and** the sentence that says what to do about it.  A failed pull
        # is the one state on this page whose next step is not obvious from the row, and
        # the operator's ask this round was 「失败了也不要就是重新到 pull 再搞一次筛选」 - so the
        # row carries the retry's own words, and the number is the bytes that *are* there
        # (`Local.present`, read from disk) rather than the act's own count.
        here = one.get("here_n", 0)
        parts.append(_pill("failed", "run", t(lang, "run_state.label.failed")))
        parts.append('<span class="sub">'
                     + html.escape(t(lang, "pull.row_failed", n=here,
                                      s=_plural(here, lang))) + "</span>")
    return (f'<span class="acts" title="{html.escape(str(one["state_text"]))}">'
            + " ".join(parts) + "</span>")


def _ran_cell(one: Mapping[str, Any]) -> str:
    """The ledger's verdicts for this build id, one pill per test, or `-`.

    The renderer computes no verdict (`00-BRIEF.md` §2): `Records.last(test, id)` is
    the ledger's own answer, and a `-` means the ledger has no record for that pair -
    which is exactly what the gap counts.  A row with no card still gets its verdicts,
    because the ledger is keyed by build id and does not care what the table says.
    """
    parts = [f'{html.escape(test)} {_pill(one["verdicts"].get(test, ""), "verdict")}'
             for test in DEFAULT_TESTS if one["verdicts"].get(test)]
    return " ".join(parts) if parts else "-"


def _badge(text: str, title: str = "") -> str:
    """One short fact, with its explanation in the tooltip - the shape this page uses
    where it used to print a sentence (`05-i18n-prose.md` §B.2)."""
    attr = f' title="{html.escape(title)}"' if title else ""
    return f'<span class="badge"{attr}>{text}</span>'


def _number_chip(label: str, value: str, href: str = "", title: str = "") -> str:
    """One number with the noun that belongs to it: a chip, and a link when it has rows.

    The label and the number are separate elements on purpose: the noun is not
    pluralised from the number by any rule this catalogue has, so `cards 27` reads
    correctly at every count, and a chip that is a link is the *same* chip - a count
    and the page it counts cannot drift when pressing the count is how you see them.
    """
    attr = f' title="{html.escape(title)}"' if title else ""
    inner = f'<span class="k">{html.escape(label)}</span><b class="n">{html.escape(value)}</b>'
    if href:
        return f'<a class="chip"{attr} href="{html.escape(href)}">{inner}</a>'
    return f'<span class="chip"{attr}>{inner}</span>'


def _number_row(chips: Iterable[str]) -> str:
    """A row of numbers: the strip in the header, and the ledger's own four numbers."""
    found = [one for one in chips if one]
    return f'<p class="numbers">{"".join(found)}</p>' if found else ""


def _job_tick(build_id: str) -> str:
    """The tick box of one build on `/jobs`, owned by that page's one `run` bar.

    `form="run-now"` and not a box inside the bar: the bar is one element and the rows
    are many, and a form cannot wrap a table without putting its own button in the
    middle of it.  The box is drawn on the first row of each build, because the bar
    carries one test - a box per (build, test) row would offer three ticks for one
    command, and `_first()` would silently decide which of the three test values
    counted.
    """
    return (f'<input type="checkbox" form="run-now" name="selected" '
            f'value="{html.escape(build_id)}">')


def _other_test_tick(one: Mapping[str, Any], check: "Filter",
                     lang: str = DEFAULT_LANG) -> str:
    """Why this row has no box, and the one click that gives it one.

    A row whose test is not the test in force is covered by its build's own box when no
    test is chosen at all (the command then runs all three tests), and by nothing when
    the page has chosen another one - so the cell says which, in words, and the words are
    a link to the same page with `test=` set to this row's test.  A dash here was the
    operator's 「test 有些好像有但是不能勾选跑不了」: true of the code, and unreadable -
    nothing said why, and nothing said what to do.
    """
    href = _url("/jobs", check, lang=lang, test=str(one["test"]))
    label = t(lang, "jobs.tick_other", test=html.escape(str(one["test"])))
    return (f'<span class="none" title="{html.escape(t(lang, "jobs.tick_other_title", test=str(one["test"])))}">'
            f'<a href="{html.escape(href)}">{label}</a></span>')


def _empty_builds(answer: "Remote", held: Mapping[str, Any],
                  lang: str = DEFAULT_LANG) -> str:
    """Why the merged table is empty - it can be empty for four different reasons.

    "The API did not answer" and "the API answered with nothing" are two facts
    (`_empty_remote`); "this machine holds nothing" and "your filter hid it" are two
    more (`_empty_local`).  One table can be empty for any of the four, so it says
    which.  The filter case carries its number: how much the filter hid is what makes
    it visible that a filter is in force, and a count is not a sentence about one.
    """
    if answer.note and not len(answer):
        return t(lang, "empty.remote_no_answer", note=html.escape(answer.note))
    if held:
        link = (f'<a href="{html.escape(_plain_url("/", lang))}">'
                f'{html.escape(t(lang, "link.clear_filter"))}</a>')
        return t(lang, "empty.filter_hides", n=len(held), link=link)
    return t(lang, "empty.remote_empty", query=html.escape(answer.query))


def _tick_all(form_id: str, count: int, lang: str = DEFAULT_LANG) -> str:
    """The tick column's header: one box that ticks every box this page drew.

    A column of forty unchecked boxes over a bar with one button is the shape the
    operator kept asking to have a shortcut for (「能不能加一个全选功能」), and the
    shortcut has to be honest about its extent: it ticks **this page's** boxes, not
    the rows the filter matched - `table.py pull --build` and `table.py run` take the
    ids a form posts and nothing else, so "select all matching" would need a flag
    that does not exist yet.  The count in the label is that extent, printed.

    Rendered `hidden` and unhidden by the page's script, the same progressive
    enhancement the notify button uses: with JavaScript off a box that ticks nothing
    would be a lie, and the server-side `?tick=` key is the no-JS path.
    """
    return (f'<label hidden><input type="checkbox" data-all-for="{html.escape(form_id)}" hidden '
            f'title="{html.escape(t(lang, "tick.all_title"))}"> '
            f'{html.escape(t(lang, "tick.all", n=str(count)))}</label>')


def _remote_cell(one: dict[str, Any], remote: "Kbuild | None",
                 answer: "Remote | None" = None, lang: str = DEFAULT_LANG) -> str:
    """What the remote column says: this page's answer, or the fact that it has none.

    "Not in the answer" is not "not on the API".  The answer is the newest `limit`
    rows of one query, so a row the cap left out is named as exactly that -
    `outside window (50)`, with the cap as the number - and an API that did not answer
    is named as an API that did not answer, which is a third thing again.  The merged
    builds page must never say "no remote counterpart" about a row the *window* did not
    reach (`03-structure.md` §d.9): the build exists, this query's answer does not
    carry it, and the thing that stopped it is a cap with a number on it.
    """
    if remote is None:
        if answer is not None and answer.note:
            return t(lang, "state.no_answer_remote")
        # A card this machine made has no remote counterpart **by construction**, and
        # saying "outside the window" about it was saying the cap hid something that was
        # never in the question.  `Local.state` is the engine's own verdict, and the row
        # dict already carries it, so this reads a fact instead of guessing one.
        if one.get("state") == "made-here":
            return t(lang, "state.no_remote_counterpart")
        if answer is not None and answer.total is not None and answer.total > len(answer):
            # The cap is a number, and what it means is a tooltip: both numbers on it
            # come from the API's own answer (`total`, `limit`), not from this renderer.
            why = t(lang, "state.outside_window_title",
                    total=answer.total, limit=answer.limit)
            return (f'<span title="{html.escape(why)}">'
                    + t(lang, "state.outside_window", limit=answer.limit) + "</span>")
        return t(lang, "state.no_remote_counterpart")
    said = t(lang, "state.remote_cell", state=remote.state or "?", result=remote.result or "?",
             node=_short(remote.node_id))
    record_node = str(one.get("node_id") or "")
    if record_node and remote.node_id and record_node != remote.node_id:
        return t(lang, "state.remote_cell_mismatch", said=said, node=_short(record_node))
    return said


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
    """
    seeds = TREES_KNOWN if kind == "tree" else BRANCH_SEEDS
    if kind != "tree":
        # A tree's branches come from that tree's own config entry.  The six seeds are
        # the fallback for a checkout without `config/trees/`, not the set: offering
        # `net-next`'s branch names beside `tree=riscv` is not an incomplete list, it
        # is a wrong one (`02-filters.md` §A4).
        seeds = _branches_from_config(_field_of(check, "tree")) or BRANCH_SEEDS
    seen = _seen_names(kind, rows, table) | {_field_of(check, kind)}
    found = [one for one in seeds if _token(one)]
    found += sorted(one for one in seen if one and _token(one) and one not in found)
    return found


def _url(route: str, check: "Filter | None", *drop: str,
         carry: Iterable[str] | None = None, keep: Iterable[tuple[str, str]] = (),
         lang: str = "", spell_lang: bool = False, **over: str) -> str:
    """One GET URL for a route: this filter, minus the defaults, plus the overrides.

    Every link a page writes goes through here - navigation, a chip's ×, a preset -
    so "the URL is the state" keeps holding after someone adds a filter key.  A
    positional name drops that key, a keyword sets it (an empty value drops it),
    and only what the route reads rides along: a link that carried the jobs page's
    verdict to `/runs` would put a condition there that nothing reads.

    `carry` narrows that further.  Left out, a link keeps everything the target
    reads, which is what a link on the target's own page wants - a chip's × has
    to drop one condition and leave the others alone.  The navigation bar passes
    `NAV_KEYS[route]` instead: whoever moves to another page wants the window,
    not the verdict they typed on this one.

    `keep` adds pairs that are page state rather than filter conditions (the
    worker's mode, the pull page's ticks), which `to_query()` leaves out.

    `lang` rides at the end of the query and only when it is not the default: a
    link that spelled `lang=en` out would make today's English URLs (and every
    check that compares them) differ for no reader's benefit, while a reader
    reading Chinese must keep reading Chinese when they click.

    `api` rides on every link the same way, and it is the one key the route
    whitelist does not get to veto.  It is not a condition of one page - it is the
    identity of the stack the whole console is pointed at, and every page either
    reads it or hands it on (`/runs`).  A link that dropped it would move the reader
    to another API with nothing said, which is exactly the confusion this key
    exists to end; `/local/<build_id>` is the case that proves it, since it is not
    in `ROUTE_KEYS` at all and reads the API for the build's remote counterpart.
    """
    pairs = dict(check.to_query()) if check is not None else {}
    if check is not None and check.api:
        pairs["api"] = check.api
    for key, value in keep:
        if value:
            pairs[str(key)] = str(value)
    for key in drop:
        pairs.pop(key, None)
    for key, value in over.items():
        if value:
            pairs[key] = str(value)
        else:
            pairs.pop(key, None)                 # an empty override is a removal
    if lang and (spell_lang or lang != DEFAULT_LANG):
        # `spell_lang` is for the one link whose whole job is to *change* the language
        # (`_lang_links`): `?lang=en` is the default, so it was dropped, and the
        # `kci_lang=zh` cookie the previous click set won the negotiation instead -
        # the English link on a Chinese page answered in Chinese (`accept.py`'s N3).
        # A reader switching languages is stating a preference, and a preference that
        # is the default still has to be spelled or the cookie outvotes it.
        pairs["lang"] = lang
    # The route's own key list, by **longest prefix**: `/analysis/<id>` is the same
    # page's keys (`/analysis/`) plus the build id in the path, and `/local/<id>` reads
    # the api key even though it is not a station.  An exact-match lookup made a detail
    # route's whitelist empty, so a link into one comparison silently dropped the order
    # and the comparison cap it was made under - and a comparison read out of the context
    # it was made in is a different comparison.
    wanted = set(ROUTE_KEYS.get(route, ()))
    for name, allowed in ROUTE_KEYS.items():
        if name.endswith("/") and route.startswith(name):
            wanted |= set(allowed)
    if carry is not None:
        wanted &= set(carry)
    # An override the caller wrote by hand is that caller's decision and is never
    # filtered out; what `wanted` filters is what rides along from the filter.
    # `api` is in here for the same reason it is put into `pairs` above: the route
    # whitelist does not get to drop the stack the reader is looking at.
    given = set(over) | {"lang", "api"}
    ordered = [key for key in FILTER_ORDER if key in pairs]
    ordered += [key for key in pairs if key not in FILTER_ORDER]
    query = urllib.parse.urlencode([(key, pairs[key]) for key in ordered
                                    if key in given or key in wanted])
    return f"{route}?{query}" if query else route


def _plain_url(route: str, lang: str = DEFAULT_LANG) -> str:
    """A route with no conditions on it, in this language: the "start over" link.

    Which is what "clear the filter" means - a link that carried the conditions
    along would leave the reader looking at the same filtered table.
    """
    return _url(route, Filter(), lang=lang)


def _link(route: str, check: "Filter | None", carry: Iterable[str], text: str,
          lang: str = DEFAULT_LANG) -> str:
    """One page-to-page link: the target route, the conditions it wants, this language."""
    return (f'<a href="{html.escape(_url(route, check, carry=carry, lang=lang))}">'
            f"{html.escape(text)}</a>")


def _hidden(name: str, value: str) -> str:
    """A hidden `name=value`, or nothing at all when the value is empty.

    For the state a form has to carry to another route without showing a control:
    the reader's language, and the API this page is reading.  An empty value is left
    out, because an empty key in a URL means "the default" and a field that spelled
    it out would say something the reader never chose.
    """
    return (f'<input type="hidden" name="{html.escape(name)}" '
            f'value="{html.escape(value)}">' if value else "")


def _lang_field(lang: str = DEFAULT_LANG) -> str:
    """The hidden `lang` for a form that leaves this page (the /local tick boxes).

    Not a filter condition, so it is not in `ROUTE_KEYS`; it is the reader's
    language, and the page they land on has to keep it.
    """
    return _hidden("lang", "" if lang == DEFAULT_LANG else lang)


def _route_of(name: str, route: str = "") -> str:
    """The path a page is served at: its own route, else its name's.

    `/local/<build_id>` is the one page that is not in `PAGES`, so it hands its path
    in (`_shell`'s `route`); everything else is looked up by the name that picks its
    navigation word.
    """
    return route or {title: path for path, title in PAGES}.get(name, "/")


def _lang_links(check: "Filter | None", current: str, lang: str,
                route: str = "", keep: Iterable[tuple[str, str]] = ()) -> str:
    """The header's language slot: one link per language, the current one marked.

    Each link is a URL, so it carries what this page reads - including the keys
    that are not filter fields (`/runs`'s kind and state, the worker's mode), which
    is what `keep` is for.  `route` overrides the path for the one page that is not
    in `PAGES` (`/local/<id>`), whose build id would otherwise be lost on a switch.

    Every href spells its own language out (`spell_lang=True`), the default one
    included.  Leaving the default out is what made this slot dead in one direction:
    the click into Chinese set `kci_lang=zh`, the English href then carried no
    `?lang=`, and `pick_lang` preferred the cookie - so `English` on a Chinese page
    answered in Chinese and the reader had no way back but to clear the cookie
    (`accept.py`'s N3).
    """
    here = _route_of(current, route)
    parts = []
    for one in LANGS:
        text = t(lang, f"lang.{one}")
        attrs = f'hreflang="{html.escape(one)}" lang="{html.escape(one)}"'
        if one == lang:
            attrs += ' aria-current="true"'
        href = _url(here, check, keep=keep, lang=one, spell_lang=True)
        parts.append(f'<a href="{html.escape(href)}" {attrs}>{html.escape(text)}</a>')
    return "".join(parts)


def _refresh(route: str, check: "Filter | None", keep: Iterable[tuple[str, str]] = (),
             lang: str = DEFAULT_LANG) -> str:
    """The one control that re-reads this page, and the age of what it last read.

    A link and not a button: every page here is a GET whose URL *is* its state, so
    "ask again" is the same URL with `fresh=1` in it - which is the one thing that
    turns the API cache off for that read (`_ttl_of`).  `keep` carries the page's
    own keys through it exactly as the language links do, so a refresh of `/worker`
    is a refresh of the worker page's question and not of a default one.

    The age beside it is not decoration.  An answer served from the cache and shown
    without its age is a page pretending it just asked, which is the one thing a
    cache here may not do (`docs/gui-rework/01-perf.md` §D2) - so the number is
    printed, and `?ttl=` is named in the `title=` for a reader who wants to know how
    long "cached" means.
    """
    age = api_mod.read_age()
    when = (t(lang, "refresh.now") if age is None or age < 1
            else t(lang, "refresh.age", age=_ago(age)))
    return (f'<a class="btn" href="'
            f'{html.escape(_url(route, check, keep=keep, lang=lang, fresh="1"))}" '
            f'title="{html.escape(t(lang, "refresh.title", ttl=_ago(api_mod.request_ttl())))}">'
            f'{html.escape(t(lang, "btn.refresh"))}</a> '
            f'<span class="pill idle">{html.escape(when)}</span>')


def _axes(check: "Filter", route: str, lang: str = DEFAULT_LANG,
          counts: "Mapping[str, int] | None" = None,
          keep: Iterable[tuple[str, str]] = ()) -> str:
    """Every axis that shapes this answer, default values included, as `key: value`.

    Built from the **effective** values and never from `check.to_query()`.  A query
    elides its defaults, and an axis whose value *is* the default is exactly the one a
    reader cannot otherwise see.  `?api=production` in a process started on production
    is that case in full: `api` is empty by design (`Apis.key`), so a strip built from
    what the URL carries printed nothing, and the page rendered **byte-identically** to
    one with no `api` key at all while an operator watched `local` show up and
    `production` not (`docs/gui-rework/02-filters.md` §A5, the F3 fix).  Start the
    server on `local` and the symptom mirrors, which is why this is structural: the
    axis is printed because the *route reads it*, not because it is set.

    The value is always printed; the `×` appears only when dropping the key would
    change the answer, so the link is never a no-op.  `counts` is how many rows each
    axis in force matched (`Gui._axis_counts`); the number is inked when the axis
    removed rows and greyed when it removed fewer than a tenth of them, because
    `arch=riscv` matching 1771 of 1782 is a fact a reader has to be able to see
    without being told a sentence about it (`05-i18n-prose.md` §B.2's badge).

    No sentence anywhere: `any` and `all` are the words for "this axis is not
    filtering", and both already exist in the catalogue.
    """
    any_word = t(lang, "state.any")
    keys = set(ROUTE_KEYS.get(route, ()))
    # (key, label, value, droppable, is_default).  Two separate facts on purpose: an
    # axis can be **stated and still be the default** - `?api=production` on a process
    # started on production is exactly that - and the `set` class (this axis is doing
    # work) is not the same question as the `×` (dropping this key changes the answer).
    rows: list[tuple[str, str, str, bool, bool]] = []
    if "api" in keys:
        # The *base*, not the key: the address this page really reads.  `check.api` is
        # empty whenever the page is on the base it started on, which is exactly the
        # value a reader could not see.  `api_given` is what the URL said, so a page
        # that was *told* `api=production` is not the same page as one that was told
        # nothing - even when both resolve to the same address, which is how `local`
        # came to show a chip and `production` came to show none (F3).
        stated = bool(check.api or check.api_given)
        rows.append(("api", t(lang, "filter.api"),
                     check.api_base or check.api or any_word, stated, not stated))
    for name in ("tree", "branch", "arch", "defconfig", "compiler"):
        if name in keys:
            value = str(getattr(check, name, "") or "")
            rows.append((name, t(lang, "word." + name), value or any_word,
                         bool(value), not value))
    if "state" in keys:
        rows.append(("state", t(lang, "word.state"), check.state or any_word,
                     bool(check.state), not check.state))
    if "result" in keys:
        rows.append(("result", t(lang, "word.result"), check.result or any_word,
                     bool(check.result), not check.result))
    if "days" in keys:
        rows.append(("days", t(lang, "filter.window"),
                     t(lang, "filter.day_all") if check.days == NO_WINDOW
                     else str(check.days), check.days != NO_WINDOW,
                     check.days == NO_WINDOW))
    if "limit" in keys:
        rows.append(("limit", t(lang, "filter.rows"), str(check.limit), check.limit != 50,
                     check.limit == 50))
    if "sort" in keys:
        # Printed **always**, like `api`, `days` and `limit`, and for the same reason:
        # the order is in force whether or not the URL spells it, it is what the rows'
        # adjacent deltas are computed against, and a default is exactly the value a
        # reader cannot otherwise see.  The `×` appears only when dropping the key
        # changes the answer, so an unstated sort has no control to drop.
        rows.append(("sort", t(lang, "filter.sort"),
                     _sort_label(_sort_keys(check.sort), lang), bool(check.sort),
                     not check.sort))
    # The rest of the `Filter` keys this route reads: the page's own row filters.  They
    # are printed **when they are in force** and not when they are at their default, and
    # that is the one asymmetry in this strip, on purpose.  An axis that shapes the API
    # read is printed always (the F3 rule above: a default is the value a reader cannot
    # otherwise see); an axis that only filters the rows already read is noise at its
    # default and a lost condition when it is set - the chips this strip replaced did
    # show `?evidence=bytes`, and a reader must not lose a condition by gaining a
    # strip.  `test`,`ran`,`verdict`,`evidence`,`origin`,`missing`,`has`,`text`,`job`.
    for name in ("test", "ran", "verdict", "evidence", "origin", "missing", "has", "text",
                 "job"):
        if name not in keys:
            continue
        raw = getattr(check, name, "")
        value = ",".join(str(one) for one in raw) if isinstance(raw, (tuple, list)) \
            else str(raw or "")
        if not value or value == "any":
            continue
        label = (t(lang, AXIS_LABELS[name]) if name in AXIS_LABELS else name)
        rows.append((name, label, value, True, False))
    # The page's own keys that are not `Filter` fields are axes in force too: what
    # kind of activity `/runs` is showing, which state, and the worker's mode,
    # platform and runtime.  They are printed with the value the page is using and no
    # `×` - the select box beside them is how they are changed, and doubling that as a
    # link would be a second control for one condition (`_action_bar`'s rule).
    for name, value in keep:
        if value:
            label = t(lang, AXIS_LABELS.get(name, name)) if AXIS_LABELS.get(name) else name
            rows.append((str(name), label, str(value), False, False))
    out = []
    for key, label, value, droppable, default in rows:
        if not value:
            continue
        drop = ""
        if droppable:
            drop = (f'<a class="x" href="{html.escape(_url(route, check, key, lang=lang))}" '
                    f'title="{html.escape(t(lang, "filter.drop_condition"))}" '
                    f'aria-label="{html.escape(label)}">&times;</a>')
        found, badge = (counts or {}).get(key), ""
        if found is not None:
            total = max(1, int((counts or {}).get("_total", found)))
            dim = " dim" if found * 10 >= total * 9 else ""
            badge = (f'<span class="n{dim}" title="'
                     f'{html.escape(t(lang, "filter.axis_count", n=found, total=total))}">'
                     f'{found}</span>')
        out.append(f'<span class="ax{" set" if not default else ""}" '
                   f'data-axis="{html.escape(key)}">'
                   f'<span class="k">{html.escape(label)}</span>'
                   f'<span class="v{"" if not default else " any"}">'
                   f'{html.escape(value)}</span>{badge}{drop}</span>')
    return f'<p class="axes">{"".join(out)}</p>' if out else ""


def _datalist(list_id: str, values: Iterable[str],
              labels: Mapping[str, str] | None = None) -> str:
    """The candidate list for an open text field (a tree, a branch, an API).

    A `<datalist>` suggests without constraining: the API takes any name, and a
    tree that appeared after this page was written must still be typeable.  The
    value is checked on the server (`_named`) whatever the list offered.

    `labels` is optional text for a candidate - the API box offers `local` and
    `http://127.0.0.1:8001`, and each one is shown under the other's name, so a
    reader who does not know the shorthand can see what it stands for.  The value is
    what a browser submits either way; only the text beside it changes.
    """
    labels = labels or {}
    return (f'<datalist id="{html.escape(list_id)}">'
            + "".join(f'<option value="{html.escape(str(one))}">'
                      f'{html.escape(str(labels.get(one, "")))}</option>' for one in values)
            + "</datalist>")


def _stops_attr(stops: Iterable[str]) -> str:
    """The suggestion set as a `data-stops` attribute, or `""` when there is none.

    Data, not markup: with the script off nothing reads it, and the field is the plain
    box it has always been.  It is packed as JSON because that is what the script can
    read back with `JSON.parse`, and escaped for an attribute because a tree or a
    defconfig name may contain a quote (`x86_64_defconfig+allnoconfig`).
    """
    packed = [str(one) for one in stops]
    if not packed:
        return ""
    return f' data-stops="{html.escape(json.dumps(packed), quote=True)}"'


def _name_field(name: str, value: str, label: str, list_id: str,
                lang: str = DEFAULT_LANG, placeholder: str = "",
                stops: Iterable[str] = (), note: str = "") -> str:
    """A text field with a candidate list: a name nothing can enumerate.

    `placeholder` is what an empty box means.  `(any)` is right for a name that
    filters nothing, and wrong for a box whose empty value is a real address: there
    the placeholder says *which* base empty stands for.

    `stops` is the suggestion set the page's script builds a rail from (`_rail`), and
    `note` is a small number the label carries beside itself - how many stops the set
    has, which is the one fact a reader needs to know the rail is worth using.  Both
    are optional and both degrade to nothing.
    """
    stops = [str(one) for one in stops]
    badge = (f' <span class="n" title="{html.escape(note)}">{len(stops)}</span>'
             if stops and note else "")
    return (f'<div class="field w-name"><label for="f-{html.escape(name)}">'
            f'{html.escape(label)}{badge}</label>'
            f'<input id="f-{html.escape(name)}" name="{html.escape(name)}" '
            f'list="{html.escape(list_id)}" value="{html.escape(value)}" '
            f'placeholder="{html.escape(placeholder or t(lang, "state.any_paren"))}" '
            f'autocomplete="off"{_stops_attr(stops)}></div>')


def _num(name: str, value: str, label: str, low: int, high: int,
         list_id: str = "", stops: Iterable[str] = ()) -> str:
    """A number field: free to type, bounded in the box, clamped on the server.

    `min`/`max` let the browser refuse an absurd number in the reader's own
    language, which is free.  The server clamps anyway (`Filter.from_query`),
    because a URL is hand-editable and a typo deserves a note, not a 500.

    `stops` is the suggestion set, handed to the page's script in `data-stops` so it
    can build the rail.  It is *data*, not markup: with the script off nothing reads
    it, and the field is the plain number box it has always been.  `days` and `rows`
    are the two that need it most: the operator asked for "有一些可以滑下来的选项"
    instead of a row of ten buttons, and `rows` is also the page's latency lever, so
    its stops are its six costs (`_coverage`).
    """
    return (f'<div class="field w-num"><label for="f-{html.escape(name)}">'
            f'{html.escape(label)}</label>'
            f'<input id="f-{html.escape(name)}" name="{html.escape(name)}" type="number" '
            f'min="{int(low)}" max="{int(high)}" step="1" value="{html.escape(str(value))}"'
            + (f' list="{html.escape(list_id)}"' if list_id else "")
            + _stops_attr(stops) + "></div>")


# 3.5 KB a row, measured: 175 082 bytes for the 50 rows `/remote` keeps
# (`docs/gui-rework/01-perf.md` §D1c).  It is the cap's own cost, so the cap's own
# readout quotes it: the operator asked for a `rows` he can type, and a control that
# does not say what a row costs is a control he cannot price - 1000 rows is 3.5 MB
# over a 20-35 KB/s link, not "more of the same".
ROW_BYTES = 3502


def _coverage(rows: "Remote", check: "Filter", lang: str = DEFAULT_LANG) -> str:
    """What the cap costs and what it hides, as four numbers.

    `rows.total` is the API's own count for this query - quoted, never counted from
    what came back, because what came back is what the cap allowed.  `outside` is the
    part of it no cap can show, `filtered here` is the part this page's own row filter
    dropped after the cap, and the bytes are `3.5 KB x cap`.  Four facts that used to
    be one 45-word sentence under four tables (`filter.rows_note`), which the operator
    read as `这个网页用起来很卡` and `不要这种垃圾文字注释` at once.
    """
    if rows.note:
        return (f'<span class="ofnum" title="{html.escape(rows.note)}"><b>&ndash;</b>'
                f'<span class="sub">{html.escape(t(lang, "filter.no_answer"))}</span></span>')
    if rows.total is None:
        return ""
    kb = ROW_BYTES * max(1, check.limit) // 1024
    cap = (f'<span class="ofnum" title="'
           f'{html.escape(t(lang, "filter.cap_title", bytes=ROW_BYTES, rows=50))}">'
           f'<b>{html.escape(t(lang, "filter.cap_bytes", kb=kb))}</b>'
           f'<span class="sub">{html.escape(t(lang, "filter.cap_rows", n=check.limit))}'
           f'</span></span>')
    total = (f'<span class="ofnum"><b>{rows.total}</b>'
             f'<span class="sub">{html.escape(t(lang, "filter.api_total"))}</span></span>')
    parts = [cap, total]
    if rows.total > check.limit:
        parts.append(f'<span class="gap"><b>{rows.total - check.limit}</b><span class="sub">'
                     f'{html.escape(t(lang, "filter.outside_cap"))}</span></span>')
    here = max(0, min(rows.total, check.limit) - rows.kept)
    if here:
        parts.append(f'<span class="gap"><b>{here}</b><span class="sub">'
                     f'{html.escape(t(lang, "filter.filtered_here"))}</span></span>')
    return "".join(parts)


def _view_presets(route: str, check: "Filter", table: Any, answer: "Remote | None",
                  lang: str = DEFAULT_LANG) -> str:
    """The three sets this list can be, as one pressable number each.

    `origin` is the axis that decides *which* builds a row set is about, and until now
    it was a `<select>` among fourteen other controls - so "the place that holds my
    cards" had no name on the page, and the default view had no way of saying it was
    one of three.  The three numbers are the engine's own (`len(table)`, the API's
    `total`, the union's row count), and each link keeps every other condition, so
    switching the view never changes the filter.

    The middle number is the API's own count and is left out when the API did not
    answer: a window nobody measured has no size, and `-` is the honest word for it.
    """
    links = []
    for value, key, number in (("card", "view.cards", len(table)),
                               ("any", "view.union", _union_size(table, answer)),
                               ("remote", "view.window",
                                answer.total if answer is not None else None)):
        label = t(lang, key, n="-" if number is None else str(number))
        href = _url(route, check, lang=lang, origin=value)
        links.append(f'<a href="{html.escape(href)}"'
                     + (' aria-current="true"' if check.origin == value else "")
                     + f">{html.escape(label)}</a>")
    return '<span class="quick">' + "".join(links) + "</span>"


def _union_size(table: Any, answer: "Remote | None") -> int:
    """How large the union of the API's answer and this disk is - measured, not guessed.

    A card whose build the answer did not carry is a row of the union and of nothing
    else, so the two sets cannot simply be added: the overlap is counted away by id.
    """
    named = {one.build_id for one in answer} if answer is not None else set()
    return len(named) + sum(1 for one in table if one.build_id not in named)


def _quick(name: str, route: str, check: "Filter", current: str,
           choices: Iterable[tuple[str, str]], lead: str = "",
           keep: Iterable[tuple[str, str]] = (), lang: str = DEFAULT_LANG) -> str:
    """The presets beside a field: one click each, and the URL stays the state.

    A datalist is only a suggestion in some browsers (Firefox opens it on the down
    arrow), so the same values are repeated as links.  The one in force is marked,
    which is also how a reader sees the value a free number box is holding.

    `keep` is the page's own state that is not a filter field (the worker's mode
    and claim filters, the analysis page's two builds): a preset that dropped it
    would answer a different question than the page the reader is standing on.
    """
    pairs = dict(keep)
    links = "".join(
        f'<a href="{html.escape(_url(route, check, lang=lang, **{**pairs, name: value}))}"'
        + (' aria-current="true"' if value == current else "")
        + f'>{html.escape(label)}</a>'
        for label, value in choices)
    return (f'<span class="quick"><span class="lead">{html.escape(lead or name)}:</span>'
            f"{links}</span>")


def _pill(value: str, kind: str = "", label: str = "") -> str:
    """A state or a verdict as a small block; the class is the value, always.

    `pass`, `running`, `pulled` are the values the code compares *and* the classes
    the stylesheet colours, so there is one vocabulary rather than two.  The word
    leads the class list because that is what a reader (or a checker) greps the
    page for; `pill` is only how it looks.  `kind` is the fallback class for a
    value the stylesheet has no word for, and `idle` for one nothing named at all:
    an API that grows a new state must not lose its shape.

    `label` is what the pill *says* when the vocabulary has a translation (the
    evidence states above; `_evidence_label`); left out, the pill says the value,
    which is what every word kept in English does.
    """
    word = str(value or "")
    if not word:
        return '<span class="none pill">-</span>'
    known = any(word in words for words in PILL_WORDS.values())
    cls = word if known else (kind or "idle")
    return (f'<span class="{html.escape(cls)} pill">'
            f'{html.escape(label or word)}</span>')


def _h2(title: str, sub: str = "", id: str = "", hint: str = "") -> str:
    """A section heading: the title, and the one-line explanation the page puts beside it.

    The `<span>` is the heading's own sub-line in the stylesheet, and it is a
    sentence like any other - both halves come from the catalogue.  `id` is the
    heading's anchor, which is how the numbers strip's `acts` chip links to the rows it
    counts: a section a number points at has to have something to point at.

    `hint` is a *limitation* the heading used to spell out in that sub-line ("displayed
    and not interpreted", "a text match"): a limitation is a tooltip's job, so it moves
    to the heading's `title=` and the sub-line goes back to being data or being absent.
    """
    attr = f' id="{html.escape(id)}"' if id else ""
    attr += f' title="{html.escape(hint)}"' if hint else ""
    return (f"<h2{attr}>{title} <span>{sub}</span></h2>" if sub
            else f"<h2{attr}>{title}</h2>")


def _cell(text: str, cls: str = "") -> str:
    """One table cell, with its column's class on it (`id` / `wrap` / `num` / `act`)."""
    return f'<td class="{html.escape(cls)}">{text}</td>' if cls else f"<td>{text}</td>"


def _row(cells: Iterable[str], cls: str = "", id: str = "") -> str:
    """One table row out of already-escaped cells; `id` is the row's own anchor.

    A row anchor is what makes `:target` highlight the row a link came back to.
    """
    attrs = (f' id="{html.escape(id)}"' if id else "") + (f' class="{html.escape(cls)}"' if cls else "")
    return f"<tr{attrs}>" + "".join(cells) + "</tr>"


def _table(head: Iterable[str], rows: Iterable[str], empty: str = "", cls: str = "",
           id: str = "", rows_of: str = "", kinds: Iterable[str] = ()) -> str:
    """A table; `empty` is what a page says instead of an empty table.

    `cls` names the table so a stylesheet can size its columns by position
    instead of every caller decorating every cell.  There is no scroll wrapper on
    purpose: `overflow-x` would make that wrapper the scroll container, and the
    sticky `thead` would stop being sticky on the page.

    `rows_of` says whether the rows in this table are **all** the activities or a
    subset of them, and only `"all"` may be re-rendered by the 2 s poll.  It exists
    because `dashPoll` used to rewrite `#runs tbody` from the *unfiltered* `GET
    /api/runs` on every page: a table drawn with a filter (or, on
    `/local/<id>`, drawn from one build's argv) grew back to the fifty rows nobody
    asked for two seconds after the page was read.  A filtered table is the reader's
    question, and a poll that replaces it with another answer is the one thing this
    page may not do (`07-shell.md` §A2).

    `kinds` is the group order the rows were drawn in, and it rides to the script in
    `data-kinds`: the poll re-renders this tbody from JSON, so a table drawn with
    captions has to tell the script which order those captions came in, or the
    refresh would be a different table (`_runs_table(group=True)`).
    """
    rows = list(rows)
    if not rows:
        return f'<p class="empty">{empty}</p>' if empty else ""
    order = ",".join(kinds)
    attrs = ((f' class="{html.escape(cls)}"' if cls else "")
             + (f' id="{html.escape(id)}"' if id else "")
             + (f' data-rows="{html.escape(rows_of)}"' if rows_of else "")
             + (f' data-kinds="{html.escape(order)}"' if order else ""))
    return (f"<table{attrs}><thead><tr>" + "".join(f"<th>{one}</th>" for one in head)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


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


def _action_bar(action: str, fields: "Iterable[tuple[str, str]] | Mapping[str, str]" = (),
                label: str = "", argv: str = "", note: str = "", inner: str = "",
                form_id: str = "", lang: str = DEFAULT_LANG, api: str = "",
                hint: str = "") -> str:
    """One write action: the conditions it will send, as hidden values and as words.

    The hidden inputs have to stay hidden - the body is what `Gui.command()` reads
    - but the same pairs are printed once more, as the command line an operator
    could type (`argv`).  One dict, two readings, so the bar cannot show one thing
    and run another.  The third reading - a `<details>` table of every name and
    value - is gone: the operator read it as noise (「这个按钮发出去什么」), and the
    command line below the button already carries the same body in the form a reader
    can paste into a shell.

    `hint` is a sentence about what this button does, rendered as the form's
    `title=`; readers who need it hover, readers who do not are not told twice.

    `api` is this page's API key, and it is added to the body for the actions whose
    argv carries `--api-url` (`src/GUI.md` §3: `run`, `runday`, `fetch`, `worker`,
    `provision`, `drift`).  It is passed together with `_argv_of(..., api=…)` or not
    at all: the printed line and the posted body then come from one dict, and the
    button cannot run against an API other than the one it promised.  The three
    actions that do not carry the flag get no field for it, so their bodies stay
    exactly what they were.

    `inner` is the action's own control (a tick box per row), never a filter: a
    condition shown twice would submit both values, and `_first()` would silently
    decide which one counted.  `note` is HTML on purpose - the caller escapes the
    values and keeps the sentence it already had.

    Nothing here is a GET, so no `lang` is carried: the action posts to
    `/api/actions/<name>`, which runs a command, and a command line has no
    language (the reader's language is remembered by the `kci_lang` cookie the
    page they came from set).

    `[data-status]` is this form's own line for what its POST answered.  It is per
    form and not one per page: a page holds several action bars, and two of them
    writing into one line would each claim the other's refusal.  The page's script
    takes the POST over (`_JS`) and writes here; with JavaScript off nothing writes
    it and the browser shows the JSON instead (that is the endpoint's contract,
    src/GUI.md §4), so the span is empty and hidden (`:empty`) rather than promising
    something that will not come.
    """
    pairs = ([("api", str(api))] if api else []) + [
        (name, str(value)) for name, value in
        (fields.items() if isinstance(fields, Mapping) else fields)]
    hidden = "".join(f'<input type="hidden" name="{html.escape(name)}" '
                     f'value="{html.escape(value)}">' for name, value in pairs)
    return ('<form class="actionbar" method="post" '
            f'action="/api/actions/{html.escape(action)}"'
            + (f' id="{html.escape(form_id)}"' if form_id else "")
            # `hint` is the sentence the bar used to print beside the button, as a
            # `title=` on the form.  A fact about what a control does is a tooltip's
            # job (`05-i18n-prose.md` §B.1 case 4); the words stay in the catalogue, in
            # both languages, where `--check` can still see them.
            + (f' title="{html.escape(hint)}"' if hint else "") + ">"
            + hidden + inner
            + (f'<button class="primary">{html.escape(label)}</button>' if label else "")
            + '<span class="status" data-status></span>'
            + (f'<code class="argv" title="{html.escape(argv)}">{html.escape(argv)}</code>'
               if argv else "")
            + (f"<span>{note}</span>" if note else "")
            + "</form>")


def _option(value: str, current: str, label: str = "",
            lang: str = DEFAULT_LANG) -> str:
    """One option of a select box, marked when it is the current value.

    `label` is the display text of a *value*; the value itself is what the box
    submits and is never translated.  The empty option means "(any)" wherever
    empty means anything at all.
    """
    chosen = " selected" if value == current else ""
    return (f'<option value="{html.escape(value)}"{chosen}>'
            f'{html.escape(label or value or t(lang, "state.any_paren"))}</option>')


def _select(name: str, options: Iterable[str], current: str, label: str,
            placeholder: bool = True, labels: Mapping[str, str] | None = None,
            lang: str = DEFAULT_LANG) -> str:
    """A select box: every value it offers is one this tree knows.

    A `current` no option carries is *appended* and marked `(current)`, never
    dropped: with nothing selected the browser falls back to the first option, so
    the next `apply` would send a different value than the one in the URL - how
    `?missing=kernel` quietly became "(any)".  A free number is a text box now
    (`_num`), so a value the tree cannot enumerate is the only case left.

    `placeholder` adds the empty option, which means "(any)" where empty means
    anything and nothing at all where the box picks one of two things (`older`
    has no "(any)": an empty id is not a build).  `labels` renames one value's
    text, never the value a command line would carry.
    """
    labels = labels or {}
    found = [str(one) for one in options]
    if placeholder and "" not in found:
        found.insert(0, "")
    kept = str(current)
    rendered = [_option(one, kept, labels.get(one, ""), lang) for one in found]
    if kept not in found:
        rendered.append(_option(kept, kept, t(lang, "state.current_paren", value=kept), lang))
    return (f'<div class="field"><label for="f-{html.escape(name)}">{html.escape(label)}</label>'
            f'<select id="f-{html.escape(name)}" name="{html.escape(name)}">'
            + "".join(rendered) + "</select></div>")


def _form(route: str, controls: Iterable[str], check: "Filter | None" = None,
          rendered: Iterable[str] = (), keep: Iterable[tuple[str, str]] = (),
          lang: str = DEFAULT_LANG) -> str:
    """The page's one GET form: the filter bar, whose result is a URL you can copy.

    It carries, as hidden inputs, every condition the page reads and shows no
    control for - a page that dropped one on `apply` would answer a different
    question than the URL it was handed, and the reader would have no way to see
    that.  `offset` is deliberately not among them: a new condition starts the
    list over.  `keep` adds the page's own keys (the worker's mode, the pull
    page's ticks), which are not filter fields at all.

    Nothing here submits on its own: the `change` listener in `_JS` does that,
    and with JavaScript off the `apply` button is still a button.

    The language is a hidden input of its own (`_lang_field`): an `apply` is a
    GET to the same route, and a reader who applied a filter must not fall back
    into the default language for it.
    """
    allowed = set(ROUTE_KEYS.get(route, ()))
    shown = set(rendered)
    hidden: dict[str, str] = {}
    for key, value in (check.to_query() if check is not None else ()):
        if key in allowed and key not in shown:
            hidden[key] = value
    for key, value in keep:
        if value and key not in shown:
            hidden[key] = str(value)
    return (f'<form class="toolbar" method="get" action="{html.escape(route)}" data-auto="1">'
            + "".join(f'<input type="hidden" name="{html.escape(key)}" '
                      f'value="{html.escape(value)}">' for key, value in hidden.items())
            + _lang_field(lang)
            + "".join(controls) + '<span class="spacer"></span>'
            + f'<button type="submit">{html.escape(t(lang, "btn.apply"))}</button> '
            + f'<a href="{html.escape(_plain_url(route, lang))}">'
              f'{html.escape(t(lang, "btn.clear"))}</a></form>')


def _filter_bar(route: str, controls: Iterable[str], check: "Filter | None" = None,
                rendered: Iterable[str] = (), keep: Iterable[tuple[str, str]] = (),
                notes: Iterable[str] = (), lang: str = DEFAULT_LANG,
                counts: "Mapping[str, int] | None" = None) -> str:
    """A page's one GET form, with what is in force above it and what it means below.

    Kept together so the three parts cannot drift apart page by page, and so a
    reader always finds the conditions, the controls and the explanation in the
    same place.

    `counts` is what each axis in force matched (`Gui._axis_counts`), handed straight
    to `_axes`: the strip is where a filter that removed nothing becomes visible as a
    greyed number instead of reading like a filter that worked.  A caller that has no
    number passes none, and the strip then claims none - it never guesses.
    """
    return ((_axes(check, route, lang, counts, keep) if check is not None else "")
            + _form(route, controls, check, rendered, keep, lang)
            + '<noscript><p class="note">' + t(lang, "filter.noscript") + "</p></noscript>"
            + "".join(f'<p class="note">{one}</p>' for one in notes if one))


def _records_table(rows: Iterable[Any], empty: str = "", lang: str = DEFAULT_LANG,
                   title: bool = False, api: str = "") -> str:
    """The ledger's own rows: test, verdict, exit, source, when and the detail.

    One shape for the two pages that show records - a build's whole history on
    `/local/<id>` (`Records.for_build`) and the ledger itself on `/jobs`
    (`Records.load`).  Written once because the two were about to be two spellings of
    one table, which is how the `cards`/`records` columns of the two pages drifted
    apart in the first place (`03-structure.md` §A3).

    `title` adds the build id the record belongs to, which the per-build page has no
    use for (its whole page is one id) and the ledger page cannot do without: the
    `/jobs` table is the only place a reader can see a record for a build the local
    table no longer holds.  With `api` the id is a **link** to that build's own page,
    which is where the full record lives - one click, and the reader does not have to
    copy a hex id into the address bar.

    `detail` is printed **verbatim, and that is the decision**.  It is free text a
    child process wrote into the record (`lib/judge.py` produces `12 selftest(s): 9
    pass, 0 fail, 3 skip`), so a ledger written before that phrasing changed keeps the
    old words for ever; the value on screen is the value on disk, and a page that
    rewrote it would be claiming something about a run nobody can re-observe.
    `docs/gui-rework/tools/accept.py`'s W3 draws the line in the same place: a machine
    plural is the page's fault only when the *page* invented it.
    """
    head = ([t(lang, "word.build_id")] if title else []) + [
        t(lang, "word.test"), t(lang, "col.verdict"), t(lang, "col.exit"),
        t(lang, "col.source"), t(lang, "col.when"), t(lang, "col.detail")]
    built = []
    for one in rows:
        first = []
        if title:
            shown = (f'<code title="{html.escape(one.build_id)}">'
                     f'{html.escape(_short(one.build_id, 16))}</code>')
            href = _url("/local/" + urllib.parse.quote(one.build_id), Filter(api=api),
                        lang=lang)
            shown = f'<a href="{html.escape(href)}">{shown}</a>'
            first = [_cell(shown, "id")]
        built.append(_row(first
                          + [_cell(html.escape(one.test)),
                             _cell(_pill(one.verdict, "verdict")),
                             _cell(str(one.exit_code if one.exit_code is not None else "-"),
                                   "num"),
                             _cell(html.escape(one.source or "-"), "wrap"),
                             _cell(html.escape(one.timestamp or "-")),
                             _cell(html.escape(one.detail or ""), "wrap")]))
    return _table(head, built, empty=empty, cls="ledger")


def _tick_missing(rows: Iterable[dict[str, Any]], check: "Filter",
                  lang: str = DEFAULT_LANG) -> str:
    """The link that pre-ticks every card whose artifacts are not all on disk.

    「就是默认显示全部卡片可以筛选，然后就是想拉取卡片就轻松一点」 - the middle of that sentence
    is the part that was missing: the filter can already say *which* cards are incomplete
    (`?missing=kernel,modules,kselftest` is exact - `filtered_locals` measured 44 of the 52
    on this workspace), and the tick key can already pre-tick them, so the whole control is
    one link that lands on **the same page with the same filter** and those boxes on.  The
    reader sees the set and its cost before committing, which matters when the set is 132
    artifacts; the bar's own button then posts them, so no new command exists.

    The set comes from the engine's `accepts`, not from a second criterion written here: it
    is the same predicate that decided the rows above the link.
    """
    # The three the pipeline actually publishes for a test run.  `config` is deliberately
    # out: it is the comparison input, not something a build needs before it can run.
    want = check.missing or ("kernel", "modules", "kselftest")
    # The rows this page already drew are the honest set: they are what the reader can see,
    # and their ids are the ids a form can post.  `missing` decides which of them count.
    wanted = [str(one["build_id"]) for one in rows
              if one.get("local") is not None and one["local"].card is not None
              and any(name not in one["local"].present for name in want)]
    if not wanted or len(wanted) == len(rows):
        return ""
    href = _url("/", check, lang=lang, origin="card", tick=",".join(wanted))
    return (" " + f'<a class="badge" href="{html.escape(href)}"'
            f' title="{html.escape(t(lang, "link.tick_missing_title"))}">'
            + t(lang, "link.tick_missing", n=len(wanted)) + "</a>")


def _plural(n: int, lang: str = DEFAULT_LANG) -> str:
    """English's plural `s`, or nothing - the one place this program spells it.

    The catalogue has no plural rule on purpose (`lib/i18n.py`'s header), and the old
    habit of writing `artifact(s)` is what `accept.py`'s W3 check calls a machine plural
    invented by the page: it never says how many.  Chinese needs nothing, so `zh` and a
    single count both get the empty string.
    """
    return "s" if lang == "en" and n != 1 else ""


def _tick_failed(rows: Iterable[dict[str, Any]], check: "Filter",
                 lang: str = DEFAULT_LANG) -> str:
    """The link that pre-ticks the rows whose last pull failed, or `""` when none did.

    Retrying used to mean going back to the filter, finding the rows again and ticking
    them by hand (「失败了也不要就是重新到 pull 再搞一次筛选」).  The failure is already a fact
    of the row (`Local.latest["error"]`), the page's filter is already in the URL, and
    the tick key already exists - so the retry is one link that carries all three, and
    the reader sees the set and its cost before committing.
    """
    failed = [str(one["build_id"]) for one in rows if one.get("pull_failed")]
    if not failed:
        return ""
    href = _url("/", check, lang=lang, tick=",".join(failed))
    return (f'<a href="{html.escape(href)}">'
            + t(lang, "link.tick_failed", n=len(failed), s=_plural(len(failed), lang))
            + "</a>")


def _claim_pairs(rows: Iterable[dict[str, Any]], check: "Filter", picked: Mapping[str, str],
                 route: str, lang: str = DEFAULT_LANG) -> str:
    """Which (platform, runtime) pairs the available queue actually has, biggest first.

    `/worker` defaults to `qemu-riscv64` × `pull-labs-riscv` - this deployment's own
    machine - and on the public queue that pair claims nothing: every available job belongs
    to another lab.  The page said so honestly (`现在可领取 0 个`) and left the reader with a
    list of sixty platform names and ten lab names to search by hand for the one that has
    work.  This is that search, done: the available rows counted by pair, and each count a
    link that sets both boxes (`_url` with the worker's own two page keys), so one press
    points the worker at a queue that has something in it.

    Rows the page already read - the same answer the table and the badge use, so the three
    cannot disagree.  `mode` rides along like any other page key.
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
        current = " aria-current=\"true\"" if (platform, runtime) == wanted else ""
        href = _url(route, check, lang=lang, platform=platform, runtime=runtime,
                    mode=picked.get("mode", ""))
        parts.append(f'<a href="{html.escape(href)}"{current}>'
                     + t(lang, "worker.pair", platform=html.escape(platform),
                         runtime=html.escape(runtime), n=many) + "</a>")
    return ('<p class="quick"><span class="lead">'
            + html.escape(t(lang, "worker.pairs_lead")) + ":</span>"
            + " ".join(parts) + "</p>")


def _pulls_table(acts: list[dict[str, Any]], empty: str = "",
                 lang: str = DEFAULT_LANG, api: str = "") -> str:
    """Every recorded pull act: what was pulled, from where, and when.

    `api` is the page's API key, and it is carried onto the `/local/<build_id>`
    links because that page reads an API of its own (the build's remote
    counterpart): leading the reader from a production pull act to a page that
    quietly queries the local stack would be the whole failure this key fixes.
    """
    return _table((t(lang, "col.when"), t(lang, "word.build_id"), t(lang, "col.artifacts"),
                   t(lang, "col.bytes"), t(lang, "col.transferred"), t(lang, "col.hosts"),
                   t(lang, "col.error")),
                  [_row((_cell(html.escape(one["at"]), "wrap"),
                         _cell(f'<a href="{html.escape(_url("/local/" + urllib.parse.quote(one["build_id"]), Filter(api=api), lang=lang))}">'
                               f'<code>{html.escape(one["build_id"][:16])}</code></a>', "id"),
                         _cell(str(one["entries_count"]), "num"),
                         _cell(f'{one["bytes"]} ({_human(one["bytes"])})', "num"),
                         _cell(str(sum(1 for entry in one["entries"]
                                       if isinstance(entry, dict)
                                       and entry.get("transferred"))), "num"),
                         _cell(html.escape(", ".join(sorted({
                             _host(str(entry.get("url") or "")) for entry in one["entries"]
                             if isinstance(entry, dict)}))), "wrap"),
                         _cell(html.escape(one["error"] or "-"), "wrap")))
                        for one in acts], empty=empty, cls="pulls")


def _acts_table(local: "Local", empty: str = "", lang: str = DEFAULT_LANG) -> str:
    """One copy's recorded acts, one block each: the newest first."""
    if not local.acts:
        return f'<p class="empty">{empty}</p>'
    parts = []
    for act in local.acts:
        entries = [one for one in act.get("entries") or [] if isinstance(one, dict)]
        parts.append(
            f'<p class="query"><b>{html.escape(str(act.get("at") or "?"))}</b> &mdash; '
            + t(lang, "count.artifacts_act", n=len(entries)) + ", "
            + (t(lang, "label.error_prefix", what=html.escape(str(act["error"])))
               if act.get("error") else t(lang, "state.no_error"))
            + "</p>")
        parts.append(_table((t(lang, "col.artifact"), t(lang, "word.url"), t(lang, "col.bytes"),
                             t(lang, "col.that_pull")), [
            _row((html.escape(str(one.get("artifact") or "")),
                  f'<code>{html.escape(str(one.get("url") or ""))}</code>',
                  f'{one.get("bytes")} ({_human(int(one.get("bytes") or 0))})',
                  t(lang, "col.transferred") if one.get("transferred")
                  else t(lang, "state.already_whole_proven")))
            for one in entries]))
    return "".join(parts)


def _remote_detail(local: "Local", remote: "Kbuild | None", query: str, note: str = "",
                   lang: str = DEFAULT_LANG) -> str:
    """The remote side of one local copy: the row this page's query returned, or none.

    Three different facts again: the API answered and has this row, the API
    answered without it, and the API did not answer at all - only the second of
    those is "not in that answer", and only the third says nothing either way.
    """
    if remote is None:
        if note:
            return ('<p class="query">'
                    + t(lang, "remote_detail.no_answer", note=html.escape(note)) + "</p>")
        # The visible words are the **same two words the list page uses**
        # (`state.no_remote_counterpart`) - the detail page and the row that led here now
        # name the same fact the same way - and the doctrine that used to be printed here
        # ("the window is the API's only way of being asked…") is the tooltip, because it
        # is a definition of the vocabulary and not data (`02-dedupe.md` §C.4).
        why = t(lang, "remote_detail.none", query=html.escape(query))
        return ('<p class="query" title="' + html.escape(re.sub(r"<[^>]+>", "", why)) + '">'
                + t(lang, "state.no_remote_counterpart") + "</p>")
    record_node = local.node_id
    warning = ""
    if record_node and remote.node_id and record_node != remote.node_id:
        warning = ('<p class="bad">'
                   + t(lang, "remote_detail.node_mismatch",
                       record=html.escape(record_node), api=html.escape(remote.node_id))
                   + "</p>")
    return warning + _table((t(lang, "word.build_id"), t(lang, "word.node_id"),
                             t(lang, "word.tree_branch"), t(lang, "word.created"),
                             t(lang, "word.state_result"), t(lang, "col.artifact_urls")), [
        _row((_cell(f'<code>{html.escape(remote.build_id)}</code>', "id"),
              _cell(f'<code>{html.escape(remote.node_id or "-")}</code>', "id"),
              _cell(html.escape(f"{remote.tree} / {remote.branch}")),
              _cell(html.escape((remote.created or "-")[:16])),
              _cell(f'{_pill(remote.state, "job")}{_pill(remote.result, "idle")}'),
              _cell("<br>".join(f"<code>{html.escape(name)}: {html.escape(url)}</code>"
                                for name, url in sorted(remote.artifacts.items())), "wrap")))],
        cls="remote-detail")


def _found(catalogue: "Kbuilds | None", build_id: str) -> "Kbuild | None":
    """One build out of a catalogue we already hold, or None.

    A plain scan of `Kbuilds.items` and **not** `catalogue.get()`: `get()` asks the API
    for an id it does not hold, and that is a 1 000-node walk - measured at 116.8 s and
    137.9 s per id on production (`lib/kbuild.py: SCAN`, `06-analysis.md` §A7.1).  This
    labels rows the page has already read, so a build nobody here read gets no label,
    which is a fact the page prints rather than a reason to go and look.
    """
    for build in catalogue or ():
        if build.build_id == build_id:
            return build
    return None


def _ref_of(catalogue: "Kbuilds | None", build_id: str) -> str:
    """One build as a reader names it (`_build_ref`), or '' when this page has not read it."""
    return _build_ref(_found(catalogue, build_id))


def _artifact_of(catalogue: "Kbuilds | None", build_id: str, name: str) -> str:
    """One build's artifact URL, or '' - the raw `.config` the drift block links to."""
    build = _found(catalogue, build_id)
    return build.artifact(name) if build is not None else ""


def _build_ref(kbuild: "Kbuild | None") -> str:
    """`tree/branch · describe` - what tells two builds of one job apart.

    The ids do not: `6aa3689720239ade` and `6aac1402fc1857a9` name nothing, and the
    characters that do distinguish two builds (`…20239ade90` against `…fc1857a999`) are
    the ones a 16-character truncation drops (`06-analysis.md` §A3).  The tree, the
    branch and the kernel describe string are already on the `Kbuild` the page read, so
    this costs no request.
    """
    if kbuild is None:
        return ""
    where = "/".join(part for part in (kbuild.tree, kbuild.branch) if part)
    named = str((kbuild.revision or {}).get("describe") or "")
    return " · ".join(part for part in (where, named) if part)


def _same_branch(catalogue: "Kbuilds | None", older: str, newer: str) -> "bool | None":
    """Are both builds of one tree and branch?  None when this page cannot say.

    `True`/`False` is a fact about the pair, and `None` is a fact about this page: an
    id that is not in the catalogue the page read cannot be labelled, and guessing
    "different tree" for it would be exactly the confident-wrong sentence this whole
    rework is about.  The engine refuses nothing on tree or branch (`06-analysis.md`
    §A7), so this never decides anything - it only labels the number.
    """
    left, right = _found(catalogue, older), _found(catalogue, newer)
    if left is None or right is None:
        return None
    return (left.tree, left.branch) == (right.tree, right.branch)


# The verdicts in the order "by verdict" means: the ones a reader is looking for
# first, and `""` (no record at all) last rather than first - an empty cell is the
# absence of an answer, not a verdict.
_VERDICT_ORDER = ("fail", errors.VERDICT_ERROR, "incomplete", errors.VERDICT_PASS, "")


def _sort_keys(raw: str) -> tuple[tuple[str, str], ...]:
    """An order as `((key, direction), …)`, primary key first - the operator's list.

    One query value, comma-separated, each component `key` or `key:dir`
    (`sort=tree-branch,date:desc`).  One value and not a repeated key because
    `Filter.to_query` returns one pair per key and `_url` collapses the result through a
    dict, so a repeated `sort=` would be silently reduced to its last component by every
    link in this program - the comma-joined list is what `missing`/`has` already do.

    A round-1 spelling (`date-asc`, `same-branch`, `verdict`, `build`, `""`) is an alias
    for a list (`SORT_ALIASES`), so every URL written against the old control still means
    what it meant.  An unknown component is **dropped**, and `Filter.clamps` says so: a
    page that silently reordered itself is the one thing this filter may not do.
    """
    if raw in SORT_ALIASES:
        return SORT_ALIASES[raw]
    found = []
    for part in str(raw or "").split(","):
        name, _, direction = part.strip().partition(":")
        if name not in SORT_KEYS:
            continue
        default = SORT_KEYS[name][0]
        if any(seen == name for seen, _ in found):
            continue
        found.append((name, "asc" if direction == "asc" else
                      "desc" if direction == "desc" else default))
    return tuple(found) or SORT_ALIASES[""]


def _sort_refused(raw: str) -> str:
    """The order a URL asked for when it named a key this page does not have, else `""`.

    Only an *unknown key* is a refusal: `tree-branch,date:desc` and its canonical
    `tree-branch,date` are the same order, and a reader who spells a default out has
    not been refused anything.  `""` and the round-1 spellings are aliases, so they are
    not refusals either.
    """
    if not raw or raw in SORT_ALIASES:
        return ""
    for part in str(raw).split(","):
        if part.strip().partition(":")[0] not in SORT_KEYS:
            return raw
    return ""


def _sort_spec(raw: str) -> str:
    """The canonical spelling of an order: what `Filter.sort` holds and a URL carries.

    Canonical so that one order has one URL - the round-1 spellings are read and then
    written back as the list they mean, and an order whose keys are all invalid becomes
    the default and carries no `sort` key at all.
    """
    keys = _sort_keys(raw)
    if keys == SORT_ALIASES[""]:
        return ""
    return ",".join(name if direction == SORT_KEYS[name][0] else f"{name}:{direction}"
                    for name, direction in keys)


def _sort_label(key: "str | tuple[tuple[str, str], ...]", lang: str = DEFAULT_LANG) -> str:
    """The order's own name, out of the catalogue - the page never spells one in code.

    A list is named key by key with its arrows (`总分支 ↑, 日期 ↓`), which is what the
    axes strip, the sort control and the headings' sub-lines all print.  A bare string
    is a *value a URL carried*: it is read as the round-1 vocabulary first
    (`_sort_keys`), so `same-branch` still prints as the order it means rather than as
    three catalogue misses.
    """
    if isinstance(key, str):
        key = _sort_keys(key)
    return ", ".join(f'{t(lang, "sort.k." + name.replace("-", "_"))} '
                     + t(lang, "sort.dir.asc" if direction == "asc" else "sort.dir.desc")
                     for name, direction in key)


def _sort_cell(row: Mapping[str, Any], name: str) -> Any:
    """One sort key's value in one row, as something comparable and never raising.

    A row is a plain dict and different lists carry different keys; a key a list cannot
    answer sorts as the empty string, which is what lets one sorter serve the builds
    half and the runs half without either of them declaring a schema.  Numbers and the
    verdict rank are the two that are not text: `bytes`/`records` compare as ints, and a
    verdict compares by `_VERDICT_ORDER` (worst first), because alphabetical order would
    put `fail` after `error` for no reader's reason.
    """
    if name == "tree-branch":
        return (str(row.get("tree") or ""), str(row.get("branch") or ""))
    if name == "verdict":
        found = row.get("verdict")
        return _VERDICT_ORDER.index(found) if found in _VERDICT_ORDER else len(_VERDICT_ORDER)
    if name == "id":
        return str(row.get("build_id") or "")
    if name == "date":
        return (str(row.get("created") or row.get("timestamp") or ""),
                str(row.get("build_id") or ""))
    return str(row.get(name) or "")


def _sort_control(route: str, check: "Filter", keys: "tuple[tuple[str, str], ...]",
                  keep: Iterable[tuple[str, str]] = (), drop_added: Iterable[str] = (),
                  lang: str = DEFAULT_LANG) -> str:
    """The order, as the list of keys in force plus one link that adds each key.

    The operator asked for two things here and they are one control: **several keys at
    once** and **the order visible enough to change one of them**.  So the keys in force
    are chips numbered by position - each with an arrow that reverses it and an `×` that
    removes it - and every key *not* in force is a `+key` link that appends it at its
    default direction.  「先按总分支排，再按日期排」 is then `+总分支` and `+日期`: two
    presses, and the URL after each one says what the order is (`sort=tree-branch` then
    `sort=tree-branch,date`).

    Every link goes through `_url` and carries `keep` (the page's own state that is not
    a filter: the two chosen builds on `/analysis`), so changing the order never changes
    the question.  No JavaScript: the state is the URL, which is what makes an order
    shareable by copying the address bar - and `filter.sort` stays in the controlling
    form's `rendered=` list, so pressing `apply` keeps it.
    """
    keys = tuple(keys)
    chips = []
    for at, (name, direction) in enumerate(keys):
        label = t(lang, "sort.k." + name.replace("-", "_"))
        arrow = t(lang, "sort.dir.asc" if direction == "asc" else "sort.dir.desc")
        # Reversing one key keeps its position and every other key: the order lives in
        # the URL as text, so it is edited as text and re-parsed by `_sort_keys`.
        flipped = [(other, ("desc" if direction == "asc" else "asc") if other == name
                    else other_dir) for other, other_dir in keys]
        chips.append(
            f'<span class="chip">{at + 1}. {html.escape(label)} '
            f'<a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of(flipped)))}"'
            f' title="{html.escape(t(lang, "sort.flip_title"))}">{html.escape(arrow)}</a>'
            f' <a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of([one for one in keys if one[0] != name])))}"'
            f' title="{html.escape(t(lang, "sort.drop_title"))}">&times;</a></span>')
    added = {name for name, _ in keys}
    appends = "".join(
        f'<a href="{html.escape(_url(route, check, keep=keep, lang=lang, sort=_sort_spec_of([*keys, (name, SORT_KEYS[name][0])])))}"'
        f'>{html.escape(t(lang, "sort.add", key=t(lang, "sort.k." + name.replace("-", "_"))))}</a>'
        for name in SORT_KEYS if name not in added)
    return (f'<span class="quick"><span class="lead">'
            f'{html.escape(t(lang, "filter.sort"))}:</span>'
            + "".join(chips) + appends + "</span>")


def _sort_spec_of(keys: "Iterable[tuple[str, str]]") -> str:
    """The URL spelling of an order built in code: the default direction is left out.

    One spelling of one order, shared with `_sort_spec`'s parse of what a reader typed,
    so a link this control writes and a URL a reader edits mean the same thing.
    """
    return ",".join(name if direction == SORT_KEYS[name][0] else f"{name}:{direction}"
                    for name, direction in keys)


def _sort_rows(rows: list[dict[str, Any]],
               key: "str | tuple[tuple[str, str], ...] | None") -> list[dict[str, Any]]:
    """The one place an `/analysis` list is put in order - and the reason `sort` exists.

    The operator's model in one sentence: *selection decides the content, the order
    decides what is compared with what.*  So both halves of the page come through here -
    the builds the config half compares and the runs the regression half lists - and the
    header, the deltas and the chart all read the same answer.

    **Several keys, each with its own direction** (「先按总分支排，再按日期排」).  Python's
    sort is stable, so the list is composed right to left: the last key sorts first and
    the primary key is applied last, which is the only way to spell "descending inside an
    ascending group" without a hand-rolled comparison.  A bare string is read as the
    round-1 vocabulary (`_sort_keys`), which is what makes every existing caller and
    bookmark keep working.
    """
    keys = _sort_keys(key) if isinstance(key, str) or key is None else tuple(key)
    found = list(rows)
    for name, direction in reversed(keys):
        found.sort(key=lambda row: _sort_cell(row, name), reverse=(direction == "desc"))
    return found


def _chosen_pair(rows: list[dict[str, Any]], older: str = "",
                 newer: str = "") -> tuple[str, str]:
    """Which two builds the config half compares when the URL names none.

    **This is a product decision, and it was made against a measurement.**  Asked for
    two builds known to differ by hundreds of options the page renders hundreds of
    `CONFIG_` names; asked for *nothing in particular* it rendered **one**, because the
    pair it defaulted to (the first two rows of the local table) genuinely differs by a
    single option.  Both answers are honest and the second read as `显示太少了`, which is
    the complaint this step exists to answer.

    So the default pair is: **the newest build this page can name, against the newest
    build it can name that is of another *kernel series* - else of another *tree*, else
    of another *branch***, both of which must carry a `_config` artifact (a card with
    only a `kernel` artifact can never be a side of a comparison - `deadbeef1234`, §A3).
    Reasons, in order:

    * a comparison wants two kernels, and the only adjacency that *means* something is
      one where the sources differ - adjacent builds of one branch drift by 0/0/0
      every time (§A7, measured on four builds of `net-next/main`).  The series
      (`v7.3` against `v6.12`, off the `describe` the row already carries) is the widest
      difference the page can see without reading anything; another tree is next, then
      another branch;
    * it is deterministic and it needs **no read**: every row's series, tree, branch and
      `_config` are in the row the page already has;
    * the reader can see what was chosen (both builds are named on the block, and the
      line says which kind of pair it is), and can change it with one click or by
      typing an id.

    **The size of the drift is deliberately not the rule.**  Choosing the pair that
    drifts most would mean reading configs for candidate pairs until one looks big -
    the unbounded cost §D2 prices - and the page says how much this pair moved either
    way (`drift.badge`), so a small number reads as a fact about two close kernels
    rather than as a comparison that failed.  (Measured on this deployment, the newest
    builds all come off one shared base - `asoc-fix-v7.3-rc3-…` - which is why a
    same-series rule would pick two builds that differ by four options and read as
    `显示太少了` again.)

    A pair the URL names is never second-guessed.  One id named and the other missing:
    the missing side becomes the nearest row of another tree, else of another branch,
    else the next row.  The rows handed in must be **date-ordered** - the caller sorts
    for this, not the reader's sort, because "the newest" is a fact about time and not
    about the view.
    """
    known = [row for row in rows if row.get("config")]
    if (older and newer) or not known:
        return older, newer

    def apart(row: "dict[str, Any]", other: "dict[str, Any]") -> int:
        """How different two rows are: another series (3), tree (2), branch (1), neither (0)."""
        if row.get("series") and other.get("series") and row["series"] != other["series"]:
            return 3
        if row.get("tree") != other.get("tree"):
            return 2
        return 1 if row.get("branch") != other.get("branch") else 0

    if older or newer:
        chosen = older or newer
        at = next((one for one, row in enumerate(known) if row["build_id"] == chosen),
                  None)
        if at is None:
            # An id this page did not read (typed by hand): keep it - the reader named
            # it - and put the newest comparable row on the other side.
            partner = known[0] if known else None
        else:
            # The other side comes from the rows on the far side of `chosen` in time (an
            # `older` wants a newer partner and the other way round), and from all of
            # them when there is none - a page that left the slot empty because nothing
            # was newer would be a page that refused to answer a question it can answer.
            side = known[:at] if older else known[at + 1:]
            pool = side or [row for one, row in enumerate(known) if one != at]
            partner = max(pool, key=lambda row: apart(row, known[at]), default=None)
        other = partner["build_id"] if partner is not None else ""
        return (chosen, other) if older else (other, chosen)
    newest = known[0]
    rest = known[1:]
    partner = max(rest, key=lambda row: apart(row, newest), default=None)
    if partner is None or apart(partner, newest) == 0:
        partner = rest[0] if rest else None
    return (partner["build_id"] if partner is not None else ""), newest["build_id"]


def _other_side(key: str, build_id: str, older: str, newer: str) -> str:
    """The build the *other* side of a click's pair should name, so it is never the same one.

    A row that is already one side of the pair would otherwise build
    `older=<this row>&newer=<this same row>` - a config compared with itself, which the
    engine answers "no drift", i.e. a number about nothing.  So a click on a side that
    is already taken **swaps** the pair, which is also the affordance a reader expects
    from the row they have already picked: clicking the other cell of it turns the
    comparison round.
    """
    if key == "older":
        return newer if build_id != newer else older
    return older if build_id != older else newer


def _delta_cell(index: int, total: int, compared: int, edges: list[Any],
                render: "Any", lang: str = DEFAULT_LANG,
                rows: "list[dict[str, Any]] | None" = None,
                check: "Filter | None" = None) -> str:
    """One row's `±` against its neighbours **in the order this list is in**.

    Two segments per row, because the operator asked for both: "排序决定了它以前一个序和
    后一个序进行一个比较" - the row before and the row after.  Three rules, and each one
    is a case where the alternative would be a lie:

    * **the ends are printed, not faked**: the first row of the order says so, and so
      does the last.  A dash with no reason reads as "unknown", and a delta against a
      row that does not exist would be an invented number.
    * **a pair beyond the cap is not a zero**: only the first `compared` rows may spend
      a config read on their neighbours (`?delta=`, clamped to 0..6 - D2 prices one pair
      at 7.5-12.5 s cold), so a row past that says the comparison was not made instead
      of showing `0` - **and names the two neighbours as links**, which is what makes a
      500-row order readable without paying for 499 config reads.
    * **a row that cannot be compared keeps its place** and shows the engine's own
      reason via `render` (`这个为什么比不了` is answerable per row; a dropped row is the
      one answer that is never honest).

    **Each segment is a link into the comparison it names** (「点击会看到它那个比较」):
    the number is the door to the detail, so the page does not have to print hundreds of
    `CONFIG_` names inline for a comparison nobody asked to read.  A refusal is a link
    too - "why can't these two be compared" is a question the detail page answers.
    """
    def door(other_index: int, body: str) -> str:
        if rows is None or check is None or not (0 <= other_index < len(rows)):
            return body
        here = str(rows[index].get("build_id") or "")
        there = str(rows[other_index].get("build_id") or "")
        if not (here and there):
            return body
        return (f'<a class="delta-door" href="{html.escape(_compare_url(here, there, check, lang))}">'
                + body + "</a>")

    def marker(other_index: int, text: str) -> str:
        """A neighbour whose comparison was not made: its id, as the door to running it."""
        if rows is None or check is None or not (0 <= other_index < len(rows)):
            return f'<span class="none">{text}</span>'
        there = str(rows[other_index].get("build_id") or "")
        if not there:
            return f'<span class="none">{text}</span>'
        return (f'<a class="delta-door none" title="{html.escape(t(lang, "delta.door_title", build=there))}"'
                f' href="{html.escape(_compare_url(str(rows[index].get("build_id") or ""), there, check, lang))}">'
                f'{text} {html.escape(_short(there, 12))}</a>')

    parts = []
    if index == 0:
        parts.append(f'<span class="none">{t(lang, "delta.none_prev")}</span>')
    elif index < compared:
        parts.append(door(index - 1, render(edges[index - 1])))
    else:
        parts.append(marker(index - 1, t(lang, "delta.before")))
    if index == total - 1 and index > 0:
        parts.append(f'<span class="none">{t(lang, "delta.none_next")}</span>')
    elif index + 1 < compared:
        parts.append(door(index + 1, render(edges[index])))
    else:
        # The row after this one is past the cap: the comparison was **not made**, and a
        # `0` here would be the invented number this whole cell exists to avoid.  The
        # tooltip names the cap, which is the number the reader can raise.
        parts.append(marker(index + 1, t(lang, "delta.after")))
    return "<br>".join(parts)


def _compare_url(build_id: str, other: str, check: "Filter",
                 lang: str = DEFAULT_LANG) -> str:
    """The detail URL for one comparison: `/analysis/<id>?vs=<other>#drift`.

    Built through `_url` so the filter and the order ride along (a comparison read out of
    context is a different comparison), with `older`/`newer` cleared: the pair this page
    is *comparing* is page state and must not be dragged into a link that names its own
    two builds.
    """
    return _url("/analysis/" + urllib.parse.quote(build_id or ""), check, "older", "newer",
                lang=lang, vs=other) + "#drift"


def _why_of(error: str, lang: str = DEFAULT_LANG) -> str:
    """The *kind* of a refusal, read off the engine's own message.

    `Drift` refuses for exactly three reasons (`06-analysis.md` §A7) and the page shows
    the engine's sentence either way - this adds the two-word kind beside it, because
    "cannot compare" with no kind is the state the operator was in when they asked
    `有些无法进行比较，我也不懂为什么`.  A message this does not recognise gets no kind
    rather than a wrong one: the sentence is still there, in the `title=`.
    """
    text = str(error or "")
    if "not a kernel config" in text:
        return t(lang, "delta.why_not_config")
    if "among the newest" in text:
        return t(lang, "delta.why_not_found", scan=SCAN)
    if "does not match its record" in text:
        return t(lang, "delta.cache_short")
    code = re.search(r"HTTP (\d{3})", text)
    if code:
        return t(lang, "delta.why_no_config", code=code.group(1))
    return ""


def _config_delta(edge: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """One adjacent comparison as the operator's own arithmetic: `+added −removed ~changed`.

    The sign is always the *newer* build against the older one, whatever order the list
    is in (`Drift.series` fixes the direction), and the tooltip names both builds and the
    pair's numbers, so `+616` cannot be read backwards.  `A5.3`'s ambiguity is answered
    the same way: nothing here is a bare triple that the reader has to remember the
    sense of.
    """
    if edge.get("error"):
        why = edge.get("why") or _why_of(edge["error"], lang)
        return (f'<span class="bad" title="{html.escape(edge["error"])}">'
                + t(lang, "delta.cannot")
                + (f'<span class="sub">{why}</span>' if why else "") + "</span>")
    report = edge["report"]
    added, removed, changed = (len(report.added), len(report.removed),
                               len(report.changed))
    title = t(lang, "delta.pair_title",
              older=edge["older"].build_id, newer=edge["newer"].build_id,
              added=added, removed=removed, changed=changed)
    if not report.drifted():
        return (f'<span class="delta" title="{html.escape(title)}">'
                f'<span class="zero">0</span></span>')
    return (f'<span class="delta" title="{html.escape(title)}">'
            f'<span class="plus">+{added}</span> '
            f'<span class="minus">&minus;{removed}</span> '
            f'<span class="tilde">~{changed}</span></span>')


def _cases_delta(edge: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """`+n / −n` for the regression half: more cases failing, or fewer (B6).

    The ledger is on disk, so this costs nothing: one run's `results["failed"]` against
    its neighbour's, plus the verdict change in words, so the fact survives a
    colour-blind reader and a monochrome print - the timeline's ring is the chart's
    version of the same fact.
    """
    moved = int(edge["failed"])
    older, newer = edge["older"]["verdict"], edge["newer"]["verdict"]
    cls = "delta-up" if moved > 0 else ("delta-down" if moved < 0 else "zero")
    shown = (f'<span class="{cls}" title="{html.escape(t(lang, "delta.failed_title"))}">'
             f'{"+" if moved > 0 else ("&minus;" if moved < 0 else "")}{abs(moved)}</span>')
    change = ""
    if older != newer:
        change = (f'<br><span class="sub">{html.escape(older or "-")}&rarr;'
                  f'{html.escape(newer or "-")}</span>')
    return shown + change


def _bar_chart(edges: list[dict[str, Any]], lang: str = DEFAULT_LANG) -> str:
    """The same order, as bars: one row per adjacent comparison.

    **Widths are classes, not inline styles.**  The quantum (5 %) is decided once in the
    stylesheet, the exact number is printed beside the bar, and a third colour would be
    a third class rather than a third `style=` - the rule the regression timeline's two
    facts already follow (`.timeline .point`).  The bar is `added + removed`, which is
    the number a reader comparing two configs is looking at, and the tooltip carries
    the three counts and the two build ids.

    A pair the engine refused gets a dashed `w0` bar and the refusal in its `title=`: an
    empty bar for a comparison that was never made is the honest picture, and it keeps
    the chart the same length as the list above it.
    """
    top = max((_config_weight(edge) for edge in edges), default=0)
    rows = []
    for edge in edges:
        weight = _config_weight(edge)
        width = 0 if not top else min(20, round(20 * weight / top))
        if edge.get("error"):
            bar = f'<span class="bar w0 gap" title="{html.escape(edge["error"])}"></span>'
            number = '<span class="none">-</span>'
        else:
            report = edge["report"]
            title = t(lang, "delta.pair_title", older=edge["older"].build_id,
                      newer=edge["newer"].build_id, added=len(report.added),
                      removed=len(report.removed), changed=len(report.changed))
            bar = f'<span class="bar w{width}" title="{html.escape(title)}"></span>'
            number = f"{weight:,}".replace(",", " ")
        pair = " &rarr; ".join(
            f'<code>{html.escape(_id_of(edge[key]))}</code>' for key in ("older", "newer"))
        rows.append(f'<tr><th scope="row">{pair}</th>'
                    f'<td>{bar}</td><td class="num">{number}</td></tr>')
    return ('<table class="bars"><tbody>' + "".join(rows) + "</tbody></table>")


def _id_of(build: Any) -> str:
    """A build's id, or `-` for a side that is not a build this page could name.

    An edge with a `var/downloads/` directory and no card on one side has no `Kbuild`
    at all (`_config_edges` records the refusal rather than dropping the row), and the
    chart still draws its two ends: the dashed `w0` bar says the comparison was not
    made, and this keeps the row's own labels honest instead of raising.
    """
    return str(getattr(build, "build_id", "") or "-")


def _config_weight(edge: dict[str, Any]) -> int:
    """How much a pair moved: the two counts a `+n −n` column is read for."""
    report = edge.get("report")
    return 0 if report is None else len(report.added) + len(report.removed)


def _pair_doors(report: dict[str, Any], older: str, newer: str, check: "Filter",
                lang: str = DEFAULT_LANG) -> str:
    """What `/analysis` prints where the whole diff used to be: the two doors and the files.

    Three things, and each is one line: the raw `.config` files the comparison was made
    from (`_raw_configs` - "open it yourself" in its cheapest honest form), the link into
    the detail route that prints **every** changed option, and nothing else.  A refusal
    still prints the engine's own sentence here, because a reader who cannot compare needs
    to know why before they need the numbers.
    """
    parts = []
    if report.get("error"):
        parts.append('<p class="bad">'
                     + t(lang, "drift.cannot_compare", error=html.escape(str(report["error"])))
                     + "</p>")
    if older and newer:
        parts.append('<p class="query"><a href="'
                     + html.escape(_compare_url(older, newer, check, lang)) + '">'
                     + t(lang, "one.all_rows") + "</a></p>")
    return _raw_configs(report, lang) + "".join(parts)


def _drift_block(report: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """The config difference between the two builds, whole, with each count said once.

    Three defects of the old block are fixed here, and they were checked against the
    **served markup** rather than against extracted text (`08-PLAN.md`, carry-over):

    1. **The counts were printed twice** - in a summary sentence *and* in each category
       head (`新增 (0)`, `改动 (0)`), and the parentheses of those heads are what the
       operator read as one broken string, `新增 (616 删除 (618))`.  The heads are now
       plain words, and the three numbers live in exactly two places, each with a job:
       the heading's badge (`+1899 −308 ~131`, `_pair_line`, so a pair that moved
       nothing says so before the reader scrolls) and each `<details>`' own label
       ("all 1899 rows"), which is the control that opens it.
    2. **A zero category drew a head over an empty list.**  A category with no rows is
       now a phrase (`nothing added`), not a box.
    3. **The triples were unlabelled** (`CONFIG_ACPI_DEBUG  y  n`, with HTML collapsing
       the two spaces).  Each row is now a labelled `option | older | newer` - the two
       sides named once in the header - and the whole thing is a `table.drift`, so the
       34-character `tbody td` clip that cut 4 of the 123 rendered rows (and every one
       of the 1 210 behind `... N more`) does not apply.

    The rows are already in hand: `Gui.drift` returns every one of them (616 + 618 + 99
    on the pair §A1 measured), so showing the whole diff costs **no** read - the first
    25 rows of each section are inline and the rest rides in a `<details>`, which needs
    no JavaScript and no second fetch.  The two raw `.config` files are linked beside
    them (`_raw_configs`), which is the operator's `可以打开一个文本查看` in its cheapest
    honest form: the file itself, not this page's reading of it.
    """
    if report.get("error"):
        return ('<p class="bad">'
                + t(lang, "drift.cannot_compare", error=html.escape(str(report["error"])))
                + "</p>")
    if not report.get("drifted"):
        return ('<p>' + t(lang, "drift.no_drift",
                          older=html.escape(report.get("older_ref") or report["older"]),
                          newer=html.escape(report.get("newer_ref") or report["newer"]))
                + "</p>")
    older = html.escape(report.get("older_ref") or report["older"])
    newer = html.escape(report.get("newer_ref") or report["newer"])
    head = ("<tr><th>" + t(lang, "col.option") + '</th>'
            f'<th>{t(lang, "filter.older")} <span class="sub">{older}</span></th>'
            f'<th>{t(lang, "filter.newer")} <span class="sub">{newer}</span></th></tr>')
    sections = []
    for order, (label, entries) in enumerate(
            ((t(lang, "drift.added"), report["added"]),
             (t(lang, "drift.removed"), report["removed"]),
             (t(lang, "drift.changed"), report["changed"]))):
        if not entries:
            # A phrase, not a head over an empty box: the count is on the line above.
            sections.append(f'<p class="none">{t(lang, "drift.nothing", what=label)}</p>')
            continue
        rows = "".join(_drift_row(order, entry) for entry in entries[:_DRIFT_FIRST])
        rest = entries[_DRIFT_FIRST:]
        table = ("<table class=\"drift\">" + head + "<tbody>" + rows + "</tbody></table>")
        if rest:
            table += ("<details><summary>"
                      + t(lang, "drift.all_rows", n=len(entries)) + "</summary>"
                      + '<table class="drift">' + head + "<tbody>"
                      + "".join(_drift_row(order, entry) for entry in rest)
                      + "</tbody></table></details>")
        sections.append(f'<h3 id="{("added", "removed", "changed")[order]}">{label}</h3>'
                        + table)
    return (_raw_configs(report, lang) + "".join(sections))


def _raw_configs(report: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """The two `.config` files themselves, as links - "可以打开一个文本查看", cheapest form.

    The URL is already on the `Kbuild` the page read (`artifacts["_config"]`), so this
    costs nothing and it is the *whole* file rather than this page's reading of it: a
    diff this page caps (25 rows a category inline, the rest behind one `<details>`) is
    not a diff the reader cannot get in full.  `.config` is a filename and stays as it
    is in both languages; the two sides are named by `filter.older`/`filter.newer`, the
    same two words the pair is named with everywhere else on this page.
    """
    links = []
    for key, label in (("older_url", "filter.older"), ("newer_url", "filter.newer")):
        url = str(report.get(key) or "")
        if url:
            links.append(f'<a href="{html.escape(url)}" title="{html.escape(url)}">'
                         f'<code>{html.escape(t(lang, label))} .config</code></a>')
    return f'<p class="sub">{" · ".join(links)}</p>' if links else ""


# How many rows of each category the block prints before the `<details>`: enough to
# read the shape of a diff without scrolling past a thousand lines, and every row after
# that is one click away in the same document (nothing is re-fetched).
_DRIFT_FIRST = 25


def _drift_row(order: int, entry: "tuple[Any, ...]") -> str:
    """One option of a diff as `option | older | newer`, with the missing side a dash.

    `lib/drift.diff` returns `(key, older, newer)` for a change and `(key, value)` for
    an addition or a removal, so the absent side is printed as `-` and never as an
    empty cell: "this option has no value here" is the whole content of the row.
    """
    key = html.escape(str(entry[0]))
    cells = [f'<td class="wrap"><code>{key}</code></td>']
    if order == 0:                     # added: newer has it, older does not
        cells += ['<td class="none">-</td>', f"<td>{html.escape(str(entry[1]))}</td>"]
    elif order == 1:                   # removed: older had it
        cells += [f"<td>{html.escape(str(entry[1]))}</td>", '<td class="none">-</td>']
    else:                              # changed: both sides, in the ledger's order
        cells += [f"<td>{html.escape(str(entry[1]))}</td>",
                  f"<td>{html.escape(str(entry[2]))}</td>"]
    return f'<tr class="{("added", "removed", "changed")[order]}">' + "".join(cells) + "</tr>"


def _remote_line(lead: str, rows: "Remote", check: Filter, extra: str = "",
                 lang: str = DEFAULT_LANG) -> str:
    """The one line that says which API was asked, what it answered, and how much is shown.

    Three counts, kept apart: the rows this page prints, the rows the fetched
    window kept, and the API's own `total` for the query - which is quoted,
    because a page that counted its own rows would be answering its own question.
    An API that did not answer has no counts to print, and says that instead.

    `lead` is the sentence the caller looked up (`remote.asked`): the page owns the
    words, this function owns the counts.  `{query}` is the machine-readable question
    and stays exactly as it is in both languages (`src/GUI.md` §1.5).

    **The coverage sentence is a tooltip now.**  It used to end this line, and it is
    the only place a reader learns *why* a row is missing - "the API counts 1782 for
    this query, so 1732 older rows are outside the 50-row cap; 7 of the rows inside the
    cap are not in this table - this page's own filter, not the API".  That is a
    limitation of the API's window and of this page's filter, which is a definition and
    therefore a `title=` (`05-i18n-prose.md` §B.1), and it was the sentence the
    operator's own acceptance script greps for as prose (`accept.py`'s W1 list).  The
    counts it is about stay on the line as numbers; pressing the number is how a reader
    sees the rows.
    """
    if rows.note:
        return ('<p class="query">' + html.escape(lead) + ": "
                f'<code>{html.escape(rows.query)}</code> &mdash; '
                + t(lang, "remote.no_answer_line", note=html.escape(rows.note)) + "</p>")
    return ('<p class="query">' + html.escape(lead) + ": "
            f'<code>{html.escape(rows.query)}</code>'
            + (f" &mdash; {html.escape(extra)}; " if extra else " &mdash; ")
            + f'<span title="{html.escape(rows.coverage(lang))}">'
            + t(lang, "remote.line_tail",
                showing=t(lang, "remote.showing", shown=len(rows), kept=rows.kept),
                cap=t(lang, "remote.rows_cap", n=check.limit))
            + "</span></p>")


def _empty_remote(rows: "Remote", lang: str = DEFAULT_LANG) -> str:
    """Why the remote table is empty.

    "The API did not answer" and "the API answered with nothing" are two different
    facts, and a page that prints the second when the first is true is telling its
    reader the API has no such build.
    """
    if rows.note:
        return t(lang, "empty.remote_no_answer", note=html.escape(rows.note))
    return t(lang, "empty.remote_empty", query=html.escape(rows.query))


def _empty_queue(note: str, check: Filter, state: str, lang: str = DEFAULT_LANG) -> str:
    """Why the queue table is empty: same two facts as `_empty_remote`, in the queue's words."""
    if note:
        return t(lang, "empty.queue_no_answer", note=html.escape(note))
    return t(lang, "empty.queue_empty", state=html.escape(state or "any"),
             job=html.escape(check.job or "any"))


def _timeline(points: list[dict[str, Any]], check: "Filter | None" = None,
              keep: Iterable[tuple[str, str]] = (), point: str = "",
              test: str = "", lang: str = DEFAULT_LANG) -> str:
    """One block per run, oldest first; a regression point (pass -> fail) is ringed.

    **Each block is a link now.**  They were `<span class="pass point">` with a `title`
    and nothing else: no `href`, no focusable element, no `cursor`, no script - inert
    with JavaScript on *and* off, which is what `这个不能选` meant (`06-analysis.md` §A6).
    The link is the shape that works with JavaScript off, it carries the whole query
    plus `point` (`_url`, the same rule as every other link on the page: the URL is the
    state), and the selected cell is marked `aria-current` the way a preset is.

    The ring stays a class and not an inline style - the two facts a point carries are
    its verdict and whether it is a regression, and both belong to the stylesheet.
    """
    if not points:
        return "<span>" + t(lang, "state.no_runs") + "</span>"
    cells = []
    for one in points:
        mark = "&#9632;" if one["verdict"] in (errors.VERDICT_PASS, errors.VERDICT_FAIL) else "&#9633;"
        ring = " regressed" if one["regression"] else ""
        title = _point_title(one)
        cls = f'{html.escape(one["verdict"])} point{ring}'
        here = ' aria-current="true"' if point and one["build_id"] == point else ""
        href = _url("/analysis", check, keep=keep, lang=lang, point=one["build_id"],
                    test=test)
        cells.append(f'<a class="{cls}" href="{html.escape(href)}"{here} '
                     f'title="{html.escape(title)}">{mark}</a>')
    return '<span class="timeline">' + "".join(cells) + "</span>"


def _point_title(one: dict[str, Any]) -> str:
    """One run as a tooltip: the five facts the cell cannot print.

    `06-analysis.md` §A6: these used to be *all* the page said about a run - the four
    facts a point carried lived in a `title=` and nowhere else, so a phone or a
    keyboard-only reader never saw them.  The design keeps the tooltip (it costs
    nothing and survives JavaScript off) **and** prints them in the run's own row and
    in the record block below, because a tooltip is not a reading.
    """
    exit_code = one.get("exit_code")
    exit_text = "-" if exit_code is None else str(exit_code)
    return " · ".join(part for part in (
        str(one.get("build_id") or ""), str(one.get("timestamp") or ""),
        f'{one.get("verdict") or "-"} ({one.get("source") or "-"})',
        f'exit {exit_text}', str(one.get("detail") or "")) if part)


def _record_block(point: dict[str, Any], held: Mapping[str, Any], ref: str = "",
                  lang: str = DEFAULT_LANG) -> str:
    """The run a timeline cell selected, with every field its record holds.

    `Gui.trend` projects five fields of an `Outcome`; the record on disk holds thirteen
    (`lib/out.py: RECORD_FIELDS`), and the operator's `看见一些哈希值那个，这没什么用`
    is about exactly that gap.  Nothing here is re-derived and nothing is fetched: every
    value is a field of the record the ledger read, and the two links go to pages that
    already exist (`/local/<id>`, which is where the bytes and the log box are).

    A build with no local copy is **not** linked to `/local/<id>`: that page raises
    `error.no_local_copy` for one, and a link that refuses is worse than a path.  `ref`
    is the page's own label for this build (`tree/branch · describe`), used when the
    record itself carries no revision - older records do not, and a row of dashes is
    less use than the label the list above is already showing.
    """
    build_id = str(point.get("build_id") or "")
    revision = point.get("revision") or {}
    results = point.get("results") or {}
    local = held.get(build_id)
    where = str(point.get("artifacts_dir") or "")
    commit = " · ".join(part for part in (
        "/".join(part for part in (str(revision.get("tree") or ""),
                                   str(revision.get("branch") or "")) if part),
        str(revision.get("describe") or ""),
        str(revision.get("commit") or "")[:12]) if part) or ref
    rows = [
        (t(lang, "word.build_id"), _build_cell(build_id, bool(local), lang)),
        (t(lang, "word.commit"), html.escape(commit or "-")),
        (t(lang, "col.verdict"),
         _pill(point.get("verdict") or "", "verdict")
         + " · exit " + html.escape("-" if point.get("exit_code") is None
                                    else str(point["exit_code"]))
         + " · " + html.escape(str(point.get("source") or "-"))
         + " · " + html.escape(str(point.get("timestamp") or "-"))),
        (t(lang, "col.cases"), html.escape(_cases_text(results))),
        (t(lang, "col.detail"), html.escape(str(point.get("detail") or "-"))),
        (t(lang, "word.log"), (f'<code>{html.escape(str(point.get("log") or "-"))}</code>'
                               if point.get("log") else "-")),
        (t(lang, "col.bytes"), (f'<a href="{html.escape(_local_url(build_id, lang))}">'
                                f'<code>{html.escape(where)}</code></a>'
                                if where and local else html.escape(where or "-"))),
    ]
    return ('<h2 id="point">' + t(lang, "page.analysis.point_title") + " "
            + f'<span>{t(lang, "page.analysis.point_sub")}</span></h2>'
            "<table class=\"record-fields\">" + "".join(
                f'<tr><th>{label}</th><td class="wrap">{value}</td></tr>'
                for label, value in rows) + "</table>")


def _build_cell(build_id: str, held: bool, lang: str = DEFAULT_LANG) -> str:
    """A build id, linked to its detail page when this deployment holds the copy."""
    code = f'<code title="{html.escape(build_id)}">{html.escape(build_id)}</code>'
    if not build_id:
        return "-"
    return (f'<a href="{html.escape(_local_url(build_id, lang))}">{code}</a>'
            if held else code)


def _local_url(build_id: str, lang: str = DEFAULT_LANG) -> str:
    """The `/local/<id>` drill-down, in this language and with no conditions on it."""
    return _url("/local/" + urllib.parse.quote(build_id), Filter(), (), lang=lang)


def _trend_rows(points: list[dict[str, Any]], held: Mapping[str, Any],
                lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
    """One run as the list's own kind of row: the five sort keys plus what a row shows.

    The five keys (`build_id`, `created`, `verdict`, `tree`, `branch`) are the ones
    `_sort_rows` reads, so the runs list is ordered by the *same* function that orders
    the builds - one order for the page, which is the operator's model.  `created` is
    the record's `timestamp`: the ledger's own clock is the one both runs are ordered
    by everywhere else (`Records.series`).
    """
    rows = []
    for one in points:
        revision = one.get("revision") or {}
        results = one.get("results") or {}
        build_id = str(one.get("build_id") or "")
        rows.append({
            "build_id": build_id, "created": str(one.get("timestamp") or ""),
            "verdict": str(one.get("verdict") or ""),
            "tree": str(revision.get("tree") or ""),
            "branch": str(revision.get("branch") or ""),
            "point": one, "held": build_id in held,
            "failed": int(results.get("failed") or 0),
            "total": int(results.get("total") or 0),
            "test": str(one.get("test") or ""),
        })
    return rows


def _wave_slots(rows: list[dict[str, Any]], records: "Records",
                test: str) -> list[dict[str, Any]]:
    """One slot per position of the page's order: the build, and what this test has for it.

    A slot is a *position*, not a run: the list is the page's whole order (gaps included),
    and every position the ledger has no record for is a slot with `gap` - which is how
    the chart can show a test that stopped, instead of a line that pretends it never ran.
    """
    slots = []
    for at, row in enumerate(rows):
        build_id = str(row["build_id"])
        found = _last_verdict_row(records, test, build_id)
        slots.append({
            "at": at, "build_id": build_id, "record": found,
            "verdict": str(found.get("verdict") or "") if found else "",
            "gap": found is None,
        })
    return slots


def _wave_chart(slots: list[dict[str, Any]], check: "Filter | None" = None,
                keep: Iterable[tuple[str, str]] = (), point: str = "", test: str = "",
                lang: str = DEFAULT_LANG) -> str:
    """One test's verdicts over the page's whole order: a chart, not another strip.

    The operator asked for exactly this and named the coordinate himself: 「回归分析它可能
    还要加一个图，一个图那个坐标就是排序的坐标，就类似直接可能要加一个图表，就那种折线图」.
    So `x` is **the order above** - not time, because the order is what the reader chose
    and the whole point of `/analysis` is that the order defines what is next to what -
    and `y` is three lanes of one column each:

    * **the verdict**, as the same `.point` cell `_timeline` already draws, so the
      `title=`, the `aria-current` marking and the JavaScript-off behaviour are
      inherited rather than re-invented.  Adjacent cells are contiguous, so the lane
      reads as one line broken exactly where the data breaks;
    * **the case counts**, from the record's own TAP numbers (`_cases_text`): `·` where
      the record has none, never `0`, because "the run reported no failures" and "the
      run reported nothing" are two different facts;
    * **the row number in the list below**, so the chart and the list can be walked
      together - the same coordinates, which is the operator's whole request.

    **A gap is not a hole in the page.**  A build in the order with no record for this
    test is a dashed slot that links to `/jobs` - where the gap is reported and can be
    filled - because the alternative (an inert cell) is the `这个不能选` complaint again,
    and a silent gap would hide the one thing the operator is looking for: a test that
    stopped running.

    Widths are classes and never inline styles (the rule `_bar_chart` keeps), so this
    stays a table: printable, keyboard-navigable, and honest with JavaScript off.  The
    data is the ledger and the row list, both already in memory - the chart costs no
    read at all.
    """
    if not slots:
        return ""
    cells = [[], [], []]
    for slot in slots:
        here = ' aria-current="true"' if point and slot["build_id"] == point else ""
        if slot["gap"]:
            why = t(lang, "chart.gap_title", build=slot["build_id"], test=test)
            href = _url("/jobs", check, keep=keep, lang=lang, test=test)
            cells[0].append(f'<td><a class="gap point" href="{html.escape(href)}"{here} '
                            f'title="{html.escape(why)}">&#9633;</a></td>')
            cells[1].append('<td class="empty">&middot;</td>')
            cells[2].append('<td class="num">-</td>')
            continue
        found = slot["record"]
        mark = ("&#9632;" if slot["verdict"] in (errors.VERDICT_PASS, errors.VERDICT_FAIL)
                else "&#9633;")
        href = _url("/analysis", check, keep=keep, lang=lang,
                    point=slot["build_id"], test=test)
        title = _point_title({"build_id": slot["build_id"],
                              "timestamp": found.get("timestamp"),
                              "verdict": found.get("verdict"),
                              "source": found.get("source"),
                              "exit_code": found.get("exit_code"),
                              "detail": found.get("detail")})
        cells[0].append(f'<td><a class="{html.escape(slot["verdict"])} point" '
                        f'href="{html.escape(href)}"{here} '
                        f'title="{html.escape(title)}">{mark}</a></td>')
        cells[1].append(f'<td class="num">{html.escape(_cases_text(found.get("results") or {}))}</td>')
        cells[2].append(f'<td class="num">{slot["at"] + 1}</td>')
    lanes = (t(lang, "chart.lane_verdict"), t(lang, "chart.lane_cases"), t(lang, "chart.lane_at"))
    body = "".join("<tr><th>" + name + "</th>" + "".join(one) + "</tr>"
                   for name, one in zip(lanes, cells))
    return ('<div class="wave-wrap"><table class="wave"><tbody>' + body
            + "</tbody></table></div>")


def _last_verdict_row(records: "Records", test: str, build_id: str) -> dict[str, Any]:
    """The newest record for one (test, build) pair, as a plain dict, or `{}`.

    `Records.series` already answers this and hands back `Outcome` objects; the chart
    wants the record's own fields (verdict, results, timestamp) per column, so this is
    one lookup per build with no second parse - `Records` is in memory for the request.
    """
    found = records.series(test, build_id)
    if not found:
        return {}
    newest = found[-1]
    return {"verdict": getattr(newest, "verdict", ""),
            "timestamp": getattr(newest, "timestamp", ""),
            "source": getattr(newest, "source", ""),
            "exit_code": getattr(newest, "exit_code", None),
            "detail": getattr(newest, "detail", ""),
            "results": getattr(newest, "results", {}) or {}}


def _cases_text(results: Mapping[str, Any]) -> str:
    """The TAP counts of one record as `failed/total`, or `-` when the run never got that far.

    A record whose test died before TAP ran holds `{}`, and printing `0/0` for it is a
    claim the ledger does not make: the run did not report zero failures, it reported
    nothing at all (`03-structure.md`'s complaint about a machine-generated number in
    place of an absent one).
    """
    total = int(results.get("total") or 0)
    if not total and not int(results.get("failed") or 0):
        return "-"
    skipped = int(results.get("skipped") or 0)
    return (f'{int(results.get("failed") or 0)}/{total}'
            + (f' ({skipped} skipped)' if skipped else ""))


def _trend_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`+failed / −fixed` between consecutive rows, the older run of each pair first.

    Free: the ledger is on disk and `Gui.trend` already carries `results`.  The pair is
    directed by timestamp for the same reason the config pairs are (`+2` must mean "the
    newer run had two more failures" on every row, whichever way the list is sorted).
    """
    edges = []
    for first, second in itertools.pairwise(rows):
        older, newer = (first, second) if first["created"] <= second["created"] \
            else (second, first)
        edges.append({"older": older, "newer": newer,
                      "failed": newer["failed"] - older["failed"]})
    return edges


def _trend_table(rows: list[dict[str, Any]], check: "Filter | None", keep: Iterable[tuple[str, str]],
                 point: str, test: str, compared: int, edges: list[dict[str, Any]],
                 lang: str = DEFAULT_LANG) -> str:
    """The chosen test's runs, in the page's order, each with its `±` beside it.

    **Not called `_runs_table`.**  That name is the *activity* table on `/runs`
    (`_runs_table(rows, empty, lang, rows_of, group, kinds)`, gui.py:7012) and a second
    definition of one name at module scope silently wins, which is how a shadowed
    `_numbers` made every page answer HTTP 500 during the merge (`CHANGELOG.md` §6).
    The two tables are different questions: that one is what *this machine ran*, this
    one is one test's history from the ledger.

    The list the operator asked for, on the other half of the page: selection (the
    test) decides the content, the order decides what is compared with what, and the
    delta column says what changed against the neighbours in *that* order.  The `#`
    cell is a link selecting the run, so the record block below is one click from a row
    as well as from a timeline cell.
    """
    head = (t(lang, "col.n"), t(lang, "word.build_id"), t(lang, "col.when"),
            t(lang, "col.verdict"),
            f'{t(lang, "col.cases")} <span class="sub">{t(lang, "col.delta_sub")}</span>',
            t(lang, "col.exit"), t(lang, "col.detail"))
    body = []
    for at, row in enumerate(rows):
        selected = bool(point) and row["build_id"] == point
        href = _url("/analysis", check, keep=keep, lang=lang, point=row["build_id"],
                    test=test)
        number = (f'<a href="{html.escape(href)}" aria-current="true">{at + 1}</a>'
                  if selected else f'<a href="{html.escape(href)}">{at + 1}</a>')
        point_one = row["point"]
        body.append(_row((
            _cell(number, "num"),
            _cell(_build_cell(row["build_id"], row["held"], lang), "id"),
            _cell(html.escape(row["created"] or "-"), "wrap"),
            _cell(_pill(row["verdict"], "verdict")),
            _cell(f'<span class="num">{html.escape(_cases_text({"failed": row["failed"], "total": row["total"]}))}'
                  f'</span><br>'
                  + _delta_cell(at, len(rows), min(compared, len(rows)), edges,
                                lambda edge: _cases_delta(edge, lang), lang), "wrap"),
            _cell(html.escape("-" if point_one.get("exit_code") is None
                              else str(point_one["exit_code"])), "num"),
            _cell(html.escape(str(point_one.get("detail") or "-")), "wrap")),
            cls="selected" if selected else ""))
    return _table(head, body, t(lang, "state.no_runs"), cls="runs-list")


def _build_rows(known: list[str], builds: list[Kbuild], check: Filter, records: "Records",
                held: Mapping[str, Any], lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
    """The builds this page can name, as rows: what it read, what it holds, what the ledger says.

    **The filter decides which builds are in this list.**  `tree`, `branch`, `arch`,
    `defconfig`, `compiler`, `state`, `result`, `text`, `origin`, `has`, `missing`,
    `evidence`, `ran` and `verdict` go through `Filter.accepts` - the same predicates
    every other table in this program uses - so the bar above the list means what it
    means everywhere else and the renderer computes nothing (`00-BRIEF.md` rule 2).

    Nothing here is fetched: the `Kbuild` comes from `_known_builds` (one read the page
    was making anyway), the local copy from `all_locals()` and the record count from
    `_state()`, both cached for this request.  The API cannot be asked for a build *by
    id* (`lib/kbuild.py: SCAN`, 116.8-137.9 s measured), so a chooser that wanted more
    detail per row would pay a hundred-second scan for it; everything a reader needs to
    tell two builds apart is in the row the page already has (`06-analysis.md` §A3).

    `known` is every id the page can name - including the directories under
    `var/downloads/` that no card names, which have no `Kbuild` at all.  They are rows
    too (the id, and what is on disk), they are simply not comparable: no card means no
    `_config` artifact, which is one of the three refusals §A7 measured.
    """
    cards = {build.build_id: build for build in builds}
    rows = []
    for build_id in known:
        kbuild = cards.get(build_id)
        local = held.get(build_id)
        if not check.accepts(kbuild, records, local):
            continue
        found = records.for_build(build_id)
        revision = (kbuild.revision or {}) if kbuild is not None else {}
        config = kbuild.artifact("_config") if kbuild is not None else ""
        rows.append({
            "build_id": build_id, "kbuild": kbuild,
            "created": str(kbuild.created or "") if kbuild is not None else "",
            "tree": str(kbuild.tree or "") if kbuild is not None else "",
            "branch": str(kbuild.branch or "") if kbuild is not None else "",
            "series": _series_of(revision.get("describe")),
            "verdict": found.items[-1].verdict if found.items else "",
            "config": bool(config), "config_url": config,
            "records": len(found),
            "held": bool(local is not None and local.present),
            "ref": _build_ref(kbuild),
            "line": _build_line(kbuild, revision, build_id),
            "marks": _build_marks(config, local, len(found), lang),
        })
    return rows


def _series_of(describe: Any) -> str:
    """The kernel series a build belongs to, out of its `describe` (`v6.12.108-2861-…` -> `v6.12`).

    The one signal this page has for "these are two different kernels" without reading a
    config.  It is searched for rather than anchored, because this deployment's newer
    builds carry a topic prefix (`asoc-fix-v7.3-rc3-803-g9f1c440f92830`) and an anchored
    pattern would call all of them series-less.  A describe string with no `v<major>.<minor>`
    (`next-20260915`) yields `''`, which `_chosen_pair` treats as *unknown* and never as
    a series of its own - the alternative would make two unknown builds "different".
    """
    found = re.search(r"\bv(\d+\.\d+)", str(describe or ""))
    return f"v{found.group(1)}" if found else ""


def _build_line(kbuild: "Kbuild | None", revision: Mapping[str, Any], build_id: str) -> str:
    """The two lines the operator asked for: what the build *is*, then its details.

    A native `<option>` cannot wrap to two lines - its content model is text, browsers
    render one line and ignore child elements (`06-analysis.md` §A4) - which is why the
    chooser is a table of links rather than a select box.  Line one is the fact that
    tells two builds apart, line two the fields a reader checks next.  The commit is
    shortened to twelve characters because the full forty are in the record's own
    `title` and on the correspondence page.
    """
    if kbuild is None:
        return (f'<code title="{html.escape(build_id)}">{html.escape(build_id)}</code>'
                '<br><span class="sub">-</span>')
    named = _build_ref(kbuild)
    detail = " · ".join(part for part in (str(kbuild.created or ""),
                                          str(kbuild.compiler or ""),
                                          str(kbuild.arch or ""),
                                          str(kbuild.defconfig or ""),
                                          str(revision.get("commit") or "")[:12]) if part)
    return (f'<b>{html.escape(named) or html.escape(build_id)}</b>'
            f'<br><span class="sub">{html.escape(detail)}</span>')


def _build_marks(config: str, local: Any, records: int, lang: str = DEFAULT_LANG) -> str:
    """Three marks per row: can this build be compared, is there a copy here, has it run.

    They are the facts that decide the questions a reader is about to ask, and two of
    them are what makes a doomed pair visible **before** it is picked: `config -` is a
    build no comparison can use (`06-analysis.md` §A7), and the artifact URL is in the
    `title=` for the reader who wants the raw file.
    """
    def mark(word: str, yes: bool, title: str = "") -> str:
        attr = f' title="{html.escape(title)}"' if title else ""
        return (f'<span class="{"yes" if yes else "no"}"{attr}>'
                f'{html.escape(word)} {"&#10003;" if yes else "&mdash;"}</span>')

    held = bool(local is not None and local.present)
    return ('<span class="marks">'
            + mark(t(lang, "word.config"), bool(config), config) + " "
            + mark(t(lang, "col.bytes"), held) + " "
            + f'<span>{t(lang, "mark.records")} {records}</span></span>')


def _picks_table(rows: list[dict[str, Any]], check: Filter, older: str, newer: str,
                 keep: Iterable[tuple[str, str]], compared: int, edges: list[dict[str, Any]],
                 lang: str = DEFAULT_LANG) -> str:
    """The list: the builds the filter chose, in the sort order, each with its neighbours' delta.

    **One list, three jobs** - which builds, in what order, and what changed between the
    neighbours in that order - because that is one question, and it is the operator's own
    design: "首先我通过筛选构建…下面是一个列表…还有就是一个排序…排序决定了它以前一个序和
    后一个序进行一个比较…旁边可以写成那种加减".

    The two left-hand cells are the *selection*, as links (`[older]` / `[newer]`) carrying
    the whole query, because two controls for one key is the failure mode this design has
    to avoid: a `<select name="older">` beside an `<input name="older">` and `_first()`
    would silently pick one.  So the rows are links and the only *inputs* are the two
    text boxes in the page's one GET form (`_filter_bar`), which is also where a pasted
    id goes - refused when it names a build this page did not read, because that path is
    a 116.8-137.9 s scan inside a GET (`06-analysis.md` §D3).
    """
    head = (t(lang, "col.n"), t(lang, "filter.older"), t(lang, "filter.newer"),
            t(lang, "word.build"),
            f'{t(lang, "col.delta")} <span class="sub">{t(lang, "col.delta_sub")}</span>')
    body = []
    for at, row in enumerate(rows):
        build_id = row["build_id"]
        picks = []
        for key, current, label in (("older", older, t(lang, "filter.older")),
                                    ("newer", newer, t(lang, "filter.newer"))):
            here = ' aria-current="true"' if build_id and build_id == current else ""
            # Both keys of the condition, because a pair needs two builds: the other
            # side is the page's own choice, or a swap when this row already holds it.
            href = _url("/analysis", check, keep=keep, lang=lang,
                        **{key: build_id,
                           ("newer" if key == "older" else "older"):
                               _other_side(key, build_id, older, newer)})
            picks.append(_cell(f'<a href="{html.escape(href)}"{here}>'
                               + label + "</a>", "act"))
        shown = (f'<a href="{html.escape(_local_url(build_id, lang))}">{row["line"]}</a>'
                 if row["held"] else row["line"])
        # The group break of `sort=same-branch`: a rule above the row where the
        # tree/branch changes, so the order the sort *means* is visible without a
        # caption row (which would be a row the chart and the deltas then have to skip).
        group = (_sort_keys(check.sort)[0][0] == "tree-branch" and at > 0
                 and (rows[at - 1]["tree"], rows[at - 1]["branch"])
                 != (row["tree"], row["branch"]))
        body.append(_row((_cell(str(at + 1), "num"), *picks,
                          _cell(shown + "<br>" + row["marks"], "wrap"),
                          _cell(_delta_cell(at, len(rows), compared, edges,
                                            lambda edge: _config_delta(edge, lang), lang,
                                            rows=rows, check=check),
                                "delta")),
                         cls=" ".join(part for part in ("group" if group else "",
                                                        "" if row["config"] else "nocfg")
                                      if part)))
    return _table(head, body, t(lang, "empty.no_builds"), cls="picks")


def _by_kind(rows: list[dict[str, Any]], order: Iterable[str] = KIND_ORDER
             ) -> list[dict[str, Any]]:
    """The activity rows in the group order, each kind's rows kept in the page's own order.

    `sorted` on a key that is *not* in the order puts an unknown kind last rather than
    dropping it: a kind this page has never heard of (a `stack`, a `verify`) is a fact
    about the deployment, not something to hide.  `sorted` is stable, so within a kind
    the newest-first order `Run.load_all()` produced survives untouched.
    """
    wanted = list(order)
    return sorted(rows, key=lambda one: wanted.index(one["kind"])
                  if one["kind"] in wanted else len(wanted))


def _runs_table(rows: list[dict[str, Any]], empty: str = "",
                lang: str = DEFAULT_LANG, rows_of: str = "",
                group: bool = False, kinds: Iterable[str] = ()) -> str:
    """The activity table: what ran, what it ran, and the two things you can do to it.

    The markup here and the re-render in `_JS` are the same cells in the same
    order with the same classes: a table that changes shape when it refreshes is a
    table nobody can read while something runs.  They also read the same three
    words from the same keys - `link.log` and `js.cancel` are looked up here and
    injected into the script (`_js`), so a refreshed row cannot change language.
    That now includes the **group captions**: `group=True` emits one caption row per
    kind and hands the order to the script in `data-kinds`, because a poll that
    dropped the captions would re-shape the table two seconds after it was drawn.

    `rows_of` is passed straight through to `_table`: the caller that drew the *whole*
    activity list says so (`rows_of="all"`), and every caller that drew a subset -
    `/runs` with a kind or state filter, `/local/<id>` with one build's argv - leaves
    it out, which is what tells the 2 s poll to leave those rows alone.

    `group` is the classification the operator asked for in as many words: 37 of the
    50 activities on this deployment are `table.py index`, and they were interleaved
    with the run he was watching ("为什么拉取或者这里就 run 也会显示").  The caption
    is the kind - code vocabulary, translated by `runs.group` only for its brackets -
    and its count, so a reader can see at a glance which group is the noise.
    """
    head = (t(lang, "word.id"), t(lang, "word.kind"), t(lang, "word.state"),
            t(lang, "col.age"), t(lang, "col.exit"), t(lang, "col.what_run"),
            t(lang, "word.argv"), "")
    order = list(kinds) or list(KIND_ORDER)
    body: list[str] = []
    last = ""
    for row in rows:
        # The group caption rides in the **first cell of its group's first row** and
        # is not a row of its own.  A caption `<tr>` was the plan's shape
        # (`04-actions.md` §P8) and it is wrong here for a reason worth stating: a row
        # count is how this page is checked, the numbers strip counts *activities*
        # (every row of `var/runs`), and `accept.py`'s S6 finds that number by counting
        # `<tr>`s on this page - so a caption row per kind would make `activities 64`
        # unreproducible (70 `<tr>`s for 64 activities) and the label would be the lie
        # instead of the number.  `display: block` on the span gives it the caption's
        # own line; the count of what a row *is* stays exact.
        first = group and row["kind"] != last
        caption = ""
        if first:
            last = row["kind"]
            many = sum(1 for one in rows if one["kind"] == last)
            caption = (f'<span class="kind-group">'
                       f'{html.escape(t(lang, "runs.group", kind=last, n=many))}</span>')
        code = "-" if row["exit_code"] is None else row["exit_code"]
        argv = " ".join(row["argv"])
        # A `drift` activity's exit code is its *answer* (0 no drift, 1 drift), not a
        # failure - said where it applies, as a tooltip on that row's own cell, instead
        # of as a paragraph about every row above the table (`runs.intro`, deleted).
        exit_cell = (f'<span title="{html.escape(t(lang, "analysis.drift_hint"))}">{code}</span>'
                     if row["kind"] == "drift" else str(code))
        home = layout.runs(row["id"])
        body.append(_row((
            _cell(f'{caption}<code title="{html.escape(t(lang, "runs.dir_title", dir=home))}">'
                  f'{html.escape(row["id"])}</code>',
                  "id" + (" group-first" if first else "")),
            _cell(html.escape(row["kind"])),
            _cell(_pill(row["state"], "run")),
            _cell(html.escape(row["age"]), "num"),
            _cell(exit_cell, "num"),
            _cell(html.escape(row["what"][:60]), "wrap"),
            _cell(f'<code title="{html.escape(argv)}">{html.escape(argv[:60])}</code>', "wrap"),
            _cell('<span class="cell-actions">'
                  # `href` is the machine endpoint (`src/GUI.md` §4) and `onclick` is
                  # the box: a link that is only an `onclick` does **nothing at all**
                  # with JavaScript off, and there is no other way to read a log from
                  # this page (`_log_box` is rendered `hidden`).  Progressive
                  # enhancement, the same rule every button on this page follows:
                  # without JavaScript the reader gets the documented JSON, with it he
                  # gets the box.  This is the operator's "某些日志点不开", cause (b).
                  f'<a href="/runs/{html.escape(row["id"])}/log" '
                  f'onclick="showLog(\'{html.escape(row["id"])}\');return false">'
                  f'{html.escape(t(lang, "link.log"))}</a>'
                  f'<form method="post" action="/api/runs/{html.escape(row["id"])}/cancel">'
                  f'<button class="btn">{html.escape(t(lang, "js.cancel"))}</button>'
                  "</form></span>", "act"))))
    if not body:
        return f'<p class="empty">{empty}</p>' if empty else ""
    return _table(head, body, cls="runs", id="runs", rows_of=rows_of,
                  kinds=order if group else ())


def log_body(payload: Mapping[str, Any], lang: str = DEFAULT_LANG) -> str:
    """One activity's log as the bytes a browser shows at `/runs/<id>/log`.

    The payload is `Gui.log(id, 0)`'s - the same read the log box uses, so the page
    and the address cannot show different logs.  Two lines of header carry what the
    activity *is* (its id, its state, its exit code) because a log with no name on it
    is a wall of text in a tab the reader then cannot identify; an activity with an
    empty log gets a sentence instead of a blank page, which is the same complaint
    ("打开不了") arriving a second way.
    """
    text = str(payload.get("text") or "")
    head = t(lang, "log.head", run=str(payload.get("id") or ""),
             state=str(payload.get("state") or ""),
             exit_code="-" if payload.get("exit_code") is None else str(payload["exit_code"]))
    if not text:
        return head + "\n\n" + t(lang, "log.empty") + "\n"
    return head + "\n\n" + text


def _log_box(lang: str = DEFAULT_LANG) -> str:
    """The incremental log tail: one box per page, filled by the 1s poll.

    It is rendered `hidden` and `showLog()` takes the attribute off: a page with
    no activity being watched must not sit under a large empty grey box, which is
    what four pages did.
    """
    return ('<section class="logbox" hidden><div class="head">'
            + html.escape(t(lang, "link.log")) + ' <span id="logid">-</span></div>'
            '<div id="log"></div></section>')


# How many ended activities the panel keeps under the running ones.  A display cap
# like `ROWS`, and the same kind of number: it decides how much this page prints,
# never what happened.  Three is what fits above the fold on a 700px window.  It
# rides to the script as `LIVE_KEPT` (`_js`), so the panel the server drew and the
# one the poll rewrites cannot disagree about how much history a "live" panel keeps.
LIVE_KEPT = 3


def _duration(seconds: float) -> str:
    """A run's own seconds as the panel prints them: `1m06s`, `28s`.

    A unit, not a sentence (`05-i18n-prose.md` §B.1 class 2): `1m06s` needs no
    translation and no plural rule, where "1 minute and 6 seconds" would need both.
    """
    whole = max(0, round(seconds or 0))
    return f"{whole // 60}m{whole % 60:02d}s" if whole >= 60 else f"{whole}s"


def _live_chip(count: int, lang: str = DEFAULT_LANG) -> str:
    """The header's one live fact: how many activities are running, and a link to them.

    A link and not a second list, because the header answers *is anything running*
    while the panel answers *what* - and it is the one live fact that has to be
    visible on every page and while scrolling, which is why it sits in the header's
    existing flex row rather than on a row of its own (`--head-h` is the sticky
    `thead`'s offset, and a wrap here would hide the header row under it).

    It carries the same two elements the panel's tab does (`.spin`, `.live-word`), so
    the poll script keeps both in step with one rule and one number.  The count comes
    from the same `run_rows()` the panel was drawn from, so chip and panel cannot
    disagree at render time.

    `header.busy` stays where it is: it is about *writes being refused*, and a running
    `results` shuts no gate (`07-shell.md` §A4).
    """
    word = (t(lang, "live.tab_running", n=count) if count else t(lang, "live.tab_idle"))
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if count else " hidden") + "></span>")
    return (f'<a class="live-chip{" idle" if not count else ""}" href="#live">'
            f'{spin}<span class="live-word">{html.escape(word)}</span></a>')


def _live_row(one: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """One activity in the panel: state, elapsed, what it is, its argv, and its two acts.

    The ended rows say the exit code **or say that none was seen**.  `Run._settle`
    (`lib/run.py`) turns a code it never learned into `failed`, so an activity whose
    process the GUI lost settles as `failed` with `exit_code: null` whatever the child
    really exited with - the live tree holds two such rows.  A panel that printed
    "failed" beside an invented code would repeat a claim nobody can check, so it
    prints `exit code not seen` and lets the pill carry the stored state
    (`07-shell.md` §A3, `live.exit_unknown`).

    `log` is a **real href**, not `href="#"`: with JavaScript off the reader gets the
    documented JSON instead of nothing, and with it `showLog()` takes the click over -
    the same progressive enhancement `_runs_table` uses (the operator's "某些日志点不开").
    """
    ended = one["state"] != run_mod.RUNNING
    code = one["exit_code"]
    exit_text = (t(lang, "live.exit", code=code) if code is not None
                 else t(lang, "live.exit_unknown"))
    argv = " ".join(str(part) for part in one["argv"])
    home = html.escape(str(one["id"]))
    acts = (f'<a href="/runs/{home}/log" '
            f'onclick="showLog(\'{home}\');return false">'
            f'{html.escape(t(lang, "link.log"))}</a>')
    if not ended:
        acts += (f'<form method="post" action="/api/runs/{home}/cancel">'
                 f'<button class="btn">{html.escape(t(lang, "js.cancel"))}</button></form>')
    return ('<li class="live-row ' + ("ended" if ended else "running") + '"'
            f' data-id="{home}" data-started="{float(one["started"] or 0):.3f}"'
            f' data-state="{html.escape(str(one["state"]))}">'
            '<div class="live-line">'
            + ("" if ended else '<span class="spin" aria-hidden="true"></span>')
            + _pill(one["state"], "run")
            + f'<code class="live-id">{home}</code>'
            + f'<span class="live-time num">{_duration(one["seconds"])}</span></div>'
            + f'<div class="live-what">{html.escape(str(one["what"])[:80])}</div>'
            + f'<code class="live-argv" title="{html.escape(argv)}">'
              f'{html.escape(argv)}</code>'
            + '<div class="live-act">'
            + (f'<span class="live-exit">{exit_text}</span>' if ended else "")
            + acts + "</div></li>")


def _live_panel(rows: list[dict[str, Any]], lang: str = DEFAULT_LANG,
                kept: int = LIVE_KEPT) -> str:
    """What is running now, and what just ended - the shell's own side panel.

    **Rendered by the server, not built by the script**, and that is the point: a page
    whose side panel exists only after a successful `fetch` shows nothing when
    JavaScript is off or the API answers slowly, and the running activity is exactly
    when the page is being read.  The script's job is to *update* this list, never to
    create it (`livePoll`).

    `open` follows the facts: something running means the panel is already out, so the
    reader sees it with no click; nothing running means it is a tab they can pull, and
    a quiet page does not lose 380px of width to an empty column.  That is also what
    "the sidebar must work without JavaScript" costs - one attribute, decided here.

    Nothing is computed.  A row is an activity on disk, and "recently ended" is the
    first `kept` rows of this same list that are not running - no verdict, no
    re-derivation of what `lib/judge.py` or the record says (ground rule 2).
    """
    running = [one for one in rows if one["state"] == run_mod.RUNNING]
    ended = [one for one in rows if one["state"] != run_mod.RUNNING][:kept]
    body = "".join(_live_row(one, lang) for one in (*running, *ended))
    head = t(lang, "live.head_running") if running else t(lang, "live.head_recent")
    word = (t(lang, "live.tab_running", n=len(running)) if running
            else t(lang, "live.tab_idle"))
    # The ring is drawn whether or not anything is running and hidden when nothing is,
    # so the poll script only ever toggles `hidden` on it - it never has to build the
    # element, and a page that has never run anything still has the shape.
    spin = ('<span class="spin" aria-hidden="true"'
            + ("" if running else " hidden") + "></span>")
    return ('<details class="live" id="live"' + (" open" if running else "") + ">"
            + f'<summary class="live-tab">{spin}'
              f'<span class="live-word">{html.escape(word)}</span></summary>'
            + '<div class="live-body"><div class="live-head">'
            + spin + f'<b class="live-headword">{html.escape(head)}</b>'
            + f'<span class="live-count">{len(running)}</span>'
            # Rendered `hidden` and unhidden by the script only where the browser
            # really has the Notification API: a button that does nothing because the
            # origin is not a secure context (a LAN address, not 127.0.0.1) is a worse
            # lie than no button.  It never prompts on its own - the click is the
            # gesture, which is the only form of this every browser accepts.
            + f'<button class="btn live-notify" type="button" data-notify="1" hidden>'
              f'{html.escape(t(lang, "live.notify_off"))}</button></div>'
            + f'<ul class="live-list">{body}</ul>'
            + f'<p class="live-empty"{" hidden" if body else ""}>'
              f'{html.escape(t(lang, "live.none"))}</p>'
            + '<noscript><p class="note">' + html.escape(t(lang, "live.noscript"))
            + "</p></noscript>"
            + "</div></details>")


def _nav(check: "Filter | None", current: str, lang: str = DEFAULT_LANG) -> str:
    """The navigation bar, with the current page spelled out and its conditions carried.

    Moving between pages keeps what the target reads and nothing more: the carry
    whitelist is the whole rule, so no link can quietly add a condition.  The pages
    are listed once - this bar *is* the list of them, which is why the footer no
    longer repeats it.

    `current` is a route *name*, and the comparison is made on it and never on the
    printed word: the day a translation changes, a bar that compared titles would
    stop marking the page the reader is on.
    """
    route_of = {title: route for route, title in PAGES}
    source = NAV_KEYS.get(route_of.get(current, ""), ())
    parts = []
    for route, title in PAGES:
        text = html.escape(t(lang, f"nav.{title}"))
        if title == current:
            parts.append(f"<b>{text}</b>")
            continue
        parts.append(_link(route, check, source, t(lang, f"nav.{title}"), lang))
    return " ".join(parts)
