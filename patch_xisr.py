#!/usr/bin/env python3
"""
patch_xisr.py
=============
アップストリームの `xisr` スクリプトをfork用に自動パッチする。

パッチ内容:
  1. リポジトリURLをfork版に置換
  2. wget の -c / --continue オプションを除去し、直前に rm -f を挿入
  3. ZIP整合性チェック (unzip -t) を if 条件に追加

各パッチは冪等（何度適用しても結果が変わらない）。
"""

import re
import sys
import shutil
import tempfile
from pathlib import Path

# ────────────────────────────────────────────
# 設定
# ────────────────────────────────────────────
UPSTREAM_API_URL  = "https://api.github.com/repos/Xisrr1/Revancify-Xisr/"
FORK_API_URL      = "https://api.github.com/repos/YuzuMikan404/Revancify-Xisr-fork/"

UPSTREAM_RAW_URL  = "https://github.com/Xisrr1/Revancify-Xisr/"
FORK_RAW_URL      = "https://github.com/YuzuMikan404/Revancify-Xisr-fork/"

TARGET_FILE       = Path("xisr")

# ────────────────────────────────────────────
# パッチ関数
# ────────────────────────────────────────────

def patch_urls(line: str) -> str:
    """パッチ1: リポジトリURLをfork版に置換。"""
    line = line.replace(UPSTREAM_API_URL, FORK_API_URL)
    line = line.replace(UPSTREAM_RAW_URL, FORK_RAW_URL)
    return line


# wget でZIPをダウンロードしている行を検出するパターン
_WGET_ZIP_RE = re.compile(r'\bwget\b')
_WGET_OPT_C_RE = re.compile(
    r'(?<!\w)--continue\b'          # --continue 形式
    r'|(?<=wget\s)-([a-zA-Z]*)c([a-zA-Z]*)'  # -c / -qc / -cq など複合形式
)

def _remove_wget_c(line: str) -> str:
    """wget から -c / --continue オプションを除去する。"""
    # --continue
    line = re.sub(r'\s--continue\b', '', line)
    # -c を含む複合オプション: -qc → -q、-c のみ → オプション自体を削除
    def _strip_c(m: re.Match) -> str:
        prefix, suffix = m.group(1) or '', m.group(2) or ''
        combined = prefix + suffix
        return ('-' + combined) if combined else ''
    line = re.sub(r'(?<=wget\s)-([a-zA-Z]*)c([a-zA-Z]*)', _strip_c, line)
    return line

def patch_wget(line: str, prev_line: str) -> tuple[str, str | None]:
    """
    パッチ2: wget ZIP ダウンロード行を修正する。
    戻り値: (修正済みの行, 直前に挿入する rm -f 行 or None)
    """
    if not (_WGET_ZIP_RE.search(line) and '.zip' in line and '-O' in line):
        return line, None

    line = _remove_wget_c(line)

    # -O "ファイル名" を取り出す（シングルクォートも考慮）
    zip_match = re.search(r'''-O\s+(['"]?)([^\s'"]+)\1''', line)
    if not zip_match:
        return line, None

    zip_file  = zip_match.group(2)
    rm_stmt   = f'rm -f "{zip_file}"'

    # 直前行にすでに同じ rm -f があれば挿入しない（冪等）
    if rm_stmt in prev_line:
        return line, None

    indent = re.match(r'(\s*)', line).group(1)
    return line, indent + rm_stmt + '\n'


# if [ -e "$TAG.zip" ] を検出するパターン（クォートの有無・空白の揺れに対応）
_ZIP_CHECK_RE = re.compile(
    r'if\s+\[\s+-e\s+["\']?\$TAG\.zip["\']?\s+\]'
)

def patch_zip_integrity(line: str) -> str:
    """
    パッチ3: if [ -e "$TAG.zip" ] に unzip -t チェックを追加する。
    すでに unzip -t が含まれていれば何もしない（冪等）。
    """
    if not _ZIP_CHECK_RE.search(line):
        return line
    if 'unzip -t' in line:
        return line  # すでに適用済み

    # ] の直後（; then の前）に && unzip -t を挿入
    line = re.sub(
        r'(\s*\])\s*(;?\s*then)',
        r'\1 && unzip -t "$TAG.zip" &>/dev/null\2',
        line
    )
    return line


# ────────────────────────────────────────────
# メイン処理
# ────────────────────────────────────────────

def apply_patches(path: Path) -> None:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    result: list[str] = []

    for line in lines:
        prev = result[-1] if result else ''

        # パッチ1: URL置換
        line = patch_urls(line)

        # パッチ2: wget 修正（必要なら rm -f 行を先に追加）
        line, rm_insert = patch_wget(line, prev)
        if rm_insert:
            result.append(rm_insert)

        # パッチ3: ZIP整合性チェック
        line = patch_zip_integrity(line)

        result.append(line)

    # アトミック書き込み（書き込み失敗で元ファイルを壊さない）
    tmp = path.with_suffix('.tmp')
    try:
        tmp.write_text(''.join(result), encoding='utf-8')
        shutil.move(str(tmp), str(path))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"ERROR: failed to write {path}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[patch_xisr] {path} patched successfully")


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET_FILE
    apply_patches(target)
