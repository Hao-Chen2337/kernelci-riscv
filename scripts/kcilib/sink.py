# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""Sinks: where a run's result goes.

A sink is a name + a switch (wants) + one delivery (deliver); sinks_for() is the
only place that decides, and it decides from the job definition.  The ledger is
unconditional, the callback only when the definition carries callback.url.

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
