#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diablo II 1.13c 数据修改一键脚本（v2.0）

功能：
1. 暗金（Unique）装备名字颜色 -> 紫色（游戏原生紫色 AE00FF）
2. 暗金装备掉率 x10（itemratio.txt: Unique/10, UniqueDivisor*10, UniqueMin/10）

原理：把改好的文件写进 Patch_D2.mpq（游戏启动时优先级最高的数据包），
原版 d2data/d2exp 等 MPQ 一个字节都不动，可完整回滚。

用法：
  把 mpqlib.py 和本脚本放到游戏目录（与 Game.exe、Patch_D2.mpq 同级），然后：
      python apply_mods.py            # 使用脚本所在目录作为游戏目录
      python apply_mods.py "D:\\Diablo II"   # 或显式指定游戏目录

  首次运行会自动创建 _ModBackup_<时间戳> 备份目录（含原 Patch_D2.mpq 和注册表导出），
  覆盖备份中的 Patch_D2.mpq 即可撤销全部数据修改。
"""
import sys, os, shutil, struct
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mpqlib import MPQ, append_to_mpq

GAME = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = os.path.join(GAME, "_ModBackup_" + TS)
GOLD = b"\xC7\xB3\x77"
PURPLE = b"\xAE\x00\xFF"
COLOR_OFF = 0x6B60C

PALETTES = [
    "data\\global\\palette\\act1\\pal.pl2",
    "data\\global\\palette\\act2\\pal.pl2",
    "data\\global\\palette\\act3\\pal.pl2",
    "data\\global\\palette\\act4\\pal.pl2",
    "data\\global\\palette\\act5\\pal.pl2",
    "data\\global\\palette\\endgame\\pal.pl2",
    "data\\global\\palette\\endgame2\\pal.pl2",
    "data\\global\\palette\\fechar\\pal.pl2",
    "data\\global\\palette\\loading\\pal.pl2",
    "data\\global\\palette\\menu0\\pal.pl2",
    "data\\global\\palette\\menu1\\pal.pl2",
    "data\\global\\palette\\menu2\\pal.pl2",
    "data\\global\\palette\\menu3\\pal.pl2",
    "data\\global\\palette\\menu4\\pal.pl2",
    "data\\global\\palette\\sky\\pal.pl2",
    "data\\global\\palette\\trademark\\pal.pl2",
]
ITEMRATIO = "data\\global\\excel\\itemratio.txt"


def log(msg):
    print(msg, flush=True)


def main():
    log("=" * 72)
    log("Diablo II 1.13c mod patcher v2.0  (%s)" % TS)
    log("game dir: %s" % GAME)
    log("=" * 72)

    # ---------------------------------------------------------- backup -------
    log("[0] creating backup -> %s" % BACKUP)
    os.makedirs(BACKUP, exist_ok=True)
    for f in ("Patch_D2.mpq", "PlugY.ini", "SGD2FreeRes.json", "d2dx_sgd2freeres.json",
              "d2dx.cfg", "d2fps.dll", "glide3x.dll"):
        src = os.path.join(GAME, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(BACKUP, f))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Blizzard Entertainment\Diablo II") as k:
            lines = ["Windows Registry Editor Version 5.00", "",
                     "[HKEY_CURRENT_USER\\Software\\Blizzard Entertainment\\Diablo II]"]
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if typ == winreg.REG_SZ:
                    lines.append('"%s"="%s"' % (name, str(val).replace("\\", "\\\\")))
                elif typ == winreg.REG_DWORD:
                    lines.append('"%s"=dword:%08x' % (name, val))
                i += 1
            with open(os.path.join(BACKUP, "DiabloII.reg"), "w") as f:
                f.write("\n".join(lines) + "\n")
        log("    registry values dumped")
    except Exception as e:
        log("    registry dump failed: %s" % e)
    with open(os.path.join(BACKUP, "MANIFEST.txt"), "w") as f:
        f.write("Backup of Diablo II mod state before v2.0 patching.\n")
        f.write("Restore Patch_D2.mpq to revert purple + drop-rate mods.\n")
        f.write("Restore DiabloII.reg (double-click) to revert video/registry settings.\n")

    d2 = MPQ(os.path.join(GAME, "d2data.mpq"))
    de = MPQ(os.path.join(GAME, "d2exp.mpq"))
    pd2 = MPQ(os.path.join(GAME, "Patch_D2.mpq"))

    # ---------------------------------------------------- itemratio x10 ------
    log("")
    log("[1] itemratio.txt: unique drop rate x10")
    data, fl = pd2.read(ITEMRATIO)
    if not data:
        log("    ERROR: cannot read itemratio.txt from Patch_D2.mpq")
        return 1
    log("    read %d bytes (active vanilla 1.13c file)" % len(data))
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.split(nl)
    header = lines[0].split(b"\t")
    try:
        iU = header.index(b"Unique")
        iUD = header.index(b"UniqueDivisor")
        iUM = header.index(b"UniqueMin")
    except ValueError:
        log("    ERROR: unexpected itemratio header: %r" % lines[0][:120])
        return 1
    log("    columns: Unique=%d UniqueDivisor=%d UniqueMin=%d" % (iU, iUD, iUM))
    out = [lines[0]]
    changed = 0
    for line in lines[1:]:
        if not line.strip():
            out.append(line)
            continue
        f = line.split(b"\t")
        if len(f) != len(header):
            out.append(line)
            continue
        u, ud, um = int(f[iU]), int(f[iUD]), int(f[iUM])
        f[iU] = str(u // 10).encode()
        f[iUD] = str(ud * 10).encode()
        f[iUM] = str(um // 10).encode()
        out.append(b"\t".join(f))
        changed += 1
        log("    %-38s Unique %4d->%-3d  Div %2d->%-3d  Min %5d->%-4d"
            % (f[0].decode("latin-1")[:38], u, u // 10, ud, ud * 10, um, um // 10))
    new_itemratio = nl.join(out)
    log("    %d rows modified" % changed)

    # ---------------------------------------------------- palettes purple ----
    log("")
    log("[2] palette text color table: unique gold -> purple")
    new_files = {ITEMRATIO: new_itemratio}
    for path in PALETTES:
        b_d2, b_de = d2.lookup(path), de.lookup(path)
        if b_de is not None:
            src_mpq, src_b, tag = de, b_de, "d2exp"
        elif b_d2 is not None:
            src_mpq, src_b, tag = d2, b_d2, "d2data"
        else:
            log("    SKIP (not found): %s" % path)
            continue
        pdata, pfl = src_mpq.read_by_index(src_b)
        if not pdata or len(pdata) <= COLOR_OFF + 3:
            log("    SKIP (unreadable): %s" % path)
            continue
        cur = pdata[COLOR_OFF:COLOR_OFF + 3]
        if cur == GOLD:
            patched = pdata[:COLOR_OFF] + PURPLE + pdata[COLOR_OFF + 3:]
            new_files[path] = patched
            log("    [patched] %-46s (%s) %s -> %s"
                % (path, tag, cur.hex(), PURPLE.hex()))
        elif cur == PURPLE:
            new_files[path] = pdata
            log("    [already] %-46s (%s)" % (path, tag))
        else:
            log("    [SKIP]    %-46s unexpected %s" % (path, cur.hex()))
    log("    %d palette files to deliver" % (len(new_files) - 1))

    # ---------------------------------------------------- rebuild patch_d2 ---
    log("")
    log("[3] rebuilding Patch_D2.mpq (preserving all original files)")
    tmp = os.path.join(GAME, "Patch_D2.mpq.new")
    n = append_to_mpq(os.path.join(GAME, "Patch_D2.mpq"), tmp, new_files)
    log("    wrote %s (%d files added/replaced, %d bytes)"
        % (os.path.basename(tmp), n, os.path.getsize(tmp)))

    # ---------------------------------------------------- verify -------------
    log("")
    log("[4] verifying new Patch_D2.mpq")
    chk = MPQ(tmp)
    v, vfl = chk.read(ITEMRATIO)
    ok = v is not None and v.split(nl)[1].split(b"\t")[iU] == b"40"
    log("    itemratio readback: %s bytes, Unique(first data row)=%s -> %s"
        % (len(v) if v else -1,
           v.split(nl)[1].split(b"\t")[iU].decode() if v else "?",
           "OK" if ok else "FAIL"))
    bad = 0
    for path in PALETTES:
        if path not in new_files:
            continue
        pdata, pfl = chk.read(path)
        if not pdata or pdata[COLOR_OFF:COLOR_OFF + 3] != PURPLE:
            log("    FAIL: %s" % path)
            bad += 1
    log("    palette readback: %d/%d OK" % (len([p for p in PALETTES if p in new_files]) - bad,
                                            len([p for p in PALETTES if p in new_files])))
    # original files still intact? (raw data region must be byte-identical)
    raw_ok = chk.raw[32:pd2.hash_off] == pd2.raw[32:pd2.hash_off]
    log("    original data region byte-identical: %s" % ("OK" if raw_ok else "FAIL"))
    orig_ok = 0
    orig_total = 0
    orig_both_failed = 0
    for bidx in range(len(pd2.block_table)):
        off, asz, sz, fl = pd2.block_table[bidx]
        if not fl & 0x80000000 or asz == 0:
            continue
        orig_total += 1
        try:
            d1, _ = pd2.read_by_index(bidx)
        except Exception:
            d1 = "ERR"
        try:
            d2c, _ = chk.read_by_index(bidx)
        except Exception:
            d2c = "ERR"
        if d1 == d2c:
            orig_ok += 1
            if d1 == "ERR":
                orig_both_failed += 1
    log("    original files preserved: %d/%d readable-identical (%d encrypted/unreadable in both)"
        % (orig_ok, orig_total, orig_both_failed))
    if not ok or bad or not raw_ok or orig_ok != orig_total:
        log("    VERIFICATION FAILED - keeping original Patch_D2.mpq")
        os.remove(tmp)
        return 1
    os.replace(tmp, os.path.join(GAME, "Patch_D2.mpq"))
    log("")
    log("DONE. Patch_D2.mpq replaced (%d bytes). Backup in %s"
        % (os.path.getsize(os.path.join(GAME, "Patch_D2.mpq")), BACKUP))
    return 0


if __name__ == "__main__":
    sys.exit(main())
