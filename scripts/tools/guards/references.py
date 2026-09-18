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


def test_layers_import_downward_only():
    """The dependency table is a rule, not a description of the code.

    kcilib is layered - api, core (what every line stands on), run (one job),
    table + source (the local job table) - and docs/ARCHITECTURE.md's dependency
    table says which edges may exist.  Nothing enforced it: kcilib/core/config.py
    imported kcilib.run.jobrun for two constants, so "does core depend on the
    execution layer?" had a yes answer, and a new layer could import anything at
    all with ./run.sh verify still green (ruff checks style, compileall checks
    syntax, neither reads an import graph).  Read with ast, not a regex: these
    modules explain the rules in docstrings that name the very modules they may
    not import.

    Forbidden, and why each is a cycle or a lie:
      * run -> table / model: the execution layer is HANDED a job definition and
        must not learn where it came from (kcilib/table/build.py's docstring:
        run_node cannot tell ours from the API's), nor hold the model's cards;
      * core -> run / table / model: core is the bottom layer - api.py, table/
        and run/ all stand on it;
      * api -> anything in the package: the API client is the lowest thing there
        is (it imports the standard library and requests, nothing else);
      * table -> model: the model's Builds and the sources' views stand ON the
        table, so the table may not import them back.  The other direction is
        the layer's shape, not a violation: model/builds.py, model/jobs.py and
        model/views.py import kcilib.table (Build, BuildQuery, BuildIndex),
        which is why the rule below names the direction it bans;
      * sink -> model: kcilib/sink.py delivers a result INTO the model's
        vocabulary, so it may not import it back;
      * anything -> kcilib.model, which is what the table below enforces: the
        model (the builds and the objects a caller holds) sits on top of every
        other module here.  It used to be a separate top-level package
        (scripts/kci), which made every consumer of it import kcilib as well -
        two packages, one vocabulary, and no module that was the only face.

    kcilib/source.py and kcilib/table/{buildref,jobspec,localrun}.py are gone
    (2026-09-19): their rules went with the modules, and the things they held
    live in kcilib/model/sources.py, kcilib/table/build.py,
    kcilib/model/jobs.py's definition() and kcilib/model/views.py.
    """
    import ast
    import glob

    import kcilib

    root = kcilib.repo_root()
    package = os.path.join(root, "scripts", "kcilib")

    def imports_of(path):
        """Every module name *path* imports, with the line that imports it."""
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            found.extend((name, node.lineno) for name in names)
        return found

    # One key per module (or subtree): a second spelling of the same key would
    # REPLACE the first in a dict literal, and the replaced rule would read as
    # enforced while nothing checked it - which is how the api.py rule below was
    # silently weakened to kcilib.model before 2026-09-19.
    rules = {
        # api.py is the lowest thing in the package: it may not import kcilib at
        # all.  Naming the submodules would let `from kcilib import
        # repo_root` through, i.e. the rule would not be what its docstring says.
        os.path.join(package, "api.py"): ("kcilib",),
        os.path.join(package, "sink.py"): ("kcilib.model",),
        os.path.join(package, "core"): ("kcilib.run", "kcilib.table",
                                        "kcilib.model"),
        os.path.join(package, "run"): ("kcilib.table", "kcilib.model"),
        # The model itself is not named: it is the layer a caller holds and is
        # free to import any of the modules above (model -> table is the
        # direction the 2026-09-19 cleanup made explicit).
        os.path.join(package, "table"): ("kcilib.model",),
    }
    scanned, offenders = 0, []
    for target, banned in rules.items():
        if target.endswith(".py"):
            paths = [target]
        elif target.endswith("**"):
            paths = sorted(glob.glob(os.path.join(target[:-3], "**", "*.py"),
                                     recursive=True))
        else:
            paths = sorted(glob.glob(os.path.join(target, "*.py")))
        check(paths, f"no module found under {os.path.relpath(target, root)}; "
                     "the layering check would pass by scanning nothing")
        for path in paths:
            scanned += 1
            for name, lineno in imports_of(path):
                for module in banned:
                    if name == module or name.startswith(module + "."):
                        offenders.append(
                            f"{os.path.relpath(path, root)}:{lineno} "
                            f"imports {name}")
    check(scanned >= 15, f"only {scanned} modules scanned; the glob is wrong")
    check(not offenders,
          "a layer imports upward (see docs/ARCHITECTURE.md's dependency table); "
          "move the shared thing down instead of reaching up: "
          + ", ".join(offenders))
    print("test_layers_import_downward_only OK")


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
