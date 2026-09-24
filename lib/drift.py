# SPDX-License-Identifier: LGPL-2.1-or-later
"""Kernel config drift between two builds.

Draft this file is built from (``lib/drift``)::

    (empty - the config drift reader)

Read-only, and the only tool here that fetches a *text* artifact (a `.config`)
rather than bytes to run.  Two configs of the same job, parsed to option ->
value, then three lists: added, removed, changed.

A config is read from wherever this workspace already has it - the kept copy under
`var/configs/`, else the copy a pull left under `var/downloads/<build-id>/` - and
only then from the artifact store (`_config_text` says which, and in what order).

An empty parse is an ERROR: an HTML index page also parses to no options, and
"no drift" must never be the answer to a download that failed.

Exit status is the answer: 0 no drift, 1 drift - a caller can gate on it.

接口形状（C++，只有声明）：include/kci/view.hpp §18 config 漂移。
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import ClassVar

from . import api as api_mod
from . import atomic
from .build import Build
from .build.model import config_note, config_path
from .errors import ConfigError, KciError
from .kbuild import PASSED_FILTER, Kbuilds


@dataclass
class Drift:
    """Two builds' configs and what differs between them."""

    older: object = None
    newer: object = None
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)

    # The two newest builds this job *finished and passed* are what a
    # toolchain-bump comparison wants, and that filter lives with the API reads
    # (`lib/kbuild.py: PASSED_FILTER`) because provisioning wants the same one -
    # one spelling, two callers.  The old `./run.sh drift` tool sent it too
    # (`config_drift.py`: `list_nodes(job, kind="kbuild", state="done", result="pass")`).
    PASSED: ClassVar[dict] = PASSED_FILTER

    @classmethod
    def between(cls, api, job="", older=None, newer=None, catalogue=None):
        """Compare two builds of one job: by build id, else the newest two passing.

        `catalogue` is a `Kbuilds` the caller has already read.  A page that just
        listed these two builds has them in hand, and handing them over is the
        difference between one read and two scans of the whole window (`get()`
        cannot ask the API for an id - see `lib/kbuild.py: SCAN`).

        **`job` is the storage prefix, never a tree.**  It names this deployment's
        directory (`_config_url`: `<storage>/<job>-<node id>/.config`).  It used to
        be handed to `getdays()` as the *tree* on the no-ids path, so
        `--job kbuild-gcc-14-riscv` asked the production API for a tree of that name,
        was told `total=0`, and ended in a `ConfigError` traceback - which is why
        `python3 drift.py` could not be repointed at this reader.  Nothing on a page
        ever hit it: `gui` always passes the two ids it just listed.  The no-ids
        read asks for the job's whole history with `state=done`/`result=pass`
        (`_fetch` pins `name` to the job itself), so it is the old tool's selection
        with the new tree's one reader.
        """
        catalogue = catalogue if catalogue is not None else Kbuilds(api)
        if not (older and newer):
            recent = catalogue.getdays("", 0, extra=cls.PASSED)
            if len(recent) < 2:
                raise ConfigError(
                    "need two builds to compare; this job has "
                    f"{len(recent)} finished and passing")
            # Ids, not the objects: the two lines below resolve them through
            # `catalogue.get()`, which is the one place a build id becomes a build -
            # and both are already in `catalogue.items` (`getdays` kept them), so
            # that lookup costs no second read.
            newer, older = recent[0].build_id, recent[1].build_id
        older_build, newer_build = catalogue.get(older), catalogue.get(newer)
        older_url = _config_url(older_build, job)
        newer_url = _config_url(newer_build, job)
        left = parse(_config_text(api, older_url, _config_local(older_build)))
        right = parse(_config_text(api, newer_url, _config_local(newer_build)))
        _refuse_empty(left, older_url)
        _refuse_empty(right, newer_url)
        added, removed, changed = diff(left, right)
        return cls(older=older, newer=newer, added=added, removed=removed, changed=changed)

    @classmethod
    def series(cls, api, builds, job="", catalogue=None):
        """Adjacent comparisons of `builds`, one per neighbour pair, in the order given.

        The order is the caller's answer to "what is compared with what" - on
        `/analysis` it is the reader's sort - and that is the whole reason this
        exists: a list of N builds has N-1 adjacent comparisons, and asking
        `between()` for each one reads every build's config twice.

        **Built for clarity, not for speed.**  `06-analysis.md` §P13 proposed it to
        share one fetch and parse per build, and the coordinator measured the parse at
        2.4-2.6 ms for a 192-194 KB config, so a four-row delta column costs 12.4 ms
        the naive way and 6.1 ms this way: 6 ms is not a reason to add a method.  What
        is a reason is that "one config read per build, N-1 comparisons" is a sentence
        a reader can check, where two reads per pair has to be argued about - and after
        the disk cache (`_config_text`) the *fetch* is free anyway, so the remaining
        difference is that sentence.

        Returns `[(older_build, newer_build, Drift | KciError)]` in the same order, so
        a pair that cannot be compared keeps its place in the list with the engine's own
        reason (`这个为什么比不了` must be answerable per row, and a silently dropped row
        is the one answer that is never honest).

        Each pair is directed **oldest build first**, whatever order the list is in:
        `added`/`removed` are directional, and `+616` has to mean the same thing on
        every row - "the newer of these two has 616 options the older one has not" -
        rather than flipping meaning with the sort.  A build with no `created` (or two
        with the same one) keeps the order they were given in.
        """
        catalogue = catalogue if catalogue is not None else Kbuilds(api)
        parsed: dict[str, dict] = {}

        def one(build):
            known = catalogue.get(build.build_id)
            url = _config_url(known, job)
            if url not in parsed:
                options = parse(_config_text(api, url, _config_local(known)))
                _refuse_empty(options, url)
                parsed[url] = options
            return parsed[url]

        out = []
        for first, second in zip(list(builds), list(builds)[1:]):
            older, newer = _ordered(first, second)
            try:
                added, removed, changed = diff(one(older), one(newer))
                out.append((older, newer,
                            cls(older=older.build_id, newer=newer.build_id,
                                added=added, removed=removed, changed=changed)))
            except KciError as exc:            # ConfigError | ApiError, errors.py:28-40
                out.append((older, newer, exc))
        return out

    @classmethod
    def from_files(cls, older_path, newer_path):
        """Compare two local `.config` files (what `--older-config` means)."""
        left_text = _read(older_path)
        right_text = _read(newer_path)
        left, right = parse(left_text), parse(right_text)
        _refuse_empty(left, older_path)
        _refuse_empty(right, newer_path)
        added, removed, changed = diff(left, right)
        return cls(older=older_path, newer=newer_path,
                   added=added, removed=removed, changed=changed)

    def drifted(self):
        """Did anything change at all?"""
        return bool(self.added or self.removed or self.changed)

    def print(self, stream=None, max_lines=0):
        """The text report; `max_lines` truncates each list and says how many it hid."""
        for line in self.lines(max_lines):
            print(line, file=stream)

    def lines(self, max_lines=0):
        """The report as lines, so a caller can print or ship them."""
        out = [f"older: {_name(self.older)}", f"newer: {_name(self.newer)}"]
        if not self.drifted():
            out.append("no drift: the two configs hold the same options")
            return out
        for label, rows in (("added", self.added), ("removed", self.removed),
                            ("changed", self.changed)):
            out.append(f"--- {label} ({len(rows)})")
            shown = rows if not max_lines else rows[:max_lines]
            for row in shown:
                out.append("  " + "  ".join(str(part) for part in row))
            if max_lines and len(rows) > max_lines:
                out.append(f"  ... {len(rows) - max_lines} more")
        return out

    def json(self):
        """The same report as data, for a page or another tool."""
        import json
        return json.dumps({"older": _name(self.older), "newer": _name(self.newer),
                           "drifted": self.drifted(), "added": self.added,
                           "removed": self.removed, "changed": self.changed,
                           "summary": {"added": len(self.added),
                                       "removed": len(self.removed),
                                       "changed": len(self.changed)}},
                          indent=1, sort_keys=True)


def _ordered(first, second):
    """Two builds as `(older, newer)`, by `created` where the two can be told apart.

    `created` is the API's own timestamp and is a string on both sides
    (`Kbuild.created`, `Outcome.timestamp`), so comparing them is comparing them as
    written - which is what every other reader in this tree does (`records.series`).
    An empty or equal pair keeps the order it was handed in: a caller that knows the
    order (a reversed timeline, a list built oldest first) must not be second-guessed
    by a missing field.
    """
    older, newer = first, second
    first_at = str(getattr(first, "created", "") or "")
    second_at = str(getattr(second, "created", "") or "")
    if first_at and second_at and first_at > second_at:
        older, newer = second, first
    return older, newer


def parse(text):
    """A kernel `.config` as `{option: value}`.

    `CONFIG_X=y` maps to the value after `=`, `# CONFIG_X is not set` to `n`
    even with trailing text; comments and blanks are ignored, and an inline
    comment is dropped unless its `#` sits inside quotes - a quoted cmdline or
    path keeps its `#`.
    """
    options = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            options[key] = _drop_comment(value)
        elif line.startswith("# CONFIG_") and " is not set" in line:
            options[line[2:].split(" is not set", 1)[0].strip()] = "n"
    return options


def diff(older, newer):
    """`(added, removed, changed)` going from `older` to `newer`, each sorted."""
    added, removed, changed = [], [], []
    for key in sorted(set(older) | set(newer)):
        if key not in older:
            added.append((key, newer[key]))
        elif key not in newer:
            removed.append((key, older[key]))
        elif older[key] != newer[key]:
            changed.append((key, older[key], newer[key]))
    return added, removed, changed


def _drop_comment(value):
    """Cut a value at the first `#` outside double quotes; escaped quotes stay inside."""
    kept, quoted, escaped = [], False, False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted:
            break
        kept.append(char)
    return "".join(kept).strip()


def _config_url(kbuild, job):
    """Where a build's config lives: its own artifact, else this deployment's storage.

    The definition is `Build.config_url` (`lib/build/model.py`), because a page's
    config mark asks the same question and two answers to "which URL is this
    build's config" is a mark that disagrees with the fetch it predicts.  The
    storage environment variable and its default moved with it, so this module no
    longer names either.
    """
    return Build(kbuild).config_url(job)


def _config_path(url):
    """Where one URL's `.config` is kept between downloads: `model.config_path`.

    A wrapper, and only for the name: the digest itself is the build half's, since
    `Build.config_cache` looks a kept copy up by it.
    """
    return config_path(url)


def _config_note(url):
    """The sidecar that says what the kept file is supposed to be (`model.config_note`).

    What the note *contains* - the URL, the byte count, the sha256 - and why a
    checksum is the whole point of it are stated where the note is defined and
    where it is checked (`_kept_config`); this only says where it sits.
    """
    return config_note(url)


def _kept_config(url):
    """The cached text for `url`, or `None` when there is none that can be trusted."""
    path = _config_note(url)
    try:
        with open(path, encoding="utf-8") as handle:
            note = json.load(handle)
        with open(_config_path(url), encoding="utf-8", errors="replace") as handle:
            kept = handle.read()
    except (OSError, ValueError):
        return None
    if not isinstance(note, dict) or not kept:
        return None
    raw = kept.encode("utf-8")
    if note.get("bytes") != len(raw) or note.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ConfigError(
            f"the kept copy of {url} in {_config_path(url)} does not match its record "
            f"({len(raw)} bytes now, {note.get('bytes')} when it was kept): refusing to "
            f"compare against it - delete it to download the config again")
    return kept


def _already_kept(url, raw, note):
    """Is `var/configs/` already holding exactly `raw` for `url`, under exactly `note`?"""
    try:
        with open(_config_path(url), "rb") as handle:
            kept = handle.read()
        with open(_config_note(url), encoding="utf-8") as handle:
            kept_note = json.load(handle)
    except (OSError, ValueError):
        return False
    return kept == raw and kept_note == note


def _keep_config(url, text):
    """Keep `text` as the copy of `url`, with the note that makes it checkable.

    **An identical copy is not written again.**  The bytes are compared first, and
    a file the workspace already holds is left completely alone - no temporary
    file, no `os.replace`, and so no new mtime.  That matters because "read a page
    and write nothing" is a promise this tree makes out loud, and a rewrite that
    changes no byte still breaks it: a page render that re-downloads a `.config`
    whose content is unchanged used to restamp every file it touched, which is
    indistinguishable from a real update to anyone watching the workspace (`find
    var -newermt ...`, a backup, an rsync) - the bytes and the sha256 stayed the
    same, so nothing on screen could tell the reader it had happened.

    The **note** is compared too, and not only the `.config`: a sidecar that
    disagrees with the file beside it is what `_kept_config` refuses on the next
    request, so leaving one in place would trade a needless rewrite now for a
    refused read later.

    Content that really changed is still written - that is the cache update this
    function exists for - and so is a damaged or deleted copy: a `.config` edited
    by hand matches neither `raw` nor its note and is repaired here, which is what
    `_kept_config`'s own refusal points at ("delete it to download the config
    again") and what `?fresh=1` asks for.
    """
    raw = text.encode("utf-8")
    note = {"url": url, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if _already_kept(url, raw, note):
        return
    for path, body in ((_config_path(url), text), (_config_note(url), json.dumps(note))):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic.write_text(path, body)
        except OSError:
            return                      # a cache that cannot be written is not a failure


def _config_local(kbuild):
    """The `.config` a pull of this build already left here, or `""` when there is none.

    A config is one of the artifacts a pull fetches (`ARTIFACTS["config"]`,
    `lib/build/model.py`), so a build this deployment has already downloaded has
    its config on disk - and until this function existed a comparison of it asked
    the artifact store for bytes this workspace was already holding.  `present()`
    is the downloader's own answer to "which of this build's artifacts are here",
    so the file's name and its directory are asked of the owner rather than spelled
    again here.

    **The copy has to have been proven whole to be on disk at all**:
    `fetch.download` publishes an artifact only when it is complete, writing to
    `<dest>.part` until then, so what this returns is not a half-written file.
    """
    return Build(kbuild).present().get("config", "")


def _local_config(path):
    """A pulled build's `.config` as text, or `""` when it is not one.

    Never an error, unlike `_read`: a copy that cannot be opened, or that holds
    something other than a kernel config, is simply *not an answer* - the read
    below it is the one that answers.  Raising here would fail a comparison of two
    builds whose configs the artifact store still has, over a damaged file in the
    download tree that the reader never asked about.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    return text if parse(text) else ""


def _config_text(api, url, local=""):
    """One `.config` as text: the kept copy, else this build's own pulled copy, else fetched.

    Why this exists at all: `Drift.between` used to call `api.text(url)` on every
    render, so each look at the analysis page re-downloaded both configs over the
    internet - measured at 8-12s and ~194KB each, ~18s of that page's ~43s, spent
    again on every single load including a reload of a page nobody had changed.

    Three places, in this order, and each one is cheaper than the one after it:

    * **`var/configs/`** - what an earlier comparison of this URL already fetched,
      checked against the note that was written with it.  This is the copy the
      whole cache exists for: a reader who compares the same builds twice pays for
      it once.
    * **`var/downloads/<build-id>/.config`** (`local`, `_config_local`) - a build
      that was *pulled*, whose config therefore came down with it.  It is seeded
      into `var/configs/` as it is read, so it is paid for once too, and a pull
      followed by a comparison is one download rather than two.  This is the step
      the engine was missing: the bytes were on disk and it went to the network
      anyway.
    * **the URL** - `api.text`, counted (`api.note_fetch`) because this is the read
      the reader pays for, and the page says how many of them a render made.

    A config is a pure function of its URL, so caching one is not a claim about
    the world that can go stale in a way a reader would act on differently; and
    the page states which build it compared, which is the fact that matters.

    **A request that asked for freshness gets it.**  `?fresh=1` and `?ttl=0`
    (`api.request_ttl`) mean "do not hand me an answer read earlier", and the
    operator asked for that in as many words ("我刷新一次界面起码我运行时候能够在外
    重新读文件").  A disk cache that ignored the control would be the same lie the
    in-process one is forbidden to tell, so the fetch happens and the cache is
    refreshed from it rather than merely bypassed - and refreshed *only* when the
    bytes differ, so a fresh read of an unchanged config leaves the kept copy, and
    its mtime, exactly where they were (`_keep_config`).

    It does **not** skip the pulled copy, and it is not meant to: `?fresh=1` asks
    for a page whose files were re-read and whose API answers were asked for again,
    and a `.config` sitting in `var/downloads/` is one of *this workspace's* files -
    reading it is the "re-read the files" half, and a config is a pure function of
    its build, so the URL has nothing newer to say about those bytes.

    Two things are **not** kept: a failure, and anything that fails its check.
    An HTTP error page parses to no options and `_refuse_empty` calls that "not a
    kernel config", so keeping it would turn one bad download into a permanent
    one; a truncated body would parse into a *wrong* answer, which is worse, and
    `_kept_config` is what catches it.  Only text that parses is written, which is
    also why the write is here and not in `Api`.
    """
    if api_mod.request_ttl() > 0:
        kept = _kept_config(url)
        if kept is not None and parse(kept):
            return kept

    if local:
        pulled = _local_config(local)
        if pulled:
            _keep_config(url, pulled)
            return pulled

    api_mod.note_fetch()
    text = api.text(url)
    if not parse(text):
        return text                 # let `_refuse_empty` say so, and keep nothing
    _keep_config(url, text)
    return text


def _refuse_empty(options, where):
    """An empty parse is a failed read, never "no drift"."""
    if not options:
        raise ConfigError(f"no CONFIG_ options in {where}: that is not a kernel config "
                          "(an HTML index page parses to nothing too)")


def _read(path):
    """One local `.config` as text; a path this cannot open is an INFRA failure.

    **A `ConfigError`, not the `OSError`.**  `drift.py`'s `main()` answers a
    `KciError` with one `X ...` line and that error's own exit status (3, infra);
    an `OSError` it does not catch escapes as a traceback and the interpreter's
    exit 1 - and 1 is this tool's *answer*, "the two configs differ".  So a
    misspelled `--newer-config`, a `chmod 000` file or a directory handed to
    `--older-config` was reported as a detected configuration regression, which
    is the one false positive a caller gating on the exit status can act on; with
    `--json` the traceback also went to stdout, where the caller was reading JSON.

    The error is wrapped rather than caught and turned into "no drift" for the
    same reason `_refuse_empty` exists: a read that did not happen must never be
    an answer about the configs.  Naming the file and keeping the OS's own reason
    is `sink.py:488`'s spelling of the same repair.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as error:
        raise ConfigError(f"config {path} is unreadable: {error}") from error


def _name(one):
    """A build id, a Kbuild, or a path, as one label."""
    if one is None:
        return "-"
    if isinstance(one, str):
        return one
    return getattr(one, "build_id", None) or str(one)
