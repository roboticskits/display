"""!! DO NOT USE - REFERENCE ONLY (2026-10-30) !!
The filled-rectangle list this was made for FROZE THE DISPLAY (page switching
and touch stopped until a power cycle; see DEVELOPER_NOTES "SETTINGS VALUES IN
ARIAL BOLD"). The board code that drew it was removed from dwin_get_data.py,
so running this script would only add an unused table there.

Bold-Arial letters for the board's Settings / Bluetooth / Firmware values, so
they match the page lettering (make_sd_card.py draws the pages in Arial Bold).

    python make_settings_font.py

The display paints each Basic Graphic *dot* as a 3x3 block, which cannot draw
Arial; its *filled rectangle* command (0x0004: x0, y0, x1, y1, colour) draws
exact pixels. Each letter is rendered here (1-bit, no smoothing) and split into
rectangles (row runs merged downwards, or column runs merged sideways,
whichever gives fewer). The table goes into board_r4/dwin_get_data.py between
the "# --- AFONT begin/end ---" lines: _AFONT = {char: (advance, hex)}, hex =
4 bytes per rectangle (x0, y0, x1, y1, inclusive, from the text's top-left).
"""
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "..", "board_r4", "dwin_get_data.py")
FONT, SIZE = "C:/Windows/Fonts/arialbd.ttf", 20
CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:/()#?+%"


def bitmap(ch, f):
    im = Image.new("1", (int(f.getlength(ch)) + 6, SIZE + 10), 0)
    ImageDraw.Draw(im).text((0, 0), ch, font=f, fill=1)
    return im


def merge(im, vertical):
    if vertical:
        im = im.transpose(Image.Transpose.TRANSPOSE)
    w, h = im.size
    px = im.load()
    rects, open_ = [], {}
    for y in range(h + 1):
        cur = set()
        if y < h:
            x = 0
            while x < w:
                if px[x, y]:
                    x0 = x
                    while x < w and px[x, y]:
                        x += 1
                    cur.add((x0, x - 1))
                else:
                    x += 1
        for span in list(open_):
            if span not in cur:
                y0 = open_.pop(span)
                rects.append((span[0], y0, span[1], y - 1))
        for span in cur:
            if span not in open_:
                open_[span] = y
    if vertical:
        rects = [(b, a, d, c) for a, b, c, d in rects]
    return sorted(rects, key=lambda r: (r[1], r[0]))


def main():
    f = ImageFont.truetype(FONT, SIZE)
    lines = ["# --- AFONT begin (made by dwin/make_settings_font.py: Arial Bold %d) ---" % SIZE,
             "_AFONT_SPACE = %d" % round(f.getlength(" ")),
             "_AFONT = {"]
    for ch in CHARS:
        im = bitmap(ch, f)
        h, v = merge(im, False), merge(im, True)
        rects = h if len(h) <= len(v) else v
        hexs = "".join("%02x%02x%02x%02x" % r for r in rects)
        lines.append("    %r: (%d, '%s')," % (ch, round(f.getlength(ch)), hexs))
    lines += ["}", "# --- AFONT end ---"]
    block = "\n".join(lines)
    src = open(TARGET, encoding="utf-8").read()
    if "# --- AFONT begin" in src:
        src = re.sub(r"# --- AFONT begin.*?# --- AFONT end ---", lambda m: block, src, flags=re.S)
    else:
        anchor = "\ndef _draw_settings_graphic("
        assert anchor in src
        src = src.replace(anchor, "\n" + block + "\n\n" + anchor, 1)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    print("wrote %d letters into %s" % (len(CHARS), os.path.normpath(TARGET)))


if __name__ == "__main__":
    main()
