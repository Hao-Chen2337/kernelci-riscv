# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""来源:谁决定"这次要跑什么"。

整个仓库只有一种 job 定义(kcilib/table/jobspec.job_definition 造的,字段与上游
模板渲染结果同构),所以"跑一个 job"只有一条路。变的只是**谁决定跑哪些**:

    table   本地索引表 − 账本       同步,调用者驱动     ← ./run.sh run --source table
    newest  生产上最新的可用构建     同步,调用者驱动     ← ./run.sh run --source newest

**为什么 events(worker 接单)不在这里**:它不是"取一批 job"这么简单。它要轮询、
记游标、防重复、抢锁、把发失败的结果留着重发——那些是**常驻进程的状态机**,不是
一个 jobs() 迭代器能表达的。把它塞进这个接口,只会得到一个假的统一。

真正统一的地方是**边界**:两种来源最后都产出一份 job 定义,交给同一个 run_node。
所以解耦规则是——

    source 不知道 job 怎么跑(它不 import runner/judge/bake)
    runner 不知道 job 从哪来(它只收一份定义)
    sink   不知道谁发起的(账本无条件写;有 callback URL 才回传)
"""

from kcilib.api import PRODUCTION_API
from kcilib.table.buildindex import BuildIndex
from kcilib.table.buildref import BuildQuery, builds_from_production_api
from kcilib.table.jobspec import DEFAULT_TESTS, jobs_from_build


class JobSource:
    """A pull source: something that can say what to run right now.

    Subclasses implement jobs(); nothing else.  They must not run anything, and
    they must not import the execution layer - that is what keeps "where a job
    comes from" and "how a job is run" independently replaceable.
    """

    name = "?"

    def jobs(self, tests=None):
        raise NotImplementedError


class TableSource(JobSource):
    """The local index minus what the ledger already has."""

    name = "table"

    def __init__(self, db=None, tests=None):
        self.index = BuildIndex(db)
        self.tests = tuple(tests) if tests else DEFAULT_TESTS

    def jobs(self, tests=None):
        """(specs, skipped, builds_checked) - see kcilib.table.localrun.todo."""
        from kcilib.table.localrun import todo
        return todo(self.index, tests=tests or self.tests)


class NewestSource(JobSource):
    """The newest usable production build, and the tests it can support.

    This is what ./run.sh fetch does, expressed as a source instead of as a
    script: query the production API, take the newest passing build, and offer
    it as the three specs.  It reads only - no token, no local stack.
    """

    name = "newest"

    def __init__(self, job="kbuild-gcc-14-riscv", api=PRODUCTION_API,
                 days=3, tests=None, trees=()):
        self.job = job
        self.api = api
        self.days = days
        self.tests = tuple(tests) if tests else DEFAULT_TESTS
        self.trees = tuple(trees)

    def build(self):
        """The newest usable BuildRef, or None (and why, on stderr)."""
        query = BuildQuery(job=self.job, api=self.api, trees=self.trees,
                           result="pass")
        # Widen the window until something shows up: the API pages old-first and
        # a quiet tree can be days behind, which used to look like "no build".
        for days in (self.days, 7, 30, 180):
            query.since = _days_ago(days)
            refs, _dropped = builds_from_production_api(query)
            if refs:
                return refs[0]
        return None

    def jobs(self, tests=None):
        build = self.build()
        if build is None:
            return [], [(self.job, "no usable build",
                         f"no passing {self.job} in the last 180 days")], 0
        specs, skipped = jobs_from_build(build, tests=tests or self.tests)
        return specs, [(build.build_id, test, reason)
                       for test, reason in skipped], 1


def _days_ago(days):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.gmtime(time.time() - days * 86400))


SOURCES = {"table": TableSource, "newest": NewestSource}


def get_source(name, **kwargs):
    """Look up a pull source by name (the CLI's --source)."""
    try:
        return SOURCES[name](**kwargs)
    except KeyError:
        raise SystemExit(
            f"unknown source {name!r}; known: {', '.join(sorted(SOURCES))} "
            "(the events source is the worker: ./run.sh worker)") from None
