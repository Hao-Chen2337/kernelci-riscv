#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ask a running GUI whether the operator's complaints are actually fixed.

    accept.py [--base http://127.0.0.1:8083] [--timeout 120] [--slow 1.5]

One line per complaint, in the operator's own numbering (`REQUIREMENTS.md`), with
the evidence that decided it.  Exit status is 0 only when every check passes, so
this is the gate for the rework: a page that renders but still prints
`activit(ies)` is not done.

Written against the *requirements*, not against a chosen implementation: a check
asks for the property the operator asked for ("a branch this page reads reaches
the API query"), never for a particular control or wording.  Where a requirement
is a matter of judgement the check is deliberately absent and the requirement is
listed at the end as one a human has to look at.
"""

import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# The words that were the operator's "垃圾文字注释".  A page that still prints one of
# these is a page that still explains itself instead of showing the data.
BANNED = (
    "is not evidence",
    "print cap",
    "fixed names",
    "cannot list branches",
    "the address this page really read",
    "written by Build.make()",
    "counted over the local rows above",
    "and the row cap decide",
    "older row(s) are outside",
    # Found on `/jobs` *after* the merge's W1 pass: a sentence that survived the prose
    # sweep and is now also FALSE, because `table.py run` skips what the ledger holds
    # as of this rework.  A page that tells the operator "this command runs even what
    # the ledger already has; the page adds no skip of its own" is describing a
    # behaviour that no longer exists - the worst kind of stale prose, and exactly
    # what step 4 is for.
    "the page adds no skip",
    "runs even what the ledger already has",
    # And three found on `/runs`, which the first pass did not cover because they are
    # not in `i18n.py` at all - they are section captions built in `gui.py`.  All three
    # are `05-i18n-prose.md` §B.1 class 1: they explain how the page works instead of
    # showing data, and the facts they carry (that an activity is a directory, that an
    # argv is a command line, that exit 1 is a verdict) belong in a `title=` or
    # nowhere.  The operator's words were "不要这种垃圾文字注释".
    "is the exact command an operator would type",
    "Every activity is a directory with",
    "that exit code is the answer, not a failure",
)

# The machine plurals.  `activit(ies)` and `cop(y|ies)` are not words in either
# language, and a Chinese page has no plural to mark at all.
# A machine plural: `row(s)`, `activit(ies)`, and the `(y|ies)` spelling.  Three
# exclusions, each of them a false positive this check produced before it had them:
# `http(s)` is a real word, `esc(s)` is *JavaScript's* parameter name (the shipped script
# defines `function esc(s)` and every page carries it), and a plural is always a word that
# starts with a letter - `(s)` alone is not one.
PLURALS = re.compile(r"\b(?!http|esc)[a-z]{3,}\(s\)|\b[a-z]{3,}\(y\|ies\)")

# A page may not cost a language.  This threshold is deliberately loose and this
# check is deliberately the *coarse* one: wall clock on this API varies ~3x minute to
# minute on its own, so `/worker` measured 3.37 s in English against 3.09 s in Chinese
# at best-of-three while a single unlucky pair reported a 2.8x "language" skew.  Tighten
# it and it fails on the weather.  The deterministic form of this question - *does one
# language make more API reads than the other?* - is
# `python3 tools/gate/smoke_pages.py --all --calls`, which counts the reads
# in-process and cannot be unlucky.  Measured there: 0/0, 2/2, 2/2, 4/4, 2/2.
LANG_RATIO = 3.5


class Page:
    """One fetched page: status, seconds, body, and the reader-visible text."""

    def __init__(self, base, path, lang, timeout, query=""):
        self.path, self.lang = path, lang
        self.query = query
        self.status, self.seconds, self.error = 0, 0.0, ""
        self.body = ""
        url = f"{base.rstrip('/')}{path}?lang={lang}" + (f"&{query}" if query else "")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as answer:
                self.body, self.status = answer.read().decode("utf-8", "replace"), answer.status
        except urllib.error.HTTPError as exc:
            self.body, self.status = exc.read().decode("utf-8", "replace"), exc.code
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        self.seconds = time.monotonic() - started

    @property
    def text(self) -> str:
        """The reader-visible words: tags stripped, entities decoded."""
        import html as html_mod
        body = re.sub(r"(?is)<(script|style|head)\b.*?</\1\s*>", " ", self.body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        return re.sub(r"\s+", " ", html_mod.unescape(body))


def _phrase_pattern(phrase: str) -> "re.Pattern":
    """A phrase as a pattern, with `{placeholder}` standing for whatever it rendered as.

    A catalogue string like `，所以有 {n} 行更旧的落在 {limit} 行上限之外` never appears
    literally on a page - the reader sees the substituted numbers - so a plain `in` test
    would silently never match it and the Chinese half of this check would pass by
    accident.  Every `{...}` therefore becomes "some characters", and the literal parts
    around it must still be there in order.
    """
    parts = [re.escape(one) for one in re.split(r"\{[^}]*\}", phrase)]
    return re.compile(".+?".join(parts), re.IGNORECASE | re.DOTALL)


def _banned() -> list[str]:
    """The banned English phrases plus the Chinese of every catalogue entry using one.

    Derived rather than hand-listed: `lib/i18n.py` already pairs `en` with `zh`, so the
    translation of a sentence we have decided not to print is a fact the catalogue
    knows.  A key whose `en` contains a banned phrase *is* prose, so its `zh` is prose
    too, and checking only English would let a half-done deletion stay on every Chinese
    page.  Falls back to the English list alone if the catalogue cannot be read, so the
    check never fails for the wrong reason.
    """
    phrases = list(BANNED)
    try:
        from lib import i18n
        for entry in getattr(i18n, "CATALOGUE", {}).values():
            english = str(entry.get("en") or "")
            chinese = str(entry.get("zh") or "")
            if chinese and len(chinese) > 12 and any(
                    one.lower() in english.lower() for one in BANNED):
                phrases.append(chinese)
    except (ImportError, AttributeError):
        pass            # the English list alone; a catalogue that cannot be read must
                        # not turn this check into a failure for the wrong reason
    return phrases


def _stored_text() -> list[str]:
    """Every `detail` string the ledger holds, for the plural check to exempt.

    Read straight from `var/results/*/*.json` rather than through `lib.re`, so this
    stays a check on what is *on disk* - the same thing the page is printing.
    """
    import json
    import os
    root = os.environ.get("KCI_WORK_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "var")
    found = []
    for where, _dirs, names in os.walk(os.path.join(root, "results")):
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(where, name), encoding="utf-8") as handle:
                    record = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("detail"):
                found.append(str(record["detail"]))
    return found


def _strip_chips(markup: str) -> list[tuple[str, int, str]]:
    """`(label, number, href)` for every chip in the numbers strip, href `""` if none.

    The strip is `<p class="numbers">` full of `<a class="chip">`/`<span class="chip">`;
    a chip's text is `<span class="k">label</span><b class="n">number</b>`.  Parsed
    loosely on purpose: what this check cares about is the *pair* (a number and where
    it points), not the markup around it.
    """
    import html as html_mod
    strip = re.search(r'(?s)<p class="numbers">(.*?)</p>', markup)
    if not strip:
        return []
    found = []
    for chip in re.finditer(r'(?s)<(a|span)[^>]*class="chip"[^>]*>(.*?)</\1>', strip.group(1)):
        inner = chip.group(2)
        href = re.search(r'href="([^"]*)"', chip.group(0))
        text = re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        number = re.search(r"(\d[\d,]*)\s*$", text)
        if number:
            label = text[:number.start()].strip()
            found.append((label or text, int(number.group(1).replace(",", "")),
                          html_mod.unescape(href.group(1)) if href else ""))
    return found


def _table_row_counts(markup: str) -> set[int]:
    """How many body rows each table on a page has, header excluded."""
    counts = set()
    for table in re.finditer(r"(?s)<table\b[^>]*>(.*?)</table>", markup):
        rows = len(re.findall(r"(?s)<tr", table.group(1)))
        counts.add(max(0, rows - 1))
    return counts


# One `±` cell's three numbers.  `ui.delta` writes them as added / removed / changed
# inside their own spans, and that is the only place the page says how far apart two
# builds are - so it is where a reader wanting to know which pair is worth opening has
# to look, and where this gate looks too.
_DELTA_CELL = re.compile(
    r'<span class="delta"><span class="plus">\+(\d+)</span>'
    r'<span class="minus">&minus;(\d+)</span><span class="same">~(\d+)</span></span>')


def _delta_total(cell: str) -> int:
    """`a + r + c` for one `±` cell, or 0 when the cell carries no number at all.

    A cell with no number is not a zero: it says "the first row in this order",
    "beyond the delta cap (n)", or names the engine's refusal as a door.  None of
    those is a difference there is anything to go and look at.
    """
    found = _DELTA_CELL.search(cell)
    return sum(int(one) for one in found.groups()) if found else 0


def _pick_rows(markup: str) -> list[tuple[str, int, int]]:
    """`(build_id, above, below)` per picks-table row, each cell read as its total.

    The pairing is the table's own order: the cell drawn *above* a build is its
    comparison with the row before it, and the cell *below* is its comparison with
    the row after - exactly how `analysis._edge_cell` fills them (`delta_up` from
    `picks[at - 1]`, `delta_down` from `picks[at + 1]`).  Read out of the document
    rather than rebuilt, because the ids are the row's own and the order is the page's.
    """
    table = re.search(r'(?s)<table[^>]*class="[^"]*picks[^"]*".*?</table>', markup)
    if not table:
        return []
    rows = []
    for row in re.findall(r"(?s)<tr\b.*?</tr>", table.group(0))[1:]:
        box = re.search(r'name="pick" value="([^"]+)"', row)
        cells = re.findall(r"(?s)<td\b.*?</td>", row)[-2:]
        if box and len(cells) == 2:
            rows.append((box.group(1), _delta_total(cells[0]), _delta_total(cells[1])))
    return rows


def _widest_pair(markup: str):
    """The pair this listing advertises as differing most: `(first, second, total, where)`.

    `None` when the listing advertises no difference at all - which is a fact about the
    instance and not a defect in the page, so the `X2` check says it rather than failing
    on it.  The two ids are in the table's order and *not* in the engine's oldest-first
    one: the order is the reader's sort, and this gate has no way to tell which end is
    which.  It does not need to - the comparison prints the same option names whichever
    way round it is asked, because a difference is symmetric even though its `+`/`−`
    signs are not (measured on both directions of the same pair).
    """
    rows = _pick_rows(markup)
    best = None
    for at, (build_id, above, below) in enumerate(rows):
        for other, total, side in ((at - 1, above, "above"), (at + 1, below, "below")):
            if not total or not 0 <= other < len(rows):
                continue
            if best is None or total > best[2]:
                first, second = ((rows[other][0], build_id) if other < at
                                 else (build_id, rows[other][0]))
                best = (first, second, total, f"row {at + 1}'s {side} `±` cell")
    return best


def check(results, name, ok, evidence):
    """Record one verdict; `evidence` is what a reader needs to believe it."""
    results.append((name, bool(ok), evidence))


def _orphan_build() -> str | None:
    """A build with a pull record on disk and no card in the table, or `None`.

    That pair is the state the operator complained about - "pulled and run, and the
    page still says nothing was pulled" - so it is the one to test for.  Reads the
    workspace the *server* would read: `$KCI_WORK_DIR` if set, else `var/` beside
    the repository, which is what `lib/layout.py` does.
    """
    import json
    import os
    root = os.environ.get("KCI_WORK_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "var")
    try:
        with open(os.path.join(root, "state", "builds.json"), encoding="utf-8") as handle:
            cards = json.load(handle)
    except (OSError, ValueError):
        return None
    downloads = os.path.join(root, "downloads")
    try:
        names = sorted(os.listdir(downloads))
    except OSError:
        return None
    for name in names:
        if name in cards:
            continue
        record = os.path.join(downloads, name, "provenance.json")
        try:
            with open(record, encoding="utf-8") as handle:
                found = json.load(handle)
        except (OSError, ValueError):
            continue
        if any(one.get("entries") for one in (found.get("acts") or [])
               if isinstance(one, dict)):
            return name
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8083")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--slow", type=float, default=1.5,
                        help="a WARM page slower than this is a failure")
    parser.add_argument("--budget", type=float, default=45.0,
                        help="a forced re-read (cold) must fit this, per the page's own API_BUDGET")
    args = parser.parse_args(argv)

    results = []
    pages = ["/", "/jobs", "/runs", "/worker", "/analysis"]
    read = {path: {lang: Page(args.base, path, lang, args.timeout)
                   for lang in ("en", "zh")} for path in pages}
    # The pages the operator complained about may legitimately be gone; fetch them
    # best-effort so a redirect (a 302 the urllib opener follows) still counts.
    legacy = {path: Page(args.base, path, "en", args.timeout)
              for path in ("/remote", "/local", "/pull")}

    # --- P1: the page is not slow ------------------------------------------
    #
    # Two halves, because only one of them is ours.  The public API costs 1.2-3.7 s
    # per call *returning nothing at all* and streams at 20-35 KB/s, so a page that
    # reads it cannot be under a second **cold** however it is written; what the
    # rework can promise is that a page nobody changed is not re-read, and that the
    # cold cost is bounded rather than unbounded.  So:
    #
    #   warm  - the second load of the same page: this is what the operator feels
    #           while working, and it must be quick on every page;
    #   cold  - the first load with `?fresh=1`: charged to the API, but it must fit
    #           the page's stated budget rather than run away.
    #
    # A single "every page under 1.5 s" check was measuring the API's mood and calling
    # it our bug, which is the same mistake the `P1b` note below records.
    #
    # `warm` is two **back-to-back** loads of the same page, and the second is the
    # measurement.  Fetching them as one batch instead measures nothing: the TTL is 5 s
    # and a sweep of the pages takes longer than that, so by the time the batch reached
    # each page its entry had expired and every "warm" load was cold again - which is a
    # property of the harness, not of the page.
    warm = {}
    for path in pages:
        Page(args.base, path, "en", args.timeout)                       # may be cold
        warm[path] = Page(args.base, path, "en", args.timeout)          # immediately again
    # A page that did not answer is not a fast page.  Measured the hard way: with the
    # server down, every request was refused in ~0.00 s and this check *passed* while
    # P1c reported ten connection errors - a check that rewards failure is worse than
    # no check, because it hides the failure it is standing next to.
    unreachable = [p for p in pages if warm[p].status != 200 or warm[p].error]
    slow = [(p, round(warm[p].seconds, 2)) for p in pages
            if p not in unreachable and warm[p].seconds > args.slow]
    # The timings are printed whether or not the check fails: a number that only shows
    # up on failure is a number nobody can compare from one run to the next.
    timed = ", ".join(f"{p} {warm[p].seconds:.2f}s"
                      for p in sorted(pages, key=lambda p: -warm[p].seconds))
    check(results, "P1 warm: an unchanged page is not re-read",
          not slow and not unreachable,
          f"did not answer: {unreachable}" if unreachable
          else f"over {args.slow:g}s: {slow}   (all: {timed})" if slow
          else f"every warm page under {args.slow:g}s: {timed}")

    over = [(p, round(fresh_load.seconds, 1)) for p, fresh_load in
            ((p, Page(args.base, p, "en", args.timeout, query="fresh=1")) for p in pages)
            if fresh_load.status != 200 or fresh_load.seconds > args.budget]
    check(results, f"P1 cold: a forced re-read fits the {args.budget:g}s budget",
          not over, f"over budget: {over}" if over else
          "every forced re-read answered inside the budget")

    # P1b: a language must not change the amount of work -- measured with `fresh=1`,
    # because otherwise the cache answers the *second* language from the first one's
    # read and the ratio measures the TTL rather than the page.  (It reported 0.01 s
    # against 5-10 s and called it a language problem; the page was fine and the
    # harness was wrong.)  Each language is therefore charged for its own API reads.
    # Two samples per language and the **minimum** of each, because a single cold
    # sample of this API varies ~3x minute to minute on its own: one slow draw was
    # enough to report a 2.7x "language" skew on `/` when the same page measured ~1.0x
    # either side of it.  The minimum is the closest thing to "what this page costs
    # when the API is being itself", and it is the right statistic for a check whose
    # question is whether one language does *more work* than the other.
    fresh = {p: {l: [Page(args.base, p, l, args.timeout, query="fresh=1")
                     for _ in range(2)] for l in ("en", "zh")} for p in pages}
    skewed = []
    for path in pages:
        took = {l: min(one.seconds for one in fresh[path][l]) for l in ("en", "zh")}
        fast = min(took.values()) or 1e-6
        if max(took.values()) / fast > LANG_RATIO and max(took.values()) > 0.5:
            skewed.append((path, round(max(took.values()) / fast, 1)))
    check(results, "P1b language does not change the cost", not skewed,
          f"en/zh skew {skewed} (best of two fresh loads each)" if skewed else
          f"ratio under {LANG_RATIO} on every page (best of two fresh loads each); "
          f"the deterministic check is `smoke_pages.py --all --calls`")

    # --- P1c: no page errors -----------------------------------------------
    bad = [(p, l, read[p][l].status, read[p][l].error)
           for p in pages for l in ("en", "zh")
           if read[p][l].status != 200 or read[p][l].error]
    check(results, "P1c every page answers 200", not bad, str(bad) if bad else "8/8 answers 200")

    # --- F1: branch reaches the query the page prints ----------------------
    home = read["/"]["en"]
    with_branch = Page(args.base, "/", "en", args.timeout, query="branch=for-next")
    check(results, "F1 a branch value reaches the page's query",
          "for-next" in with_branch.text,
          "`?branch=for-next` is named on the page" if "for-next" in with_branch.text
          else "the page never mentions for-next; it was dropped on the way in")

    # --- F5/F6: rows and days are typable, not only a row of buttons -------
    typable = re.findall(r'<input[^>]*name="(days|limit)"[^>]*>', home.body)
    check(results, "F5/F6 days and rows are typeable",
          {"days", "limit"} <= set(typable),
          f"inputs found: {sorted(set(typable))}" if typable
          else "no days/limit input; the values are a fixed row of buttons")

    # --- W1: the explanatory prose is gone ---------------------------------
    # Checked in **both** languages, and the Chinese half needs the Chinese words: the
    # prose lives in `lib/i18n.py` as `en`/`zh` pairs, so a sentence removed from `en`
    # and left in `zh` prints on every Chinese page - and a check holding only English
    # phrases would call that a pass while the operator, who reads Chinese, kept seeing
    # it.  `_banned()` therefore looks up the catalogue and adds the `zh` of every entry
    # whose `en` carries a phrase; the English list stays the source of truth, and the
    # translations are derived rather than maintained by hand.
    banned = _banned()
    found = {}
    for page in pages:
        for lang in ("en", "zh"):
            hits = sorted({one for one in banned
                           if _phrase_pattern(one).search(read[page][lang].text)})
            if hits:
                found[f"{page}[{lang}]"] = hits
    check(results, "W1 no explanatory prose on any page", not found,
          str(found) if found
          else f"{len(BANNED)} banned phrases and their translations, none present")

    # --- W1b: no Python symbol printed as a caption ------------------------
    # A symbol on screen is the same complaint in a different alphabet: the operator read
    # `新增 (616) 删除 (618)` as one broken string and `Records / todo() / transitions()` as
    # "奇怪的注释文字".  The **headings** are where it happened (`_h2`'s sub-line), and where
    # it must not come back - so this checks what a heading says, not what the page says,
    # because a *command line* is full of file names on purpose (`table.py pull --build …`
    # is printed under every button and is the whole point of `/`).
    #
    # `09-VERIFY.md`'s addendum found the flaw in the first draft of this check: a regex
    # for `name()` and `file.py` goes green on a bare `runday`.  So the symbol list is
    # explicit and small - the module names this program prints on purpose nowhere, and
    # the spellings a caption used before this round - and it is matched inside headings
    # only.  A new caption that names a module is a new entry here, which is the point:
    # the list is a decision, not a heuristic.
    symbols = re.compile(r"\b(runday|poller|judge|drift|records|Builds?)\.?\w*\(\)"
                         r"|\b\w+\.py\b|\bRecords\.[a-z_]+\(\)")
    captions = {}
    for page in pages:
        for lang in ("en", "zh"):
            for head in re.findall(r"<h2[^>]*>(.*?)</h2>", read[page][lang].body, re.DOTALL):
                words = html.unescape(re.sub(r"<[^>]+>", " ", head))
                hits = sorted(set(symbols.findall(words)))
                if hits:
                    captions.setdefault(f"{page}[{lang}]", []).append(
                        (re.sub(r"\s+", " ", words).strip()[:60], hits))
    check(results, "W1b no Python symbol in a heading", not captions,
          f"a heading prints a symbol: {captions}" if captions
          else "no heading names a module, a file or a function")

    # --- W3: no machine plurals -------------------------------------------
    # A machine plural that is a **record's own stored text** is not the page's
    # phrasing.  `Outcome.detail` is written by `lib/judge.py` at run time and printed
    # verbatim by the jobs page, so a ledger written before that file stopped saying
    # `selftest(s)` keeps saying it for ever - the ledger is history, and rewriting it
    # to look tidier would be a claim about runs nobody can re-observe.  Record text is
    # therefore exempt, and named in the evidence when it is the reason a page is clean.
    stored = _stored_text()
    plurals, exempt = {}, {}
    for page in pages:
        for lang in ("en", "zh"):
            # The **tooltips too**, not only the visible text.  A `title=` is this page's
            # own phrasing as much as a cell is - and the three that a round-2 tooltip
            # introduced (`outside window (cap …)`'s explanation, the coverage sentence,
            # a failed pull's act text) all live in `title=` attributes, where a
            # text-only scan cannot see them.
            haystack = read[page][lang].text + " " + " ".join(
                html.unescape(one) for one in re.findall(r'title="([^"]*)"', read[page][lang].body))
            hits = sorted(set(PLURALS.findall(haystack)))
            kept = []
            for one in hits:
                if any(one in text for text in stored):
                    exempt.setdefault(one, []).append(f"{page}[{lang}]")
                else:
                    kept.append(one)
            if kept:
                plurals[f"{page}[{lang}]"] = kept
    note = ("; " + ", ".join(f"{one} is a record's own text" for one in sorted(exempt))
            if exempt else "")
    check(results, "W3 no `(s)` / `(y|ies)` in the page's own words", not plurals,
          f"invented by the page (text and tooltips): {plurals}" if plurals
          else f"none invented by the page, text or tooltips{note}")

    # --- W2: the drift summary's parentheses balance ----------------------
    drift = Page(args.base, "/analysis", "en", args.timeout)
    bad_parens = []
    for chunk in re.findall(r"[^<>]{0,40}(?:added|removed|changed|新增|删除)[^<>]{0,40}",
                            drift.text):
        if chunk.count("(") != chunk.count(")"):
            bad_parens.append(chunk.strip())
    check(results, "W2 drift counts balance their parentheses", not bad_parens,
          str(bad_parens[:3]) if bad_parens else "every added/removed phrase is balanced")

    # --- X3: a regression-timeline cell can be chosen ----------------------
    check(results, "X3 timeline cells are selectable",
          bool(re.search(r"(timeline|trend)[^>]*>\s*<a\b", drift.body, re.IGNORECASE))
          or "timeline" in drift.body and "<a " in drift.body.split("timeline")[-1][:2000],
          "a timeline cell carries a link" if "<a " in drift.body else
          "timeline cells are plain <span>s: nothing to click")

    # --- R1: a live side panel exists --------------------------------------
    live = bool(re.search(r'(aside|class="[^"]*(live|panel|side)[^"]*")', home.body, re.IGNORECASE))
    check(results, "R1 a live activity panel exists", live,
          "the shell carries an aside/live panel" if live
          else "no aside or live-panel container in the shell")

    # --- S6: every number in the strip is a link that reproduces it --------
    # The operator's "这些数字得是真的", and the plan's rule for the strip: a chip is a
    # link to the rows it counted, so a number that a link cannot reproduce is a
    # number that is wrong.  Checked implementation-independently - the chip's number
    # must appear as the row count of **some** table on the page it points at, which
    # does not care what the chip, the table or the filter is called.
    chips = _strip_chips(home.body)
    bad_chips, checked, empties = [], 0, 0
    for label, number, href in chips:
        if not href or href.startswith("#"):
            continue                    # an anchor into this page: nothing to fetch
        target = href if href.startswith("http") else args.base.rstrip("/") + href
        # Fetched **twice**, because some of these numbers count a live quantity: the
        # activities chip counts `var/runs`, and any activity starting between the
        # strip's render and the target's fetch changes the answer by one.  A number
        # that matches on either read is a live count, not a broken link - and a number
        # that matches on neither (which is what `cards 52` and `records 7` do) is a
        # real inconsistency and still fails.
        counts, failure = set(), ""
        for _ in range(2):
            try:
                with urllib.request.urlopen(target, timeout=args.timeout) as answer:
                    counts |= _table_row_counts(answer.read().decode("utf-8", "replace"))
            except OSError as exc:
                failure = f"{href}: {exc}"
        checked += 1
        if failure and not counts:
            bad_chips.append((label, failure))
        elif number == 0 and not counts:
            # **A zero on an empty page is a count, not a broken link.**  The rows are
            # what a table is made of, so a page with nothing to show draws no `<table>`
            # at all: `counts` comes back empty and there is no row count for the chip's
            # 0 to match.  That is the truth on a fresh deployment - and after `prune`,
            # which is a state this tree is supposed to be able to be in - so it reads
            # as "0, and the page agrees", the same way a chip whose page draws an
            # empty table already did.
            #
            # Narrow on purpose, so nothing real is let through: only a **zero** chip
            # reads this way, and only when the page drew no table at all.  A chip
            # that says N > 0 is still compared below, and so is a 0 whose page does
            # have tables (`counts` is not empty then) - a page drawing rows under a
            # chip that says none is exactly the disagreement this check exists for.
            empties += 1
        elif number not in counts:
            bad_chips.append((label, f"{href} has no table with {number} rows"))
    # Said out loud, because "found a table with exactly its number" is not what
    # happened for those: there was no table to find.  A deployment that holds any
    # bytes at all has none of them (`empties` is 0 exactly when every zero chip found
    # a table, which is the only way this check ever passed before), so the line an
    # operator with data sees is the one it always was.
    followed = (f"{checked} chip link(s) followed, each found a table with exactly"
                " its number")
    if empties:
        followed += (f"; {empties} of them counted 0 and the page drew no table,"
                     " which is that count")
    check(results, "S6 every number chip reproduces its rows",
          not bad_chips and checked > 0,
          f"broken: {bad_chips}" if bad_chips else
          followed if checked else
          "no chip link to follow - the strip is not a set of links")

    # --- S1: the three old pages still answer ------------------------------
    dead = [p for p, one in legacy.items() if one.status not in (200, 301, 302)]
    check(results, "S1 /remote /local /pull still answer", not dead,
          str({p: legacy[p].status for p in dead}) if dead else
          " ".join(f"{p}→{one.status}" for p, one in legacy.items()))

    # --- N3: the language switch can come back to English ------------------
    # The bug was `_url` dropping the default language, so the link carried no
    # `?lang=` and the `kci_lang=zh` cookie won.  Tested through the cookie,
    # because that is the state a reader is actually in after switching once.
    zh = read["/"]["zh"]
    hrefs = re.findall(r'href="([^"]*)"[^>]*hreflang="en"', zh.body)
    back = None
    for href in hrefs:
        target = href if href.startswith("http") else args.base.rstrip("/") + href
        request = urllib.request.Request(target, headers={"Cookie": "kci_lang=zh"})
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as answer:
                back = Page.__new__(Page)
                back.body = answer.read().decode("utf-8", "replace")
                back.status = answer.status
        except OSError as exc:
            back = None
            hrefs = [f"{href} ({exc})"]
            break
    if back is None:
        check(results, "N3 the language switch returns to English", False,
              f"no hreflang=en link on the zh page ({hrefs or 'none'})")
    else:
        still_chinese = bool(re.search(r"[\u4e00-\u9fff]", back.body)) and \
            not re.search(r"(?i)<html[^>]*lang=[\"']en", back.body)
        check(results, "N3 the language switch returns to English", not still_chinese,
              "the cookie-carrying English link answers in English" if not still_chinese
              else "followed the English link with kci_lang=zh set and got Chinese back")

    # --- X2: the drift comparison shows the detail, not just the counts ----
    # The summary is three numbers; a reader who wants detail needs the option
    # names themselves.
    #
    # **The pair is discovered, not named.**  This check used to carry two node ids
    # measured where it was written (`6aa3689720239ade90209d50` /
    # `6aac1402fc1857a999e11514`, 616/618/99 names) and ask for those.  That quietly
    # made it a check on *that database*: a deployment holding neither id - every
    # fresh one, this tree's own `deploy/` recipe among them - was told FAIL for
    # "asked for a pair you do not have", which is not a defect in the page.  The
    # comment above it claimed a skip there, and the harness has no way to make one
    # (`check()` writes PASS or FAIL and nothing else).
    #
    # What the *capability* needs is two builds that differ by something, and the
    # listing already says which pairs do: every `±` cell prints `+a −r ~c`, so the
    # widest pair on this instance is in a page this gate had already fetched.  So the
    # check takes that pair and asks the page to print exactly the names it promised -
    # a stronger reading of the same requirement than "at least fifty", and one that
    # holds at any scale instead of only on a database with hundreds of differences.
    # Measured here (widest pair `~1`): every advertised `+a −r ~c` prints `a + r + c`
    # distinct `CONFIG_` names, 4 of 4 pairs.
    #
    # **Round 2 moved the detail one click away, on purpose.**  Printing 265 KB of
    # `CONFIG_` names inline - 67 % of `/analysis` - under a page whose question is
    # *which builds* is what `就不用列一大串了` asked to have removed, so the list now
    # carries the counts and a link into `/analysis/<id>?vs=<other>`, and the whole
    # comparison is printed there.  The capability is unchanged; the check follows
    # the link, because a check that insisted on the old placement would be testing
    # the layout rather than the requirement.
    widest = _widest_pair(read["/analysis"]["en"].body)
    # The doors the page draws for its config list (`table.picks`): a door appears on a
    # row whose pair the engine put **no number** beside - past the delta cap, or refused
    # - so for those rows the door is the only way to the comparison at all, and it has
    # to open.  A door names its pair in the query (`?vs=...`), which is what tells it
    # apart from the row's own `/analysis/<id>` link: the earlier version of this check
    # counted those plain links as doors and so "found" three where this page draws none.
    # Following an arbitrary row's door and demanding names would be wrong - neighbours
    # in a list are usually *similar*, and the page is honest about that (`+0 −0 ~0` is
    # the true answer for most adjacent pairs), which is why only the count above is
    # compared against a number.
    table = re.search(r'(?s)<table[^>]*class="[^"]*picks[^"]*".*?</table>',
                      read["/analysis"]["en"].body)
    doors = [html.unescape(one) for one in
             re.findall(r'href="(/analysis/[^"]*\?[^"]*)"', table.group(0))] if table else []
    door_ok, door_note = True, ""
    if doors:
        path, _, query = doors[0].partition("?")
        opened = Page(args.base, path, "en", args.timeout, query=query.split("#")[0])
        if opened.status == 200:
            door_note = f"; the door {doors[0]} opens ({opened.status})"
        else:
            door_ok = False
            door_note = (f"; the door {doors[0]} answered"
                         f" {opened.status or opened.error}")
    if widest is None:
        # Nothing to open, and that is a fact about this instance rather than a fault in
        # the page: with no pair differing by anything there is no detail to show.  Said
        # out loud, because "no pair differs" and "the names did not print" would
        # otherwise read the same from a green line.
        held = len(_pick_rows(read["/analysis"]["en"].body))
        check(results, "X2 drift shows the changed options", door_ok,
              f"no pair in the picks table differs, so this instance has no comparison"
              f" to open ({held} build(s) listed){door_note}")
    else:
        first, second, want, where = widest
        shown = Page(args.base, "/analysis/" + first, "en", args.timeout,
                     query=f"vs={second}")
        names = sorted(set(re.findall(r"CONFIG_[A-Z0-9_]+", shown.body)))
        check(results, "X2 drift shows the changed options", len(names) == want and door_ok,
              f"{len(names)} CONFIG_ name(s) on /analysis/{first[:12]}?vs={second[:12]}, "
              f"which is the {want} the {where} advertises"
              + (f" ({', '.join(names[:4])}{', ...' if len(names) > 4 else ''})"
                 if names else "")
              + ("" if len(names) == want else
                 f" - the page's own `±` says {want}, its detail printed {len(names)}")
              + door_note)

    # --- S7: a build with bytes must not read as "no card" -----------------
    # Two halves own this: a pull must register its card (so no new orphans), and
    # the page must render an existing orphan honestly from its pull record rather
    # than saying "no card" beside 30 MiB of bytes.  Tested on the page that lists
    # local copies, and *around the orphan's own row* - a bare "the phrase is absent
    # from the page" would pass vacuously, because the orphan is usually outside the
    # API window and therefore not on the landing page at all.
    orphan = _orphan_build()
    if orphan is None:
        check(results, "S7 a pulled build is not card-less", True,
              "no build on disk has a pull record without a card")
    else:
        listing = Page(args.base, "/local", "en", args.timeout)
        if listing.status not in (200, 301, 302):
            listing = home
        where = listing.body.find(orphan[:16])
        window = listing.body[max(0, where - 200):where + 1500] if where >= 0 else ""
        on_page = where >= 0
        said = "no card in the local table" in window
        check(results, "S7 a pulled build is not card-less", on_page and not said,
              f"{orphan[:16]} has a pull record on disk; " +
              ("not on the local listing page at all" if not on_page else
               "its row still says `no card in the local table`" if said else
               "its row is rendered from the pull record"))

    # --- what a human still has to judge ----------------------------------
    eyes = ("S5 overview vs local has a distinct identity; S6 the counts read as data",
            "X4 select → sort → adjacent delta → horizontal chart",
            "X2 the drift detail can be opened in full",
            "A3 run skips what the ledger already has (a `no skip` badge, not a sentence)",
            "A6 every activity's log opens, with JavaScript off too",
            "R2 a finished run announces itself",
            "R4 the page looks deliberate rather than plain")

    width = max(len(name) for name, _, _ in results)
    print(f"# {args.base}   ({args.timeout:g}s timeout, {args.slow:g}s budget)")
    for name, ok, evidence in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {evidence}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("failed: " + "; ".join(failed))
    print("\nby eye, not by this script:")
    for one in eyes:
        print(f"  - {one}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
