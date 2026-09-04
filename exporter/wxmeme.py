#!/usr/bin/env python3
"""Export the user's own WeChat sticker library in panel order."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import plistlib
import posixpath
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from wechat_crypto import (
    decrypt_emoticon_file,
    decrypt_legacy_msg_db,
    decrypt_sqlcipher4_db,
    derive_emoticon_key,
    emoticon_cdn_map_from_db,
    favorite_md5s_from_db,
    looks_like_image,
    parse_hex_key,
    sticker_md5s_from_msg_db,
    verify_emoticon_key,
)

if sys.platform == "darwin":
    from mac_seed_scan import (
        find_db_key_from_memory,
        find_emoticon_key_from_memory,
        find_encrypted_sample,
        scan_seed_candidates,
    )

HOME = Path.home()
LIBRARY = Path(os.environ.get("WXMEME_LIBRARY", HOME / "Downloads" / "wxmeme" / "library"))
PORT = int(os.environ.get("WXMEME_PORT", "8765"))

_export_status = {"done": True, "phase": "idle", "message": "", "current": 0, "total": 0}
_export_lock = threading.Lock()


def export_status_reset() -> None:
    with _export_lock:
        _export_status.update(done=False, phase="start", message="准备导出…", current=0, total=0)


def export_status_snapshot() -> dict:
    with _export_lock:
        return dict(_export_status)


def _set_export_status(**kwargs) -> None:
    with _export_lock:
        _export_status.update(kwargs)

MAGICS = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"GIF89a", "gif", "image/gif"),
    (b"GIF87a", "gif", "image/gif"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)


@dataclass
class ExportConfig:
    emoticon_key: bytes | None = None
    db_key: bytes | None = None
    msg_key: bytes | None = None
    decrypted_db: Path | None = None
    wxid: str | None = None
    seed: str | None = None
    use_cdn: bool = False
    force_fav_archive: bool = False
    sync_persist: bool = False


@dataclass
class FavEntry:
    md5: str
    cdnurl: str = ""


def wechat_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        localappdata = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
        roots.extend(
            [
                HOME / "Documents" / "WeChat Files",
                HOME / "Documents" / "xwechat_files",
                appdata / "Tencent" / "WeChat",
                localappdata / "Tencent" / "WeChat",
            ]
        )
        for base in (HOME / "Documents" / "WeChat Files", HOME / "Documents" / "xwechat_files"):
            if base.is_dir():
                for child in base.iterdir():
                    if child.is_dir() and child.name.lower().startswith("wxid_"):
                        roots.append(child)
    else:
        roots.extend(
            [
                HOME / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat",
                HOME / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files",
                HOME / "Documents/WeChat Files",
                HOME / "Documents/xwechat_files",
            ]
        )
    extra = os.environ.get("WXMEME_WECHAT_ROOT")
    if extra:
        roots.insert(0, Path(extra).expanduser())
    seen: set[str] = set()
    found: list[Path] = []
    for path in roots:
        if not path.exists():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


@dataclass
class WeChatPaths:
    library_dirs: list[Path]
    emoticon_dirs: list[Path]
    account_dirs: list[Path]
    sticker_index: dict[str, Path]


def discover_paths() -> WeChatPaths:
    library_dirs = find_library_dirs()
    account_dirs: list[Path] = []
    emoticon_dirs: list[Path] = []
    seen_accounts: set[str] = set()

    for root in wechat_roots():
        if root.name.startswith("wxid_"):
            key = str(root.resolve())
            if key not in seen_accounts:
                seen_accounts.add(key)
                account_dirs.append(root)
                for sub in ("business/emoticon", "emoticon"):
                    path = root / sub
                    if path.is_dir():
                        emoticon_dirs.append(path)
                if sys.platform == "win32":
                    for sub in (
                        "FileStorage/CustomEmotion",
                        "FileStorage/CustomEmoticon",
                        "CustomEmotion",
                    ):
                        path = root / sub
                        if path.is_dir():
                            emoticon_dirs.append(path)

        xwechat = root / "xwechat_files" if root.name != "xwechat_files" else root
        if xwechat.is_dir():
            for child in xwechat.iterdir():
                if child.is_dir() and child.name.startswith("wxid_"):
                    key = str(child.resolve())
                    if key not in seen_accounts:
                        seen_accounts.add(key)
                        account_dirs.append(child)
                        for sub in ("business/emoticon", "emoticon"):
                            path = child / sub
                            if path.is_dir():
                                emoticon_dirs.append(path)
                        if sys.platform == "win32":
                            for sub in (
                                "FileStorage/CustomEmotion",
                                "FileStorage/CustomEmoticon",
                                "CustomEmotion",
                            ):
                                path = child / sub
                                if path.is_dir():
                                    emoticon_dirs.append(path)

    sticker_index: dict[str, Path] = {}
    for library_dir in library_dirs:
        for folder in ("Persistence", "NonPersistence", "CustomEmotion"):
            base = library_dir / folder
            if not base.is_dir():
                continue
            for path in base.iterdir():
                if path.is_file() and len(path.name) == 32:
                    sticker_index.setdefault(path.name.lower(), path)

    for emo_dir in emoticon_dirs:
        for sub in ("Persist", "PersistStore"):
            base = emo_dir / sub
            if not base.is_dir():
                continue
            for shard in base.iterdir():
                if not shard.is_dir():
                    continue
                for path in shard.iterdir():
                    if path.is_file():
                        md5 = path.name.lower()
                        if len(md5) == 32:
                            sticker_index.setdefault(md5, path)
        if sys.platform == "win32" and emo_dir.is_dir():
            for path in emo_dir.iterdir():
                if path.is_file() and len(path.name) == 32:
                    sticker_index.setdefault(path.name.lower(), path)

    return WeChatPaths(
        library_dirs=library_dirs,
        emoticon_dirs=emoticon_dirs,
        account_dirs=account_dirs,
        sticker_index=sticker_index,
    )


def find_library_dirs() -> list[Path]:
    found: list[Path] = []
    for root in wechat_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if current.name == "Stickers" and "fav.archive" in filenames:
                found.append(current)
    return found


def find_emoticon_dirs() -> list[Path]:
    return discover_paths().emoticon_dirs


def uid_index(value):
    if isinstance(value, dict) and "CF$UID" in value:
        return int(value["CF$UID"])
    data = getattr(value, "data", None)
    if data is not None and value.__class__.__name__ == "UID":
        return int(data)
    return None


def load_plist(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return plistlib.load(handle)
    except Exception:
        if sys.platform != "darwin":
            raise RuntimeError(f"无法读取 {path}") from None
        converted = subprocess.run(
            ["plutil", "-convert", "xml1", "-o", "-", str(path)],
            capture_output=True,
            check=False,
        )
        if converted.returncode != 0:
            raise RuntimeError(converted.stderr.decode("utf-8", "replace") or f"无法读取 {path}")
        return plistlib.loads(converted.stdout)


def ordered_fav_entries(fav_archive: Path) -> list[FavEntry]:
    data = load_plist(fav_archive)

    def resolve(value):
        index = uid_index(value)
        return data["$objects"][index] if index is not None else value

    root = resolve(data["$top"]["root"])
    sequence = root.get("NS.objects", []) if isinstance(root, dict) else []
    entries: list[FavEntry] = []
    for item in sequence:
        obj = resolve(item)
        if not isinstance(obj, dict):
            continue
        md5 = resolve(obj.get("md5"))
        cdnurl = resolve(obj.get("cdnurl"))
        if isinstance(md5, str) and len(md5) >= 32:
            entries.append(
                FavEntry(
                    md5=md5.lower(),
                    cdnurl=str(cdnurl) if isinstance(cdnurl, str) and cdnurl.startswith("http") else "",
                )
            )
    return entries


def ordered_md5s_from_fav(fav_archive: Path) -> list[str]:
    return [entry.md5 for entry in ordered_fav_entries(fav_archive)]


def fav_archive_path(paths: WeChatPaths) -> Path | None:
    for library_dir in paths.library_dirs:
        fav = library_dir / "fav.archive"
        if fav.is_file():
            return fav
    return None


def count_persist_stickers(paths: WeChatPaths) -> int:
    seen: set[str] = set()
    for emo_dir in paths.emoticon_dirs:
        base = emo_dir / "Persist"
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and len(path.name) == 32:
                seen.add(path.name.lower())
    return len(seen)


def merge_persist_md5s(base_md5s: list[str], paths: WeChatPaths) -> list[str]:
    existing = {md5.lower() for md5 in base_md5s}
    additions: list[tuple[float, str]] = []
    for emo_dir in paths.emoticon_dirs:
        persist = emo_dir / "Persist"
        if not persist.is_dir():
            continue
        for path in persist.rglob("*"):
            if not path.is_file() or len(path.name) != 32:
                continue
            md5 = path.name.lower()
            if md5 in existing:
                continue
            additions.append((path.stat().st_mtime, md5))
            existing.add(md5)

    if not additions:
        return base_md5s

    additions.sort(key=lambda item: item[0])
    merged = list(base_md5s)
    merged.extend(md5 for _mtime, md5 in additions)
    print(
        f"wxmeme: --sync-persist 追加 {len(additions)} 个新缓存表情（顺序为近似值）",
        flush=True,
    )
    return merged


def warn_if_stale_fav_archive(
    paths: WeChatPaths,
    fav_archive: Path,
    md5_count: int,
    source_label: str,
) -> None:
    if not source_label.startswith("fav.archive"):
        return

    persist_count = count_persist_stickers(paths)
    fav_mtime = fav_archive.stat().st_mtime
    db_path = None
    db_mtime = 0.0
    for account in paths.account_dirs:
        candidate = resolve_emoticon_db(account)
        if candidate and candidate.is_file():
            db_path = candidate
            db_mtime = max(db_mtime, candidate.stat().st_mtime)
            wal = candidate.with_name(candidate.name + "-wal")
            if wal.is_file():
                db_mtime = max(db_mtime, wal.stat().st_mtime)

    stale = False
    reasons: list[str] = []
    if persist_count and abs(persist_count - md5_count) >= 3:
        stale = True
        reasons.append(f"本地 4.x 缓存 {persist_count} 个，fav.archive 仅 {md5_count} 个")
    if db_path and db_mtime > fav_mtime + 60:
        stale = True
        reasons.append("emoticon.db 比 fav.archive 更新")

    if not stale:
        return

    print("wxmeme: 警告: 当前列表来自旧版 fav.archive，与微信里增删不同步。", flush=True)
    for reason in reasons:
        print(f"  - {reason}", flush=True)
    print(
        "  建议: 提供 --db-key / --decrypted-db，或 macOS 上尝试 --auto-db-key；"
        "临时可用 --sync-persist 追加新表情。",
        flush=True,
    )


def decrypt_emoticon_db(db_path: Path, db_key: bytes) -> Path | None:
    return decrypt_sqlcipher4_db(db_path, db_key)


def load_cdn_map(config: ExportConfig, paths: WeChatPaths, decrypted_db: Path | None = None) -> dict[str, str]:
    mapping: dict[str, str] = {}

    if decrypted_db and decrypted_db.is_file():
        mapping.update(emoticon_cdn_map_from_db(decrypted_db))

    if config.db_key and not mapping:
        for account in paths.account_dirs:
            db_path = resolve_emoticon_db(account)
            if not db_path:
                continue
            decoded = decrypt_emoticon_db(db_path, config.db_key)
            if decoded:
                mapping.update(emoticon_cdn_map_from_db(decoded))

    for library_dir in paths.library_dirs:
        fav = library_dir / "fav.archive"
        if not fav.is_file():
            continue
        for entry in ordered_fav_entries(fav):
            if entry.cdnurl:
                mapping.setdefault(entry.md5, entry.cdnurl)

    return mapping


def download_cdn(url: str) -> bytes | None:
    if not url:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read()
    except Exception:
        return None


def resolve_emoticon_db(account_dir: Path) -> Path | None:
    candidate = account_dir / "db_storage" / "emoticon" / "emoticon.db"
    return candidate if candidate.is_file() else None


WCDB_KEYS_CANDIDATES = (
    HOME / "Desktop" / "wcdb-key-tool" / "all_keys.json",
    HOME / "wcdb-key-tool" / "all_keys.json",
    HOME / "Documents" / "wcdb-key-tool" / "all_keys.json",
)
EMOTICON_DB_KEY = "emoticon/emoticon.db"


def find_wcdb_keys_file(explicit: str | None) -> Path | None:
    if explicit and explicit != "auto":
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    env = os.environ.get("WXMEME_WCDB_KEYS")
    if env:
        path = Path(env).expanduser()
        return path if path.is_file() else None
    for path in WCDB_KEYS_CANDIDATES:
        if path.is_file():
            return path
    return None


def db_key_from_wcdb_keys(keys_file: Path) -> bytes | None:
    try:
        data = json.loads(keys_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    entry = data.get(EMOTICON_DB_KEY)
    if isinstance(entry, dict) and entry.get("enc_key"):
        return parse_hex_key(str(entry["enc_key"]), 32)

    for key, value in data.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        if "emoticon" in key and value.get("enc_key"):
            return parse_hex_key(str(value["enc_key"]), 32)
    return None


def decrypted_db_from_wcdb(keys_file: Path) -> Path | None:
    candidate = keys_file.parent / "decrypted" / "emoticon" / "emoticon.db"
    return candidate if candidate.is_file() else None


def load_ordered_md5s(config: ExportConfig, paths: WeChatPaths) -> tuple[list[str], str]:
    if config.decrypted_db and config.decrypted_db.is_file():
        md5s = favorite_md5s_from_db(config.decrypted_db)
        if md5s:
            return md5s, f"emoticon.db ({config.decrypted_db})"

    if not config.force_fav_archive:
        for account in paths.account_dirs:
            db_path = resolve_emoticon_db(account)
            if db_path and config.db_key:
                decoded = decrypt_emoticon_db(db_path, config.db_key)
                if decoded:
                    md5s = favorite_md5s_from_db(decoded)
                    if md5s:
                        return md5s, f"decrypted emoticon.db ({db_path})"

    fav = fav_archive_path(paths)
    if fav and fav.is_file():
        md5s = ordered_md5s_from_fav(fav)
        if md5s:
            if config.sync_persist:
                md5s = merge_persist_md5s(md5s, paths)
            warn_if_stale_fav_archive(paths, fav, len(md5s), f"fav.archive ({fav})")
            return md5s, f"fav.archive ({fav})"

    return [], "none"


def identify_bytes(data: bytes) -> tuple[str, str] | None:
    ext = looks_like_image(data)
    if not ext:
        return None
    mime = {
        "png": "image/png",
        "gif": "image/gif",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "wxgf": "application/octet-stream",
    }.get(ext, "application/octet-stream")
    return ext, mime


def identify_file(path: Path) -> tuple[str, str] | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    for magic, ext, mime in MAGICS:
        if head.startswith(magic):
            return ext, mime
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp", "image/webp"
    if head.startswith(b"wxgf"):
        return "wxgf", "application/octet-stream"
    return None


def load_sticker_bytes(
    md5: str,
    config: ExportConfig,
    paths: WeChatPaths,
    cdn_map: dict[str, str],
    cdn_cache: dict[str, tuple[bytes, str]] | None = None,
) -> tuple[bytes, str, str | None, str]:
    source = paths.sticker_index.get(md5)
    if source and source.is_file():
        identified = identify_file(source)
        if identified:
            ext, _mime = identified
            return source.read_bytes(), ext, str(source), "plain"

        if config.emoticon_key:
            decrypted = decrypt_emoticon_file(source, config.emoticon_key)
            if decrypted:
                body, ext = decrypted
                return body, ext, str(source), "decrypted"

    if config.use_cdn and cdn_cache and md5 in cdn_cache:
        body, ext = cdn_cache[md5]
        return body, ext, cdn_map.get(md5, ""), "cdn"

    if config.use_cdn and md5 in cdn_map:
        body = download_cdn(cdn_map[md5])
        identified = identify_bytes(body) if body else None
        if identified:
            ext, _mime = identified
            return body, ext, cdn_map[md5], "cdn"

    if source and source.is_file():
        return b"", "", str(source), "encrypted"
    return b"", "", None, "missing"


def prefetch_cdn_stickers(
    md5s: list[str],
    config: ExportConfig,
    paths: WeChatPaths,
    cdn_map: dict[str, str],
) -> dict[str, tuple[bytes, str]]:
    pending: list[str] = []
    for md5 in md5s:
        source = paths.sticker_index.get(md5)
        if source and source.is_file() and identify_file(source):
            continue
        if config.emoticon_key and source and source.is_file():
            decrypted = decrypt_emoticon_file(source, config.emoticon_key)
            if decrypted:
                continue
        if md5 in cdn_map:
            pending.append(md5)

    if not pending:
        return {}

    total = len(pending)
    local_plain = len(md5s) - total
    print(
        f"wxmeme: 面板共 {len(md5s)} 个，本地明文 {local_plain} 个（跳过 CDN），"
        f"需 CDN 下载 {total} 个（约 1-2 分钟）…",
        flush=True,
    )
    _set_export_status(phase="cdn", message=f"CDN 下载 0/{total}", current=0, total=total)
    cache: dict[str, tuple[bytes, str]] = {}
    workers = min(8, max(4, (os.cpu_count() or 4)))
    done = 0

    def fetch(md5: str) -> tuple[str, tuple[bytes, str] | None]:
        body = download_cdn(cdn_map[md5])
        identified = identify_bytes(body) if body else None
        if not identified:
            return md5, None
        ext, _mime = identified
        return md5, (body, ext)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, md5): md5 for md5 in pending}
        for future in as_completed(futures):
            md5, result = future.result()
            done += 1
            if result:
                cache[md5] = result
            if done == 1 or done % 20 == 0 or done == total:
                print(f"wxmeme: CDN 进度 {done}/{total}，已成功 {len(cache)}", flush=True)
                _set_export_status(
                    phase="cdn",
                    message=f"CDN 下载 {done}/{total}（成功 {len(cache)}）",
                    current=done,
                    total=total,
                )
    return cache


def resolve_auto_db_key(args: argparse.Namespace, paths: WeChatPaths) -> None:
    if sys.platform != "darwin":
        raise SystemExit("--auto-db-key 目前仅支持 macOS。")

    db_path = None
    for account in paths.account_dirs:
        candidate = resolve_emoticon_db(account)
        if candidate and candidate.is_file():
            db_path = candidate
            break
    if not db_path:
        raise SystemExit("未找到 emoticon.db，无法自动扫描 db_key。")

    key = find_db_key_from_memory(db_path, pid=args.pid)
    args.db_key = key.hex()


def resolve_auto_key(args: argparse.Namespace, paths: WeChatPaths) -> None:
    if sys.platform != "darwin":
        raise SystemExit("--auto-key 目前仅支持 macOS。")

    wxid = args.wxid or os.environ.get("WXMEME_WXID")
    if not wxid and paths.account_dirs:
        wxid = paths.account_dirs[0].name
    if not wxid:
        raise SystemExit("无法确定 wxid，请传 --wxid wxid_xxx_6075")

    sample = find_encrypted_sample(paths.sticker_index, identify_file)
    seed, key = find_emoticon_key_from_memory(wxid, sample, pid=args.pid)
    args.seed = str(seed)
    args.emoticon_key = key.hex()


def build_config(args: argparse.Namespace) -> ExportConfig:
    emoticon_key = None
    if args.emoticon_key:
        emoticon_key = parse_hex_key(args.emoticon_key, 16)
    elif args.seed:
        wxid = args.wxid or os.environ.get("WXMEME_WXID")
        if not wxid:
            accounts = discover_paths().account_dirs
            wxid = accounts[0].name if accounts else None
        if not wxid:
            raise SystemExit("使用 --seed 时需要 --wxid 或自动检测到 wxid 目录")
        emoticon_key = derive_emoticon_key(args.seed, wxid)

    db_key = parse_hex_key(args.db_key, 32) if args.db_key else None
    msg_key = parse_hex_key(args.msg_key) if args.msg_key else None
    decrypted_db = Path(args.decrypted_db).expanduser() if args.decrypted_db else None

    wcdb_keys = getattr(args, "wcdb_keys", None)
    if wcdb_keys is not None:
        keys_file = find_wcdb_keys_file(wcdb_keys)
        if not keys_file:
            raise SystemExit("未找到 wcdb-key-tool 的 all_keys.json，请先运行 scripts/export-stickers.sh")
        if not db_key:
            db_key = db_key_from_wcdb_keys(keys_file)
            if not db_key:
                raise SystemExit(f"{keys_file} 里没有 emoticon.db 的 enc_key")
        if not decrypted_db:
            decrypted_db = decrypted_db_from_wcdb(keys_file)
        print(f"wxmeme: 使用 wcdb 密钥 {keys_file}", flush=True)

    return ExportConfig(
        emoticon_key=emoticon_key,
        db_key=db_key,
        msg_key=msg_key,
        decrypted_db=decrypted_db,
        wxid=args.wxid,
        seed=args.seed,
        use_cdn=args.cdn,
        force_fav_archive=args.force_fav_archive,
        sync_persist=args.sync_persist,
    )


def export_library(config: ExportConfig, paths: WeChatPaths) -> tuple[list[dict], int, int]:
    export_status_reset()
    _set_export_status(phase="scan", message="读取表情列表…")
    LIBRARY.mkdir(parents=True, exist_ok=True)
    for old in LIBRARY.iterdir():
        if old.is_file():
            old.unlink()

    md5s, source_label = load_ordered_md5s(config, paths)
    if not md5s:
        (LIBRARY / "index.json").write_text("[]", encoding="utf-8")
        _set_export_status(done=True, phase="ready", message="完成", current=0, total=0)
        return [], 0, 0

    print(f"wxmeme: 顺序来源 {source_label}", flush=True)
    _set_export_status(message=f"顺序来源 {source_label}", total=len(md5s))

    decrypted_db = config.decrypted_db
    if not decrypted_db and config.db_key:
        for account in paths.account_dirs:
            db_path = resolve_emoticon_db(account)
            if db_path:
                decrypted_db = decrypt_emoticon_db(db_path, config.db_key)
                break

    cdn_map = load_cdn_map(config, paths, decrypted_db) if config.use_cdn else {}
    cdn_cache: dict[str, tuple[bytes, str]] = {}
    if config.use_cdn:
        print(f"wxmeme: 启用 CDN 回退（共 {len(cdn_map)} 个 CDN 链接）", flush=True)
        cdn_cache = prefetch_cdn_stickers(md5s, config, paths, cdn_map)

    print(f"wxmeme: 正在写入 {len(md5s)} 个表情到 {LIBRARY} …", flush=True)
    _set_export_status(phase="write", message=f"写入文件 0/{len(md5s)}", current=0, total=len(md5s))
    items: list[dict] = []
    skipped = 0
    for index, md5 in enumerate(md5s, start=1):
        body, ext, source, mode = load_sticker_bytes(md5, config, paths, cdn_map, cdn_cache)
        if index == 1 or index % 40 == 0 or index == len(md5s):
            _set_export_status(
                phase="write",
                message=f"写入文件 {index}/{len(md5s)}",
                current=index,
                total=len(md5s),
            )
        record = {
            "index": index,
            "md5": md5,
            "exported": False,
            "order_source": source_label,
        }
        if body and ext:
            name = f"{index:03d}.{ext}"
            dest = LIBRARY / name
            dest.write_bytes(body)
            identified = identify_bytes(body)
            mime = identified[1] if identified else "application/octet-stream"
            record.update(
                {
                    "name": name,
                    "ext": ext,
                    "mime": mime,
                    "size": len(body),
                    "exported": True,
                    "source": source or "",
                    "mode": mode,
                }
            )
        else:
            skipped += 1
            record["reason"] = mode if mode in {"encrypted", "missing"} else "missing"
        items.append(record)

    (LIBRARY / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_export_status(done=True, phase="ready", message="导出完成", current=len(items), total=len(items))
    return items, skipped, len(items)


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>wxmeme 我的表情</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 28px; font: 14px/1.5 "PingFang SC", sans-serif; background: #101010; color: #f3f3f3; }
    h1 { font-size: 22px; margin: 0 0 6px; }
    .muted { color: #8d8d8d; }
    .bar { display: flex; gap: 10px; align-items: center; margin: 18px 0 22px; flex-wrap: wrap; }
    a.btn, button { border: 0; border-radius: 8px; padding: 8px 14px; background: #07c160; color: #063; font-weight: 700; text-decoration: none; cursor: pointer; }
    button.ghost { background: #222; color: #ddd; }
    button:disabled { opacity: 0.5; cursor: wait; }
    .progress { margin: 0 0 18px; padding: 14px 16px; background: #1b1b1b; border: 1px solid #2a2a2a; border-radius: 12px; }
    .progress.hidden { display: none; }
    .progress-track { height: 6px; background: #2a2a2a; border-radius: 999px; overflow: hidden; margin-top: 10px; }
    .progress-fill { height: 100%; width: 0; background: #07c160; transition: width 0.25s ease; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 10px; }
    .card {
      background: #1b1b1b; border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden;
      aspect-ratio: 1; position: relative; display: grid; place-items: center; cursor: pointer;
    }
    .card.skip { border-style: dashed; color: #666; font-size: 12px; text-align: center; padding: 8px; cursor: default; }
    .card img { width: 100%; height: 100%; object-fit: contain; display: block; background: #252525; }
    .card .ph {
      position: absolute; inset: 0; display: grid; place-items: center; color: #555; font-size: 11px;
      pointer-events: none;
    }
    .card span { position: absolute; left: 6px; bottom: 6px; padding: 1px 6px; border-radius: 6px; background: rgba(0,0,0,.65); font-size: 11px; pointer-events: none; }
    .count { color: #07c160; font-variant-numeric: tabular-nums; font-weight: 700; }
    .toast { position: fixed; right: 18px; bottom: 18px; padding: 10px 14px; background: #222; border: 1px solid #333; border-radius: 8px; opacity: 0; transition: opacity 0.2s; pointer-events: none; }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>
  <h1>我的表情</h1>
  <p class="muted">按微信表情面板顺序导出。点击表情可保存到下载目录。</p>
  <div id="progress" class="progress hidden">
    <div id="progressText">正在导出…</div>
    <div class="progress-track"><div id="progressFill" class="progress-fill"></div></div>
  </div>
  <div class="bar">
    <span>面板 <span class="count" id="total">0</span> 个，可导出 <span class="count" id="count">0</span> 个</span>
    <button class="btn" id="zipBtn">打包下载 ZIP</button>
    <button class="ghost" id="reload">重新扫描</button>
  </div>
  <div class="grid" id="grid"></div>
  <div id="toast" class="toast"></div>
  <script>
    const grid = document.getElementById("grid");
    const progressEl = document.getElementById("progress");
    const progressText = document.getElementById("progressText");
    const progressFill = document.getElementById("progressFill");
    const toastEl = document.getElementById("toast");
    let toastTimer = null;

    function showToast(msg) {
      toastEl.textContent = msg;
      toastEl.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
    }

    function hasNativeApi() {
      return window.pywebview && window.pywebview.api;
    }

    async function downloadSticker(name) {
      if (hasNativeApi()) {
        const r = await window.pywebview.api.save_sticker(name);
        showToast(r.ok ? "已保存：" + r.path.split("/").pop() : (r.error || "保存失败"));
        return;
      }
      const resp = await fetch("/library/" + encodeURIComponent(name));
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    }

    async function downloadZip() {
      const btn = document.getElementById("zipBtn");
      btn.disabled = true;
      try {
        if (hasNativeApi()) {
          showToast("正在打包…");
          const r = await window.pywebview.api.save_zip();
          showToast(r.ok ? "ZIP 已保存" : (r.error || "打包失败"));
          return;
        }
        const resp = await fetch("/zip");
        const blob = await resp.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "wxmeme-stickers.zip";
        a.click();
        URL.revokeObjectURL(a.href);
      } finally {
        btn.disabled = false;
      }
    }

    function renderCard(item, eager) {
      const idx = String(item.index).padStart(3, "0");
      if (!item.exported) {
        const el = document.createElement("div");
        el.className = "card skip";
        el.innerHTML = `<span>${idx}</span>${item.reason === "encrypted" ? "需密钥解密" : "缺失"}`;
        return el;
      }
      const el = document.createElement("div");
      el.className = "card";
      el.title = "点击保存 " + item.name;
      const lazy = eager ? "" : ' loading="lazy"';
      el.innerHTML = `<div class="ph">加载中</div><img src="/library/${item.name}" alt="" decoding="async"${lazy}><span>${idx} · ${item.ext}</span>`;
      const img = el.querySelector("img");
      const ph = el.querySelector(".ph");
      img.onload = () => ph?.remove();
      img.onerror = () => { if (ph) ph.textContent = "加载失败"; };
      el.onclick = () => downloadSticker(item.name);
      return el;
    }

    async function loadGrid() {
      const items = await (await fetch("/api/list")).json();
      const exported = items.filter(item => item.exported);
      document.getElementById("total").textContent = items.length;
      document.getElementById("count").textContent = exported.length;
      grid.replaceChildren();
      const batch = 48;
      let i = 0;
      function appendBatch() {
        const frag = document.createDocumentFragment();
        const end = Math.min(i + batch, items.length);
        for (; i < end; i += 1) frag.appendChild(renderCard(items[i], i < 96));
        grid.appendChild(frag);
        if (i < items.length) requestAnimationFrame(appendBatch);
      }
      appendBatch();
    }

    async function pollStatus() {
      const s = await (await fetch("/api/status")).json();
      if (!s.done) {
        progressEl.classList.remove("hidden");
        progressText.textContent = s.message || "正在导出…";
        progressFill.style.width = s.total > 0 ? ((100 * s.current / s.total).toFixed(1) + "%") : "8%";
        setTimeout(pollStatus, 700);
        return;
      }
      progressEl.classList.add("hidden");
      await loadGrid();
    }

    document.getElementById("zipBtn").onclick = downloadZip;
    document.getElementById("reload").onclick = async () => {
      progressEl.classList.remove("hidden");
      progressText.textContent = "重新扫描…";
      await fetch("/api/rescan", { method: "POST" });
      await pollStatus();
    };
    pollStatus();
  </script>
</body>
</html>
"""


def build_stickers_zip() -> Path:
    items = json.loads((LIBRARY / "index.json").read_text(encoding="utf-8")) if (LIBRARY / "index.json").exists() else []
    zip_path = LIBRARY.parent / "wxmeme-stickers.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if not item.get("exported"):
                continue
            path = LIBRARY / item["name"]
            if path.is_file():
                zf.write(path, item["name"])
    return zip_path


class Handler(http.server.SimpleHTTPRequestHandler):
    config: ExportConfig = ExportConfig()
    paths: WeChatPaths | None = None

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        sys.stdout.write("wxmeme: " + (format % args) + "\n")
        sys.stdout.flush()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/rescan":
            paths = self.paths or discover_paths()
            export_library(self.config, paths)
            self._json({"ok": True})
            return
        self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._bytes(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path == "/api/list":
            index = LIBRARY / "index.json"
            payload = index.read_text(encoding="utf-8") if index.exists() else "[]"
            self._bytes(payload.encode("utf-8"), "application/json; charset=utf-8")
            return
        if self.path == "/api/status":
            self._json(export_status_snapshot())
            return
        if self.path == "/zip":
            zip_path = build_stickers_zip()
            data = zip_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=wxmeme-stickers.zip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/library/"):
            name = posixpath.basename(urllib.parse.unquote(self.path[len("/library/") :]))
            path = (LIBRARY / name).resolve()
            if path.parent != LIBRARY.resolve() or not path.is_file():
                self.send_error(404)
                return
            mime = {
                ".gif": "image/gif",
                ".png": "image/png",
                ".webp": "image/webp",
                ".jpg": "image/jpeg",
                ".wxgf": "application/octet-stream",
            }.get(path.suffix.lower(), "application/octet-stream")
            self._bytes(path.read_bytes(), mime)
            return
        self.send_error(404)

    def _json(self, payload: dict) -> None:
        self._bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _bytes(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def cmd_verify_key(config: ExportConfig, paths: WeChatPaths) -> int:
    if not config.emoticon_key:
        print("请提供 --emoticon-key 或 --seed")
        return 1

    sample = None
    for path in paths.sticker_index.values():
        if identify_file(path) is None:
            sample = path
            break
    if not sample:
        print("没有找到可验证的加密表情样本")
        return 1
    ok = verify_emoticon_key(config.emoticon_key, sample)
    print(f"样本: {sample}")
    print("密钥有效" if ok else "密钥无效")
    return 0 if ok else 2


def cmd_decrypt_msg(config: ExportConfig, input_dir: Path, output_dir: Path, talker: str | None) -> int:
    if not config.msg_key:
        print("请提供 --msg-key（Windows MSG*.db 密码，hex）")
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for db_file in sorted(input_dir.glob("MSG*.db")):
        out = output_dir / f"decoded_{db_file.name}"
        result = decrypt_legacy_msg_db(db_file, config.msg_key, out)
        if result:
            ok += 1
            print(f"  OK  {db_file.name}")
            if talker:
                md5s = sticker_md5s_from_msg_db(result, talker)
                print(f"      Type=47 md5 数量: {len(md5s)}")
        else:
            print(f"  FAIL {db_file.name}")
    print(f"解密完成: {ok}/{len(list(input_dir.glob('MSG*.db')))}")
    return 0


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port: int, open_browser: bool, config: ExportConfig, paths: WeChatPaths) -> None:
    Handler.config = config
    Handler.paths = paths
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}"
        print(f"wxmeme: {url}", flush=True)
        if open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nwxmeme: bye")


def start_server_thread(port: int, config: ExportConfig, paths: WeChatPaths) -> threading.Thread:
    thread = threading.Thread(
        target=serve,
        args=(port, False, config, paths),
        daemon=True,
        name="wxmeme-http",
    )
    thread.start()
    return thread


def main() -> int:
    parser = argparse.ArgumentParser(description="按顺序导出并解密微信「我的表情」")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--emoticon-key", help="表情文件 AES 密钥，16 字节 hex")
    parser.add_argument("--seed", help="与 wxid 组合派生表情密钥: md5(seed+wxid+EMOTICON)")
    parser.add_argument("--wxid", help="微信账号目录名，例如 wxid_xxx_6075")
    parser.add_argument("--db-key", help="emoticon.db 的 SQLCipher4 raw key，32 字节 hex")
    parser.add_argument("--decrypted-db", help="已解密的 emoticon.db 路径")
    parser.add_argument("--msg-key", help="Windows MSG*.db 密码（hex），用于参考脚本同款解密")
    parser.add_argument("--verify-key", action="store_true", help="验证 --emoticon-key / --seed 是否有效")
    parser.add_argument("--decrypt-msg-dir", help="批量解密 Windows MSG*.db 目录")
    parser.add_argument("--msg-output-dir", default="decoded_msg", help="MSG 解密输出目录")
    parser.add_argument("--msg-talker", help="解密后统计 Type=47 的联系人 id")
    parser.add_argument("--auto-key", action="store_true", help="从运行中的微信进程自动扫描 seed（macOS）")
    parser.add_argument("--auto-db-key", action="store_true", help="从运行中的微信进程自动扫描 emoticon.db 密钥（macOS）")
    parser.add_argument("--scan-seed", action="store_true", help="只扫描并打印 seed / emoticon_key")
    parser.add_argument("--scan-db-key", action="store_true", help="只扫描并打印 emoticon.db 的 db_key")
    parser.add_argument("--cdn", action="store_true", help="本地解密失败时，从 CDN 链接下载")
    parser.add_argument("--sync-persist", action="store_true", help="fav.archive 模式下，把 4.x 本地新缓存追加到列表末尾")
    parser.add_argument("--wcdb-keys", nargs="?", const="auto", metavar="PATH", help="从 wcdb-key-tool 的 all_keys.json 读取 emoticon.db 密钥")
    parser.add_argument("--force-fav-archive", action="store_true", help="强制使用旧版 fav.archive，忽略 emoticon.db")
    parser.add_argument("--pid", type=int, help="指定微信进程 PID（默认自动选择主进程）")
    args = parser.parse_args()

    paths = discover_paths()

    if args.auto_db_key or args.scan_db_key:
        try:
            resolve_auto_db_key(args, paths)
        except (PermissionError, RuntimeError, OSError) as exc:
            print(f"错误: {exc}", file=sys.stderr, flush=True)
            print(
                "微信 4.1+ 可能需外部工具提取 db_key，例如 wcdb-key-tool / LLDB，然后：\n"
                "  python3 exporter/wxmeme.py --db-key YOUR_64_HEX --cdn --scan-only",
                file=sys.stderr,
                flush=True,
            )
            return 1
        if args.scan_db_key:
            print(f"db_key={args.db_key}")
            return 0

    if args.auto_key or args.scan_seed:
        try:
            resolve_auto_key(args, paths)
        except (PermissionError, RuntimeError, OSError) as exc:
            print(f"错误: {exc}", file=sys.stderr, flush=True)
            print(
                "Mac 无法读微信内存时，可尝试 --auto-db-key；或临时用 --cdn --sync-persist：\n"
                "  python3 exporter/wxmeme.py --cdn --sync-persist --scan-only",
                file=sys.stderr,
                flush=True,
            )
            return 1
        if args.scan_seed:
            print(f"seed={args.seed}")
            print(f"emoticon_key={args.emoticon_key}")
            return 0

    config = build_config(args)

    if args.verify_key:
        return cmd_verify_key(config, paths)

    if args.decrypt_msg_dir:
        return cmd_decrypt_msg(
            config,
            Path(args.decrypt_msg_dir).expanduser(),
            Path(args.msg_output_dir).expanduser(),
            args.msg_talker,
        )

    libraries = paths.library_dirs
    accounts = paths.account_dirs
    if not libraries and not accounts:
        print("没有找到微信表情数据目录。")
        return 1

    if libraries:
        print("旧版 Stickers:", flush=True)
        for path in libraries:
            print(f"  {path}", flush=True)
    if accounts:
        print("账号目录:", flush=True)
        for path in accounts:
            print(f"  {path}", flush=True)

    items, skipped, total = export_library(config, paths)
    exported = sum(1 for item in items if item.get("exported"))
    print(f"面板共 {total} 个，导出 {exported} 个 -> {LIBRARY}", flush=True)
    if skipped:
        print(f"仍有 {skipped} 个未导出（缺密钥或文件缺失）。", flush=True)
    if not config.emoticon_key and exported < total and not args.auto_key and not config.use_cdn:
        print("提示: 内存读取失败时可用 --cdn；或复制微信重签名后再 --auto-key。", flush=True)

    if args.scan_only:
        return 0
    serve(args.port, open_browser=not args.no_browser, config=config, paths=paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
