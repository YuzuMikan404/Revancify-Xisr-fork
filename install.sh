#!/usr/bin/bash
[ -z "$TERMUX_VERSION" ] && echo -e "Termux not detected !!" && exit 1
BIN="$PREFIX/bin/xisr"
curl -sL "https://github.com/YuzuMikan404/Revancify-Xisr-fork/raw/refs/heads/main/xisr" -o "$BIN"
[ -e "$BIN" ] && chmod +x "$BIN" && "$BIN"
