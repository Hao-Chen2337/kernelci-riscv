#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Host-port probes shared by the local stack and the artifact server.

Binding is the only honest test: a listener that answers nothing still owns the
port.  run-local-stack.sh probes through this module's command line, so there is
one implementation of "is this port free" and not two that can differ.
Rationale: docs/code-notes/W2c-kcilib.md.
"""

import argparse
import os
import shutil
import socket
import subprocess

# What the callers need for "is the port I am about to hand to a client taken?".
# A caller reproducing the stack's own bind passes host="0.0.0.0".
DEFAULT_HOST = "127.0.0.1"

# require_port_free() exempts a port published by OUR compose project (the
# partly-up stack); the default is what run-local-stack.sh builds as PROJECT.
COMPOSE_PROJECT_ENV = "KCI_COMPOSE_PROJECT"
DEFAULT_COMPOSE_PROJECT = "kcirv"

# Never an empty line: a refusal that cannot name the holder has to say so.
NO_HOLDER = "(listener could not be identified; install iproute2 for 'ss')"


def _command_output(argv, skip_header=False):
    """First two lines of *argv*'s stdout, or "" - a probe, never a failure.

    stderr is discarded: ss absent, lsof denied and "no listener" all mean the
    same thing to the caller.
    """
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, check=False)
    except OSError:
        return ""
    lines = done.stdout.splitlines()
    if skip_header:
        lines = lines[1:]
    return "\n".join(lines[:2]).strip()


def port_is_free(port, host=DEFAULT_HOST):
    """True when *port* can be bound on *host* right now.

    A failed bind is the answer, not an error - anything holding the port, even
    a socket another process left behind, says no.  SO_REUSEADDR is set because
    that is how the services themselves bind.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def port_holder(port):
    """Best-effort description of the listener on *port* (never raises).

    ss first (it names the process), lsof second, an explicit sentence last:
    the string is embedded in a refusal that has to name the holder.
    """
    if shutil.which("ss"):
        info = _command_output(["ss", "-ltnpH", f"sport = :{port}"])
        if info:
            return info
    if shutil.which("lsof"):
        info = _command_output(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                               skip_header=True)
        if info:
            return info
    return NO_HOLDER


def _compose_project(port):
    """The compose project publishing *port*, or "" when none does.

    Docker absent or unreadable reports no owner, which only costs the hint.
    """
    if not shutil.which("docker"):
        return ""
    info = _command_output([
        "docker", "ps", f"--filter=publish={port}",
        "--format", '{{.Label "com.docker.compose.project"}}',
    ])
    return info.splitlines()[0] if info else ""


def require_port_free(port, who, override_var, project=None,
                      host=DEFAULT_HOST):
    """Refuse to start *who* on *port* when somebody else already holds it.

    Raises SystemExit (status 1, the code the shell produced) naming the port,
    the service that wanted it, the holder and the variable that moves this
    deployment.  *project* names the compose project this deployment owns.

    *host* is the address the probe binds and is NOT decoration: probing
    127.0.0.1 for a service that binds 0.0.0.0 would let a foreign listener on
    another interface through, which is why run-local-stack.sh passes
    host="0.0.0.0".
    """
    if port_is_free(port, host=host):
        return
    if project is None:
        project = os.environ.get(COMPOSE_PROJECT_ENV) or DEFAULT_COMPOSE_PROJECT
    owner = _compose_project(port)
    # An empty owner must not compare equal to an empty project, or a foreign
    # listener would be waved through in silence.
    if owner and owner == project:
        return
    suffix = f" (compose project '{owner}')" if owner else ""
    # Every override variable this check is called with is a KCI_*_PORT entry.
    raise SystemExit(
        f"X port {port} for the {who} is already in use{suffix}\n"
        f"  holder: {port_holder(port)}\n"
        "  Name the conflict instead of letting the service fail on it later:\n"
        f"    stop that listener, or move this deployment with {override_var}=<free port>\n"
        "  (the KCI_*_PORT list is at the top of scripts/run-local-stack.sh)"
    )


def main(argv=None):
    """The probe as a command line, for scripts/run-local-stack.sh.

    The shell's own copy of the bind test and the refusal text is gone, so the
    stack's check and fetch-and-run-latest.py's cannot answer differently.  A
    taken port exits 1 with the refusal on stderr; a free one exits 0 silently.
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m kcilib.core.ports",
        description="Check that a host port is free before a service binds it.",
    )
    parser.add_argument("--require", type=int, required=True, metavar="PORT",
                        help="the port that must be free")
    parser.add_argument("--label", required=True,
                        help="what wants the port (named in the refusal)")
    parser.add_argument("--override", required=True, metavar="VAR",
                        help="the KCI_*_PORT variable that moves this "
                             "deployment")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"address to probe (default {DEFAULT_HOST}; the "
                             "stack passes 0.0.0.0 because it binds 0.0.0.0)")
    parser.add_argument("--project", default=None,
                        help="compose project this deployment owns (default "
                             f"${COMPOSE_PROJECT_ENV} or "
                             f"{DEFAULT_COMPOSE_PROJECT!r})")
    args = parser.parse_args(argv)
    require_port_free(args.require, args.label, args.override,
                      project=args.project, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
