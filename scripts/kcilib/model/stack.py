# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The local stack, driven through the shell that owns starting it.

Starting the stack is scripts/run-local-stack.sh's job - compose, the port
probes, the artifact server, the real callback, the scheduler and the seed -
and `./run.sh stack` is its entry point.  This class re-implements none of
that: it runs those command lines and reads back only what they own (docker's
containers, the ports' bind probe, the pid file the shell writes).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from kcilib import repo_root
from kcilib.core import ports as _ports

# The shell owns these numbers: run.sh's own ${KCI_API_PORT:-8001} and the
# "--- ports ---" block at the top of scripts/run-local-stack.sh.  They are
# repeated here because a Python caller connects to the same services, and a
# guard reads both shell files to fail the moment one of them moves.
API_PORT_VAR = "KCI_API_PORT"
API_PORT = 8001
ARTIFACT_PORT_VAR = "KCI_SERVE_PORT"
ARTIFACT_PORT = 8999
CALLBACK_PORT_VAR = "KCI_CB_PORT"
CALLBACK_PORT = 8003

# The three ports a caller connects to, as status() reports them.
LISTENERS = (
    ("api", API_PORT_VAR, API_PORT),
    ("artifact", ARTIFACT_PORT_VAR, ARTIFACT_PORT),
    ("callback", CALLBACK_PORT_VAR, CALLBACK_PORT),
)

# Where run-local-stack.sh redirects the services it starts on the host: fixed
# /tmp paths, rotated to .prev by the next `stack`.  The API's log is not a
# file at all - that service runs in a container, so docker owns it.
SCHEDULER_LOG = "/tmp/sched-local.log"
API_CONTAINER = "kernelci-api"


def _port(var: str, default: int) -> int:
    """The port run.sh would use for *var*: $<var> when set, else its default.

    A value that is not a number raises rather than falling back: silently
    probing a different port than the shell publishes would make status() lie.
    """
    value = os.environ.get(var)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"{var}={value!r} is not a port number; run.sh would use it "
            f"verbatim"
        ) from None


class Stack:
    """The local KernelCI stack, driven through the scripts that own it."""

    def __init__(self, root: Path | None = None, project: str = "") -> None:
        """*root* overrides the checkout; *project* the compose project name.

        The default project is kcilib.core.ports' own - the same
        $KCI_COMPOSE_PROJECT fallback run-local-stack.sh builds, so a second
        deployment keeps one identity across the shell and this class.
        """
        self.root: Path = Path(root) if root is not None else Path(repo_root())
        self.project: str = (
            project
            or os.environ.get(_ports.COMPOSE_PROJECT_ENV)
            or _ports.DEFAULT_COMPOSE_PROJECT
        )

    # ---- the deployment's identity ---------------------------------------

    @property
    def api_url(self) -> str:
        """The API base run.sh itself talks to (env var, else its port)."""
        return os.environ.get("KCI_API_URL") or (
            f"http://127.0.0.1:{_port(API_PORT_VAR, API_PORT)}"
        )

    @property
    def artifact_url(self) -> str:
        """The artifact server the stack publishes on the host."""
        return f"http://127.0.0.1:{_port(ARTIFACT_PORT_VAR, ARTIFACT_PORT)}"

    @property
    def callback_url(self) -> str:
        """The lava_callback the stack runs on the host."""
        return f"http://127.0.0.1:{_port(CALLBACK_PORT_VAR, CALLBACK_PORT)}"

    @property
    def pid_file(self) -> Path:
        """The shell's service ownership record: role|pid|start|pattern lines.

        run-local-stack.sh writes it (and `./run.sh stop` reads it) at
        work/env/stack-<project>.pids; not existing means "nothing of ours was
        started from this checkout".
        """
        return self.root / "work" / "env" / f"stack-{self.project}.pids"

    # ---- the command lines (asserted by a guard, never executed by it) ----

    def _argv(self, *args: str) -> list[str]:
        """`./run.sh` with *args* - the one entry point every method uses."""
        return [str(self.root / "run.sh"), *args]

    def _run(self, *args: str,
             capture: bool = False) -> subprocess.CompletedProcess[str]:
        """Run one of run.sh's command lines and hand back the result.

        check=False on purpose: a stack that refuses to start (a taken port, a
        missing token) is a RETURN VALUE here, not an exception - the caller
        reads run.sh's exit status and its own message.  Output is inherited
        unless *capture*, so a long start stays visible while it happens.
        """
        return subprocess.run(self._argv(*args), cwd=str(self.root),
                              check=False, capture_output=capture, text=True)

    def _result(
            self, done: subprocess.CompletedProcess[str],
    ) -> dict[str, object]:
        """What a command-returning method reports: argv, status, and state.

        The status read after the command is the useful half of the answer (did
        the services come up, did stop really stop them), so it is part of the
        return value rather than a second call the caller may forget.
        """
        return {"argv": list(done.args), "returncode": done.returncode,
                "ok": done.returncode == 0, "status": self.status()}

    # ---- read-only state -------------------------------------------------

    def status(self) -> dict[str, object]:
        """What is up right now. Read-only: never starts or stops anything.

        Live answers only - docker's containers of this compose project (docker
        absent is an empty list, not an error), the roles in the shell's pid
        file, and whether each of the three ports has a listener.  The ports
        are probed by binding them through kcilib.core.ports - the one
        implementation of that question - at 127.0.0.1: the address a
        caller connects to, and the stack's own 0.0.0.0 bind holds it too.
        """
        return {
            "project": self.project,
            "pid_file": str(self.pid_file),
            "containers": self._containers(),
            "services": self._recorded_services(),
            "listening": {
                name: not _ports.port_is_free(_port(var, default))
                for name, var, default in LISTENERS
            },
        }

    def _containers(self) -> list[str]:
        """`docker ps` lines ("name state") for this compose project."""
        if not shutil.which("docker"):
            return []
        done = subprocess.run(
            ["docker", "ps", "-a",
             f"--filter=label=com.docker.compose.project={self.project}",
             "--format", "{{.Names}} {{.State}}"],
            check=False, capture_output=True, text=True)
        return [line.strip() for line in done.stdout.splitlines()
                if line.strip()]

    def _recorded_services(self) -> list[str]:
        """The host services recorded here, as "<role> pid N (state)".

        A pid whose /proc entry is gone reads as "gone": the record
        outlives the process it names, which is what ./run.sh stop copes
        with.
        """
        try:
            text = self.pid_file.read_text(encoding="utf-8")
        except OSError:
            return []
        services = []
        for line in text.splitlines():
            if "|" not in line:
                continue
            role, pid, *_rest = line.split("|")
            if not role or not pid:
                continue
            state = "alive" if Path(f"/proc/{pid}").is_dir() else "gone"
            services.append(f"{role} pid {pid} ({state})")
        return services

    # ---- commands --------------------------------------------------------

    def start(self, *, seed: bool = False) -> dict[str, object]:
        """Start the stack: `./run.sh stack`, with `--seed` when asked.

        The seed dispatches a kbuild node at the end of the same start:
        that is what makes `start(seed=True)` one call instead of two.
        """
        args = ("stack", "--seed") if seed else ("stack",)
        return self._result(self._run(*args))

    def stop(self) -> dict[str, object]:
        """Stop the whole stack (host services first, then docker compose)."""
        return self._result(self._run("stop"))

    def seed(self) -> dict[str, object]:
        """Dispatch a seed kbuild node: `./run.sh stack --seed` on its own."""
        return self._result(self._run("stack", "--seed"))

    def worker_once(self, **flags: str) -> int:
        """One worker batch: `./run.sh worker --once [--flag VALUE]...`.

        Each keyword becomes one worker flag (underscores become dashes:
        ``limit="1"`` -> ``--limit 1``); a keyword whose value is empty is a
        bare flag (``kvm_full=""`` -> ``--kvm-full``).  Returns run.sh's
        exit status, and the worker's output stays on the terminal: a run
        in progress is what the operator is watching.
        """
        args = ["worker", "--once"]
        for name, value in flags.items():
            args.append("--" + name.replace("_", "-"))
            if value:
                args.append(value)
        return self._run(*args).returncode

    def report(self) -> str:
        """`./run.sh report`'s stdout, verbatim - parsed nowhere here."""
        return self._run("report", capture=True).stdout

    def verify(self) -> bool:
        """Run the full gate (`./run.sh verify`) and report whether it passed.

        The gate's own lines are left on the terminal: on failure they are the
        answer, and a boolean with the evidence swallowed is not.
        """
        return self._run("verify").returncode == 0

    def logs(self, which: str, lines: int = 50) -> list[str]:
        """The last *lines* of one service's log, as the shell wrote it.

        *which* is api, artifact, callback or scheduler - the four services the
        stack starts.  A log that is not there yet is an empty list (the
        service has not run), but an unknown name raises: that is a typo,
        not a state.
        """
        if which == "api":
            return self._command_lines(
                ["docker", "logs", "--tail", str(lines), API_CONTAINER])
        path = self._log_path(which)
        if not path.exists():
            return []
        return self._command_lines(["tail", "-n", str(lines), str(path)])

    def _log_path(self, which: str) -> Path:
        """The fixed /tmp log run-local-stack.sh writes for *which*."""
        if which == "artifact":
            port = _port(ARTIFACT_PORT_VAR, ARTIFACT_PORT)
            return Path(f"/tmp/fs{port}.log")
        if which == "callback":
            port = _port(CALLBACK_PORT_VAR, CALLBACK_PORT)
            return Path(f"/tmp/cb{port}.log")
        if which == "scheduler":
            return Path(SCHEDULER_LOG)
        raise ValueError(
            f"unknown service {which!r}; the stack logs api, artifact, "
            f"callback, scheduler"
        )

    def _command_lines(self, argv: list[str]) -> list[str]:
        """*argv*'s stdout as lines; a command that fails answers [].

        Reading a log is a convenience over a service that may not exist (an
        absent container, a rotated file): the caller wants lines or none, not
        an exception about a log it never asked to be there.
        """
        done = subprocess.run(argv, check=False, capture_output=True,
                              text=True)
        return done.stdout.splitlines() if done.returncode == 0 else []
