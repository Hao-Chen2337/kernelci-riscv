// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 远端事实：KernelCI 那边有什么。只读，不落盘，不跑东西。
//
//   Api            唯一跟 KernelCI 说话的 HTTP
//   Kbuild/Kbuilds API 里有哪些 build
//   Kjob/Kjobs     API 里有哪些 job（队列 + 历史）
//
// 这一层的输出是「能跑什么」，engine 层的输入是「怎么跑」。

#pragma once

#include <optional>
#include <string>
#include <vector>

#include "kci/base.hpp"

namespace kci {

// ===========================================================================
// 4. API 客户端                                          （lib/api.py）
// ===========================================================================
//
// 四个调用者要的是同样的三件事：/latest 基址、不会静默截断的翻页、
// 以及「API 答了但不是 JSON」变成一种异常，而不是让调用者炸在 ValueError 上。
//
// 3xx 必须拒绝：allow_redirects=false 只是「没跟」，不等于「发现」——
// 别的什么在应答时，要变成 ApiError。

class Api {
public:
    explicit Api(std::string base = "", std::string token = "", int timeout = 60);

    // --- 三个动词 ---
    Json        get(const std::string& path, const Json& params = {});
    void        post(const std::string& path, const Json& body, const std::string& token = "");
    std::string text(const std::string& url);        // 纯文本构件（内核 .config）

    // --- 节点词汇 ---
    std::vector<Json> nodes(const std::string& kind = "", const Json& filters = {});
    Json              node(const std::string& node_id);
    std::vector<Json> events(const std::string& kind  = "job",
                             const std::string& state = "",
                             const std::string& since = "");
    std::optional<Json> counts();                    // API 不通返回 nullopt，不抛

    // flag > $KCI_API_URL > 本地部署
    static std::string url(const std::string& explicit_url = "");
};

// ===========================================================================
// 5. 远端 build                                          （lib/kbuild.py）
// ===========================================================================
//
// 身份是 build_id（从构件 URL 里解析出来），**不是 node id** —— node id 每个
// 数据库都不一样：本地 API 和生产 API 对同一个 build 给的 node id 不同。
//
// 去重按 build_id：同一个 build 见两次就是一条。

struct Kbuild {
    std::string node_id;                             // 这个数据库里的节点 id，只作引用
    std::string build_id;                            // 真正的身份
    std::string tree, branch, arch, defconfig, compiler;
    std::string created, state, result;
    std::map<std::string, std::string> artifacts;    // 构件名 → URL（名字用 API 的拼法）
    Json revision;                                   // data.kernel_revision 原样带着

    static Kbuild from_node(const Json& node);       // 不是 kbuild 节点就抛 ApiError

    std::string artifact(const std::string& name) const;   // 没有就返回 ""，不抛
    bool        usable(std::string* why_not = nullptr) const;
    std::string describe() const;                    // tree-branch-arch-defconfig，记录和命令行用的标签
};

class Kbuilds {
public:
    explicit Kbuilds(Api* api = nullptr);

    Kbuild              getnew(const std::string& tree, const std::string& branch = "");
    std::vector<Kbuild> getdays(const std::string& tree, int days, const std::string& branch = "");
    Kbuild              get(const std::string& build_id);

    void                       merge(const Kbuilds& other);   // 按 build_id 去重
    size_t                     size() const;
    const std::vector<Kbuild>& items() const;
    void                       print(std::ostream& os = std::cout) const;

private:
    Api*                api_;
    std::vector<Kbuild> items_;
};

// ===========================================================================
// 6. 远端 job                                            （lib/kjob.py）
// ===========================================================================
//
// 两种形态是同一个节点类型：
//
//     state = available  要跑的（带 job_definition URL）   ← worker 读这个
//     state = done       跑完的（带 result）               ← trend 读这个
//
// 「本地跑过没有」**不是**这一层的字段：那是账本的事，见 view.hpp。

struct Kjob {
    std::string node_id, name, state, result, platform, runtime, created;
    std::string definition_url;                      // 空 = 这活没法跑
    std::string callback_url;
    Json        artifacts;
    Json        node;                                // 原始节点：给需要本类没列出的字段的读者

    static Kjob from_node(const Json& node);

    bool claimable(const std::string& runtime = "") const;   // 现在还是 available、是我们的 runtime 吗
    Json definition(Api& api) const;                          // 取回并解析 definition
    void print(std::ostream& os = std::cout) const;
};

class Kjobs {
public:
    explicit Kjobs(Api* api = nullptr);

    std::vector<Kjob> getjob(const std::string& state  = "",
                             const std::string& name   = "",
                             const std::string& device = "",
                             const std::string& kind   = "job");
    std::vector<Kjob> available(const std::string& runtime = "");
    std::vector<Kjob> done(const std::string& name);          // 历史，旧到新（趋势要这个顺序）

    void                     merge(const Kjobs& other);
    size_t                   size() const;
    const std::vector<Kjob>& items() const;
    void                     print(std::ostream& os = std::cout) const;
};

}  // namespace kci
