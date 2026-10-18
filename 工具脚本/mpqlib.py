#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mpqlib.py - minimal MPQ reader (zlib/bz2/implode) + append-style writer.

Reader/writer verified against the real D2 1.13c archives in this game folder.
Crypt variant: seed1 = ((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)  (verified).
"""
import struct
import zlib
import bz2

# ---------------------------------------------------------------- implode ----

MAXBITS = 13
MAXWIN = 4096

_LITLEN = [11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
           9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
           7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
           8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
           44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
           44, 173]
_LENLEN = [2, 35, 36, 53, 38, 23]
_DISTLEN = [2, 20, 53, 230, 247, 151, 248]
_BASE = [3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264]
_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]


class ImplodeError(Exception):
    pass


def _construct(rep):
    """Build (count, symbol) huffman tables from compact repeat list (blast.c)."""
    symbol = 0
    length = [0] * 256
    for r in rep:
        left = (r >> 4) + 1
        ln = r & 15
        for _ in range(left):
            length[symbol] = ln
            symbol += 1
    count = [0] * (MAXBITS + 1)
    for s in range(symbol):
        count[length[s]] += 1
    if count[0] == symbol:
        return count, []
    offs = [0] * (MAXBITS + 1)
    for ln in range(1, MAXBITS):
        offs[ln + 1] = offs[ln] + count[ln]
    sym = [0] * symbol
    for s in range(symbol):
        if length[s]:
            sym[offs[length[s]]] = s
            offs[length[s]] += 1
    return count, sym


class _Implode(object):
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.bitbuf = 0
        self.bitcnt = 0
        self.window = bytearray(MAXWIN)
        self.next = 0
        self.first = True
        self.result = bytearray()
        self.litcode = _construct(_LITLEN)
        self.lencode = _construct(_LENLEN)
        self.distcode = _construct(_DISTLEN)

    def bits(self, need):
        val = self.bitbuf
        while self.bitcnt < need:
            if self.pos >= len(self.data):
                raise ImplodeError("out of input")
            val |= self.data[self.pos] << self.bitcnt
            self.pos += 1
            self.bitcnt += 8
        self.bitbuf = val >> need
        self.bitcnt -= need
        return val & ((1 << need) - 1)

    def decode(self, h):
        count, symbol = h
        bitbuf = self.bitbuf
        left = self.bitcnt
        orig_cnt = self.bitcnt
        code = first = index = 0
        ln = 1
        ci = 1
        while True:
            while left > 0:
                code |= (bitbuf & 1) ^ 1
                bitbuf >>= 1
                left -= 1
                cnt = count[ci]
                ci += 1
                if code < first + cnt:
                    self.bitbuf = bitbuf
                    self.bitcnt = (orig_cnt - ln) & 7
                    return symbol[index + (code - first)]
                index += cnt
                first += cnt
                first <<= 1
                code <<= 1
                ln += 1
            left = (MAXBITS + 1) - ln
            if left == 0:
                break
            if self.pos >= len(self.data):
                raise ImplodeError("out of input")
            bitbuf = self.data[self.pos]
            self.pos += 1
            if left > 8:
                left = 8
        return -9

    def run(self):
        lit = self.bits(8)
        if lit > 1:
            raise ImplodeError("bad literal flag")
        dict_ = self.bits(8)
        if dict_ < 4 or dict_ > 6:
            raise ImplodeError("bad dict size")
        w = self.window
        while True:
            if self.bits(1):
                symbol = self.decode(self.lencode)
                if symbol < 0:
                    raise ImplodeError("bad length code")
                ln = _BASE[symbol] + self.bits(_EXTRA[symbol])
                if ln == 519:
                    break
                dbits = 2 if ln == 2 else dict_
                dsym = self.decode(self.distcode)
                if dsym < 0:
                    raise ImplodeError("bad distance code")
                dist = (dsym << dbits) + self.bits(dbits) + 1
                if self.first and dist > self.next:
                    raise ImplodeError("distance too far back")
                while ln:
                    to = self.next
                    frm = to - dist
                    copy = MAXWIN
                    if self.next < dist:
                        frm += copy
                        copy = dist
                    copy -= self.next
                    if copy > ln:
                        copy = ln
                    ln -= copy
                    self.next += copy
                    for i in range(copy):
                        w[to + i] = w[frm + i]
                    if self.next == MAXWIN:
                        self.result.extend(w)
                        self.next = 0
                        self.first = False
            else:
                symbol = self.decode(self.litcode) if lit else self.bits(8)
                w[self.next] = symbol
                self.next += 1
                if self.next == MAXWIN:
                    self.result.extend(w)
                    self.next = 0
                    self.first = False
        self.result.extend(w[:self.next])
        return bytes(self.result)


def implode_decompress(data):
    """Decompress a PKWARE implode stream (MPQ compression type 0x08)."""
    return _Implode(data).run()


def decompress_sector(sec):
    """Decompress one MPQ sector given its compression-type first byte."""
    if not sec:
        return b""
    t = sec[0]
    if t == 0x02:
        return zlib.decompress(sec[1:], 15)
    if t == 0x10:
        return bz2.decompress(sec[1:])
    if t == 0x08:
        return implode_decompress(sec[1:])
    if t == 0x00:
        return sec[1:]
    raise ValueError("unsupported sector compression type 0x%02X" % t)


# ------------------------------------------------------------------- MPQ ------

def _prepare_crypt():
    crypt = [0] * 0x500
    seed = 0x00100001
    for i in range(256):
        index = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            t1 = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            t2 = seed & 0xFFFF
            crypt[index] = t1 | t2
            index += 0x100
    return crypt


CRYPT = _prepare_crypt()
HASH_TYPES = {"TABLE_OFFSET": 0, "HASH_A": 1, "HASH_B": 2, "TABLE": 3}


def hash_string(s, ht):
    if isinstance(s, str):
        s = s.upper().encode("utf-8")
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in s:
        v = CRYPT[(HASH_TYPES[ht] << 8) + ch]
        seed1 = (v ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed2 = (ch + seed1 + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
    return seed1


def crypt_data(data, key):
    """Decrypt (or apply the cipher) - seed2 is updated with the OUTPUT value."""
    seed1 = key
    seed2 = 0xEEEEEEEE
    out = bytearray()
    n = len(data) // 4
    for i in range(n):
        seed2 = (seed2 + CRYPT[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack_from("<I", data, i * 4)[0]
        value = (value ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed1 = (((((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111) | (seed1 >> 0x0B))) & 0xFFFFFFFF
        seed2 = (value + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
        out += struct.pack("<I", value)
    return bytes(out)


def encrypt_data(data, key):
    """Encrypt - seed2 must be updated with the PLAINTEXT value so that
    crypt_data() (which updates with the decrypted value) is its inverse."""
    seed1 = key
    seed2 = 0xEEEEEEEE
    out = bytearray()
    n = len(data) // 4
    for i in range(n):
        seed2 = (seed2 + CRYPT[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        plain = struct.unpack_from("<I", data, i * 4)[0]
        cipher = (plain ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed1 = (((((~seed1 & 0xFFFFFFFF) << 0x15) + 0x11111111) | (seed1 >> 0x0B))) & 0xFFFFFFFF
        seed2 = (plain + seed2 + ((seed2 << 5) + 3)) & 0xFFFFFFFF
        out += struct.pack("<I", cipher)
    return bytes(out)


class MPQ(object):
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.raw = f.read()
        hs, asz, fmt, sec = struct.unpack("<IIHH", self.raw[4:16])
        self.header_size = hs
        self.archive_size = asz
        self.fmt = fmt
        self.sector_shift = sec
        hoff, boff, hnum, bnum = struct.unpack("<IIII", self.raw[16:32])
        self.hash_off, self.block_off = hoff, boff
        self.hash_num, self.block_num = hnum, bnum
        hdec = crypt_data(self.raw[hoff:hoff + hnum * 16], hash_string("(hash table)", "TABLE"))
        self.hash_table = [struct.unpack_from("<IIHHI", hdec, i * 16) for i in range(hnum)]
        bdec = crypt_data(self.raw[boff:boff + bnum * 16], hash_string("(block table)", "TABLE"))
        self.block_table = [struct.unpack_from("<IIII", bdec, i * 16) for i in range(bnum)]

    def lookup_all(self, name):
        ha = hash_string(name, "HASH_A")
        hb = hash_string(name, "HASH_B")
        return [e for e in self.hash_table if e[0] == ha and e[1] == hb and e[4] != 0xFFFFFFFF]

    def lookup(self, name):
        m = self.lookup_all(name)
        return m[0][4] if m else None

    def read_by_index(self, bidx):
        off, asz, sz, fl = self.block_table[bidx]
        if not fl & 0x80000000 or asz == 0:
            return None, fl
        data = self.raw[off:off + asz]
        if fl & 0x00010000:
            raise ValueError("file-level encryption not supported")
        # flag 0x100 alone (IMPLODE) => sectors are raw implode streams (no type byte)
        # flag 0x200 (COMPRESS) => sectors carry a compression-type first byte
        typed = bool(fl & 0x00000200)
        if fl & 0x01000000:
            if fl & 0x00000300 and sz > asz:
                data = decompress_sector(data) if typed else implode_decompress(data)
            return data, fl
        sector_size = 512 << self.sector_shift
        nsect = (sz + sector_size - 1) // sector_size
        crc = bool(fl & 0x04000000)
        if crc:
            nsect += 1
        positions = struct.unpack_from("<%dI" % (nsect + 1), data, 0)
        out = bytearray()
        left = sz
        for i in range(nsect - (1 if crc else 0)):
            sec = data[positions[i]:positions[i + 1]]
            if fl & 0x00000300 and left > len(sec):
                sec = decompress_sector(sec) if typed else implode_decompress(sec)
            left -= len(sec)
            out += sec
        return bytes(out), fl

    def read(self, name):
        b = self.lookup(name)
        if b is None:
            return None, None
        return self.read_by_index(b)


# ------------------------------------------------------------------ writer ---

def build_mpq(files, hash_num=None, sector_shift=3):
    """Build a fresh MPQ (single-unit, uncompressed) from {name: bytes}.

    Used only for brand-new archives; for patch_d2 we use append_to_mpq().
    """
    entries = sorted(files.items())
    if hash_num is None:
        hash_num = 4
        while hash_num < len(entries) * 2:
            hash_num *= 2
    body = bytearray()
    block_table = []
    for name, content in entries:
        block_table.append((32 + len(body), len(content), len(content), 0x81000000))
        body += content
        body += b"\x00" * ((-len(body)) % 4)
    hash_off = 32 + len(body)
    block_off = hash_off + hash_num * 16
    total = block_off + len(entries) * 16
    hash_tbl = [None] * hash_num
    for i, (name, _c) in enumerate(entries):
        idx = hash_string(name, "TABLE_OFFSET") % hash_num
        while hash_tbl[idx] is not None:
            idx = (idx + 1) % hash_num
        hash_tbl[idx] = (hash_string(name, "HASH_A"), hash_string(name, "HASH_B"), 0, 0, i)
    hash_bytes = bytearray()
    for e in hash_tbl:
        if e is None:
            hash_bytes += struct.pack("<IIHHI", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
        else:
            hash_bytes += struct.pack("<IIHHI", *e)
    block_bytes = bytearray()
    for e in block_table:
        block_bytes += struct.pack("<IIII", *e)
    out = bytearray()
    out += b"MPQ\x1a"
    out += struct.pack("<IIHH", 32, total, 0, sector_shift)
    out += struct.pack("<IIII", hash_off, block_off, hash_num, len(entries))
    out += body
    out += encrypt_data(bytes(hash_bytes), hash_string("(hash table)", "TABLE"))
    out += encrypt_data(bytes(block_bytes), hash_string("(block table)", "TABLE"))
    return bytes(out)


def encrypt(data, key):
    return crypt_data(data, key)


def append_to_mpq(src_path, dst_path, new_files):
    """Rewrite an existing MPQ, adding/replacing files (single-unit, uncompressed).

    Keeps every original file byte-for-byte at its original offset; for names that
    already exist in the hash table the existing entry is re-pointed at the new
    block (true replacement); otherwise a new entry is placed in the first empty
    hash slot. Original tables are relocated to the end of the new archive.
    """
    mpq = MPQ(src_path)
    raw = mpq.raw
    data_end = mpq.hash_off  # original file data occupies [32, hash_off)
    for off, asz, sz, fl in mpq.block_table:
        if fl & 0x80000000 and off + asz > data_end:
            raise ValueError("file data extends past hash table offset")
    # new file data starts right after the original data region (4-aligned)
    pos = (data_end + 3) & ~3
    new_blocks = []
    body = bytearray()
    for name in sorted(new_files):
        content = new_files[name]
        new_blocks.append((pos + len(body), len(content), len(content), 0x81000000))
        body += content
        body += b"\x00" * ((-len(body)) % 4)
    # hash table: copy decrypted original, replace existing entries / fill empty slots
    hash_entries = list(mpq.hash_table)
    next_block = len(mpq.block_table)

    def is_empty(e):
        return e[0] == 0xFFFFFFFF and e[1] == 0xFFFFFFFF and e[4] == 0xFFFFFFFF

    for i, name in enumerate(sorted(new_files)):
        ha = hash_string(name, "HASH_A")
        hb = hash_string(name, "HASH_B")
        start = hash_string(name, "TABLE_OFFSET") % mpq.hash_num
        idx = start
        existing = None
        empty_slot = None
        while True:
            e = hash_entries[idx]
            if is_empty(e):
                if empty_slot is None:
                    empty_slot = idx
                break
            if e[0] == ha and e[1] == hb and e[4] != 0xFFFFFFFF:
                existing = idx
                break
            idx = (idx + 1) % mpq.hash_num
            if idx == start:
                break
        if existing is not None:
            hash_entries[existing] = (ha, hb, 0, 0, next_block + i)
        else:
            if empty_slot is None:
                # scan the whole table for any empty slot
                for j in range(mpq.hash_num):
                    if is_empty(hash_entries[j]):
                        empty_slot = j
                        break
            if empty_slot is None:
                raise ValueError("hash table full")
            hash_entries[empty_slot] = (ha, hb, 0, 0, next_block + i)
    block_table = list(mpq.block_table) + new_blocks
    hash_off = pos + len(body)
    block_off = hash_off + mpq.hash_num * 16
    total = block_off + len(block_table) * 16
    hash_bytes = bytearray()
    for e in hash_entries:
        hash_bytes += struct.pack("<IIHHI", *e)
    block_bytes = bytearray()
    for e in block_table:
        block_bytes += struct.pack("<IIII", *e)
    out = bytearray()
    out += b"MPQ\x1a"
    out += struct.pack("<IIHH", 32, total, 0, mpq.sector_shift)
    out += struct.pack("<IIII", hash_off, block_off, mpq.hash_num, len(block_table))
    out += raw[32:data_end]
    if len(out) < pos:
        out += b"\x00" * (pos - len(out))
    out += body
    out += encrypt_data(bytes(hash_bytes), hash_string("(hash table)", "TABLE"))
    out += encrypt_data(bytes(block_bytes), hash_string("(block table)", "TABLE"))
    assert len(out) == total, (len(out), total)
    with open(dst_path, "wb") as f:
        f.write(bytes(out))
    return len(new_files)
