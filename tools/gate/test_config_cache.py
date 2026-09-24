#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The kept-config cache: what it may reuse, and what it must refuse.

    test_config_cache.py

`lib/drift.py::_config_text` reads each build's `.config` from wherever this
workspace already has it - the kept copy under `var/configs/`, else the copy a *pull*
left under `var/downloads/<build-id>/` - and only then from the artifact store over
the API.  The cache is safe only because of the checks that live beside it, and those
checks are what this test pins down:

* a kept copy is reused **only** if its bytes match the sha256 recorded when it was
  kept - a config truncated to 5 000 of 192 231 bytes still parses into 166 options,
  so without this the comparison answers `+5426 -8 ~1` instead of `+618 -616 ~99`,
  with zero HTTP calls and nothing on screen to say it is wrong;
* a **failure** is never kept, or one bad download becomes a permanent one;
* `?fresh=1` / `?ttl=0` really refetches, because the operator asked for a refresh
  that re-reads;
* a build this console has **pulled** answers from its own copy with no request at
  all, and that copy is kept - a pull followed by a comparison is one download, not
  two - while a pulled copy that is not a config is passed over rather than believed
  (`_local_config`), because a file in the download tree must never be able to fail a
  comparison the artifact store could answer;
* the count the page prints (`api.fetches`) counts the reads that went **out** and not
  the ones served from disk.

No network: `Api.text` is replaced by a stub whose content and call count this test
controls, so every assertion is about the cache rather than about the weather.

Exit status is the verdict, like `python3 lib/i18n.py --check lib/gui.py`.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from lib import api as api_mod
from lib import drift as drift_mod
from lib import layout
from lib.errors import ConfigError, KciError
from lib.kbuild import Kbuild

URL = "https://example.invalid/kbuild-riscv-abc123/.config"

# A real config is thousands of lines; what matters here is that it PARSES, which
# is the property that makes a truncated one dangerous.
BODY = "".join(f"CONFIG_OPTION_{n}=y\n" for n in range(200))
SHORT = BODY[:200]                       # still parses: ~14 options, not 0


class StubApi:
    """An `Api` whose `.text()` is counted and whose answer this test decides."""

    def __init__(self, body=BODY, error=None):
        self.body, self.error, self.calls = body, error, 0

    def text(self, url):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.body


def note_of(path):
    return json.load(open(path, encoding="utf-8"))


def main() -> int:
    home = tempfile.mkdtemp(prefix="kci-config-cache-")
    os.environ["KCI_WORK_DIR"] = home
    failed, checks = 0, 0

    def check(name, ok, evidence):
        # The total is counted and not written down: it was a hardcoded 13 while ten
        # checks ran, so a suite that grew or lost a case printed a number that was
        # about nothing - and a gate whose own count is wrong is the first thing a
        # reader stops believing.
        nonlocal failed, checks
        checks += 1
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({evidence})" if evidence else ""))

    def drop(*paths):
        """Forget what an earlier case left, whether or not it is there.

        Each case below starts from a state this test *names* - nothing kept, a pulled
        copy, a damaged kept copy - rather than from whatever the case above happened to
        leave behind.  Case 8 is the reason: it writes nothing, so a bare `os.remove`
        after it is an error about this test's own bookkeeping rather than about the
        cache.
        """
        for path in paths:
            if os.path.exists(path):
                os.remove(path)

    try:
        config = drift_mod._config_path(URL)
        sidecar = drift_mod._config_note(URL)

        # 1. a cold read fetches once and keeps what it read
        api = StubApi()
        api_mod.begin_request(ttl=5)
        got = drift_mod._config_text(api, URL)
        check("a cold read fetches once and answers", got == BODY and api.calls == 1,
              f"calls={api.calls}")
        check("both the config and its note are kept",
              os.path.isfile(config) and os.path.isfile(sidecar), config)
        note = note_of(sidecar)
        raw = BODY.encode("utf-8")
        check("the note records the URL, the size and the sha256",
              note == {"url": URL, "bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest()},
              str(note)[:90])

        # 2. a warm read answers from the kept copy, with no request at all
        api2 = StubApi()
        api_mod.begin_request(ttl=5)
        got = drift_mod._config_text(api2, URL)
        check("a warm read makes no request", got == BODY and api2.calls == 0,
              f"calls={api2.calls}")

        # 3. the dangerous one: a truncated kept copy
        with open(config, "w", encoding="utf-8") as handle:
            handle.write(SHORT)
        api_mod.begin_request(ttl=5)
        try:
            drift_mod._config_text(StubApi(), URL)
            check("a truncated kept copy is refused", False,
                  "it was used - this is the +5426/-8 silent wrong answer")
        except ConfigError as exc:
            check("a truncated kept copy is refused", True, str(exc)[:60] + "…")

        # 4. the same for a same-length corruption, which a size check alone misses
        with open(config, "w", encoding="utf-8") as handle:
            handle.write(BODY.replace("OPTION_1=", "OPTION_9=", 1))
        api_mod.begin_request(ttl=5)
        try:
            drift_mod._config_text(StubApi(), URL)
            check("a same-length corruption is refused", False, "a size-only check would miss this")
        except ConfigError:
            check("a same-length corruption is refused", True, "caught by the sha256, not the size")

        # 5. after deleting the damaged pair, a cold read recovers
        drop(config, sidecar)
        api = StubApi()
        api_mod.begin_request(ttl=5)
        got = drift_mod._config_text(api, URL)
        check("deleting the damaged pair lets a cold read recover",
              got == BODY and api.calls == 1, f"calls={api.calls}")

        # 6. ?fresh=1 / ttl=0 refetches even though a good copy is kept
        api = StubApi()
        api_mod.begin_request(ttl=0)
        got = drift_mod._config_text(api, URL)
        check("a fresh request refetches despite a good copy",
              got == BODY and api.calls == 1, f"calls={api.calls}")

        # 7. a failure is never kept, so one bad download cannot become permanent
        drop(config, sidecar)
        api = StubApi(error=KciError("the store answered 500"))
        api_mod.begin_request(ttl=5)
        try:
            drift_mod._config_text(api, URL)
            check("a failed download is not kept", False, "it did not raise")
        except KciError:
            check("a failed download is not kept",
                  not os.path.exists(config) and not os.path.exists(sidecar),
                  "nothing was written")

        # 8. what is not a config is not kept either (an HTML error page parses to
        #    no options, and `_refuse_empty` calls that "not a kernel config")
        api = StubApi(body="<html><h1>404 Not Found</h1></html>")
        api_mod.begin_request(ttl=5)
        drift_mod._config_text(api, URL)
        check("a body that is not a config is not kept",
              not os.path.exists(config) and not os.path.exists(sidecar),
              "the caller refuses it; the cache keeps nothing")

        # 9. a build this workspace has PULLED.  Its config is one of the artifacts the
        #    pull fetched, so it is already on disk - and the comparison of a build that
        #    was pulled to be *run* must not ask the store for bytes it is holding.
        #    This is the step that was missing: the read went to the network with the
        #    file sitting in `var/downloads/<id>/.config`.
        pulled = Kbuild(build_id="abc123", artifacts={"_config": URL})
        here = os.path.join(layout.downloads("abc123"), ".config")
        check("a build nothing was pulled for has no local config",
              drift_mod._config_local(pulled) == "", repr(drift_mod._config_local(pulled)))
        os.makedirs(os.path.dirname(here), exist_ok=True)
        with open(here, "w", encoding="utf-8") as handle:
            handle.write(BODY)
        check("a pulled build's config is found where the pull left it",
              drift_mod._config_local(pulled) == here, here)

        drop(config, sidecar)
        api = StubApi()
        api_mod.begin_request(ttl=5)
        got = drift_mod._config_text(api, URL, drift_mod._config_local(pulled))
        check("a pulled copy answers with no request at all",
              got == BODY and api.calls == 0, f"calls={api.calls}")
        check("...and it is kept, so the next comparison is free too",
              os.path.isfile(config) and os.path.isfile(sidecar)
              and note_of(sidecar).get("url") == URL, config)

        # 10. a copy in the download tree that is NOT a config is passed over, not
        #     believed: a damaged file there must not be able to fail a comparison the
        #     artifact store can still answer.
        drop(config, sidecar)
        with open(here, "w", encoding="utf-8") as handle:
            handle.write("<html><h1>404 Not Found</h1></html>")
        api = StubApi()
        api_mod.begin_request(ttl=5)
        got = drift_mod._config_text(api, URL, drift_mod._config_local(pulled))
        check("a pulled copy that is not a config falls through to the store",
              api.calls == 1 and got == BODY, f"calls={api.calls}")
        os.remove(here)

        # 11. what the page prints (`page.analysis.fetched`): the reads that went OUT,
        #     not the ones served from this disk.  A number that counted the cache hits
        #     would tell a reader their page had just downloaded files it never asked for.
        drop(config, sidecar)
        api_mod.begin_request(ttl=5)
        drift_mod._config_text(StubApi(), URL)
        check("a read that went out is counted", api_mod.fetches() == 1,
              f"fetches={api_mod.fetches()}")
        drift_mod._config_text(StubApi(), URL)
        check("a read served from the kept copy is not counted", api_mod.fetches() == 1,
              f"fetches={api_mod.fetches()}")
    finally:
        shutil.rmtree(home, ignore_errors=True)
        os.environ.pop("KCI_WORK_DIR", None)

    print(f"\n{checks - failed}/{checks} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
