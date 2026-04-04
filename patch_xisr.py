#!/usr/bin/env python3
"""
patch_xisr.py
=============
アップストリームの `xisr` スクリプトをfork用に自動パッチする。

パッチ内容 (xisr):
  1. リポジトリURLをfork版に置換
  2. wget の -c / --continue オプションを除去し、直前に rm -f を挿入
  3. ZIP整合性チェック (unzip -t) を if 条件に追加

パッチ内容 (modules/patch.sh):
  4. morphe CLIに --keystore-password / --keystore-entry-alias を追加
  5. revanced CLIに --keystore-password / --keystore-entry-alias を追加

各パッチは冪等（何度適用しても結果が変わらない）。
上流が同等のオプションを追加した場合は自動的にスキップされる。
"""

import re
import sys
import shutil
from pathlib import Path

# ────────────────────────────────────────────
# 設定
# ────────────────────────────────────────────
UPSTREAM_API_URL = "https://api.github.com/repos/Xisrr1/Revancify-Xisr/"
FORK_API_URL     = "https://api.github.com/repos/YuzuMikan404/Revancify-Xisr-fork/"

UPSTREAM_RAW_URL = "https://github.com/Xisrr1/Revancify-Xisr/"
FORK_RAW_URL     = "https://github.com/YuzuMikan404/Revancify-Xisr-fork/"

TARGET_FILE    = Path("xisr")
PATCH_SH_FILE  = Path("modules/patch.sh")

# morphe keystore 認証情報（Morphe CLIのデフォルト）
MORPHE_KS_PASSWORD = ""
MORPHE_KS_ALIAS    = "Morphe Key"

# revanced keystore 認証情報（ReVanced CLIのデフォルト）
REVANCED_KS_PASSWORD = ""
REVANCED_KS_ALIAS    = "ReVanced Key"

# ────────────────────────────────────────────
# xisr パッチ関数
# ────────────────────────────────────────────

def patch_urls(line: str) -> str:
    """パッチ1: リポジトリURLをfork版に置換。"""
    line = line.replace(UPSTREAM_API_URL, FORK_API_URL)
    line = line.replace(UPSTREAM_RAW_URL, FORK_RAW_URL)
    return line


_WGET_ZIP_RE = re.compile(r'\bwget\b')

def _remove_wget_c(line: str) -> str:
    """wget から -c / --continue オプションを除去する。"""
    line = re.sub(r'\s--continue\b', '', line)
    def _strip_c(m: re.Match) -> str:
        prefix, suffix = m.group(1) or '', m.group(2) or ''
        combined = prefix + suffix
        return ('-' + combined) if combined else ''
    line = re.sub(r'(?<=wget\s)-([a-zA-Z]*)c([a-zA-Z]*)', _strip_c, line)
    return line

def patch_wget(line: str, prev_line: str) -> tuple:
    """パッチ2: wget ZIP ダウンロード行を修正する。"""
    if not (_WGET_ZIP_RE.search(line) and '.zip' in line and '-O' in line):
        return line, None
    line = _remove_wget_c(line)
    zip_match = re.search(r"-O\s+(['\"]?)([^\s'\"]+)\1", line)
    if not zip_match:
        return line, None
    zip_file = zip_match.group(2)
    rm_stmt  = f'rm -f "{zip_file}"'
    if rm_stmt in prev_line:
        return line, None
    indent = re.match(r'(\s*)', line).group(1)
    return line, indent + rm_stmt + '\n'


_ZIP_CHECK_RE = re.compile(
    r'if\s+\[\s+-e\s+["\']?\$TAG\.zip["\']?\s+\]'
)

def patch_zip_integrity(line: str) -> str:
    """パッチ3: if [ -e "$TAG.zip" ] に unzip -t チェックを追加する。"""
    if not _ZIP_CHECK_RE.search(line):
        return line
    if 'unzip -t' in line:
        return line
    line = re.sub(
        r'(\s*\])\s*(;?\s*then)',
        r'\1 && unzip -t "$TAG.zip" &>/dev/null\2',
        line
    )
    return line


# ────────────────────────────────────────────
# patch.sh パッチ関数
# ────────────────────────────────────────────

_MORPHE_KS_RE   = re.compile(r'--keystore=.*morphe\.keystore')
_REVANCED_KS_RE = re.compile(r'--keystore=.*revanced\.keystore')

def _already_has_ks_options(lines: list, idx: int, lookahead: int = 5) -> bool:
    """
    idx行の直後 lookahead 行以内に --keystore-password または
    --keystore-entry-alias がすでにあれば True。
    上流が同等のオプションを追加した場合もここで検出してスキップ（冪等）。
    """
    for j in range(idx + 1, min(idx + 1 + lookahead, len(lines))):
        if '--keystore-password' in lines[j] or '--keystore-entry-alias' in lines[j]:
            return True
    return False

def patch_patch_sh(lines: list) -> list:
    """
    パッチ4/5: morphe / revanced の java -jar patch コマンドに
    --keystore-password と --keystore-entry-alias を追加する。

    冪等: すでにオプションが存在する場合（上流が追加した場合を含む）はスキップ。
    """
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if _MORPHE_KS_RE.search(line) and not _already_has_ks_options(lines, i):
            indent = re.match(r'(\s*)', line).group(1)
            result.append(line)
            result.append(f'{indent}--keystore-password="{MORPHE_KS_PASSWORD}" \\\n')
            result.append(f'{indent}--keystore-entry-alias="{MORPHE_KS_ALIAS}" \\\n')
            i += 1
            continue

        if _REVANCED_KS_RE.search(line) and not _already_has_ks_options(lines, i):
            indent = re.match(r'(\s*)', line).group(1)
            result.append(line)
            result.append(f'{indent}--keystore-password="{REVANCED_KS_PASSWORD}" \\\n')
            result.append(f'{indent}--keystore-entry-alias="{REVANCED_KS_ALIAS}" \\\n')
            i += 1
            continue

        result.append(line)
        i += 1

    return result


# ────────────────────────────────────────────
# 汎用アトミック書き込み
# ────────────────────────────────────────────

def write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix('.tmp')
    try:
        tmp.write_text(content, encoding='utf-8')
        shutil.move(str(tmp), str(path))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"ERROR: failed to write {path}: {e}", file=sys.stderr)
        sys.exit(1)


# ────────────────────────────────────────────
# メイン処理
# ────────────────────────────────────────────

def apply_xisr_patches(path: Path) -> None:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    result = []

    for line in lines:
        prev = result[-1] if result else ''
        line = patch_urls(line)
        line, rm_insert = patch_wget(line, prev)
        if rm_insert:
            result.append(rm_insert)
        line = patch_zip_integrity(line)
        result.append(line)

    write_atomic(path, ''.join(result))
    print(f"[patch_xisr] {path} patched successfully")


def apply_patch_sh_patches(path: Path) -> None:
    if not path.exists():
        print(f"WARN: {path} not found, skipping", file=sys.stderr)
        return

    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    result = patch_patch_sh(lines)

    if result == lines:
        print(f"[patch_xisr] {path} already up to date (skipped)")
        return

    write_atomic(path, ''.join(result))
    print(f"[patch_xisr] {path} patched successfully")


if __name__ == '__main__':
    xisr_target = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET_FILE
    apply_xisr_patches(xisr_target)
    apply_patch_sh_patches(PATCH_SH_FILE)
