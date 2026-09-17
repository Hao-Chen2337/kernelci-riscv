"""The port probe the stack's shell entry point calls by module name."""
import os
import socket
import subprocess
import sys

from kcilib.core import ports

from .support import TOOLS, check


def test_port_probe():
    """#4: the port check the stack makes is kcilib.core.ports', not a second copy.

    scripts/run-local-stack.sh calls `python3 -m kcilib.core.ports --host 0.0.0.0`,
    so that contract is what is checked: a free port passes, a foreign listener
    exits 1 naming port, holder and KCI_*_PORT, our own compose project is no
    conflict, and an EMPTY owner is never ours.
    """
    # Explicit ports, NOT port 0: an ephemeral port makes this test depend on
    # the machine's ephemeral pool, and a box whose pool is exhausted fails
    # bind(0) with EADDRINUSE, which reads as "the port probe is broken".  The
    # stack's own ports (8001-8999) sit outside that range anyway.
    def _bind(host, wanted):
        for offset in range(32):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, wanted + offset))
            except OSError:
                sock.close()
                continue
            return sock, wanted + offset
        check(False, f"no free port in {wanted}..{wanted + 31} for the probe test; "
                     f"the machine may be out of sockets (see 'ss -s')")
    held, taken = _bind("0.0.0.0", 18801)
    held.listen(1)
    spare, free = _bind("127.0.0.1", 18851)
    spare.close()

    real_compose = ports._compose_project
    real_free = ports.port_is_free
    try:
        # A port nobody holds: no refusal, whatever the compose answer is.
        ports._compose_project = lambda _port: ""
        ports.require_port_free(free, "artifact server", "KCI_SERVE_PORT",
                                host="0.0.0.0")

        # Somebody else holds it: exit 1 naming port, holder and the way out.
        try:
            ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                                    host="0.0.0.0")
        except SystemExit as refusal:
            # The refusal is a message SystemExit: python prints it to stderr
            # and exits 1, so `refusal.code` is the MESSAGE, not 1.  The exit
            # status is checked below through the real command line.
            message = str(refusal)
            check(isinstance(refusal.code, str) and "already in use" in message,
                  f"a taken port must refuse with a message: {refusal.code!r}")
            for needle in (str(taken), "artifact server", "KCI_SERVE_PORT"):
                check(needle in message,
                      f"the refusal must name {needle!r}: {message}")
        else:
            check(False, "a taken port must refuse")

        # Published by OUR compose project: not a conflict.
        ports._compose_project = lambda _port: "kcirv"
        ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                               project="kcirv", host="0.0.0.0")

        # An empty owner is NOT ours: an unnamed deployment must not wave a
        # foreign listener through in silence.
        ports._compose_project = lambda _port: ""
        try:
            ports.require_port_free(taken, "artifact server", "KCI_SERVE_PORT",
                                    project="", host="0.0.0.0")
        except SystemExit:
            pass
        else:
            check(False, "an empty owner must not be read as our own project")

        # The host is forwarded, not defaulted away: probing 127.0.0.1 for a
        # 0.0.0.0 service is the weaker check.
        seen = []

        def recording_probe(port, host=ports.DEFAULT_HOST):
            seen.append(host)
            return True

        ports.port_is_free = recording_probe
        ports.require_port_free(1234, "x", "KCI_X_PORT", host="0.0.0.0")
        ports.require_port_free(1234, "x", "KCI_X_PORT")
        check(seen == ["0.0.0.0", ports.DEFAULT_HOST],
              f"the probe host must be forwarded, got {seen}")

        # The command line run-local-stack.sh calls, end to end: exit 1 on a
        # taken port with the refusal on stderr, exit 0 on a free one.
        # PYTHONPATH is scripts/ (where kcilib lives), not this file's directory.
        env = dict(os.environ, PYTHONPATH=os.path.dirname(TOOLS))

        def probe(port):
            return subprocess.run(
                [sys.executable, "-m", "kcilib.core.ports", "--require", str(port),
                 "--label", "artifact server", "--override", "KCI_SERVE_PORT",
                 "--host", "0.0.0.0", "--project", "kcirv"],
                cwd=TOOLS, env=env, check=False, capture_output=True,
                text=True)

        ports._compose_project = lambda _port: ""
        taken_run = probe(taken)
        check(taken_run.returncode == 1,
              f"the CLI must exit 1 on a taken port, got {taken_run.returncode}")
        check("already in use" in taken_run.stderr,
              f"the refusal must reach stderr: {taken_run.stderr!r}")
        free_run = probe(free)
        check(free_run.returncode == 0,
              f"the CLI must exit 0 on a free port, got {free_run.returncode}: "
              f"{free_run.stderr!r}")
    finally:
        ports._compose_project = real_compose
        ports.port_is_free = real_free
        held.close()
    print("test_port_probe OK")
