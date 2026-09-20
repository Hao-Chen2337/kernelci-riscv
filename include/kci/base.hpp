// SPDX-License-Identifier: LGPL-2.1-or-later
//
// 地板：退出码与异常、落盘位置、配置。
// 下面没有别的东西了 —— 这一层不 import 任何本项目的头文件。

#pragma once

#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace kci {

// 随便哪个 JSON 库：nlohmann/json、jsoncpp、RapidJSON 都行。这里只占个名字。
using Json = std::map<std::string, std::string>;

struct Kbuild;
struct Kjob;
struct Build;
struct Job;
struct Outcome;
class Api;
class Sink;

// ===========================================================================
// 1. 退出码与异常                                        （lib/errors.py）
// ===========================================================================
//
// 一次运行只有三种结局，退出码就是判决本身：
//
//     0   pass    console 证明测试跑了，且没有失败
//     1   fail    至少一个 selftest 失败
//     3   infra   根本没拿到判决：参数错、构件下不来、超时、tuxrun 拒跑、API 挂了
//
// 3 是 LAVA 的 incomplete，pipeline 读成基础设施问题，而不是测试结果。

enum class Verdict {
    Pass,
    Fail,
    Incomplete,   // 没拿到判决
    Error,        // 我们自己崩了（记进账本，再往上抛）
};

enum class Exit : int {
    Pass = 0,
    TestFail = 1,
    Infra = 3,
};

struct KciError : std::runtime_error {
    Exit code = Exit::Infra;

    explicit KciError(std::string what, Exit code = Exit::Infra)
        : std::runtime_error(std::move(what)), code(code) {}
};

struct ConfigError : KciError { using KciError::KciError; };    // 操作员要了不可能的东西
struct ApiError : KciError { using KciError::KciError; };       // API 答了，但答的不是能用的
struct ArtifactError : KciError { using KciError::KciError; };  // 构件的字节不对 / 下不来

// ===========================================================================
// 2. 落盘位置                                            （lib/layout.py）
// ===========================================================================
//
// 工作目录是 var/，不是旧树的 work/ —— 两棵树并行期间互不污染：旧读者遇到
// 读不懂的记录会直接抛异常，共用一个目录等于让一棵树弄坏另一棵树。
// $KCI_WORK_DIR 可以整体挪走。
//
// 一个位置只有一个函数拼，所以「换个目录」是一次编辑而不是一次 grep。

struct Layout {
    static std::string work();                                   // var/ 或 $KCI_WORK_DIR
    static std::string downloads(const std::string& build_id);   // var/downloads/<id>/  拉下来的构件
    static std::string baked(const std::string& name);           // var/baked/<key>.ext4 烤好的客户机磁盘
    static std::string runs(const std::string& run_id);          // var/runs/<id>/       一次活动（Run）
    static std::string workspaces(const std::string& name);      // var/workspaces/<n>/  一个 job 的临时目录
    static std::string provenance(const std::string& build_id);  // var/downloads/<id>/provenance.json
    static std::string logs(const std::string& name);            // var/logs/            归档的 console
    static std::string serve(const std::string& name);           // var/serve/           本部署对外服务的内核
    static std::string state(const std::string& name);           // var/state/           部署事实

    static std::string results(const std::string& build_id = "",
                               const std::string& test = "");    // var/results/<id>/<test>.json（账本，历史）

    static std::string worker_state();                           // 轮转的 cursor / seen / pending
    static std::string worker_lock();                            // flock：一个部署一个 worker
    static std::string index();                                  // var/state/builds.json 本地表
};

// ===========================================================================
// 3. 配置：跑一次 / 轮转                                  （lib/config.py）
// ===========================================================================
//
// 单向一次：argv 进，对象出。配置对象不落盘、不带密文 —— callback token 在
// 投递那一刻才从环境读（见 engine.hpp 的 callback_token），所以 state 文件
// 永远不会变成凭据。
//
// 两个结构体，不是一个：一次运行要的东西（设备、超时、往哪报告）和常驻轮转
// 要的东西（游标、重试、轮询间隔）没有一处重叠，合成一个只会让人以为它们相关。

struct RunConfig {
    std::vector<std::string> tests;                  // 空 = DEFAULT_TESTS
    // 三个容易混的名字，混过一次：
    //   device              tuxrun 启什么              (qemu-riscv64)
    //   lab                 派活给我们的 pipeline runtime (pull-labs-riscv)
    //   container_runtime   tuxrun 在什么里跑镜像       (docker / podman)
    std::string container_runtime = "docker";
    std::string device     = "qemu-riscv64";
    std::string tuxrun_bin = "tuxrun";
    std::string callback_url;                        // 空 = 只落账本，不发回调
    int         timeout    = 1800;                   // 单个 job 的墙上时间上限
    std::string rootfs;                              // 空 = 用默认的 nfsroot；实验室自己拥有 guest 镜像
    std::string output_dir;
    Json        params;                              // 额外的 tuxrun 参数

    // 出口：账本永远有，回调只在被要求时才有
    std::vector<std::shared_ptr<Sink>> sinks() const;
};

struct PollConfig {
    std::string api_url;
    // 认领过滤：节点的 data.platform / data.runtime 对不上就不是我们的活。
    // 这里的 runtime 是**实验室名**（pull-labs-riscv），不是容器运行时 ——
    // 把两者当成一个，worker 就会拒绝调度器派给它的每一个节点。
    std::string platform = "qemu-riscv64";
    std::string runtime  = "pull-labs-riscv";
    std::string container_runtime = "docker";
    std::string state_file;
    int         period      = 5;                     // 两次轮询之间睡多久
    int         max_retries = 5;                     // 连续取事件失败多少次就退出
    bool        once        = false;                 // 处理完当前队列就返回
    std::string since;                               // 只给没有 cursor 的 state 文件播种

    static RunConfig  parse_run(int argc, char** argv);
    static PollConfig parse_poll(int argc, char** argv);

    Api client(bool write = false) const;            // write=true 才要 token（两个结构体共用）
};

}  // namespace kci
