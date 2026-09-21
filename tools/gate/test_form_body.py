#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The POST body reader, exercised in both encodings a browser can send.

    test_form_body.py

`lib/gui.py::_form_body` exists because the page's own script posted
`multipart/form-data` while the server read the body with `parse_qs`, which is an
`application/x-www-form-urlencoded` parser.  It did not raise - it returned **no
fields**, so every action fell back to its defaults and `run`/`pull` were refused
with "needs at least one ticked build" however many rows were ticked.  This is the
regression test for that: the shapes below are byte-for-byte what a browser and
`curl -F` actually send, and the two refusals are the half that stops the same
silence from coming back for a third encoding.

Run it with no arguments; exit status is the verdict (the repository's own
convention - see `python3 lib/i18n.py --check lib/gui.py`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from lib import errors, gui

# What `curl -F test=boot -F selected=A -F selected=B` puts on the wire, captured.
BOUNDARY = "----formdata-undici-074213202509"
MULTIPART = (
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="test"\r\n'
    "\r\n"
    "boot\r\n"
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="selected"\r\n'
    "\r\n"
    "6aa3689720239ade90209d50\r\n"
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="selected"\r\n'
    "\r\n"
    "6aac1402fc1857a999e11514\r\n"
    f"--{BOUNDARY}--\r\n"
).encode()

MULTIPART_TYPE = f"multipart/form-data; boundary={BOUNDARY}"

CASES = (
    # name, content-type, body, expectation
    ("urlencoded, repeated names",
     "application/x-www-form-urlencoded",
     b"test=boot&selected=A&selected=B",
     {"test": ["boot"], "selected": ["A", "B"]}),
    ("urlencoded, no content-type at all",
     "", b"test=boot&selected=A",
     {"test": ["boot"], "selected": ["A"]}),
    ("urlencoded, charset on the type",
     "application/x-www-form-urlencoded; charset=UTF-8",
     b"test=boot", {"test": ["boot"]}),
    ("multipart, repeated names in order",
     MULTIPART_TYPE, MULTIPART,
     {"test": ["boot"], "selected": ["6aa3689720239ade90209d50",
                                     "6aac1402fc1857a999e11514"]}),
    ("multipart, a quoted boundary",
     f'multipart/form-data; boundary="{BOUNDARY}"', MULTIPART,
     {"test": ["boot"], "selected": ["6aa3689720239ade90209d50",
                                     "6aac1402fc1857a999e11514"]}),
    ("multipart, one field and no ticks",
     MULTIPART_TYPE,
     (f"--{BOUNDARY}\r\n"
      'Content-Disposition: form-data; name="test"\r\n'
      "\r\n"
      "kselftest-riscv\r\n"
      f"--{BOUNDARY}--\r\n").encode(),
     {"test": ["kselftest-riscv"]}),
)

# A body this cannot read must be refused, never parsed into an empty form: that
# silence is exactly what turned a missing field into a defaulted one.
REFUSED = (
    ("json", "application/json", b'{"selected":"A"}'),
    ("multipart with no boundary", "multipart/form-data",
     b'--x\r\nContent-Disposition: form-data; name="t"\r\n\r\nv\r\n--x--\r\n'),
    ("text/plain", "text/plain", b"selected=A"),
)


def main() -> int:
    failed = 0
    for name, kind, body, want in CASES:
        try:
            got = gui._form_body(kind, body, "en")
        except errors.KciError as exc:
            print(f"FAIL  {name}: refused ({exc})")
            failed += 1
            continue
        if got == want:
            print(f"ok    {name} -> {got}")
        else:
            print(f"FAIL  {name}\n        want {want}\n        got  {got}")
            failed += 1

    for name, kind, body in REFUSED:
        try:
            got = gui._form_body(kind, body, "en")
        except errors.KciError as exc:
            print(f"ok    {name} refused: {exc}")
            continue
        print(f"FAIL  {name}: read as {got} - a body it cannot read must be refused")
        failed += 1

    # The refusal is a sentence the reader sees, so it has to exist in both languages.
    for lang in ("en", "zh"):
        for key in ("error.body_not_a_form", "error.body_no_boundary"):
            try:
                said = gui.t(lang, key, kind="x")
            except Exception as exc:                            # noqa: BLE001
                print(f"FAIL  {key} [{lang}] missing: {exc}")
                failed += 1
                continue
            if not said or said == key:
                print(f"FAIL  {key} [{lang}] renders as the key itself")
                failed += 1

    total = len(CASES) + len(REFUSED) + 4
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
