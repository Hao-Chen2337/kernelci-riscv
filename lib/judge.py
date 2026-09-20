# SPDX-License-Identifier: LGPL-2.1-or-later
"""The console's verdict for one tuxrun run: TAP counts, or why there is none.

tuxrun exits 0 even when every selftest fails, so the TAP - never the exit code -
carries the verdict, and a console with no TAP at all is a failure, never a pass.

接口形状（C++，只有声明）：include/kci/engine.hpp §12 判决。
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import errors
from .out import Outcome

# Three things the old run/judge.py had, dropped on purpose:
#   * its EXIT_*/VERDICT_* re-exports: errors.py owns that vocabulary, and two
#     owners is how a verdict starts disagreeing with its own exit code.
#   * judge_run()'s (verdict, exit_code, detail, summary, per_test) 5-tuple:
#     verdict() returns the Outcome the callers hand to a sink.
#   * TUXRUN_TIMEOUT: the module owned the number so its own message could not
#     name another one.  The timeout now belongs to the runner that enforces it,
#     so no reason here quotes a number this module does not own.
# Nothing here is a rebindable module name: those existed so a guard test could
# patch behaviour, and once a guard is gone the seam only hides the real call.

# CSI (ESC [ params letter), OSC (ESC ] ... BEL/ST) and stray C0 controls; TAB
# and LF survive, they are the console's line structure.
ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|[\x00-\x08\x0b-\x1f\x7f]"
)

# One top-level TAP line: "<timestamp> ok 3 selftests: riscv: hwprobe".  The
# prefix tolerates a leading token (LAVA stamps every line) and the patterns
# tolerate whitespace splits and glued variants ("notok", "NOT OK", "not  ok").
_TAP_LINE = r"(?m)^[ \t]*(?:\S+ )?"

# An argparse refusal exits 2; that is the only return code this module reads.
REFUSED_RC = 2

# LAVA's own verdict: a job case dict carrying error_type Infrastructure.  The
# gap is bounded (but spans newlines) so the search cannot wander across a
# multi-megabyte console; the bare marker below is deliberately unbounded, since
# a case dict longer than the gap must not turn a real infra failure into an
# ordinary one.
JOB_CASE_GAP = 8192

# lava_body keeps only the last 200 characters of error_msg, so every reason is
# built inside this budget, with its most useful part last.
ERROR_MSG_BUDGET = 190
# Windows, never whole-console copies: building a 190-character answer out of
# 14 MB of trailing output cost +205 MB peak RSS.
ERROR_MSG_WINDOW = JOB_CASE_GAP + 4096  # the case dict and its trailing fields
ERROR_MSG_TAIL = 4096  # an unrecognised failure prints its reason last

TUXRUN_ERROR_LINE_RE = re.compile(r"^\s*(tuxrun: error: .*)$", re.MULTILINE)
INVALID_CHOICE_RE = re.compile(r"invalid choice: '([^']+)'")
CHOICES_TAIL_RE = re.compile(r"\s*\(choose from .*\)\s*$")

# Boot evidence from the guest's own console, not LAVA's "Wait for prompt"
# chatter; a `boot` job has no TAP to carry a verdict.
BOOT_EVIDENCE_RE = re.compile(r"\[\s*0\.000000\]|Booting Linux")
LAVA_CASE_RE = re.compile(r"'case': '([^']+)'.*?'result': '(pass|fail|skip)'")

_TUXLAVA_HINT = ("tuxlava has no '{name}' class: apply the one-time "
                 "config/tuxlava-kselftest-riscv.patch (docs/RUNBOOK.md)")


@dataclass
class Tap:
    """The top-level TAP results of one run: the counts, and each name's status."""

    total: int = 0
    failed: int = 0
    skipped: int = 0
    per_test: dict[str, str] = field(default_factory=dict)


def strip_ansi(console: str) -> str:
    """The console without escape sequences; the same string object when there is none."""
    if ANSI_RE.search(console) is None:
        # An unconditional copy of a multi-megabyte console is pure overhead.
        return console
    return ANSI_RE.sub("", console)


def tap_summary(console: str, label: str) -> Tap:
    """The top-level TAP results under *label*; nothing parsed at all means failed = 1.

    One name failing anywhere is that name failing: a later `ok` for it does not
    erase the failure.  A suite that retries a flaky test prints both lines, and
    reading the retry as the verdict is how a failure disappears from a report -
    the one answer a regression lab may not give.
    """
    pattern = _tap_pattern(label)
    status: dict[str, str] = {}
    failed: set[str] = set()
    # finditer, not splitlines: a 14 MB console must not become 700k line objects.
    for match in pattern.finditer(strip_ansi(console)):
        if match.group("failed") is not None:
            name = match.group("failed")
            status[name] = "fail"
            failed.add(name)
        elif match.group("started") is not None:
            # Started and never reported: a failure, unless a result line for the
            # same name follows (a nested TAP line has no marker and never
            # reaches here).
            status.setdefault(match.group("started"), "fail")
        elif match.group("passed") not in failed:
            name = match.group("passed")
            status[name] = "skip" if "# SKIP" in match.group("rest") else "pass"
    if not status:
        # No TAP at all: the suite never ran, so the one case this reports is a
        # failure.  Never report that as a pass, and never as nothing to report.
        return Tap(failed=1)
    return Tap(
        total=len(status),
        failed=sum(1 for result in status.values() if result == "fail"),
        skipped=sum(1 for result in status.values() if result == "skip"),
        per_test=status,
    )


def infra_reason(returncode: int | None, console: str, test: str) -> str | None:
    """Why this run got no verdict, or None when it did: refusal, job failure, timeout."""
    cleaned = strip_ansi(console)
    if returncode == REFUSED_RC and "error:" in cleaned and (
        "usage:" in cleaned or "invalid choice" in cleaned
    ):
        # tuxrun refused the invocation: unknown test class, bad flag.  Ours.
        return _refusal_reason(cleaned)
    if "cannot terminate cleanly" in cleaned or _infra_marker(cleaned):
        # The job itself failed - artifacts, container, a serial line that died.
        return _job_reason(cleaned)
    if returncode is None:
        return (f"tuxrun timed out running {test}: the console is what was "
                "captured before the kill")
    return None


def verdict(returncode: int | None, console: str, test: str) -> Outcome:
    """The whole decision, once: infra when there is no verdict, else the console's."""
    reason = infra_reason(returncode, console, test)
    if reason is not None:
        return Outcome.infra(reason, test=test)
    if test == "boot":
        return _boot_verdict(returncode, console, test)
    return _tap_verdict(returncode, console, test)


def _verdictless(returncode: int | None, console: str, test: str, what: str) -> Outcome:
    """No verdict in the console: infra if tuxrun itself failed, else a test failure.

    tuxrun exits 0 even when every selftest fails, so a non-zero exit is never
    "the tests failed" - it means we never got as far as a verdict, which is
    exactly what exit 3 is for.  Reporting it as a test failure would invent a
    regression, and a false regression is the worst answer this tool can give.
    """
    if returncode not in (0, None):
        return Outcome.infra(f"{what}, and tuxrun exited {returncode}: no verdict",
                             test=test)
    return Outcome(test=test, verdict=errors.VERDICT_FAIL,
                   exit_code=errors.EXIT_TEST_FAIL, detail=f"{what}; never a pass",
                   results={"total": 0, "failed": 1, "skipped": 0})


# --- the two non-infra verdicts ---------------------------------------------


def _tap_verdict(returncode: int | None, console: str, test: str) -> Outcome:
    """A test job: the TAP lines are the verdict, the return code only annotates it."""
    tap = tap_summary(console, test)
    results = {"total": tap.total, "failed": tap.failed, "skipped": tap.skipped}
    if tap.total == 0:
        # No TAP at all: the suite never ran, so this is never a pass.
        return _verdictless(returncode, console, test,
                            "no TAP lines at all (the suite never started)")
    # English pluralises, so it is pluralised: `12 selftests`, `1 selftest`.  The record
    # used to say `12 selftest(s)`, which is not a word in any language - and it stopped
    # being invisible when the builds/jobs page started printing a record's `detail`
    # verbatim, where `selftest(s)` read as the page's own sloppiness rather than as
    # stored text.  Records written before this line keep their spelling: the ledger is
    # history and rewriting it to look tidier would be a claim about runs nobody can
    # re-observe.
    detail = (f"{tap.total} {'selftest' if tap.total == 1 else 'selftests'}: "
              f"{tap.total - tap.failed - tap.skipped} pass, "
              f"{tap.failed} fail, {tap.skipped} skip")
    if tap.failed:
        return Outcome(test=test, verdict=errors.VERDICT_FAIL,
                       exit_code=errors.EXIT_TEST_FAIL, detail=detail, results=results)
    if returncode != 0:
        detail += (f" (tuxrun exited {returncode}; the TAP, not tuxrun's exit code, "
                   "carries the selftest verdict)")
    return Outcome(test=test, verdict=errors.VERDICT_PASS,
                   exit_code=errors.EXIT_PASS, detail=detail, results=results)


def _boot_verdict(returncode: int | None, console: str, test: str) -> Outcome:
    """A boot job: boot evidence is the pass, and the exit code is not the verdict.

    A boot test's whole job is to start the kernel, so tuxrun exiting non-zero
    *is* that test failing (an invocation tuxrun refused was already caught as
    infra, above).  A console with no boot at all is the opposite case: we never
    got a verdict, which is exit 3 - and the callback body says the same thing,
    so the ledger and the pipeline cannot disagree about one run.
    """
    if returncode != 0:
        return Outcome(test=test, verdict=errors.VERDICT_FAIL,
                       exit_code=errors.EXIT_TEST_FAIL,
                       detail=f"tuxrun exited {returncode}; see the log")
    cleaned = strip_ansi(console)
    cases: list[str] = []
    job = ""
    for match in LAVA_CASE_RE.finditer(cleaned):
        if match.group(1) in ("login-action", "kernel-messages"):
            cases.append(match.group(2))
        elif match.group(1) == "job":
            job = match.group(2)
    if job == "fail" or "fail" in cases:
        return Outcome(test=test, verdict=errors.VERDICT_FAIL,
                       exit_code=errors.EXIT_TEST_FAIL,
                       detail="tuxrun reported the boot as failed")
    if cases or job == "pass" or BOOT_EVIDENCE_RE.search(cleaned):
        return Outcome(test=test, verdict=errors.VERDICT_PASS, exit_code=errors.EXIT_PASS,
                       detail="guest booted")
    return Outcome.infra("tuxrun exited 0 but the log shows no boot at all (no kernel "
                         "console output, no login prompt, no boot case)", test=test)


# --- TAP parsing ------------------------------------------------------------


def _tap_pattern(label: str) -> re.Pattern[str]:
    """The per-line pattern for *label*'s top-level TAP results (labels differ per run)."""
    marker = re.escape("selftests: " + label.removeprefix("kselftest-") + ":")
    # One alternative per kind, in this order: the optional leading token can
    # swallow a "not", so a failure has to be recognised before an ok or the
    # same line would be counted as a pass.  A nested TAP line carries no
    # marker and matches nothing.
    return re.compile(
        _TAP_LINE + rf"not[ \t\r]*ok \d+ {marker}\s+(?P<failed>\S+)"
        + "|" + _TAP_LINE + rf"(?<!not)ok \d+ {marker}\s+(?P<passed>\S+)(?P<rest>.*)"
        + "|" + _TAP_LINE + rf"# {marker}\s+(?P<started>\S+)",
        re.IGNORECASE,
    )


# --- reason strings, all built inside a bounded window ----------------------


def _quoted(text: str) -> str:
    """A dict key/value marker for *text* in either quote style, escapes tolerated."""
    # A log line can be a repr, a JSON object, or the repr of a repr (LAVA embeds
    # its own, doubling the backslashes).
    return r"\\?['\"]" + re.escape(text) + r"\\?['\"]"


JOB_CASE_INFRA_RE = re.compile(
    _quoted("case") + r"\s*:\s*" + _quoted("job")
    + rf"[\s\S]{{0,{JOB_CASE_GAP}}}?"
    + _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)
INFRA_MARKER_RE = re.compile(
    _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)
ERROR_MSG_FIELD_RE = re.compile(
    _quoted("error_msg") + r"\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)
ERROR_MSG_PLAIN_FIELD_RE = re.compile(
    r"[\"']error_msg[\"']\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)


def _infra_marker(cleaned: str) -> bool:
    """True when the console self-reports LAVA's Infrastructure error_type."""
    return bool(JOB_CASE_INFRA_RE.search(cleaned) or INFRA_MARKER_RE.search(cleaned))


def _refusal_reason(cleaned: str) -> str:
    """The `tuxrun: error:` line, its choices list dropped, with the tuxlava hint last."""
    hint = _tuxlava_hint(cleaned)
    match = TUXRUN_ERROR_LINE_RE.search(cleaned)
    if match is None:
        return _job_reason(cleaned)
    # With a hint the marker is redundant, and its 21 characters are what the
    # intact hint needs.
    replacement = "" if hint else " (invalid test name)"
    line = CHOICES_TAIL_RE.sub(replacement, match.group(1))
    return _compose(_condense(line), hint, _clip_head)


def _job_reason(cleaned: str) -> str:
    """The last Infrastructure case's own error_msg, else a bounded console tail."""
    hint = _tuxlava_hint(cleaned)
    last: re.Match[str] | None = None
    for last in JOB_CASE_INFRA_RE.finditer(cleaned):
        pass  # the LAST verdict wins: earlier ones are stale attempts
    if last is None:
        # Nothing recognisable: a traceback, a shutdown line - the reason is last.
        return _compose(_condense(cleaned[-ERROR_MSG_TAIL:]), hint, _clip_tail)
    return _compose(_case_reason(cleaned, last), hint, _clip_reason)


def _case_reason(cleaned: str, case: re.Match[str]) -> str:
    """The job case's own error_msg, read from a window around the case dict."""
    start = max(0, case.start() - ERROR_MSG_WINDOW)
    end = min(len(cleaned), case.end() + ERROR_MSG_WINDOW)
    window = cleaned[start:end]
    # The case dict's own error_msg is authoritative; the dict's prefix would
    # spend the whole budget on scaffolding.  LAVA does not fix the field order,
    # so the candidate nearest the verdict wins.
    anchor = case.start() - start
    field = _closest(ERROR_MSG_FIELD_RE, window, anchor)
    if field is None:
        # A repr of a repr: normalise the bounded window and retry in plain.
        window = _unescape(window)
        field = _closest(ERROR_MSG_PLAIN_FIELD_RE, window, anchor)
    if field is None:
        return _condense(cleaned[case.start():end])
    value = field.group(1)
    return _condense(_unescape(value[1:-1]) if len(value) >= 2 else value)


def _closest(pattern: re.Pattern[str], window: str, anchor: int) -> re.Match[str] | None:
    """The match of *pattern* starting nearest *anchor*, or None."""
    best: re.Match[str] | None = None
    for match in pattern.finditer(window):
        if best is None or abs(match.start() - anchor) < abs(best.start() - anchor):
            best = match
    return best


def _tuxlava_hint(cleaned: str) -> str:
    """The one-time patch to name when tuxrun rejects a test tuxlava does not provide."""
    match = INVALID_CHOICE_RE.search(cleaned)
    if match is None or not match.group(1).startswith("kselftest"):
        return ""
    return _TUXLAVA_HINT.format(name=match.group(1))


def _compose(message: str, hint: str, clip: Callable[[str, int], str]) -> str:
    """Attach the actionable *hint* LAST and intact, inside ERROR_MSG_BUDGET."""
    if not hint:
        return clip(message, ERROR_MSG_BUDGET)
    budget = ERROR_MSG_BUDGET - len(hint) - len(" | ")
    if budget <= 0:
        # A pathological class name: only the hint fits, and its own tail (the
        # patch path) is the actionable part.
        return hint[-ERROR_MSG_BUDGET:]
    return f"{clip(message, budget)} | {hint}"


def _condense(text: str) -> str:
    """Collapse every whitespace run (spaces, newlines, CRLF) into one space."""
    return " ".join(text.split())


def _unescape(text: str) -> str:
    """Undo the backslash escapes of a repr'd log line (bounded window only)."""
    if "\\" not in text:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def _clip_head(message: str, budget: int) -> str:
    """Keep the HEAD: argparse names the problem in its first words."""
    if len(message) <= budget or budget <= 3:
        return message[:max(budget, 0)]
    return message[:budget - 3] + "..."


def _clip_reason(message: str, budget: int) -> str:
    """Keep BOTH ends: the head names the artifact, the end is the failure mode."""
    if len(message) <= budget:
        return message
    if budget < 16:
        return message[:budget]
    tail = max(8, (budget - 5) // 3)
    return f"{message[:budget - tail - 5]} ... {message[-tail:]}"


def _clip_tail(message: str, budget: int) -> str:
    """Keep the TAIL: an unrecognised failure's reason is printed last."""
    return message[-budget:] if budget > 0 else ""
