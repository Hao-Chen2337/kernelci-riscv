# RUNBOOK — 复现指南

> 目标:拿到本仓库,按档位 A 或 B 跑,得到与 docs/REPORT.md 口径一致的结果。
> 所有命令从仓库根执行。一键入口:`./run.sh`(见文末命令表)。
> ⚠️ 口径:早期"QEMU 11.1.1、9/9 全绿、6s/27s/167s"无原始日志,不采信;实测口径:
> tuxrun 容器 QEMU 11.0.2,riscv collection 10 项 9 ok / 1 not ok。

## 环境要求

- docker(跑 tuxrun dispatcher 容器与 kernelci-api 栈)
- `pip install tuxrun`(提供 `tuxrun` 与已装 tuxlava)
- 一次性:给已装 tuxlava 打本仓库补丁(档位 A/B 的 kselftest-riscv 都要):

```bash
cd ~/.local/lib/python3.10/site-packages && patch -p1 < /home/hao/kernelci-riscv/config/tuxlava-kselftest-riscv.patch
```

- 档位 B 另需:kernelci-pipeline/.env 里的 `KCI_API_TOKEN`(本地 API admin JWT,永不提交)。

## 档位 A:复现测试结果(0 个上游仓库)

```bash
./run.sh fetch                    # riscv collection,自动抓生产最新构建并 tuxrun 复跑
./run.sh fetch --kvm              # kvm 精选子集
```

实测输出(生产最新构建 = kbuild-gcc-14-riscv 节点 6aa0b795…,v7.3-rc1-474-g548b86839f7f):

- riscv collection:**10 项 9 ok / 1 not ok**(not ok = pointer_masking PMLEN constraint,TCG 限制)
- v6.18 对照:7 ok / 1 not ok(pointer_masking 51/61 SKIP)
- 下载构件与日志存 `artifacts/<node_id>/`

## 档位 B:复现完整闭环(3 个上游仓库)

```bash
./run.sh setup                    # 克隆 core/api/pipeline + 打补丁 + validate_yaml
./run.sh stack --seed             # 起 API/回调/官方调度器并派单
./run.sh worker                   # 前台接单(另一终端;命令 stack 会打印)
./run.sh report                   # 看结果:最近 baseline 节点状态
```

闭环 = 官方调度器读我们 4 个 YAML → 渲染任务书 → 建节点 → worker 接单 → tuxrun/QEMU 跑 →
LAVA body 回传真实 lava_callback(8003)→ 节点 done/pass。

## 验证套件

```bash
./run.sh verify                   # validate_yaml + 两个 verify 脚本 + ruff check
./run.sh drift                    # 配置漂移(GET,免 token,本地/生产均可)
./run.sh trend                    # 回归趋势(GET;track/watch 仅本地 API+token)
```

## 已知限制

- pointer_masking 的 PMLEN constraint 子项在 TCG 下 not ok(QEMU 模拟限制);
- 宿主 QEMU(~/qemu-install)= 8.2.0 有 rvv bug,勿用;tuxrun 容器 QEMU = 11.0.2 才是执行路径;
- 网络抖动会截断 144MB rootfs 下载 → worker 如实报 Infrastructure,重跑即可;
- Debian bullseye 已归档:setup 会自动打 config/kernelci-api-bullseye-archive.patch,
  否则 kernelci-api ssh 容器 build 失败。
