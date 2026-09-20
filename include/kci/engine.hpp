// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 一台机器：把 argv 递给 tuxrun，把 console 判成结论，把结论送到该去的地方。
//
//   Runner  argv 与子进程
//   Judge   console → 判决（唯一算判决的地方）
//   Sink    结果去哪里（账本永远第一个）

#pragma once

#include <optional>
#include <string>
#include <vector>

#include "kci/base.hpp"
#include "kci/local.hpp"

namespace kci {

// ===========================================================================
// 11. argv 与执行                                        （lib/runner.py）
// ===========================================================================
//
// argv 是跟 tuxrun 的字节级契约：flag 顺序和省略规则决定客户机到底怎么启动，
// 所以只在这里拼一次。执行走子进程、不走 shell；超时也要把已收到的 console
// 交回来 —— 超时的时候 console 最值得看。
//
// 构件一律用 file:// 本地路径：tuxrun 会把它**只读 bind-mount** 进容器
// （tuxrun.utils.pathurlnone，实测确认）。所以本地 HTTP artifact server
// （探端口、证明端口归属、比对字节）整块不需要了。
//
// 这里不做判决：只返回字节和返回码。

struct Runner {
    struct Result {
        std::optional<int> returncode;   // nullopt = 超时
        std::string        console;      // 超时也带着已经收到的部分
    };

    static std::pair<std::vector<std::string>, std::string> argv(const Job& job,
                                                                 const RunConfig& config);
    static Result execute(const std::vector<std::string>& argv,
                          const std::string& cwd,
                          int timeout);
};

// ===========================================================================
// 12. 判决                                               （lib/judge.py）
// ===========================================================================
//
// tuxrun 即使每个 selftest 都失败也 exit 0，所以带判决的是 TAP，不是退出码。
// 两个问题，只在这里回答：
//
//   1) 我们拿到判决了吗？参数错 / 构件下不来 / 超时 / tuxrun 拒跑 = infra，
//      **绝不**算成测试失败。（真的 infra 被报成普通失败，比反过来更糟）
//   2) 拿到了：跑了多少条 TAP、失败几条。一条 TAP 都没有 = 失败，永不为 pass。
//
// 理由字符串一律在 console 的**有界窗口**里构造：从 14MB 尾部输出里拼一个
// 190 字的答案，曾让峰值内存多花 205MB。
//
// 仓库里有两份真 console 可以做基准（唯一的两份，别删）：
//   scripts/fixtures/tuxrun-pass.log  剥掉 ANSI 后 4 条 "ok N selftests: riscv: xxx"
//   scripts/fixtures/tuxrun-fail.log  一条 TAP 都没有（JobCanceled）→ 判 fail

struct Judge {
    struct Tap {
        int total = 0, failed = 0, skipped = 0;
        std::map<std::string, std::string> per_test;   // 用例名 → pass / fail / skip
    };

    static std::string strip_ansi(const std::string& console);   // 没得剥时原样返回

    // 顶层结果才算用例；一个名字只要出现过 not ok 就算失败（后面的 ok 抹不掉它）；
    // 什么都没解析到 → failed = 1
    static Tap tap_summary(const std::string& console, const std::string& label);

    // 为什么这次没拿到判决；拿到了就返回 nullopt。三个谓词，顺序固定：
    // tuxrun 拒跑 / job 本身失败 / 超时。
    static std::optional<std::string> infra_reason(const std::optional<int>& returncode,
                                                   const std::string& console,
                                                   const std::string& test);

    static Outcome verdict(const std::optional<int>& returncode,
                           const std::string& console,
                           const std::string& test);
};

// ===========================================================================
// 13. 结果去哪里                                         （lib/sink.py）
// ===========================================================================
//
// 两个出口，顺序是契约：
//
//     Ledger    永远有，永远第一个。var/results/<build-id>/<test>.json。
//               历史，永不清理；临时文件 + rename 写入；没跑到 tuxrun 的那次也记。
//     Callback  只在 definition 带 callback.url 时才有，且必须是 LAVA 兼容形状 ——
//               pipeline 的 callback 端点没有第二种格式的 parser，换格式结果静默丢失。
//
// callback token 在投递那一刻从环境读：不进配置对象、不落盘、不进 state 文件。

class Sink {
public:
    virtual ~Sink() = default;

    virtual std::string name() const = 0;
    virtual bool        wants(const Job& job, const Outcome& outcome) const = 0;
    virtual std::string deliver(const Job& job, const Outcome& outcome) = 0;
};

class Ledger : public Sink {
public:
    std::string name() const override { return "ledger"; }
    bool        wants(const Job&, const Outcome&) const override { return true; }
    std::string deliver(const Job& job, const Outcome& outcome) override;

    static void                     write(const Outcome& outcome);      // 临时文件 + rename
    static std::vector<Outcome>     read(const std::string& build_id = "");
    static std::vector<std::string> builds();                          // 账本知道的 build id
};

class Callback : public Sink {
public:
    explicit Callback(std::string url);

    std::string name() const override { return "callback"; }
    bool        wants(const Job& job, const Outcome&) const override;   // 只在带 URL 时
    std::string deliver(const Job& job, const Outcome& outcome) override;
};

// LAVA 兼容的 body（JSON 里嵌 YAML 字符串）；用上游真 parser 回放验证
Json        lava_body(const Job& job, const Outcome& outcome, const std::string& console);

// 从 body 里读回判决 —— 账本和 pipeline 对同一次运行不许有两种说法
Outcome     verdict_from_body(const Json& body);

// 投递那一刻才读
std::string callback_token();

}  // namespace kci
