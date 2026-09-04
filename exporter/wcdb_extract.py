#!/usr/bin/env python3
"""Extract emoticon.db key via wcdb-key-tool LLDB path (skips memory scan)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WCDB_DIR = Path(os.environ.get("WCDB_DIR", Path.home() / "Desktop" / "wcdb-key-tool"))


def _load_wcdb():
    if str(WCDB_DIR) not in sys.path:
        sys.path.insert(0, str(WCDB_DIR))
    try:
        import wcdb_key_tool_macos as wcdb
    except ImportError as exc:
        raise SystemExit(f"未找到 wcdb-key-tool: {WCDB_DIR}\n请先运行 scripts/export-stickers.sh") from exc
    return wcdb


def extract(db_dir: Path, output: Path, timeout: int) -> Path:
    wcdb = _load_wcdb()
    db_files, salt_to_dbs = wcdb.collect_db_files(str(db_dir))
    if not db_files:
        raise SystemExit(f"在 {db_dir} 未找到 .db 文件")

    if output.is_file():
        try:
            with output.open(encoding="utf-8") as handle:
                existing = wcdb._strip_key_metadata(json.load(handle))
            if all(
                wcdb._get_key_info(existing, rel)
                and wcdb.verify_enc_key(
                    bytes.fromhex(wcdb._get_key_info(existing, rel)["enc_key"]),
                    page1,
                )
                for rel, _path, _size, _salt, page1 in db_files
            ):
                print(f"wxmeme: 已有有效密钥 {output}", flush=True)
                return output
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    passphrase_hex = wcdb.load_passphrase()
    if passphrase_hex:
        print("wxmeme: 使用已保存的 passphrase 派生密钥…", flush=True)
        key_map = wcdb._derive_keys_from_passphrase(bytes.fromhex(passphrase_hex), db_files, salt_to_dbs)
        if key_map:
            wcdb._save_results(db_files, salt_to_dbs, key_map, str(db_dir), str(output))
            return output

    print("wxmeme: LLDB 等待重新登录（最多 {} 秒）…".format(timeout), flush=True)
    passphrase_hex = wcdb.capture_passphrase_lldb(timeout=timeout)
    wcdb.save_passphrase(passphrase_hex)
    key_map = wcdb._derive_keys_from_passphrase(bytes.fromhex(passphrase_hex), db_files, salt_to_dbs)
    if not key_map:
        raise SystemExit("PBKDF2 派生后未能验证任何密钥")
    wcdb._save_results(db_files, salt_to_dbs, key_map, str(db_dir), str(output))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=WCDB_DIR / "all_keys.json")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    extract(args.db_dir, args.output, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
