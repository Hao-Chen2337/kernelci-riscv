#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where a report goes when the operator says so: the override, and its boundaries.

    test_callback_override.py

A job node carries the callback URL the pipeline that dispatched it declared, and in
production that is the pipeline's own endpoint.  An operator running this deployment
against their own instance could see that URL on `/worker` and change nothing: it
arrives inside the definition, the worker's sinks are the definition's
(`poller.Poller.handle`), and `--callback-url` is deliberately not a worker flag
(`config.parse_poll`).  `sink.callback_override` is the answer - one URL under
`var/state/`, set from the panel that shows the return path - and this test pins down
what it may and may not do:

* **nothing set is the defined behaviour.**  No file means the definition's URL, which
  is what every deployment that has never touched this setting does;
* **the override wins, and it is read at delivery, not at startup.**  The worker is a
  long-lived process; a setting that needed a restart would be one the operator
  watches do nothing;
* **a URL it will not write is refused, and the old value stays in force.**  A refusal
  that half-applied would leave the page showing one thing and the worker doing another;
* **both delivery sites resolve through it.**  `handle` (a fresh run) and
  `_repost_pending` (a report that was refused) are the two places a report leaves this
  machine, and a re-post that ignored the override would be the case the operator most
  needs it in: a pending report is usually one that was going somewhere that refused it;
* **a one-shot run is not a delivery site.**  `table.py run` posts only when it is given
  `--callback-url`; a deployment-wide setting that silently turned callbacks *on* would
  have a command POST a token to a service it was never asked to talk to;
* **it can be turned off.**  `off` is the one accepted value that is not a URL, and it
  has to survive the whole way down: an empty override would fall through to the
  definition's URL inside `Callback.wants`, which is the opposite of what the operator
  asked for.  So the checks below are about the *value reaching the sink*, not about the
  file - and about a pending report being kept rather than thrown away, because a
  setting can be turned back on;
* **the page and the worker give the same answer.**  The panel draws **one** row for the
  destination - the merge the operator asked for (「callback.url 和这个部署改发到这两个
  不能合并一下吗」) - and that row is `sink.delivery_url`'s own answer, the same call the
  worker's delivery and its re-post make.  The definition's URL is still in the answer
  beside it, because the one sentence under the row has to be able to say which of the
  three states is in force.

No network: `sink.Callback` is replaced by a recorder, and `Job.run` by a stub that
records the sinks it was handed.  No disk outside a temporary `KCI_WORK_DIR`.

Exit status is the verdict, like `python3 lib/i18n.py --check lib/gui.py`.
"""

import os
import shutil
import sys
import tempfile
from typing import ClassVar

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from lib import config as config_mod
from lib import job as job_mod
from lib import layout
from lib import poller as poller_mod
from lib import sink as sink_mod
from lib.errors import CallbackMissingURLError, ConfigError
from lib.gui.design import data as data_mod

BUILD = "6aade015d96a8203de6dff37"
NODE_ID = "6ab4b5c6d96a8203de8de3ac"
DEFINITION_URL = "https://pipeline.example.invalid/node/abc"
OURS = "http://172.17.0.1:8003/node/abc"

# A definition shaped like the ones the pipeline dispatches: a build id that is only
# reachable through an artifact URL (`kbuild.build_id_of`), and a callback block.  The
# build id matters here for the same reason it matters in the local stack: a
# definition without one is refused by the ledger, and a refused ledger aborts the
# whole sink chain before the callback is reached.
DEFINITION = {
    "artifacts": {"modules": f"https://files.example.invalid/kbuild-riscv-{BUILD}/modules.tar.xz"},
    "tests": [{"type": "boot", "timeout_s": 60}],
    "callback": {"url": DEFINITION_URL, "token_name": "kernelci-pipeline-callback"},
}


class Recorder:
    """`sink.Callback` with the POST taken out: records every URL one was built with."""

    seen: ClassVar[list[str]] = []

    def __init__(self, url: str = "", session=None) -> None:
        self.url = url
        Recorder.seen.append(url)

    def name(self) -> str:
        return "callback"

    def wants(self, job, outcome) -> bool:
        return bool(self.url)

    def deliver(self, job, outcome) -> str:
        return f"posted to {self.url}"


class Ran:
    """`Job.run` with tuxrun taken out: records the sinks it was handed."""

    sinks: tuple = ()


def fake_run(job, config, sinks=None, source="local"):
    """The stub itself, a function so it binds like the method it replaces."""
    Ran.sinks = tuple(sinks or ())


class Claimed:
    """What `_claim` returns: a node and its definition, and nothing else.

    `node_id` and `callback_url` are here because `handle` reads them off this object
    when a delivery fails (`_remember_pending`), not because this test walks that path:
    a stub that only works on the happy path would test a worker this tree does not have.
    """

    node_id = NODE_ID
    callback_url = ""
    created = "2026-09-24T10:00:00"

    def definition(self, api):
        return DEFINITION


class Node:
    """What `handle` reads off the node it was given."""

    node_id = NODE_ID
    created = "2026-09-24T10:00:00"
    callback_url = ""


class Gui:
    """The two readers `data._return_path` asks its gui for."""

    def job_definition(self, url):
        return DEFINITION

    def worker_state(self):
        return {}


def main() -> int:
    home = tempfile.mkdtemp(prefix="kci-callback-")
    os.environ["KCI_WORK_DIR"] = home
    failed, checks = 0, 0

    def check(name, ok, evidence=""):
        nonlocal failed, checks
        checks += 1
        if not ok:
            failed += 1
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({evidence})" if evidence else ""))

    real_callback, real_run = sink_mod.Callback, job_mod.Job.run
    sink_mod.Callback, job_mod.Job.run = Recorder, fake_run
    try:
        path = layout.state(sink_mod.OVERRIDE_NAME)

        # 1. nothing set: the ordinary deployment, and the override is not a default.
        check("with no file there is no override",
              sink_mod.callback_override() == "", repr(sink_mod.callback_override()))
        check("and the definition's URL is what a delivery would use",
              sink_mod.delivery_url(DEFINITION_URL) == DEFINITION_URL)
        check("and an empty definition URL stays empty rather than inventing one",
              sink_mod.delivery_url("") == "")

        # 2. set it: the value is read back **stripped**, because it is typed into a box
        #    by hand and a pasted newline is not part of a URL.
        check("setting one writes it",
              sink_mod.set_callback_override(f"  {OURS}\n") == OURS, path)
        check("and reads back trimmed, so a paste cannot break the POST",
              sink_mod.callback_override() == OURS, repr(sink_mod.callback_override()))
        check("and it wins over the definition's",
              sink_mod.delivery_url(DEFINITION_URL) == OURS)

        # 3. a URL it will not write is a refusal and leaves the old one in force: a
        #    half-applied refusal would have the page and the worker disagreeing.
        refusals = []
        for bad in ("notaurl", "file:///etc/passwd", "ftp://host/x", "https://"):
            try:
                sink_mod.set_callback_override(bad)
            except ConfigError:
                refusals.append(bad)
        check("four unusable URLs are refused", len(refusals) == 4, str(refusals))
        check("and a refusal does not change what is in force",
              sink_mod.callback_override() == OURS, sink_mod.callback_override())

        # 4. the two delivery sites.  `_repost_pending` first: a report that was refused
        #    is the case the override exists for, and it must not go back to the URL that
        #    refused it just because that is the one written in the state file.
        worker = poller_mod.Poller(None)
        worker.state["pending"] = {Node.node_id: {"callback": DEFINITION_URL,
                                                  "definition": DEFINITION,
                                                  "record": {"verdict": "pass"}}}
        Recorder.seen = []
        worker._repost_pending()
        check("a re-post goes to the override, not to the definition's URL",
              Recorder.seen == [OURS], str(Recorder.seen))
        check("and the report is no longer pending", worker.state["pending"] == {},
              str(worker.state["pending"]))

        # 5. `handle`, which is the other one: the sink it builds for a fresh run.
        worker = poller_mod.Poller(None)
        worker._claim = lambda node: Claimed()
        Recorder.seen = []
        worker.handle(Node())
        forwarded = getattr(Ran.sinks[0], "sinks", ())
        urls = [one.url for one in forwarded if isinstance(one, Recorder)]
        check("a fresh run delivers through the override too", urls == [OURS], str(urls))

        # 6. and with the override cleared, both sites go back to the definition's - which
        #    is the whole of what "cleared" has to mean, and the reason it is a file that
        #    is removed rather than a flag that is set to empty.
        check("clearing removes the file", sink_mod.set_callback_override("") == "")
        check("and clearing again is not an error", sink_mod.set_callback_override("") == "")
        check("and the file is really gone", not os.path.exists(path), path)
        Recorder.seen = []
        worker = poller_mod.Poller(None)
        worker._claim = lambda node: Claimed()
        worker.handle(Node())
        forwarded = getattr(Ran.sinks[0], "sinks", ())
        urls = [one.url for one in forwarded if isinstance(one, Recorder)]
        check("with nothing set a fresh run uses the definition's URL",
              urls == [DEFINITION_URL], str(urls))

        # 7. **the boundary**: a one-shot run is not a delivery site.  `RunConfig.sinks`
        #    with no URL is the ledger alone, and it stays that way with an override set -
        #    otherwise `table.py run` would POST a token to a remote service nobody asked
        #    it to talk to.
        sink_mod.set_callback_override(OURS)
        names = [one.name() for one in config_mod.RunConfig().sinks()]
        check("a one-shot run with no --callback-url still posts nothing",
              names == ["ledger"], str(names))

        # 8. the panel's one row for the destination is the same resolution the worker
        #    makes, and the definition's URL rides beside it so the sentence under the row
        #    can say which of the three states is in force.  `destination` is *not* a
        #    second owner: it is `sink.delivery_url`'s answer, reached through this reader.
        rows = data_mod._return_path(Gui(), [{"definition_url": "https://x.invalid/d.json"}])
        check("with an override set the panel's destination is the override",
              rows["destination"] == OURS and rows["callback"] == DEFINITION_URL,
              f'destination={rows["destination"]!r} callback={rows["callback"]!r}')
        check("and it is exactly what a delivery would resolve, not a second guess",
              rows["destination"] == sink_mod.delivery_url(rows["callback"]))
        # The row that used to print this is gone: nothing in this tree has ever read the
        # field, and the reader who went looking for a token by that name was chasing a
        # name no `Authorization` header carries.
        check("and the definition's token_name is not read at all", "token_name" not in rows)

        # 9. where the resolved value *is* the fact a row reports - a pending report's
        #    destination - the page resolves it the way the worker does, not the way the
        #    state file spells it: a re-post that went back to the URL that refused it is
        #    the exact case this setting exists for.
        pending = data_mod._pending({"pending": {Node.node_id: {"callback": DEFINITION_URL}}})
        check("the pending table shows where the re-post will really go",
              pending[0]["callback"] == OURS, pending[0]["callback"])
        sink_mod.set_callback_override("")
        rows = data_mod._return_path(Gui(), [{"definition_url": "https://x.invalid/d.json"}])
        check("with nothing set the destination is the definition's own callback.url",
              rows["override"] == "" and rows["destination"] == DEFINITION_URL,
              f'override={rows["override"]!r} destination={rows["destination"]!r}')

        # 10. **off.**  The value that is not a URL, and the one place it could go wrong:
        #     an empty override falls through to the definition's URL inside
        #     `Callback.wants`, so "off" has to arrive at the sink as itself or the worker
        #     posts to the very endpoint the operator turned off.
        check("off is accepted where a URL is expected",
              sink_mod.set_callback_override("off") == sink_mod.OFF, sink_mod.OFF)
        check("and is read back as itself, not folded into the empty answer",
              sink_mod.callback_override() == sink_mod.OFF)
        check("so delivery resolves to off and not to the definition's URL",
              sink_mod.delivery_url(DEFINITION_URL) == sink_mod.OFF)
        # The real sink, not the recorder: this is a claim about `sink.Callback`'s own
        # reading of the value, and `Recorder.wants` is `bool(self.url)` by construction.
        check("and the real sink wants nothing at all",
              real_callback(sink_mod.OFF).wants(None, None) is False)
        refused = False
        try:
            real_callback(sink_mod.OFF).deliver(None, None)
        except CallbackMissingURLError:
            refused = True
        check("and a report handed to it anyway is not posted", refused)
        # Both delivery sites again, with off in force: the value that reaches them is the
        # one that must not fall through, so this is the check that would have caught an
        # `off` implemented as "write an empty override".
        Recorder.seen = []
        worker = poller_mod.Poller(None)
        worker._claim = lambda node: Claimed()
        worker.handle(Node())
        urls = [one.url for one in getattr(Ran.sinks[0], "sinks", ()) if isinstance(one, Recorder)]
        check("a fresh run is handed off, not the definition's URL",
              urls == [sink_mod.OFF], str(urls))
        # …and the re-post, driven with the **real** sink so the claim is about what really
        # happens to a report the operator's setting has nowhere to send: it stays pending
        # and is delivered if the callback is turned back on.  Dropping it would be the
        # page taking a decision the operator did not make.
        worker = poller_mod.Poller(None)
        worker.state["pending"] = {Node.node_id: {"callback": DEFINITION_URL,
                                                  "definition": DEFINITION,
                                                  "record": {"verdict": "pass"}}}
        sink_mod.Callback = real_callback
        try:
            worker._repost_pending()
        finally:
            sink_mod.Callback = Recorder
        check("and a re-post with callbacks off is kept, not posted and not dropped",
              Node.node_id in worker.state["pending"], str(worker.state["pending"]))
        # …after which the page has to say so rather than showing a destination the worker
        # is not using, which is the same rule the override itself follows.
        rows = data_mod._return_path(Gui(), [{"definition_url": "https://x.invalid/d.json"}])
        check("and the panel's destination is off rather than the definition's URL",
              rows["destination"] == sink_mod.OFF and rows["override"] == sink_mod.OFF,
              f'destination={rows["destination"]!r}')

        # 11. and clearing still wins over everything: the file is removed, not written as
        #     a third value, so a deployment that never touched this setting and one that
        #     went back to it are the same deployment.
        check("clearing an off override removes the file",
              sink_mod.set_callback_override("") == "" and not os.path.exists(path), path)
        check("and the definition's URL is in force again",
              sink_mod.delivery_url(DEFINITION_URL) == DEFINITION_URL)
    finally:
        sink_mod.Callback, job_mod.Job.run = real_callback, real_run
        shutil.rmtree(home, ignore_errors=True)
        os.environ.pop("KCI_WORK_DIR", None)

    print(f"\n{checks - failed}/{checks} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
