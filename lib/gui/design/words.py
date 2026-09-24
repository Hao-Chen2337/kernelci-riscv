# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every visible word in this console: both languages in the markup, one swap.

The design writes both columns into the same element and shows one of them -

    <span data-i18n="text" data-en="builds" data-zh="构建">builds</span>

- so a reader who switches language does not wait for a round trip: the page was
already carrying the other column, and `shell.BRIDGE_JS` (the board's own `setLang`)
is what moves it.  **There are four modes and no fifth**: `text` for an element's own
words, and `aria-label`, `placeholder` and `title` for the three attributes a reader
reads but cannot see in the markup.  Measured on the board: 352 `text`, 48
`aria-label`, 17 `title`, 14 `placeholder`, and **no `html` mode at all** - the three
strings that used to carry markup went with the screens that printed them.  `attr()` is
how a value reaches an attribute; `both()` is how it reaches an element.

Three things this module refuses to do.

* **It never re-implements the lookup.**  `t()` delegates to `lib.i18n.t`, so the
  fallback chain (asked language -> English -> the key), the `str.format` placeholders
  and "an unknown key is its own name, never an exception" have one owner.  The
  argument order is `lib.i18n`'s (`lang` first) on purpose: a second spelling of one
  call is how a caller ends up passing the key where the language goes.  The one thing
  added on top is `heading()`.
* **It never escapes a value twice.**  A catalogue value carries the markup its
  English carries, and every *value* interpolated into one is escaped by the caller.
* **It never lets a swapped word arrive as markup.**  `both()` refuses a value that
  contains a tag or an entity: all four modes are written with `textContent` or
  `setAttribute`, so a swap would put `<b>API 没有应答</b>` on the page as those
  characters.  The twenty-three catalogue values that carry one (`empty.remote_no_answer`
  and its siblings' `<b>`, `worker.where_results`' link, `remote.rows`' `&mdash;`) are
  therefore **`t(view.lang, key)`-only**: a sentence that cannot be swapped is rendered
  in the language of the answer, which is the one honest reading of it.  In an *attribute* the
  same value is safe - an attribute value is never parsed as markup, so a tag shows as
  its own characters before and after a swap alike - and `attr()` allows it.

**The column a reader sees is the response's, not English.**  `both(lang, key)` and
`attr(lang, kind, key)` take the language first and have no default: a page that forgot
it would hand a Chinese reader English with nothing on the page to say so, while a
*missed* argument is a `TypeError` the moment the page is drawn.  It is also what makes
the Chinese half verifiable at all - `accept.py`'s W1 and W3 read the *served* body, so
a page whose visible column was always English kept its translations in the attributes,
where no check looks.

`HEADING_KEYS` and `heading()` exist because the acceptance gate rejects an `<h2>`
whose text names a module, a `*.py` or a `Foo()` call: a heading is where the operator
read `Records / todo() / transitions()` as "奇怪的注释文字".  The rule is applied while
the page is drawn, so a page that would have failed the gate fails at its own panel
with the words that did it - and a misspelled key, which no gate can see through
`both()`, fails there too.
"""

import html
import re

from ...i18n import CATALOGUE, LANGS
from ...i18n import t as _lookup

# The three attributes a reader reads, and the only non-`text` modes there are.  The
# list is the board's own (`ATTRS` in its script) and closed on purpose: a fifth mode
# would need a client that knows it, and this console's client is four lines long.
ATTR_KINDS = ("aria-label", "placeholder", "title")

# A tag or an entity: what `textContent` writes as its own characters where the first
# paint wrote them as markup, so the two halves of a swapped page would disagree.
_MARKUP = re.compile(r"[<&]")


def _check_lang(lang: str) -> None:
    """Refuse anything that is not one of the two languages, with the fix in the error.

    The ruling that the visible column is the response's made `lang` the first argument
    of every function here, and a call site written before it - `both("link.log")` -
    would otherwise bind the *key* to `lang` and fail further in with a message about a
    missing argument rather than about the language.  The screens are written in
    parallel with this file, so the mistake is worth catching by name.
    """
    if lang not in LANGS:
        raise TypeError(
            f"{lang!r} is not a language ({', '.join(LANGS)}): it comes first and has no "
            "default - `both(view.lang, key)`, `attr(view.lang, 'title', key)`, "
            "`heading(view.lang, key)`")


def both(lang: str, key: str = "", /, **fmt: str) -> str:
    """One string in both languages, as the element the swap reads.

    `fmt` fills `{placeholders}` exactly as `lib.i18n.t` does, on both columns, so a
    number is interpolated the same way in English and in Chinese.  An unknown key
    comes back as the key itself: the same trade `lib/i18n/__init__.py` makes, because
    a page that dies is harder to review than a page with `shell.brand` on it - and
    `python3 -m lib.i18n --check lib/gui` is what catches the typo.

    A value carrying a tag or an entity raises instead (see the module docstring): the
    swap has no `html` mode, so it would be written into the element as its own
    characters and a Chinese reader would read the tags.

    **The visible text is `lang`'s column**, and the language has no default: a page
    that forgot it would show English to a reader who asked for Chinese, and nothing on
    the page would say so - while a missed argument is a `TypeError` the moment the page
    is drawn.  The other column rides in the attribute, and `shell.BRIDGE_JS` re-applies
    this one on load: the swap is idempotent when the two agree, which they do, because
    `?lang=`, the `kci_lang` cookie and `<html lang>` are all this response's language.

    `lang` and `key` are positional-only, for `lib.i18n.t`'s reason: a row may use
    `{key}` as a placeholder, so `both(view.lang, "error.not_a_stamp", key="since")` has
    to mean "fill `{key}`", not "the key is `since`" - and without the `/` it was a
    `TypeError` at the raise site instead of the sentence the caller meant.
    """
    _check_lang(lang)
    row = CATALOGUE.get(key)
    if row is None:
        _no_such_key(key)
        return key
    english = _fill(row.get("en") or key, fmt)
    chinese = _fill(row.get("zh") or english, fmt)
    _swappable(key, english, chinese)
    shown = chinese if lang == "zh" else english
    return (f'<span data-i18n="text" data-en="{_attr(english)}"'
            f' data-zh="{_attr(chinese)}">{shown}</span>')


def attr(lang: str, kind: str = "", key: str = "", /, **fmt: str) -> str:
    """One attribute a reader reads, in both languages: the design's own shape.

    The board writes a translatable attribute twice - once as the attribute itself, so
    the first paint and a reader with the script off have a value, and once as the pair
    the swap moves:

        <button title="light / dark" data-i18n="title"
                data-en="light / dark" data-zh="浅色 / 深色">

    The attribute itself is written in `lang`'s column, so a reader with the script off
    - and the first paint - read the language they asked for; the pair beside it is what
    the swap moves.  `lang` has no default, for `both()`'s reason.

    `kind` is one of `ATTR_KINDS`, and a name outside that list raises: a typo there
    would leave an attribute nobody can read in the other language, with nothing on the
    page to say so - the bug this function exists to make impossible.

    Unlike `both()`, a value carrying a tag is allowed: an attribute value is never
    parsed as markup, so `<code>x</code>` shows as those characters before the swap and
    after it, which is the same text and therefore not a lie.
    """
    _check_lang(lang)
    if kind not in ATTR_KINDS:
        raise ValueError(f"{kind!r} is not a mode the swap knows: "
                         f"{', '.join(ATTR_KINDS)}")
    row = CATALOGUE.get(key)
    if row is None:
        _no_such_key(key)
        return f'{kind}="{_attr(key)}"' if key else ""
    english = _fill(row.get("en") or key, fmt)
    chinese = _fill(row.get("zh") or english, fmt)
    shown = chinese if lang == "zh" else english
    return (f'{kind}="{_attr(shown)}" data-i18n="{kind}"'
            f' data-en="{_attr(english)}" data-zh="{_attr(chinese)}"')


def t(lang: str, key: str = "", /, **fmt: str) -> str:
    """One string in one language, for the three places the swap cannot reach.

    The `<html lang>` itself, the cells the shipped script re-writes every two seconds
    from its own `I18N` (which was built for this response's language), and a catalogue
    value that carries a tag - which `both()` refuses.  Everything else a reader sees,
    including every `title=` and `aria-label=`, goes through `both()`/`attr()`, or the
    reader needs a reload to change language halfway down a page.

    `lang` and `key` are positional-only, for `both()`'s reason.
    """
    _check_lang(lang)
    return _lookup(lang, key, **fmt)


def html_text(text: str) -> str:
    """What a fragment says, as words: tags dropped, entities decoded, spaces folded.

    The one reader of "is this text a heading a gate would accept", and the reason
    `heading()` can be handed either a catalogue key or markup a page built: both end
    up as the same sentence here.
    """
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


# The spellings `accept.py`'s W1b rejects in a heading, copied from that file
# on purpose and kept in step with it by hand: it is a *decision* and not a
# heuristic (a bare `runday` is not flagged, `runday()` is), and a heading that
# trips it here would have tripped it there - just later, and with no line number.
_MODULE_IN_HEADING = re.compile(
    r"\b(runday|poller|judge|drift|records|Builds?)\.?\w*\(\)"
    r"|\b\w+\.py\b|\bRecords\.[a-z_]+\(\)")

# What a catalogue key looks like: dotted, lower-case, no spaces.  A heading that
# spells one and is not in the catalogue is a typo, and a typo printed as a heading is
# the one mistake nothing catches - it reads like a label on screen, `accept.py`'s W1b
# only looks for module names, and `--check` reads calls spelled `t(...)` while the
# visible words of this layer go through `both()`.
_KEY_SHAPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def heading(lang: str, key: str = "", **fmt: str) -> str:
    """A panel title: a catalogue key in both languages, or markup that is words.

    Raises `ValueError` rather than drawing a heading the gate would reject - a panel
    titled `Builds.load()` is a bug in the page, and the place to say so is the panel.
    An empty title is allowed and means what it means in the design: the board draws
    panels whose `<h2>` is empty and whose sub-line carries the fact (`the numbers
    behind this page`).
    """
    _check_lang(lang)
    if key in CATALOGUE:
        if key not in HEADING_KEYS:
            raise ValueError(
                f"heading {key!r} names a module, a file or a call: "
                f"{html_text(CATALOGUE[key].get('en') or '')!r} cannot be an <h2>")
        return both(lang, key, **fmt)
    if _KEY_SHAPE.match(key):
        raise ValueError(f"heading {key!r} is shaped like a catalogue key and is not one")
    text = html_text(key)
    found = _MODULE_IN_HEADING.search(text)
    if found:
        raise ValueError(f"heading {text!r} prints the symbol {found.group(0)!r}")
    return key


def _no_such_key(key: str) -> None:
    """Refuse a key-shaped string that names no row: a typo nothing else can see.

    `python3 -m lib.i18n --check` reads calls spelled `t(...)`, and this layer's
    visible words go through `both()` - so the catalogue cannot catch a misspelled key
    here, and the page would print `col.age` in a header, which reads like a label.
    A literal that is *not* key-shaped (a code-form word, a path) is passed through, so
    only a typo is refused.
    """
    if _KEY_SHAPE.match(key):
        raise ValueError(f"{key!r} is shaped like a catalogue key and is not one")


def _swappable(key: str, *columns: str) -> None:
    """Refuse a value the four modes cannot carry: a tag, or an entity."""
    for text in columns:
        found = _MARKUP.search(text)
        if found:
            raise ValueError(
                f"{key!r} carries markup ({text!r}): the swap has four modes and none "
                f"of them is html, so render this sentence with t(view.lang, {key!r}) "
                "instead - or split it into words that carry none")


def _fill(text: str, fmt: dict) -> str:
    """`{placeholders}` filled, or the string as written - `lib.i18n.t`'s own rule."""
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (IndexError, KeyError, ValueError):
        return text


def _attr(text: str) -> str:
    """One column as an attribute value: the four characters that can end it."""
    return (text.replace("&", "&amp;").replace('"', "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;"))


# The catalogue keys whose text is plain words and may therefore title a panel.
# Derived by the same rule `heading()` applies, so the two cannot disagree: this is
# the set a page may *choose from*, and `heading()` is the check on what it chose.
HEADING_KEYS: frozenset[str] = frozenset(
    key for key, row in CATALOGUE.items()
    if not _MODULE_IN_HEADING.search(html_text(row.get("en") or "")))
