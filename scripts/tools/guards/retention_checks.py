"""Retention: which fetched builds ./run.sh prune deletes, and that dry-run deletes none."""
import json
import os
import tempfile

from kcilib.core import retention

from .support import check


def _build(downloads, name, mtime, commit=None, size=10):
    """One work/downloads/<name>/ with a file of *size* bytes and an mtime."""
    path = os.path.join(downloads, name)
    os.makedirs(path)
    with open(os.path.join(path, "Image"), "wb") as handle:
        handle.write(b"x" * size)
    if commit is not None:
        with open(os.path.join(path, "node.json"), "w") as handle:
            handle.write(json.dumps(
                {"data": {"kernel_revision": {"commit": commit}}}))
    os.utime(path, (mtime, mtime))
    return path


def _tree(tmp):
    """A downloads tree: 4 builds, the build.env build being the OLDEST one."""
    downloads = os.path.join(tmp, "downloads")
    os.makedirs(downloads)
    served = _build(downloads, "served", 1000, commit="deadbeefcafe0000",
                    size=20)
    old = _build(downloads, "old", 2000, size=30)
    newer = _build(downloads, "newer", 3000)
    newest = _build(downloads, "newest", 4000)
    build_env = os.path.join(tmp, "build.env")
    with open(build_env, "w") as handle:
        handle.write("KCI_BUILD_COMMIT=deadbeefcafe0000\n"
                     "KCI_BUILD_DIR=/somewhere/builds/served\n")
    # a plain file in the downloads root is not a build and must be ignored
    with open(os.path.join(downloads, "README"), "w") as handle:
        handle.write("not a build\n")
    return downloads, build_env, {
        "served": served, "old": old, "newer": newer, "newest": newest,
    }


def test_retention_plan_and_prune():
    """The only path that deletes a user's own retained data, finally guarded.

    This ruled on a user's data from inside a run.sh heredoc, where the guard
    suite (which imports kcilib and nothing else) could not see it.  Three things
    are pinned: the served build survives even when it is the oldest, the dry run
    and the real run share one decision, and a dry run deletes nothing at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        downloads, build_env, paths = _tree(tmp)
        lines, to_remove = retention.plan(downloads, keep=2,
                                          build_env=build_env)
        # Read the decision back out of the printed table: the reason is the
        # line's tail, so a change in wording is a visible failure rather than a
        # silently re-parsed one.
        by_name = {}
        for line in lines:
            fields = line.split()
            if len(fields) > 5 and os.path.isdir(
                    os.path.join(downloads, fields[0])):
                by_name[fields[0]] = " ".join(fields[5:])
        check(by_name["newest"] == "keep: newest"
              and by_name["newer"] == "keep: newest",
              f"the newest builds are not the ones kept: {by_name}")
        check("build.env" in by_name["served"],
              f"the build work/env/build.env records must be kept even when it "
              f"is the oldest: {by_name}")
        check(by_name["old"] == "PRUNE", by_name)
        check([os.path.basename(p) for p, _s in to_remove] == ["old"],
              f"the plan and its removals disagree: {to_remove}")
        check(not any("README" in line for line in lines),
              f"a plain file is not a build: {lines}")

        # dry run: the same table, nothing deleted, the remover never called
        called = []
        out = []
        removed = retention.prune(downloads, keep=2, build_env=build_env,
                                  dry=True, remove=called.append, out=out.append)
        check(removed == 1 and called == [], f"dry run deleted: {called}")
        check(out[:len(lines)] == lines,
              "the dry run's table differs from the plan it is based on")
        check(out[-1].startswith("would remove 1 build(s)")
              and "nothing was deleted" in out[-1], out[-1])
        check(os.path.isdir(paths["old"]),
              "a dry run must not remove anything from disk")

        # the real run deletes exactly what the dry run marked, and nothing else
        out = []
        removed = retention.prune(downloads, keep=2, build_env=build_env,
                                  out=out.append)
        check(removed == 1, removed)
        check(not os.path.exists(paths["old"]),
              "the PRUNE build was not deleted")
        for name in ("served", "newer", "newest"):
            check(os.path.isdir(paths[name]),
                  f"prune deleted a build it must keep: {name}")
        check(out[-1].startswith("removed 1 build(s)"), out[-1])

        # Every unreadable node.json shape is "not the served build", never a
        # crash: this runs once per build inside a loop that has already started
        # deleting, so raising here would leave a HALF-pruned downloads directory.
        for name, text in (("corrupt", "{not json"), ("empty", ""),
                           ("an array", "[1, 2]"),
                           ("data not an object", '{"data": 5}'),
                           ("revision not an object",
                            '{"data": {"kernel_revision": 5}}')):
            with open(os.path.join(paths["newest"], "node.json"), "w") as handle:
                handle.write(text)
            check(retention.recorded_commit(paths["newest"]) == "",
                  f"a node.json that is {name} must not read as a commit")
            check(retention.plan(downloads, keep=2, build_env=build_env)[0],
                  f"a node.json that is {name} must not stop the plan")

        # a missing tree is an answer, not a failure (run.sh prune on a fresh
        # checkout used to exit 0 saying so)
        missing = os.path.join(tmp, "nope")
        out = []
        check(retention.prune(missing, out=out.append) == 0 and len(out) == 1
              and out[0].startswith("nothing to prune:"), out)
    print("test_retention_plan_and_prune OK")
