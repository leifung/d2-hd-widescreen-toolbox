#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
暗金变紫补丁 (Unique Purple Patcher)
====================================
原理：
  暗黑2 原版中"暗金（独特）装备"的名字颜色由调色板文件 (.pl2) 末尾的
  "文本颜色表"决定，表内第 4 项（文件偏移 0x6B60C 处的 3 字节）默认是
  暗金色 C7 B3 77。本工具把它改成紫色 AE 00 FF。

  PL2 文本颜色表（偏移 0x6B600 起，每项 3 字节 RGB）：
    0: FFFFFF 普通    1: FF4D4D 服务器  2: 00FF00 套装(绿)
    3: 6969FF 魔法(蓝) 4: C7B377 暗金(金) 5: 696969 灰
    ...
    11: AE00FF 紫

用法：
  1. 把本程序放到游戏目录（和 Game.exe、d2data.mpq 同级），双击运行；
  2. 或者把 d2data.mpq 直接拖到本程序图标上。
  程序会自动备份并生成 d2_patch.mpq（游戏启动时自动加载，无需加参数）。

卸载：删除游戏目录下的 d2_patch.mpq 即可。
"""
import os
import struct
import sys
import zlib
from datetime import datetime

TEXT_COLOR_TABLE_OFFSET = 0x6B600   # 文本颜色表起始偏移
UNIQUE_COLOR_OFFSET = 0x6B60C       # 暗金色在表内的偏移（第 4 项）
UNIQUE_GOLD = b"\xC7\xB3\x77"       # 原版暗金 RGB
UNIQUE_PURPLE = b"\xAE\x00\xFF"     # 目标紫色 RGB
PATCH_MPQ_NAME = "d2_patch.mpq"

# ---------------------------------------------------------------- MPQ 加密 --

CRYPT_TABLE = [0] * 0x500


def _prepare_crypt_table():
    seed = 0x00100001
    for i in range(256):
        index = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = seed & 0xFFFF
            CRYPT_TABLE[index] = temp1 | temp2
            index += 0x100


_prepare_crypt_table()

HASH_TYPES = {"TABLE_OFFSET": 0, "HASH_A": 1, "HASH_B": 2, "TABLE": 3}


def hash_string(string, hash_type):
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    if isinstance(string, str):
        string = string.upper().encode("utf-8")
    for ch in string:
        value = CRYPT_TABLE[(HASH_TYPES[hash_type] << 8) + ch]
        seed1 = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed2 = (ch + seed1 + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
    return seed1


def decrypt(data, key):
    seed1 = key
    seed2 = 0xEEEEEEEE
    out = bytearray()
    for i in range(len(data) // 4):
        seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack("<I", data[i * 4:i * 4 + 4])[0]
        value = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed1 = (((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111 |
                 (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (value + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
        out += struct.pack("<I", value)
    return bytes(out)


def encrypt(data, key):
    seed1 = key
    seed2 = 0xEEEEEEEE
    out = bytearray()
    for i in range(len(data) // 4):
        seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack("<I", data[i * 4:i * 4 + 4])[0]
        cipher = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed1 = (((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111 |
                 (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (value + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
        out += struct.pack("<I", cipher)
    return bytes(out)


# ------------------------------------------------------------- MPQ 读取 ----


class MPQReader:
    """最小 MPQ 读取器：按文件名读取文件内容（复用暴雪标准算法）。"""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.raw = f.read()
        self._read_header()
        self._read_tables()

    def _read_header(self):
        if self.raw[:4] != b"MPQ\x1a":
            raise ValueError("不是有效的 MPQ 文件")
        (self.header_size, self.archive_size, fmt_ver,
         self.sector_shift) = struct.unpack("<IIHH", self.raw[4:16])
        (self.hash_off, self.block_off, self.hash_num,
         self.block_num) = struct.unpack("<IIII", self.raw[16:32])
        self.base_offset = 0  # 无 user data 前缀

    def _read_tables(self):
        key = hash_string("(hash table)", "TABLE")
        data = self.raw[self.hash_off + self.base_offset:
                        self.hash_off + self.base_offset + self.hash_num * 16]
        self.hash_table = [struct.unpack("<IIHHI", decrypt(data, key)[i * 16:(i + 1) * 16])
                           for i in range(self.hash_num)]
        key = hash_string("(block table)", "TABLE")
        data = self.raw[self.block_off + self.base_offset:
                        self.block_off + self.base_offset + self.block_num * 16]
        self.block_table = [struct.unpack("<IIII", decrypt(data, key)[i * 16:(i + 1) * 16])
                            for i in range(self.block_num)]

    def list_files(self):
        """从 (listfile) 条目读取文件名列表。"""
        names = []
        content = self.read_file("(listfile)")
        if content:
            for line in content.decode("utf-8", "ignore").splitlines():
                line = line.strip().replace("/", "\\")
                if line:
                    names.append(line)
        return names

    def read_file(self, filename):
        hash_a = hash_string(filename, "HASH_A")
        hash_b = hash_string(filename, "HASH_B")
        entry = None
        for ha, hb, _loc, _plat, bidx in self.hash_table:
            if ha == hash_a and hb == hash_b and bidx != 0xFFFFFFFF:
                entry = bidx
                break
        if entry is None:
            return None
        offset, arch_size, size, flags = self.block_table[entry]
        if not flags & 0x80000000 or arch_size == 0:
            return None
        data = self.raw[offset + self.base_offset:
                        offset + self.base_offset + arch_size]
        if not flags & 0x01000000:  # 多 sector 文件
            sector_size = 512 << self.sector_shift
            sectors = size // sector_size + 1
            if flags & 0x00000400:
                sectors += 1
            positions = struct.unpack("<%dI" % (sectors + 1), data[:4 * (sectors + 1)])
            buf = bytearray()
            left = size
            for i in range(len(positions) - (2 if flags & 0x00000400 else 1)):
                sector = data[positions[i]:positions[i + 1]]
                if flags & 0x00000200 and left > len(sector):
                    sector = _decompress(sector)
                left -= len(sector)
                buf += sector
            return bytes(buf)
        if flags & 0x00000200 and size > arch_size:
            return _decompress(data)
        return data


def _decompress(data):
    t = data[0]
    if t == 0x02:
        return zlib.decompress(data[1:], 15)
    if t == 0x10:
        import bz2
        return bz2.decompress(data[1:])
    raise RuntimeError("不支持的压缩类型: %d" % t)


# ------------------------------------------------------------- MPQ 写入 ----


def write_mpq(path, files):
    """把 {文件名: 内容} 写成最小可用的 MPQ（未压缩 single-unit）。"""
    entries = sorted(files.items())
    hash_num = 4
    while hash_num < len(entries) * 2:
        hash_num *= 2

    data_offset = 32  # header 后紧跟文件数据
    block_table = []
    body = bytearray()
    for name, content in entries:
        block_table.append((data_offset + len(body), len(content),
                            len(content), 0x81000000))  # EXISTS|SINGLE_UNIT
        body += content
        pad = (-len(body)) % 4
        body += b"\x00" * pad

    hash_off = data_offset + len(body)
    block_off = hash_off + hash_num * 16
    total = block_off + len(entries) * 16

    # 哈希表
    hash_tbl = [None] * hash_num
    for i, (name, _c) in enumerate(entries):
        idx = hash_string(name, "TABLE_OFFSET") % hash_num
        while hash_tbl[idx] is not None:
            idx = (idx + 1) % hash_num
        hash_tbl[idx] = (hash_string(name, "HASH_A"),
                         hash_string(name, "HASH_B"),
                         0, 0, i)
    hash_bytes = bytearray()
    for e in hash_tbl:
        if e is None:
            hash_bytes += struct.pack("<IIHHI", 0, 0, 0, 0, 0xFFFFFFFF)
        else:
            hash_bytes += struct.pack("<IIHHI", *e)
    block_bytes = bytearray()
    for e in block_table:
        block_bytes += struct.pack("<IIII", *e)

    out = bytearray()
    out += b"MPQ\x1a"
    out += struct.pack("<IIHH", 32, total, 0, 3)          # header
    out += struct.pack("<IIII", hash_off, block_off, hash_num, len(entries))
    assert len(out) == 32
    out += body
    assert len(out) == hash_off
    out += encrypt(bytes(hash_bytes), hash_string("(hash table)", "TABLE"))
    out += encrypt(bytes(block_bytes), hash_string("(block table)", "TABLE"))
    assert len(out) == total, (len(out), total)
    with open(path, "wb") as f:
        f.write(bytes(out))


# ------------------------------------------------------------------ 主逻辑 --


def find_game_dir(argv):
    cands = []
    for a in argv[1:]:
        if os.path.isfile(a):
            cands.append(os.path.dirname(os.path.abspath(a)))
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    cands += [exe_dir, os.path.dirname(exe_dir)]
    for c in cands:
        if os.path.isfile(os.path.join(c, "d2data.mpq")):
            return c
    return None


def main():
    print("=" * 60)
    print(" 暗金装备变紫补丁 (Diablo II Unique Purple Patcher)")
    print("=" * 60)
    game_dir = find_game_dir(sys.argv)
    if not game_dir:
        print("[错误] 未找到游戏目录（d2data.mpq）。")
        print("请把本程序放到游戏目录（与 Game.exe 同级）后运行，")
        print("或把 d2data.mpq 拖到本程序图标上。")
        input("按回车退出...")
        return 1

    d2data = os.path.join(game_dir, "d2data.mpq")
    print("游戏目录: %s" % game_dir)

    print("\n[1/3] 读取 d2data.mpq 中的调色板文件 (.pl2) ...")
    try:
        mpq = MPQReader(d2data)
        names = mpq.list_files()
    except Exception as e:
        print("[错误] 读取 d2data.mpq 失败: %s" % e)
        input("按回车退出...")
        return 1
    pl2_names = [n for n in names if n.lower().endswith(".pl2")
                 and n.lower().startswith("data\\global\\palette\\")]
    print("      共找到 %d 个调色板文件" % len(pl2_names))

    print("\n[2/3] 修改暗金色 (C7B377 -> AE00FF) ...")
    patched = {}
    already = 0
    for n in pl2_names:
        try:
            data = mpq.read_file(n)
        except Exception as e:
            print("      [跳过] %s 读取失败: %s" % (n, e))
            continue
        if not data or len(data) <= UNIQUE_COLOR_OFFSET + 3:
            continue
        cur = data[UNIQUE_COLOR_OFFSET:UNIQUE_COLOR_OFFSET + 3]
        if cur == UNIQUE_PURPLE:
            already += 1
            patched[n] = data
        elif cur == UNIQUE_GOLD:
            patched[n] = (data[:UNIQUE_COLOR_OFFSET] + UNIQUE_PURPLE +
                          data[UNIQUE_COLOR_OFFSET + 3:])
            print("      [已改] %s" % n)
        else:
            print("      [跳过] %s 颜色非常规值 %s（可能已被其他补丁修改）"
                  % (n, cur.hex()))

    if not patched:
        print("\n[完成] 没有需要修改的文件（已经是紫色或未找到暗金色定义）。")
        input("按回车退出...")
        return 0
    print("      修改 %d 个，其中原本已是紫色 %d 个" % (len(patched), already))

    print("\n[3/3] 写入 %s ..." % PATCH_MPQ_NAME)
    # 若已有 d2_patch.mpq，先读出其中内容以便合并保留
    target = os.path.join(game_dir, PATCH_MPQ_NAME)
    merged = dict(patched)
    if os.path.isfile(target):
        backup = target + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            old = MPQReader(target)
            old_files = old.list_files()
            for fn in old_files:
                if fn not in merged:
                    try:
                        d = old.read_file(fn)
                        if d is not None:
                            merged[fn] = d
                    except Exception:
                        pass
            os.replace(target, backup)
            print("      已备份旧文件 -> %s" % os.path.basename(backup))
        except Exception as e:
            print("      [警告] 合并旧 %s 失败(%s)，将覆盖它" % (PATCH_MPQ_NAME, e))
            os.replace(target, target + ".bak_" +
                       datetime.now().strftime("%Y%m%d_%H%M%S"))

    write_mpq(target, merged)
    size_kb = os.path.getsize(target) / 1024.0
    print("      已生成 %s (%.1f KB, %d 个文件)" % (PATCH_MPQ_NAME, size_kb, len(merged)))

    print("\n" + "=" * 60)
    print(" 完成！暗金装备（含未鉴定、地面掉落）的名字现在显示为紫色。")
    print(" 游戏启动时会自动加载 %s，无需额外参数。" % PATCH_MPQ_NAME)
    print(" 如不生效，可在启动参数追加: -mod d2_patch")
    print(" 卸载方法: 删除游戏目录下的 %s" % PATCH_MPQ_NAME)
    print("=" * 60)
    input("按回车退出...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
