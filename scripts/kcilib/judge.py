# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""The run verdict for one tuxrun run, in one place.

Exit-code contract - judge_run's exit_code IS the process exit status of the
local runner, and the same verdict LAVA reports for the worker's callback:
    0   pass: TAP produced, no selftest failed (or the guest booted)
    1   test failure: at least one selftest failed
    3   infrastructure: tuxrun never started (argparse error, LAVA job error),
        the console self-reports error_type Infrastructure, the run timed out,
        the guest never booted, or no TAP lines were produced at all
tuxrun exits 0 even when every selftest fails, so the TAP - never tuxrun's exit
code - carries the verdict (judge_run used to reach in through importlib).
"""

import re

# One verdict vocabulary.  Exit 3 for "infrastructure" mirrors LAVA's job
# status 3 (incomplete): "the tests ran and failed" vs "nothing ran at all".
EXIT_PASS = 0
EXIT_TEST_FAIL = 1
EXIT_INFRA = 3
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_INFRA = "infra"
# No verdict at all (stale artifact server, truncated download, ...).
VERDICT_ERROR = "error"


# The local runner's tuxrun subprocess timeout, quoted by judge_run's timeout
# detail so the message cannot name a timeout other than tuxrun's.
TUXRUN_TIMEOUT = 1800


# CSI (ESC [ params letter), OSC (ESC ] ... BEL/ST) sequences, and stray C0
# control characters; tab, LF and CR are kept (console text structure).
ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|[\x00-\x08\x0b-\x1f\x7f]"
)


def strip_ansi(text):
    """Remove ANSI colour/control sequences from tuxrun console output.

    Returns *text* itself when there is nothing to strip: an unconditional copy
    of a multi-megabyte console is pure overhead for bounded-window callers."""
    if ANSI_RE.search(text) is None:
        return text
    return ANSI_RE.sub("", text)


def tap_summary(output, label=""):
    """Count top-level TAP results for a kselftest job from the tuxrun console
    log.  tuxrun/LAVA report "job pass" even when a selftest fails, so the TAP
    lines must be read here: any top-level ``not ok`` (or a started test that
    never reported) makes the job fail.  Lines carry ANSI codes/timestamps.
    ``label`` builds the TAP marker: without one nothing matches (no pass)."""
    output = strip_ansi(output)
    collection = (
        label.removeprefix("kselftest-")
    )
    marker = "selftests: " + collection + ":"
    # Tolerate whitespace splits and glued variants ("notok", "NOT OK",
    # "not\x1b[31mok", "not  ok"): the ok lookbehind keeps glued "notok" out
    # of ok_m, and the not_ok loop overwrites any split "not ok" with fail.
    line = r"(?m)^[ \t]*(?:\S+ )?"
    ok_m = re.findall(
        line + rf"(?<!not)ok \d+ {re.escape(marker)}\s+(\S+)(.*)",
        output,
        re.IGNORECASE,
    )
    not_ok = re.findall(
        line + rf"not[ \t\r]*ok \d+ {re.escape(marker)}\s+(\S+)",
        output,
        re.IGNORECASE,
    )
    started = set(re.findall(line + rf"# {re.escape(marker)}\s+(\S+)", output))
    if not ok_m and not not_ok and not started:
        # No TAP at all: the suite never ran (tuxrun job-level failure).  Never
        # report that as pass - mark the suite failed so it surfaces as fail.
        return (
            {"total": 0, "failed": 1, "skipped": 0},
            {label: {"status": "fail"}},
            {},
        )
    ok_names = {name for name, _ in ok_m}
    finished = ok_names | set(not_ok)
    missing = started - finished
    # One entry per test name, last result wins (no count inflation).
    per_test = {}
    for name, rest in ok_m:
        per_test[name] = "skip" if "# SKIP" in rest else "pass"
    for name in not_ok:
        per_test[name] = "fail"
    for name in missing:
        per_test.setdefault(name, "fail")
    skipped = sum(1 for r in per_test.values() if r == "skip")
    failed = sum(1 for r in per_test.values() if r == "fail")
    summary = {"total": len(per_test), "failed": failed, "skipped": skipped}
    status = "pass" if failed == 0 else "fail"
    return summary, {label: {"status": status}}, per_test


LAVA_CASE_RE = re.compile(r"'case': '([^']+)'.*?'result': '(pass|fail|skip)'")


# The guest's own console output: boot evidence that does not come from LAVA's
# "Wait for prompt [...]" chatter.  A --test boot run has no TAP (judge_run).
BOOT_EVIDENCE_RE = re.compile(r"\[\s*0\.000000\]|Booting Linux")


def tuxrun_invocation_error(returncode, output):
    """argparse-level failures (unknown test class, bad flag) exit 2 and
    print usage - an infra problem, not a test result."""
    return (
        returncode == 2
        and "error:" in output
        and ("usage:" in output or "invalid choice" in output)
    )


def tuxrun_job_error(returncode, output):
    """A tuxrun run that never reached the tests: LAVA's own infrastructure
    marker (unreachable artifacts, corrupt images, invalid job data) - an
    infra problem.  Genuine boot/test failures do not print this line."""
    return "cannot terminate cleanly" in strip_ansi(output)


def _quoted(text):
    """A dict key/value marker for *text*, in either quote style: a log line can
    be a plain Python repr, a JSON object, or the repr of a repr (LAVA embeds
    its own repr inside the message, doubling the backslashes)."""
    return r"\\?['\"]" + re.escape(text) + r"\\?['\"]"


# LAVA's authoritative verdict: a job case dict carrying error_type
# Infrastructure.  The gap between the two fields is BOUNDED but spans
# newlines, so the pattern reads a repr, a JSON object and a multi-line dict
# without letting the search wander across a multi-megabyte console.
JOB_CASE_GAP = 8192
JOB_CASE_INFRA_RE = re.compile(
    _quoted("case") + r"\s*:\s*" + _quoted("job")
    + rf"[\s\S]{{0,{JOB_CASE_GAP}}}?"
    + _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)
# Fail-safe, deliberately NOT distance-bounded: a case dict whose own text
# exceeds the gap (a very long error_msg) would fail to match, reporting a real
# infrastructure failure as an ordinary job failure (status 2, error_type Job).
# A plain substring search, it can only *add* infra classifications.
INFRA_MARKER_RE = re.compile(
    _quoted("error_type") + r"\s*:\s*" + _quoted("Infrastructure")
)


def tuxrun_infra_error(returncode, output):
    """Authoritative infra signal: the final LAVA job case self-reports
    error_type 'Infrastructure' (e.g. serial connection closed mid-run).
    The string heuristics above are fallbacks for logs without that line."""
    cleaned = strip_ansi(output)
    return bool(
        JOB_CASE_INFRA_RE.search(cleaned) or INFRA_MARKER_RE.search(cleaned)
    )


def is_infra_error(output, returncode):
    """True when the run never produced a test result: bad flags (argparse
    exit 2), LAVA's job-level infrastructure marker, or the console's own
    error_type: Infrastructure verdict - checked in this order so the reason
    matches the classifier.  A timeout (no returncode) is judge_run's job."""
    return bool(
        tuxrun_invocation_error(returncode, output)
        or tuxrun_job_error(returncode, output)
        or tuxrun_infra_error(returncode, output)
    )


# The callback keeps only the last 200 characters of error_msg (see lava_body),
# so an infra reason has to fit in that window with its most useful part last.
ERROR_MSG_BUDGET = 190
TUXRUN_ERROR_LINE_RE = re.compile(r"^\s*(tuxrun: error: .*)$", re.MULTILINE)
INVALID_CHOICE_RE = re.compile(r"invalid choice: '([^']+)'")
CHOICES_TAIL_RE = re.compile(r"\s*\(choose from .*\)\s*$")
# Windows, never whole-console copies: joining 14 MB of trailing output to make
# a 190-character answer cost millions of token strings (+205 MB peak RSS).
ERROR_MSG_WINDOW = JOB_CASE_GAP + 4096  # the case dict + its trailing fields
ERROR_MSG_TAIL = 4096  # unrecognised failure: the reason is the very last text
ERROR_MSG_FIELD_RE = re.compile(
    _quoted("error_msg") + r"\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)
ERROR_MSG_PLAIN_FIELD_RE = re.compile(
    r"[\"']error_msg[\"']\s*:\s*"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
)


def missing_test_hint(output):
    """Name the documented one-time patch when tuxrun rejects a test name
    because tuxlava does not provide it: tuxrun builds ``--tests`` choices from
    tuxlava's registry, so a tuxlava without the riscv kselftest class fails as
    ``invalid choice: 'kselftest-riscv'`` - an unexplained infra error."""
    match = INVALID_CHOICE_RE.search(strip_ansi(output))
    if not match or not match.group(1).startswith("kselftest"):
        return ""
    return (f"tuxlava has no '{match.group(1)}' class: apply the one-time "
            f"config/tuxlava-kselftest-riscv.patch (docs/RUNBOOK.md)")


def _condense(text):
    """Collapse every whitespace run (spaces, newlines, CRLF) into one space."""
    return " ".join(text.split())


def _repr_unescape(text):
    """Undo the backslash escapes of a repr'd log line (bounded window only)."""
    if "\\" not in text:
        return text
    out = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            out.append(text[index + 1])
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def _clip_head(message, budget):
    """Keep the HEAD of *message*: argparse names the problem in its first words,
    and the choices list after it is dropped separately."""
    if len(message) <= budget:
        return message
    if budget <= 3:
        return message[:max(budget, 0)]
    return message[:budget - 3] + "..."


def _clip_reason(message, budget):
    """Keep BOTH ends of a reason that does not fit: the failure mode is the END
    of a reason ("...: Read timed out.") while the head names the artifact that
    failed, and the callback keeps only the last 200 characters sent - so
    ``message[:budget]`` reported node 6aa387ecba3aeacda180ff12 as
    "HTTPSConnectionPool(host='files." alone."""
    if len(message) <= budget:
        return message
    if budget < 16:
        return message[:budget]
    tail = max(8, (budget - 5) // 3)
    return f"{message[:budget - tail - 5]} ... {message[-tail:]}"


def _clip_tail(message, budget):
    """Keep the TAIL: an unrecognised failure's reason is printed last."""
    return message[-budget:] if budget > 0 else ""


def _compose(message, hint, clip):
    """Attach the actionable *hint* LAST and intact, inside ERROR_MSG_BUDGET: the
    callback keeps the LAST 200 characters, so the hint - the one-time tuxlava
    patch - must never be truncated (capping it at half dropped the path)."""
    if not hint:
        return clip(message, ERROR_MSG_BUDGET)
    budget = ERROR_MSG_BUDGET - len(hint) - len(" | ")
    if budget <= 0:
        # A pathological class name: only the hint still fits, and its own
        # tail (the patch path) is the actionable part.
        return hint[-ERROR_MSG_BUDGET:]
    return f"{clip(message, budget)} | {hint}"


def _verdict_reason(cleaned, verdict):
    """The reason carried by the job case dict that *verdict* matched.

    The dict's own ``error_msg`` is the authoritative reason: a 190-character
    prefix of the whole dict spends the budget on scaffolding instead of on the
    failure (a download timeout reported as a URL fragment).  The window reaches
    *before* the verdict as well as after it, because LAVA does not fix the
    field order - the candidate nearest the verdict wins."""
    start = max(0, verdict.start() - ERROR_MSG_WINDOW)
    end = min(len(cleaned), verdict.end() + ERROR_MSG_WINDOW)
    window = cleaned[start:end]
    anchor = verdict.start() - start
    field = _closest(ERROR_MSG_FIELD_RE, window, anchor)
    if field is None:
        # Doubly-escaped repr: normalise the bounded window, retry in plain.
        window = _repr_unescape(window)
        field = _closest(ERROR_MSG_PLAIN_FIELD_RE, window, anchor)
    if field is None:
        return _condense(cleaned[verdict.start():end])
    value = field.group(1)
    if len(value) >= 2:
        value = _repr_unescape(value[1:-1])
    return _condense(value)


def _closest(pattern, window, anchor):
    """The match of *pattern* whose start is nearest *anchor*, or None."""
    best = None
    for match in pattern.finditer(window):
        if best is None or abs(match.start() - anchor) < abs(best.start() - anchor):
            best = match
    return best


def tuxrun_error_message(output, label=""):
    """The infra reason to report, built for the callback's 200-character window.

    Neither tuxrun's argparse errors (one line whose choices list runs to
    thousands of characters) nor LAVA's dispatcher verdict (a case dict) has its
    useful text in the console's tail: reporting ``output[-2000:]`` produced
    "md-analyze', ..., 'zlib')" for a run whose real problem was a missing test
    class.  Three sources, in order of authority: the first ``tuxrun: error:``
    line with the choices list dropped; the LAST job-case Infrastructure verdict
    (only the final attempt counts), whose own ``error_msg`` field is reported
    rather than a prefix of the dict; a bounded console tail.
    ``label`` is kept for the callers' sake: the reason does not depend on it."""
    cleaned = strip_ansi(output)
    hint = missing_test_hint(cleaned)
    match = TUXRUN_ERROR_LINE_RE.search(cleaned)
    if match:
        # With a hint the marker is redundant (the hint names the rejected
        # class), and its 21 characters are what the intact hint needs.
        replacement = "" if hint else " (invalid test name)"
        message = _condense(CHOICES_TAIL_RE.sub(replacement, match.group(1)))
        return _compose(message, hint, _clip_head)
    verdict = None
    for verdict in JOB_CASE_INFRA_RE.finditer(cleaned):
        pass  # the LAST verdict wins: earlier ones are stale attempts
    if verdict is not None:
        return _compose(_verdict_reason(cleaned, verdict), hint, _clip_reason)
    # Nothing recognisable: the reason (a traceback, a shutdown line) sits at
    # the END of the output, so keep a bounded tail (without splitting it all).
    return _compose(
        _condense(cleaned[-ERROR_MSG_TAIL:]), hint, _clip_tail
    )


def judge_run(returncode, output, test):
    """The verdict for one tuxrun run:
    (verdict, exit_code, detail, summary, per_test).

    TAP parsing is tap_summary() here, not a second weaker copy (#23): tuxrun
    exits 0 even when every selftest fails, so it is authoritative (its total=0
    encoding is the "suite never ran" case, #2).  returncode is None on timeout."""
    if returncode is None:
        return (VERDICT_INFRA, EXIT_INFRA,
                f"tuxrun timed out after {TUXRUN_TIMEOUT}s", None, {})
    if is_infra_error(output, returncode):
        return (VERDICT_INFRA, EXIT_INFRA,
                tuxrun_error_message(output, test), None, {})
    if test != "boot":
        summary, _status, per_test = tap_summary(output, test)
        if summary["total"] == 0:
            # No TAP at all: the suite never ran.  Never a pass - exactly the
            # false green tap_summary() guards against.
            if returncode != 0:
                return (VERDICT_INFRA, EXIT_INFRA,
                        (f"no TAP lines and tuxrun exited {returncode}: the "
                         "guest never booted or the suite never started"),
                        summary, per_test)
            return (VERDICT_FAIL, EXIT_TEST_FAIL,
                    "tuxrun exited 0 but produced no TAP lines at all",
                    summary, per_test)
        detail = (f"{summary['total']} selftest(s): "
                  f"{summary['total'] - summary['failed'] - summary['skipped']} "
                  f"pass, {summary['failed']} fail, "
                  f"{summary['skipped']} skip")
        if summary["failed"]:
            return VERDICT_FAIL, EXIT_TEST_FAIL, detail, summary, per_test
        if returncode != 0:
            detail += (f" (tuxrun exited {returncode}; the TAP, not tuxrun's "
                       "exit code, carries the selftest verdict)")
        return VERDICT_PASS, EXIT_PASS, detail, summary, per_test
    # boot has no TAP, and the exit code alone is not a verdict (lava_body()
    # also refuses a run with no boot evidence a pass): require boot output.
    if returncode != 0:
        return (VERDICT_FAIL, EXIT_TEST_FAIL,
                f"tuxrun exited {returncode}; see the log", None, {})
    cleaned = strip_ansi(output)
    job_result = None
    boot_cases = []
    for raw in cleaned.splitlines():
        match = LAVA_CASE_RE.search(raw)
        if not match:
            continue
        if match.group(1) in ("login-action", "kernel-messages"):
            boot_cases.append(match.group(2))
        elif match.group(1) == "job":
            job_result = match.group(2)
    if job_result == "fail" or "fail" in boot_cases:
        return (VERDICT_FAIL, EXIT_TEST_FAIL,
                "tuxrun reported the boot as failed", None, {})
    if boot_cases or job_result == "pass" or BOOT_EVIDENCE_RE.search(cleaned):
        return (VERDICT_PASS, EXIT_PASS, "guest booted", None, {})
    return (VERDICT_INFRA, EXIT_INFRA,
            ("tuxrun exited 0 but the log shows no boot at all (no kernel "
             "console output, no login prompt, no boot case)"), None, {})
