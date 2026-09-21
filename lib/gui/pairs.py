# SPDX-License-Identifier: LGPL-2.1-or-later
"""Which two builds are compared, and what makes the two comparable.

`_chosen_pair` reads the pair out of the URL or picks one off the page's own order -
adjacent rows of the same branch, which is the comparison `06-analysis.md` §A7
measured to be worth making (two branches of one tree drift 363/538/92; adjacent
builds of one branch drift 0/0/0) - `_other_side` is what a click on the other door of
that pair should name, `_delta_cell` is one row's `±` against its neighbours **in the
order this list is in**, and `_compare_url` is the detail URL for one comparison.

`_build_ref`, `_ref_of`, `_found` and `_artifact_of` name a build the way a reader
does (`tree/branch · describe`), which is what lets a URL or a comparison name one."""

import html
import urllib.parse
from typing import TYPE_CHECKING, Any

from ..i18n import DEFAULT_LANG, t
from .urls import _url
from .values import _short

if TYPE_CHECKING:
    from ..kbuild import Kbuild, Kbuilds
    from .models import Filter

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
      500-row order readable without paying for 499 config reads.  Those links are
      doors, not labels: each one opens the pair's whole diff, and the column's own
      label (`col.delta_sub`) is where that is said - once for the column, never once
      per row (`marker`).
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
        """A neighbour whose comparison was not made: its id, as the door to running it.

        **The door is the discoverability** (`08-PLAN.md`'s on-click finding): a row past
        the cap has no `+n −n ~n`, and there is nothing on the page that says the click
        that would have produced one is still available.  It is: `_compare_url` lands on
        `/analysis/<id>?vs=<id>`, which prints the pair's **whole** diff (every changed
        option, in `<details>`, no JavaScript and no second read - the pair's two configs
        are already in hand).  So the cap is stated per cell in the `title=`
        (`delta.beyond`, with the cap in force), and the column's own label says it once
        for the whole list (`col.delta_sub`) - one sentence per column rather than one
        per row, because 47 rows of the same sentence is a wall, not a hint.
        """
        if rows is None or check is None or not (0 <= other_index < len(rows)):
            return f'<span class="none">{text}</span>'
        there = str(rows[other_index].get("build_id") or "")
        if not there:
            return f'<span class="none">{text}</span>'
        why = t(lang, "delta.door_title", build=there)
        if compared:
            why += " · " + t(lang, "delta.beyond", n=compared)
        return (f'<a class="delta-door none" title="{html.escape(why)}"'
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
