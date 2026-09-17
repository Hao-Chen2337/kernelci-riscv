# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""从"一个构建"得到"要跑的测试":表里的一行,和交给执行层的定义。

两个东西,别混:

* **JobSpec** 是**表里的一行** —— (build_id, test, timeout_s)。它能存、能打印、
  能拿来比"跑没跑";它**不**含 callback URL,因为那是"跑的时候"才知道的。
* **JobDefinition** 是**交给执行层的完整定义** —— artifacts / tests /
  environment / callback。它的字段名和上游 pull_labs.jinja2 渲染出来的**完全
  一样**,所以 kcilib.run.jobrun.run_node 分不清也不用分清这一份是官方 API 给的、
  还是我们自己拼的:同一个函数吃两种来源。

于是"我本地造一个 job 跑掉"和"我领一个上游 job 跑掉"在**执行层是同一件事**,
差别只有 job_definition() 的 callback_url 给不给:

    给了 callback_url -> 跑完还会回传(callback 段写进定义)
    没给             -> 只写账本(定义里没有 callback 段)
"""

from dataclasses import dataclass

from kcilib.table.buildref import build_ref_from_node

# 我们这套配置认领的三个测试,与 config/scheduler-pull-labs.yaml 里那三条
# runtime=pull-labs-riscv 的条目一一对应(整个文件 44 条,命中的只有 3 条)。
DEFAULT_TESTS = ("boot", "kselftest-riscv", "kselftest-kvm")

# 每个测试的默认超时。boot 只要启动内核;两个 kselftest 集合是长跑。
TEST_TIMEOUTS = {
    "boot": 600,
    "kselftest-riscv": 1800,
    "kselftest-kvm": 1800,
}

PLATFORM = "qemu-riscv64"
ARCH = "riscv"


@dataclass
class JobSpec:
    """表里的一行:一个构建 × 一个测试。

    故意只有三个字段 —— 它是"意图",不是"怎么跑"。多一个字段都会让它不再是
    一张能拿在手里的清单。
    """

    build_id: str
    test: str
    timeout_s: int = 0
    build: object = None                # BuildRef;单独放,便于只打印 build_id

    def __post_init__(self):
        if not self.timeout_s:
            self.timeout_s = TEST_TIMEOUTS.get(self.test, 1800)

    def as_row(self):
        return {"build_id": self.build_id, "test": self.test,
                "timeout_s": self.timeout_s}


def jobs_from_build(build, tests=None, timeout_s=None):
    """★ 一个构建 -> N 个 JobSpec。纯函数:不联网、不落盘、不跑测试。

    *build* 可以是 BuildRef,也可以是**完整的节点 dict** —— 后者是刻意的:
    自己造的节点没有 id 可查,而"输入一个节点"让官方和自己造的一视同仁。

    返回 (specs, skipped):
      specs   —— 长度可能小于 len(tests):缺构件的测试会被跳过
      skipped —— [(test, 原因)];静默跳过是"为什么没跑"这类问题的常见来源

    构建整个不可用(连 kernel 都没有)时 specs 为空,skipped 里说明原因。
    """
    tests = tuple(tests) if tests else DEFAULT_TESTS
    if not hasattr(build, "missing_for"):
        build = build_ref_from_node(build)
    specs, skipped = [], []
    for test in tests:
        missing = build.missing_for(test)
        if missing:
            skipped.append((test, f"missing artifact(s): {', '.join(missing)}"))
            continue
        specs.append(JobSpec(
            build_id=build.build_id,
            test=test,
            timeout_s=timeout_s or 0,
            build=build,
        ))
    return specs, skipped


def test_of(definition):
    """A definition -> the test it asks for (tests[0].type, then id, then boot).

    One place owns "what is this job called": the ledger files rows under it, and
    the run's own naming must agree with the callback it produces.
    """
    tests = definition.get("tests") or [{}]
    first = tests[0] if isinstance(tests[0], dict) else {}
    return first.get("type") or first.get("id") or "boot"


def job_definition(spec, callback_url=None, token_name=None):
    """★ JobSpec -> 交给 run_node 的定义。纯函数。

    *callback_url* 是**出口开关**:给了就回传,不给就只写账本。它在这里而不是
    在 JobSpec 里,是因为列表阶段还不知道要回传给谁(本地栈?生产?).

    产出的形状与上游模板渲染结果同构 —— 见模块开头的说明。
    """
    build = getattr(spec, "build", None)
    if build is None:
        raise ValueError(
            f"JobSpec {spec.build_id}/{spec.test} carries no build; specs come "
            "from jobs_from_build(), which keeps a reference to it")
    test = spec.test
    definition = {
        "artifacts": dict(build.artifacts),
        "tests": [{
            "id": test,
            "type": test,
            "depends": [],
            "timeout_s": spec.timeout_s,
            "pre-commands": [],
            "post-commands": [],
        }],
        "environment": {
            "platform": PLATFORM,
            "arch": ARCH,
            "console": {"method": "serial", "baud": 115200},
        },
    }
    if callback_url:
        definition["callback"] = {
            "url": callback_url,
            "token_name": token_name or "kernelci-pipeline-callback",
        }
    return definition
