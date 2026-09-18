"""Two structural rules of the layout/policy phase: one owner per path, one per number.

Both owners exist (kcilib/core/layout.py, kcilib/core/policy.py) and both are
declared in docs/REFACTOR-D-BRIEF.md (2.2 "输入 / 派生 / 输出 / 状态四类不许混住",
1.4 "四个没有 owner 的决定"), and neither was enforced by anything: the guard suite
imported kcilib and looked at BEHAVIOUR, so a caller could spell work/<somewhere>
by hand and a retention number could be re-typed beside the table, with
./run.sh verify still green.  Structure is what these two checks read, not
behaviour, because the failure they prevent is a second copy of a decision that
already has an owner - and a second copy is exactly what no test sees.
"""
import ast
import glob
import importlib
import os

from .support import check

# The directory under work/ whose spelling layout owns.  The SEGMENT is what is
# matched, never a full path: joining this segment onto a repo root is the whole
# violation, whatever is appended after it.
_WORK = "work"

# The one module allowed to spell that segment - it IS the owner every message
# below sends the caller to.  Repo-relative, so the exemption cannot go stale the
# way an absolute path would.  It includes "scripts/" because the comparison
# below is against os.path.relpath(path, repo_root()), which never drops that
# segment: without it the exemption silently matched nothing and the owner was
# scanned like any other module.
_OWNER = os.path.join("scripts", "kcilib", "core", "layout.py")

# (module, constant, POLICY field): every constant that is a policy number under
# an old name its callers already read.  Equal values are the contract; a
# re-typed number on either side is how the two owners drift apart.
_POLICY_NUMBERS = (
    ("kcilib.core.config", "MIN_TIMEOUT", "seconds_min_job_timeout"),
    ("kcilib.core.config", "LOG_ARCHIVE_KEEP", "console_logs_keep"),
    ("kcilib.core.retention", "DEFAULT_KEEP", "downloads_keep"),
    ("kcilib.run.bake", "BAKE_CACHE_MAX_ENTRIES", "baked_images_keep"),
    ("kcilib.run.bake", "BAKE_CACHE_TMP_AGE_S", "seconds_bake_tmp_age"),
    # Two quantities policy.py recorded as ONE number while their other spelling
    # still holds a literal.  Pinned as equal here rather than left to phase 1:
    # config.MAX_DOWNLOAD_MB already reads the table, so without this row editing
    # the one ceiling would move the worker's limit and leave the bake path's
    # behind - a drift with no symptom until a 5 GiB image is refused.
    ("kcilib.run.artifacts", "MAX_DOWNLOAD_SIZE", "bytes_max_download"),
    ("kcilib.table.jobspec", "PLATFORM", "platform"),
)


def _is_repo_root(node):
    """True when *node* is a call that IS the repository root.

    Three spellings, no more: repo_root() (kcilib's own, re-exported as
    kcilib.repo_root), <something>.repo_root() (kcilib.repo_root), and
    layout.root() (the path form of the same root).  Naming them is what keeps
    this rule narrow - a path built out of a plain variable is not proof of
    anything.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "repo_root"
    if isinstance(func, ast.Attribute):
        if func.attr == "repo_root":
            return True
        return (func.attr == "root" and isinstance(func.value, ast.Name)
                and func.value.id == "layout")
    return False


def _root_names(tree):
    """The module-level names bound to a repo-root call: ROOT, REPO_ROOT, ...

    A module that walks up to run.sh once and joins "work" onto that name is the
    common shape here (config.REPO_ROOT, delivery.ROOT, buildindex.ROOT,
    render-local-config's ROOT), so binding the name is what has to be followed -
    matching only the inline repo_root() call would read one of those files and
    miss the other three.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_repo_root(node.value):
            names.update(target.id for target in node.targets
                         if isinstance(target, ast.Name))
    return names


def _is_root(node, roots):
    """True when *node* is the repository root, inline or through a bound name.

    pathlib.Path(repo_root()) unwraps to the same root: without this the shorter
    spelling -- the one layout.py itself uses -- would be the free bypass, and a
    guard that reads only the os.path spelling is a guard you can walk around by
    typing Path().
    """
    if isinstance(node, ast.Call):
        func = node.func
        wrapped = ((isinstance(func, ast.Name) and func.id == "Path")
                   or (isinstance(func, ast.Attribute) and func.attr == "Path"
                       and isinstance(func.value, ast.Name)
                       and func.value.id == "pathlib"))
        if wrapped and node.args:
            return _is_root(node.args[0], roots)
    return _is_repo_root(node) or (isinstance(node, ast.Name) and node.id in roots)


def _is_os_path_join(func):
    """True for the os.path.join attribute chain, and nothing else."""
    return (isinstance(func, ast.Attribute) and func.attr == "join"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "os")


def _is_work_segment(node):
    """True when *node* is the literal "work", or a literal path starting with "work/".

    "workflows" is not "work": the segment stands alone or opens a path, so
    os.path.join(ROOT, "work/logs") is caught while an unrelated name that merely
    begins with those four letters is not.
    """
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and (node.value == _WORK or node.value.startswith(_WORK + "/")))


def _joins_work_onto_root(node, roots):
    """True when *node* is a repo root joined with the work segment.

    Both spellings of "join" count, because both build the same second owner:
    os.path.join(root, "work", ...) and root / "work" (pathlib).  Reading only
    the os.path one would leave the shorter spelling free to bypass layout.
    """
    if isinstance(node, ast.Call) and _is_os_path_join(node.func):
        args = node.args
        return (len(args) >= 2 and _is_root(args[0], roots)
                and _is_work_segment(args[1]))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_root(node.left, roots) and _is_work_segment(node.right)
    return False


def test_new_writes_go_through_layout():
    """Where bytes live is layout's decision, so no module may spell work/ itself.

    kcilib.core.layout's docstring says four categories go in four directories and
    that they may not mix, and docs/REFACTOR-D-BRIEF.md 2.2 asks for a guard
    pinning "新写入只许走 layout".  Nothing pinned it: the path was spelled by
    hand in the execution layer, in the table layer, in core and in the tools, so
    "which category is work/env/baked in?" had as many answers as there were call
    sites - and a second spelling is invisible, because it computes the same
    directory until the day the tree is reorganised and only the copies that
    called layout move.

    Read with ast, not a regex: these modules explain the layout in docstrings and
    in messages that NAME work/logs and work/downloads (retention.py's table,
    dashboard.py's help text), and a regex cannot tell a sentence from a path.

    Deliberately NOT checked, and why each would be worse than no check:
      * a bare "work/..." string literal.  layout.py's legacy_map() is made of
        them (it is the owner's own table) and retention.py prints them, so the
        rule would need an exemption list longer than the rule;
      * a path joined onto a variable that is not a repo-root call.  Without
        knowing where the base came from there is no violation to point at, only
        a naming convention.
    Both spellings that ARE unambiguous - the os.path.join one and the pathlib
    one - are matched, so the narrowing above costs coverage nowhere.
    """
    import kcilib

    root = kcilib.repo_root()
    scripts = os.path.join(root, "scripts")
    guards = os.path.join(scripts, "tools", "guards")

    scanned, offenders = 0, []
    for path in sorted(glob.glob(os.path.join(scripts, "**", "*.py"),
                                 recursive=True)):
        relative = os.path.relpath(path, root)
        if "__pycache__" in path or relative == _OWNER:
            # The owner of the table is the one module allowed to spell it;
            # every other module is told to ask the owner instead.
            continue
        if os.path.abspath(path).startswith(guards + os.sep):
            # The guards' own modules: this file would otherwise read itself (and
            # the messages above), not the code under test.
            continue
        scanned += 1
        with open(path, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read(), filename=path)
            except SyntaxError as error:
                check(False, f"{relative} does not parse, so this guard is "
                             f"reading nothing where code used to be: {error}")
        roots = _root_names(tree)
        for node in ast.walk(tree):
            if _joins_work_onto_root(node, roots):
                offenders.append(f"{relative}:{node.lineno}")

    # A guard that scans nothing passes by finding nothing.  references.py keeps
    # the same floor (>= 15) for the same reason: scripts/ holds well over a
    # hundred modules, so a glob that stops matching is a broken guard, not a
    # clean tree.
    check(scanned >= 15,
          f"only {scanned} modules scanned; the glob is wrong, so this guard "
          "would pass by reading nothing")
    check(not offenders,
          "a work/ path is joined onto the repository root by hand; the bytes' "
          "category (input / derived / output / state) is kcilib.core.layout's "
          "decision and it has one accessor per category, so these must go "
          "through kcilib.core.layout: " + ", ".join(offenders))
    print("test_new_writes_go_through_layout OK")


def test_retention_numbers_come_from_policy():
    """Every "how many / how long" constant still equals the policy field that owns it.

    docs/REFACTOR-D-BRIEF.md 1.4 ("留几份（下载 / 烤盘 / 日志 / 账本）") sends the
    four retention policies to one owner, kcilib.core.policy.POLICY, and
    policy.py's own docstring says the constants keep their old names so their
    callers keep working.  Keeping the name while re-typing the number is the one
    way that goes wrong: both spellings read as "the policy" and only one of them
    is the table, which is how five builds, three baked images and 200 consoles
    ended up in three files in three units with the ledger's retention owned by
    nobody.

    Compared with ==, not is.  These are ints, so `is` would pass only by accident
    of CPython's small-int cache and would start failing on a value that stopped
    being cached - a guard that breaks on a correct change teaches people to
    ignore it.
    """
    policy = importlib.import_module("kcilib.core.policy")

    check(hasattr(policy, "POLICY"),
          "kcilib.core.policy.POLICY is gone: this guard depends on the one table "
          "of retention numbers, so restore it or update the guard with the "
          "decision that replaced it")
    # The rows below are the rule, so an empty or shrunken table of rows would
    # make this guard pass by asking no question at all.
    check(len(_POLICY_NUMBERS) >= 7,
          f"only {len(_POLICY_NUMBERS)} constants are pinned; this guard would "
          "pass without checking the retention numbers it exists for")

    for module_name, attribute, field in _POLICY_NUMBERS:
        module = importlib.import_module(module_name)
        check(hasattr(module, attribute),
              f"{module_name}.{attribute} is gone: this guard depends on the "
              "name (it is the one its callers read), so either keep it as a "
              "re-export of the policy field or update the guard with the "
              "decision that removed it")
        check(hasattr(policy.POLICY, field),
              f"policy.POLICY.{field} is gone: this guard depends on the field "
              f"that owns {module_name}.{attribute}")
        found = getattr(module, attribute)
        owned = getattr(policy.POLICY, field)
        check(found == owned,
              f"{module_name}.{attribute} is {found!r} but policy.POLICY.{field} "
              f"is {owned!r}: the number has two owners again, so change "
              f"policy.POLICY.{field} (the one table) and let this name read it")
    print("test_retention_numbers_come_from_policy OK")
