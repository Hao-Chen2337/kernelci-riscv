# SPDX-License-Identifier: LGPL-2.1-or-later
"""The three exit codes and the exceptions that carry them.

A run ends in exactly one of three ways, and the exit status says which:

    0  pass          the console showed the test ran and nothing failed
    1  test failure  the console showed at least one selftest failure
    3  infra         we never got a verdict: bad flags, unreachable artifacts,
                     timeout, tuxrun refusing the job, API down

3 is LAVA's "incomplete", and the pipeline reads it as infrastructure rather
than as a test result.  The infrastructure side arrives as exceptions; a test
failure does not - it is the exit status a caller returns (`EXIT_TEST_FAIL`) -
so a traceback never means "the tests failed".

接口形状（C++，只有声明）：include/kci/base.hpp §1 退出码与异常。
"""

EXIT_PASS = 0
EXIT_TEST_FAIL = 1
EXIT_INFRA = 3

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_INFRA = "incomplete"
VERDICT_ERROR = "error"


class KciError(Exception):
    """Base: anything this project raises on purpose."""

    exit_code = EXIT_INFRA


class ConfigError(KciError):
    """The operator asked for something impossible (unknown test, no API, bad flag)."""

    exit_code = EXIT_INFRA


class ApiError(KciError):
    """The API answered, but not with something usable."""

    exit_code = EXIT_INFRA


class ArtifactError(KciError):
    """A build's bytes are missing, truncated, or not fetchable."""

    exit_code = EXIT_INFRA


class InfraError(KciError):
    """The way to the bytes is broken, as opposed to the bytes themselves.

    The distinction `table.py pull` acts on: a build whose artifact 404s is one build to
    skip, while a proxy that cannot connect, a name that does not resolve or a TLS
    handshake that times out is true of *every* build - so a loop that treats the two the
    same either skips work that was fine or hammers a dead host for as many builds as it
    was given.  `ArtifactError` says "this build"; this says "this network".
    """

    exit_code = EXIT_INFRA


class LedgerError(KciError):
    """A record on disk that this tree cannot read.

    History is the one thing here that is not regenerable: `var/results/` is kept
    forever, and a reader that skipped a record it could not parse would answer
    "this machine ran nothing" for a machine that ran something.  So the reader
    raises - and this is the type it raises, because the record is neither an
    *artifact* (a build's bytes, refetchable) nor an *infrastructure* failure (the
    network): it is our own file.

    Deliberately **not** a subclass of `InfraError`, even though the exit code is
    the same 3: a caller that tells "the proxy is down, stop hammering" from "one
    record is corrupt, the rest are fine" needs the two to be different types
    (`table.py pull`'s breaker reads `InfraError`).
    """

    exit_code = EXIT_INFRA


# --- delivering a result to the pipeline ------------------------------------
#
# These three are a retry policy expressed as types, and the difference between
# them is the difference between "try again" and "this will never work".  The
# rule they encode: a result that has not been accepted must stay unaccepted -
# it is re-posted, never re-run.

class CallbackTransientError(KciError):
    """The endpoint may accept it next time (5xx, a dead network, no URL yet)."""

    exit_code = EXIT_INFRA


class CallbackPermanentError(KciError):
    """It will never accept this (a 4xx, a redirect): give up and move on."""

    exit_code = EXIT_INFRA


class CallbackMissingURLError(CallbackTransientError):
    """No callback URL *yet* - deliberately transient, so the report is kept."""

    exit_code = EXIT_INFRA
