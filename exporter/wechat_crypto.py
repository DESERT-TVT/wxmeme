"""WeChat local crypto helpers (read-only).

Supports:
- Windows MSG*.db (legacy SQLCipher page layout, PBKDF2-SHA1 x64000)
- WeChat 4.x SQLCipher 4 / WCDB databases (raw 32-byte key)
- Emoticon cache files (AES-128-CBC, key = IV)
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import sqlite3
import struct
import tempfile
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖: pip install pycryptodome") from exc

SQLITE_FILE_HEADER = b"SQLite format 3\x00"

LEGACY_PAGESIZE = 4096
LEGACY_ITER = 64000
LEGACY_KEY_SIZE = 32

WCDB_PAGESIZE = 4096
WCDB_SALT_SIZE = 16
WCDB_HMAC_SIZE = 64
WCDB_RESERVE = 80

IMAGE_MAGICS = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF89a", "gif"),
    (b"GIF87a", "gif"),
    (b"\xff\xd8\xff", "jpg"),
)


def parse_hex_key(value: str, size: int | None = None) -> bytes:
    cleaned = value.strip().replace(" ", "")
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    key = bytes.fromhex(cleaned)
    if size is not None and len(key) != size:
        raise ValueError(f"密钥长度应为 {size} 字节，当前 {len(key)} 字节")
    return key


def derive_emoticon_key(seed: str, wxid: str) -> bytes:
    digest = hashlib.md5(f"{seed}{wxid}EMOTICON".encode()).hexdigest()
    return bytes.fromhex(digest)


def looks_like_image(data: bytes) -> str | None:
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"wxgf"):
        return "wxgf"
    for magic, ext in IMAGE_MAGICS:
        if data.startswith(magic):
            return ext
    return None


def decrypt_emoticon_bytes(data: bytes, key: bytes) -> bytes | None:
    if len(key) != 16 or len(data) < 32 or len(data) % 16 != 0:
        return None
    decrypted = AES.new(key, AES.MODE_CBC, key).decrypt(data)
    pad = decrypted[-1]
    if not (1 <= pad <= 16 and decrypted[-pad:] == bytes([pad]) * pad):
        return None
    body = decrypted[:-pad]
    return body if looks_like_image(body) else None


def verify_emoticon_key(key: bytes, encrypted_file: Path) -> bool:
    try:
        sample = encrypted_file.read_bytes()
    except OSError:
        return False
    return decrypt_emoticon_bytes(sample, key) is not None


def decrypt_emoticon_file(source: Path, key: bytes) -> tuple[bytes, str] | None:
    try:
        raw = source.read_bytes()
    except OSError:
        return None
    body = decrypt_emoticon_bytes(raw, key)
    if body is None:
        return None
    ext = looks_like_image(body)
    if ext is None:
        return None
    return body, ext


def decrypt_legacy_msg_db(input_file: Path, password: bytes, output_file: Path | None = None) -> Path | None:
    data = input_file.read_bytes()
    if len(data) < LEGACY_PAGESIZE:
        return None

    salt = data[:16]
    key = hashlib.pbkdf2_hmac("sha1", password, salt, LEGACY_ITER, LEGACY_KEY_SIZE)
    first_page = data[16:LEGACY_PAGESIZE]

    mac_salt = bytes(x ^ 58 for x in salt)
    mac_key = hashlib.pbkdf2_hmac("sha1", key, mac_salt, 2, LEGACY_KEY_SIZE)
    digest = hmac.new(mac_key, digestmod="sha1")
    digest.update(first_page[:-32])
    digest.update(bytes(ctypes.c_int(1)))
    if digest.digest() != first_page[-32:-12]:
        return None

    out_path = output_file or input_file.with_name(f"decoded_{input_file.name}")
    with out_path.open("wb") as handle:
        handle.write(SQLITE_FILE_HEADER)
        iv = first_page[-48:-32]
        handle.write(AES.new(key, AES.MODE_CBC, iv).decrypt(first_page[:-48]))
        handle.write(first_page[-48:])

        for offset in range(LEGACY_PAGESIZE, len(data), LEGACY_PAGESIZE):
            page = data[offset : offset + LEGACY_PAGESIZE]
            if len(page) < 48:
                handle.write(page)
                continue
            iv = page[-48:-32]
            handle.write(AES.new(key, AES.MODE_CBC, iv).decrypt(page[:-48]))
            handle.write(page[-48:])
    return out_path


def _verify_sqlcipher4_key(raw_key: bytes, page1: bytes) -> bool:
    salt = page1[:WCDB_SALT_SIZE]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", raw_key, mac_salt, 2, dklen=32)
    hmac_data = page1[WCDB_SALT_SIZE : WCDB_PAGESIZE - WCDB_RESERVE + 16]
    stored = page1[WCDB_PAGESIZE - WCDB_HMAC_SIZE : WCDB_PAGESIZE]
    digest = hmac.new(mac_key, hmac_data, hashlib.sha512)
    digest.update(struct.pack("<I", 1))
    return hmac.compare_digest(digest.digest(), stored)


def _decrypt_sqlcipher4_page(raw_key: bytes, page: bytes, page_no: int) -> bytes:
    iv = page[WCDB_PAGESIZE - WCDB_RESERVE : WCDB_PAGESIZE - WCDB_RESERVE + 16]
    if page_no == 1:
        decrypted = AES.new(raw_key, AES.MODE_CBC, iv).decrypt(
            page[WCDB_SALT_SIZE : WCDB_PAGESIZE - WCDB_RESERVE]
        )
        return SQLITE_FILE_HEADER + decrypted + (b"\x00" * WCDB_RESERVE)
    decrypted = AES.new(raw_key, AES.MODE_CBC, iv).decrypt(page[: WCDB_PAGESIZE - WCDB_RESERVE])
    return decrypted + (b"\x00" * WCDB_RESERVE)


def decrypt_sqlcipher4_db(input_file: Path, raw_key: bytes, output_file: Path | None = None) -> Path | None:
    if len(raw_key) != 32:
        raise ValueError("SQLCipher4 raw key 需要 32 字节")

    data = input_file.read_bytes()
    if len(data) < WCDB_PAGESIZE:
        return None

    page1 = data[:WCDB_PAGESIZE]
    if not _verify_sqlcipher4_key(raw_key, page1):
        return None

    out_path = output_file or input_file.with_name(f"decoded_{input_file.name}")
    total_pages = (len(data) + WCDB_PAGESIZE - 1) // WCDB_PAGESIZE
    with input_file.open("rb") as src, out_path.open("wb") as dst:
        for page_no in range(1, total_pages + 1):
            page = src.read(WCDB_PAGESIZE)
            if not page:
                break
            if len(page) < WCDB_PAGESIZE:
                page = page + (b"\x00" * (WCDB_PAGESIZE - len(page)))
            dst.write(_decrypt_sqlcipher4_page(raw_key, page, page_no))
    return out_path


def open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def favorite_md5s_from_db(db_path: Path) -> list[str]:
    conn = open_sqlite(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "kNonStoreEmoticonTable" not in tables:
            return []

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(kNonStoreEmoticonTable)").fetchall()
        }
        order_col = next(
            (name for name in ("sort_order_", "sortOrder", "sort_", "sort", "index_") if name in columns),
            None,
        )
        query = "SELECT md5 FROM kNonStoreEmoticonTable"
        if order_col:
            query += f" ORDER BY [{order_col}]"
        return [str(row[0]).lower() for row in conn.execute(query).fetchall() if row[0]]
    finally:
        conn.close()


def sticker_md5s_from_msg_db(db_path: Path, talker: str) -> list[str]:
    conn = open_sqlite(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if str(row[0]).upper().startswith("MSG")
        ]
        if not tables:
            return []

        table = tables[0]
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()}
        if "StrContent" not in columns or "StrTalker" not in columns:
            return []

        rows = conn.execute(
            f"""
            SELECT StrContent
            FROM [{table}]
            WHERE StrTalker = ? AND Type = 47
            ORDER BY CreateTime
            """,
            (talker,),
        ).fetchall()

        md5s: list[str] = []
        seen: set[str] = set()
        for row in rows:
            content = str(row[0] or "")
            for token in content.replace('"', " ").replace("'", " ").split():
                token = token.lower().strip("<>/\\")
                if len(token) == 32 and all(c in "0123456789abcdef" for c in token) and token not in seen:
                    seen.add(token)
                    md5s.append(token)
        return md5s
    finally:
        conn.close()
