# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The console's own words, in English and Chinese: one catalogue, one lookup.

`lib/gui/` is the only reader.  Every sentence a page prints is looked up here
by a dot-named key -- `t(lang, "remote.asked")` -- and **the English column is
today's gui wording, word for word**, so wiring a page changes which language
it speaks and never what it says.  The Chinese column is written for an operator:
short sentences, and one fixed vocabulary (远端 / 本地 / 对应 / 拉取 / 账本 /
判决 / 缺口 / 回归 / 登记 / 轮转).  An English mode renders
byte for byte what the page renders today.

Three things the caller has to know:

* **Nothing here is escaped, and nothing here escapes.**  A value carries the
  HTML the English carries (`&mdash;`, `&ldquo;…&rdquo;`, `<code>Build.make()</code>`)
  and is put into the page as written.  Every *value* interpolated into it -- a
  build id, a path, a query -- is still escaped by the caller with
  `html.escape()` and passed bare: `t(lang, "remote.asked", query=html.escape(q))`.
  Markup that wraps a whole string (`<h2>`, `<span>`, `<p class="query">`) stays
  in the page modules; a sentence that contains a link takes it as `{link}`.
* **Placeholders are `str.format`'s**: `t(lang, "count.rows", n=3)`.  No gettext,
  no plural rule -- English keeps its own `row(s)` spelling, Chinese counts
  without one.  A missing or malformed placeholder never raises: the row comes
  back as it stands, because a page that dies is worse than a page with `{n}` in
  it.  An unknown key comes back as the key itself, for the same reason.
* **What is not language is not translated.**  Command names, flags, paths,
  `build_id`, and the vocabulary the record itself uses (`tree`, `pulled`, `pass`,
  `resident`) stay as they are.  The code-form words that a page does show live
  in `word.*`, with the same string in both columns, so a mechanical replacement
  has somewhere to point and `--check` can tell "same on purpose" from "not
  translated".

Keys are named after where the words are read:

    nav.*        the eight pages, as navigation and as the page's <h1>
    page.*       one page's <h2> heading and its <span> sub-line
    filter.*     a select box's label
    col.*        a table's column headers
    label.*      a word used in both roles (a label somewhere, a header elsewhere)
    word.*       code-form words: identical in both columns, on purpose
    btn.* link.* a button's and a link's own text
    state.*      the words a fact is put in ("yes", "ready", "card only")
    state_text.* the sentences `Local.state_text()` builds
    evidence.*   the six meanings of the 「本地证据」 column
    count.* empty.* header.* js.*  phrases a page or the poll script assembles
    error.*      what a refused request answers on the wire (409/404)

The rows themselves live in `lib/i18n/catalogue/`, one module per group of the
page-shaped `# ---` banners they carry, and are merged below **in source order** --
that order is what `KEYS` keeps.  A new sentence is one edit in one part.

The command line is the only way in without a page:

    python3 -m lib.i18n --check lib/gui      # 缺失 / 未使用 / zh 与 en 相同
    python3 -m lib.i18n --map lib/gui        # key -> 它在哪个文件的第几行

`--check` exits 1 when a key a source *uses* is not in the catalogue, or when an
entry has no `zh` at all.  An entry whose `zh` equals its `en` is listed
separately and is not a failure -- that is what `word.*` is for.

An argument is a file *or* a directory.  A directory is read as every `*.py`
under it, in path order, which is what the reader has been since `lib/gui.py` was
split into `lib/gui/`: `--check lib/gui` reads the package, and a single file
still works the same way it always did.

接口形状（C++，只有声明）：include/kci/view.hpp §20 页面文案（中英两份）。
"""
from .catalogue import analysis, local, record, shell, words, work

# The two columns, in the order a request negotiates them.
LANGS = ("en", "zh")
DEFAULT_LANG = "en"

# Every sentence a page can say.  `en` is the wording the pages use today, verbatim
# except that a computed part became a `{placeholder}`; `zh` is the same fact in
# an operator's Chinese.  Keys are grouped the way the pages print them, so a page
# and its words can be read side by side.
CATALOGUE: dict[str, dict[str, str]] = {
    **shell.PART, **local.PART, **work.PART,
    **analysis.PART, **record.PART, **words.PART,
}

# Every key, in catalogue order - what `--check` walks and what `--map` prints.
KEYS: tuple[str, ...] = tuple(CATALOGUE)


# ---------------------------------------------------------------------------
# The two reads: one string, and one language
# ---------------------------------------------------------------------------

def t(lang: str, key: str, /, **fmt) -> str:
    """One string, in `lang`; an unknown key is returned as itself, never raised.

    The fallback chain is the whole robustness story of a page: the asked language
    -> English -> the key.  Values in `fmt` are interpolated with `str.format`,
    and are **not escaped** - the caller escapes what it interpolates.  A row that
    is missing a placeholder, or that has a stray brace, comes back as written.

    `lang` and `key` are positional-only (the `/`) so that a row may use `{key}`
    as a placeholder - `error.not_a_name` does - without the call colliding with
    this signature.  A collision is not a bad string: it is a `TypeError` at the
    raise site, which is a 500 on a request that meant to be a 409.
    """
    row = CATALOGUE.get(key)
    if row is None:
        return key
    text = row.get(lang) or row.get(DEFAULT_LANG) or key
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (IndexError, KeyError, ValueError):
        return text


def is_key(key: str) -> bool:
    """Is this a key the catalogue knows?  (`key_for()` is the other direction.)"""
    return key in CATALOGUE


def pick_lang(query_lang: str, cookie_lang: str, accept_language: str) -> str:
    """Which of LANGS to draw a page in: query, then cookie, then the header.

    A value nobody knows is skipped rather than refused, so `?lang=fr` still
    renders - in the next language that *is* known.  `Accept-Language` is
    negotiated by q value (ties go to the earlier tag), `zh-CN`/`zh-Hans`/`zh-TW`
    all count as `zh`, and a tag with `q=0` is a tag the client refused: it is
    dropped before it can be chosen.

    A region tag counts the same way in a URL and in the cookie as it does in the
    header: `?lang=zh-CN` asks for `zh`, not for the default.  The page itself
    only ever writes `zh`/`en`, so this costs nothing, and a pasted or bookmarked
    URL then means what whoever wrote it meant.
    """
    for asked in (query_lang, cookie_lang):
        found = _asked(asked)
        if found:
            return found
    return _negotiate(accept_language) or DEFAULT_LANG


def _asked(value: str) -> str:
    """A URL or cookie value as one of LANGS, or `""` when it names nothing we have.

    `zh-CN`, `ZH-cn` and `zh_Hans` are all `zh`.  `*` is *not* the default here:
    it names no language this function can pick, so the caller falls through to
    the next source instead of the negotiation stopping on it.
    """
    text = (value or "").strip().lower().replace("_", "-")
    for lang in LANGS:
        if text == lang or text.startswith(f"{lang}-"):
            return lang
    return ""


def _negotiate(header: str) -> str:
    """The best of an Accept-Language header, or `""` when it names nothing we have."""
    best: tuple[float, int, str] | None = None
    for order, item in enumerate((header or "").split(",")):
        tag, _, params = item.partition(";")
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value.strip())
                except ValueError:
                    weight = 1.0
        if weight <= 0:
            continue                        # q=0 is "not acceptable", not "least wanted"
        lang = _from_tag(tag.strip().lower())
        if not lang:
            continue
        rank = (weight, -order)
        if best is None or rank > best[:2]:
            best = (rank[0], rank[1], lang)
    return best[2] if best else ""


def _from_tag(tag: str) -> str:
    """One language tag as one of LANGS: `zh-TW` is `zh`, `*` is the default."""
    if not tag:
        return ""
    if tag == "*":
        return DEFAULT_LANG
    for lang in LANGS:
        if tag == lang or tag.startswith(lang + "-"):
            return lang
    return ""


def key_for(text: str) -> str | None:
    """The key a piece of today's English belongs to - how a page gets wired.

    Whitespace is normalised on both sides first, so a sentence a page builds
    from two source lines is still found.  A hit is an exact match on an English
    row, a whole-template match (`{n}` standing for whatever is there), or an
    unambiguous prefix (`"asked the API"` is enough).  Anything ambiguous - the
    word `what`, which is two headers, say - is `None`: `--map`'s reading of the
    tree, not a guess, is what a mechanical replacement should follow.
    """
    wanted = _normalize(text)
    if not wanted:
        return None
    rows = _index()
    exact = rows["exact"].get(wanted) or ()
    if len(exact) == 1:
        return exact[0]
    whole = [key for key, english in rows["templates"] if _template_match(english, wanted)]
    if len(whole) == 1:
        return whole[0]
    near = sorted({key for key, english in rows["prefixes"].items()
                   if english.startswith(wanted)},
                  key=KEYS.index)
    return near[0] if len(near) == 1 else None


def _normalize(text: str) -> str:
    """One line, one space between words - what a source line and a value agree on."""
    return " ".join(str(text or "").split())


def _template_match(english: str, text: str) -> bool:
    """Does `text` fill this English row's `{placeholders}`?  Each one matches anything."""
    head, sep, tail = _split_placeholder(english)
    if not sep:
        return text == head
    if not text.startswith(head):
        return False
    rest = text[len(head):]
    while True:                                 # the placeholder eats one more char at a time
        if _template_match(tail, rest):
            return True
        if not rest:
            return False
        rest = rest[1:]


def _split_placeholder(text: str) -> tuple[str, str, str]:
    """The first `{name}` of a value, split out as (before, `{name}`, after)."""
    start = text.find("{")
    while start != -1:
        end = text.find("}", start)
        if end == -1:
            break
        name = text[start + 1:end]
        if name and (name[0].isalpha() or name[0] == "_") \
                and all(one.isalnum() or one == "_" for one in name):
            return text[:start], text[start:end + 1], text[end + 1:]
        start = text.find("{", start + 1)
    return text, "", ""


_INDEX: dict[str, object] | None = None


def _index() -> dict[str, object]:
    """The lookup `key_for()` needs, built once: exact rows, templates, prefixes."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    exact: dict[str, list[str]] = {}
    prefixes: dict[str, str] = {}
    templates = []
    for key in KEYS:
        english = _normalize(CATALOGUE[key][DEFAULT_LANG])
        exact.setdefault(english, []).append(key)
        prefixes.setdefault(key, english)
        if "{" in english:
            templates.append((key, english))
    _INDEX = {"exact": {one: tuple(keys) for one, keys in exact.items()},
              "prefixes": prefixes, "templates": tuple(templates)}
    return _INDEX
