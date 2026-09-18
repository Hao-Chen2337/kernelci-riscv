"""One decision, one implementation: the structural half of the phase-1 cleanup.

docs/REFACTOR-D-BRIEF.md §1.3 lists seven places where one job had two
implementations and §5's 1-g row asks for the structural rule that keeps them
from growing back ("不许出现第二份下载/烤盘/写账本实现").  Three of the seven are
pinned here - each of them a second copy that no behavioural test can see,
because a second copy behaves the same until the day it does not:

  * the tuxrun command line and its execution (§1.3 #2: jobrun.run_node and
    fetch's run_once each assembled the same argv).  Owner:
    kcilib/run/runner.py, which now holds the single build_tuxrun_argv() and the
    single run_tuxrun();
  * the result's exit (§1.3 #6: poll.py posted a result itself, beside
    kcilib/sink.py).  Owner: kcilib/sink.py, the one caller of
    kcilib.run.callback.post_result();
  * the ledger write (§1.3 #4: fetch wrote records itself, beside
    kcilib.run.jobrun.record_result).  Owner: kcilib/core/ledger.py, reached
    only from the run layer and the interface layer.

Read with ast, not a regex: every module here explains the rule in a docstring
that names the very function it must not call (sink.py's "neither caller holds an
idea of its own about where a result goes", jobs.py's "kcilib.run.runner.run_tuxrun
with the one-shot line's separator"), and a regex cannot tell a sentence from a
call.  What each rule pins is a CLOSED SET OF CALLERS: a new caller has to be
written into this file, which is the point - "who is allowed to do this?" is a
decision, and a decision nobody wrote down is how the second copy appears.

Deliberately NOT checked, and why each would be worse than no check:
  * whether two call sites of the SAME function are two implementations.  They
    are not: run_tuxrun is reached three times (the worker's run_command, the
    table/served command step, the one-shot line's console seam), every one of
    them the owner's own function through an import of kcilib.run - which is
    what this guard proves per call site.  A second implementation would be a
    second DEFINITION or a second process spawn, and both of those are pinned;
  * a call site whose spelling this guard cannot resolve to an import (a
    callable passed around, ``getattr(runner, "run_tuxrun")(...)``, or the
    owner's function bound to another name - ``fn = runner.run_tuxrun; fn()``).
    The first two are read as calls and reported as strangers, so they fail;
    the third is spelled under a name that is not the symbol's, so nothing is
    read at all - which is why every rule here also pins the DEFINITION and the
    process, not only the call;
  * an argv assembled in a variable and handed to a spawn in another module.
    The spawn itself is read here (its first element is checked when it is
    spelled there), but a chain of variables is not followed - that is what the
    entry-point rule below is for: the one-shot line may not spawn at all.
"""
import ast
import glob
import os

from .support import check

# Repo-relative paths, built with os.path.join: the comparison below is against
# os.path.relpath(path, repo_root()), which always keeps the "scripts/" segment,
# so an exemption spelled without it would silently match nothing (the trap
# layout_policy_checks documents for its own owner constant).
_SCRIPTS = "scripts"

# The one module that owns the tuxrun command line, its execution, and (below)
# the only place a tuxrun process may be started at all.
_RUNNER = os.path.join(_SCRIPTS, "kcilib", "run", "runner.py")

# The one-shot line: §1.3's fetch entry point, whose second copy of the run path
# was deleted in phase 1.  It is named here (not just left out of the caller
# sets) because the failure message has to send its author somewhere.
_ENTRY_POINT = os.path.join(_SCRIPTS, "fetch-and-run-latest.py")

# Closed caller sets.  Each tuple is the whole list; a new entry means editing
# this file, deliberately.
_ARGV_CALLERS = (os.path.join(_SCRIPTS, "kcilib", "run", "jobrun.py"),)
_RUN_CALLERS = (
    # run_command(): the worker's and the table line's command step.
    os.path.join(_SCRIPTS, "kcilib", "run", "jobrun.py"),
    # kci/jobs.py: the one-shot line's console seam (_fetch_console) and its
    # command step (_oneshot_run_command).  Two call sites, one executor: both
    # call the owner's function, and neither assembles an argv of its own.
    os.path.join(_SCRIPTS, "kcilib", "model", "jobs.py"),
)
_POST_RESULT_CALLERS = (os.path.join(_SCRIPTS, "kcilib", "sink.py"),)
_WRITE_RESULT_CALLERS = (
    # The worker's and the table line's naming of a run.
    os.path.join(_SCRIPTS, "kcilib", "run", "jobrun.py"),
    # The interface layer's naming of a run (kci.Job.record), which is how the
    # fetch entry point files its record without writing the ledger itself.
    os.path.join(_SCRIPTS, "kcilib", "model", "jobs.py"),
)

# Dotted spellings of the ONE function behind each symbol, as a call site
# reaches it.  Two spellings for run_tuxrun: kcilib.run.jobrun re-exports the
# runner's function - it defines none of its own, which the definition check
# below proves - and that re-export is the rebindable seam the served line and
# the guards themselves re-bind.
_ARGV_REACHES = ("kcilib.run.runner.build_tuxrun_argv",)
_RUN_REACHES = ("kcilib.run.runner.run_tuxrun", "kcilib.run.jobrun.run_tuxrun")
_POST_REACHES = ("kcilib.run.callback.post_result",)
_WRITE_REACHES = ("kcilib.core.ledger.write_result",)

# The floor under the whole-tree scan: scripts/ holds 45 modules outside the
# guards (references.py keeps a >= 15 floor for the same reason).  A glob that
# stops matching is a broken guard, not a clean tree.
_MODULES_FLOOR = 30

# What "start a process" looks like from a module that is not the runner.
_SPAWN_SUBMODULE = "subprocess"
_SPAWN_ATTRS = ("run", "Popen", "call", "check_call", "check_output",
                "getoutput", "getstatusoutput")
# The ways around subprocess that a second executor would reach for.
_OS_SPAWN_ATTRS = ("system", "popen", "fork", "forkpty", "posix_spawn",
                   "spawnv", "spawnve", "spawnvp", "spawnl", "spawnle",
                   "spawnlp", "execl", "execle", "execlp", "execlpe",
                   "execv", "execve", "execvp", "execvpe")

# The ledger's own accessors, for the rule that no module may open a record for
# writing by hand.  Matched against the unparsed path argument.
_LEDGER_ACCESSORS = ("result_path(", "results_dir(")
_WRITE_MODES = ("w", "a", "x", "+")


def _modules(root):
    """(repo-relative path, tree) for every module under scripts/ this guard reads.

    The guards' own modules are excluded: they call these very symbols
    (kcilib.run.callback.post_result, kcilib.core.ledger.write_result) to test
    what happens around them, so reading them here would make this guard
    describe the tests instead of the code.
    """
    guards = os.path.join(root, "scripts", "tools", "guards")
    found = []
    for path in sorted(glob.glob(os.path.join(root, "scripts", "**", "*.py"),
                                 recursive=True)):
        if "__pycache__" in path:
            continue
        if os.path.abspath(path).startswith(guards + os.sep):
            continue
        relative = os.path.relpath(path, root)
        with open(path, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read(), filename=path)
            except SyntaxError as error:
                check(False, f"{relative} does not parse, so this guard is "
                             f"reading nothing where code used to be: {error}")
        found.append((relative, tree))
    check(len(found) >= _MODULES_FLOOR,
          f"only {len(found)} modules scanned; the glob is wrong, so this "
          "guard would pass by reading nothing")
    return found


def _definitions(modules, name):
    """Every module that defines a function called *name*, as [(rel, lineno)]."""
    found = []
    for path, tree in modules:
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name):
                found.append((path, node.lineno))
    return found


def _dotted(node):
    """The dotted spelling of a Name/Attribute chain, or None for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _bindings(tree):
    """One module's imports, as two maps from the local name to what it names.

    *symbols* is for the from-import of a function: ``from kcilib.run.runner
    import run_tuxrun`` (and its aliased spelling) maps "run_tuxrun" to
    "kcilib.run.runner.run_tuxrun".  *modules* is for the spellings that reach a
    function through its module: an aliased import maps the alias to the module,
    a plain ``import a.b.c`` maps the head name "a" to "a" (what Python binds),
    and ``from kcilib.run import callback`` maps "callback" to the submodule
    kcilib.run.callback - which is what makes callback.post_result resolvable.
    """
    symbols, modules = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                symbols[local] = f"{node.module}.{alias.name}"
                modules[local] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    # `import a.b.c` binds "a" alone; appending the rest of the
                    # spelling back on is what _resolves_to does below.
                    modules[alias.name.split(".")[0]] = alias.name.split(".")[0]
    return symbols, modules


def _resolves_to(node, modules):
    """The dotted module a call's base names, or None when it names no import."""
    dotted = _dotted(node)
    if dotted is None:
        return None
    head, _, rest = dotted.partition(".")
    base = modules.get(head)
    if base is None:
        return None
    return f"{base}.{rest}" if rest else base


def _call_sites(modules, name, reaches):
    """Every call of *name*, split into the ones that reach the owner and the rest.

    *reaches* is the set of dotted spellings of the owner's one function (e.g.
    "kcilib.run.runner.run_tuxrun").  A call reaches it when it is spelled
    ``name(...)`` with that name imported from one of those modules, or
    ``owner_module.name(...)`` through a module this file can resolve to one of
    them.  Anything else is a stranger and is reported with its own spelling -
    a same-named function of the caller's own, or a call through a name that
    resolves to no import at all.
    """
    allowed_functions = set(reaches)
    allowed_modules = {reach.rsplit(".", 1)[0] for reach in reaches}
    sites, strangers = [], []
    for path, tree in modules:
        symbols, imports = _bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                reached = symbols.get(func.id)
                if reached in allowed_functions:
                    sites.append((path, node.lineno))
                else:
                    strangers.append(
                        f"{path}:{node.lineno} {func.id} "
                        f"(imported from {symbols.get(func.id) or 'nowhere'})")
            elif isinstance(func, ast.Attribute) and func.attr == name:
                reached = _resolves_to(func.value, imports)
                if reached in allowed_modules:
                    sites.append((path, node.lineno))
                else:
                    strangers.append(
                        f"{path}:{node.lineno} {_dotted(func.value)}.{name} "
                        f"(resolves to {reached or 'no import'})")
    return sites, strangers


def _spawns(tree):
    """Every process a module starts: [(call, spelling)] for subprocess.* and os.*.

    Only the spellings whose base resolves to the subprocess or os module count:
    a method that happens to be called ``run`` is every class's business, and a
    guard that flags it is a guard people learn to ignore.
    """
    _symbols, imports = _bindings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        base = _resolves_to(func.value, imports)
        if base == _SPAWN_SUBMODULE and func.attr in _SPAWN_ATTRS:
            found.append((node, f"{_dotted(func.value)}.{func.attr}"))
        elif base == "os" and func.attr in _OS_SPAWN_ATTRS:
            found.append((node, f"os.{func.attr}"))
    return found


def _imports_subprocess(tree):
    """Whether a module imports subprocess at all (any alias, any form)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _SPAWN_SUBMODULE:
                    return True
        elif isinstance(node, ast.ImportFrom) and node.module == _SPAWN_SUBMODULE:
            return True
    return False


def _argv_names_tuxrun(call):
    """Whether a spawn call's command is spelled like tuxrun.

    The three spellings a hand-written executor has: a literal argv whose first
    element is the binary (["tuxrun", "--device", ...]), a bare name
    (subprocess.run(TUXRUN ...)), and the shell form (os.system("tuxrun ...")).
    A command assembled in another variable is not followed - see the
    entry-point rule, which forbids the one-shot line from spawning at all.
    """
    if not call.args:
        return False
    argv = call.args[0]
    if isinstance(argv, ast.Constant) and isinstance(argv.value, str):
        return "tuxrun" in argv.value.lower()
    head = None
    if isinstance(argv, (ast.List, ast.Tuple)) and argv.elts:
        head = argv.elts[0]
    elif isinstance(argv, (ast.Name, ast.Attribute)):
        head = argv
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return "tuxrun" in head.value.lower()
    spelling = _dotted(head) if head is not None else None
    return bool(spelling) and "tuxrun" in spelling.lower()


def _writes_a_record_by_hand(tree):
    """Calls that open a ledger path for writing, as [(lineno, spelling)].

    The write itself, not the writer function: a module that spells
    open(ledger.result_path(...), "w") has made itself a second writer whatever
    it calls the enclosing function.  Only a path argument that is still visible
    as one of kcilib.core.ledger's accessors is caught; a path carried through
    two variables is not (that is layout_policy_checks' business - the path
    itself).
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_open = ((isinstance(func, ast.Name) and func.id == "open")
                   or (isinstance(func, ast.Attribute) and func.attr == "open"))
        if not is_open:
            continue
        mode = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                and any(flag in mode.value for flag in _WRITE_MODES)):
            continue
        spelling = ", ".join(ast.unparse(argument) for argument in node.args)
        spelling += "".join(f", {keyword.arg}={ast.unparse(keyword.value)}"
                            for keyword in node.keywords)
        if any(accessor in spelling for accessor in _LEDGER_ACCESSORS):
            found.append((node.lineno, spelling))
    return found


def _one_definition(modules, name, owner):
    """The symbol is defined exactly once, in the module that owns it."""
    defined = _definitions(modules, name)
    spellings = ", ".join(f"{path}:{lineno}" for path, lineno in defined)
    check(bool(defined),
          f"nothing defines {name} any more: this guard pins the one copy in "
          f"{owner}, so either it moved there or the guard has to be updated "
          f"with the decision that replaced it")
    check(len(defined) == 1 and defined[0][0] == owner,
          f"{name} is defined {len(defined)} time(s) ({spellings}); the one "
          f"copy is {owner}'s.  A second definition IS a second implementation "
          f"of the same decision - delete it and call {owner}'s instead")


def _closed_callers(sites, strangers, callers, symbol, owner, floor,
                    advice=None):
    """The callers of *symbol* are exactly *callers*, and every one reaches *owner*.

    *owner* is the module that DEFINES the one function (the module every
    message sends the reader to); *callers* is the closed set of modules allowed
    to call it, which is narrower for the result exit - there the one function
    is kcilib/run/callback.py's and the one caller is kcilib/sink.py.
    """
    check(not strangers,
          f"a call to {symbol} that does not reach {owner}'s own function: "
          + ", ".join(strangers)
          + f".  {symbol} has one implementation ({owner}); call it through the "
            "module it lives in instead of growing a local one")
    check(len(sites) >= floor,
          f"only {len(sites)} call site(s) of {symbol} found, expected at least "
          f"{floor}: this rule would pass by finding nothing the day the call "
          "sites are rewritten, so fix the guard or the caller list")
    found = sorted({path for path, _lineno in sites})
    check(found == sorted(callers),
          f"{symbol} is called from {', '.join(found) or 'nowhere'}; the callers "
          f"this guard knows are {', '.join(sorted(callers))}.  "
          + (advice or (f"A new caller is a new path: register it here on "
                        f"purpose, or call {symbol} from one of the modules "
                        "above")))


def test_tuxrun_has_one_command_line_and_one_executor():
    """One argv builder and one executor, both in kcilib/run/runner.py.

    §1.3 #2's two ways to run a job each assembled the same tuxrun argv - same
    flag order, same --rootfs/--modules/--tests omission rules, two copies - so
    the flag order lived in two files and a change to one was a change to
    neither.  runner.py's docstring says the assembly "and the execution live
    here instead of twice", and nothing enforced it: fetch-and-run-latest.py
    could build its own argv and its own subprocess.run again, with ./run.sh
    verify still green (ruff reads style, compileall reads syntax, and the argv
    snapshot test compares bytes - which is exactly what a faithful second copy
    reproduces).

    What is pinned: build_tuxrun_argv is defined once and called once (from
    jobrun.run_command's argv step), run_tuxrun is defined once, and every call
    to either provably reaches that one function.  The one-shot line may not
    spawn a process at all any more, and no module outside runner.py may spawn
    one with a tuxrun argv.  Its run goes through kci.Job.run ->
    kcilib.run.jobrun.run_node -> kcilib.run.runner.run_tuxrun, so the flag
    order, the console separator and the judgement stay the run layer's.
    """
    import kcilib

    modules = _modules(kcilib.repo_root())
    trees = dict(modules)

    for symbol in ("build_tuxrun_argv", "run_tuxrun"):
        _one_definition(modules, symbol, _RUNNER)

    argv_sites, argv_strangers = _call_sites(modules, "build_tuxrun_argv",
                                             _ARGV_REACHES)
    _closed_callers(argv_sites, argv_strangers, _ARGV_CALLERS,
                    "kcilib.run.runner.build_tuxrun_argv", _RUNNER, floor=1)
    # Exactly one: the argv is built once per run, and the place that builds it
    # is the run layer's, not each caller's.
    check(len(argv_sites) == 1,
          f"build_tuxrun_argv is called {len(argv_sites)} times "
          f"({', '.join(f'{path}:{lineno}' for path, lineno in argv_sites)}); "
          f"{_ARGV_CALLERS[0]} is the one caller.  A second call site is a "
          "second idea about the command line: pass the definition to the run "
          "layer (kcilib.run.jobrun.run_node) instead")

    run_sites, run_strangers = _call_sites(modules, "run_tuxrun", _RUN_REACHES)
    _closed_callers(run_sites, run_strangers, _RUN_CALLERS,
                    "kcilib.run.runner.run_tuxrun", _RUNNER, floor=2)

    entry = trees.get(_ENTRY_POINT)
    check(entry is not None,
          f"{_ENTRY_POINT} is not there: this guard exists to keep the one-shot "
          "line off the execution path, so it has to be told where that line "
          "went (or to be updated with the decision that removed it)")
    check(_ENTRY_POINT not in {path for path, _lineno in run_sites},
          f"{_ENTRY_POINT} executes tuxrun itself again (§1.3 #2): its run is "
          "one kci.Job.run() call, and the execution is kcilib.run.runner's - "
          f"delete the argv and the spawn (owner: {_RUNNER})")
    check(not _imports_subprocess(entry),
          f"{_ENTRY_POINT} imports subprocess: the one-shot line does not start "
          "processes any more, it hands the run to the run layer "
          "(kci.Job.run -> kcilib.run.jobrun.run_node), which reaches tuxrun "
          f"through kcilib.run.runner.run_tuxrun (owner: {_RUNNER})")
    entry_spawns = _spawns(entry)
    check(not entry_spawns,
          f"{_ENTRY_POINT} starts processes itself: "
          + ", ".join(f"line {call.lineno} {spelling}"
                      for call, spelling in entry_spawns)
          + ".  The one-shot line runs tuxrun through the run layer only "
            f"(owner: {_RUNNER})")

    # Tree-wide: a tuxrun process may be started in exactly one module.  The
    # first element of a spawn's argv is read when it is spelled there; the
    # modules that legitimately spawn other things (the artifact server, mkfs,
    # docker compose) are untouched by this because their argv names no tuxrun.
    offenders = []
    for path, tree in modules:
        if path == _RUNNER:
            continue
        for call, spelling in _spawns(tree):
            if _argv_names_tuxrun(call):
                offenders.append(f"{path}:{call.lineno} {spelling}")
    check(not offenders,
          "a module starts a tuxrun process of its own: "
          + ", ".join(offenders)
          + f".  The executor is kcilib.run.runner.run_tuxrun (owner: {_RUNNER}) "
            "- call it instead of spawning tuxrun")
    print("test_tuxrun_has_one_command_line_and_one_executor OK")


def test_results_leave_by_one_exit():
    """A result goes where kcilib/sink.py says, and only sink.py posts it.

    §1.3 #6: poll.py posted the callback result itself while kcilib/sink.py
    decided where a result goes - two exits for one result, so "did this run
    report back?" had two answers and the sink's ordering promise (ledger
    first, callback second) held on only one of them.  poll.py now calls
    sink.deliver_report(), and this rule is what keeps the next caller from
    doing what it did: post_result() is reached from sink.py alone.

    It is the last hop that is pinned, not the whole route: kci.Job,
    local-jobs.py and poll.py all reach the sinks (that is the design), but
    every one of them goes through kcilib/sink.py, which is the only module
    that holds post_result's URL, token and body.
    """
    import kcilib

    modules = _modules(kcilib.repo_root())
    _one_definition(modules, "post_result",
                    os.path.join(_SCRIPTS, "kcilib", "run", "callback.py"))
    sites, strangers = _call_sites(modules, "post_result", _POST_REACHES)
    _closed_callers(
        sites, strangers, _POST_RESULT_CALLERS,
        "kcilib.run.callback.post_result",
        os.path.join(_SCRIPTS, "kcilib", "run", "callback.py"), floor=1,
        advice="A result goes where kcilib/sink.py says, and sink.py is the "
               "only module allowed to hold the callback's URL, token and body: "
               "deliver through sink.deliver()/sink.deliver_report() instead of "
               "posting it yourself (owner: kcilib/sink.py)")
    print("test_results_leave_by_one_exit OK")


def test_ledger_has_one_writer():
    """One writer of the ledger record, and the fetch line is not it.

    §1.3 #4: kcilib.run.jobrun.record_result and fetch's own write_result wrote
    the same document with the same key set, so the record's shape had two
    authors and the second one was free to drift (it is also why §1.4's
    retention policy had no owner for the ledger - nobody knew which writer
    defined a row).  The interface layer may name a record (kci.Job.record, the
    path the fetch line reaches without touching the ledger), and the run layer
    may file one, and that is the whole list: a new entry here is a new author
    of the ledger's rows, which is a decision, not a detail.

    Read as call sites of kcilib.core.ledger.write_result plus one look at the
    write itself: a module that opens a ledger path for writing by hand is a
    second writer whatever it names the function.
    """
    import kcilib

    modules = _modules(kcilib.repo_root())
    _one_definition(modules, "write_result",
                    os.path.join(_SCRIPTS, "kcilib", "core", "ledger.py"))
    sites, strangers = _call_sites(modules, "write_result", _WRITE_REACHES)
    _closed_callers(
        sites, strangers, _WRITE_RESULT_CALLERS,
        "kcilib.core.ledger.write_result",
        os.path.join(_SCRIPTS, "kcilib", "core", "ledger.py"), floor=2,
        advice="A record is filed, not written: the run layer files one through "
               "kcilib.run.jobrun.record_result and the interface layer through "
               "kci.Job.record - a third author is a third idea about the "
               "record's key set (owner: kcilib/core/ledger.py)")

    callers = {path for path, _lineno in sites}
    check(_ENTRY_POINT not in callers,
          f"{_ENTRY_POINT} writes the ledger itself again (§1.3 #4): the "
          "record's key set and its path are kcilib.core.ledger's, and the "
          "fetch line files its record through kci.Job.record "
          "(owner: kcilib/run/jobrun.py's record_result)")

    by_hand = [(path, lineno, spelling)
               for path, tree in modules
               for lineno, spelling in _writes_a_record_by_hand(tree)]
    check(not by_hand,
          "a module opens a ledger record for writing by hand: "
          + ", ".join(f"{path}:{lineno} {spelling}"
                      for path, lineno, spelling in by_hand)
          + ".  work/results/<build>/<test>.json is written by "
            "kcilib.core.ledger.write_result alone, through "
            "kcilib.run.jobrun.record_result or kci.Job.record - one writer, "
            "or the record's key set has two authors again")
    print("test_ledger_has_one_writer OK")
