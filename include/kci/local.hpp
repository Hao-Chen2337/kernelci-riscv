// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 本地动作：把一个远端事实变成本地的东西，然后在上面跑一个 test。
//
//   Build/Builds   一次 build 的本地副本；本地表
//   Job/Jobs       一个 test 的规格；一批规格
//   Outcome        跑完的结果
//
// 三个名词的关系（这是整个设计里最要紧的一句话）：
//
//     Job 是**规格**（build + test），可复用、无副作用、可以跑很多次
//     Outcome 是**产物**（判决 + TAP 计数 + 日志），进账本
//     一次跑 = (Job, Outcome)，中间的「正在跑」在 flow.hpp 的 Run 里
//
//     Job : Run : Outcome = 1 : N : 1

#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "kci/base.hpp"
#include "kci/remote.hpp"

namespace kci {

// ===========================================================================
// 7. 本地 build                                          （lib/build.py）
// ===========================================================================
//
// 草稿：struct buildnode { struct kbuildnode } —— 本地 build = 远端 build + 本地状态。
//
// **一个本地目录的名字等于远端 build_id，什么也证明不了。** 两个相等的值不是同一个
// 东西：对应关系要在**拉取的那一刻**被建立，并被记下来 ——
// `var/downloads/<id>/provenance.json` 里每个构件一行：从哪个 URL 来、证明了几个字节、
// 什么时候。于是「这份本地拷贝来自那个远端 build」是一个**事实**，
// 而不是从两个相等 id 推出来的假设；没有记录的字节就是没有记录：
// 「东西在，但从哪来的不知道」也是一种答案，而且必须说出来。

struct Build {
    Kbuild                             kbuild;   // 它是哪个 build
    std::string                        path;     // var/downloads/<build-id>/
    std::map<std::string, std::string> files;    // 构件名 → 本地文件

    explicit Build(Kbuild kb);

    std::string build_id() const;
    std::string describe() const;

    // 下载一个 run 需要的构件，逐个核对大小；已存在且大小对的就不重下。幂等。
    // 任何字节不对都抛 ArtifactError —— 半截 Image 会「跑起来」然后骗人。
    Build& make(const std::vector<std::string>& want = {"kernel", "modules", "kselftest"});

    // 落在这台机器上的构件，`{名字: 路径}`（就是 files 的形状）。
    std::map<std::string, std::string> present() const;

    // 这份本地拷贝被拉取过几次的记录，新的在前；没拉过就是空 ——
    // 「字节是我们的，但从哪来的没有记录」也是诚实的答案。
    Json provenance() const;

    // 跑这个 test 还缺什么；空 = 能跑。带原因，不静默丢。
    std::vector<std::string> missing(const std::string& test) const;

    // 客户机磁盘：nfsroot tar.xz → mkfs.ext4 -d（不用 loop mount、不用 root）。
    // 同名文件在就复用（实测一次烤盘 66~124s）；没有缓存机制的第二层。
    std::string rootfs(bool with_modules = false);

    void merge(const Build& other);   // 把另一个 build 的构件并进来
    void remove();                    // ./run.sh prune 干的事
    void print(std::ostream& os = std::cout) const;
};

// 本地表：这台机器上有哪些 build。一个 JSON 文件，不是 sqlite 库。
class Builds {
public:
    Builds() = default;

    static Builds load(const std::string& path = "");   // 读不出来 = 空表，不是错误
    void          save(const std::string& path = "") const;   // 临时文件 + rename

    void  fetch(Api* api, const std::string& tree = "", int days = 7, size_t limit = 200);
    Build get(const std::string& build_id) const;
    Build newest() const;
    void  merge(const Kbuilds& other);
    void  make(const std::vector<std::string>& tests = {});

    size_t                   size() const;
    const std::vector<Build>& items() const;
    void                     print(std::ostream& os = std::cout) const;
};

// ===========================================================================
// 8. 测试目录                                            （lib/job.py）
// ===========================================================================
//
// 一个 test 就是：名字 + 需要什么构件 + 怎么变成 tuxrun 参数。一处定义，一个 owner。

namespace tests {

inline const char* BOOT            = "boot";
inline const char* KSELFTEST_RISCV = "kselftest-riscv";
inline const char* KSELFTEST_KVM   = "kselftest-kvm";

// 不带 --test 时跑什么。boot 最便宜，而且它的 console 决定「内核问题」还是「测试问题」。
extern const std::vector<std::string> DEFAULT_TESTS;   // boot, kselftest-riscv, kselftest-kvm

// KVM 是**排除表**，不是白名单：tarball 里有什么由 build 决定（老内核没编出来的
// 名字自然缺席，不会报「没有这个测试」），这七个在 TCG 下不可能过 ——
// 3 个 perf、2 个 stress，加两个会挂 / 烧完预算的。
extern const std::vector<std::string> KVM_SKIP_TESTS;

}  // namespace tests

// ===========================================================================
// 9. 本地 job：规格与执行                                （lib/job.py）
// ===========================================================================
//
// 草稿：struct jobnode { kjobnode }; job(build) → make() → run() → out

struct Job {
    Build       build;
    std::string test;
    Json        given;        // 非空 = 跑这份 definition；空 = 自己渲染
    Json        params;       // 额外的 tuxrun 参数
    std::string workspace;    // 本次跑用的临时目录（run() 自己设）
    int         timeout = 0;

    // make() 填：构件名 → 本地路径（kernel / modules / rootfs / kselftest）。
    // argv() 优先用它（file:// 交给 tuxrun 只读 bind-mount），没有再退回远端 URL。
    std::map<std::string, std::string> local;

    Job(Build b, std::string test);

    // 包一份别人造的 definition（节点给的、本地表给的、测试夹具给的）
    static Job from_definition(const Json& definition, std::optional<Build> build = std::nullopt);

    std::string id() const;   // "(build_id, test)"，GUI 的行键；同 id 就是同一个规格

    Job& make();              // 备好构件和（需要时的）客户机磁盘

    // definition 是**普通 JSON**，和上游模板渲染出来的同构。
    // 这是唯一的跨层边界：换成类，执行层就会开始分辨「这个定义是谁造的」，
    // 而本地那条线的绿就不再是 worker 那条线的证据。
    Json definition() const;

    std::pair<std::vector<std::string>, std::string> argv(const RunConfig& config) const;

    // 唯一的执行器。job 层面的任何问题都不往外抛：没跑到 tuxrun 也照样产出一个
    // Outcome（infra，退出码 3），也照样写账本 —— 最值得留的记录是失败那次的。
    // 配置作为参数传进来，而不是挂在 Job 上：Job 是**规格**（build + test），
    // 部署配置（runtime / device / tuxrun 路径 / 超时）不属于规格。
    Outcome run(const RunConfig& config,
                const std::vector<std::shared_ptr<Sink>>& sinks = {},
                const std::string& source = "local");

    void print(std::ostream& os = std::cout) const;
};

class Jobs {
public:
    Jobs() = default;

    // 一个 build 能跑的每个 test；不能跑的也列出来，带原因
    static Jobs for_build(Build build, const std::vector<std::string>& tests = {});

    // 顺序跑，一个 Outcome 一个；一个失败不打断其余的
    std::vector<Outcome> run(const RunConfig& config,
                             const std::vector<std::shared_ptr<Sink>>& sinks = {},
                             const std::string& source = "local");

    size_t                 size() const;
    const std::vector<Job>& items() const;
    void                   print(std::ostream& os = std::cout) const;
};

// ===========================================================================
// 10. 结果                                               （lib/out.py）
// ===========================================================================
//
// 一次跑的产物，也是 sink、查看器、调用者唯一看得见的东西。

struct Outcome {
    std::string build_id, test;
    Verdict     verdict   = Verdict::Error;
    Exit        exit_code = Exit::Infra;
    std::string detail;
    Json        results;      // TAP 摘要：{"total": N, "failed": N, "skipped": N}
    Json        revision;     // 被测内核的版本信息（build 节点带的话）
    std::string build_created, job, source, timestamp, artifacts_dir, log;

    Json        record() const;   // 账本记录：字段一个不缺，也不许多
    std::string json() const;     // 键排序、缩进一格 —— 同样的结果 diff 出来一样
    bool        passed() const;
    void        print(std::ostream& os = std::cout) const;

    static Outcome infra(const std::string& detail);   // 没拿到判决的那次
};

}  // namespace kci
