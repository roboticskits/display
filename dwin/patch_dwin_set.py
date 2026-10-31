"""Add the bird face pages to a DWIN_SET project folder.

usage: python patch_dwin_set.py <DWIN_SET dir> <pages dir with NN.bmp + bird_pages.json>

- copies the page BMPs in
- extends the 14ShowFile.bin page table (new pages have no display controls)
- appends touch controls to 13TouchFile.bin: mood buttons jump to each
  mood's first frame page, HOME jumps to page 10
- re-points the home page's "AI PROJECTS" card (page 10) to the first bird page
Formats were decoded from this project's own files (DGUS II, T5L).
"""
import os, sys, json, shutil, struct

dst, src = sys.argv[1], sys.argv[2]
meta = json.load(open(os.path.join(src, "bird_pages.json")))
first = meta["first_page"]
moods = meta["moods"]
frames = meta["frames"]
boxes = meta["boxes"]
last_page = first + len(moods) * frames - 1
HOME_PAGE = 10

# 1. page images
for p in range(first, last_page + 1):
    shutil.copyfile(os.path.join(src, "%02d.bmp" % p), os.path.join(dst, "%02d.bmp" % p))
print("copied pages %d..%d" % (first, last_page))

# 2. 14ShowFile.bin: page table entries (count, offset) for the new pages
sf = bytearray(open(os.path.join(dst, "14ShowFile.bin"), "rb").read())
assert sf[:7] == b"\x14DGUS_2", "unexpected ShowFile header"
old_last = sf[9] | (sf[10] << 8)           # header: 0x10 table offset, then last page (little-endian)
end_off = len(sf)
assert end_off < 0x10000, "ShowFile too large for 16-bit offsets"
for p in range(old_last + 1, last_page + 1):
    o = 0x10 + p * 4
    assert o + 4 <= 0x4000, "page table overflow"
    sf[o:o + 4] = bytes((0, 0, end_off >> 8, end_off & 0xFF))      # 0 controls
sf[9], sf[10] = last_page & 0xFF, last_page >> 8
open(os.path.join(dst, "14ShowFile.bin"), "wb").write(sf)
print("ShowFile: last page %d -> %d" % (old_last, last_page))

# 3. 13TouchFile.bin: page-jump touch records (16 bytes each, 0xFFFF terminator)
tf = bytearray(open(os.path.join(dst, "13TouchFile.bin"), "rb").read())
assert tf[-2:] == b"\xff\xff"
recs = [bytes(tf[i:i + 16]) for i in range(0, len(tf) - 2, 16)]


def jump(page, box, target):
    x, y, w, h = box
    return struct.pack(">HHHHHH", page, x, y, x + w - 1, y + h - 1, target) + b"\xff\x00\x00\x00"


# re-point "AI PROJECTS" card on the home page (box (0xf4,0x36)-(0x161,0xfe) -> 12) to the bird
for i, r in enumerate(recs):
    pg, x0, y0, x1, y1, tgt = struct.unpack(">HHHHHH", r[:12])
    if pg == HOME_PAGE and (x0, y0, x1, y1) == (0xF4, 0x36, 0x161, 0xFE):
        recs[i] = r[:10] + struct.pack(">H", first) + r[12:]
        print("home page: AI PROJECTS card now jumps to page", first)

new = []
for p in range(first, last_page + 1):
    for m, mood in enumerate(moods):
        new.append(jump(p, boxes[mood], first + m * frames))
    new.append(jump(p, boxes["HOME"], HOME_PAGE))
recs.extend(new)
recs.sort(key=lambda r: struct.unpack(">H", r[:2])[0])     # keep pages ascending
open(os.path.join(dst, "13TouchFile.bin"), "wb").write(b"".join(recs) + b"\xff\xff")
print("TouchFile: %d records (+%d), %d bytes" % (len(recs), len(new), len(recs) * 16 + 2))
