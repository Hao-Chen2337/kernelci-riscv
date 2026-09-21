#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The shape of this tree, as checks: one owner per thing, and no second exit path.

    python3 tools/gate/check_structure.py     # exit 1 on the first failure

`ruff` reads style, `smoke_pages.py` draws the pages, `verify_callback_body.py`
parses the body with the real upstream parser.  None of them can see the thing
that actually rots in a tree like this one: **the same decision made in two
places**.  The old tree's guard suite pinned exactly that for `kcilib` (one argv
builder, one ledger writer, one exit, paths only from `layout`), and it is going
away with `kcilib` - so the invariants that are *also true of `lib/`* are checked
here, from the day the old gate is deleted.

Five checks, each one a fact this tree promises in prose:

1. **every entry point turns a `KciError` into its exit code.**  A bad flag, a dead
   API or a corrupt ledger is `X <why>` and exit 3; a traceback means exit 1, which
   is the code that says "a test failed".  Three entries were missing this when the
   check was written (`results.py`, `pull_worker.py`, `gui.py`) - and `results.py`
   could really produce it, because the ledger reader raises on a record it cannot
   parse.
2. **one ledger writer**: `lib/sink.py`.  History is the one thing here that cannot
   be regenerated, and two writers means two ideas about the record's key set.
3. **one tuxrun command line**: `lib/runner.py` reads `config.tuxrun_bin`, and
   nothing else does.  The flag order and the omission rules are a byte-level
   contract with tuxrun; a second assembly point is how they drift.
4. **paths come from `lib/layout.py`**: no other module builds a path out of a
   workspace directory name.  A moved directory is then one edit, not a hunt.
5. **the callback body has one builder** (`lib/sink.py: lava_body`), and **every
   entry point answers `--help`** - a tree whose front door cannot print its own
   usage is broken in a way no import check sees.

What this deliberately does not do: read the *behaviour* of a run (that is
`var/results/`, the page and the fixtures), or check anything under `scripts/`
(that tree is deleted; its gate went with it).
"""

import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "lib")
TOOLS = os.path.dirname(os.path.abspath(__file__))

# The entry points: every root-level `*.py` except this repository's tooling.
ENTRIES = sorted(name for name in os.listdir(ROOT)
                 if name.endswith(".py") and os.path.isfile(os.path.join(ROOT, name)))

# The one module allowed to write a record, and the one allowed to name tuxrun.
LEDGER_OWNER = "sink.py"
ARGV_OWNER = "runner.py"
BODY_OWNER = "sink.py"

# The directories `lib/layout.py` owns.  A literal one of these used as a path
# component anywhere else means a caller is spelling a workspace path itself.
WORKSPACE_NAMES = ("results", "downloads", "baked", "logs", "state", "serve",
                   "workspaces", "runs", "env", "configs")

# Calls that take a path.  Only their *string literal* arguments are judged.
PATH_CALLS = ("join", "isdir", "isfile", "exists", "makedirs", "open", "remove",
              "rmtree", "listdir", "abspath", "dirname", "read_text", "write_text")

CHECKS = 0


def check(condition, message):
    global CHECKS
    CHECKS += 1
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def modules():
    """`[(name, path, tree)]` for every module of `lib/`, packages included.

    **Walked, not listed.**  This used `os.listdir(LIB)` and kept only `*.py`, so
    when `lib/gui.py` became the package `lib/gui/` the whole thing - 28 modules,
    ~9.4k lines - left the checker's view **without one check going red**: every
    invariant below (one ledger writer, one tuxrun reader, paths only from
    `lib/layout.py`, one `lava_body`) silently stopped covering it.  A gate that
    goes quiet when code moves is worse than no gate, because the count still
    prints OK.

    `name` is the path **relative to `lib/`**, so a top-level module keeps the
    bare name the checks compare against (`name == "layout.py"`, `"sink.py"`) and
    a package member reads `gui/app.py`.
    """
    found = []
    for root, dirs, files in os.walk(LIB):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for filename in sorted(files):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            name = os.path.relpath(path, LIB)
            with open(path, encoding="utf-8") as handle:
                found.append((name, path, ast.parse(handle.read(), filename=path)))
    check(len(found) >= 15, f"only {len(found)} modules under lib/; the reader is wrong")
    return found


def entry_tree(name):
    path = os.path.join(ROOT, name)
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def calls(tree):
    """Every call node in a module, as `(node, unparsed-callee)`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node, ast.unparse(node.func)


def function(tree, name):
    """The `def name(...)` node of a module, or None."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def check_entry_exit_contract():
    """Check 1: `main()` catches `KciError`, prints one line, returns its exit code."""
    for name in ENTRIES:
        tree = entry_tree(name)
        main = function(tree, "main")
        check(main is not None, f"{name} has no main()")
        handled = [node for node in ast.walk(main) if isinstance(node, ast.ExceptHandler)
                   and node.type is not None
                   and "KciError" in ast.unparse(node.type)]
        check(handled, f"{name}: main() does not catch errors.KciError - a bad flag, a "
                       "dead API or a corrupt ledger would traceback (exit 1)")
        body = ast.unparse(handled[0])
        check("exc.exit_code" in body,
              f"{name}: the handler does not return the error's own exit code")
        check("sys.stderr" in body,
              f"{name}: the handler does not print to stderr (a machine reads stdout)")
    print(f"check 1 OK: {len(ENTRIES)} entry point(s) turn a KciError into an exit code")


def check_one_ledger_writer():
    """Check 2: only `lib/sink.py` writes a record."""
    offenders = []
    for name, _path, tree in modules():
        if name == LEDGER_OWNER:
            continue
        for node, callee in calls(tree):
            if callee.rsplit(".", 1)[-1] not in ("open", "replace", "makedirs",
                                                 "remove", "rmtree", "write_text"):
                continue
            # A write whose path is built from the ledger's own accessor.
            if "layout.results" in ast.unparse(node):
                offenders.append(f"{name}:{node.lineno} {ast.unparse(node)[:70]}")
    check(not offenders,
          "a second module writes the ledger (owner: lib/sink.py): " + "; ".join(offenders))
    print(f"check 2 OK: {LEDGER_OWNER} is the only module that writes a record")


# The module that *declares* the run configuration: it owns the field name and the
# flag that fills it, so it is not a second reader.  Every other module that reads
# `tuxrun_bin` must be the argv builder.
CONFIG_OWNER = "config.py"


def check_one_tuxrun_command_line():
    """Check 3: outside the config that declares it, only the argv builder reads it."""
    readers = set()
    for name, _path, tree in modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "tuxrun_bin":
                readers.add(name)
    readers.discard(CONFIG_OWNER)
    check(sorted(readers) == [ARGV_OWNER],
          f"the tuxrun binary is read by {sorted(readers)}; {CONFIG_OWNER} owns the "
          f"name and {ARGV_OWNER} must be its only reader (the flag order is a "
          "byte-level contract with tuxrun)")
    print(f"check 3 OK: {ARGV_OWNER} is the only reader of the tuxrun binary")


def check_layout_owns_paths():
    """Check 4: no module outside `lib/layout.py` spells a workspace path."""
    offenders = []
    for name, _path, tree in modules():
        if name == "layout.py":
            continue
        for node, callee in calls(tree):
            if callee.rsplit(".", 1)[-1] not in PATH_CALLS:
                continue
            for arg in node.args:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                if arg.value in WORKSPACE_NAMES:
                    offenders.append(f"{name}:{node.lineno} {ast.unparse(node)[:70]}")
    check(not offenders,
          "a module builds a workspace path itself (owner: lib/layout.py): "
          + "; ".join(offenders))
    print("check 4 OK: layout.py is the only module that spells a workspace path")


def check_one_body_and_help():
    """Check 5: one `lava_body`, and every entry point answers `--help`."""
    definitions = []
    for name, _path, tree in modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "lava_body":
                definitions.append(name)
    check(definitions == [BODY_OWNER],
          f"lava_body is defined in {definitions}; the body has one builder ({BODY_OWNER})")
    for name in ENTRIES:
        result = subprocess.run([sys.executable, os.path.join(ROOT, name), "--help"],
                                capture_output=True, text=True, timeout=60, check=False)
        check(result.returncode == 0,
              f"{name} --help exited {result.returncode}: "
              f"{(result.stderr or result.stdout).strip().splitlines()[-1:] }")
        check("usage" in result.stdout.lower(),
              f"{name} --help printed no usage line")
    print(f"check 5 OK: one lava_body, and {len(ENTRIES)} entry point(s) print their usage")


def main():
    check_entry_exit_contract()
    check_one_ledger_writer()
    check_one_tuxrun_command_line()
    check_layout_owns_paths()
    check_one_body_and_help()
    print(f"\nALL STRUCTURE CHECKS PASSED ({CHECKS} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
