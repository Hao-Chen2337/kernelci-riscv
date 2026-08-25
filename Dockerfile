# riscv64 测试容器：在 K3 上 docker build 会自动拉 riscv64 架构的基础镜像
FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

# 编译内核 selftests 需要的依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc make git wget xz-utils ca-certificates \
    bison flex bc libelf-dev libssl-dev python3 rsync \
    && rm -rf /var/lib/apt/lists/*

# 把测试脚本塞进镜像
COPY run-tests.sh /usr/local/bin/run-tests.sh
RUN chmod +x /usr/local/bin/run-tests.sh

WORKDIR /root
ENTRYPOINT ["/usr/local/bin/run-tests.sh"]
