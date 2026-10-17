#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金币上限补丁 (Gold Limit Patcher)
=================================
原版暗黑2 (1.13c/1.13d/1.14d) 的金币限制：
  * 储物箱每页上限固定 250 万（D2Common.dll: MOV EAX,2625A0）
  * 人物携带上限随等级计算（D2Common.dll: IMUL EAX,EAX,2710，即 等级x10000）

本工具把这两处改为：
  * 储物箱上限 250 万 -> 1 亿 (0x05F5E100)
  * 人物携带上限乘数 10000 -> 250 万（99 级约 24.75 亿，1 级也有 250 万）

用法：
  1. 把本程序放到游戏目录（和 Game.exe、D2Common.dll 同级），双击运行；
  2. 或者把 D2Common.dll 拖到本程序图标上；
  3. 加参数 -restore 可还原备份。

注意：
  * 修改的是游戏代码文件，务必先用本工具自动生成的 .bak 备份；
  * 每次游戏版本更新（重打补丁）后需重新运行本工具；
  * 仅限单机/允许修改的平台使用，不要带修改版连暴雪战网。
"""
import os
import shutil
import struct
import sys
from datetime import datetime

# 储物箱金币上限: B8 A0 25 26 00        MOV EAX,2625A0   (250万)
#            ->  B8 00 E1 F5 05        MOV EAX,5F5E100  (1亿)
STASH_OLD = b"\xB8\xA0\x25\x26\x00"
STASH_NEW = b"\xB8\x00\xE1\xF5\x05"

# 人物携带金币上限乘数: 69 C0 10 27 00 00    IMUL EAX,EAX,2710 (x10000)
#                ->   69 C0 A0 25 26 00    IMUL EAX,EAX,2625A0 (x250万)
CHAR_OLD = b"\x69\xC0\x10\x27\x00\x00"
CHAR_NEW = b"\x69\xC0\xA0\x25\x26\x00"


def find_dll(argv):
    cands = []
    for a in argv[1:]:
        if a.lower().endswith(".dll") and os.path.isfile(a):
            cands.append(os.path.abspath(a))
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    for d in [exe_dir, os.path.dirname(exe_dir)]:
        p = os.path.join(d, "D2Common.dll")
        if os.path.isfile(p):
            cands.append(p)
    for c in cands:
        if os.path.basename(c).lower() == "d2common.dll":
            return c
    return None


def is_pe_dll(path):
    try:
        with open(path, "rb") as f:
            head = f.read(0x200)
        return head[:2] == b"MZ" and b".dll" in head[:0x200].lower() or head[:2] == b"MZ"
    except Exception:
        return False


def patch_bytes(data, old, new, label):
    """返回 (新数据, 修改位置列表)。已修改过的跳过。"""
    positions = []
    if data.find(new) != -1 and data.find(old) == -1:
        return data, positions, "already"
    start = 0
    while True:
        i = data.find(old, start)
        if i == -1:
            break
        positions.append(i)
        start = i + 1
    if not positions:
        return data, positions, "notfound"
    out = bytearray(data)
    for p in positions:
        out[p:p + len(new)] = new
    return bytes(out), positions, "patched"


def main():
    argv = sys.argv
    print("=" * 62)
    print(" 暗黑2 金币上限补丁 (Gold Limit Patcher)  储物箱 250万 -> 1亿")
    print("=" * 62)

    dll = find_dll(argv)
    if not dll:
        print("[错误] 未找到 D2Common.dll。")
        print("请把本程序放到游戏目录（与 Game.exe 同级）运行，")
        print("或把 D2Common.dll 拖到本程序图标上。")
        input("按回车退出...")
        return 1
    print("目标文件: %s" % dll)

    # 还原模式
    if any(a.lower() in ("-restore", "--restore", "-r", "restore") for a in argv[1:]):
        baks = sorted(f for f in os.listdir(os.path.dirname(dll))
                      if f.startswith("D2Common.dll.bak"))
        if not baks:
            print("[错误] 没有找到备份文件 (D2Common.dll.bak*)。")
            input("按回车退出...")
            return 1
        latest = os.path.join(os.path.dirname(dll), baks[-1])
        shutil.copy2(dll, dll + ".before_restore_" +
                     datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(latest, dll)
        print("已从 %s 还原。" % baks[-1])
        input("按回车退出...")
        return 0

    if not is_pe_dll(dll):
        print("[错误] %s 不是有效的 D2Common.dll。" % dll)
        input("按回车退出...")
        return 1

    with open(dll, "rb") as f:
        original = f.read()
    print("文件大小: %d 字节" % len(original))

    data, pos1, st1 = patch_bytes(original, STASH_OLD, STASH_NEW, "stash")
    data, pos2, st2 = patch_bytes(data, CHAR_OLD, CHAR_NEW, "char")

    print("\n扫描结果:")
    for label, positions, st in (("储物箱上限 250万->1亿", pos1, st1),
                                 ("人物携带上限 x10000->x250万", pos2, st2)):
        if st == "patched":
            print("  [可修改] %s : 找到 %d 处 (偏移 %s)"
                  % (label, len(positions),
                     ", ".join(hex(p) for p in positions)))
        elif st == "already":
            print("  [已应用] %s : 已经是修改后的状态" % label)
        else:
            print("  [未找到] %s : 未匹配到原版指令" % label)

    if data == original:
        print("\n无需修改（可能已应用过，或你的游戏版本指令不同）。")
        print("如刚更新过游戏版本，请重新运行本工具。")
        input("按回车退出...")
        return 0

    backup = dll + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(dll, backup)
    print("\n已创建备份: %s" % os.path.basename(backup))

    try:
        with open(dll, "wb") as f:
            f.write(data)
    except PermissionError:
        print("[错误] 无法写入文件，请关闭游戏后重试。")
        input("按回车退出...")
        return 1

    print("\n" + "=" * 62)
    print(" 修改完成！共改动 %d 处。" % (len(pos1) + len(pos2)))
    print(" 储物箱每页金币上限: 250 万 -> 1 亿")
    print(" 人物携带金币上限: 等级x10000 -> 等级x250万")
    print(" 还原方法: 运行 本程序 -restore （或把 .bak 文件改回 D2Common.dll）")
    print("=" * 62)
    input("按回车退出...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
