# SPDX-License-Identifier: LGPL-2.1-or-later
"""One test's record over the builds a page lists: the timeline, the lines, the wave, the rows.

Four renderings of the same ledger reads: `_timeline` is one block per run, oldest
first, with a regression (`pass` -> `fail`) ringed; `_trend_lines` is one line per
verdict class over the page's whole order, cumulatively, and it is **the tree's only
SVG**; `_wave_chart` is the same slots as a table of cells - the numbers `_trend_lines`
draws a shape of, reachable without a picture; `_trend_table` is one row per run with
its `+failed / −fixed` beside it.  `_record_block` is the run a timeline cell selected,
with every field its record holds - not the five that used to be in a `title=`.

Two of them are pictures of one order and neither replaces the other: a line is a shape
a table cell cannot draw (see the note above `_trend_lines`), and a cell is a number a
shape cannot print.  They are handed the same `_wave_slots`, so the sentence above them
and the two pictures under it cannot disagree about how many positions there are.

The machine readers are not here: `/api/analysis/trend` is `reports.trend`, and what
this module holds is only what a page prints."""

import html
import itertools
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from .. import errors
from ..i18n import DEFAULT_LANG, t
from .driftview import _cases_delta
from .models import Filter
from .pairs import _delta_cell
from .schema import _labels
from .urls import _url
from .widgets import _cell, _pill, _row, _table

if TYPE_CHECKING:
    from ..re import Records

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
    already exist (`/local/<id>`, which is where the bytes are, and `/runs/<id>/log`,
    which is the whole log - `text/plain`, in a tab of its own).

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

    **`gap` is `not found`, and it used to be `found is None`.**  `_last_verdict_row`
    answers `{}` for a position with no record - it never answers `None` - so that test
    was false at *every* position: `gap` was always `False`, every no-record slot was
    handed on as a run whose verdict happened to be the empty string, and the two things
    that read it were both wrong at once.  `_wave_chart` never drew a single dashed gap
    cell or linked to `/jobs` (its gap branch is dead under `gap == False`), and
    `chart.band_sub` - `{ran} with a record, {gap} with none`, counted from these same
    slots - printed `50 with a record, 0 with none` over an order where the ledger had
    19.  The empty string is what gave it away: `verdict` is `""` for exactly the
    positions `gap` claimed did not exist, and the new line chart counted 16 runs where
    the sentence above it claimed 50.  Found while building `_trend_lines`; the two
    readers are correct as written and this one line was the whole of it.
    """
    slots = []
    for at, row in enumerate(rows):
        build_id = str(row["build_id"])
        found = _last_verdict_row(records, test, build_id)
        slots.append({
            "at": at, "build_id": build_id, "record": found,
            "verdict": str(found.get("verdict") or "") if found else "",
            "gap": not found,
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


# --- the line chart (`_trend_lines`) ---------------------------------------
#
# **This is the tree's first SVG, and it is here because a table of cells cannot
# draw a line.**  Every other picture in `lib/gui` is a table: `_bar_chart` writes a
# width class (`w0`..`w20`) on a `<span>`, `_wave_chart` writes contiguous `.point`
# cells, and both are honest - a bar is one independent length per row and a strip is
# a grid of uniform rectangles, so a class per value is enough.  A *polyline* is
# neither: joining `(i, y_i)` to `(i+1, y_{i+1})` needs a segment with an arbitrary
# slope, and a table cell is an axis-aligned rectangle.  Encoding a slope in classes
# would need one class per (direction, offset) pair, and the rule this tree keeps -
# **widths are classes, never inline styles** - is what rules that out.  So the two
# verdict pictures are complementary and neither replaces the other: this one draws
# the shape of the order, `_wave_chart` under it keeps the per-position numbers
# reachable with no picture at all (`_wave_chart`'s cells are the table view this
# chart would otherwise be hiding behind a colour).
#
# The coordinates are SVG user units, and the stylesheet decides how wide the box is
# drawn (`min-width: 640px` so the axis text stays legible, `max-width: 1000px` so it
# does not grow without bound on a wide screen, `overflow-x: auto` on the wrapper so a
# narrow screen scrolls rather than folding the axis - the same trade `.wave-wrap`
# makes).  Nothing inside is scaled non-uniformly, so a marker is a circle at any
# width.  There is no `<text>`-in-`style`, no `<script>`, no `onclick`: the picture is
# server-rendered markup, which is why it is identical with JavaScript off, and no
# part of it reads anything - it is drawn from the `_wave_slots` the page already has.
_LINE_W = 640         # the viewBox' width
_LINE_H = 148         # the viewBox' height
_LINE_L = 34          # left margin: the y tick labels
_LINE_R = 14          # right margin: the last x tick label
_LINE_TOP = 12        # the top of the plot, where the largest value is drawn
_LINE_BASE = 122      # the x axis, where 0 is drawn
_LINE_RUG = 128       # the gap rug's top edge; below the axis, above the tick labels
_LINE_TICK = 142      # the x tick labels' baseline
_LINE_RUG_H = 5       # the rug marks' height
_LINE_TICKS = 16      # at most this many x tick labels, however long the order is
_LINE_MARKER = 2.5    # draw markers (and their per-point links) while a position is
                      # at least this many user units wide; below it they overlap into
                      # a smear and the line itself is the reading
_LINE_R_MARK = 2.6    # a marker's radius, and the emphasised one's
_LINE_R_ERROR = 3.6
_LINE_R_HIT = 7       # the transparent hit target around a marker

# The four series, in the order they are drawn: `pass` first and `error` last, so the
# emphasised line is painted on top of the others wherever they cross.  The words are
# `judge`'s own and the class the stylesheet colours; what a reader *reads* comes from
# `schema._LABELS["verdict"]`, which is the one place a verdict word becomes a
# sentence - a second table here would be the second verdict vocabulary, and the two
# would drift the first time one of them grew a word.
_LINES = (errors.VERDICT_PASS, errors.VERDICT_INFRA,
          errors.VERDICT_FAIL, errors.VERDICT_ERROR)


def _trend_lines(slots: list[dict[str, Any]], check: "Filter | None" = None,
                 keep: Iterable[tuple[str, str]] = (), point: str = "", test: str = "",
                 lang: str = DEFAULT_LANG) -> str:
    """One line per verdict class over the page's whole order, cumulatively.

    The operator asked for this and named the coordinate: 「回归分析它可能还要加一个图，
    一个图那个坐标就是排序的坐标，就类似直接可能要加一个图表，就那种折线图」.  So `x` is
    **the order above** and not time - the order is what the reader chose and it is what
    makes two neighbours comparable - and there is **one line per verdict**, because a
    single line cannot say *which* verdict is climbing.

    **`y` is a running count of the records this page is already displaying**, up to and
    including that position.  Nothing else is available: a build has at most one record
    for a test (`_wave_slots`), so a per-class value that is not accumulated is `0` or
    `1` at every position - four step functions, which is a rug and not a line.  The
    accumulation is over the *page's* positions, so it counts the rows this page put up
    and not the ledger's history: `Records.tally()` answers a different question (the
    whole ledger) and nobody here re-derives it (the page may count
    what it displays).  A class the order never saw gets no line at all, and its absence
    from the key row says so.

    A position with no record keeps every line flat, which on its own is ambiguous with
    "nothing changed".  The **gap rug** under the axis is what removes the ambiguity: the
    same dashed mark `_wave_chart` puts in a gap cell, one mark per position the ledger
    has nothing for, drawn as **one `<path>`** rather than one element each.

    Colour is not the only carrier.  `node scripts/validate_palette.js
    "#0f5132,#842029,#7a4b00,#6d2a86" --mode light` FAILS its CVD separation check on
    these four status inks (fail↔pass is ΔE 4.7 under deuteranopia, fail↔incomplete 11.1
    with full colour vision) - so each series also carries its own **dash pattern** and
    its own **marker size**, and the row of keys above the plot names every one of them
    in words (`chart.key`), with the final count beside it.  The palette is not the thing
    to fix: `--ok/bad/warn/err` are the verdict colours of every pill on every page, and
    a second verdict palette would be a second verdict.

    A marker is a link to the run it marks (`point` on this page, the same URL
    `_wave_chart`'s cells carry) with the record in its `title=` - so the picture is
    walkable with a keyboard and readable on hover, both with JavaScript off.  Below
    `_LINE_MARKER` user units per position the markers are not drawn: 4 000 links is not
    a chart, and the keys row and `_wave_chart` below still name every number.
    """
    if not slots:
        return ""
    n = len(slots)
    span = _LINE_W - _LINE_L - _LINE_R
    step = span / (n - 1) if n > 1 else 0.0

    def x_at(at: int) -> float:
        """Where position `at` sits: the order's own coordinate, left to right."""
        return _LINE_L + (at * step if n > 1 else span / 2)

    counts = dict.fromkeys(_LINES, 0)
    running: dict[str, list[int]] = {word: [] for word in _LINES}
    for slot in slots:
        word = "" if slot["gap"] else slot["verdict"]
        if word in counts:
            counts[word] += 1
        for name in _LINES:
            running[name].append(counts[name])
    top = max(counts.values(), default=0)

    def y_at(value: float) -> float:
        """Where a count sits: 0 on the axis, `top` against the top of the plot."""
        return _LINE_BASE - (value / top) * (_LINE_BASE - _LINE_TOP) if top else _LINE_BASE

    parts = [f"<title>{html.escape(t(lang, 'chart.lines_title'))}</title>",
             "<desc>" + html.escape(t(lang, "chart.lines_desc", n=n,
                                      gap=sum(1 for one in slots if one["gap"]),
                                      test=test)) + "</desc>"]
    # The frame: one gridline per labelled height, the axis, and the height's own name.
    # Recessive by construction - the stylesheet draws these in `--line`, the ink of a
    # rule, and keeps the verdict colours for the data.
    for level in sorted({0, top // 2, top}):
        at = y_at(level)
        parts.append(f'<line class="grid" x1="{_LINE_L:g}" y1="{at:g}" '
                     f'x2="{_LINE_W - _LINE_R:g}" y2="{at:g}"/>')
        parts.append(f'<text class="tick" x="{_LINE_L - 6:g}" y="{at + 3.5:g}" '
                     f'text-anchor="end">{level}</text>')
    parts.append(f'<text class="tick axis-name" x="{_LINE_L - 6:g}" y="{_LINE_TOP - 3:g}" '
                 f'text-anchor="end">{html.escape(t(lang, "chart.axis_y"))}</text>')
    parts.append(f'<line class="axis" x1="{_LINE_L:g}" y1="{_LINE_BASE:g}" '
                 f'x2="{_LINE_W - _LINE_R:g}" y2="{_LINE_BASE:g}"/>')
    # The x axis: a tick label every `stride` positions, so the axis is numbered without
    # 1 000 labels, and the first and last always - an axis whose ends are unlabelled
    # cannot be read at all.  `at + 1` is the number `_wave_chart`'s `#` lane prints.
    stride = max(1, -(-n // _LINE_TICKS))
    ticks = sorted({0, n - 1} | set(range(0, n, stride)))
    for at in ticks:
        here = x_at(at)
        parts.append(f'<line class="grid" x1="{here:g}" y1="{_LINE_TOP:g}" '
                     f'x2="{here:g}" y2="{_LINE_BASE:g}"/>')
        anchor = "start" if at == 0 else "end" if at == n - 1 else "middle"
        parts.append(f'<text class="tick" x="{here:g}" y="{_LINE_TICK:g}" '
                     f'text-anchor="{anchor}">{at + 1}</text>')
    rug = "".join(f"M{x_at(at):g},{_LINE_RUG:g} h{max(1.0, min(6.0, step * 0.8)):g} "
                  for at, one in enumerate(slots) if one["gap"])
    if rug:
        parts.append(f'<path class="rug" d="{rug.strip()}"/>')
    if top:
        for word in running:
            if not counts[word]:
                continue
            points = " ".join(f"{x_at(at):g},{y_at(running[word][at]):g}"
                              for at in range(n))
            parts.append(f'<polyline class="{html.escape(word)} line" points="{points}"/>')
    marked = n == 1 or step >= _LINE_MARKER
    for at, slot in enumerate(slots):
        if slot["gap"] or not top or not marked:
            continue
        word = slot["verdict"]
        if word not in counts:
            continue
        found = slot["record"]
        here = ' aria-current="true"' if point and slot["build_id"] == point else ""
        title = _point_title({"build_id": slot["build_id"],
                              "timestamp": found.get("timestamp"),
                              "verdict": found.get("verdict"),
                              "source": found.get("source"),
                              "exit_code": found.get("exit_code"),
                              "detail": found.get("detail")})
        radius = _LINE_R_ERROR if word == errors.VERDICT_ERROR else _LINE_R_MARK
        x, y = x_at(at), y_at(running[word][at])
        href = _url("/analysis", check, keep=keep, lang=lang,
                    point=slot["build_id"], test=test)
        parts.append(f'<a href="{html.escape(href)}"{here}>'
                     f'<circle class="hit" cx="{x:g}" cy="{y:g}" r="{_LINE_R_HIT}"/>'
                     f'<circle class="{html.escape(word)} marker" cx="{x:g}" cy="{y:g}" '
                     f'r="{radius}"/><title>{html.escape(title)}</title></a>')
    keys = "".join(
        f'<span class="k {html.escape(word)}"><span class="sw"></span>'
        + html.escape(t(lang, "chart.key",
                        verdict=_labels("verdict", lang).get(word, word),
                        n=counts[word]))
        + "</span>"
        for word in _LINES if counts[word])
    return (('<p class="lines-key">' + keys + "</p>" if keys else "")
            + f'<div class="lines-wrap"><svg class="trend-lines" '
              f'viewBox="0 0 {_LINE_W} {_LINE_H}">' + "".join(parts) + "</svg></div>"
            + ("" if top else
               '<p class="query">' + t(lang, "chart.lines_none", test=html.escape(test))
               + "</p>"))


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
    (`_runs_table(rows, empty, lang, rows_of, group, kinds)`, pages/runs.py:123) and a second
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
