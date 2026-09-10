# RISC-V KernelCI 实战经验总结

> 这份文档记录了一次完整的「给 RISC-V 建 KernelCI 自动化测试」实战，包含目标、路线、踩过的每一个坑和解法。给下一个接手的人（或下一个 AI 会话）看，能少走 90% 的弯路。

---

## 一、项目是什么（5 句话讲清）

1. 源头是 [riscv-admin/dev-partners#49](https://github.com/riscv-admin/dev-partners/issues/49)，一份 KernelCI 的 **SOW（工作说明书）**，招人来做。
2. **要做什么**：给 RISC-V 建一套「自动编译内核 → 自动跑测试 → 自动抓回归」的持续测试系统。
3. **测什么**：Linux 内核自带的 **selftests**（在 `tools/testing/selftests/` 里），不用自己写测试。
4. **Phase 1** = 跑通脚本 + 容器化 + 开 tracking issue；**Phase 2** = 回归对比、配置漂移检测、编译矩阵、KVM 测试。
5. 已有两个实习生在做：xjysiiau（QEMU 侧，做得最完整）、Acidmoon（真机 K1，无 H 扩展）。

**核心认知**：这个项目的产出不是「测试全绿」，而是「**如实记录不同内核/芯片/工具链下的差异**」。一个 not ok 往往是结论（硬件不支持某扩展），不是失败。

---

## 二、完整技术路线（实际走过的路）

```
1. 读 issue，搞清目标
2. WSL(x86) + QEMU 模拟出一台 riscv64 虚拟机（跑通流程用）
3. 升级 QEMU 6.2 → 8.2（6.2 不支持 vector，源码编译解决）
4. 打通 WSL → K3 真机的 stunnel 隧道
5. K3 真机（X100, 有 Vector + H 扩展）跑同一套测试
6. 做成 riscv64 Docker 容器（可复现）
7. 补 Phase 2：回归趋势表、配置漂移检测、KVM 测试、CI
```

**三个环境的分工**（容易混淆，务必记牢）：

| 环境 | 角色 | 跑什么 |
|---|---|---|
| QEMU（软件模拟） | 快速验证流程 | 裸机脚本 run-tests.sh |
| K3 真机 | 真实验证 | 裸机脚本 + 容器 |
| Docker 容器 | 环境封装 | 寄生在真机上，只固定「工具链+脚本」 |

---

## 三、踩坑清单（每个坑 + 解法）

### 坑 1：QEMU 6.2 不支持 `-cpu max` 和 Vector
- **现象**：`-cpu max` 报 `unable to find CPU model 'max'`；`-cpu rv64,v=true` 报 `Property 'v' not found`。
- **原因**：Ubuntu 22.04 的 QEMU 是 6.2，太老；`max` 模型是 QEMU 8.0 才有的。
- **解法**：源码编译 QEMU 8.2（见 `build-qemu.sh`，只编 `riscv64-softmmu`，快）。

### 坑 2：ruyi 的 QEMU 11 缺库
- **现象**：`error while loading shared libraries: libsnappy.so.1`。
- **原因**：QEMU 11 要 glibc 2.38，Ubuntu 22.04 只有 2.35；**glibc 不能升**（会搞坏系统）。
- **解法**：别用预编译的 QEMU 11，源码编译 QEMU 8.2（链接系统自己的 glibc）。

### 坑 3：`-cpu max` 导致内核起不来
- **现象**：OpenSBI 打印完就退出，没有内核输出。
- **原因**：`max` 带 `h`（超管）等一堆扩展，和内核不兼容。
- **解法**：用 `-cpu rv64,v=true`（只开 vector），或 `-cpu max,h=false`（但实测不稳定，不推荐）。

### 坑 4：selftests 编译时 `ARCH` 匹配失败
- **现象**：`make -C tools/testing/selftests/riscv` 直接 Entering→Leaving，啥都没编译。
- **原因**：riscv 的 Makefile 用 `uname -m` 判断，返回 `riscv64`，但代码只匹配精确的 `riscv`。
- **解法**：**显式传 `ARCH=riscv`**：`make ARCH=riscv -C tools/testing/selftests TARGETS=riscv install`。

### 坑 5：`run_kselftest.sh` 不存在
- **原因**：直接在子目录 make 不会生成它。
- **解法**：正确用法是 `make ... TARGETS=riscv install`，它会生成到 `kselftest_install/run_kselftest.sh`，然后 `cd kselftest_install && ./run_kselftest.sh`。

### 坑 6：磁盘满（3GB 镜像）
- **现象**：clone 内核时报 `No space left on device`。
- **原因**：debian-13 云镜像虚拟盘只有 3GB，内核源码 1.5GB+ 就爆了。
- **解法**：加一块独立数据盘（`qemu-img create` 20G），挂载到 `/kci`，内核源码放数据盘。

### 坑 7：cloud-init 只跑一次
- **现象**：改了 seed 密码，但虚拟机里登录还是旧密码/进不去。
- **原因**：cloud 镜像的 cloud-init **一辈子只初始化一次**，之后再改 seed 不生效。
- **解法**：绕过 cloud-init，直接挂载镜像改 `/etc/shadow`（见 `reset-vm-password.sh`）。

### 坑 8：sshd 服务名
- **现象**：`systemctl restart ssh` 和 `sshd` 都报 not found。
- **原因**：Debian 里服务名是 **`ssh`**（`sshd` 只是 alias），而且前提是 openssh-server 装好了。
- **解法**：先 `apt install openssh-server`，再 `systemctl restart ssh`。

### 坑 9：stunnel 占用 2222 端口
- **现象**：PowerShell 里 `ssh -p 2222 localhost` 连到 stunnel（不是 QEMU 虚拟机）。
- **原因**：Windows 的 stunnel 监听 `127.0.0.1:2222`，和 QEMU 的 hostfwd 撞端口。
- **解法**：QEMU 用 2222 时，K3 隧道用 **2223**，错开；分清「Windows 的 localhost」和「WSL 的 localhost」是两个命名空间。

### 坑 10：连 K3 的 stunnel 隧道
- **真相**：K3 是 `bianbu@8aaa88a59e96940c019fd62b65790a76.gdriscv.com:2222`（TLS 包装的，直接 ssh 会被拒）。
- **配置**（Windows 的 `D:\APP\stunnel\config\stunnel.conf`）：
  ```
  [spacemit-ssh]
  client=yes
  accept = 127.0.0.1:2222
  connect = 8aaa88a59e96940c019fd62b65790a76.gdriscv.com:2222
  ```
- **WSL 复刻**：装 `stunnel4`，写同样的配置（accept 改 2223），见 `k3-tunnel.sh`。
- **密钥**：Windows 的 `~/.ssh/ed25519_K3` 要复制到 WSL 的 `~/.ssh/`。

### 坑 11：git clone 内核巨慢
- **现象**：K3 上 clone git.kernel.org 只有 10 KiB/s。
- **解法**：改用国内 tar 包镜像，单文件下载快几十倍：
  - 阿里云：`https://mirrors.aliyun.com/linux-kernel/v6.x/linux-6.18.tar.xz`（154MB）

### 坑 12：docker 拉 riscv64 镜像报 `no matching manifest`
- **现象**：`FROM debian:bookworm` 在 riscv64 上报 `no matching manifest for linux/riscv64`。
- **原因**：国内加速器（daocloud 等）不缓存 riscv64 架构。
- **解法**：用明确 riscv64 的镜像标签 `riscv64/ubuntu:22.04`；加速器配 `docker.1ms.run` 或 `docker.m.daocloud.io`。

### 坑 13：sudo 的 HOME 变 /root
- **现象**：`sudo bash script.sh` 里 `$HOME` 变成 `/root`，找不到用户目录的文件。
- **解法**：脚本里用 `SUDO_USER` 回退到真实用户 home，或显式传 `WORKDIR=...`。

### 坑 14：sudo 在管道里读不到密码
- **现象**：脚本里 `sudo xxx | tee log` 报 `Authentication failed`。
- **原因**：sudo 的 stdin 被管道占了，没法交互输密码。
- **解法**：**整个脚本用 sudo 跑**（`sudo bash script.sh`），脚本内部不再 sudo。

### 坑 15：KVM selftests 没有 `run_tests.sh`
- **现象**：`./run_tests.sh: No such file or directory`。
- **原因**：KVM selftests 编译出的是一个个测试**二进制**（kvm_page_table_test 等），不是脚本。
- **解法**：直接运行编译出的二进制（`find` 找出 executable 文件逐个跑），别找 run_tests.sh。

### 坑 16：KVM selftests 官方默认 45 秒超时
- **现象**：perf/stress 测试大量 exit=124（超时）。
- **原因**：内核 kselftest 框架默认 `kselftest_default_timeout=45`（`runner.sh` 里写死），KVM 的 settings 目录是空的、没单独设。
- **结论**：**45 秒就是标准**，perf/stress 超时是预期，不是 bug。别自作主张加长到 600 秒（实测 steal_time/kvm_page_table_test 给 10 分钟也卡死，是死等不是慢）。

### 坑 17：riscv64 KVM 不成熟（卡死/SKIP/漂移）
- `steal_time`、`kvm_page_table_test` → **死等卡死**（等一个 riscv64 上不来的事件）。
- `irqfd_test` → SKIP（`kvm_arch_has_default_irqchip()` 不满足，riscv64 无默认 irqchip）。
- `get-reg-list` → **版本漂移**（内核 6.18.3 比测试清单新，`aia: There are 2 new registers`）。
- **定性**：这些是「riscv64 KVM 成熟度缺口」，是能反馈上游的发现，不是你的环境问题。

### 坑 18：tar/scp 传输丢失脚本执行权限
- **现象**：传过去的脚本 `./run-tests.sh` 报 `Permission denied`。
- **原因**：tar 打包没保留可执行位（x 位）。
- **解法**：传完 `chmod +x *.sh` 补上。

### 坑 19：时间快一天 —— chrony 配置被剥掉了 NTP 源
- **现象**：`date` 显示比真实时间快一天（trend.md 记录日期跟着错）。
- **根因（已查实）**：`/etc/chrony/chrony.conf` 被某个初始化脚本覆盖成了 129 字节极简版，**丢了 `sourcedir` 指令** → chrony 不加载任何 NTP 源（`chronyc sources` 空列表、`chronyc tracking` 显示 `Not synchronised`、Reference ID 全 0）→ 时钟自由漂移一整天。文件权限还是 `0777`（脚本写的，不是包管理器装的）。WSL 和 K3 是同一镜像，**两台都中招**。
- **排查命令**：
  - `chronyc sources -v`（源列表为空 = 没配源）
  - `chronyc tracking`（Not synchronised）
  - `cat /etc/chrony/chrony.conf`（确认有没有 `pool`/`sourcedir`）
- **解法**：往 chrony.conf **追加**国内源（别覆盖原有配置），重启并强制同步：
  ```bash
  sudo bash -c 'echo -e "pool ntp.aliyun.com iburst\npool ntp.tencent.com iburst" >> /etc/chrony/chrony.conf'
  sudo systemctl restart chrony
  sudo chronyc makestep
  date    # 确认显示正确日期
  ```
  顺手 `sudo chmod 644 /etc/chrony/chrony.conf` 把 0777 权限修掉。
- **验证真实日期**：本机时钟不可信时，用外部服务器 HTTP `Date` 头交叉验证：
  `curl -sI https://www.qq.com | grep -i date`
- **备注**：趋势表日期只影响观感，**相对顺序才是关键**；NTP 实在连不上就接受。

### 坑 20：ed25519_github 密钥 GitHub 不认
- **现象**：push 时报 `Permission denied (publickey)`。
- **原因**：本地 ed25519_github 公钥没加到 GitHub 账号（或不是 GitHub 上配的那把）。
- **解法**：要么把公钥加到 GitHub Settings → SSH keys；要么改用 HTTPS + Personal Access Token（push 时 token 当密码）。

---

## 四、关键知识点（原理，理解了就不慌）

### 1. QEMU / 真机 / 容器 三层关系
- **QEMU** = 用软件在 x86 上「捏」出一台假 riscv64 机器（含假内核），慢但能跑流程。
- **真机** = 真实芯片（K3 的 X100）。
- **容器** = 不是机器！它**寄生在宿主机上，共享宿主机的内核**，只封装「工具链+脚本+依赖」这一层。
- 所以：**容器保证「怎么测」一致；「测出什么」由宿主机内核+芯片决定**。

### 2. 容器固定什么、固定不了什么
```
容器固定：工具链、依赖、脚本（上层，可复现）
容器管不了：宿主机内核版本、芯片及其扩展（下层，被测对象）
```
selftests 测的恰恰是下层，所以换内核/换芯片，结果就不同——**这正是 KernelCI 的价值**（比差异）。

### 3. 串口 vs SSH
- **串口** = 板子的「显示器」，看开机/崩溃日志，日志会刷屏，不适合干活。
- **SSH** = 干净的远程登录，传文件、跑脚本都用它。
- 云实例/虚拟机没有物理串口，靠 SSH + dmesg/journalctl。

### 4. kselftest 的正确姿势
```bash
make ARCH=riscv headers                                    # 生成内核头文件
make ARCH=riscv -C tools/testing/selftests TARGETS=riscv install  # 编译+安装
cd tools/testing/selftests/kselftest_install
./run_kselftest.sh                                          # 跑，TAP 格式输出
```
- `ARCH=riscv` 必须显式传（否则 uname -m 返回 riscv64 匹配不上）
- 统计时 `grep '^ok '` 只匹配顶层测试行（子测试行带 `# ` 前缀）

### 5. ISA 扩展速查
- `v` = Vector（RVV 1.0），`h` = Hypervisor，`j/zpm` = 指针掩码
- K3 的 X100：有 v、h，**无 zpm**（所以 pointer_masking 测试跳过是预期的）
- K1（Acidmoon 的板子）：无 h、无 zpm（所以 KVM 做不了）
- QEMU `-cpu rv64,v=true` 只开 vector；`max` 开一堆但不稳定

### 6. 回归趋势表（KernelCI 的灵魂）
每次跑完把结果追加进 `trend.md`，形成历史通过率趋势——这样「哪天变 Fail 了」一眼可见。这是回归测试的核心，不是「跑一次全绿」。

---

## 五、环境配置速查

| 项 | 值 |
|---|---|
| K3 连接 | `ssh -p 2223 bianbu@localhost`（走 stunnel 隧道，密钥 ed25519_K3） |
| K3 架构 | riscv64, 8×X100 + 8×A100, 32GB, Bianbu 4.0, 内核 6.18.3, 有 /dev/kvm |
| QEMU 启动 | `qemu-system-riscv64 -machine virt -m 4G -smp 8 -cpu rv64,v=true -bios default -kernel <Image> -append "root=/dev/vda1 rw console=ttyS0" -drive file=<qcow2> -netdev user,id=net0,hostfwd=tcp::2222-:22 -nographic` |
| QEMU 登录 | `ssh -p 2222 root@localhost`，密码 riscv |
| 内核源码 | K3 上 `/home/bianbu/kci/linux`（tar 包解压） |
| 项目仓库 | WSL 上 `/home/hao/test/kernelci-riscv/` |

---

## 六、项目当前状态 & 下一步

**已完成**：
- QEMU + K3 真机跑通 selftests（7 过 1 跳过）
- riscv64 Docker 容器化（`riscv64/ubuntu:22.04` 基础镜像）
- 回归趋势表、配置漂移检测、KVM 测试脚本、CI workflow（全部验证过）
- **KVM 真机验证**：核心 3 PASS（set_memory_region / kvm_create_max_vcpus / kvm_binary_stats）→ K3 的 Hypervisor 可用；get-reg-list 版本漂移、irqfd SKIP、perf/stress 超时 = riscv64 KVM 成熟度缺口
- 全英文化：文件注释 + commit message + README 全英文
- 仓库整理：6 个核心文件，辅助脚本分离到 `~/kernelci-tools/`

**KVM 最终结论**：
> K3（X100，有 H 扩展）真机 KVM 验证：核心功能 3 项 PASS，证明 Hypervisor 可用；高级特性（steal_time、页表压力、中断等）多数超时或 SKIP，反映 riscv64 KVM 上游成熟度有限。这是 issue #49 里没人有的数据（K1 无 H 做不了，QEMU 不算真机）。

**待做**：
1. push 到 GitHub（卡在认证：ed25519_github 密钥 GitHub 不认，需配 HTTPS+Token 或重新加 SSH key）
2. 回帖 issue #49（附仓库链接 + KVM 发现）
3. 自托管 runner 部署（K3 装 runner，接 ci.yml）
4. 编译矩阵（GCC/Clang）
5. Phase 3：往 KernelCI 上游提 PR（最难，耗在和 maintainer 拉扯）

**竞争定位**：K3 有 H 扩展 + 新内核 → 能做 KVM 真机测试和完整 selftests，这是两位实习生（K1 无 H、内核老）都做不了的，是你的独有优势。

**目录结构（最终）**：
```
K3:
├── kernelci-riscv/    主仓库（6 文件全英文，main 分支，要 push 的）
│   ├── run-tests.sh / config-drift-check.sh / run-kvm-tests.sh
│   ├── Dockerfile / README.md / .github/workflows/ci.yml
└── kernelci-tools/    辅助工具（不进仓库）
    ├── boot-riscv-vm.sh / build-qemu.sh / k3-tunnel.sh / reset-vm-password.sh
    └── RISC-V-KernelCI-实战经验总结.md / README.md
```

> ⚠️ 上面目录结构已过时（2026-08-27 会话后）。当前结构见下方补充。

---

## 2026-08-27 会话补充（换 session 交接）

### 本次做了什么

- **仓库整理**：`~/kernelci-tools/` 已并入项目 → `tools/`（gitignored）；内核源码+结果在项目内 `kci/`（gitignored）；新增 `.gitignore`（tools/、kci/）、`.dockerignore`（排除 kci/ 出构建上下文）
- **脚本重构**：三个脚本统一用 `SCRIPT_DIR` 锚定仓库根；`run-tests.sh`/`run-kvm-tests.sh` 支持 `CC`（gcc/clang 编译矩阵），编译前强制重编；趋势表拆分 `docs/trend-riscv.md` + `docs/trend-kvm.md`，日期带时分秒（`date '+%F %T'`）+ Compiler 列
- **Dockerfile**：加 `sudo`、`clang`、`ENV WORKDIR=/root/kci`（容器固定工作目录=挂载点）
- **config-drift-check.sh**：精简成两态（查是否 `=y`），去掉了 WORKDIR（无用）
- **坑19 更新**：chrony.conf 被初始化脚本剥掉 sourcedir 的根因 + 修复（见上）

### 关键认知（踩过的坑）

1. **编译矩阵 make 缓存坑**：make 只要 .o 在就跳过重编 → 换 CC 必须 force-clean（`make clean` + `find -delete *.o/*.d`），否则 gcc/clang 结果互相污染、趋势表造假
2. **clang 能编 riscv selftests**（2 个无害警告）→ 矩阵可行，实测 gcc 和 clang 各 `7/1/0`
3. **SoW 认知**：P1/2 是"懂 + 产出数据"，P3 提交的是 **KernelCI 的 YAML 配置**（`test-configs.yaml` 里加 RISC-V 测试档案），**不是自己的脚本**
4. **tracking issue 开在哪**：`kernelci/kernelci-project`（不是 dev-partners）；xjysiiau 已开 #579（QEMU 侧）作先例；#49 要回帖亮 K3 KVM
5. **别人仓库观察**：实习生仓库大量 AI 堆砌；实质对比——xjysiiau 的 pointer_masking 上游发现 + QEMU 闭环流水线，其 README 明确"KVM 真机待实测"，正是你已完成（K3 H 扩展 KVM 3/3）的

### 待办（下个 session 从这里开始）

1. **git 提交 + push 到 GitHub**（认证：配 HTTPS+Token 或重新加 SSH key；git remote 还是空的）
2. **开 tracking issue**（kernelci/kernelci-project，模板在会话里已写好：标题"RISC-V KernelCI: kselftests + real-hardware KVM on Spacemit K3..."+ 正文）
3. **#49 回帖**（草稿已写好：我是 KUBUDS 实习生 + 补 K3 KVM 缺口 + 仓库/tracking 链接）
4. （可选）经验总结英文版放进 `docs/` + 加 LICENSE

### 当前仓库结构（最新）

```
kernelci-riscv/
├── run-tests.sh / run-kvm-tests.sh / config-drift-check.sh   # 3 个脚本
├── Dockerfile / README.md / .github/workflows/ci.yml
├── .gitignore (tools/, kci/) / .dockerignore (kci/, tools/, ...)
├── docs/trend-riscv.md  ✅ gcc+clang 各一行（7/1/0）
├── docs/trend-kvm.md    （第一次跑 KVM 后生成）
├── tools/               辅助脚本 + 本经验总结（gitignored）
└── kci/                 内核源码 + 日志（gitignored）
```

---

## 2026-08-31 会话补充（战略转向 + riscv64 上跑 KernelCI 的真相）

### 最大的认知转变：SoW 要的是「部署 KernelCI」，不是自写脚本

- 重读 issue #49 原文，四个阶段**全是用 KernelCI 本身**：
  - P1 = 容器化流水线跑起来 + 第一个配置被解析
  - P2 = KernelCI 执行逻辑部署 + 漂移检测 + QEMU/Spike 上测回归
  - P3 = 把 RISC-V 测试档案（YAML）PR 到上游
  - P4 = runbook + demo
- **自写脚本（run-tests.sh 那套）只是「学习期原型」，不是交付物**。别扔（可当对照验证），但定位降级。
- 上游现状（查证）：riscv 树、riscv build job、baseline boot job、K1 板子**都已有**；**缺 qemu-riscv64 平台 + riscv kselftest 测试 job** —— 这就是 P3 的真实缺口。

### 已写的 RISC-V 测试档案（3 文件 +40 行，官方校验通过）

在 `kernelci-pipeline/config/`：
1. `platforms.yaml`：加 `qemu-riscv64`（参考 qemu-arm64，cpu `rv64,v=true` 开 Vector）
2. `jobs.yaml`：加 `baseline-riscv64-qemu`（boot）+ `kselftest-riscv64`（collections: riscv，rootfs trixie-kselftest）
3. `scheduler.yaml`：两个 job 挂 `kbuild-gcc-14-riscv-node-event` + `runtime: {type: docker}` + qemu-riscv64
- 校验：`python3 tests/validate_yaml.py` → **"All yaml files are valid"**（官方工具）

### riscv64 上跑「整套 KernelCI」的真相（这轮踩出来的）

**结论：完整 docker 栈在 riscv64 上跑不了，卡死在 MongoDB。**

| 组件 | riscv64 有没有 |
|---|---|
| pipeline 镜像 | 官方只有 amd64（自己编了 riscv64 版，见下） |
| redis / nginx | ✅ apt 有原生版 |
| **MongoDB** | ❌ **全世界都没有 riscv64 版**（docker 无、apt 无、官方 tarball 无、Debian 无）——MongoDB 公司砍了 riscv64 |
- kernelci-api 后端必须用 MongoDB 存结果 → **api 栈在 riscv64 上无解**。
- **官方为什么没碰到这问题**：KernelCI 正常架构是「基础设施跑 x86/arm64 服务器，riscv64 板子当测试目标（经 LAVA）」。没人尝试「在 riscv64 机器上跑整套」，所以这个坑官方没记录过 → 你发现了它，本身是个可以写进 issue 的发现。

### 绕开 docker 的路：原生 Python 跑通执行逻辑

- 装依赖：`python3 -m venv --system-site-packages .venv-kci`（复用系统 cryptography）+ pip（阿里源）装 kernelci-core(-e) + fastapi/pydantic/jinja2/httpx/jsonschema。
- **坑**：系统 Python 是 PEP668 外部管理，必须用 venv；`kcidb` 不在任何 PyPI 源，跳过（pipeline 核心不需要）。
- 跑测试：`PYTHONPATH=pipeline:pipeline/src pytest tests/` → **60/60 全过**（scheduler 19 / patchset 25 / hw_reg_checker 16）。
- **意义**：KernelCI 执行逻辑在 riscv64 上原生跑通（Phase 2 的「execution logic deployed」有硬证据），不依赖 docker 镜像。

### 自己编 riscv64 的 pipeline 镜像（官方没有，可以自给自足）

- **关键坑（按顺序踩）**：
  1. 缺 `libffi-dev` → cffi 编译报 `ffi.h not found`（`sudo apt install libffi-dev`）
  2. 缺 gcc → `build-essential`
  3. 缺 `python3-dev` → 报 `Python.h not found`
  4. **cryptography 要 Rust**，而 22.04 的 rustc 1.58 / 24.04 的 1.75 都解析不了新版 cryptography 的 Cargo.lock → **绕法：`--no-deps` 装 kernelci-core，只装纯 Python 依赖，整个跳过 paramiko/docker/cryptography**（pipeline 核心用不到）
  5. 基础镜像换 `riscv64/ubuntu:24.04`（比 22.04 新、坑少）
- **结果**：225MB riscv64 原生镜像，`docker run` 原生跑通（架构 riscv64），容器内跑官方配置校验也通过。
- **docker compose 免 sudo 装法**：下载 `docker-compose-linux-riscv64` 到 `~/.docker/cli-plugins/docker-compose` + chmod +x，`docker compose` 直接可用（不用改系统）。

### 镜像下载难的教训（网络）

- 1ms.run 是唯一能拉 kernelci 镜像的源，但大 blob 会断（会卡死在特定层，重试能慢慢续完）；ghcr 超时；daocloud 403；网易/交大/腾讯云全挂；Docker Hub 直连被墙。
- **教训**：别死磕一个源；docker 镜像下载断点续传有效，多轮重试能拉完。

### #49 动态（重要）

- 另外两人已发技术更新：xjysiiau（QEMU pointer_masking 修复实验）、Acidmoon（Lichee Pi 3A 真机第二目标）。**你还没发帖。**
- mentor（gsterlin）说「还在确定谁牵头」，8-25 有 Dev Partners 会议。机会还开着。
- **你的独有卖点**：K3 真机 + 真 H 扩展 + KVM 3/3（xjysiiau 只有 QEMU，Acidmoon 的板子无 H）→ 赶紧回帖亮这个。

### 最终分工（别再迷路）

- **WSL（x86）**：跑整套 kernelci + QEMU riscv64 当目标 → **交 SOW 的 Phase 2**（正常架构：基础设施 x86，目标 riscv64）。
- **K3 真机**：只出 KVM 真机数据（独有亮点），不跑整套。
- 已打好 `kci-workspace.tar.gz`（23M，排除无用的 venv/kci），scp 到 WSL 后解压即可继续。

### 待办（下个 session）

1. **#49 回帖**（赶紧发：K3 KVM 3/3 + 链接，别被另外两人甩下）
2. WSL 上：起 stunnel → scp 拉包 → docker compose 起 kernelci → QEMU riscv64 跑 Phase 2
3. 之后 P3：把 3 个 yaml 的改动 PR 上游
