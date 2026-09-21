# SPDX-License-Identifier: LGPL-2.1-or-later
"""The self-check: `--check` and `--map`, over a file or a directory.

    python3 -m lib.i18n --check lib/gui      # 缺失 / 未使用 / zh 与 en 相同
    python3 -m lib.i18n --map lib/gui        # key -> 它在哪个文件的第几行

`--check` exits 1 when a key a source *uses* is not in the catalogue, or when an
entry has no `zh` at all; an entry whose `zh` equals its `en` is listed separately
and is not a failure - that is what `word.*` is for.  An argument is a file *or* a
directory, read as every `*.py` under it in path order (see `_sources`).

No page imports this module: it is reached as `python3 -m lib.i18n`, through
`lib/i18n/__main__.py`.
"""

import os
import sys

from . import CATALOGUE, KEYS, _normalize, is_key

# No `import re`: a `re` module first on `sys.path` is this package's own ledger
# reader (`lib/re.py`, imported by the pages as `re_mod`) and not the stdlib module,
# and this module has been run under both layouts.  `os` is safe - there is no
# `lib/os.py` - and is what `_sources()` walks a package with.  The handful of scans
# below are spelled out by hand instead.

_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz")


def _calls(line: str) -> list[int]:
    """Where `t(` starts on this line - a call, not the tail of `format(` or `split(`."""
    found, at = [], 0
    while True:
        at = line.find("t(", at)
        if at < 0:
            return found
        before = line[at - 1] if at else " "
        if not (before.isalnum() or before in "_."):
            found.append(at)
        at += 2


def _literals(text: str) -> list[str]:
    """The string literals of a piece of source, in order, unescaped by halves."""
    out, at = [], 0
    while at < len(text):
        quote = text[at]
        if quote not in "'\"":
            at += 1
            continue
        end, chunk = at + 1, []
        while end < len(text) and text[end] != quote:
            if text[end] == "\\":
                chunk.append(text[end:end + 2])
                end += 2
                continue
            chunk.append(text[end])
            end += 1
        out.append("".join(chunk))
        at = end + 1
    return out


def _key_shape(text: str) -> bool:
    """Is this literal shaped like a key - dotted, lower-case, no spaces?"""
    return bool(text) and text[0] in _LETTERS and "." in text \
        and not text.startswith(".") and not text.endswith(".") and ".." not in text \
        and all(one in _KEY_CHARS for one in text)


def _used(path: str) -> tuple[list[tuple[int, str]], int]:
    """The keys a file hands to `t()`, with the line each one is on.

    Only literal keys can be read: `t(lang, key)` is counted, not guessed, and
    comes back as the second member.
    """
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    found: list[tuple[int, str]] = []
    unknown = 0
    for number, line in enumerate(lines, 1):
        for at in _calls(line):
            tail = line[at:at + 400]
            key = next((one for one in _literals(tail) if _key_shape(one)), None)
            if key is None:
                unknown += 1
                continue
            found.append((number, key))
    return found, unknown


def _sources(path: str) -> list[str]:
    """The files an argument names: itself, or every `*.py` under it, in path order.

    A directory is how the reader is pointed at a package: `lib/gui/` is one
    program in twenty-odd files, and a `--check` that had to be handed each of
    them would be a `--check` that is quietly run on the ones someone remembered.
    """
    if not os.path.isdir(path):
        return [path]
    found = []
    for base, directories, names in os.walk(path):
        directories.sort()
        found.extend(os.path.join(base, one) for one in sorted(names) if one.endswith(".py"))
    return sorted(found)


def _check(paths: list[str]) -> int:
    """缺失的 key / 没被用到的 key / zh 缺了或与 en 一样的条目."""
    sources = [one for path in paths for one in _sources(path)]
    used: list[tuple[int, str, str]] = []
    computed = 0
    for path in sources:
        found, unknown = _used(path)
        used.extend((number, key, path) for number, key in found)
        computed += unknown
    missing = [one for one in used if not is_key(one[1])]
    seen = {key for _, key, _ in used}

    print(f"目录：{len(KEYS)} 个 key（en {len(KEYS)} 条，zh "
          f"{sum(1 for one in KEYS if CATALOGUE[one].get('zh'))} 条）")
    print(f"扫描：{', '.join(paths)}（{len(sources)} 个文件） - {len(used)} 处 t() 调用"
          + (f"，另有 {computed} 处的 key 不是字面量（读不出来）" if computed else ""))

    print(f"\n[缺失] 文件里用了、目录里没有的 key：{len(missing)}")
    for number, key, path in missing:
        print(f"  {path}:{number}  {key}")
    if not missing:
        print("  （没有）")

    unused = [one for one in KEYS if one not in seen]
    print(f"\n[未使用] 目录里有、这个文件还没用到的 key：{len(unused)}")
    print("  " + (", ".join(unused) if unused else "（没有）"))

    blank = [one for one in KEYS if not CATALOGUE[one].get("zh")]
    same = [one for one in KEYS if CATALOGUE[one].get("zh") == CATALOGUE[one]["en"]]
    print(f"\n[zh 缺失] 有 en 没有 zh 的条目：{len(blank)}")
    print("  " + (", ".join(blank) if blank else "（没有）"))
    print(f"\n[zh 与 en 相同] {len(same)} 条 - 大部分是 word.* 里本来就该相同的词，"
          "逐条看过再定：")
    print("  " + (", ".join(same) if same else "（没有）"))

    print(f"\n退出码：{1 if missing or blank else 0}"
          f"（缺失 {len(missing)} + zh 缺失 {len(blank)}；未使用与 zh==en 不算失败）")
    return 1 if missing or blank else 0


def _map(path: str) -> int:
    """key -> 它在树里的每一处，连同那一行的原文；行文已经不像那条英文的打一个 `?`.

    The lines are read off the tree as it stands, never out of a remembered line
    number: the tree is what a reader is looking at, and the tree moves.
    """
    sources = _sources(path)
    text = {}
    where: dict[str, list[tuple[str, int]]] = {}
    for one in sources:
        with open(one, encoding="utf-8") as handle:
            text[one] = handle.read().splitlines()
        for number, key in _used(one)[0]:
            where.setdefault(key, []).append((one, number))
    for key in KEYS:
        print(f"{key}\t{CATALOGUE[key]['en']}")
        for one, number in where.get(key, ()):
            lines = text[one]
            good = _looks(lines, number - 1, key)
            flag = "" if good else "?"      # the line no longer reads like that English
            print(f"    {one}:{number}{flag}\t{lines[number - 1].strip()[:110]}")
    return 0


def _looks(lines: list[str], index: int, key: str) -> bool:
    """Is there still a distinctive word of this key's English on that line?

    A coarse test on purpose: a sentence a page builds from four source lines has
    its head words on the first one only, so requiring all of them would mark
    every continuation line.  Sharing one long word is enough to say "this is
    probably still the place"; sharing none means the line moved.
    """
    if not 0 <= index < len(lines):
        return False
    words = [one for one in _words(_normalize(CATALOGUE[key]["en"])) if len(one) > 3]
    if not words:
        return True
    return any(one.lower() in lines[index].lower() for one in words)


def _words(text: str) -> list[str]:
    """The words of a sentence, apostrophes kept - what a coarse match compares."""
    out: list[str] = []
    chunk: list[str] = []
    for one in text:
        if one.isalpha() or one == "'":
            chunk.append(one)
        elif chunk:
            out.append("".join(chunk))
            chunk = []
    if chunk:
        out.append("".join(chunk))
    return out


def _main(argv: list[str]) -> int:
    """`--check PATH…` / `--map PATH`; anything else is a usage line, not a traceback.

    A path is a file or a directory (a directory is every `*.py` under it - see
    `_sources`), so the same argument reaches the whole of `lib/gui` and a single
    module alike.
    """
    if len(argv) >= 2 and argv[0] == "--check":
        return _check(argv[1:])
    if len(argv) == 2 and argv[0] == "--map":
        return _map(argv[1])
    # The headline is the package's own docstring, which is where it was when this
    # was one file: a bad flag answers with what the catalogue is.
    print(sys.modules[__package__].__doc__.strip().splitlines()[0])
    print("用法：python3 -m lib.i18n --check lib/gui   # 缺失 / 未使用 / zh 与 en 相同")
    print("      python3 -m lib.i18n --map lib/gui     # key -> 文件:行号")
    return 2
