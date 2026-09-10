# riscv64 test container: docker build on K3 pulls the riscv64 base image
FROM riscv64/ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR=/root/kci

# deps for building kernel selftests
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo clang gcc make git wget xz-utils ca-certificates \
    bison flex bc libelf-dev libssl-dev python3 rsync \
    && rm -rf /var/lib/apt/lists/*

# bake the test script into the image
COPY run-tests.sh /usr/local/bin/run-tests.sh
RUN chmod +x /usr/local/bin/run-tests.sh

WORKDIR /root
ENTRYPOINT ["/usr/local/bin/run-tests.sh"]
