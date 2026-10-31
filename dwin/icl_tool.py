"""Pack / unpack DWIN T5L DGUS II .icl picture libraries (format decoded from
this project's own 32.icl and 48_SensorIcons.icl).

Layout: 'DGUS_3' | chk(2) | length-after-first-8-bytes (BE32) | 04 00 |
        last_index (LE16) | offsets table (BE32 x N) | records...
record: width(2) height(2) jpeg_header_len(2) jpeg_scan_len(4) jpeg bytes
"""
import struct, sys, io


def unpack(data):
    assert data[:6] == b"DGUS_3", "not an ICL"
    chk = struct.unpack(">H", data[6:8])[0]
    total = struct.unpack(">I", data[8:12])[0]
    assert total == len(data) - 8, (total, len(data))
    n = struct.unpack("<H", data[14:16])[0] + 1
    offs = [struct.unpack(">I", data[16 + 4 * i:20 + 4 * i])[0] for i in range(n)]
    imgs = []
    for i, o in enumerate(offs):
        w, h, hl, sl = struct.unpack(">HHHI", data[o:o + 10])
        jpg = data[o + 10:o + 10 + hl + sl]
        imgs.append((w, h, hl, sl, jpg))
    return chk, imgs


def jpeg_header_len(jpg):
    """Bytes up to and including the SOS segment (start of entropy data)."""
    i = 2
    while i < len(jpg):
        assert jpg[i] == 0xFF, "bad marker at %d" % i
        m = jpg[i + 1]
        seglen = struct.unpack(">H", jpg[i + 2:i + 4])[0]
        if m == 0xDA:                       # SOS
            return i + 2 + seglen
        i += 2 + seglen
    raise ValueError("no SOS")


def checksum_candidates(data):
    body = data[8:]
    return {
        "sum16_from8": sum(body) & 0xFFFF,
        "sum16_from12": sum(data[12:]) & 0xFFFF,
        "sum16_from16": sum(data[16:]) & 0xFFFF,
        "xor16_from8": _xor16(body),
        "crc16_modbus_from8": _crc16(body, 0xA001, 0xFFFF),
        "crc16_ccitt_from8": _crc16_ccitt(body),
        "crc16_xmodem_from8": _crc16_ccitt(body, init=0),
        "sum16_words_from8": sum(struct.unpack(">%dH" % (len(body) // 2), body[:len(body) // 2 * 2])) & 0xFFFF,
    }


def _xor16(b):
    v = 0
    for i in range(0, len(b) - 1, 2):
        v ^= (b[i] << 8) | b[i + 1]
    return v


def _crc16(b, poly, init):
    crc = init
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc


def _crc16_ccitt(b, init=0xFFFF):
    crc = init
    for x in b:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def dwinify(jpg):
    """Convert a standard baseline JPEG to DWIN's layout: zero-pad the SOS
    segment so the entropy data starts 4-byte aligned within the record
    (record = 10-byte header + JPEG, records are 4-aligned), and zero-pad the
    scan (which keeps its FFD9) to a multiple of 4 bytes."""
    hl = jpeg_header_len(jpg)
    i = hl - 2
    while not (jpg[i] == 0xFF and jpg[i + 1] == 0xDA):      # find the SOS marker
        i -= 1
    ln = struct.unpack(">H", jpg[i + 2:i + 4])[0]
    pad = (-(10 + hl)) % 4
    sos = jpg[i:i + 2] + struct.pack(">H", ln + pad) + jpg[i + 4:hl] + b"\x00" * pad
    scan = jpg[hl:]
    scan += b"\x00" * ((-len(scan)) % 4)
    return jpg[:i] + sos + scan


def pack(jpgs, convert=()):
    """convert: indices of plain JPEGs to run through dwinify() first."""
    n = len(jpgs)
    recs = []
    for k, jpg in enumerate(jpgs):
        if k in convert:
            jpg = dwinify(jpg)
        # dimensions from SOF0
        i = jpg.find(b"\xff\xc0")
        h, w = struct.unpack(">HH", jpg[i + 5:i + 9])
        hl = jpeg_header_len(jpg)
        recs.append(struct.pack(">HHHI", w, h, hl, len(jpg) - hl) + jpg)
    table_end = 16 + 4 * n
    offs, o = [], table_end
    for r in recs:
        offs.append(o)
        o += len(r)
    body = b"".join(struct.pack(">I", x) for x in offs) + b"".join(recs)
    head = b"DGUS_3" + b"\x00\x00" + struct.pack(">I", 8 + len(body)) + b"\x04\x00" + struct.pack("<H", n - 1)
    data = bytearray(head + body)
    chk = _crc16(bytes(data[8:]), 0xA001, 0xFFFF)   # CRC-16/MODBUS over bytes 8..end
    data[6:8] = struct.pack("<H", chk)                # stored little-endian
    return bytes(data)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        d = open(name, "rb").read()
        chk, imgs = unpack(d)
        print(name, "images", len(imgs), "stored checksum 0x%04x" % chk)
        for k, v in checksum_candidates(d).items():
            print("   %-22s 0x%04x %s" % (k, v, "<== MATCH" if v == chk else ""))
        # header-length field check
        bad = [i for i, (w, h, hl, sl, jpg) in enumerate(imgs) if jpeg_header_len(jpg) != hl]
        print("   header_len field matches computed SOS offset for all images:", not bad, bad[:5])
