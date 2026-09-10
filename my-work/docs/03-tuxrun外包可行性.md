# 03 tuxrun 外包可行性(为什么上游只写 361 行,我们写了 779 行)

> 验证时间:2026-09(本 memo);证据全部来自本地代码 file:line、本机 /tmp 实测(pip 安装、`--list-devices/--list-tests`)与网页 URL。未实跑 QEMU/tuxrun(规则禁止长跑)。

## TL;DR

1. 可以外包,但**不是零成本**:"和 guest 说话"被外包给 LAVA `lava-run`(跑在 docker/podman 容器里),代价是引入容器镜像 + LAVA 词汇 + 上游 3 个未就绪点。
2. 若以「example_pull_lab.py 改一版 + tuxrun」为执行器,worker 中约 **290–330 行**可删(PTY 串口驱动、ext4 烘焙大半、guest 命令、mount hack、===DONE===),最难的维护点消失。
3. 但 riscv 专属三件事 tuxrun **没有现成表达**:①无 `kselftest-riscv` 测试类(list-tests 实测缺);②KVM 定向(insmod kvm.ko + H 扩展 + 精选子集)无 CLI 参数;③上游结果回收未闭环(与执行器无关)。
4. 结论:自研 779 行换「example+tuxrun」净省约 30–40% 行数,方向对、是上游钦定形态(长期待办 §8 成立),但**当前节点不建议主路径切换**:收益集中在消灭自研驱动维护,代价是依赖上游 tuxlava 补测试类 + 本 lab 要有容器/镜像/网络。

## 1. 上游 example_pull_lab.py:外包了什么、留了什么

本地/上游 main 逐字节一致(已验证:raw.githubusercontent.com/kernelci/kernelci-pipeline/main/tools/example_pull_lab.py 与本地完全相同,361 行)。

| 职责 | example_pull_lab.py | 我们 worker 对应 |
|---|---|---|
| poll 事件 | `state=done`(第 29 行)——**旧协议,实测拉不到 available 事件** | `state=available`(riscv_pull_worker.py:414–422) |
| 取 job 定义 | 同(37–41 行) | 同(425–429) |
| 执行测试 | **子进程调 tuxrun**(80–113 行),kernel/modules/rootfs 全是 URL | 自研 QEMU+PTY(77–407 行) |
| 交互 | `input()` 等回车(152–153 行),**不能当守护进程** | 无 |
| 失败/健壮性 | 仅 API 重试;无 node 去重、无状态持久化、无校验、无回调回传(结果只打印) | seen+flock+state 文件+sha256 校验+回调 POST(432–453、657–733) |

Issue #1373「update example_pull_lab.py to boot qemu-* (arm64|riscv etc), and fvp-aemva」:作者/关闭人 bhcopeland(=tuxrun 维护者 Ben Copeland),2026-01-15 以 **COMPLETED 关闭**,body 仅「Qemu + FVP now booting」,无关联 PR(issue 页 JSON 实测:closedByPullRequestsReferences 为空)。且 main 上该文件仍未改 state=done、riscv device 仅靠「job env platform 名直通 device 名」的通用逻辑(301–311 行)。**判断:真正落地的是 kernelci/tuxrun 侧**——注意 tuxrun 已从 Linaro/tuxrun(GitLab 归档)迁到 **kernelci/tuxrun**(默认分支 master;Linaro blog 有移交公告)。

## 2. tuxrun 本体:是什么、怎么跑(源码级)

- pip 装:PyPI `tuxrun 1.10.0`(requires-python>=3.10,依赖 argcomplete/jinja2/requests/PyYAML/ruamel.yaml/**tuxlava**)。本机 /tmp venv **装成功**(get-pip 绕过 ensurepip 缺失;apt 不能动),`tuxrun --version`=1.10.0。仓库:kernelci/tuxrun,维护人 Anders Roxell/Ben Copeland。
- 体量:tuxrun 包 11 个模块共 **2031 行**(__main__ 562/argparse 503/…);device/test 目录在依赖包 **tuxlava**(1186 行 + jinja2 模板)。**真正驱动 guest 的 `lava-run` 是 LAVA 项目 dispatcher**,不是 tuxrun 自己写的。
- 执行模型(实测代码):tuxrun 渲染 LAVA 三件套 definition.yaml + device.yaml + dispatcher.yaml(__main__.py:296–313),默认 `--runtime podman`,镜像 `docker.io/linaro/tuxrun-dispatcher:latest`(argparse.py:407–409,该镜像 FROM `lava/lava-dispatcher:2026.05.dev0091` 并 apt 装全部 qemu-system-* 含 riscv);`lava-run` 在容器内跑,QEMU 也在这容器里。**根因:LAVA 把串口/expect/auto_login/overlay 全包了**——这正是用户自述难点(login 检测、PTY、mount)所在的 ~300 行。
- console/根文件:qemu device 模板(qemu.yaml.jinja2)显示 boot 用 `-kernel … -append console=ttyS0,115200 rootwait root=/dev/vda …`,auto_login `login:/root`+prompt 正则 `root@(.*):[/~]#` 或 `/ #`(就是 worker SHELL_PROMPT_RE 那套的 LAVA 版);rootfs 以 raw 盘(-drive file={rootfs},format=raw,if=virtio)或 cpio(-initrd)启动;overlay 把 modules/kselftest tar **注入盘内**(LAVA overlay/libguestfs,容器内完成)。
- 结果产出:`--save-outputs` 落 logs*.txt/yaml/html + metadata.json + **results.json**(results.py:26 起解析 LAVA `lvl: results` 信号);退出码 = max(runtime.ret, results.ret)(__main__.py:459)。

## 3. riscv/kselftest/KVM 逐项对照(tuxrun 能力边界,①②③④⑤)

| 用户需求/worker 特性 | tuxrun 现状 | 证据 |
|---|---|---|
| ①device 支持 riscv64 | **qemu-riscv64 存在**:machine=virt,cpu=**rv64**(无 v/h),ext4 virtio,console ttyS0,rootfs 默认 storage.tuxboot.com | tuxlava/devices/qemu.py:514+;本机 `--list-devices` 有 qemu-riscv64 |
| H 扩展/自定义 CPU | **可**:device definition 从 parameters 读 `cpu`/`machine` 覆盖(qemu.py:131–132),即 `--parameters cpu=rv64,h=true`;boot 参数用 `--boot-args` 追加 | tuxlava 源码;模板 qemu.yaml.jinja2 |
| ②跑「riscv collection」kselftest | **无 `kselftest-riscv` 测试类**:126 个 KSeltest 类,无 riscv;本机 `--list-tests` 只有 kselftest-arm64/kselftest-kvm 等。需给 tuxlava 加一个小 class(~15 行)并随 2026 版发布,或用户自开 fork | tuxlava/tests/kselftest.py;本机 CLI 实测 |
| ③和 guest 说话 | LAVA lava-run 处理(expect 串口、login、shell、结果回收)——**量级上 tuxrun 自己零 PTY 代码** | 见 §2 |
| ④KVM selftest(insmod kvm.ko + 子集) | `kselftest-kvm` 测试类存在但只发 `TST_CMDFILES=kvm` 跑**整个 kvm collection**;**无 pre-command/insmod 表达**;子集只能用 SKIPFILE/SHARD 部分近似(worker 的 KVM_TEST_SUBSET「-t kvm:xxx」等价物没有);且需先解决 H 扩展(上行)与 rootfs 里有 kvm.ko | tuxlava kselftest.py:407;kselftest.yaml.jinja2 参数表 |
| ⑤URL/本地文件 | 两者皆可:http(s) 走 dispatcher/缓存(assets.py:35–98,ETag 缓存 6h);本地 `file://` bind 进容器;modules 必须 .tar.gz/.tar.xz/.tgz(qemu.py:88);kernel gz 自动解压(deploy compression) | tuxrun/assets.py、tuxlava |
| kernelci storage URL | worker 实测匿名可下(无鉴权);tuxrun 容器内同样出站下载,可达性条件相同 | worker 实测 |
| tar.xz nfsroot 直接喂 `--rootfs` | **未验证**:device 模板把 rootfs 当 raw 盘或 cpio;full.rootfs.tar.xz 是否被 LAVA deploy 接受需实跑确认。保守路线=保留 worker 的 tar→ext4 烘焙 | qemu.yaml.jinja2;未实跑 |

## 4. worker 779 行账:外包后删/留对照(行号=riscv_pull_worker.py)

| 区间 | 内容 | 外包后 |
|---|---|---|
| 62–72 | KVM_TEST_SUBSET 精选子集 | **留**(转成 SKIPFILE/自定义表达) |
| 77–97 | download(流式+sha256) | 可删(tuxrun/LAVA 下载缓存) |
| 100–111 | download_kernel(gz 解压) | 删(kernel deploy 带 compression) |
| 114–145 | safe_members/extract_tarball | 半留(若仍自烘 tar→ext4) |
| 148–179 | bake_rootfs_image(ext4 烘焙+kselftest/modules 解包) | **半删**:overlay 注入部分删,根 base 转换保守保留(见 §3 末行) |
| 182–224 | mount_cmd ctypes hack / guest_bootstrap / ===DONE=== | 删(lava-run 环境自带;insmod 需另找 LAVA 表达) |
| 229–343 | serial_reader/drain_pty/run_qemu(**~115 行**) | 删(auto_login+prompts) |
| 346–407 | baseline/kselftest/kvm 三 builder(**~62 行**) | 改写为 tuxrun 命令参数(小) |
| 414–733 | poll(state=available)/seen/flock/重试/回调/error_body/CLI | **全留**(example 脚本反而缺这些,改它也要补) |
| 467–489、559–563 | summarize(TAP→summary/tests) | 半留(可改读 results.json 或复用) |

**净效果:可整段删 ~290–330 行(占总行数 37–42%),其中 PTY/烘焙/guest 驱动 ~250–280 行是「维护最贵」部分;协议+健壮性 ~300 行两边都要写。**

## 5. 「最小 lab 执行器」形态与行数预估

- 方案 A(推荐评估):riscv_pull_worker.py 保留协议骨架,把执行块换成 `subprocess tuxrun --device qemu-riscv64 --kernel <url> --modules <url> --rootfs <ext4|url> --tests kselftest-riscv|kselftest-kvm --parameters cpu=rv64,h=true,KSELFTEST=<url>` → **约 430–480 行**(比现在少 ~300 行,且不再维护串口/mount 细节)。
- 方案 B:改 example_pull_lab.py(361 行)→ 需补 state=available、去 input()、加 seen/state 持久化、加回调回传与 error_body、加 riscv/kvm 参数分派 → **约 500–550 行**,与 A 同量级但底子是上游文件、PR 易合入。
- 两者都必须做的非执行器工作:kvm 专属表达(自写 LAVA device dict 或 tuxlava 扩展 + insmod 前置)、kselftest-riscv 测试类(上游 tuxlava PR)、结果回传收口(§6)。

## 6. 边界:外包不解决的事(均本地代码实证)

- 事件态:scheduler.py:918–921 注释+pull_labs 节点置 available;上游 example 仍查 done → **任何执行器都要自改 state=available**(worker 已改)。
- 结果回收:lava_callback.py:525 硬编码 `kernelci.runtime.lava.Callback`;core 的 `kernelci/runtime/pull_labs.py` 有 `Callback`(2025 Collabora,协议解析齐全)**但无 get_meta**(全 core 只有 lava.py:104 有)→ 上游还接不回来,worker 的 POST body 格式对也没用;send_kcidb.py:818 还挂 TODO「distinct pull-labs prepared state」。
- 与 tuxrun 无关:这些是上游 pipeline future work;PR 描述里应如实说明「结果闭环待上游接线」。

## 7. 环境与网络实测记录(证据)

- GitHub:api.github.com 429(用户已知);`git clone https://github.com/Linaro/tuxrun` 与 codeload `Linaro/tuxrun`(14 字节 404)均失败 → **仓库已迁 kernelci/tuxrun**(master);raw.githubusercontent.com、codeload kernelci/tuxrun(319KB)、tuxlava(125KB)可用。
- 本机有 docker(daemon 通)、qemu-system-riscv64、mkfs.ext4;无 podman/lava-run。
- tuxrun pip 装成功;`--list-tests/--list-devices` 纯本地可用。**未验证**:docker pull linaro/tuxrun-dispatcher:latest 大小/可用性;QEMU guest 内 KVM 全链路;nfsroot tar.xz 直接 boot(均需实跑,规则禁止)。

## 8. 留给综合代理的关键判断/数字

1. 「为什么不能外包」的答案=可外包,但净省 ~300 行/30–40%,主要消灭 PTY+烘焙+guest 驱动;执行器之外的协议/健壮性 ~300 行两边相同,不是白赚。
2. 切换前置(均未就绪):tuxlava 无 kselftest-riscv(126 类里无;--list-tests 实测);KVM insmod/子集/H 扩展无 CLI 表达;上游 example 仍 state=done+input() 暂停。
3. 长期待办 §8「tuxrun 装好后评估换 example 形态」成立,但推荐落点=worker 内换执行器(方案 A)或提交改好的 example(方案 B),并同 PR 给 tuxlava 提 kselftest-riscv。
4. 引用锚点:qemu-riscv64 device=tuxlava/devices/qemu.py:514;cpu/machine 参数覆盖=qemu.py:131–132;kselftest-kvm=tuxlava/tests/kselftest.py:407;dispatcher 镜像=argparse.py:407–409 + Dockerfile.tuxrun-dispatcher;worker 可删区间见 §4 表。
5. 不确定项全部标注「未验证」,综合时勿当结论引用;若综合代理决定实跑,最小实验=本机 docker pull dispatcher 镜像 + 用 kernelci storage 现成 artifact 跑一次 baseline(qemu-riscv64,`--tests boot` 免测? 注:tuxrun 无 boot 测试类,基线即无 --tests 的纯 boot,退出码判成败)。
