"""Scan emoticon seed from a running WeChat process on macOS."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from wechat_crypto import decrypt_emoticon_bytes, derive_emoticon_key, verify_sqlcipher4_db_key

RE_SEED = re.compile(rb"(?<![0-9])(\d{8,12})(?![0-9])")
RE_HEX64 = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])")
CHUNK = 2 * 1024 * 1024
MAX_REGION = 200 * 1024 * 1024
SEED_MIN = 100_000_000
SEED_MAX = 4_000_000_000

KERN_SUCCESS = 0
VM_REGION_BASIC_INFO_64 = 9


class VmRegionBasicInfo64(ctypes.Structure):
    _fields_ = [
        ("protection", ctypes.c_int),
        ("max_protection", ctypes.c_int),
        ("inheritance", ctypes.c_uint),
        ("shared", ctypes.c_bool),
        ("reserved", ctypes.c_bool),
        ("offset", ctypes.c_ulonglong),
        ("behavior", ctypes.c_int),
        ("user_wired_count", ctypes.c_ushort),
    ]


_libc = ctypes.CDLL(ctypes.util.find_library("c"))
_libc.task_for_pid.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
_libc.task_for_pid.restype = ctypes.c_int
_libc.mach_task_self.restype = ctypes.c_uint

_libc.mach_vm_region_recurse.argtypes = [
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint),
]
_libc.mach_vm_region_recurse.restype = ctypes.c_int

_libc.mach_vm_read_overwrite.argtypes = [
    ctypes.c_uint,
    ctypes.c_ulonglong,
    ctypes.c_ulonglong,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ulong),
]
_libc.mach_vm_read_overwrite.restype = ctypes.c_int


def find_wechat_pid() -> int | None:
    try:
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,rss=,comm="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    best_pid = None
    best_rss = -1
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid_str, rss_str, comm = parts
        if "WeChat" not in comm and "wechat" not in comm.lower():
            continue
        if comm.strip().endswith("WeChatAppEx") or "Helper" in comm:
            continue
        try:
            pid = int(pid_str)
            rss = int(rss_str)
        except ValueError:
            continue
        if rss > best_rss:
            best_rss = rss
            best_pid = pid
    return best_pid


def _open_task(pid: int) -> int:
    task = ctypes.c_uint(0)
    kr = _libc.task_for_pid(_libc.mach_task_self(), pid, ctypes.byref(task))
    if kr != KERN_SUCCESS:
        raise PermissionError(
            f"无法读取微信进程内存 (task_for_pid={kr})。\n"
            "请保持微信已登录运行，并尝试：\n"
            "  sudo python3 exporter/wxmeme.py --auto-key --scan-only\n"
            "若仍失败，需对 WeChat.app 去 Hardened Runtime 重签名后再试。"
        )
    return task.value


def _enum_regions(task: int) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    address = ctypes.c_ulonglong(0)
    size = ctypes.c_ulonglong(0)
    depth = ctypes.c_uint(0)
    info = VmRegionBasicInfo64()
    count = ctypes.c_uint(9)

    while True:
        kr = _libc.mach_vm_region_recurse(
            task,
            ctypes.byref(address),
            ctypes.byref(size),
            ctypes.byref(depth),
            ctypes.byref(info),
            ctypes.byref(count),
        )
        if kr != KERN_SUCCESS:
            break
        if info.shared is False and 0 < size.value <= MAX_REGION:
            regions.append((address.value, size.value))
        next_addr = address.value + size.value
        if next_addr <= address.value:
            break
        address.value = next_addr
        depth.value = 0
    return regions


def _read_region(task: int, address: int, size: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(size)
    read_count = ctypes.c_ulong(0)
    kr = _libc.mach_vm_read_overwrite(
        task,
        ctypes.c_ulonglong(address),
        ctypes.c_ulonglong(size),
        buffer,
        ctypes.byref(read_count),
    )
    if kr != KERN_SUCCESS or read_count.value == 0:
        return None
    return buffer.raw[: read_count.value]


def _collect_seeds(data: bytes, seeds: set[int], wxid: str | None) -> None:
    for match in RE_SEED.finditer(data):
        value = int(match.group(1))
        if SEED_MIN < value < SEED_MAX:
            seeds.add(value)

    if wxid:
        wxid_bytes = wxid.encode()
        start = 0
        while True:
            idx = data.find(wxid_bytes, start)
            if idx < 0:
                break
            window = data[max(0, idx - 128) : idx + len(wxid_bytes) + 128]
            for match in RE_SEED.finditer(window):
                value = int(match.group(1))
                if SEED_MIN < value < SEED_MAX:
                    seeds.add(value)
            start = idx + 1


def scan_seed_candidates(pid: int | None = None, wxid: str | None = None) -> set[int]:
    target_pid = pid or find_wechat_pid()
    if not target_pid:
        raise RuntimeError("未找到运行中的微信主进程，请先打开并登录微信。")

    task = _open_task(target_pid)
    seeds: set[int] = set()
    regions = _enum_regions(task)
    print(f"wxmeme: 扫描微信 PID {target_pid}，{len(regions)} 个内存区域…", flush=True)

    for base, size in regions:
        offset = 0
        tail = b""
        while offset < size:
            chunk_size = min(CHUNK, size - offset)
            chunk = _read_region(task, base + offset, chunk_size)
            if chunk:
                data = tail + chunk
                _collect_seeds(data, seeds, wxid)
                tail = data[-128:]
            else:
                tail = b""
            offset += chunk_size

    print(f"wxmeme: 找到 {len(seeds)} 个 seed 候选", flush=True)
    return seeds


def _verify_seed(seed: int, wxid: str, sample: bytes) -> tuple[int, bytes] | None:
    key = derive_emoticon_key(str(seed), wxid)
    if decrypt_emoticon_bytes(sample, key):
        return seed, key
    return None


def find_emoticon_key_from_memory(
    wxid: str,
    sample_file: Path,
    pid: int | None = None,
) -> tuple[int, bytes]:
    sample = sample_file.read_bytes()
    if len(sample) < 32:
        raise RuntimeError(f"验证样本过小: {sample_file}")

    seeds = scan_seed_candidates(pid=pid, wxid=wxid)
    if not seeds:
        raise RuntimeError("内存里没有找到 seed 候选值。")

    print(f"wxmeme: 验证 seed（wxid={wxid}）…", flush=True)
    workers = min(16, max(2, (os.cpu_count() or 4)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_verify_seed, seed, wxid, sample): seed for seed in sorted(seeds)}
        for future in as_completed(futures):
            result = future.result()
            if result:
                seed, key = result
                print(f"wxmeme: seed={seed}", flush=True)
                print(f"wxmeme: emoticon_key={key.hex()}", flush=True)
                return seed, key

    raise RuntimeError("找到了 seed 候选，但没有能通过解密的密钥。请确认 wxid 是否正确。")


def find_encrypted_sample(sticker_index: dict[str, Path], identify_file) -> Path:
    for path in sticker_index.values():
        if path.is_file() and identify_file(path) is None:
            return path
    raise RuntimeError("没有找到加密表情样本文件，请先在微信里打开一次表情面板。")


def _collect_db_key_candidates(data: bytes, candidates: set[bytes]) -> None:
    for match in RE_HEX64.finditer(data):
        try:
            candidates.add(bytes.fromhex(match.group(1).decode("ascii")))
        except ValueError:
            continue

    for offset in range(0, max(0, len(data) - 32), 8):
        candidates.add(data[offset : offset + 32])


def find_db_key_from_memory(db_path: Path, pid: int | None = None) -> bytes:
    if not db_path.is_file():
        raise RuntimeError(f"找不到数据库: {db_path}")

    target_pid = pid or find_wechat_pid()
    if not target_pid:
        raise RuntimeError("未找到运行中的微信主进程，请先打开并登录微信。")

    task = _open_task(target_pid)
    candidates: set[bytes] = set()
    regions = _enum_regions(task)
    print(f"wxmeme: 扫描 emoticon.db 密钥（PID {target_pid}，{len(regions)} 个内存区域）…", flush=True)

    for base, size in regions:
        offset = 0
        while offset < size:
            chunk_size = min(CHUNK, size - offset)
            chunk = _read_region(task, base + offset, chunk_size)
            if chunk:
                _collect_db_key_candidates(chunk, candidates)
            offset += chunk_size

    print(f"wxmeme: 找到 {len(candidates)} 个 db_key 候选，正在验证…", flush=True)
    for key in candidates:
        if verify_sqlcipher4_db_key(db_path, key):
            print(f"wxmeme: db_key={key.hex()}", flush=True)
            return key

    raise RuntimeError(
        "未能在内存中找到 emoticon.db 密钥。"
        "微信 4.1+ 可能不再缓存明文密钥，请用 LLDB / wcdb-key-tool 提取后传 --db-key。"
    )
