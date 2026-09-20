// SPDX-License-Identifier: LGPL-2.1-or-later
//
// kernelci-riscv —— 中间层接口（C++ 版）
//
// 这份头文件是**图纸**，不是程序：只有声明和注释，没有实现。
// 实现是仓库根的 lib/*.py，形状以这里为准；形状改了，同一次改这里。
//
// 一次运行只有四件事，别的都是选择器或查看器：
//
//     拉一个 build  →  变成本地的东西  →  在上面跑一个 test  →  拿到一个 out
//     Kbuilds           Build                Job                    Outcome
//
// 读的顺序 = 下面的顺序 = 依赖方向（谁也不许反向 include）：
//
//     base.hpp    地板     退出码 · 路径 · 配置
//     remote.hpp  远端事实 API · Kbuild · Kjob
//     local.hpp   本地动作 Build · Job · Outcome
//     engine.hpp  一台机器 Runner · Judge · Sink
//     flow.hpp    随时间发生的事  Run · Poller
//     view.hpp    只读      Records · Drift · Gui
//
// 三条铁律（照抄旧树用血换来的）：
//
//   1. Job::run() 是唯一的执行器。worker、一次性 fetch、本地表、GUI 按钮都走它。
//      出现第二个执行器，本地那条线的绿就不再是 worker 那条线的证据。
//
//   2. Job::run() 不许知道 definition 是自己造的还是 API 派下来的。
//      definition 保持普通 JSON，和上游模板渲染出来的同构 —— 这是唯一的跨层边界。
//
//   3. 结果先落账本（无条件、第一个）；callback 只是额外出口，且只在 definition
//      带 callback.url 时才发。token 在投递那一刻才从环境读，永不落盘。

#pragma once

#include "kci/base.hpp"
#include "kci/remote.hpp"
#include "kci/local.hpp"
#include "kci/engine.hpp"
#include "kci/flow.hpp"
#include "kci/view.hpp"

namespace kci {

// ===========================================================================
// 入口：每个都是薄薄一层 —— 解析参数、组装对象、跑、用退出码收场
// ===========================================================================
//
//   run_latest   最新的一个 build 跑一次            （./run.sh fetch）
//   pull_worker  常驻：认领 API 队列里的 job         （./run.sh worker）
//   runday       某一天的全部 build，账本说跑过的不再跑（./run.sh runday）
//   table        本地表：index / jobs / todo / summary / run，离线
//   results      读账本；gui：页面；drift：两份 config 的差异
//
// 退出码就是判决：0 pass、1 测试失败、3 基础设施。

int run_latest(int argc, char** argv);
int pull_worker(int argc, char** argv);
int runday(int argc, char** argv);
int table(int argc, char** argv);
int results(int argc, char** argv);
int gui(int argc, char** argv);
int drift(int argc, char** argv);

}  // namespace kci
