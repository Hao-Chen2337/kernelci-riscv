#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""Host-port probes shared by the local stack and the artifact server.

Every port this deployment uses is overridable (KCI_*_PORT) and nothing checked
whether the value was free before a service was started on it.  A port held by
an unrelated listener then surfaced three layers down as "X artifact server
failed" - with the real EADDRINUSE only inside /tmp/fs8999.log - or as a compose
bind failure that blamed the API.  docs/HANDOVER.md used to tell people to move
the artifact server off 8999 "because the port is reserved"; that note is stale
(8999 binds here), and the check below is what answers the question where it
matters instead of by folklore.

Binding is the only honest test, for the same reason
scripts/fetch-and-run-latest.py probes its artifact server port by binding: a
listener that answers nothing still owns the port, and "something is there, but
it did not answer me, so carry on" is how a stale server ends up serving an
older build to a run that names a newer one.
"""

import os
import shutil
import socket
import subprocess

# The stack binds 0.0.0.0, but a probe against a specific address is what the
# callers need for "is the port I am about to hand to a local client taken?".
# A caller that must reproduce the stack's own bind passes host="0.0.0.0".
DEFAULT_HOST = "127.0.0.1"

# require_port_free() exempts a port published by OUR compose project (the stack
# is partly up and compose reconciles it).  "Ours" is the same value
# run-local-stack.sh builds as its PROJECT variable, resolved here so a caller
# that does not name its project still means the default deployment.
COMPOSE_PROJECT_ENV = "KCI_COMPOSE_PROJECT"
DEFAULT_COMPOSE_PROJECT = "kcirv"

# What the holder line says when neither ss nor lsof could be run: an empty line
# would read as "no holder" inside the very message that exists to name the
# conflict.
NO_HOLDER = "(listener could not be identified; install iproute2 for 'ss')"


def _command_output(argv, skip_header=False):
    """First two lines of *argv*'s stdout, or "" - a probe, never a failure.

    stderr is discarded exactly as the shell callers discarded it: ss absent,
    lsof denied and "no listener" all mean the same thing to the caller, which
    is why "could not be identified" is a sentence at the call site rather than
    an exception here.
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

    A failed bind is the answer, not an error: the caller is asking whether a
    service may be started here, and anything already holding the port - a live
    listener, or a socket another process left behind - says no.  SO_REUSEADDR
    is set because that is how the services themselves bind; without it a
    recently closed connection would look like a conflict.
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

    ss first (it names the process too), lsof second, and an explicit sentence
    last: this string is embedded in a refusal, and a refusal that cannot say
    who holds the port sends the reader hunting through service logs for a
    conflict that is not theirs.
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

    A listener this repo started (the partly-up stack) is not a conflict, so the
    caller has to tell it from somebody else's.  Docker absent or unreadable
    reports no owner, which only costs the "(compose project ...)" hint.
    """
    if not shutil.which("docker"):
        return ""
    info = _command_output([
        "docker", "ps", f"--filter=publish={port}",
        "--format", '{{.Label "com.docker.compose.project"}}',
    ])
    return info.splitlines()[0] if info else ""


def require_port_free(port, who, override_var, project=None):
    """Refuse to start *who* on *port* when somebody else already holds it.

    Raises SystemExit (exit status 1, the code the shell's exit 1 produced) with
    the message scripts/run-local-stack.sh prints today, so the refusal keeps the
    same detail wherever it is raised from: the port, the label of the service
    that wanted it, the holder, and the variable that moves this deployment
    instead.  A caller with its own wording keeps it by building the message
    from port_is_free()/port_holder() itself.

    *project* names the compose project this deployment owns; the default is the
    same value run-local-stack.sh uses for its PROJECT variable.
    """
    if port_is_free(port):
        return
    if project is None:
        project = os.environ.get(COMPOSE_PROJECT_ENV) or DEFAULT_COMPOSE_PROJECT
    owner = _compose_project(port)
    # The shell only exempted a port OWNED by our project: an empty owner
    # compared against an empty project must not read as "ours", or a foreign
    # listener would be waved through in silence.
    if owner and owner == project:
        return
    suffix = f" (compose project '{owner}')" if owner else ""
    # The KCI_*_PORT list really is at the top of that script, and every
    # override variable this check is called with is one of its entries.
    raise SystemExit(
        f"X port {port} for the {who} is already in use{suffix}\n"
        f"  holder: {port_holder(port)}\n"
        "  Name the conflict instead of letting the service fail on it later:\n"
        f"    stop that listener, or move this deployment with {override_var}=<free port>\n"
        "  (the KCI_*_PORT list is at the top of scripts/run-local-stack.sh)"
    )
