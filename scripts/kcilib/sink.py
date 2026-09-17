# SPDX-License-Identifier: LGPL-2.1-or-later
#
r"""出口(sink):一次运行的结果"去哪"。

**为什么存在。** "结果去哪"以前散在两个地方:账本由执行层无条件写
(kcilib/run/jobrun.py:491 的 record_result -> ledger.write_result),回传由调用方
自己发(kcilib/run/poll.py:238 的 post_result),而 scripts/local-jobs.py 判断的
是 --callback-url 这个 argparse 值(scripts/local-jobs.py:264)。于是"这次运行会
往哪送"没有一个地方能回答,调用方各写各的判断,多一个出口(webhook、看板、另一个
pipeline)就要再改一遍每个调用方。这里把它收成显式的、可插拔的概念:

    一个出口 = 一个名字 + 一个开关(wants)+ 一次送达(deliver)

`sinks_for(definition)` 是唯一的判断处,依据是 **job 定义** —— 定义是运行层
真正看到的东西(scripts/kcilib/table/jobspec.py:103),不是 argparse 的值,也不是
调用方的意愿。

**为什么账本无条件。** 账本是唯一不依赖外部服务的落点:离线、无 token、无 URL
也要有 —— 一次失败或中断的运行恰恰是最需要留下记录的那一种(kcilib/core/
ledger.py 开头写的就是这个理由)。所以 `LedgerSink.wants()` 永远为真:没有任何
输入能让账本缺席,`sinks_for()` 也永远把它排在第一个。

**为什么 callback 有条件。** 回传是**上游的事**:只有定义里带了 callback.url
(这张本地表对接了某个 pipeline)才有地方可送。而且"没有 URL 也送一次"不是"少送
一次":post_result 此时抛 CallbackMissingURLError,它是 transient 的
(kcilib/run/callback.py:332),会把一次已经跑完的运行重新变成 pending。所以这个
开关只能由"定义里有没有 url"决定(callback.callback_url,
kcilib/run/callback.py:292),不能由调用方决定。

**这一层不做什么。**

* 不重写回传的失败语义:4xx 永久失败、5xx 与网络错误重试 3 次后 transient 都在
  kcilib.run.callback.post_result 里(kcilib/run/callback.py:345),这里只调用它,
  也不吞它的异常 —— "没送出去"绝不能看起来像"送出去了"。
* 不重写账本:写入点是执行层。这里再调一次 ledger.write_result 只会让记录**变少**
  (执行层写的是带 log/results 的完整记录,调用方手里只有 RunOutcome),而且
  RunOutcome 里的 record/callback_url/status 不是账本字段,会被
  ledger.write_result 直接拒绝(kcilib/core/ledger.py:108)。所以账本出口的"送达"
  是**取回**那条记录,不是再写一遍。
* 不造 body:回传要的是 run_node 返回的 (callback_url, token, body),body 是
  lava_body 的产物(kcilib/run/callback.py:82);这里不自己拼一个"差不多的",否则
  送到上游的就是一个没人认识的格式。
"""

from kcilib.run import callback

# 出口名:调用方按名字找出口、按名字报告,不要 isinstance。
LEDGER = "ledger"
CALLBACK = "callback"


class Sink:
    """一个出口。子类只回答三件事:叫什么、这次要不要用、怎么送。"""

    name = ""

    def wants(self, definition):
        """这次运行要不要用它 —— 开关判断的唯一位置。"""
        raise NotImplementedError

    def deliver(self, definition, outcome=None, report=None):
        """送达,返回"送到了哪"(没有就说 None)。

        *outcome* 是执行层整理过的 RunOutcome,*report* 是 run_node 返回的
        (callback_url, token, body) 三元组(scripts/kcilib/run/jobrun.py:494)。
        两个都收下:不同的出口要的东西不同,谁用不着谁不碰。
        """
        raise NotImplementedError


class LedgerSink(Sink):
    """账本出口:work/results/<build-id>/<test>.json。**永远执行**。"""

    name = LEDGER

    def wants(self, definition):
        # 没有输入能让账本缺席,理由见模块开头"为什么账本无条件"。
        return True

    def deliver(self, definition, outcome=None, report=None):
        """送达 = 报出执行层写好的那条记录。

        不在这里写账本:记录已经由 run_node 写过一遍(kcilib/run/jobrun.py:491),
        重写只会让 log/results 丢掉(理由见模块开头)。
        """
        return (outcome or {}).get("record")


class CallbackSink(Sink):
    """回传出口:把结果 POST 回定义里的 callback.url。**有条件执行**。"""

    name = CALLBACK

    def wants(self, definition):
        return bool(callback.callback_url(definition))

    def deliver(self, definition, outcome=None, report=None):
        """*report* 就是 post_result 的三个参数,原样交给它。

        token 既不在定义里也不在文件里:它是 run_node 跑完时从环境读的那一份
        (kcilib/run/jobrun.py:391),report 里带着的就是它。
        """
        if report is None:
            raise ValueError(
                "the callback sink needs the run's report tuple "
                "(callback_url, token, body): without the body lava_body() "
                "built there is nothing to post")
        callback.post_result(*report)


# 出厂出口,按送达顺序。加一个出口 = 在这里加一个 Sink 子类,调用方不用动
# (它们只问 sinks_for() 要一组出口);调用方也可以自己传一组给 deliver()。
SINKS = (LedgerSink, CallbackSink)


def sinks_for(definition):
    """定义 -> 这次运行要用的出口,按送达顺序。**唯一的判断处**。

    顺序是契约:账本永远排第一,所以一次失败的回传发生在记录已经落盘之后 ——
    它不会让记录消失。
    """
    chosen = []
    for cls in SINKS:
        candidate = cls()
        if candidate.wants(definition):
            chosen.append(candidate)
    return tuple(chosen)


def sink_names(sinks):
    """出口的名字,按送达顺序(打印与报告用)。"""
    return tuple(item.name for item in sinks)


def has_callback(sinks):
    """这组出口里有没有回传 —— 没有就是"只写账本"。"""
    return any(item.name == CALLBACK for item in sinks)


def deliver(sinks, definition, outcome=None, report=None):
    """按送达顺序把一次运行的结果送给 *sinks* 里的每个出口。

    返回 {出口名: 送达结果}(账本出口的是记录路径)。

    回传出口没有 *report* 时不在结果里,也不会被送 —— 那不是"送失败了",而是
    "根本没有 body 可送"(调用方没拿到 run_node 的报告三元组)。真正的送失败仍然
    由 post_result 抛异常表达,这里不吞(见模块开头)。
    """
    delivered = {}
    for item in sinks:
        if item.name == CALLBACK and report is None:
            continue
        delivered[item.name] = item.deliver(
            definition, outcome=outcome, report=report)
    return delivered
