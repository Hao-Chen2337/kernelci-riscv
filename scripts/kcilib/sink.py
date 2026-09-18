# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Sinks: where a run's result goes.

A sink is a name + a switch (wants) + one delivery (deliver); sinks_for() is the
only place that decides, and it decides from the job definition.  The ledger is
unconditional, the callback only when the definition carries callback.url.

deliver() hands one result to a set of sinks; deliver_report() is the same for
the worker line (kcilib.run.poll), whose result already exists when it is handed
over and may not be dropped - its docstring is where that one difference is
spelled out.  Both lines reach post_result() through CallbackSink, so neither
caller holds an idea of its own about where a result goes.

Rationale: docs/code-notes/A-sink-source-dashboard.md.
"""

from kcilib.run import callback

# Sink names: callers look up and report by name, never by isinstance.
LEDGER = "ledger"
CALLBACK = "callback"


class Sink:
    """One sink: its name, whether this run wants it, and how it delivers."""

    name = ""

    def wants(self, definition):
        """Whether this run uses the sink - the one place that decides."""
        raise NotImplementedError

    def deliver(self, definition, outcome=None, report=None):
        """Deliver the result, returning where it went (None for nowhere).

        *outcome* is the execution layer's RunOutcome; *report* is run_node's
        (callback_url, token, body) tuple.  Each sink touches only what it needs.
        """
        raise NotImplementedError


class LedgerSink(Sink):
    """The ledger sink: work/results/<build-id>/<test>.json.  Always runs."""

    name = LEDGER

    def wants(self, definition):
        # Unconditional: the ledger is the only sink that needs no service.
        return True

    def deliver(self, definition, outcome=None, report=None):
        """Deliver = report the record the execution layer already wrote.

        Writing it again here would drop log/results - see the notes file.
        """
        return (outcome or {}).get("record")


class CallbackSink(Sink):
    """The callback sink: POST the result to callback.url.  Conditional."""

    name = CALLBACK

    def wants(self, definition):
        return bool(callback.callback_url(definition))

    def deliver(self, definition, outcome=None, report=None):
        """*report* is exactly post_result's three arguments, passed through.

        The token is not in the definition: run_node read it from the environment
        and it arrives inside report.
        """
        if report is None:
            raise ValueError(
                "the callback sink needs the run's report tuple "
                "(callback_url, token, body): without the body lava_body() "
                "built there is nothing to post")
        callback.post_result(*report)


# Factory sinks, in delivery order.  Adding one means adding a class here, and
# callers that pass their own group to deliver() do not change at all.
SINKS = (LedgerSink, CallbackSink)


def sinks_for(definition):
    """Definition -> the sinks this run uses, in delivery order.  Sole decision point.

    Order is a contract: the ledger is always first, so a failing callback cannot
    erase a record that is already on disk.
    """
    chosen = []
    for cls in SINKS:
        candidate = cls()
        if candidate.wants(definition):
            chosen.append(candidate)
    return tuple(chosen)


def has_callback(sinks):
    """Whether this set of sinks includes the callback (otherwise: ledger only)."""
    return any(item.name == CALLBACK for item in sinks)


def deliver(sinks, definition, outcome=None, report=None):
    """Hand one run's result to every sink in *sinks*, in delivery order.

    Returns {sink name: delivery result} (the ledger's is the record path).  A
    callback sink with no *report* is skipped, not failed: there is no body to
    send; real failures still raise from post_result and are not swallowed.
    """
    delivered = {}
    for item in sinks:
        if item.name == CALLBACK and report is None:
            continue
        delivered[item.name] = item.deliver(
            definition, outcome=outcome, report=report)
    return delivered


def deliver_report(report, definition=None):
    """Deliver one run's report (callback_url, token, body): the worker's line.

    kcilib.run.poll's entry point, and the one thing it does beyond deliver():
    a report that no chosen sink took is handed to the callback sink anyway.
    The sink set is still sinks_for(*definition*) - the decision stays there -
    and the callback sink is added only when it is not in it, which is exactly
    the case "the definition carries no callback.url".  The ledger sink is first
    and unchanged, as everywhere in this module: its delivery is the record
    kcilib.run.jobrun.record_result wrote before run_node() returned this very
    report, so that record is on disk before the callback is attempted - the
    order this module promises.  (A worker report carries no record path, so
    that delivery answers None here; it never writes a second time.)

    Why that case may not be a skip here: a worker run has ALREADY happened by
    the time its result is delivered, so the report is the only copy of it, and
    the callback sink is the sink that can say why it cannot be posted - its own
    post_result() raises CallbackMissingURLError, a CallbackTransientError -
    which is what keeps the result pending and the node unseen.  Leaving the
    sink out (what sinks_for() alone does for such a definition) would let the
    worker stamp "result posted to the callback" for a result that went nowhere
    and would mark the node seen.  No failure policy is decided here: 4xx and
    5xx/network verdicts are post_result's and raise out of this unchanged.

    *definition* is the job definition when the caller still has it (the run
    that just finished).  A result re-posted from the state file has none, and
    none is fetched for it - a re-post is not a re-run - so the report's own URL
    is what the callback sink posts to: it is the value callback.callback_url()
    read from that definition when the run happened.

    The table line (scripts/local-jobs.py) is the other way round on purpose: a
    run there without --callback-url is a ledger-only run, so it calls
    sinks_for() and deliver() itself.

    Returns deliver()'s {sink name: delivery result}.
    """
    sinks = (sinks_for(definition) if definition is not None
             else (LedgerSink(),))
    if report is not None and not has_callback(sinks):
        sinks = (*sinks, CallbackSink())
    return deliver(sinks, definition, report=report)
