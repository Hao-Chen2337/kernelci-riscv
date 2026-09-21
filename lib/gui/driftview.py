# SPDX-License-Identifier: LGPL-2.1-or-later
"""The config difference between two builds, whole, with each count said once.

`Drift` (`lib/drift.py`) answers with the options that changed between two `.config`
files; this module is how that answer reaches a page.  `_drift_block` is the whole
diff with its four numbers `+added −removed ~changed`, `_drift_row` is one option of
it, `_config_delta`/`_cases_delta` are the operator's own arithmetic, `_bar_chart` is
the same order as bars, and `_raw_configs` is the two files themselves as links to
open.  `_why_of` reads the *kind* of a refusal off the engine's own message instead of
inventing one, and `_pair_doors` is what the single-build page prints where the whole
diff used to be: the two doors, not a wall of text."""

import html
import re
from typing import TYPE_CHECKING, Any

from ..i18n import DEFAULT_LANG, t
from ..kbuild import SCAN
from .pairs import _compare_url

if TYPE_CHECKING:
    from .models import Filter

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
