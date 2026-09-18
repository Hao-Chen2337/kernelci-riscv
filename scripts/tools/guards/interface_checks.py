"""The interface layer's driving classes: the stack, the page and the ledger.

kci is thin by construction - Stack runs ./run.sh's own subcommands, Dashboard
runs scripts/dashboard.py, Results reads kcilib.core.ledger - so what a guard
can pin is the exact command line each class runs and the fact that run.sh
really accepts it.  Nothing here starts a stack, a page or a test: every argv
is asserted, never executed, and the two subprocesses that ARE run (the report
and the probes) are offline one-shots against a temporary ledger.
"""
import ast
import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import kcilib
import kcilib.model.dashboard as dashboard_module
import kcilib.model.stack as stack_module
from kcilib.core import ledger
from kcilib.model import Dashboard, Record, Results, Stack

from .support import check


def _shell_default(path, var):
    """The ${VAR:-N} default run.sh / run-local-stack.sh spells for *var*."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"\$\{" + var + r":-(\d+)\}", text)
    return int(match.group(1)) if match else None


def _imports(path):
    """Every ABSOLUTE module name *path* imports, with the importing line.

    A relative import (``from .jobs import ...``, level > 0) names a module of
    the importing package itself, so it is not a dependency on anything
    outside it and would only make the rules below read the package's own
    files as if they were somewhere else.
    """
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        found.extend((name, node.lineno) for name in names)
    return found


def _script_module_names(root):
    """The module names scripts/ itself holds (files and packages)."""
    names = set()
    for entry in os.listdir(os.path.join(root, "scripts")):
        path = os.path.join(root, "scripts", entry)
        if entry.endswith(".py"):
            names.add(entry[: -len(".py")].replace("-", "_"))
        elif os.path.exists(os.path.join(path, "__init__.py")):
            names.add(entry.replace("-", "_"))
    return names


def test_stack_argv_matches_the_entry_point():
    """Every Stack command is one ./run.sh really has, spelled once.

    The class is an interface to the shell: if it assembled its own compose
    call, or named a subcommand run.sh does not dispatch, the stack would
    either run something else or fail at the first call.  Each argv is compared
    as a LIST (so a reordered argument is a failure), and each subcommand is
    also looked up in run.sh's own dispatch - and --seed in the script that
    consumes it - so this cannot pass against a shell that moved on.
    """
    root = Path(kcilib.repo_root())
    stack = Stack(root=root, project="kci-guard")
    check(stack.pid_file == root / "work" / "env" / "stack-kci-guard.pids",
          "the pid file is not the one run-local-stack.sh writes: "
          f"{stack.pid_file}")
    run_sh = str(root / "run.sh")

    commands = (
        (("stack",), [run_sh, "stack"]),
        (("stack", "--seed"), [run_sh, "stack", "--seed"]),
        (("stop",), [run_sh, "stop"]),
        (("report",), [run_sh, "report"]),
        (("verify",), [run_sh, "verify"]),
    )
    # A table this short would make the loop below vacuous.
    check(len(commands) >= 5, f"only {len(commands)} command lines checked")
    checked = 0
    for args, argv in commands:
        check(stack._argv(*args) == argv,
              f"Stack._argv{args} is {stack._argv(*args)}, not {argv}")
        checked += 1
    shell = (root / "run.sh").read_text(encoding="utf-8")
    for args, _argv in commands:
        subcommand = args[0]
        check(re.search(rf"^\s*{subcommand}\)", shell, re.MULTILINE),
              f"run.sh does not dispatch {subcommand!r} any more")
    stack_sh = (root / "scripts" / "run-local-stack.sh").read_text(
        encoding="utf-8")
    check("--seed" in stack_sh,
          "scripts/run-local-stack.sh no longer takes --seed, which "
          "Stack.start(seed=True) depends on")

    # worker_once() and the argv-only methods, through a recorder: the exit
    # status must survive, and nothing may actually run.
    seen = []

    def recorder(*args, **kwargs):
        argv = stack._argv(*args)
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    real_run = stack._run
    stack._run = recorder
    try:
        check(stack.worker_once() == 0,
              "worker_once must return run.sh's status")
        check(stack.worker_once(job="kvm", limit="1") == 0,
              "worker_once lost its status")
        check(stack.worker_once(kvm_full="") == 0,
              "worker_once lost its status")
        check(stack.start(seed=True)["argv"] == [run_sh, "stack", "--seed"],
              "start(seed=True) is not `run.sh stack --seed`")
        check(stack.stop()["ok"] is True, "stop() must report run.sh's status")
    finally:
        stack._run = real_run
    expected = [
        [run_sh, "worker", "--once"],
        [run_sh, "worker", "--once", "--job", "kvm", "--limit", "1"],
        [run_sh, "worker", "--once", "--kvm-full"],
    ]
    check(seen[:3] == expected, f"the worker flags changed: {seen[:3]}")
    check(len(seen) >= 5, f"only {len(seen)} command lines recorded")

    # The ports are run.sh's, and so are the log paths run-local-stack.sh
    # redirects to: both are read out of the shell here, not trusted.
    for var, default, path in (
        (stack_module.API_PORT_VAR, stack_module.API_PORT, root / "run.sh"),
        (stack_module.ARTIFACT_PORT_VAR, stack_module.ARTIFACT_PORT,
         root / "scripts" / "run-local-stack.sh"),
        (stack_module.CALLBACK_PORT_VAR, stack_module.CALLBACK_PORT,
         root / "scripts" / "run-local-stack.sh"),
    ):
        found = _shell_default(path, var)
        check(found == default,
              f"{path.name} defaults {var} to {found}, not {default}")
    saved = {name: os.environ.pop(name, None)
             for name in ("KCI_API_URL", "KCI_API_PORT")}
    try:
        check(stack.api_url == "http://127.0.0.1:8001",
              f"the API default is not run.sh's: {stack.api_url}")
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
    check(stack.artifact_url == "http://127.0.0.1:8999",
          f"the artifact URL is not the shell's: {stack.artifact_url}")
    check(stack.callback_url == "http://127.0.0.1:8003",
          f"the callback URL is not the shell's: {stack.callback_url}")
    check(stack._log_path("artifact") == Path("/tmp/fs8999.log"),
          f"the artifact log moved: {stack._log_path('artifact')}")
    check(stack._log_path("callback") == Path("/tmp/cb8003.log"),
          f"the callback log moved: {stack._log_path('callback')}")
    check(stack._log_path("scheduler") == Path("/tmp/sched-local.log"),
          f"the scheduler log moved: {stack._log_path('scheduler')}")
    check("/tmp/fs$SERVE_PORT.log" in stack_sh
          and "/tmp/cb$CB_PORT.log" in stack_sh,
          "run-local-stack.sh no longer writes the helper logs this "
          "class reads")
    try:
        stack._log_path("nope")
    except ValueError as refusal:
        check("nope" in str(refusal),
              f"the refusal must name the service: {refusal}")
    else:
        check(False, "an unknown service name must raise, not answer []")

    # $KCI_*_PORT moves the URLs the caller connects to, exactly as the shell.
    os.environ["KCI_SERVE_PORT"] = "18999"
    os.environ["KCI_CB_PORT"] = "18003"
    try:
        check(stack.artifact_url == "http://127.0.0.1:18999",
              f"KCI_SERVE_PORT ignored: {stack.artifact_url}")
        check(stack.callback_url == "http://127.0.0.1:18003",
              f"KCI_CB_PORT ignored: {stack.callback_url}")
    finally:
        del os.environ["KCI_SERVE_PORT"]
        del os.environ["KCI_CB_PORT"]
    check(checked + len(seen) >= 8, "too few command lines were checked")
    print("test_stack_argv_matches_the_entry_point OK")


def test_stack_status_reads_a_stopped_stack():
    """status() is a read: on a checkout with no stack it answers, not raises.

    Run against a temporary root and a compose project nobody uses, so the
    answer is "nothing of ours" - no containers, no services - and the three
    ports probed through kcilib.core.ports.  Then the pid file the shell writes
    is read back, live pid and dead pid both: a record outlives its process,
    and a status that cannot say "gone" hides a stopped service.
    """
    root = Path(tempfile.mkdtemp())
    stack = Stack(root=root, project="kci-guard-none")
    status = stack.status()
    for key in ("project", "pid_file", "containers", "services", "listening"):
        check(key in status, f"status() must report {key}: {sorted(status)}")
    check(status["project"] == "kci-guard-none", status["project"])
    check(status["pid_file"] == str(stack.pid_file), status["pid_file"])
    check(status["containers"] == [],
          "a project nobody started has no containers: "
          f"{status['containers']}")
    check(status["services"] == [],
          f"and no recorded services: {status['services']}")
    listening = status["listening"]
    check(len(status) >= 5, f"status() reported only {sorted(status)}")
    check(sorted(listening) == ["api", "artifact", "callback"],
          f"status() must report the three ports: {sorted(listening)}")
    check(all(isinstance(value, bool) for value in listening.values()),
          f"a port answer is a boolean: {listening}")

    stack.pid_file.parent.mkdir(parents=True, exist_ok=True)
    stack.pid_file.write_text(
        f"artifact server|{os.getpid()}|0|http\\.server 8999\n"
        "scheduler|999999999|0|scheduler\\.py\n"
        "no-pipe-here\n", encoding="utf-8")
    services = stack.status()["services"]
    check(len(services) == 2,
          f"a malformed line must be skipped, got {services}")
    check(any("artifact server" in line and "alive" in line
              for line in services),
          f"a live pid must read as alive: {services}")
    check(any("scheduler" in line and "gone" in line for line in services),
          f"a vanished pid must read as gone: {services}")
    print("test_stack_status_reads_a_stopped_stack OK")


def test_dashboard_argv_and_banner():
    """The page runs the command ./run.sh dashboard runs, and the URL is read.

    --port is a preference - a taken port moves the page to the next free one -
    so start() cannot assume it: the URL comes from the page's own banner.  The
    banner text is read out of scripts/dashboard.py here, so rewording it fails
    this guard instead of silently making every start() report a port the page
    may not be on.  Nothing is started: the read-back is checked on the banner
    text itself.
    """
    root = Path(kcilib.repo_root())
    page = Dashboard()
    asked = Dashboard(port=8123, api_url="http://127.0.0.1:8001", rows=12)
    checked = 0
    for argv, expected in (
        (page._argv(),
         [sys.executable, str(root / "scripts" / "dashboard.py"), "--port",
          "8079"]),
        (asked._argv(),
         [sys.executable, str(root / "scripts" / "dashboard.py"), "--port",
          "8123", "--api-url", "http://127.0.0.1:8001", "--rows", "12"]),
    ):
        check(argv == expected, f"the page command line changed: {argv}")
        checked += 1
    check(checked >= 2, f"only {checked} command lines checked")
    check(page.url == "http://127.0.0.1:8079/",
          f"the preferred URL is not the documented one: {page.url}")
    check(page.is_up() is False, "nothing was started, so nothing is up")
    check(page.stop() == 0, "stopping a page that never started must answer 0")
    check("--host" not in page._argv(),
          "the page must keep its own 127.0.0.1 default")

    source = (root / "scripts" / "dashboard.py").read_text(encoding="utf-8")
    check(dashboard_module.BANNER in source,
          "scripts/dashboard.py no longer prints the banner this class reads "
          f"back: it looks for {dashboard_module.BANNER!r}")
    line = (f"{dashboard_module.BANNER}http://127.0.0.1:8081/ "
            "(Ctrl-C to stop; /summary.json for machines)")
    check(dashboard_module._url_in(line) == "http://127.0.0.1:8081/",
          "the banner reader lost the URL: "
          f"{dashboard_module._url_in(line)!r}")
    check(dashboard_module._url_in("port 8079 is in use") == "",
          "a line that is not the banner must not be read as a URL")
    print("test_dashboard_argv_and_banner OK")


def test_results_reads_the_ledger_and_its_report():
    """Results reads what kcilib.core.ledger wrote; its text is the script's.

    Run against a temporary KCI_RESULTS_DIR - the ledger's own variable - so
    the answer for a ledger that does not exist yet is empty and not an
    error, and a record written through the ledger's writer comes back
    through the report ./run.sh results runs.  The class can then have no
    second idea of what a record is, nor of how one is printed.
    """
    root = Path(kcilib.repo_root())
    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get(ledger.RESULTS_DIR_ENV)
        os.environ[ledger.RESULTS_DIR_ENV] = tmp
        try:
            results = Results()
            check(results._argv("results")
                  == [str(root / "run.sh"), "results"],
                  "the report command line changed: "
                  f"{results._argv('results')}")
            check(results.builds() == [],
                  f"an empty ledger has no builds: {results.builds()}")
            check(results.rows("no-such-build") == [],
                  results.rows("no-such-build"))
            check(results.latest() == [], results.latest())
            empty = results.text()
            check("no result records in" in empty,
                  f"the empty report changed: {empty!r}")
            check(tmp in empty,
                  f"the report must name the ledger: {empty!r}")

            ledger.write_result("a1b2c3", "boot", {"verdict": "pass",
                                                   "exit_code": 0,
                                                   "source": "table"})
            rows = results.rows("a1b2c3")
            check(len(rows) == 1, f"one record, one row: {rows}")
            record = rows[0]
            check(isinstance(record, Record),
                  f"a row is not a Record: {type(record)}")
            fields = 0
            for read, expected in ((record.verdict, "pass"),
                                   (record.build_id, "a1b2c3"),
                                   (record.test, "boot"),
                                   (record.source, "table"),
                                   (record.exit_code, 0)):
                check(read == expected, f"a record field read back {read!r}, "
                                        f"not {expected!r}")
                fields += 1
            check(fields >= 5, f"only {fields} record fields checked")
            check(record.is_pass(),
                  f"the verdict did not survive: {record.verdict}")
            check(record.as_dict()["verdict"] == "pass",
                  "as_dict is not the ledger's document: "
                  f"{record.as_dict()}")
            check(results.builds() == ["a1b2c3"], results.builds())
            check([row.build_id for row in results.latest(3)] == ["a1b2c3"],
                  results.latest(3))
            same = Results(results_dir=Path(tmp))
            check(same.builds() == ["a1b2c3"],
                  "an explicit results_dir must read the same ledger: "
                  f"{same.builds()}")
            text = results.text()
            check("a1b2c3" in text and "1 pass" in text,
                  f"the report lost the run: {text!r}")
        finally:
            if previous is None:
                os.environ.pop(ledger.RESULTS_DIR_ENV, None)
            else:
                os.environ[ledger.RESULTS_DIR_ENV] = previous
    print("test_results_reads_the_ledger_and_its_report OK")


def test_interface_package_imports_nothing_from_scripts():
    """kci stands on kcilib and the standard library, and on nothing else.

    It reaches the stack, the page and the report by RUNNING them: an import of
    scripts/dashboard.py, scripts/results.py or scripts/tools/* would make
    those scripts part of the interface's dependency graph - a call path
    no gate keeps in step with the command the operator runs.  Both halves
    are checked: every top-level name kci imports is standard-library (or
    kcilib, or kci itself), and the same rule is stated against the module
    names scripts/ actually holds, so a script cannot quietly become
    importable interface code.
    """
    root = Path(kcilib.repo_root())
    modules = sorted(glob.glob(
        os.path.join(root, "scripts", "kcilib", "model", "**", "*.py"),
                                 recursive=True))
    check(len(modules) >= 3,
          f"only {len(modules)} modules under scripts/kcilib/model")
    allowed = set(sys.stdlib_module_names) | {"kcilib", "kci"}
    imported, offenders = 0, []
    for path in modules:
        for name, lineno in _imports(path):
            imported += 1
            if name.split(".")[0] not in allowed:
                offenders.append(f"{os.path.relpath(path, root)}:{lineno} "
                                 f"imports {name}")
    check(imported >= 10,
          f"only {imported} imports scanned; the reader is wrong")
    check(not offenders,
          "the interface layer may import kcilib and the standard library "
          "only (run a script, do not import it): " + ", ".join(offenders))

    script_modules = _script_module_names(root)
    banned = sorted(script_modules - set(sys.stdlib_module_names)
                    - {"kci", "kcilib"})
    check(len(banned) >= 3,
          f"the scripts/ module list looks wrong: {sorted(script_modules)}")
    for path in modules:
        for name, lineno in _imports(path):
            check(name.split(".")[0] not in banned,
                  f"{os.path.relpath(path, root)}:{lineno} imports the script "
                  f"module {name!r}; run it instead of importing it")
    print("test_interface_package_imports_nothing_from_scripts OK")


def test_interface_exports_its_public_names():
    """`from kcilib.model import ...` is the model, and __all__ is its list.

    The classes added for the stack, the page and the ledger - and the classes
    the project's one-line usage needs - must be exported, and every
    exported name has to exist on the package: a name in __all__ that does
    not breaks `from kcilib.model import *` for every caller at once.

    The names are the 2026-09-19 vocabulary: the one build class is Build and
    the collection is Builds (Kbuild/Kbuilds, BuildRef and JobSpec are gone), so
    the removed spellings are checked too - a caller that still writes
    ``from kcilib.model import Kbuild`` must fail loudly at the import, not
    quietly get a second class back.
    """
    from kcilib import model as kci

    for name in ("Build", "Builds", "Dashboard", "Job", "Jobs", "Outcome",
                 "Record", "Results", "Stack"):
        check(name in kci.__all__, f"{name} is not exported: {kci.__all__}")
        check(hasattr(kci, name),
              f"kcilib.model.__all__ names {name}, which does not exist")
    for gone in ("Kbuild", "Kbuilds", "BuildRef", "JobSpec"):
        check(gone not in kci.__all__ and not hasattr(kci, gone),
              f"{gone} was renamed away (Build / Builds / Job) and must not "
              f"come back as a second name for the same thing: {kci.__all__}")
    check(len(kci.__all__) == len(set(kci.__all__)),
          f"duplicate names in __all__: {kci.__all__}")
    check(len(kci.__all__) >= 16, f"__all__ shrank to {len(kci.__all__)}")
    for name in ("Dashboard", "Record", "Results", "Stack"):
        module = getattr(kci, name).__module__
        check(module.startswith("kcilib.model."),
              f"{name} is not defined in kci: {module}")
    # Build is defined by the table layer and re-exported here: one class, one
    # definition, so `kcilib.table.build.Build is kcilib.model.Build`.
    check(kci.Build.__module__ == "kcilib.table.build"
          and kci.Builds.__module__ == "kcilib.model.builds",
          f"Build/Builds are not the table's/model's own: "
          f"{kci.Build.__module__}, {kci.Builds.__module__}")
    print("test_interface_exports_its_public_names OK")
