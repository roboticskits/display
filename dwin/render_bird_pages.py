"""Render the bird face as DWIN page images: 8 moods x 3 frames (A, B, blink).
Page = 15 + 3*mood + frame. Each page has the same mood button bar at the
bottom (touch areas are written separately into 13TouchFile.bin)."""
import sys, os, json
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "stubs"))
import simcore, faketime
from simcore import S
from PIL import Image, ImageDraw, ImageFont
Image.init()
sys.modules["time"] = faketime
sys.path.insert(1, os.environ["BOARD_DIR"])
import face_reactions3 as fr
from tft import fill_rect
S.record = False

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
FIRST_PAGE = 15
MOODS = fr.REACTIONS                      # 8 moods
LABELS = list(MOODS) + ["HOME"]
font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 15)
font_small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)


def box(i):
    return (12 + (i % 5) * 94, 230 + (i // 5) * 44, 88, 38)


def face_image(mood, frame):
    """Draw the face part (y < 226) with the simulator, return a PIL image."""
    simcore.reset()
    fill_rect(0, 0, 480, 320, 0, 0, 0)
    fr._decor(mood)
    eyes = (fr._Sprite(fr.EYE_X[0], fr.EYE_Y, fr.EW, fr.EH), fr._Sprite(fr.EYE_X[1], fr.EYE_Y, fr.EW, fr.EH))
    beak = fr._Sprite(fr.BEAK_X, fr.BEAK_Y, fr.BW, fr.BH)
    alt = 1 if frame == 1 else 0
    for i, sp in enumerate(eyes):
        side = -1 if i == 0 else 1
        if frame == 2:                        # blink
            sp.clear()
            for k in range(-3, 3):
                sp.span(fr.CY + k, fr.CX - fr.RO, fr.CX + fr.RO, fr.RING)
        else:
            fr._eye(sp, side, mood, alt, 0, 0, False)
        sp.flush()
    fr._beak(beak, mood, alt)
    beak.flush()
    return S.img.copy()


def add_bar(im, selected):
    d = ImageDraw.Draw(im)
    d.rectangle((0, 226, 479, 319), fill=(0, 0, 0))
    for i, label in enumerate(LABELS):
        x, y, w, h = box(i)
        if label == "HOME":
            fill, txt = (40, 60, 110), (235, 240, 255)
        elif i == selected:
            fill, txt = (255, 150, 30), (0, 0, 0)
        else:
            fill, txt = (40, 40, 48), (240, 240, 240)
        d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=8, fill=fill)
        tw = d.textlength(label, font=font)
        d.text((x + (w - tw) / 2, y + 9), label, fill=txt, font=font)
    d.text((300, 300), "page", fill=(60, 60, 70), font=font_small)
    return im


pages = {}
for m, mood in enumerate(MOODS):
    for f in range(3):
        page = FIRST_PAGE + 3 * m + f
        im = add_bar(face_image(mood, f), m)
        ImageDraw.Draw(im).text((336, 300), str(page), fill=(60, 60, 70), font=font_small)
        path = os.path.join(OUT, "%02d.bmp" % page)
        im.convert("RGB").save(path, format="BMP")
        pages[page] = (mood, f)
        print(page, mood, f, os.path.getsize(path))

meta = {"first_page": FIRST_PAGE, "moods": list(MOODS), "frames": 3,
        "boxes": {label: box(i) for i, label in enumerate(LABELS)}}
json.dump(meta, open(os.path.join(OUT, "bird_pages.json"), "w"), indent=1)
# contact sheet
ims = [(p, Image.open(os.path.join(OUT, "%02d.bmp" % p)).convert("RGB")) for p in sorted(pages)]
cols, pad, cap = 6, 8, 20
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (240 + pad) + pad, rows * (160 + cap + pad) + pad), (40, 40, 48))
d = ImageDraw.Draw(sheet)
for i, (p, im) in enumerate(ims):
    x = pad + (i % cols) * (240 + pad); y = pad + (i // cols) * (160 + cap + pad)
    sheet.paste(im.resize((240, 160), Image.LANCZOS), (x, y))
    d.text((x + 2, y + 162), "page %d: %s %s" % (p, pages[p][0], "AB!"[pages[p][1]]), fill=(230, 230, 230), font=font_small)
sheet.save(os.path.join(OUT, "bird_pages_sheet.png"))
print("done", len(pages), "pages")
