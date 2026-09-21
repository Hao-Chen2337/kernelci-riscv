// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 只读：把中间层已经算好的东西摆出来。这一层不许自己算判决、不许自己统计 ——
// 旧 GUI 里同一份统计有四处实现，全部调 re.py 才是对的。
//
//   Filter   表格的筛选条件（builds / jobs 共用）
//   Records  账本读回来：跑了什么、还没跑什么、哪次变红了
//   Drift    两个 build 的内核 config 差异
//   Gui      那个页面：筛选 → 勾选 → 动作，外加「正在发生什么」

#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "kci/base.hpp"
#include "kci/flow.hpp"
#include "kci/local.hpp"
#include "kci/remote.hpp"

namespace kci {

// ===========================================================================
// 16. 筛选条件（GUI 的核心）                             （lib/view.py）
// ===========================================================================
//
// GUI 的价值全在这里：**用鼠标点出来，不许让人先查一遍再把 id 复制进去**。
// 所以每一列都能当筛选条件，而且条件是从已知集合里选（树、分支、test 名、
// 判决……），不是让人手打。

struct Filter {
    // --- 从远端来 ---
    std::string tree, branch, arch, defconfig;
    std::string job;                 // 只对 Kjob / job 行有意义
    int         days = 0;            // 0 = 不限；否则最近 N 天

    // --- 从本地来 ---
    enum class Origin { Any, Local, Remote, Both };
    Origin origin = Origin::Any;     // 本地有 / 远端有 / 两边都有

    // --- 构件完备性（决定要不要拉）---
    // 空 = 不限；否则要求具备这些构件
    std::vector<std::string> has;
    std::vector<std::string> missing;

    // --- 跑过没有 ---
    enum class Ran { Any, Never, Ever, Failing };
    Ran              ran  = Ran::Any;
    std::string      test;           // 只看某个 test
    std::optional<Verdict> verdict;  // 只看某种判决

    std::string text;                // commit / describe / build_id 子串
    size_t      limit = 50;
    size_t      offset = 0;

    bool accepts(const Kbuild&, const Builds* local) const;
};

// ===========================================================================
// 17. 账本的读法                                         （lib/re.py）
// ===========================================================================

struct Records {
    std::vector<Outcome> items;

    static Records load(const std::string& build_id = "");
    static std::vector<std::string> builds();      // 账本知道的 build id，新到旧

    Records                 for_build(const std::string& build_id) const;
    Records                 for_test(const std::string& test) const;
    std::optional<Outcome>  last(const std::string& test,
                                 const std::string& build_id = "") const;

    std::map<std::string, int> tally() const;      // {verdict: 条数}，判决词汇只有一份

    // 时间轴要的序列：同一 test 的历史，旧到新
    std::vector<Outcome> series(const std::string& test,
                                const std::string& build_id = "") const;
};

// 本地表减账本 = 还没跑的。带原因，不静默丢。
struct Todo {
    std::string build_id, test, reason;
};
std::vector<Todo> todo(const Builds& builds,
                       const std::vector<std::string>& tests,
                       const Records* records = nullptr);

// pass → fail 的迁移：一次坏 build 算一次回归，不是后面每次运行都算一次
std::vector<std::pair<Outcome, Outcome>> transitions(const Records& records,
                                                     const std::string& test = "");

void        render(const Records& records, std::ostream& os = std::cout, int width = 60);
std::string json_report(const Records& records);

// ===========================================================================
// 18. config 漂移                                        （lib/drift.py）
// ===========================================================================
//
// 两个 build 的内核 .config 差异。空 config 是**错误**：一个 HTML 索引页也能
// 解析出零个选项，「没有漂移」绝不能是一次失败下载的答案。
// 退出码就是答案：0 没漂移，1 有漂移。

struct Drift {
    std::optional<Kbuild> older, newer;

    std::vector<std::pair<std::string, std::string>>                        added, removed;
    std::vector<std::array<std::string, 3>>                                 changed;   // {选项, 旧, 新}

    // 不给 id 时比较该 job 最近两个 pass 且 done 的 build —— 这才是工具链升级后该看的对比
    static Drift between(Api& api, const std::string& job,
                         const std::string& older = "", const std::string& newer = "");

    // 手上有两份本地 .config 时
    static Drift from_files(const std::string& older_path, const std::string& newer_path);

    bool        drifted() const;
    void        print(std::ostream& os = std::cout, int max_lines = 0) const;
    std::string json() const;
};

// ===========================================================================
// 19. GUI                                                （lib/gui/）
// ===========================================================================
//
// 只读页面 + 一批按钮。按钮就是入口的那几条命令（子进程），页面不许变成
// 第二套行为：页面能做的事，运维手打也必须能做，反之亦然。
//
// **远端和本地是两件事，对应关系是第三件。** 所以页面按功能分开，一个功能一页：
//
//   /            总览：三个数字 + 去哪
//   /remote      API 有什么（build 与 job 各一段），条件是选择框
//   /local       我们有什么：一行一个 build，带「本地证据」列（见下）
//   /local/<id>  对应关系页：这份本地拷贝与哪个远端 build 对应、拉过几次
//   /pull        拉取：选条件 → 看候选 → 勾选 → 拉；拉完能看见留下什么记录
//   /jobs        一行一个 (build, test) = 本地表减账本
//   /runs        活动监控：谁在跑、日志、取消、重跑
//   /worker      常驻 worker 的起停与状态
//   /analysis    config 对比 + 回归时间轴
//
// 「本地证据」只有这几种，页面必须说清是哪一种：
//   pulled       有拉取记录：这些字节来自那些 URL，那时
//   unrecorded   字节在，但没有拉取记录 —— 从哪来的不知道
//   registered   有卡片（node id），还没拉
//   made-here    没有 node id 的卡片：本地产出、从没从 API 拉过
//   empty        目录或卡片是空的
//   远端列则写 `no remote counterpart` —— 并且总是紧挨着「这次问的是什么查询」
//
// 每个条件都是选择框，每个对象都是勾选，**没有一处要你手打 id**。
// 一次只允许一个写动作在跑（拉取 / 跑 / worker / runday / drift）—— 账本和下载
// 目录各自只有一个写者，两个并发就是损坏它们。

class Gui {
public:
    Gui(std::string host = "127.0.0.1",
        int         port = 8079,
        int         rows = 25,
        int         refresh = 0);

    void serve();          // 端口被占要报出来，不许悄悄换一个（旧 GUI 会扫 20 个端口）

    // --- 页面 ---
    Json        summary() const;    // 首屏要的东西，同时是 /summary.json 的契约
    std::string render() const;

    // --- 动作 ---
    std::string start(const std::string& action, const std::string& arg = "");
    Json        status() const;     // 每个 Run 的状态、开始时间、退出码

    static const std::vector<std::pair<std::string, std::vector<std::string>>>& actions();
};

// ===========================================================================
// 20. 页面文案（中英两份）                               （lib/i18n/）
// ===========================================================================
//
// 页面上每一句话都从这一份目录里取（`t(lang, "remote.asked")`），不许写在渲染代码里。
// 英文那一列是今天 gui.py 的原话，逐字不变 —— 所以 en 模式渲染出来和接文案之前
// 一模一样；中文那一列是运维口吻的短句，术语是固定的一套（远端 / 本地 / 对应 /
// 拉取 / 账本 / 判决 / 缺口 / 回归 / 登记 / 轮转）。
//
// 三条约定：
//   * **值不负责转义**。值里可以带英文那一份自己的 HTML（`&mdash;`、`<code>`），
//     插进页面原样用；插进去的那些*值*（build id、路径、查询）仍然由调用方
//     `html.escape()`。包住整句的标签（`<h2>`、`<span>`、`<p class="query">`）
//     留在 gui.py 里，句子里带链接的用 `{link}` 占位。
//   * 占位符就是 `str.format` 的 `{n}`，没有复数规则：英文保留 `row(s)` 的写法，
//     中文不带复数。
//   * 不是语言的词不译：命令名、flag、路径、`build_id`，以及记录自己的词表
//     （`tree` / `pulled` / `pass` / `resident`）—— 这些在 `word.*` 里两列相同，
//     放进目录是为了让 `--check` 分得清「故意相同」和「没翻」。
//
// 未知 key 返回 key 本身，缺语言回落 en，占位符对不上就原样返回：**页面不许因为
// 一句话死掉**。

enum class Lang { En, Zh };

// 取一条。C++ 侧没有 str.format，占位符由调用方自己拼进去。
std::string t(Lang lang, const std::string& key);

// query > cookie > Accept-Language 协商（含 zh-CN/zh-Hans/zh-TW，q=0 免疫）> En。
Lang pick_lang(const std::string& query_lang,
               const std::string& cookie_lang,
               const std::string& accept_language);

// 反查：给一段今天的英文原文，返回它的 key；歧义或找不到返回 nullopt。
std::optional<std::string> key_for(const std::string& english);

bool is_key(const std::string& key);

}  // namespace kci
