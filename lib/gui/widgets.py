# SPDX-License-Identifier: LGPL-2.1-or-later
"""The markup primitives every page is built from: tables, pills, boxes, bars.

`_table`/`_row`/`_cell` are a table and its `empty` answer, `_pill` and `_badge` are
one fact in a colour with its explanation in the tooltip, `_select`/`_option` are a
box whose every value is one this tree knows, and `_form`/`_filter_bar`/
`_action_bar` are the page's two bars - the one that is a URL you can copy, and the
one that is a command about to run.  `_number_chip`/`_number_row` are the numbers
strip, `_h2` is a section heading, `_plural` is the one place this program spells
English's `s`.

No page logic: a widget takes values and returns HTML, and every one of them is
shared by more than one page - a second copy is how one table starts printing a
different word than the next."""

import html
from collections.abc import Iterable, Mapping

from .. import errors
from ..i18n import DEFAULT_LANG, t
from .models import Filter
from .schema import AXIS_LABELS, NO_WINDOW, PILL_WORDS, ROUTE_KEYS, _labels
from .sorting import _sort_keys, _sort_label
from .urls import _lang_field, _url


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


def _plain_url(route: str, lang: str = DEFAULT_LANG) -> str:
    """A route with no conditions on it, in this language: the "start over" link.

    Which is what "clear the filter" means - a link that carried the conditions
    along would leave the reader looking at the same filtered table.
    """
    return _url(route, Filter(), lang=lang)


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


def _end_word(state: str, exit_code: "int | None", lang: str = DEFAULT_LANG) -> str:
    """What an activity's pill *says*: the exit code's word, not the state's.

    `Run._settle` (`lib/run.py`) collapses exit 1 and exit 3 onto the one state
    `failed`, and that is right for the *activity* - the process failed either way.  It
    is not the tests' verdict: `lib/errors.py` defines 0 = pass, 1 = a test failed and
    3 = infrastructure (*incomplete*, no verdict was reached), so a pill that printed
    the state called a run which finished every test it started and failed some of them
    "failed" - the very word it prints for a command that crashed.  The class stays the
    state's (the stylesheet colours one ending one way, and the state filter box offers
    the four states), and only the word is the code's.

    A cancelled activity keeps its own word whatever the code - `Run.cancel` leaves
    `0`/`-15` behind and the reader, not the tests, ended it - and so does any ending
    whose code is outside those three: the pill then says what is on disk, which is
    what the live panel's `exit code not seen` rule already does for a code nobody saw
    (`07-shell.md` §A3).
    """
    if state == "cancelled":
        return t(lang, "run_state.label.cancelled")
    if exit_code == errors.EXIT_PASS:
        return t(lang, "run_state.label.done")
    if exit_code == errors.EXIT_TEST_FAIL:
        return t(lang, "run_end.tests_failed")
    if exit_code == errors.EXIT_INFRA:
        return t(lang, "run_end.infra")
    return _labels("run_state", lang).get(state, str(state))


# The verdicts a tally prints, in the order it prints them: the value a record carries
# and the catalogue key of its word.  Taken from `PILL_WORDS["verdict"]` rather than
# spelled again, so a verdict the code grows is a verdict this line counts.
_TALLY_WORDS = tuple((one, f"verdict.label.{one}") for one in PILL_WORDS["verdict"])


def _tally_words(lang: str = DEFAULT_LANG) -> list[tuple[str, str]]:
    """`(verdict value, its word)` in the order a tally prints them.

    The script's copy of the tally reads this list (`_js` injects it as `I18N.tally`),
    so the two writers of one cell cannot disagree about the order or the word.
    """
    return [(one, t(lang, key)) for one, key in _TALLY_WORDS]


def _tally_word(tally: "Mapping[str, int]", lang: str = DEFAULT_LANG) -> str:
    """The ledger's counts for the builds an activity ran: `50 pass / 9 fail / 1 incomplete`.

    **The number the pill could not carry.**  `Run._settle`'s one `failed` state is the
    same for a run that failed every test and one that failed nine of fifty, and the
    operator's complaint was exactly that he could not tell which run he was looking
    at: `var/runs/20260920T152050-run` is exit 3 - *incomplete* - and its own log ends
    39 pass / 9 fail / 1 incomplete.  The counts come from the ledger the run wrote
    into, not from its exit code (`lib/gui/activities.py` reads the build ids out of the
    activity's own argv), so this is what happened, said as numbers.

    Only the verdicts that happened: `0 incomplete` is not a fact worth the ink.  An
    empty tally is an empty string, and the caller draws nothing.
    """
    return " / ".join(t(lang, "run_end.tally_one", n=tally[one], word=word)
                      for one, word in _tally_words(lang) if tally.get(one))


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


def _action_bar(action: str, fields: "Iterable[tuple[str, str]] | Mapping[str, str]" = (),
                label: str = "", argv: str = "", note: str = "", inner: str = "",
                form_id: str = "", lang: str = DEFAULT_LANG, api: str = "",
                hint: str = "", blocked: str = "") -> str:
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
    argv carries `--api-url` (`run`, `runday`, `fetch`, `worker`, `provision`,
    `drift`).  It is passed together with `_argv_of(..., api=…)` or not
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
    it and the browser shows the JSON instead (that is the endpoint's contract),
    so the span is empty and hidden (`:empty`) rather than promising
    something that will not come.

    `blocked` is the reason this button must **not** be pressable, and it is the one
    way this bar has ever been drawn without a `<button>`: the reason is what stands
    in the button's place, in the button's own slot, and the argv stays printed
    below it.  A page passes it when the conditions the bar holds are a command that
    cannot work (`pages/worker.py`: a platform the worker on this host would claim a
    job for and then boot with the wrong device), and the argument for saying it
    here rather than letting the POST answer later is the same one `_tick_box` makes
    about a row that cannot be ticked: a control that fails after it is pressed is
    worse than a control that explains itself.  Nothing about the endpoint changes -
    a POST sent by hand still reaches `command()`, which is where a command line is
    judged.
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
            + (f'<span class="off" aria-disabled="true" '
               f'title="{html.escape(blocked)}">{html.escape(blocked)}</span>'
               if blocked else
               (f'<button class="primary">{html.escape(label)}</button>' if label else ""))
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


def _plural(n: int, lang: str = DEFAULT_LANG) -> str:
    """English's plural `s`, or nothing - the one place this program spells it.

    The catalogue has no plural rule on purpose (`lib/i18n`'s header), and the old
    habit of writing `artifact(s)` is what `accept.py`'s W3 check calls a machine plural
    invented by the page: it never says how many.  Chinese needs nothing, so `zh` and a
    single count both get the empty string.
    """
    return "s" if lang == "en" and n != 1 else ""
