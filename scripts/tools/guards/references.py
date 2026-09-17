"""A module that moved must not leave a caller - shell or python - behind."""
import os

from .support import check


def test_no_repo_root_is_counted_with_dirname():
    """The repository root is walked up to (kcilib.repo_root), never counted.

    Three tools moved into scripts/tools/ and kept a counted root, each silently
    one level too deep: render-local-config.py rendered @KCI_ROOT@ as .../scripts
    so EVERY job node came back submit_error, and callback-catcher.py defaulted
    its log to scripts/work/logs/.  All still "worked" one directory up, so the
    rule is checked here: a module-level ROOT-ish name may not be built from
    os.path.dirname().
    """
    import glob
    import re

    import kcilib

    root = kcilib.repo_root()
    check(os.path.exists(os.path.join(root, "run.sh")),
          f"repo_root() must be the directory holding run.sh, got {root}")
    pattern = re.compile(r"^\s*([A-Z_]*ROOT[A-Z_]*)\s*=\s*os\.path\.dirname", re.MULTILINE)
    offenders = []
    scanned = 0
    for path in sorted(glob.glob(os.path.join(root, "scripts", "**", "*.py"),
                                 recursive=True)):
        scanned += 1
        with open(path, encoding="utf-8") as handle:
            for match in pattern.finditer(handle.read()):
                offenders.append(f"{os.path.relpath(path, root)}:{match.group(1)}")
    check(scanned > 10, f"only {scanned} python files scanned; the glob is wrong")
    check(not offenders,
          "a repo-root constant is built by counting dirname() levels; use "
          "kcilib.repo_root() instead (moving the file breaks the count "
          "silently): " + ", ".join(offenders))
    print("test_no_repo_root_is_counted_with_dirname OK")


def test_shell_scripts_reference_live_modules():
    """A file that moves must not leave a shell caller on the old path.

    scripts/run-local-stack.sh kept calling `python3 -m kcilib.ports` after
    ports.py moved into kcilib/core/, so `./run.sh stack` died at its first port
    check and no gate noticed.  Checked: every `python3 -m kcilib.<x>` must
    import, and every flat `scripts/<name>.py` must exist.
    """
    import glob
    import importlib.util
    import re

    import kcilib

    root = kcilib.repo_root()
    shells = [os.path.join(root, "run.sh")]
    shells += sorted(glob.glob(os.path.join(root, "scripts", "*.sh")))
    check(len(shells) > 1, f"expected run.sh and scripts/*.sh, found {shells}")

    module_re = re.compile(r"python3\s+-m\s+(kcilib(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
    flat_re = re.compile(r"scripts/([A-Za-z0-9_.-]+\.py)")
    modules = paths = 0
    for shell in shells:
        rel = os.path.relpath(shell, root)
        with open(shell, encoding="utf-8") as handle:
            text = handle.read()
        for name in module_re.findall(text):
            modules += 1
            check(importlib.util.find_spec(name) is not None,
                  f"{rel} runs `python3 -m {name}`, which does not import: "
                  f"the module moved (check the sub-package it lives in now)")
        for name in flat_re.findall(text):
            paths += 1
            check(os.path.exists(os.path.join(root, "scripts", name)),
                  f"{rel} refers to scripts/{name}, which does not exist: it "
                  f"moved (the offline tools live in scripts/tools/)")
    # Both patterns must match something, or this guard passes by finding
    # nothing the day the call sites are rewritten.
    check(modules >= 1, "no `python3 -m kcilib.*` reference found; the pattern is stale")
    check(paths >= 1, "no flat scripts/*.py reference found; the pattern is stale")
    print("test_shell_scripts_reference_live_modules OK")
