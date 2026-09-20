// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 随时间发生的事：一次活动，和一个不停转的循环。
//
//   Run     一次后台活动：跑一个 job、拉一批构件、起一个 worker……有状态、有日志、可取消
//   Poller  常驻：看 API 队列，认领、跑、上报、记住做过了什么
//
// Run 是 Job 和「跑」分开之后多出来的那个词：
//
//     Job    规格     可复用、无副作用
//     Run    发生     一次执行，有开始、有日志、有终点
//     Outcome 产物    判决，进账本
//
// 为什么不让 GUI 自己在内存里记一份（旧 GUI 就是这么干的）：GUI 一重启，
// 「什么在跑」就丢了。Run 落成 var/runs/<id>/run.json + run.log，
// 重启后扫一遍目录就知道，pid 已死的标成 failed。

#pragma once

#include <chrono>
#include <optional>
#include <string>
#include <vector>

#include "kci/base.hpp"
#include "kci/local.hpp"
#include "kci/remote.hpp"

namespace kci {

// ===========================================================================
// 14. Run：一次后台活动                                  （lib/run.py）
// ===========================================================================

struct Run {
    enum class Kind {
        Job,      // 跑一个 job（对象在 job 字段里）
        Fetch,    // 拉一批 build 的构件
        Worker,   // 常驻 worker
        Runday,   // 补跑某一天
        Stack,    // 起/停本地栈
        Verify,   // 自检
        Drift,    // config 漂移
        Trend,    // 回归趋势
        Prune,    // 清理
    };

    enum class State {
        Running,
        Done,
        Failed,
        Cancelled,
    };

    std::string                          id;        // var/runs/<id>/ 的目录名
    Kind                                 kind;
    State                                state = State::Running;
    std::string                          what;      // 给人看的一行：「<build> kselftest-kvm」
    std::vector<std::string>             argv;      // 真正跑的命令：和运维手打的那条一样
    int                                  pid = 0;
    std::string                          dir;       // var/runs/<id>/
    std::string                          log;       // var/runs/<id>/run.log
    std::chrono::system_clock::time_point started, ended;
    std::optional<int>                   exit_code;
    std::optional<Job>                   job;       // kind == Job 时才有
    std::optional<Outcome>               outcome;   // kind == Job 且跑完时才有

    // 起一个子进程。argv 就是运维手打的那条命令 —— GUI 不许有第二套行为。
    static Run start(Kind kind, std::vector<std::string> argv, std::string what = "");

    static std::vector<Run> load_all();   // 扫 var/runs/*/run.json（GUI 重启后靠这个）
    void                    save() const;
    bool                    alive() const;   // pid 还在吗；不在就把 Running 改成 Failed
    void                    cancel();
    std::string             log_since(size_t offset, size_t* next = nullptr) const;

    void print(std::ostream& os = std::cout) const;
};

// ===========================================================================
// 15. 轮转                                               （lib/poller.py）
// ===========================================================================
//
// 草稿：class poller { date d; time t; poller(d) { ... } }
//
// 整个项目最复杂的东西，故意做成一个类 + 它自己的 state 文件：它的复杂是真的，
// 而且几部分分不开 —— cursor、seen、pending 是同一个问题的三个视图
// （「这个 worker 已经处理过什么」）。拆成四个模块时它们是 1100 行。
//
// 每条保证背后都对应一个真出过的 bug：
//
//   * flock：一个部署一个 worker，第二个直接退出而不是抢
//   * cursor 只在整批都处理成功之后才前进；since 只给没有 cursor 的文件播种；
//     900s 重叠窗口重扫（events 是无序的），靠 seen 去重
//   * 有 pending 报告的节点只重投，**绝不重跑**
//   * 每条事件之后落盘、SIGTERM 先 flush 再退（被 kill 的 worker 丢过报告，
//     也给已有结果的节点重跑过 tuxrun）
//   * 只有报告真的被接受（2xx）才把节点标 seen

class Poller {
public:
    Poller(Api& api,
           RunConfig run,
           std::string runtime     = "",          // 实验室名，不是容器运行时
           std::string platform    = "",
           std::string state_file  = "",
           int         period      = 5,
           int         max_retries = 5,
           std::string since       = "");

    void                     loop();     // 常驻：取事件 → 处理 → flush → 睡
    int                      once();     // 处理完当前队列就返回（worker --once）
    std::vector<Outcome>     run_day(const std::string& day);   // 某一天的全部（runday）

    bool handle(const Kjob& node);       // 跑一个节点并投递；true = 可以标 seen

    void load();                         // 读 state；坏了只警告，绝不静默修
    void flush();                        // 原子落盘；每条事件后 + 信号处理里
    bool seen(const std::string& node_id) const;
    void mark_seen(const std::string& node_id);          // 超过上限就淘汰最旧的
    Json pending(const std::string& node_id, const Json& report = Json{});

private:
    bool               claim(const Kjob& node);   // 现在还是 available、是我们的 runtime 吗
    std::string        start_cursor();            // 持久 cursor > --since > 现在
    std::vector<Kjob>  events();                  // 一批事件（带重叠窗口）
};

}  // namespace kci
