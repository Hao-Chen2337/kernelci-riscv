# SPDX-License-Identifier: LGPL-2.1-or-later
"""What a page is handed: the rows, the question, the language, and the links.

A page module in this package draws one screen and decides nothing.  Everything it
may touch arrives in a `View`, and there are only five things in one:

    rows    the data, already in the shape the design's markup reads (`data.rows`)
    check   the question the URL asked (`lib.gui.models.Filter`) - what the filter
            bar shows, and what a link has to carry so the answer stays the answer
    lang    the language this response is being drawn in (`"en"` or `"zh"`)
    route   the route being drawn, which is what `url()` needs to know which keys
            the target reads
    gui     the console itself, for the few reads a screen makes for one cell
            (`gui.trend(...)`, `gui.drift(...)`) - reached for by name, never
            re-implemented here

`url()` is the only way a page writes an address, and it delegates to
`lib.gui.urls._url` rather than growing a second spelling: that function is where
`?api=` is canonicalised, where a key the target does not read is dropped
(`NAV_KEYS`), and where `?lang=` is spelled out on the one link whose job is to
change the language.  A page that built a query string by hand would be the second
answer to "what is this link" - and the day a filter key is added, the two answers
would part company.

The rows themselves are a plain dict, exactly as the prototype had them: a page
reads `d["builds"]` and knows nothing about where they came from.  That is the seam
the prototype documented (`proto/__init__.py`) and the reason `data.rows` can be
replaced with a fixture again for a rendering test.
"""

import html

from ...i18n import DEFAULT_LANG, t
from ..urls import _url


class View:
    """One screen's whole world: rows, question, language, route, and links."""

    __slots__ = ("apis", "check", "gui", "lang", "route", "rows")

    def __init__(self, rows: dict, check=None, lang: str = DEFAULT_LANG, route: str = "/",
                 gui=None, apis=None):
        self.rows = rows
        self.check = check
        self.lang = lang
        self.route = route
        self.gui = gui
        self.apis = apis

    def url(self, route: str = "", *drop: str, carry=None, keep=(), spell_lang: bool = False,
            **over: str) -> str:
        """A link to `route` carrying this page's question, minus `drop`, plus `over`.

        `route=""` means this page.  An empty keyword value drops that key, which is
        how a chip's `×` and "start over" are written without a second code path.
        """
        return _url(route or self.route, self.check, *drop, carry=carry, keep=keep,
                    lang=self.lang, spell_lang=spell_lang, **over)

    def link(self, route: str = "", text: str = "", *drop: str, carry=None, keep=(),
             spell_lang: bool = False, cls: str = "", title: str = "", **over: str) -> str:
        """`url()` as an anchor.  `text` is already-rendered markup, so it may be a
        dual-language span (`words.both`) or a `<code>` chip."""
        attrs = f' class="{html.escape(cls, quote=True)}"' if cls else ""
        attrs += f' title="{html.escape(title, quote=True)}"' if title else ""
        return f'<a href="{html.escape(self.url(route, *drop, carry=carry, keep=keep, spell_lang=spell_lang, **over))}"{attrs}>{text}</a>'

    def t(self, key: str, /, **fmt: str) -> str:
        """One sentence in this response's language, from the tree's own catalogue.

        Visible words go through `words.both()` instead - that is what lets the
        reader switch language without a round trip - so this is for the places a
        second language cannot live: a `title=`, an `aria-label`, the `<html lang>`.

        `key` is positional-only for the reason `lib.i18n.t`'s docstring gives: a row
        may use `{key}` as a placeholder, and `error.not_a_stamp` does.  Without the
        `/`, `view.t("error.not_a_stamp", key="since", …)` was a `TypeError` - a 500
        on a request that meant to be a 409 - and the wrapper is where that has to be
        said, because the catalogue's own `t()` cannot speak for its callers.
        """
        return t(self.lang, key, **fmt)
