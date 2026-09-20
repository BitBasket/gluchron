#!/bin/sh
set -eu

# Collect GnuPG into /out using the distroless layout (/usr/bin, /usr/lib).
# Never ship ld-linux or libc: COPY would replace the PHP image's loader with
# a relative symlink that does not resolve (/lib64 -> usr/lib).
mkdir -p /out/usr/bin /out/usr/lib
for bin in gpg gpgconf gpg-agent dirmngr gpg-connect-agent; do
    if [ -x "/usr/bin/$bin" ]; then
        cp -a "/usr/bin/$bin" /out/usr/bin/
    fi
done
if [ -d /usr/lib/gnupg ]; then
    cp -a /usr/lib/gnupg /out/usr/lib/
fi

ldd_paths() {
    ldd "$1" 2>/dev/null | awk '/=>/ { if ($3 ~ /^\//) print $3 } $1 ~ /^\// { print $1 }' || true
}

skip_lib() {
    case "$1" in
        ld-linux*|libc.so*|libm.so*|libpthread.so*|libdl.so*|librt.so*|libresolv.so*|libgcc_s.so*|libcrypt.so*|libnss_*|libthread_db.so*)
            return 0
            ;;
    esac
    return 1
}

{
    for bin in /out/usr/bin/*; do
        ldd_paths "$bin"
    done
    if [ -d /usr/lib/gnupg ]; then
        find /usr/lib/gnupg -type f | while read -r helper; do
            ldd_paths "$helper"
        done
    fi
} | sort -u | while read -r lib; do
    name=$(basename "$lib")
    if skip_lib "$name"; then
        continue
    fi
    # Dereference so we copy the real .so, not a relative symlink.
    cp -L "$lib" "/out/usr/lib/$name"
done
