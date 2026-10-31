"""Build 48_SensorIcons.icl for DWIN DGUS II display.
Contains 88 icons:
  Icon 0: Blank solid white (for cleared/empty card slots)
  Icons 1..77: Full-color vector icons for all 77 sensors & actuators
  Icons 78..87: Arial Bold status labels for SETTINGS (56) and BLUETOOTH (58)
"""
import os, sys, io
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import icl_tool
from generate_sensors_catalog import create_device_icon, CATALOG

SETTINGS_STATUS_LABELS = (
    "NO GATEWAY",  # 78
    "OFFLINE",     # 79
    "ONLINE",      # 80
    "OFF",         # 81
    "READY",       # 82
    "PAIRED",      # 83
    "VISIBLE",     # 84
    "HIDDEN",      # 85
    "CONNECTED",   # 86
    "RESTARTING",  # 87
)
SETTINGS_STATUS_MAP = {name: 78 + i for i, name in enumerate(SETTINGS_STATUS_LABELS)}

def build_sensor_icons_icl():
    jpgs = []

    # Icon 0: Blank solid white
    im0 = Image.new("RGB", (40, 40), "white")
    buf0 = io.BytesIO()
    im0.save(buf0, format="JPEG", quality=95)
    jpgs.append(buf0.getvalue())

    # Icons 1..77: Each device centered in 40x40 white square
    for i, dev in enumerate(CATALOG):
        name = dev["name"]
        ic = create_device_icon(name)
        im = Image.new("RGB", (40, 40), "white")
        im.paste(ic, (2, 2), ic if ic.mode == "RGBA" else None)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95)
        jpgs.append(buf.getvalue())

    # Icons 78..87: Arial Bold 18pt status labels on #f7f8fc card background
    f_bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
    for label in SETTINGS_STATUS_LABELS:
        im = Image.new("RGB", (160, 24), "#f7f8fc")
        d = ImageDraw.Draw(im)
        d.text((0, 12), label, font=f_bold, fill="#192a3e", anchor="lm")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95, subsampling=0)
        jpgs.append(buf.getvalue())

    # Icons 88..90: Home page top-bar live icons (34x34 px on the blue top-bar gradient)
    #   88: Hidden / Disconnected (clean blue top-bar patch)
    #   89: Bluetooth Connected (Bluetooth symbol + green link indicator)
    #   90: Wi-Fi Connected (Wi-Fi symbol + green link indicator)
    ref_path = os.path.join(HERE, "art", "home_modern_ref.png")
    ref = Image.open(ref_path).convert("RGB")
    ic_blank = ref.crop((180, 3, 214, 37))
    ic_bt = ref.crop((346, 3, 380, 37))
    ImageDraw.Draw(ic_bt).ellipse((23, 23, 32, 32), fill="#22c55e", outline="white", width=1)
    ic_wifi = ref.crop((384, 3, 418, 37))
    ImageDraw.Draw(ic_wifi).ellipse((23, 23, 32, 32), fill="#22c55e", outline="white", width=1)
    for ic in (ic_blank, ic_bt, ic_wifi):
        buf = io.BytesIO()
        ic.save(buf, format="JPEG", quality=95, subsampling=0)
        jpgs.append(buf.getvalue())

    packed = icl_tool.pack(jpgs, convert=range(len(jpgs)))
    chk, unpacked = icl_tool.unpack(packed)
    print(f"Packed {len(jpgs)} icons into ICL ({len(packed)} bytes, CRC=0x{chk:04x})")

    # Save to DWIN_SET_bird so make_sd_card.py picks it up automatically
    bird_path = os.path.join(HERE, "DWIN_SET_bird", "48_SensorIcons.icl")
    with open(bird_path, "wb") as f:
        f.write(packed)
    print(f"Saved to {bird_path}")

    # Also save to DWIN_SET_sd if it exists
    sd_path = os.path.join(HERE, "DWIN_SET_sd", "48_SensorIcons.icl")
    if os.path.exists(os.path.dirname(sd_path)):
        with open(sd_path, "wb") as f:
            f.write(packed)
        print(f"Saved to {sd_path}")

    return packed

if __name__ == "__main__":
    build_sensor_icons_icl()
