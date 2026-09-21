# SPDX-License-Identifier: LGPL-2.1-or-later
"""One test on one build: the definition that runs it, and the run itself.

Draft this file is built from (``lib/job``)::

    struct jobnode { kjobnode }
    class job {
        list jobnode
        job (class kbuild)
        make()
        class out run()
        print
    }

`Job.run()` is the single executor: the resident worker, the one-shot fetch,
the offline table and the GUI's buttons all end up here.  That is the one
structural fact worth keeping from the old tree - if a second runner appears,
the offline line stops being evidence about the worker.

The job definition stays a **plain dict, isomorphic with what the upstream
templates render** (a tuxrun argv is derived from it, nothing else).  It is the
one cross-layer boundary, and a class here would let the executor start telling
"a definition we made" from "a definition the API sent" - exactly the
distinction that makes a local run stop predicting a production run.

The test catalogue lives here too: a test is a name, what it needs from the
build, and how it maps to tuxrun arguments.  One table, one owner.

接口形状（C++，只有声明）：include/kci/local.hpp §9 Job / Jobs。
"""

import os
from dataclasses import dataclass, field

from . import build as build_mod
from . import errors, judge, layout, runner, sink
from .build import Build
from .kbuild import _stamp, build_id_of
from .out import Outcome
from .sink import Sink
from .tests import DEFAULT_TESTS, ROOTFS_URL, TESTS


@dataclass
class Job:
    """One test, on one build, ready to run."""

    build: Build | None = None
    test: str = ""
    # The definition to execute.  Empty means "render ours"; set means "run this
    # verbatim" (what the worker gets from the API).  `run()` may not look at
    # which of the two it has - that is the invariant the whole design rests on.
    given: dict = field(default_factory=dict)
    # tuxrun overrides the caller asked for (extra parameters, a cpu string).
    params: dict = field(default_factory=dict)
    # Artifact name -> local path, filled by make(); argv() prefers these.
    local: dict = field(default_factory=dict)
    # The last workspace this job ran in; `run()` sets it.
    workspace: str = ""
    timeout: int = 0

    @classmethod
    def from_definition(cls, definition, build: Build | None = None):
        """A Job around a definition someone else made (a node's, a fixture's, a table's)."""
        tests = definition.get("tests") or [{}]
        job = cls(build, tests[0].get("type") or "boot", given=definition)
        job.timeout = int(tests[0].get("timeout_s") or 0)
        return job

    # --- identity ----------------------------------------------------------

    @property
    def build_id(self):
        """The build this job is on - from the card, else out of its artifacts."""
        if self.build is not None:
            return self.build.build_id
        return build_id_of(self.given.get("artifacts") or {})

    def id(self):
        """`<build_id>.<test>` - the row key a table sorts and dedups by."""
        return f"{self.build_id}.{self.test}"

    def catalog(self):
        """This test's entry, or a ConfigError naming it (never a KeyError)."""
        try:
            return TESTS[self.test]
        except KeyError:
            raise errors.ConfigError(
                f"unknown test {self.test!r}; known: {', '.join(sorted(TESTS))}") from None

    def needs(self):
        """The artifacts this test needs from the build."""
        return self.catalog()["needs"]

    # --- the definition ----------------------------------------------------

    def make(self):
        """Prepare what the executor needs on disk: artifacts, and the guest disk.

        Idempotent.  For a definition the API sent, the definition itself is left
        exactly as it came (re-rendering it would drop keys and inject our own
        rootfs) - but the *bytes* are still ours to prepare: the guest disk has
        to be baked here, because mkfs cannot run inside the container, and the
        KVM test list has to be read off the tarball.
        """
        entry = self.catalog()
        if self.given:
            return self._make_given(entry)
        if self.build is None:
            raise errors.ConfigError("a locally rendered job needs a build")
        self.build.make(entry["needs"])
        # The pull above is also a registration, but only for a build nobody has
        # a card for: `Jobs.for_build()` is handed a build out of the API
        # (runday, run_latest, the worker's day) as often as one out of the table
        # (`table.py run`), and only the first kind is missing from the book.
        # `remember()` is the guard - a card that is already there is left alone -
        # so this costs one read of the file and no write.
        build_mod.Builds.load().remember(self.build)
        self.local = {name: self.build.files.get(name, "") for name in entry["needs"]}
        if entry["rootfs"]:
            self.local["rootfs"] = self.build.rootfs(
                url=self.params.get("rootfs", ""), with_modules=entry["modules"])
        self._kvm_list(entry)
        return self

    def _make_given(self, entry):
        """The definition's own artifacts, made usable here without touching the definition."""
        artifacts = self.given.get("artifacts") or {}
        build_id = self.build_id or "definition"
        home = layout.downloads(build_id)
        if entry["rootfs"] and artifacts.get("rootfs"):
            self.local["rootfs"] = build_mod.bake_rootfs(
                artifacts["rootfs"], entry["modules"], modules_url=artifacts.get("modules", ""))
        if entry["modules"] and not self.params.get("kvm_tests"):
            tarball = os.path.join(home, "kselftest.tar.xz")
            if not os.path.isfile(tarball):
                os.makedirs(home, exist_ok=True)
                build_mod.download(artifacts.get("kselftest", ""), tarball)
            # Hand tuxrun the copy we just read: a local file is one bind mount
            # instead of a second 100MB download inside the container.
            self.local["kselftest"] = tarball
            self._kvm_list(entry, tarball)
        return self

    def _kvm_list(self, entry, tarball=""):
        """Fill `params["kvm_tests"]`: the curated subset, unless the caller named one.

        KVM is an exclusion list, not an allow list, and the list comes from the
        build's own tarball - so an old kernel cannot make us ask tuxrun for a
        test it never built.  `kvm_full` (or an explicit list) skips this.
        """
        if not entry["modules"] or self.params.get("kvm_tests") or self.params.get("kvm_full"):
            return
        tarball = tarball or self.local.get("kselftest", "")
        if tarball and os.path.isfile(tarball):
            self.params["kvm_tests"] = build_mod.kvm_tests(tarball)

    def definition(self):
        """The job definition dict: what to run, on which artifacts, callback or not.

        Shape follows the upstream templates (`artifacts`, `tests`, `environment`,
        `callback`), so the worker cannot tell this one from a rendered one.
        A definition that came from the API is returned verbatim.
        """
        if self.given:
            return self.given
        artifacts = dict(self.build.kbuild.artifacts) if self.build else {}
        # The API spells the tarball `kselftest_tar_xz`; the executor says
        # `kselftest`.  Same rename the production template does.
        artifacts["kselftest"] = artifacts.get("kselftest") or artifacts.get("kselftest_tar_xz", "")
        artifacts["rootfs"] = self.params.get("rootfs") or ROOTFS_URL
        definition = {
            "artifacts": artifacts,
            "tests": [{
                "id": self.test,
                "type": self.test,
                "depends": [],
                "timeout_s": self.timeout or 0,
                "pre-commands": [],
                "post-commands": [],
            }],
            "environment": {
                "platform": self.params.get("platform", "qemu-riscv64"),
                "arch": "riscv64",
                "console": {"method": "serial", "baud": 115200},
            },
        }
        if self.params.get("callback_url"):
            definition["callback"] = {"url": self.params["callback_url"],
                                      "token_name": "kernelci-pipeline-callback"}
        return definition

    def argv(self, config):
        """`(argv, label)` for tuxrun - `runner` owns the spelling, this only asks."""
        return runner.argv(self, config)

    # --- the run -----------------------------------------------------------

    def run(self, config, sinks: tuple[Sink, ...] | None = None,
            source: str = "local") -> Outcome:
        """Run it once and return an `Outcome` - the one place a job is executed.

        Never raises for a job-level problem: a run that never reached tuxrun
        still produces an Outcome (infra, exit 3) and still writes the ledger,
        because the record most worth having is the failed run's.  A bug is a
        different thing: it is recorded first, then allowed to be loud.
        """
        started = _stamp()
        console = ""
        try:
            self.catalog()
            self.make()
            argv, label = self.argv(config)
            self.workspace = layout.workspaces(f"{self.build_id}.{self.test}.{started}")
            os.makedirs(self.workspace, exist_ok=True)
            _announce(argv, label)
            result = runner.execute(argv, cwd=self.workspace,
                                    timeout=self.timeout or config.timeout)
            console = result.console
            outcome = judge.verdict(result.returncode, console, self.test)
        except (errors.KciError, OSError) as exc:
            # A job-level problem - the artifact is unreachable, mkfs is missing,
            # the disk is full - is an infra outcome, never a crash: exit 3 says
            # "we never got a verdict", which is the truth, and the record is
            # still written.
            outcome = Outcome.infra(str(exc), build_id=self.build_id, test=self.test)
        except Exception:
            self._file(source, started, console,
                       Outcome(build_id=self.build_id, test=self.test, verdict="error",
                               exit_code=errors.EXIT_INFRA, detail="internal error"), sinks)
            raise

        self._file(source, started, console, outcome, sinks)
        return outcome

    def _file(self, source: str, started: str, console: str, outcome: Outcome,
              sinks: tuple[Sink, ...] | None):
        """Fill the identity fields, keep the console, then deliver - ledger first."""
        outcome.build_id = outcome.build_id or self.build_id
        outcome.test = outcome.test or self.test
        outcome.source = source
        outcome.job = self.build_id
        outcome.timestamp = started
        outcome.build_created = self.build.kbuild.created if self.build else ""
        outcome.revision = self.build.kbuild.revision if self.build else {}
        outcome.artifacts_dir = self.build.path if self.build else ""
        outcome.log = self._keep_console(console, outcome)
        # The ledger is unconditional and first: with no sinks at all, it is
        # still written, so "every run leaves a record" is not a caller's job.
        for one in (sinks if sinks is not None else (sink.Ledger(),)):
            if not one.wants(self, outcome):
                continue
            note = one.deliver(self, outcome)
            if note.startswith("NOT "):
                print(f"! {self.id()}: {note}", flush=True)

    def _keep_console(self, console, outcome):
        """Archive the console out of the workspace; its path goes into the record.

        The console is the only copy of what a real run printed, so it is written
        before anything can delete the workspace - and failing to write it must
        not cost the result.
        """
        if not console:
            return ""
        path = layout.logs(f"{self.build_id}.{self.test}.{outcome.timestamp}.log")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(console)
            return path
        except OSError:
            return ""

    def print(self, stream=None):
        print(f"{self.build_id}  {self.test}", file=stream)


class Jobs:
    """A set of jobs, and the batch run over them."""

    def __init__(self, items=()):
        self.items = list(items)

    @classmethod
    def for_build(cls, build, tests=None):
        """Every test this build may run, in catalogue order.

        A test the build cannot support is still listed: `reason()` says what is
        missing, and dropping it silently is how a green run hides a gap.
        """
        want = tuple(tests) if tests else DEFAULT_TESTS
        return cls(Job(build, test) for test in want)

    def reason(self, job):
        """Why this job cannot run here, or '' when it can."""
        if job.build is None:
            return "no build"
        return "; ".join(job.build.missing(job.test))

    def runnable(self):
        """`[(job, reason)]`, reason empty when the job can actually run."""
        return [(job, self.reason(job)) for job in self.items]

    def run(self, config, sinks: tuple[Sink, ...] | None = None,
            source: str = "local") -> list[Outcome]:
        """Run them in order, one Outcome each; a failure does not stop the rest."""
        return [job.run(config, sinks=sinks, source=source) for job in self.items]

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def print(self, stream=None):
        for job in self.items:
            job.print(stream)


def _announce(argv, label):
    """The one line an operator greps for before a ten-minute silence."""
    print(f"running: {label}: {' '.join(argv)}", flush=True)
