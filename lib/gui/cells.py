# SPDX-License-Identifier: LGPL-2.1-or-later
"""One cell of the builds and jobs tables, and the row it sits in.

The merged builds page is one row per build id with three facts to a row, and each
of those facts is a function here: where this copy is known from
(`_registered_cell`), what is on disk (`_bytes_cell`), what the pull record says
(`_act_cell`), what the ledger says (`_ran_cell`), and what the API answered about it
(`_remote_cell`).  The tick column is here too - `_job_tick` and the two "pre-tick
these" links (`_tick_missing`, `_tick_failed`) - because the tick is what turns a row
into a command, and the empty table's four reasons (`_empty_builds`) because an empty
table that does not say why is the page's worst answer."""

import html
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ..i18n import DEFAULT_LANG, t
from ..tests import DEFAULT_TESTS
from .urls import _url
from .values import _human, _short
from .widgets import _pill, _plain_url, _plural

if TYPE_CHECKING:
    from ..kbuild import Kbuild
    from .models import Filter, Remote

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
