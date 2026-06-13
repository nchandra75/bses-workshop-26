# Minimal userland for running Vitis HLS 2021.1 csim / cosim.
#
# The toolchain itself is NOT copied in - it is bind-mounted from the host at
# /tools/Xilinx by run-in-docker.sh. This image only provides a glibc/binutils
# era the 2021.1 tools expect: the host (Debian forky/sid, glibc 2.42) is too new
# and its .so files use .relr.dyn relocations the bundled binutils-2.26 can't
# read. ubuntu 20.04 (glibc 2.31) links cleanly.
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        libc6-dev \
        libtinfo5 \
        libncurses5 \
        libx11-6 \
        locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
