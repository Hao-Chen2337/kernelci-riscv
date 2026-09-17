"""The two pull sources: the table (index minus ledger) and the newest build."""
import os
import tempfile
import time as _time
from contextlib import contextmanager

from kcilib.core import ledger

from .support import check


@contextmanager
def ledger_at(path):
    """Point the ledger's root at *path* for the duration.

    Same seam and reason as test_missing_callback_keeps_result_pending: a guard
    must not write into the repository's work/results/.
    """
    real = os.environ.get(ledger.RESULTS_DIR_ENV)
    os.environ[ledger.RESULTS_DIR_ENV] = path
    try:
        yield path
    finally:
        if real is None:
            os.environ.pop(ledger.RESULTS_DIR_ENV, None)
        else:
            os.environ[ledger.RESULTS_DIR_ENV] = real


@contextmanager
def no_api_calls():
    """Any use of the one API client fails for the duration.

    kcilib/source.py documents the table source as local-only (index minus
    ledger), so a request here means it grew a network dependency silently.
    """
    from kcilib.api import KernelCI

    def refuse(_self, *_args, **_kwargs):
        raise AssertionError("the table source must not talk to the API")

    real = KernelCI.get
    KernelCI.get = refuse
    try:
        yield
    finally:
        KernelCI.get = real


@contextmanager
def stub_newest_api(builds, windows, queries):
    """kcilib.source's two production-API seams, patched ON that module.

    NewestSource.build() resolves builds_from_production_api and _days_ago as
    globals of kcilib.source, so patching them there is what the code reads, and
    the window asked for becomes observable.  *builds* takes the attempt number;
    *windows* and *queries* collect what was asked for.
    """
    from kcilib import source as kcsource

    real_builds = kcsource.builds_from_production_api
    real_days_ago = kcsource._days_ago

    def fake_builds(query):
        queries.append(query)
        windows.append(query.since)
        return builds(len(windows)), []

    kcsource.builds_from_production_api = fake_builds
    kcsource._days_ago = lambda days: f"T-{days}d"
    try:
        yield kcsource
    finally:
        kcsource.builds_from_production_api = real_builds
        kcsource._days_ago = real_days_ago


def test_table_source_subtracts_the_ledger():
    """kcilib/source.py: TableSource is the index MINUS the ledger.

    A (build, test) the ledger already holds is not offered again, and a test
    the build cannot support is skipped WITH the artifact it is missing - never
    silently dropped.
    """
    from kcilib import source as kcsource
    from kcilib.table.buildindex import BuildIndex
    from kcilib.table.buildref import BuildRef

    build_id = "6aa3689720239ade90209d50"
    ref = BuildRef(
        build_id=build_id,
        # kernel + kselftest tarball, no modules: kselftest-kvm cannot run.
        artifacts={"kernel": f"http://x/{build_id}/Image",
                   "kselftest_tar_xz": f"http://x/{build_id}/ks.txz"},
        tree="riscv", commit="deadbeef", created="2026-09-16T00:00:00Z")

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "builds.db")
        index = BuildIndex(db)
        check(index.add(ref) is True, "the build must enter the index")
        with ledger_at(os.path.join(tmp, "results")), no_api_calls():
            specs, skipped, checked = kcsource.TableSource(db=db).jobs()
            check([(spec.build_id, spec.test) for spec in specs]
                  == [(build_id, "boot"), (build_id, "kselftest-riscv")],
                  f"the runnable tests must be offered: {specs}")
            check(checked == 1, f"one build was checked: {checked}")
            check(len(skipped) == 1, f"exactly one skip expected: {skipped}")
            skipped_build, skipped_test, reason = skipped[0]
            check((skipped_build, skipped_test) == (build_id, "kselftest-kvm"),
                  f"the unrunnable test must be reported: {skipped}")
            check("modules" in reason,
                  f"the skip must name the missing artifact: {reason!r}")

            # The ledger now holds a record for boot: it must be subtracted.
            ledger.write_result(build_id, "boot",
                                {"verdict": "pass", "source": "fetch"})
            specs2, _skipped2, checked2 = kcsource.TableSource(db=db).jobs()
            check([spec.test for spec in specs2] == ["kselftest-riscv"],
                  f"the ledger's boot row must be subtracted: {specs2}")
            check(checked2 == 1, checked2)

            # ... and with both recorded the list is empty while the skip is
            # still reported: "0 to do" and "2 tests were skipped" differ.
            ledger.write_result(build_id, "kselftest-riscv",
                                {"verdict": "pass", "source": "fetch"})
            specs3, skipped3, checked3 = kcsource.TableSource(db=db).jobs()
            check(specs3 == [], f"nothing is left to run: {specs3}")
            check(len(skipped3) == 1 and checked3 == 1,
                  f"an empty todo still says what it looked at: {skipped3}")

            # A narrowed test list still reports the skip it asked about.
            specs4, skipped4, _c = kcsource.TableSource(db=db).jobs(
                tests=["kselftest-kvm"])
            check(specs4 == [] and [test for _b, test, _r in skipped4]
                  == ["kselftest-kvm"], (specs4, skipped4))
    print("test_table_source_subtracts_the_ledger OK")


def test_newest_source_widens_the_window():
    """kcilib/source.py: NewestSource widens 3 -> 7 -> 30 -> 180 days.

    The production API pages old-first and a quiet tree can be days behind, so
    a hit on the first window stops the walk, a hit on a later one is still
    used, and the query asked is the one the caller described.
    """
    import calendar

    from kcilib.table.buildref import BuildRef

    ref = BuildRef(build_id="6aa3689720239ade90209d50",
                   artifacts={"kernel": "http://x/Image"},
                   tree="riscv", commit="deadbeef")

    # The real widening clock, before it is patched: an ISO8601 stamp that
    # really is N days back (the module builds it with time.gmtime).
    from kcilib import source as kcsource

    stamp = kcsource._days_ago(180)
    check(len(stamp) == 19 and "T" in stamp,
          f"_days_ago must produce ISO8601 seconds: {stamp!r}")
    gap = _time.time() - calendar.timegm(
        _time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
    check(abs(gap - 180 * 86400) < 300,
          f"_days_ago(180) is {gap / 86400:.2f} days back, not 180")

    windows, queries = [], []
    with stub_newest_api(lambda attempt: [ref] if attempt >= 3 else [],
                         windows, queries) as kcsource:
        specs, skipped, checked = kcsource.NewestSource(
            job="kbuild-gcc-14-riscv", days=3).jobs()
    check(windows == ["T-3d", "T-7d", "T-30d"],
          "the window must widen one step at a time and stop at the first "
          f"hit: {windows}")
    check(queries and queries[0].job == "kbuild-gcc-14-riscv"
          and queries[0].result == "pass" and queries[0].trees == ()
          and queries[0].api == kcsource.PRODUCTION_API,
          f"the query must ask for passing builds of that job: {queries[0]}")
    check([spec.test for spec in specs] == ["boot"],
          f"only boot is runnable without the kselftest tarballs: {specs}")
    check([(build, test) for build, test, _reason in skipped]
          == [(ref.build_id, "kselftest-riscv"),
              (ref.build_id, "kselftest-kvm")],
          f"the skips must name the build they came from: {skipped}")
    check(all(reason for _b, _t, reason in skipped),
          f"a skip without a reason is the silent skip this is not: {skipped}")
    check(checked == 1, f"one build was offered: {checked}")

    # A custom first window leads the widening, and the walk still ends at the
    # last one when nothing is found.
    windows, queries = [], []
    with stub_newest_api(lambda _attempt: [], windows, queries) as kcsource:
        found = kcsource.NewestSource(days=1).build()
    check(windows == ["T-1d", "T-7d", "T-30d", "T-180d"],
          f"a custom window must lead the widening: {windows}")
    check(found is None,
          f"nothing found means None, not a made-up build: {found}")
    print("test_newest_source_widens_the_window OK")


def test_newest_source_reports_no_build():
    """kcilib/source.py: nothing in 180 days is an empty list AND a reason.

    "0 to do" is an answer an operator cannot act on, so the source names the
    job and the window - after really looking that far back.
    """
    windows, queries = [], []
    with stub_newest_api(lambda _attempt: [], windows,
                         queries) as kcsource:
        specs, skipped, checked = kcsource.NewestSource(
            job="kbuild-gcc-14-riscv").jobs()
    check(specs == [] and checked == 0, (specs, checked))
    check(windows == ["T-3d", "T-7d", "T-30d", "T-180d"],
          f"every window must be tried before giving up: {windows}")
    check(len(skipped) == 1, f"one reason expected: {skipped}")
    subject, test, reason = skipped[0]
    check(subject == "kbuild-gcc-14-riscv" and test == "no usable build",
          f"the reason must say which job found nothing: {skipped}")
    check("kbuild-gcc-14-riscv" in reason and "180" in reason,
          f"the reason must name the job and the window: {reason!r}")
    print("test_newest_source_reports_no_build OK")


def test_get_source_unknown_name():
    """kcilib/source.py: an unknown --source exits with the real names in it.

    --source events is the trap: ./run.sh worker is the way to it, and the user
    must be told that rather than get a KeyError traceback.
    """
    from kcilib import source as kcsource

    try:
        kcsource.get_source("events")
    except SystemExit as refusal:
        message = str(refusal)
        check(isinstance(refusal.code, str),
              f"the refusal is a message SystemExit: {refusal.code!r}")
        for needle in ("events", "table", "newest", "run.sh worker"):
            check(needle in message,
                  f"the refusal must mention {needle!r}: {message}")
    else:
        check(False, "'events' is not a pull source and must be refused")

    check(sorted(kcsource.SOURCES) == ["newest", "table"],
          "the source table is the contract run.sh's --source reads: "
          f"{sorted(kcsource.SOURCES)}")

    with tempfile.TemporaryDirectory() as tmp:
        table = kcsource.get_source("table", db=os.path.join(tmp, "b.db"),
                                    tests=["boot"])
        check(isinstance(table, kcsource.JobSource) and table.name == "table",
              f"get_source('table') must build a pull source: {table!r}")
        check(table.tests == ("boot",), table.tests)
        newest = kcsource.get_source("newest", job="kbuild-gcc-14-riscv",
                                     days=7)
        check(newest.name == "newest" and newest.days == 7,
              f"get_source must forward the keyword arguments: {newest!r}")

    # The base class refuses to be a source: a subclass that forgets jobs()
    # fails loudly rather than answering "nothing to do".
    try:
        kcsource.JobSource().jobs()
    except NotImplementedError:
        pass
    else:
        check(False, "JobSource.jobs() must not return anything")
    print("test_get_source_unknown_name OK")
