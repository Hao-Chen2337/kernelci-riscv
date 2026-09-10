# Runbook(运行手册)

> 所有命令在仓库根用 `./run.sh` 执行。

## 环境

- docker + `pip install tuxrun`
- 档位 B(本地全栈)还需在 `kernelci-pipeline/.env` 里填 `KCI_API_TOKEN`
  (本地 API admin JWT,**永不提交**)
- 已装 tuxlava 需一次性打补丁(riscv kselftest 支持):

```bash
cd ~/.local/lib/python3.10/site-packages && patch -p1 < /home/hao/kernelci-riscv/config/tuxlava-kselftest-riscv.patch
```

## 命令

| 命令 | 干什么 |
|---|---|
| `./run.sh setup` | 克隆 core/api/pipeline + 打 PR1/bullseye/nginx 补丁(已含则跳过)+ validate_yaml |
| `./run.sh fetch [--job 名] [--kvm] [--kvm-full]` | 档位 A:抓生产最新 riscv 构建,本地 tuxrun 复跑;构件落 `work/downloads/` |
| `./run.sh stack [--seed]` | 档位 B:起本地全栈(api/db/redis/storage/ssh + 构件服务 + 真实回调 + 官方调度器);`--seed` 派单(可用 `SEED_*` 环境变量覆盖) |
| `./run.sh worker [--once]` | 接单执行回传;`--once` 处理完现存单就退;未投结果持久化,下次只重投不重跑 |
| `./run.sh report` | 最近 baseline/kselftest 节点状态 |
| `./run.sh verify` | 全部门禁:validate_yaml + verify-lava-body + verify-worker-guards + ruff |
| `./run.sh drift` / `./run.sh trend` | 配置漂移 / 回归通过率 |
| `./run.sh stop` | 停整个本地栈(含 docker compose API 栈;数据在 volume) |

## 注意

- **三种 worker 模式 = 一个文件**(差异只是参数):一次性闭环
  (`stack --seed` + `worker --once`)、常驻 worker(积累历史)、
  远程官方(`--api-url` + token)。
- **KVM**:默认 8 项白名单;worker 把 modules.tar.xz 烤进 rootfs 的
  `/lib/modules`,开机加载 kvm.ko,`/dev/kvm` 真实可用。seed 内核
  (`work/serve/Image`)必须与 `SEED_MODULES_URL` **同一构建**。
  `--kvm-full` 跑全集——超时如实报 incomplete,绝不报 fail。
- **fetch** 默认 gcc-14 构建;clang riscv 无 kselftest(上游缺口)。

## 已知坑

- api.kernelci.org 时通时断(直连可用)。
- storage.kernelci.org 有时把 144MB rootfs 限速到 KB/s;绕法:worker 加
  `--rootfs http://127.0.0.1:8999/trixie-full.rootfs.tar.xz`(本地镜像)。
- 下载截断 → 如实报 Infrastructure,重跑。
- 重装 tuxrun 后需重打 tuxlava 补丁。
- worker 默认 `--since` 只接当天新单,不重放历史。
- 本地 drift 需库里 ≥2 个 done/pass 的 kbuild 节点;否则用
  `--older-config/--newer-config` 离线比较。
