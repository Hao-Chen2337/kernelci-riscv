# SPDX-License-Identifier: LGPL-2.1-or-later
#
"""构建引用:把"一个 KernelCI 节点"变成一张表能存的一行。

为什么要这一层:后面所有东西(生成 job、跑测试、算配置偏移)都需要一个
**稳定的构建身份**,而 KernelCI 的节点 id 不是它 —— 节点 id 是"哪个数据库
分配的",本地库和生产库各发各的,同一个构建在两边的 id 毫无关系(实测:
本地 job 节点 6aa822fcf84821b97339d2f9 挂着生产构建 6aa3689720239ade90209d50)。

稳定的东西是构件 URL 里的那个 id,以及 tree/commit。所以:

    node(任何来源的完整节点)  ──build_ref_from_node()──►  BuildRef(一行)
    生产 API 的一批节点        ──builds_from_production_api()──►  [BuildRef]

BuildRef 只带执行层真正要用的字段(kernel / kselftest / modules / _config),
多一个都不带:它会被存进本地索引表,存的是"够不够跑",不是"节点快照"。
"""

import json
from dataclasses import dataclass, field

from kcilib.api import KernelCI
from kcilib.run.artifacts import build_id_from_artifacts

# 执行层认得的构件键(与上游模板渲染出来的 artifacts 同名)。_config 只有
# 配置偏移(drift)用得上,但仍然抄下来:它是"这个构建的编译配置"的唯一出处。
ARTIFACT_KEYS = ("kernel", "kselftest_tar_xz", "kselftest", "modules", "_config")

# 一个构建要能被跑,至少得有内核;kselftest 类测试还需要集合 tarball。
REQUIRED_FOR = {
    "boot": ("kernel",),
    "kselftest-riscv": ("kernel", "kselftest_tar_xz"),
    "kselftest-kvm": ("kernel", "kselftest_tar_xz", "modules"),
}

PRODUCTION_API = "https://api.kernelci.org"
REQUEST_TIMEOUT = 60


@dataclass
class BuildRef:
    """一个构建的一行:身份 + 构件地址 + 来源。

    *build_id* 是主键的一半(另一半是测试名);*source* 是这一层唯一"自有"的
    字段 —— 其余全部从节点抄来,这样本地索引不是第二份真相,只是索引。
    """

    build_id: str
    artifacts: dict = field(default_factory=dict)
    tree: str | None = None
    branch: str | None = None
    commit: str | None = None
    describe: str | None = None
    created: str | None = None
    node_id: str | None = None          # 来源库的节点 id(引用列,不是键)
    source: str = "official"            # official | local

    def missing_for(self, test):
        """*test* 跑起来缺哪些构件(空元组 = 齐了)。

        缺构件不是错误而是常态:构建失败就没有产物。实测本地库 58 个
        kbuild-gcc-14-riscv 节点里,15 个 result=incomplete 且 artifacts 为空 ——
        这些构建下的 job 一个都跑不了,提前发现比跑到一半才发现好。
        """
        needed = REQUIRED_FOR.get(test, ("kernel",))
        return tuple(key for key in needed if not self.artifacts.get(key))

    def as_row(self):
        """SQLite 行(dict):索引表只存这些列。"""
        return {
            "build_id": self.build_id,
            "tree": self.tree,
            "branch": self.branch,
            "commit": self.commit,
            "describe": self.describe,
            "created": self.created,
            "node_id": self.node_id,
            "source": self.source,
            "artifacts": json.dumps(self.artifacts, sort_keys=True),
        }


def build_ref_from_node(node, source="official"):
    """一个完整节点 -> BuildRef。纯函数:不联网、不落盘。

    *node* 是任何 KernelCI 形状的 dict —— 官方 API 拿的、搬来的、自己造的,
    一视同仁(这就是为什么这一层收节点而不是收 id:自己造的节点没有 id 可查)。

    build_id 从构件 URL 解析(artifacts.build_id_from_artifacts);解析不出时
    退回节点自己的 id 并保持 source 不变 —— 调用方由此知道这一行的身份有多硬。

    节点没有 kernel 构件 -> 抛 ValueError:一个跑不了的构建不该进表。
    """
    if not isinstance(node, dict):
        raise TypeError(f"a node must be a dict, got {type(node).__name__}")
    artifacts = node.get("artifacts") or {}
    if not artifacts.get("kernel"):
        raise ValueError(
            f"node {node.get('id') or '?'} has no kernel artifact; it cannot "
            "be run, so it does not belong in the build index")
    revision = (node.get("data") or {}).get("kernel_revision") or {}
    build_id = build_id_from_artifacts(artifacts) or str(node.get("id") or "")
    if not build_id:
        raise ValueError("node has neither a build id in its artifact URLs nor "
                         "a node id; nothing stable to file it under")
    return BuildRef(
        build_id=build_id,
        artifacts={key: artifacts[key] for key in ARTIFACT_KEYS
                   if artifacts.get(key)},
        tree=revision.get("tree"),
        branch=revision.get("branch"),
        commit=revision.get("commit"),
        describe=revision.get("describe"),
        created=node.get("created"),
        node_id=str(node.get("id") or "") or None,
        source=source,
    )


@dataclass
class BuildQuery:
    """要在生产上找哪些构建 —— 显式字段,不用"最近 N 天"猜。

    每一项都对应 API 的一个过滤参数(或本地的一次筛选),所以"找到的正是想
    要的"这件事在调用点就能读懂,而不是靠一个天数魔数。
    """

    job: str = "kbuild-gcc-14-riscv"
    trees: tuple = ()               # 空 = 不限;例:("mainline", "next", "riscv")
    result: str | None = "pass"     # "pass" / None(全部);API 不支持,本地筛
    since: str | None = None        # ISO8601,含
    until: str | None = None        # ISO8601,不含(本地筛)
    require: tuple = ("kernel",)    # 必需存在的构件键
    limit: int = 200
    order: str = "newest"           # newest | oldest
    api: str = PRODUCTION_API

    def as_params(self):
        """API 真正支持的过滤参数(其余在本地筛)。"""
        params = {"kind": "kbuild", "name": self.job, "limit": str(self.limit)}
        if self.since:
            params["created__gte"] = self.since
        if len(self.trees) == 1:
            params["data.kernel_revision.tree"] = self.trees[0]
        return params

    def accepts(self, ref):
        """本地筛选:API 不支持的那些条件在这里落地。

        返回 (ok, reason);reason 只在 ok=False 时非空,便于调用方统计
        "拉回来 200 个,因为什么被丢掉" —— 静默筛选是"为什么没有构建"这类
        问题的常见来源。
        """
        if self.trees and ref.tree not in self.trees:
            return False, f"tree {ref.tree!r} not in {list(self.trees)}"
        if self.until and (ref.created or "") >= self.until:
            return False, f"created {ref.created} >= until {self.until}"
        for key in self.require:
            if not ref.artifacts.get(key):
                return False, f"missing artifact {key!r}"
        return True, ""


def build_refs_from_nodes(nodes, query=None, source="official"):
    """节点列表 -> (refs, dropped)。*dropped* 是 (节点id, 原因) 列表。"""
    query = query or BuildQuery()
    refs, dropped = [], []
    for node in nodes:
        try:
            ref = build_ref_from_node(node, source=source)
        except ValueError as error:
            dropped.append((str(node.get("id") or "?"), str(error)))
            continue
        ok, reason = query.accepts(ref)
        if ok:
            refs.append(ref)
        else:
            dropped.append((ref.build_id, reason))
    return refs, dropped


def fetch_nodes(query):
    """问 API 要一批节点。走 kcilib.api —— 全仓库唯一的 API 客户端。

    这里曾经自己拼 URL、自己开 urllib;现在只有"构造过滤参数"是本地知识,
    取数、错误分类都在 kcilib/api.py 一处(以前有五个地方各写一份)。
    """
    return KernelCI(query.api).nodes(**query.as_params())


def builds_from_production_api(query=None):
    """生产 API -> (refs, dropped)。只读,不需要任何 token。

    返回 BuildRef 列表(按 query.order 排序),外加被丢掉的 (id, 原因) ——
    调用方想打印"为什么没找到构建"时不用重新查一遍。
    """
    query = query or BuildQuery()
    nodes = fetch_nodes(query)
    if query.result:
        # result 不是 API 的过滤参数,在本地筛:构建失败(incomplete)的节点
        # 也会被 API 返回,它们的产物要么没有、要么不完整。
        nodes = [n for n in nodes if n.get("result") == query.result]
    refs, dropped = build_refs_from_nodes(nodes, query)
    refs.sort(key=lambda r: r.created or "", reverse=(query.order == "newest"))
    return refs, dropped
