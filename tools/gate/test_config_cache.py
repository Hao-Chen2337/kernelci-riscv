#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The kept-config cache: what it may reuse, and what it must refuse.

    test_config_cache.py

`lib/drift.py::_config_text` keeps each build's `.config` under `var/configs/` so
the analysis page stops re-downloading two ~194 KB files on every single load.  The
cache is safe only because of the checks that live beside it, and those checks are
what this test pins down:

* a kept copy is reused **only** if its bytes match the sha256 recorded when it was
  kept - a config truncated to 5 000 of 192 231 bytes still parses into 166 options,
  so without this the comparison answers `+5426 -8 ~1` instead of `+618 -616 ~99`,
  with zero HTTP calls and nothing on screen to say it is wrong;
* a **failure** is never kept, or one bad download becomes a permanent one;
* `?fresh=1` / `?ttl=0` really refetches, because the operator asked for a refresh
  that re-reads.

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
from lib.errors import ConfigError, KciError

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
    failed = 0

    def check(name, ok, evidence):
        nonlocal failed
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({evidence})" if evidence else ""))

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
        os.remove(config)
        os.remove(sidecar)
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
        os.remove(config)
        os.remove(sidecar)
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
    finally:
        shutil.rmtree(home, ignore_errors=True)
        os.environ.pop("KCI_WORK_DIR", None)

    print(f"\n{13 - failed}/13 checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
