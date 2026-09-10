# Cross-compile toolchain for the Akai Force (ARM 32-bit hard-float).
#
# Force binaries are: ELF 32-bit LSB, ARM EABI5, interpreter
# /lib/ld-linux-armhf.so.3, built "for GNU/Linux 3.2.0". Euclidier &co. show a
# max requirement of GLIBC_2.4 / GLIBCXX_3.4.21 (≈ GCC 5.1).
#
# We use Debian Buster (glibc 2.28, GCC 8) as a conservative host and STATICALLY
# link libstdc++ / libgcc so the newer compiler's C++ runtime never has to match
# the device's. libasound / libc / libpthread stay dynamic and resolve on-device.
#
# If a glibc-version link error ever shows up, drop to an armhf-native build
# instead (Raspberry Pi OS 32-bit, or gcc on the Force itself over SSH) — see
# DESIGN.md "Toolchain".
FROM debian:buster

RUN sed -i 's|deb.debian.org|archive.debian.org|g; /security.debian.org/d; /-updates/d' /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends \
        g++-arm-linux-gnueabihf \
        binutils-arm-linux-gnueabihf \
        make file ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
