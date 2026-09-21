# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the operator asked for: flags and environment turned into objects.

One mapping, in one direction: argv in, config object out.  No config object is
written to disk and none carries a secret - the callback token is read at the
moment of delivery (`sink.callback_token()`), so a saved state file can never
become a credential.

The two objects are small on purpose.  They exist to be passed to a constructor
that needs six numbers, not to be the project's global settings.

接口形状（C++，只有声明）：include/kci/base.hpp §3 配置。
"""

import argparse
import os
from dataclasses import dataclass, field

from . import api, errors, tests
from .sink import Callback, Ledger

# Defaults, with the name of the thing they configure.  The old tree kept every
# number in one `policy.py`; that made a reader look in two files to learn what
# a timeout was, so each number now lives at its use and only the deployment's
# own knobs are here.
DEFAULT_DEVICE = tests.DEFAULT_DEVICE
DEFAULT_LAB = tests.DEFAULT_LAB
DEFAULT_CONTAINER_RUNTIME = tests.DEFAULT_CONTAINER_RUNTIME
DEFAULT_TIMEOUT = 1800
DEFAULT_POLL_PERIOD = 5


@dataclass
class RunConfig:
    """How to run one job: what, where, and for how long."""

    tests: tuple = ()
    # What tuxrun runs the dispatcher image in - NOT the lab name (see PollConfig).
    container_runtime: str = DEFAULT_CONTAINER_RUNTIME
    device: str = DEFAULT_DEVICE
    tuxrun_bin: str = "tuxrun"
    callback_url: str = ""
    timeout: int = DEFAULT_TIMEOUT
    # The guest image to boot, when the operator names one; "" = the default.
    rootfs: str = ""
    # Where a run's scratch space and its archived console go.
    output_dir: str = ""
    # Extra tuxrun parameters, as `--parameters k=v`.
    params: dict = field(default_factory=dict)

    def sinks(self):
        """The outlets for this run: the ledger always, the callback only when asked."""
        if not self.callback_url:
            return (Ledger(),)
        return (Ledger(), Callback(self.callback_url))


@dataclass
class PollConfig:
    """How the resident worker behaves: which queue, how often, how patient."""

    api_url: str = ""
    # The claim filters: a node whose platform or runtime differs is not ours.
    # `runtime` here is the LAB (pull-labs-riscv), which is what a job node's
    # `data.runtime` carries.  Collapsing this with the container runtime is how
    # a worker ends up rejecting every node the scheduler offers it.
    platform: str = DEFAULT_DEVICE
    runtime: str = DEFAULT_LAB
    container_runtime: str = DEFAULT_CONTAINER_RUNTIME
    state_file: str = ""
    period: int = DEFAULT_POLL_PERIOD
    max_retries: int = 5
    once: bool = False
    since: str = ""


def api_url(explicit=None):
    """The API to use: the flag, else $KCI_API_URL, else the local deployment."""
    return explicit or os.environ.get("KCI_API_URL") or api.LOCAL


def client(args=None, write=False, timeout=None):
    """An `api.Api` for this deployment; `write=True` also requires a token.

    *args* is a parsed command line (its `api_url` is the `--api-url` flag), not a
    URL: passing a string here silently reads no flag at all, which is how a page
    ends up ignoring `--api-url` while nobody reports anything.

    A page passes a short `timeout`: a flaky upstream then costs one slow page,
    not a page that stops answering.
    """
    if isinstance(args, str):
        raise errors.ConfigError("client() wants a parsed command line, not a URL string")
    url = api_url(getattr(args, "api_url", None))
    if timeout is None:
        return api.Api(url, token=_token() if write else None)
    return api.Api(url, token=_token() if write else None, timeout=timeout)


def run_flags(parser):
    """Add the flags every run shares: which API, which runtime, how long, where to report."""
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--container-runtime", dest="runtime", default=DEFAULT_CONTAINER_RUNTIME)
    parser.add_argument("--tuxrun-bin", default=os.environ.get("TUXRUN_BIN", "tuxrun"))
    parser.add_argument("--timeout", type=_positive, default=DEFAULT_TIMEOUT)
    parser.add_argument("--parameter", action="append", default=[], metavar="K=V")
    parser.add_argument("--rootfs", default="")
    parser.add_argument("--callback-url", default="")
    return parser


def run_from(args):
    """An already-parsed command line as a `RunConfig` - the entry points' one call."""
    return RunConfig(tests=tuple(getattr(args, "test", ()) or ()), container_runtime=args.runtime,
               device=args.device, tuxrun_bin=args.tuxrun_bin,
               callback_url=args.callback_url, timeout=args.timeout,
               rootfs=args.rootfs, output_dir=getattr(args, "output_dir", ""),
               params=_pairs(args.parameter))


def parse_run(argv=None):
    """`argv` (default: sys.argv) as a `RunConfig`, for callers with no parser of their own."""
    parser = run_flags(argparse.ArgumentParser(prog="run"))
    parser.add_argument("--output-dir", default="")
    return run_from(parser.parse_args(argv))


def parse_poll(argv=None):
    """`argv` as `(run, PollConfig, namespace)`.

    The namespace comes back because its caller needs the one thing a PollConfig does not
    carry: `client()`, which reads `--api-url` off a parsed command line and refuses a URL
    string.  Rationale: docs/gui-rework/round2/06-worker.md F2 - passing `poll.api_url`
    there is what made every worker start exit 1.

    **The usage line is named after the file that was typed.**  It said `prog="worker"`,
    so `pull_worker.py --help` printed `usage: worker` and a refusal read `worker: error:
    ...` - a name no operator can type, from the only entry point this parser serves.
    Every other entry point leaves `prog` to argparse, which is argv[0]'s own name
    (`table.py --help` says `table.py`), so this is that and nothing else.

    **The run config is built here too, because this is where tuxrun is configured.**
    The worker is the one process that really executes a job and it had no `--device` /
    `--tuxrun-bin` / `--timeout` / `--parameter`: those argv were argparse's
    `unrecognized arguments` (exit 2), so a worker could only ever run with
    `RunConfig()`'s defaults.  The four are the fields the worker's own path reads -
    `runner.argv()` the binary and the device, `Job.run()` the timeout, `runner`'s
    parameters the extras - and they are spelled exactly as `run_flags()` spells them,
    so one flag keeps one meaning on every entry point.  `--rootfs` and `--callback-url`
    are deliberately left out: `RunConfig.rootfs` has no reader anywhere in this tree
    (the guest disk comes from the definition's own artifact) and the worker's sinks
    come from the definition the pipeline sent (`Poller.handle`), so both flags would be
    accepted and quietly change nothing.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--platform", default=DEFAULT_DEVICE,
                        help="only claim jobs for this platform (data.platform)")
    parser.add_argument("--runtime", default=DEFAULT_LAB,
                        help="only claim jobs of this pipeline runtime (data.runtime)")
    parser.add_argument("--container-runtime", default=DEFAULT_CONTAINER_RUNTIME,
                        help="what tuxrun runs the dispatcher image in")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--poll-period", type=_positive, default=DEFAULT_POLL_PERIOD)
    parser.add_argument("--max-retries", type=_positive, default=5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--since", default="")
    # The run flags, for the jobs this process claims: `--platform` above is the
    # claim filter, this is what tuxrun boots when a definition names no platform.
    parser.add_argument("--device", default=DEFAULT_DEVICE,
                        help="the device a job definition that names none runs on")
    parser.add_argument("--tuxrun-bin", default=os.environ.get("TUXRUN_BIN", "tuxrun"))
    parser.add_argument("--timeout", type=_positive, default=DEFAULT_TIMEOUT)
    parser.add_argument("--parameter", action="append", default=[], metavar="K=V")
    args = parser.parse_args(argv)
    run = RunConfig(device=args.device, tuxrun_bin=args.tuxrun_bin,
                    timeout=args.timeout, params=_pairs(args.parameter))
    poll = PollConfig(api_url=api_url(args.api_url), platform=args.platform,
                      runtime=args.runtime, container_runtime=args.container_runtime,
                      state_file=args.state_file, period=args.poll_period,
                      max_retries=args.max_retries, once=args.once, since=args.since)
    return run, poll, args


def _positive(value):
    """An argparse type: a whole number above zero, or the operator is told why not."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value} must be at least 1")
    return number


def _pairs(items):
    """`["k=v", ...]` as a dict, refusing anything that is not a pair."""
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        if not key or not _:
            raise errors.ConfigError(f"--parameter wants K=V, got {item!r}")
        out[key] = value
    return out


def _token():
    """The write token from the environment; never stored, never passed around."""
    return os.environ.get("KCI_API_TOKEN", "")
