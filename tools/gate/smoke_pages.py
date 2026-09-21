#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render every page in-process and report the ones that raise.

    smoke_pages.py [--all] [--lang en|zh|both] [--api URL] [--timeout 20]

Why this exists, in one sentence: **`ruff` and an import check both missed a
breaking change.**  During the structure merge a second module-level
`def _numbers(chips)` was added while the original `_numbers(form, key, default)`
still existed; the new one shadowed the old at module scope, so five call sites
began raising `TypeError: _numbers() takes 1 positional argument but 3 were given`
and **every page answered HTTP 500 in both languages** - while `ruff check` reported
clean and `import lib.gui` succeeded, because neither of those ever calls a page.

So this is the third canary, and the only one that exercises a render:

* `ruff` sees syntax, imports and obvious dead names - not shadowing across 3 700 lines;
* `import lib.gui` sees module-scope evaluation (default arguments, decorators) - not
  a function that only runs when a page is drawn;
* **this** sees both, because it draws the pages.

No server and no network are required for the pages that read only local disk.  With
`--all` the API-backed pages are rendered too, which costs whatever the API costs -
use `--api` to point them at a fast one, or leave them out.

**"The page drew" is not "the page had a data source."**  Every page catches its own
`ApiError` and draws the state it draws when the rows are not there, so an API that
answers nothing looks exactly like a page that renders - and this check used to call
that `every page rendered` and exit 0.  The reads are therefore watched too: when the
renders ask the API and **not one** of those reads comes back, this exits 1 and names
the page, the read and the URL that did not answer.  A read that failed while others
answered is printed and is not fatal: one endpoint refusing is a fact about that
endpoint, and the pages that did read show it.
"""

import argparse
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# The pages that read only `var/`: these are the cheap, always-run part, and they are
# where a render-time break shows up first.
LOCAL_PAGES = ("/jobs", "/runs")
API_PAGES = ("/", "/worker", "/analysis")

# `/local/<id>` is the one route that is not in `PAGES`; it needs an id that exists,
# so it is tried only when the workspace has one.
DETAIL = "/local/{build_id}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true",
                        help="render the API-backed pages too (slow)")
    parser.add_argument("--lang", default="both", choices=("en", "zh", "both"))
    parser.add_argument("--api", default="", help="base for the API-backed pages")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--calls", action="store_true",
                        help="count the API reads each render makes, per language")
    args = parser.parse_args(argv)

    from lib import api as api_mod
    from lib import gui as g

    pages = list(LOCAL_PAGES) + (list(API_PAGES) if args.all else [])
    langs = ("en", "zh") if args.lang == "both" else (args.lang,)

    build_id = _a_build_id()
    if build_id:
        pages.append(DETAIL.format(build_id=build_id))

    client = None
    if args.all or args.api:
        client = api_mod.Api(args.api or None, timeout=args.timeout)

    bad, slow = [], []
    calls = {}
    current = [""]                      # which page/language the counter is attributing to

    # **An API that answers nothing is a verdict, and it used to be invisible here.**
    # Measured: `KCI_API_URL=http://127.0.0.1:19998` (nothing listening) printed
    # `every page rendered` and exited 0, with the 143 KB homepage carrying
    # `did not answer this query ... nothing is known about this window either way` -
    # every query behind every page had failed.  Nothing raised, so `bad` stayed empty
    # and `failed = bool(bad)` was False; the only other signal, `slow`, is printed and
    # never reaches the exit code.  The pages are not wrong to paint the empty state -
    # a console has to draw something - but a *check* may not read that state as
    # success, and the difference between the two is countable: a read either answered
    # or it did not.  Both counts are taken at the one place every read goes through.
    #
    # Total silence (not one read answered) fails the check whatever the workspace
    # holds - "the API is not there" is not a state this canary may report as fine.
    # Renders that made no read at all (no `--all`, no client) are left alone: there is
    # no data source to judge, and the render canary still does its own job.
    reads = [0, 0]                      # [asked, answered]
    refused = {}                        # "page[lang]" -> [(method, path, why), ...]

    if args.calls:
        # Count the API reads each render makes, **per language**.  This is the
        # deterministic form of "a language must not change the cost": wall clock on
        # this API varies by ~3x minute to minute, so `/worker` measured 3.37 s in
        # English and 3.09 s in Chinese at best-of-three while a single unlucky pair
        # reported a 2.8x "language" skew.  The *number of reads* cannot be unlucky.
        original = api_mod.Api._request

        def counting(self, method, path, params=None, body=None, token="", retries=1):
            calls.setdefault(current[0], []).append((method, path))
            return original(self, method, path, params=params, body=body,
                            token=token, retries=retries)

        api_mod.Api._request = counting

    # The observation wraps whatever is installed above, so `--calls`' own counting
    # stays exactly what it was - and a read is retried exactly as `lib/api` retries
    # it (`retries` is forwarded only when the caller names one), so the pages see the
    # answer they would see in production.
    answered_through = api_mod.Api._request

    def watching(self, method, path, params=None, body=None, token="", **rest):
        reads[0] += 1
        try:
            answer = answered_through(self, method, path, params=params, body=body,
                                      token=token, **rest)
        except Exception as exc:                # counted, then re-raised: nothing is hidden
            refused.setdefault(current[0], []).append((method, path, str(exc)))
            raise
        reads[1] += 1
        return answer

    api_mod.Api._request = watching

    width = max(len(page) for page in pages)
    print(f"# rendering {len(pages)} page(s), {len(langs)} language(s)"
          f"{'  (API-backed pages included)' if args.all else ''}")
    for page in pages:
        for lang in langs:
            current[0] = f"{page}[{lang}]"
            started = time.monotonic()
            try:
                gui = g.Gui(rows=25, api=client)
                markup = gui.render(page, {}, lang=lang)
            except Exception as exc:                            # noqa: BLE001
                bad.append((page, lang, exc))
                print(f"RAISE {page:<{width}} [{lang}] {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=3)
                continue
            took = time.monotonic() - started
            if took > 5.0:
                slow.append((page, lang, took))
            mark = "slow " if took > 5.0 else "ok   "
            print(f"{mark} {page:<{width}} [{lang}] {len(markup):>7} bytes  {took:6.2f}s")

    print()
    if bad:
        print(f"{len(bad)} render(s) raised - this is the failure `ruff` cannot see:")
        for page, lang, exc in bad:
            print(f"  {page} [{lang}]: {type(exc).__name__}: {exc}")
    else:
        print("every page rendered")
    if slow:
        print(f"{len(slow)} render(s) over 5s (the API's cost, not the renderer's): "
              + ", ".join(f"{p}[{l}] {t:.1f}s" for p, l, t in slow))

    # **The evidence, page by page.**  A boolean would leave an operator with "the pages
    # rendered, and the check failed" and no way to tell which read died; and "the API is
    # down" and "one endpoint refuses" need different actions.  So every read that failed
    # is named with the page it was made for, and the distinct reasons are printed once -
    # 68 failed reads are two URLs and one connection refusal, not a page of text.
    if refused:
        print()
        print(f"{reads[0] - reads[1]} of {reads[0]} API read(s) did not answer:")
        for where, ones in refused.items():
            seen = dict.fromkeys((method, path) for method, path, _ in ones)
            print(f"  {where}: {len(ones)} read(s) - "
                  + ", ".join(f"{method} {path}" for method, path in seen))
        for why in dict.fromkeys(reason for ones in refused.values()
                                 for _, _, reason in ones):
            print(f"    {why}")

    silence = bool(reads[0]) and not reads[1]
    if silence:
        at = client.base if client is not None else api_mod.Api.url()
        print()
        print(f"the API at {at} answered none of the {reads[0]} read(s) these pages made, "
              "so every page that shows rows drew the state it draws when its data source "
              "is not there - `every page rendered` is not the same answer as `the pages "
              "had a data source`")

    failed = bool(bad) or silence
    if args.calls:
        print()
        print("# API reads per render (the deterministic form of `a language must not "
              "change the cost`)")
        skew = []
        for page in pages:
            per = {l: calls.get(f"{page}[{l}]", []) for l in langs}
            counts = {l: len(one) for l, one in per.items()}
            line = "  ".join(f"{l}: {counts[l]} read(s)" for l in langs)
            mark = ""
            if len(langs) == 2 and len(set(counts.values())) > 1:
                mark = "   <-- UNEQUAL"
                skew.append((page, counts))
            print(f"  {page:<{width}} {line}{mark}")
        if skew:
            failed = True
            print(f"\n{len(skew)} page(s) read the API a different number of times per "
                  f"language: {skew}")
            for page, counts in skew:
                for lang in langs:
                    seen = calls.get(f"{page}[{lang}]", [])
                    print(f"  {page} [{lang}]: " + ", ".join(p for _, p in seen))
        else:
            print("\nevery page read the API the same number of times in both languages")
    return 1 if failed else 0


def _a_build_id() -> str:
    """One build id the workspace holds, for the `/local/<id>` detail route."""
    import json
    root = os.environ.get("KCI_WORK_DIR") or os.path.join(ROOT, "var")
    try:
        with open(os.path.join(root, "state", "builds.json"), encoding="utf-8") as handle:
            return next(iter(json.load(handle)), "")
    except (OSError, ValueError, StopIteration):
        return ""


if __name__ == "__main__":
    sys.exit(main())
