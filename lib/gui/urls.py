# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every link this console writes: one function, one spelling of a URL.

`_url` is the one place a route, a filter and an override become an address, so
`?api=` is canonicalised by `Apis.key` and not by hand, the keys come out in
`FILTER_ORDER`, and a condition a link drops is dropped on purpose (`NAV_KEYS`).
`_link`, `_plain_url`, `_hidden` and `_lang_field` are the four wrappers the pages
use: a page-to-page link, the "start over" link, a hidden form value, and the
language a form that leaves this page was drawn in."""

import html
import urllib.parse
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..i18n import DEFAULT_LANG
from .schema import FILTER_ORDER, route_keys

if TYPE_CHECKING:
    from .models import Filter


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
    # The route's own key list (`route_keys` says how the longest-prefix part works, and
    # is the one spelling of it - `ui.pager` asks the same question to know which page
    # state a link has to keep), narrowed to what this caller wants carried.
    wanted = set(route_keys(route))
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


def _carried(route: str, check: "Filter | None",
             drawn: Iterable[str] = ()) -> list[tuple[str, str]]:
    """Every condition the filter holds that a GET bar on `route` must spell out again.

    A GET form replaces the whole query string, so a key a bar draws no control for is a
    key the next request silently answers without.  This is the inverse of the whitelist
    `_url` applies to a link, and it asks the same three questions: what the filter holds
    (`to_query()`, which is the conditions with their defaults omitted and no page state),
    what this route reads (`route_keys`), and what this bar draws for itself (`drawn`).

    The route's list is here because a form has no whitelist of its own - the browser
    submits whatever is inside it - so a bar states the keys rather than handing over
    everything the page happens to hold.  The filter's list is here because
    `FILTER_ORDER` is *not* the whole of it, and a rule that walked only the order could
    not see a `Filter` field the order does not list.  That was not a theoretical gap:
    `tz` and `tests` are both outside the order, and the clock select on `/analysis` was
    a control that changed nothing for exactly this reason - the bar above it wrote a
    hidden copy of the same key, and of a repeated key the first one wins
    (`forms._first`).
    """
    if check is None:
        return []
    named = set(drawn)
    allowed = set(route_keys(route))
    return [(key, value) for key, value in check.to_query()
            if key in allowed and key not in named]


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
