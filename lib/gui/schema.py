# SPDX-License-Identifier: LGPL-2.1-or-later
"""The vocabulary every page is drawn from: routes, actions, filters, orders.

One module, because these are the tables two pages must agree about.  Which routes
exist and where they are (`PAGES`, `REDIRECTS`), what a route reads and what a nav
link carries on from it (`ROUTE_KEYS`, `NAV_KEYS`), the buttons and the `Run` kind
each one starts (`ACTIONS`, `KINDS`, `WRITERS`), the values a select box may offer
(`ORIGINS`, `EVIDENCE`, `LIMITS`, `DAYS`), the order `/analysis` sorts in (`SORTS`,
`SORT_KEYS`) and the measurements a cap is set from (`ROW_BYTES` lives with the page
that prints it, `MAX_DELTA` is here): a second copy of any of them is a page that
answers a question its URL does not state.

Nothing here is behaviour - every other module of this package reads these tables
and no table reads them - so this is the one module everything may import."""

import os
import re

from .. import api as api_mod
from .. import errors, repo_root
from ..i18n import DEFAULT_LANG, t
from ..tests import DEFAULT_DEVICE, DEFAULT_LAB

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
# state in this GUI, not two.
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


def _archs_from_config() -> tuple[str, ...]:
    """Every architecture the vendored build config declares, in its own order.

    `jobs*.yaml` is where a build job's `params.arch` lives (`kbuild-gcc-14-riscv`
    carries `arch: riscv`), and that value is what the node's `data.arch` is a copy
    of - so this is the same kind of source `_platforms_from_config` found for
    `data.platform`: the file that *decides* the value, read from a checkout that has
    it.  It has to be a config and not a constant for the reason `_trees_from_config`
    gives, and it has to be this config because the API cannot enumerate a field's
    values (`_combo`'s docstring).

    The 11 names it yields here (`arc`, `arm`, `arm64`, `i386`, `loongarch`, `mips`,
    `powerpc`, `riscv`, `s390`, `um`, `x86_64`) are the pipeline's own vocabulary.
    They are offered as *candidates*: this deployment's nodes are all `riscv` because
    its job name is pinned to one (`KBUILD_JOB`), and it is the axes strip's own count
    that tells a reader `arch=arm64` matched nothing here.

    A list-valued `arch:` (`rules:` then `- arm64`, which three `coverage-report`
    jobs carry) contributes nothing, by the rule `_platforms_from_config` follows: a
    shape this page does not own degrades to a shorter list, never to a guess.  A
    `rules.arch` is not a `params.arch` in the first place - it says which nodes a job
    applies to, not which arch a node carries.
    """
    base = os.path.join(repo_root(), "kernelci-pipeline", "config")
    try:
        names = sorted(one for one in os.listdir(base)
                       if one.startswith("jobs") and one.endswith(".yaml"))
    except OSError:
        return ()                       # no vendored config: `ARCH_FIXED` is the floor
    found: list[str] = []
    for name in names:
        try:
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        for one in re.findall(r"^\s+arch:\s*([A-Za-z0-9._+-]{1,64})\s*$", text,
                              re.MULTILINE):
            if one not in found:
                found.append(one)
    return tuple(found)


def _scheduler_text() -> list[tuple[str, str]]:
    """`[(name, text)]` for every vendored `scheduler*.yaml`, in name order.

    The upstream pipeline's scheduler config is the only static place in this
    checkout that says which *platforms* a lab serves and which *runtimes* exist -
    a job node's `data.platform` and `data.runtime` are copies of what these files
    declare.  Read with a regex rather than a YAML parser, like
    `_trees_from_config` and for the same reason: four files whose shape this page
    does not own, and one that changed shape must degrade to "no extra names"
    rather than to an exception on a page.
    """
    base = os.path.join(repo_root(), "kernelci-pipeline", "config")
    try:
        names = sorted(one for one in os.listdir(base)
                       if one.startswith("scheduler") and one.endswith(".yaml"))
    except OSError:
        return []                       # no vendored config: the fixed lists are the floor
    found = []
    for name in names:
        try:
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                found.append((name, handle.read()))
        except OSError:
            continue
    return found


def _block_lines(lines: list[str], index: int, indent: int) -> list[str]:
    """The lines of the YAML block opened at `index` by a key at `indent`.

    A block ends at the next line at or above the key's own indentation, which is
    what makes `platforms:`'s items readable without knowing which lab they belong
    to - the file is a list of jobs, and every one of them carries the same keys.
    Blank lines are inside the block; they carry no item and no key.
    """
    body = []
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return body


def _platforms_from_config() -> tuple[str, ...]:
    """Every platform the vendored scheduler config lists, in its own order.

    A lab block spells them as a YAML list (`platforms:` then `- qemu-x86_64`),
    which is where `qemu-x86_64` lives: the page could not offer it before, because
    the only candidates it had were the platforms the queue answer happened to
    carry plus `DEFAULT_DEVICE`.

    An alias (`platforms: *ltp-full-qemu-platforms`) contributes nothing *here* and
    does not need to: the anchor that defines that list is a block of its own, one
    lab further up the same file, and is read where it stands.  An anchor on the key
    itself (`platforms: &name`) is followed by the items as usual.
    """
    found: list[str] = []
    for _name, text in _scheduler_text():
        lines = text.splitlines()
        for index, line in enumerate(lines):
            head = re.match(r"^(\s*)platforms:\s*(.*)$", line)
            if head is None or head.group(2).startswith("*"):
                continue
            for item in _block_lines(lines, index, len(head.group(1))):
                one = re.match(r"^\s*-\s+([A-Za-z0-9._+-]{1,64})\s*$", item)
                if one is None:
                    break               # not a scalar list any more: stop, do not guess
                if one.group(1) not in found:
                    found.append(one.group(1))
    return tuple(found)


def _runtimes_from_config() -> tuple[str, ...]:
    """Every **pull-lab** runtime the vendored scheduler config names, in its own order.

    The `runtime:` blocks carry `type:` and `name:`; only `pull_labs` is a candidate
    for this worker, and that is a fact about the engine and not a preference: a job
    a worker here can claim is one whose node carries a definition artifact
    (`Kjob.claimable`), and only the pull-lab template renders one.  Offering a
    `lava` lab would offer a claim filter that can never match.
    """
    found: list[str] = []
    for _name, text in _scheduler_text():
        lines = text.splitlines()
        for index, line in enumerate(lines):
            head = re.match(r"^(\s*)runtime:\s*(.*)$", line)
            if head is None or head.group(2).startswith("*"):
                continue                # an alias: named where its anchor stands
            block = "\n".join(_block_lines(lines, index, len(head.group(1))))
            kind = re.search(r"^\s*type:\s*(\S+)\s*$", block, re.MULTILINE)
            named = re.search(r"^\s*name:\s*([A-Za-z0-9._+-]{1,64})\s*$", block, re.MULTILINE)
            if kind is None or named is None or kind.group(1) != "pull_labs":
                continue
            if named.group(1) not in found:
                found.append(named.group(1))
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

# The architectures a build node can carry.  Same two halves as the trees above and
# for the same reason, with one difference worth stating: this list exists because the
# operator noticed the *absence* of it - `arch` offered exactly one value here
# ("架构目前只填一个 riscv 的怪状"), and it offered one because `_combo` derived its
# candidates from the rows the API had answered, and every row this deployment reads
# is `kbuild-gcc-14-riscv` with `data.arch=riscv`.  There is no way to enumerate a
# field's values over the API, so the candidates come from the file that sets them:
# `ARCH_FIXED` is what the page needs on a machine with no vendored checkout, and
# `_archs_from_config` is the same list read live from `jobs*.yaml`.  The count is
# here so a drift between the two is one diff away from being visible, as above.
ARCH_FIXED = ("arc", "arm", "arm64", "i386", "loongarch", "mips", "powerpc", "riscv",
              "s390", "um", "x86_64")
ARCH_KNOWN = ARCH_FIXED + tuple(one for one in _archs_from_config()
                                if one not in ARCH_FIXED)

# Branches cannot be enumerated: `Api.nodes()` filters by branch but has no way
# of listing them (`lib/api.py`).  These are a typing convenience for the trees
# this deployment reads, and the page says so instead of pretending they are all.
# The mapping, so the next reader does not have to guess: `main` is what this
# deployment's cards carry, `master` the mainline and linux-next trees, `for-next`
# the riscv/arm64/soc ones, `linux-X.Y.y` the stable ones.
BRANCH_SEEDS = ("main", "master", "for-next", "linux-next", "linux-6.6.y",
                "linux-6.12.y")

# The two things `/worker` selects that the page could not offer before: the
# platform a worker claims jobs for, and the runtime (the lab) it claims them from.
# Both are floors the page needs on a machine with no vendored config, plus the
# names `scheduler*.yaml` declares.  `DEFAULT_DEVICE` is what `lib/tests.py` calls
# "what tuxrun boots": it is in the list because it is this deployment's own
# machine, and a page that could not offer its own default would be a page that
# cannot reproduce the command it prints today.
PLATFORMS_FIXED = (DEFAULT_DEVICE,)
PLATFORMS_KNOWN = PLATFORMS_FIXED + tuple(one for one in _platforms_from_config()
                                          if one not in PLATFORMS_FIXED)
RUNTIMES_FIXED = (DEFAULT_LAB,)
RUNTIMES_KNOWN = RUNTIMES_FIXED + tuple(one for one in _runtimes_from_config()
                                        if one not in RUNTIMES_FIXED)


def _worker_platforms() -> tuple[str, ...]:
    """What `/worker` may be pointed at, and the only list `command()` accepts.

    **One list, two readers** (`pages/worker.py`'s quick links and
    `actions.py::command`'s `_offered`).  They have to be the same list: `_offered`
    *refuses* a value it was not offered (`error.not_an_option_n`), so a dropdown
    widened on one side only is a button whose Start answers 409.  The page reads
    the *same* list a second way - `_platform_refusal` below, which is built on this
    function - so a name the page prints is either a link this function accepts or a
    marked value with its reason.

    It is a **floor and not a cage**: the vendored config is 131 names today, and a
    name it does not carry is exactly that - a name this deployment has no lab block
    for.  `_offered` is the whitelist and not `_named` because a platform reaches
    `--platform` (`data.platform`) and the API answers a name nobody runs with `0`,
    which is the failure mode a whitelist exists to prevent.
    """
    return tuple(sorted(PLATFORMS_KNOWN))


def _worker_runtimes() -> tuple[str, ...]:
    """The same, for the lab the worker claims from (`--runtime`, `data.runtime`).

    Same floor, same reader on the page (`RUNTIMES_KNOWN` is the `type: pull_labs`
    runtimes `scheduler*.yaml` declares, by `name:`), and the reason it needs no
    `off` marking of its own is that a runtime is **only** a claim filter: it says
    which lab's queue to read (`Kjob.claimable(runtime)`, `poller.Poller.runtime`)
    and nothing about what runs.  A lab with no work is not a broken choice - the
    page counts what the pair would claim before the button is pressed
    (`worker.would_claim`) and `_claim_pairs` shows where the work is, so a wrong
    lab answers `nothing to claim` instead of failing.  A name this list does not
    carry is still refused (`_offered`), which is the only case `_runtime_refusal`
    below has anything to say about.
    """
    return tuple(sorted(RUNTIMES_KNOWN))


def _platform_refusal(platform: str, lang: str = DEFAULT_LANG) -> str:
    """Why `/worker` must not offer `platform` as a link - `""` when it may.

    `command()` accepts every name in `_worker_platforms()`, so a refusal here is
    never about the argv: it is about whether a job for that platform could be
    *run* here, which is now the pair (claim filter, the rest of the boot line -
    see the second bullet).  The page passes
    the answers to `_quick(off=…)` and `_action_bar(blocked=…)`, so a name it will
    not link is a name it still shows, with this sentence in `title=`.  Nothing
    here is silent and nothing here is a second list: both branches read
    `_worker_platforms()`.

    * **a name the vendored config does not carry**: nothing to say beyond that the
      worker would refuse it.  Read off the same table `_offered` uses, so this
      cannot drift from the refusal a hand-edited URL would meet;
    * **a platform a worker started from this page cannot boot**: the device is no
      longer the reason.  `runner.argv` boots `tests.device(definition, …)`, so a
      job whose definition names `qemu-x86_64` is booted with `--device
      qemu-x86_64`, and `sink` reports the same one - what boots and what is
      reported are one answer (`tests.device`).  What is still riscv64 is
      *everything else on that line*: `runner.CPU` is `rv64,v=true,ssnpm=true`, so
      the argv carries `--parameters cpu=rv64,…`, and `tests.ROOTFS_URL` is a
      `riscv64` rootfs image.  Booting an x86 `bzImage` with riscv cpu parameters
      and a riscv rootfs ends in an infra failure at the same place it always
      would.  Offering that as a button would be offering a run that can only end
      in an infra failure, which is the thing this page exists to stop doing.

      This bullet is the one that goes stale when someone makes the boot line
      follow the definition's arch as well - at that point the refusal itself, not
      just its wording, is what has to go.
    """
    if not platform or platform == DEFAULT_DEVICE:
        return ""
    if platform not in _worker_platforms():
        return t(lang, "worker.platform_unknown", platform=platform)
    return t(lang, "worker.platform_off", platform=platform)


def _runtime_refusal(runtime: str, lang: str = DEFAULT_LANG) -> str:
    """The same question for the lab box - `""` unless this list never heard of it.

    There is no second branch and that is the answer to "does the runtime need the
    same paired-validation treatment": the pairing (claim filter ↔ device) exists on
    the platform side only.  A runtime that *is* in the config is a lab, and a lab a
    worker cannot reach answers with an empty queue, not with a failed boot; a
    runtime the config does not declare is one `_offered` refuses, so the page must
    not link it, and this is that reason.
    """
    if not runtime or runtime in _worker_runtimes():
        return ""
    return t(lang, "worker.runtime_unknown", runtime=runtime)


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

# The four axes a reader may name **several values of at once**, offered as tick
# boxes rather than as one box (`fields._check_group`).  The set is a judgement with
# a reason and not a rule about `Filter`: these four are the axes whose values are
# *orthogonal to the row* - a build is in `riscv` or `mainline` and nothing about the
# page changes if both are asked for - while `branch` is bound to the tree it belongs
# to (`_branches_from_config`), `state`/`result` are two of a row's own answering
# words, and `test`/`ran`/`verdict`/`evidence`/`origin`/`missing` are questions about
# one row's ledger and artifacts, where "any of these" is either the same as "any" or
# a different question the page does not implement.
#
# **This is the one table that decides what may go on the wire as `__in`**, and it is
# read by `forms._axis_pairs` alone.  `Filter.accepts` needs no such list: its test is
# a membership test for every value axis, and `tree=riscv` is the one-value case of it
# (`_names("riscv")` is `("riscv",)`), so a single value filters exactly as it did.
MULTI_FIELDS = ("tree", "arch", "defconfig", "compiler")

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
    "/worker": ("state", "job", "text", "limit", "mode", "platform", "runtime", "since",
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
# second implementation of a verdict - the pill next to the label shows the same
# word on purpose.  `any` is shared, because "no condition at
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


# How many ended activities the panel keeps under the running ones.  A display cap
# like `ROWS`, and the same kind of number: it decides how much this page prints,
# never what happened.  Three is what fits above the fold on a 700px window.  It
# rides to the script as `LIVE_KEPT` (`_js`), so the panel the server drew and the
# one the poll rewrites cannot disagree about how much history a "live" panel keeps.
LIVE_KEPT = 3
