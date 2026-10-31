"""Build the DWIN display's SD card (DWIN_SET) including the pictures saved in
the display's own memory (slots 1-3), so they can be viewed with the display
running on its own: Home > PROJECTS LIST > picture.

usage:
  python make_sd_card.py --sd E:        read pictures through the board, build, copy to SD card
  python make_sd_card.py --no-read      rebuild from saved_pictures/ (no board needed), no copy
  python make_sd_card.py --keep-memory --sd E:
                                        pages only: the pictures and the video already in the
                                        display stay (no board needed; for displays flashed before)

Pages added to the project (base = DWIN_SET_bird, pages 0-39, unchanged):
  40      PROJECTS LIST: three cards (home card now opens it)
  41-43   one saved picture each, large, with BACK (to 40) and HOME buttons
  44      VIDEO (from the PROJECTS LIST header)
  45      home page 2 (home NEXT, or swipe left on the home page): STORAGE card
  46      STORAGE: the three pictures and the video
  47-49   pictures, 50 video, opened from STORAGE (BACK goes to 46)
  51      AI PROJECTS (home card): four project types, like the web app
  52-55   one information page per type
  56      SETTINGS: live Wi-Fi gateway, Bluetooth status, board firmware text
  57-59   Wi-Fi, Bluetooth, Firmware details opened from SETTINGS
The pictures themselves are icons in 24_SavedPictures.icl (flash font ID 24),
shown by icon controls: icons 0-2 = thumbnails on page 40, 3-5 = large views.
Each icon has a fixed 32 KB-aligned place, so the board's lib.py dwin_save()
replaces it over UART: the PROJECTS LIST follows every save, no SD card needed.
This SD card only has to be flashed once; it starts with the pictures that are
in the display's memory when it is built.

Steps: read slots via the board (main.py stopped, then restarted), render pages,
append them to 32.icl, build 24_SavedPictures.icl with the board's own JPEG
encoder, add icon controls to 14ShowFile.bin and buttons to 13TouchFile.bin,
write DWIN_SET_sd/, copy it to <SD>:/DWIN_SET and verify.
"""
import os, sys, io, json, time, struct, shutil, hashlib, binascii, argparse
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "board_main"))
import icl_tool

BASE = os.path.join(HERE, "DWIN_SET_bird")       # working project, pages 0-39
OUT = os.path.join(HERE, "DWIN_SET_sd")
PICS = os.path.join(HERE, "saved_pictures")
SKIP = {"32_diagnostic.icl"}                     # test file; its name would clash with 32.icl
# Font 0: the base project's 0_ASCII_12x24.bin does not draw (text controls stay
# empty). DWIN's standard 0# font made with DGUS's DW_0Font.exe (Arial) replaces
# it when present; it fills flash font IDs 0-11. It is also what the display's
# own clock (RTC display controls on the home pages) draws with.
NEW_FONT, OLD_FONT = "0_DWIN_ASC.HZK", "0_ASCII_12x24.bin"
HAVE_FONT = os.path.exists(os.path.join(HERE, NEW_FONT))
if HAVE_FONT:
    SKIP = SKIP | {OLD_FONT}
# display's own clock on pages 10 and 45 (x, y, colour, font width, format):
# H hour 00-23, Q minute, W weekday, D day, M month, Y year (DGUS RTC codes)
RTC_FIELDS = ((122, 4, 0xFFFF, 15, "H:Q"), (204, 10, 0xFFFF, 10, "W D-M-Y"))
HOME_MODERN_REF = os.path.join(HERE, "art", "home_modern_ref.png")

HOME, LIST_PAGE, LIST_PAGE_2, FIRST_PIC = 10, 40, 41, 42
PROJECT_EXTRA_PAGES = (71, 72, 73)
PROJECT_PAGES = (LIST_PAGE, LIST_PAGE_2) + PROJECT_EXTRA_PAGES
LAST_PROJECTS_PAGE = PROJECT_EXTRA_PAGES[-1]
CATALOG_FIRST_PAGE = 79
CATALOG_TOTAL_PAGES = 13
CATALOG_PAGES = tuple(range(CATALOG_FIRST_PAGE, CATALOG_FIRST_PAGE + CATALOG_TOTAL_PAGES))
# BLUETOOTH page (58) buttons and the name keyboard (board: dwin_wifi_ui.py,
# dwin_get_data.py BT_STATE_POS / BT_LABEL_POS; ESP32 ops ble_adv/disconnect/name)
DISPLAY_BAUD = 460800                            # display UART speed (was 115200 until 2026-10-28)
BT_PAGE = 58
BT_KB_PAGE = CATALOG_PAGES[-1] + 1               # 92: Bluetooth name keyboard
BT_KB_PRESSED = BT_KB_PAGE + 1                   # 93: the same keys pressed
PROFILE_PAGE = BT_KB_PRESSED + 1                 # 94: full-size user profile image
BT_BTNS = [(18, 208, 160, 252), (170, 208, 312, 252), (322, 208, 461, 252)]
BT_BTN_CODES = [("VISIBLE ON/OFF", 0x0120), ("DISCONNECT", 0x0121), ("RENAME", 0x0122)]
BT_LABEL_POS = (246, 160)                        # board draws the name label here (dots)
BLE_PREFIX = "ESP32-BLE-CURIO_V2"
# SENSOR GRAPH (home page 2, card 3): live line chart of up to 3 sensors from the
# running program (board lib.py _graph_*). Lines are Basic Graphic line lists at
# the end of the image page's region B (a full picture ends at 0xFB22; 0xFFF0 is
# the save scratch); the legend text is a dot list at 0x5400 (shared, redrawn).
GRAPH_PAGE = PROFILE_PAGE + 1                    # 95
HOME_GRAPH_CARD = (244, 54, 353, 254)            # third card on home page 2
GRAPH_AREA = (24, 58, 466, 234)                  # plot area (lines are clipped to it)
GRAPH_LINE_VPS = (0xFB40, 0xFBE0, 0xFC80)        # = _GRAPH_VPS in lib.py, 160 words each
GRAPH_COLOURS = (0xE8E4, 0x2B7F, 0x1D67)         # = _GRAPH_COLOURS in lib.py: red, blue, green
GRAPH_LEGEND_Y = (246, 268, 290)                 # legend rows; the board writes name + value at x 48
GRAPH_KEY_VP = 0x5F70                            # = _GRAPH_KEY_VP in lib.py: row taps 0x0601-0x0603
# IOT & KIT-TO-KIT page (home page 2, card 4): live Wi-Fi, Cloud, Kit ID, Send & Receive data
IOT_PAGE = GRAPH_PAGE + 1                        # 96
HOME_IOT_CARD = (360, 54, 466, 254)              # fourth card on home page 2
IOT_KEY_VP = 0x5F80                              # = _IOT_KEY_VP on board: 0x0701 send, 0x0702 receive, 0x0703 sync
IOT_WIFI_BOX = (12, 53, 236, 113)                # tap Wi-Fi status box -> open page 57 Wi-Fi setup
IOT_BTNS = [(12, 273, 158, 310), (167, 273, 313, 310), (322, 273, 468, 310)]
IOT_BTN_SPECS = [("SEND DATA", 0x0701, "#059669"), ("RECEIVE DATA", 0x0702, "#2563eb"), ("SYNC / ID", 0x0703, "#6320ef")]
# LLM CHAT (home page 3, card 1): type a question, the AI answers. Board:
# dwin_llm_chat.py (pages + keys), lib.py LLM_URL / LLM_KEY (the API link).
HOME3 = IOT_PAGE + 1                             # 97: home page 3
CHAT_PAGE = HOME3 + 1                            # 98: the conversation
CHAT_KB_PAGE = CHAT_PAGE + 1                     # 99: question keyboard
CHAT_KB_PRESSED = CHAT_KB_PAGE + 1               # 100: the same keys pressed
HOME_CHAT_CARD = (13, 56, 121, 256)              # first card on home page 3
CHAT_KEY_VP = 0x5F90                             # = KEY_VP in dwin_llm_chat.py
CHAT_DOTS_VP = 0x1000                            # conversation text, 4200 dots max (page 39's region A:
CHAT_KB_DOTS_VP = 0x4200                         # free while page 39 is not shown); question, 1500 max
CHAT_TEXT_BOX = (10, 52, 469, 262)
CHAT_BTNS = [((12, 268, 112, 310), "UP", 0x0802), ((120, 268, 220, 310), "DOWN", 0x0803),
             ((228, 268, 328, 310), "CLEAR", 0x0804)]
CHAT_ASK_BTN = (336, 268, 468, 310)              # opens the keyboard (page change, no code)
CHAT_Q_BOX = (12, 54, 468, 125)
LAST_BUILTIN_PAGE = CHAT_KB_PRESSED              # DWIN Page Studio list pages follow this one
PROJECT_PREV_BOX = (14, 263, 134, 306)
PROJECT_NEXT_BOX = (346, 263, 466, 306)
PROJECTS_KEY_VP = 0x5F60
PLAY_KEY_CODE = 0x0501
STOP_KEY_CODE = 0x0502
PLAY_BOX = (205, 4, 278, 44)
STOP_BOX = (282, 4, 355, 44)
SETTINGS_PAGE = 56
SETTINGS_DETAIL_FIRST = 57
HOME_SETTINGS_CARD = (360, 54, 466, 254)
SETTINGS_FIELDS = (("Wi-Fi", 0x5300, 82), ("Bluetooth", 0x5320, 155),
                   ("Firmware", 0x5340, 228))
SLOTS = (1, 2, 3)
BACK_BOX = (10, 4, 53, 44)                       # same spots as the other pages
HOME_BOX = (427, 4, 467, 43)
HOME_PROJECTS_CARD = (13, 56, 121, 256)          # "PROJECTS LIST" card on the home page
CARD_COLOURS = [("#d61829", "#fde3e5"), ("#006de6", "#dceaff"), ("#ef7900", "#ffecd9")]
PURPLE, GREY = "#6320ef", "#dedfe6"
FONT = "C:/Windows/Fonts/arialbd.ttf"
LIB_SECTION = os.path.join(HERE, "..", "board_main", "lib_dwin_section.py")
ICON_LIB = 24                                    # must match _DW_LIB_ID in lib_dwin_section.py
ICON_LIB_NAME = "24_SavedPictures.icl"
PROFILE_LIB = 26                                 # reserved flash ID 26, blocks 208-215
PROFILE_NAME = "26_Profile.icl"
PROFILE_THUMB_POS = (426, 2)                     # 48x36 profile avatar in the modern blue top bar
PROFILE_TAP_BOX = (418, 0, 479, 47)
ICON_VP = 0x5200                                 # unused VP, 0 at boot: icon controls show a fixed icon
VIEW_POS = (36, 48)                              # large view (408 x 272) on pages 41-43
VIDEO_PAGE = 44                                  # VIDEO page: Animation Icon control
VIDEO_LIB = 49                                   # 49_Video.icl, flash font IDs 49-63 (from Blockly)
VIDEO_NAME = "49_Video.icl"
VIDEO_VP = 0x5210                                # 0 after power-on = playing; 1 = stopped
VIDEO_POS = (120, 104)                           # 240 x 160 frames, centred under the header
VIDEO_BTN = (290, 9, 410, 39)                    # VIDEO button in the PROJECTS LIST header
HOME2 = 45                                       # home page 2: STORAGE card
STORAGE_PAGE = 46                                # STORAGE: 3 pictures + video
STORE_PIC = 47                                   # 47-49: pictures opened from STORAGE
STORE_VIDEO = 50                                 # video opened from STORAGE
HOME_PREV_BTN = (12, 260, 136, 306)              # home page PREVIOUS / NEXT buttons
HOME_NEXT_BTN = (346, 263, 467, 308)             # NEXT went to page 11, now to home page 2
ORANGE = "#ef7900"
AI_PAGE = 51                                     # AI PROJECTS: the four project types (home card)
AI_FIRST = 52                                    # 52-55: one page per type
HOME_AI_CARD = (244, 54, 353, 254)               # "AI PROJECTS" card on the home page (was -> 15)
AI_REF = os.path.join(HERE, "art", "ai_projects_ref.png")   # web app screenshot: the pictures
SEGOE, SEGOE_B, SEGOE_I = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                           "C:/Windows/Fonts/segoeuii.ttf")
INK, MUTED, NEEDS = (30, 41, 59), (100, 116, 139), (96, 105, 123)
# title, tag, colour, tag tint, card border, picture box in AI_REF, description, needs, button
AI_TYPES = [
    ("Image Classification", "Vision AI", (37, 99, 235), (224, 234, 255), (200, 213, 241), (63, 192, 437, 432),
     "Teach AI to recognise objects, gestures, and scenes using your camera or photos.",
     "Camera or Images", "Use Pictures"),
    ("Voice Classification", "Audio AI", (124, 58, 237), (243, 232, 255), (220, 205, 253), (513, 199, 887, 438),
     "Teach AI to recognise different sounds, words, or voices.", "Microphone Needed", "Use Sounds"),
    ("Pose Classification", "Vision AI", (22, 163, 74), (231, 248, 238), (192, 231, 210), (964, 199, 1338, 438),
     "Teach AI to recognise body positions and movements.", "Camera", "Use Body Poses"),
    ("Gesture Classification", "Vision AI", (245, 158, 11), (254, 243, 212), (251, 228, 198), (1414, 199, 1788, 438),
     "Teach AI to recognise hand signs and gestures.", "Camera", "Use Hand Gestures"),
]
AI_STEPS = [("Add examples", "Show the AI some examples"), ("Train your AI", "Let it learn from them"),
            ("Test it out", "See if it gets it right")]
GESTURE_INDEX = 3                                # page AI_FIRST + 3: live results instead of the steps
# AI pages with a live result panel (board lib.py _ai_live_*: image 52, voice 53,
# pose 54, gesture 55 - the K230 classify functions open them)
AI_LIVE_INDEXES = (0, 1, 2, 3)
GESTURE_VP = 0x5400                              # dot list of the live panel (= _DW_GESTURE_VP in lib)
PROJECTS_DOTS_VP = 0x5500                        # live active sensors dot list on PROJECT_PAGES
WIFI_DOTS_VP = 0x7340                           # dedicated page 57 buffer; 1100 dots end at 0x8026
SETTINGS_GRAPHICS_VP = 0x8030                   # shared by pages 56,58,59; 230 dots end at 0x82E4
SETTINGS_DOTS_VP = SETTINGS_GRAPHICS_VP
BLUETOOTH_DOTS_VP = SETTINGS_GRAPHICS_VP
FIRMWARE_DOTS_VP = SETTINGS_GRAPHICS_VP
WIFI_KEY_VP = 0x5F00                             # key codes of the Wi-Fi keys (= KEY_VP in board dwin_wifi_ui.py)
WIFI_KB_DOTS_VP = 0x5400                         # keyboard text dot list (= DOT_VP in dwin_wifi_ui.py)
PORT_TEST_DOTS_VP = 0x6600                        # live hardware port/pin test dot buffer
PORT_TEST_KEY_VP = 0x5F50                         # return key codes for port/pin touch buttons
PORT_PAGE_DIG_IN = 74
PORT_PAGE_ANA_IN = 75
PORT_PAGE_DIG_OUT = 76
PORT_PAGE_PWM = 77
PORT_PAGE_SERVO = 78
PORT_PAGES = (PORT_PAGE_DIG_IN, PORT_PAGE_ANA_IN, PORT_PAGE_DIG_OUT, PORT_PAGE_PWM, PORT_PAGE_SERVO)
HOME_PORT_CARD = (128, 54, 236, 254)
WIFI_ROWS = [(18, 198 + 28 * i, 461, 225 + 28 * i) for i in range(4)]   # tappable network rows, page 57
WIFI_ON_BTN = (224, 158, 295, 190)
WIFI_OFF_BTN = (302, 158, 373, 190)
WIFI_SCAN_BTN = (381, 158, 461, 190)
KB_PAGES = (60, 61, 62)                          # Wi-Fi password keyboard: letters, CAPS, symbols
KB_PRESSED = (63, 64, 65)                        # the same pages with every key pressed (press effect)
KB_PW_BOX, KB_SHOW_BTN = (12, 76, 392, 102), (400, 76, 468, 102)
ANIM_PAGE = 66                                   # small animation from the "play animation" block
ANIM_VP = 0x5220                                 # = _DW_ANIM_VP in lib_dwin_section.py (0 = play)
ANIM_LIB = 28                                    # flash font ID 28, written by the board (dwin_anim)
ANIM_POS = (160, 132)                            # 160 x 104 frames, centred under the header
ANIM_SLOT_PAGES = (67, 68, 69)                   # animation memories 1-3, full page each
ANIM_LIST_PAGE = 70                              # ANIMATIONS: the three memories playing as previews
ANIM_SLOT_VP = (0x5222, 0x5224, 0x5226)          # = _DW_ANIM_VP + 2 * slot in lib (0 = play)
ANIM_SLOT_LIB = (29, 30, 31)                     # flash font IDs (= 28 + slot in lib)
ANIM_SLOT_NAMES = ("29_AnimMemory1.icl", "30_AnimMemory2.icl", "31_AnimMemory3.icl")
ANIM_LIST_POS = ((70, 56), (250, 56), (70, 188))  # previews on page 70
ANIM_BTN = (282, 9, 416, 39)                     # ANIMATIONS button in the STORAGE header
ANIM_INIT = False                                # --anim-placeholders: put "no animation" into the memories
PROFILE_INIT = False                             # --init-profile: first-time avatar placeholder only
PROFILE_TEST = False                             # --profile-test: keep icon control off boot HOME only
BRIGHT_VP = 0x0082                               # display system variable LED_Config, high byte = brightness
BRIGHT_LEVELS = (20, 40, 60, 80, 100)            # percent (0x00-0x64); 20 is the lowest so it never goes dark
BRIGHT_STRIP = (18, 274, 461, 310)               # brightness row at the bottom of SETTINGS
# DWIN Page Studio (dwin_studio.py): edits the user makes without touching this
# file - texts on any page, button targets, extra buttons, new list pages.
STUDIO_FILE = os.path.join(HERE, "studio_project.json")
STUDIO_CACHE = os.path.join(HERE, "studio_cache")  # page pictures + buttons before edits, for the studio
STUDIO_ROWS = 5                                  # rows on a studio list page
STUDIO = {}
CLOCK_BLANK = (8, 4, 305, 46)                    # baked-in "10:42 AM MON 05 OCT 2026" on the home top bar
# (VP, bytes, x0, y, x1, RGB565 colour) - must match _DW_GESTURE_FIELDS in lib_dwin_section.py
GESTURE_FIELDS = ((0x5360, 16, 24, 252, 232, 0xF4E1),      # gesture name, orange
                  (0x5370, 8, 250, 252, 360, 0x1947),      # confidence, ink
                  (0x5380, 36, 24, 280, 458, 0x63B1))      # last line received, grey


def lib_section():
    """The board's lib.py DWIN section, run on the PC (same JPEG encoder and
    icon layout as dwin_save on the board)."""
    import types
    mp = types.ModuleType("micropython")
    mp.native = lambda f: f
    sys.modules.setdefault("micropython", mp)
    ns = {"UART": None, "time": None, "asyncio": None}
    exec(compile(open(LIB_SECTION, encoding="utf-8").read(), LIB_SECTION, "exec"), ns)
    assert ns["_DW_LIB_ID"] == ICON_LIB
    return ns


def font(size):
    return ImageFont.truetype(FONT, size)


# ---------------------------------------------------------------- 1. read slots
def read_slots():
    """Return {slot: 160x106 RGB image or None}, read from the display's flash."""
    from install_file import Board
    b = Board()
    print("board on", b.port)
    if not b.enter_raw():
        sys.exit("Could not reach the board's Python prompt (close the Blockly page's USB connection).")
    b.run("try:\n stop_checker.deinit()\nexcept Exception:\n pass\nimport lib, binascii, struct\n", 60)
    b.run("def load(s):\n    res = []\n    for _ in lib._dw_show_steps(s, res):\n        pass\n    return bool(res)\n"
          "def chunk(vp, n):\n    w = lib._dw_read(vp, n)\n    if w is None:\n        print('NONE')\n        return\n"
          "    b = struct.pack('>%dH' % n, *w)\n    print(binascii.hexlify(b).decode(), binascii.crc32(b))\n")
    pics = {}
    for slot in SLOTS:
        t0 = time.time()
        if "True" not in b.run("print(load(%d))" % slot, 30):
            print("  slot %d: empty" % slot)
            pics[slot] = None
            continue
        dots = []
        for base in (0x1000, 0x8400):
            count = None
            for _ in range(5):
                parts = b.run("chunk(%d, 2)" % base, 10).split()
                if len(parts) == 2:
                    h = bytes.fromhex(parts[0])
                    count = h[2] << 8 | h[3]
                    break
            words, total, addr = [], 3 * count + 1, base + 2
            while len(words) < total:
                n = min(120, total - len(words))
                for _ in range(6):
                    parts = b.run("chunk(%d, %d)" % (addr + len(words), n), 10).split()
                    if len(parts) == 2:
                        raw = bytes.fromhex(parts[0])
                        if len(raw) == 2 * n and binascii.crc32(raw) == int(parts[1]):
                            words += [raw[2 * j] << 8 | raw[2 * j + 1] for j in range(n)]
                            break
                else:
                    sys.exit("slot %d: reading failed at %#x" % (slot, addr + len(words)))
            if words[-1] != 0xFFFF:
                sys.exit("slot %d: dot list has no end marker" % slot)
            dots += [words[3 * k:3 * k + 3] for k in range(count)]
        pics[slot] = dots_to_image(dots)
        print("  slot %d: %dx%d picture (%.0f s)" % (slot, pics[slot].width, pics[slot].height, time.time() - t0))
    print("main.py restarted:", b.back_to_main())
    return pics


def dots_to_image(dots):
    xs = sorted({d[0] for d in dots})
    ys = sorted({d[1] for d in dots})
    w, h = (xs[-1] - xs[0]) // 3 + 1, (ys[-1] - ys[0]) // 3 + 1
    im = Image.new("RGB", (w, h))
    px = im.load()
    for x, y, c in dots:
        r, g, b = c >> 11, (c >> 5) & 63, c & 31
        px[(x - xs[0]) // 3, (y - ys[0]) // 3] = (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)
    return im


# ---------------------------------------------------------------- 2. pages
def header_page(title):
    """Modern blue glossy header bar (BACK + HOME buttons), title, and dotted body."""
    ref = Image.open(HOME_MODERN_REF).convert("RGB")
    im = Image.new("RGB", (480, 320), "#eef4f8")
    tile = ref.crop((160, 260, 208, 308))
    for y in range(44, 320, 48):
        for x in range(0, 480, 48):
            im.paste(tile.crop((0, 0, min(48, 480 - x), min(48, 320 - y))), (x, y))
    blue_strip = ref.crop((180, 0, 220, 44))
    for x in range(0, 480, 40):
        im.paste(blue_strip.crop((0, 0, min(40, 480 - x), 44)), (x, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((10, 4, 52, 38), radius=8, fill="#1d4ed8", outline="#93c5fd", width=2)
    d.line([(36, 13), (24, 21), (36, 29)], fill="white", width=3)
    d.rounded_rectangle((427, 4, 469, 38), radius=8, fill="#1d4ed8", outline="#93c5fd", width=2)
    d.polygon([(448, 10), (436, 20), (460, 20)], fill="white")
    d.rectangle((440, 20, 456, 31), fill="white")
    d.rectangle((446, 24, 450, 31), fill="#1d4ed8")
    d.text((62, 21), title, font=font(20), fill="white", anchor="lm")
    return im, d


def card_box(i):
    x0 = 16 + i * 152
    return (x0, 58, x0 + 142, 290)


def thumb_pos(i):
    """Top-left of card i's thumbnail icon (120 x 80, centred in the card)."""
    x0, y0, _, _ = card_box(i)
    return x0 + 11, y0 + 46


def list_page(page_num=1):
    """Six live sensor cards on the modern blue header & dotted background."""
    im, d = header_page("")
    d.text((60, 21), "PROJECTS LIST", font=font(17), fill="white", anchor="lm")

    # PLAY button (green)
    d.rounded_rectangle((210, 8, 275, 36), radius=7, fill="#16a34a", outline="white", width=1)
    d.polygon([(220, 15), (220, 29), (232, 22)], fill="white")
    d.text((250, 22), "PLAY", font=font(12), fill="white", anchor="mm")

    # STOP button (red)
    d.rounded_rectangle((285, 8, 350, 36), radius=7, fill="#dc2626", outline="white", width=1)
    d.rectangle((295, 16, 307, 28), fill="white")
    d.text((326, 22), "STOP", font=font(12), fill="white", anchor="mm")

    # LIVE badge (green pill)
    d.rounded_rectangle((360, 9, 420, 35), radius=10, fill="#00a76a")
    d.ellipse((368, 18, 376, 26), fill="white")
    d.text((397, 22), "LIVE", font=font(12), fill="white", anchor="mm")

    colours = (
        ("#d7192d", "#ffe1e3"), ("#0872df", "#d8e7ff"),
        ("#ee8300", "#ffecd0"), ("#009aa6", "#d3f3f5"),
        ("#681cef", "#e9dfff"), ("#00a16a", "#dcf7e8"),
    )
    for i, (bright, pale) in enumerate(colours):
        x0 = 14 + (i % 3) * 154
        y0 = 56 + (i // 3) * 103
        x1, y1 = x0 + 142, y0 + 92
        d.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=pale, outline="#1e3a8a", width=2)
        d.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 31), radius=9, fill=bright)
        d.rectangle((x0 + 2, y0 + 19, x1 - 2, y0 + 26), fill=bright)
        d.line((x0 + 2, y0 + 26, x1 - 2, y0 + 26), fill="#1e3a8a", width=2)
        d.rounded_rectangle((x0 + 8, y0 + 35, x0 + 52, y0 + 80), radius=7,
                            fill="white", outline="#1e3a8a", width=2)

    for box, label, active, left in (
        (PROJECT_PREV_BOX, "PREVIOUS", page_num > 1, True),
        (PROJECT_NEXT_BOX, "NEXT", page_num < len(PROJECT_PAGES), False),
    ):
        x0, y0, x1, y1 = box
        d.rounded_rectangle(box, radius=11, fill="#0260d8" if active else "#163a66",
                            outline="#93c5fd" if active else "#3b6598", width=2)
        colour = "white" if active else "#94a3b8"
        d.text(((x0 + x1) // 2 + (8 if left else -8), (y0 + y1) // 2), label,
               font=font(15), fill=colour, anchor="mm")
        if left:
            d.line(((x0 + 24, y0 + 13), (x0 + 15, y0 + 22), (x0 + 24, y0 + 31)),
                   fill=colour, width=4, joint="curve")
        else:
            d.line(((x1 - 24, y0 + 13), (x1 - 15, y0 + 22), (x1 - 24, y0 + 31)),
                   fill=colour, width=4, joint="curve")
    d.text((240, 271), "PAGE %d / %d" % (page_num, len(PROJECT_PAGES)),
           font=font(16), fill="#091e42", anchor="mm")
    for i in range(len(PROJECT_PAGES)):
        x = 196 + i * 22
        d.ellipse((x - 5, 290, x + 5, 300), fill="#0260d8" if i == page_num - 1 else "white",
                  outline="#1e3a8a", width=2)
    return im


def picture_page(slot):
    """Picture page background: header with BACK / HOME, black body; the
    picture is an icon control at VIEW_POS."""
    im, d = header_page("IMAGE %d" % slot)
    d.rectangle((0, 48, 479, 319), fill="black")
    return im


def profile_page():
    """Full-size profile photo; icon 1 of library 26 fills the black body."""
    im, d = header_page("PROFILE IMAGE")
    d.rectangle((0, 48, 479, 319), fill="black")
    return im


def profile_placeholder():
    """Initial library only; omit it on later SD updates to retain uploads."""
    thumb = Image.new("RGB", (48, 36), "#295a9b")
    d = ImageDraw.Draw(thumb)
    d.ellipse((20, 6, 28, 14), fill="white")
    d.ellipse((14, 18, 34, 38), fill="white")
    view = Image.new("RGB", (408, 272), "#172943")
    d = ImageDraw.Draw(view)
    d.ellipse((172, 58, 236, 122), fill="#c8dafa")
    d.ellipse((123, 136, 285, 300), fill="#c8dafa")
    d.text((204, 242), "UPLOAD PROFILE IMAGE", font=font(18), fill="white", anchor="mm")
    data = icl_tool.pack([jpeg(thumb), jpeg(view)], convert={0, 1})
    assert len(data) <= 8 * 32768, "profile placeholder exceeds font ID 26"
    return data


def empty_picture(slot):
    """Stand-in icon for a memory that has no picture yet (160 x 106)."""
    im = Image.new("RGB", (160, 106), "#2b2d33")
    d = ImageDraw.Draw(im)
    d.text((80, 44), "EMPTY", font=font(20), fill="#c9cdd6", anchor="mm")
    d.text((80, 70), "memory %d" % slot, font=font(12), fill="#9a9ba3", anchor="mm")
    return im


def icon_library(pics):
    """24_SavedPictures.icl: header + 6 icons at fixed 32 KB blocks, made with
    the board's own encoder so dwin_save() can replace them in place."""
    ns = lib_section()
    blocks = 1 + 3 + 3 * 3                       # header, 3 thumbnails, 3 large views (3 blocks each)
    data = bytearray(b"\xff" * (blocks * 32768))
    offsets = []
    for kind, (tw, th), cap in (("thumb", ns["_DW_THUMB"], 1), ("view", ns["_DW_VIEW"], 3)):
        for slot in SLOTS:
            pic = pics.get(slot) or empty_picture(slot)
            pix = bytearray()                          # RGB565 big-endian, as on the board
            for r, g, b in pic.getdata():
                v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pix += bytes((v >> 8, v & 255))
            thumb_blk, view_blk = ns["_dw_icon_blocks"](slot)
            off = ((thumb_blk if kind == "thumb" else view_blk) - ICON_LIB * 8) * 32768
            offsets.append(off)
            rec = bytearray(cap * 32768)

            def sink(chunk, roff, rec=rec):
                rec[roff:roff + len(chunk)] = bytes(chunk)
                yield from ()
            q = ns["_DW_QUALITY"]
            while True:
                try:
                    gen = ns["_dw_jpeg_steps"](pix, pic.width, pic.height, tw, th, q, sink)
                    while True:
                        next(gen)
                except StopIteration as e:
                    n = e.value
                    break
                except IndexError:
                    q -= 15
            data[off:off + n] = rec[:n]
    head = b"DGUS_3\x00\x00" + struct.pack(">I", len(data) - 8) + b"\x04\x00" + struct.pack("<H", len(offsets) - 1)
    head += b"".join(struct.pack(">I", o) for o in offsets)
    data[:len(head)] = head
    data[6:8] = struct.pack("<H", icl_tool._crc16(bytes(data[8:]), 0xA001, 0xFFFF))
    return bytes(data)


def icon_control(x, y, icon, lib=ICON_LIB):
    """14ShowFile variable-icon record that always shows one icon of ICON_LIB."""
    return (b"\x5a\x00\xff\xff\x00\x0a" + struct.pack(">HHHHHHH", ICON_VP, x, y, 0, 0, icon, icon)
            + bytes((lib, 0x01, 0, 0, 0, 0x3F)) + bytes(6))


def variable_icon_control(vp, x, y, lib=48, vmin=0, vmax=98):
    """14ShowFile variable-icon record that dynamically displays an icon based on VP value."""
    return (b"\x5a\x00\xff\xff\x00\x0a"
            + struct.pack(">HHHHHH", vp, x, y, vmin, vmax, vmin)
            + struct.pack(">HB", vmax, lib)
            + b"\x00\x00\x00\x00\x3f"
            + b"\x00" * 6)


PROJECT_CARD_ICONS = [
    (0x6110, 24, 93),
    (0x6210, 178, 93),
    (0x6310, 332, 93),
    (0x6410, 24, 196),
    (0x6510, 178, 196),
    (0x6610, 332, 196),
]


def video_page():
    """VIDEO page background; the frames are an Animation Icon control."""
    im, d = header_page("VIDEO")
    d.rectangle((0, 48, 479, 319), fill="black")
    x, y = VIDEO_POS
    d.rectangle((x - 3, y - 3, x + 242, y + 162), outline="#6320ef", width=2)
    d.text((240, 292), "Send a video from Blockly: click the picture in the play video block",
           font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13), fill="#9a9ba3", anchor="mm")
    return im


def settings_page():
    """Static labels; R4 main.py fills the three dynamic VP text controls."""
    im, d = header_page("SETTINGS")
    for i, (label, _, y) in enumerate(SETTINGS_FIELDS):
        d.rounded_rectangle((18, y - 19, 461, y + 41), radius=10,
                            fill="#f7f8fc", outline="#d9ddea", width=2)
        d.text((31, y - 10), label, font=font(16), fill="#303a55")
        d.text((444, y + 12), ">", font=font(19), fill=PURPLE, anchor="mm")
    d.rounded_rectangle(BRIGHT_STRIP, radius=10, fill="#f7f8fc", outline="#d9ddea", width=2)
    cx, cy = 40, (BRIGHT_STRIP[1] + BRIGHT_STRIP[3]) // 2      # small sun
    d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill="#f59e0b")
    for k in range(8):
        import math
        a = k * math.pi / 4
        d.line((cx + 9 * math.cos(a), cy + 9 * math.sin(a), cx + 12 * math.cos(a), cy + 12 * math.sin(a)),
               fill="#f59e0b", width=2)
    d.text((58, cy), "Brightness", font=font(15), fill="#303a55", anchor="lm")
    for box, level in zip(bright_boxes(), BRIGHT_LEVELS):
        d.rounded_rectangle(box, radius=7, fill="white", outline=PURPLE, width=2)
        d.text(((box[0] + box[2]) // 2, cy), "%d%%" % level, font=font(13), fill=PURPLE, anchor="mm")
    return im


def bright_boxes():
    """The five brightness buttons in the SETTINGS strip."""
    return [(170 + i * 58, BRIGHT_STRIP[1] + 5, 222 + i * 58, BRIGHT_STRIP[3] - 5) for i in range(len(BRIGHT_LEVELS))]


def settings_detail_page(index):
    label = SETTINGS_FIELDS[index][0]
    im, d = header_page(label.upper())
    d.rounded_rectangle((18, 73, 461, 146), radius=10,
                        fill="#f7f8fc", outline="#d9ddea", width=2)
    d.text((31, 84), "Current status", font=font(16), fill="#303a55")
    messages = (
        (),
        ("Live BLE status from the ESP32-S3 gateway.", "Advertises as ESP32-BLE-CURIO_V2 (UART6 bridge)."),
        ("Version comes from the STM32 board.", ""),
    )
    if index == 1:                                 # BLUETOOTH: status, name, three buttons
        im, d = header_page(label.upper())
        small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
        d.rounded_rectangle((18, 58, 461, 128), radius=10, fill="#f7f8fc", outline="#d9ddea", width=2)
        d.text((31, 64), "Status", font=small, fill="#727d91")
        d.rounded_rectangle((18, 136, 461, 198), radius=10, fill="#f7f8fc", outline="#d9ddea", width=2)
        d.text((31, 142), "Name that phones and the app see", font=small, fill="#727d91")
        d.text((BT_LABEL_POS[0] - 6, 171), BLE_PREFIX + "-", font=font(15), fill="#303a55", anchor="rm")
        for (x0, y0, x1, y1), (label, _) in zip(BT_BTNS, BT_BTN_CODES):
            d.rounded_rectangle((x0, y0, x1, y1), radius=9, fill=PURPLE, outline="black", width=2)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=font(14), fill="white", anchor="mm")
        d.text((29, 266), "Hidden: phones cannot find the board.", font=small, fill="#3b4660")
        d.text((29, 286), "Renaming restarts Bluetooth and Wi-Fi (about 10 s).", font=small, fill="#3b4660")
        return im
    if index == 0:
        d.text((29, 160), "AVAILABLE NETWORKS", font=font(15), fill="#303a55")
        d.text((29, 180), "Tap network when ON", font=font(12), fill="#727d91")
        for box in WIFI_ROWS:                      # the board draws the network names inside
            d.rounded_rectangle(box, radius=7, fill="#f7f8fc", outline="#d9ddea", width=2)
            d.text((box[2] - 14, (box[1] + box[3]) // 2), ">", font=font(15), fill=PURPLE, anchor="mm")
        for box, label, fill in ((WIFI_ON_BTN, "ON", "#008a52"),
                                 (WIFI_OFF_BTN, "OFF", "#c9283d")):
            d.rounded_rectangle(box, radius=8, fill=fill, outline="black", width=2)
            d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2),
                   label, font=font(14), fill="white", anchor="mm")
        x0, y0, x1, y1 = WIFI_SCAN_BTN
        d.rounded_rectangle(WIFI_SCAN_BTN, radius=8, fill=PURPLE, outline="black", width=2)
        d.text(((x0 + x1) // 2, (y0 + y1) // 2), "SCAN", font=font(14), fill="white", anchor="mm")
    for j, line in enumerate(messages[index]):
        if line:
            d.text((29, 187 + j * 29), line, font=font(14), fill="#3b4660")
    return im


def settings_text_control(vp, y):
    """Clone a known working 0x11 text control from the base project."""
    sf = open(os.path.join(BASE, "14ShowFile.bin"), "rb").read()
    entry = 0x10 + 11 * 4
    off = int.from_bytes(sf[entry + 2:entry + 4], "big")
    rec = bytearray(sf[off:off + 32])
    assert rec[:2] == b"\x5a\x11" and len(rec) == 32
    rec[6:8] = struct.pack(">H", vp)
    rec[8:12] = struct.pack(">HH", 32, y)
    rec[14:22] = struct.pack(">HHHH", 32, y, 450, y + 27)
    rec[22:24] = struct.pack(">H", 28)
    return bytes(rec)


def project_text_controls():
    """Native font text on each sensor card; six cards share a 96-word VP buffer."""
    records = []
    for i in range(6):
        x = 14 + (i % 3) * 154
        y = 56 + (i // 3) * 103
        for value, vp, x0, y0, x1, y1, colour in (
            (False, PROJECTS_TEXT_VP + i * 0x10, x + 9, y + 1, x + 133, y + 25, 0xFFFF),
            (True, PROJECTS_TEXT_VP + i * 0x10 + 8, x + 57, y + 43, x + 135, y + 72, 0x1947),
        ):
            rec = bytearray(settings_text_control(vp, y0))
            rec[8:12] = struct.pack(">HH", x0, y0)
            rec[12:14] = struct.pack(">H", colour)
            rec[14:22] = struct.pack(">HHHH", x0, y0, x1, y1)
            rec[22:24] = struct.pack(">H", 16)
            # The display's tested 12x24 font draws correctly; the trial 8x16
            # setting rendered as broken glyph fragments on the real screen.
            rec[26:28] = bytes((12, 24))
            records.append(bytes(rec))
    return records


def gesture_text_control(vp, nbytes, x0, y, x1, colour):
    """Text field on the gesture page, from the same base record as the settings
    fields (12 x 24 ASCII font)."""
    rec = bytearray(settings_text_control(vp, y))
    rec[8:12] = struct.pack(">HH", x0, y)
    rec[12:14] = struct.pack(">H", colour)
    rec[14:22] = struct.pack(">HHHH", x0, y, x1, y + 27)
    rec[22:24] = struct.pack(">H", nbytes)
    return bytes(rec)


def gesture_dot_control():
    """Basic Graphic control for the live gesture panel: a copy of page 39's
    dot-list control (the image page, known to draw on this display) reading
    VP GESTURE_VP. The board draws the text as dots (lib _dw_gesture_show);
    text-display controls stay empty because 0_ASCII_12x24.bin does not draw."""
    sf = open(os.path.join(BASE, "14ShowFile.bin"), "rb").read()
    entry = 0x10 + 39 * 4
    off = int.from_bytes(sf[entry + 2:entry + 4], "big")
    rec = bytearray(sf[off:off + 32])
    assert rec[:2] == b"\x5a\x21" and len(rec) == 32
    rec[6:8] = struct.pack(">H", GESTURE_VP)
    return bytes(rec)


def wifi_dot_control():
    """Basic Graphic dot list, as used by the working live gesture page."""
    rec = bytearray(gesture_dot_control())
    rec[6:8] = struct.pack(">H", WIFI_DOTS_VP)
    return bytes(rec)


def settings_dot_control(vp):
    """Graphic text for Settings; the display corrupts its 0x11 text controls."""
    rec = bytearray(gesture_dot_control())
    rec[6:8] = struct.pack(">H", vp)
    return bytes(rec)


def rtc_control(x, y, colour, width, fmt):
    """RTC Display (text) record, type 0x12: the display shows its own clock in
    the given format with font library 0; no board needed once the clock is set."""
    code = fmt.encode("ascii")[:15]
    return (b"\x5a\x12\xff\xff\x00\x0d" + struct.pack(">HHHH", 0, x, y, colour)
            + bytes((0, width)) + code + bytes(16 - len(code)))


def clock_controls():
    """The display's RTC controls draw the readable HOME clock."""
    return [rtc_control(*f) for f in RTC_FIELDS] if HAVE_FONT else []


_MODERN_CARDS = (
    (8, 51, 121, 249, 64, 123, (0, 92, 218)),     # Card 1: Blue
    (125, 51, 238, 249, 181, 123, (0, 125, 132)), # Card 2: Teal
    (242, 51, 355, 249, 298, 123, (198, 14, 108)),# Card 3: Magenta
    (359, 51, 472, 249, 415, 123, (0, 92, 218)),  # Card 4: Blue
)


def _clean_modern_card(im, idx):
    """Clear the inner circle icon and bottom label text of a 3D glossy card shell."""
    x0, y0, x1, y1, cx, cy, _ = _MODERN_CARDS[idx]
    px = im.load()
    for y in range(cy - 31, cy + 32):
        t = (y - (cy - 31)) / 62.0
        if idx in (0, 3):
            c = (int(242 - t * 68), int(250 - t * 32), int(255 - t * 2))
        elif idx == 1:
            c = (int(242 - t * 65), int(255 - t * 8), int(254 - t * 10))
        else:
            c = (int(255 - t * 4), int(244 - t * 28), int(252 - t * 10))
        for x in range(cx - 31, cx + 32):
            if (x - cx) ** 2 + (y - cy) ** 2 <= 30.5 ** 2:
                px[x, y] = c
    sample_x = x0 + 8
    for y in range(190, 243):
        bg = px[sample_x, y]
        for x in range(x0 + 8, x1 - 8):
            px[x, y] = bg


def home_page():
    """Home page 10: modern 3D glossy card design (1 / 3) with clean top-right
    header area for live Bluetooth (0x5366), Wi-Fi (0x5368), and Profile Image."""
    im = Image.open(HOME_MODERN_REF).convert("RGB")
    blue_strip = im.crop((180, 0, 220, 42))
    for x in range(340, 478, 40):
        im.paste(blue_strip.crop((0, 0, min(40, 478 - x), 42)), (x, 0))
    return im


def home2_page():
    """Home page 2 (2 / 3): STORAGE MEDIA, PORT & PIN MANAGER, SENSOR GRAPH, IOT & KIT-TO-KIT."""
    from PIL import ImageOps
    src = home_page()
    p2 = src.copy()
    for i in range(4):
        _clean_modern_card(p2, i)
    d2 = ImageDraw.Draw(p2)

    # Card 1: STORAGE MEDIA
    cx, cy, col = _MODERN_CARDS[0][4], _MODERN_CARDS[0][5], _MODERN_CARDS[0][6]
    d2.rounded_rectangle((cx - 22, cy - 16, cx + 22, cy + 16), radius=4, outline=col, width=4)
    d2.polygon([(cx - 16, cy + 11), (cx - 4, cy - 4), (cx + 7, cy + 11)], fill=col)
    d2.ellipse((cx + 5, cy - 10, cx + 13, cy - 2), fill=col)
    d2.text((cx, 208), "STORAGE", font=font(15), fill="white", anchor="mm")
    d2.text((cx, 226), "MEDIA", font=font(14), fill="white", anchor="mm")

    # Card 2: PORT & PIN MANAGER
    cx, cy, col = _MODERN_CARDS[1][4], _MODERN_CARDS[1][5], _MODERN_CARDS[1][6]
    d2.rounded_rectangle((cx - 16, cy - 16, cx + 16, cy + 16), radius=3, outline=col, width=4)
    d2.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=col)
    for off in (-10, 0, 10):
        d2.line([(cx + off, cy - 24), (cx + off, cy - 16)], fill=col, width=3)
        d2.line([(cx + off, cy + 16), (cx + off, cy + 24)], fill=col, width=3)
        d2.line([(cx - 24, cy + off), (cx - 16, cy + off)], fill=col, width=3)
        d2.line([(cx + 16, cy + off), (cx + 24, cy + off)], fill=col, width=3)
    d2.text((cx, 208), "PORT & PIN", font=font(14), fill="white", anchor="mm")
    d2.text((cx, 226), "MANAGER", font=font(14), fill="white", anchor="mm")

    # Card 3: SENSOR GRAPH
    cx, cy, col = _MODERN_CARDS[2][4], _MODERN_CARDS[2][5], _MODERN_CARDS[2][6]
    d2.line([(cx - 20, cy - 18), (cx - 20, cy + 18), (cx + 22, cy + 18)], fill=col, width=4)
    d2.line([(cx - 16, cy + 10), (cx - 5, cy - 4), (cx + 5, cy + 4), (cx + 19, cy - 14)], fill=col, width=4)
    for gx, gy in ((cx - 16, cy + 10), (cx - 5, cy - 4), (cx + 5, cy + 4), (cx + 19, cy - 14)):
        d2.ellipse((gx - 3, gy - 3, gx + 3, gy + 3), fill=col)
    d2.text((cx, 208), "SENSOR", font=font(15), fill="white", anchor="mm")
    d2.text((cx, 226), "GRAPH", font=font(15), fill="white", anchor="mm")

    # Card 4: IOT & KIT-TO-KIT
    cx, cy, col = _MODERN_CARDS[3][4], _MODERN_CARDS[3][5], _MODERN_CARDS[3][6]
    d2.ellipse((cx - 15, cy - 18, cx + 7, cy + 2), fill=col)
    d2.ellipse((cx - 3, cy - 14, cx + 19, cy + 4), fill=col)
    d2.ellipse((cx - 21, cy - 10, cx - 3, cy + 4), fill=col)
    d2.rectangle((cx - 15, cy - 4, cx + 13, cy + 4), fill=col)
    d2.line([(cx - 10, cy + 4), (cx - 14, cy + 16)], fill=col, width=3)
    d2.line([(cx + 10, cy + 4), (cx + 14, cy + 16)], fill=col, width=3)
    d2.line([(cx - 14, cy + 16), (cx + 14, cy + 16)], fill=col, width=3)
    d2.ellipse((cx - 19, cy + 12, cx - 9, cy + 22), fill=col)
    d2.ellipse((cx + 9, cy + 12, cx + 19, cy + 22), fill=col)
    d2.text((cx, 208), "IOT &", font=font(15), fill="white", anchor="mm")
    d2.text((cx, 226), "KIT-TO-KIT", font=font(14), fill="white", anchor="mm")

    # Active PREVIOUS button + PAGE 2 / 3
    next_btn = src.crop((326, 260, 470, 310))
    prev_active = ImageOps.mirror(next_btn)
    px_p = prev_active.load()
    for y in range(10, 40):
        for x in range(38, 128):
            px_p[x, y] = px_p[40, y]
    dp = ImageDraw.Draw(prev_active)
    dp.text((82, 25), "PREVIOUS", font=font(15), fill="white", anchor="mm")
    p2.paste(prev_active, (10, 260))

    bg_patch = src.crop((165, 260, 205, 312))
    p2.paste(bg_patch, (212, 260))
    p2.paste(bg_patch, (235, 260))
    d2.text((240, 269), "PAGE", font=font(11), fill="#0f2547", anchor="mm")
    d2.text((240, 291), "2 / 3", font=font(24), fill="#091e42", anchor="mm")
    return p2


def home_nav(d, page, pages):
    """PREVIOUS / NEXT buttons (NEXT greyed on the last page) and 'PAGE n / m'."""
    for (bx0, by0, bx1, by1), label, active in ((HOME_PREV_BTN, "PREVIOUS", True),
                                                (HOME_NEXT_BTN, "NEXT", page < pages)):
        fill, edge, ink = (PURPLE, "black", "white") if active else (GREY, "#a0a2af", "#7a7c8a")
        d.rounded_rectangle((bx0, by0, bx1, by1), radius=9, fill=fill, outline=edge, width=3)
        my = (by0 + by1) // 2
        if label == "PREVIOUS":
            d.line([(bx0 + 22, my - 8), (bx0 + 14, my), (bx0 + 22, my + 8)], fill=ink, width=4)
            d.text(((bx0 + bx1) // 2 + 8, my), label, font=font(14), fill=ink, anchor="mm")
        else:
            d.line([(bx1 - 22, my - 8), (bx1 - 14, my), (bx1 - 22, my + 8)], fill=ink, width=4)
            d.text(((bx0 + bx1) // 2 - 8, my), label, font=font(17), fill=ink, anchor="mm")
    d.text((240, 274), "PAGE", font=font(13), fill="black", anchor="mm")
    d.text((240, 295), "%d / %d" % (page, pages), font=font(19), fill="black", anchor="mm")


def home3_page():
    """Home page 3 (3 / 3): LLM CHAT card in the first slot; dotted background for slots 2-4."""
    from PIL import ImageOps
    src = home_page()
    p3 = home2_page()
    tile = src.crop((160, 260, 208, 308))
    for y in range(48, 256, 48):
        for x in range(124, 479, 48):
            w = min(48, 479 - x)
            h = min(48, 256 - y)
            p3.paste(tile.crop((0, 0, w, h)), (x, y))
    _clean_modern_card(p3, 0)
    d3 = ImageDraw.Draw(p3)
    cx, cy, col = _MODERN_CARDS[0][4], _MODERN_CARDS[0][5], _MODERN_CARDS[0][6]
    d3.rounded_rectangle((cx - 22, cy - 18, cx + 8, cy + 2), radius=6, fill="#7aa7e8")
    d3.polygon([(cx - 16, cy + 1), (cx - 20, cy + 9), (cx - 9, cy + 1)], fill="#7aa7e8")
    d3.rounded_rectangle((cx - 6, cy - 4, cx + 24, cy + 16), radius=6, fill=col)
    d3.polygon([(cx + 12, cy + 15), (cx + 20, cy + 23), (cx + 19, cy + 15)], fill=col)
    for k in (-1, 0, 1):
        d3.ellipse((cx + 9 + k * 7 - 2, cy + 4, cx + 9 + k * 7 + 2, cy + 8), fill="white")
    d3.text((cx, 208), "LLM", font=font(15), fill="white", anchor="mm")
    d3.text((cx, 226), "CHAT", font=font(15), fill="white", anchor="mm")

    prev_dark = src.crop((10, 260, 154, 310))
    next_dark = ImageOps.mirror(prev_dark)
    px_n = next_dark.load()
    for y in range(10, 40):
        for x in range(16, 108):
            px_n[x, y] = px_n[106, y]
    dn = ImageDraw.Draw(next_dark)
    dn.text((62, 25), "NEXT", font=font(16), fill="white", anchor="mm")
    p3.paste(next_dark, (326, 260))

    bg_patch = src.crop((165, 260, 205, 312))
    p3.paste(bg_patch, (212, 260))
    p3.paste(bg_patch, (235, 260))
    d3.text((240, 269), "PAGE", font=font(11), fill="#0f2547", anchor="mm")
    d3.text((240, 291), "3 / 3", font=font(24), fill="#091e42", anchor="mm")
    return p3


def chat_page():
    """LLM CHAT: the board writes the conversation as dots inside CHAT_TEXT_BOX;
    UP / DOWN scroll it, CLEAR starts again, ASK opens the keyboard."""
    im, d = header_page("LLM CHAT")
    d.rounded_rectangle(CHAT_TEXT_BOX, radius=8, fill="white", outline="#c7cbe0", width=2)
    for box, label, _ in CHAT_BTNS:
        d.rounded_rectangle(box, radius=8, fill="#d9ddea", outline="#9aa0b4", width=2)
        d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, font=font(15), fill="#303a55",
               anchor="mm")
    x0, y0, x1, y1 = CHAT_ASK_BTN
    d.rounded_rectangle(CHAT_ASK_BTN, radius=8, fill=PURPLE, outline="black", width=2)
    d.text(((x0 + x1) // 2, (y0 + y1) // 2), "ASK", font=font(17), fill="white", anchor="mm")
    return im


def chat_rows():
    """Question keyboard (page 99): small letters, digits, , . ? and SEND."""
    def keys(s):
        return [(c, ord(c), 1) for c in s]
    return [keys("1234567890"), keys("qwertyuiop"), keys("asdfghjkl") + [("DEL", 8, 1)],
            keys("zxcvbnm,.?"),
            [("CANCEL", ("page", CHAT_PAGE), 2), ("CLEAR", 0x0805, 2), ("SPACE", 32, 3), ("SEND", 13, 3)]]


def chat_kb_page(pressed):
    """Question keyboard; pressed=True draws every key held down (press effect page)."""
    im, d = header_page("ASK THE AI")
    d.rounded_rectangle(CHAT_Q_BOX, radius=7, fill="#f7f8fc", outline=PURPLE, width=2)
    for box, label, code in kb_keys(None, chat_rows()):
        if code == 13:
            fill, ink = ((15, 110, 50) if pressed else (22, 163, 74)), "white"
        elif pressed:
            fill, ink = PURPLE, "white"
        elif len(label) > 1:
            fill, ink = "#d9ddea", "#303a55"
        else:
            fill, ink = "#eef0f6", "#1e293b"
        d.rounded_rectangle(box, radius=6, fill=fill, outline="#b9bfcf", width=1)
        d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label,
               font=font(17) if len(label) == 1 else font(12), fill=ink, anchor="mm")
    return im


def rgb565(c):
    """RGB565 colour as an (r, g, b) tuple for drawing."""
    return ((c >> 11) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3)


def graph_page():
    """SENSOR GRAPH background: plot frame with grid, three legend rows with the
    line colours; the board draws the lines and the names / values."""
    im, d = header_page("SENSOR GRAPH")
    x0, y0, x1, y1 = GRAPH_AREA
    d.rounded_rectangle((x0 - 8, y0 - 6, x1 + 8, y1 + 6), radius=8, fill="#f7f8fc", outline="#d9ddea", width=2)
    for k in range(1, 4):                          # light grid
        y = y0 + k * (y1 - y0) // 4
        d.line((x0, y, x1, y), fill="#e3e6ef", width=1)
    d.text(((x0 + x1) // 2, (y0 + y1) // 2), "Run a program that reads sensors",
           font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12), fill="#c9cdd6", anchor="mm")
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 11)
    d.text((x1, y1 + 8), "last 30 s  ->  now", font=small, fill="#9aa0b4", anchor="ra")
    d.text((x1, y1 + 28), "more than 3 sensors:", font=small, fill="#9aa0b4", anchor="ra")
    d.text((x1, y1 + 44), "tap a row to change it", font=small, fill="#9aa0b4", anchor="ra")
    for c, y in zip(GRAPH_COLOURS, GRAPH_LEGEND_Y):
        d.rounded_rectangle((26, y + 3, 40, y + 17), radius=3, fill=rgb565(c))
    return im


def graph_line_control(vp):
    """Basic Graphic control (copy of page 39's) reading a line list at vp,
    clipped to the plot area."""
    rec = bytearray(gesture_dot_control())
    rec[6:8] = struct.pack(">H", vp)
    rec[8:16] = struct.pack(">HHHH", *GRAPH_AREA)
    return bytes(rec)


def iot_page():
    """IOT & KIT-TO-KIT page (96): static dashboard frames for Wi-Fi Connected,
    Cloud Connected, Kit Name/ID, Send Data (TX), Receive Data (RX) and action
    buttons; the board draws the live statuses and values into VP 0x5400."""
    im, d = header_page("IOT & KIT-TO-KIT")

    # 1. Top Row: WI-FI STATUS (left) & CLOUD STATUS (right)
    # Left Card: WI-FI
    d.rounded_rectangle((12, 53, 236, 113), radius=9, fill="white", outline="#cbd5e1", width=2)
    d.rounded_rectangle((12, 53, 236, 75), radius=7, fill="#eef2ff")
    d.rectangle((12, 68, 236, 75), fill="#eef2ff")
    d.ellipse((22, 61, 30, 69), fill="#4f46e5")
    d.text((36, 65), "WI-FI STATUS", font=font(11), fill="#3730a3", anchor="lm")
    d.text((228, 65), "SETUP >", font=font(10), fill="#6320ef", anchor="rm")

    # Right Card: CLOUD
    d.rounded_rectangle((244, 53, 468, 113), radius=9, fill="white", outline="#cbd5e1", width=2)
    d.rounded_rectangle((244, 53, 468, 75), radius=7, fill="#ecfeff")
    d.rectangle((244, 68, 468, 75), fill="#ecfeff")
    d.ellipse((254, 61, 262, 69), fill="#0891b2")
    d.text((268, 65), "CLOUD STATUS", font=font(11), fill="#155e75", anchor="lm")
    d.text((460, 65), "ESP32-S3", font=font(10), fill="#0891b2", anchor="rm")

    # 2. Middle Row: KIT-TO-KIT COMMUNICATION (Kit Name / ID)
    d.rounded_rectangle((12, 119, 468, 173), radius=9, fill="white", outline="#c7d2fe", width=2)
    d.rounded_rectangle((12, 119, 468, 140), radius=7, fill="#4f46e5")
    d.rectangle((12, 133, 468, 140), fill="#4f46e5")
    d.text((22, 130), "KIT-TO-KIT COMMUNICATION", font=font(11), fill="white", anchor="lm")
    d.text((458, 130), "STM32 <-> CLOUD", font=font(10), fill="#e0e7ff", anchor="rm")
    d.text((22, 156), "KIT ID:", font=font(13), fill="#303a55", anchor="lm")

    # 3. Send Data (TX) & Receive Data (RX) Cards
    # Left Box: SEND DATA (TX)
    d.rounded_rectangle((12, 179, 236, 266), radius=9, fill="white", outline="#86efac", width=2)
    d.rounded_rectangle((12, 179, 236, 202), radius=7, fill="#059669")
    d.rectangle((12, 195, 236, 202), fill="#059669")
    d.polygon([(22, 195), (27, 185), (32, 195)], fill="white")
    d.text((38, 191), "SEND DATA (TX)", font=font(11), fill="white", anchor="lm")

    # Right Box: RECEIVE DATA (RX)
    d.rounded_rectangle((244, 179, 468, 266), radius=9, fill="white", outline="#93c5fd", width=2)
    d.rounded_rectangle((244, 179, 468, 202), radius=7, fill="#2563eb")
    d.rectangle((244, 195, 468, 202), fill="#2563eb")
    d.polygon([(254, 185), (259, 195), (264, 185)], fill="white")
    d.text((270, 191), "RECEIVE DATA (RX)", font=font(11), fill="white", anchor="lm")

    # 4. Bottom Action Bar: SEND DATA, RECEIVE DATA, SYNC / ID
    for (bx0, by0, bx1, by1), (label, _, col) in zip(IOT_BTNS, IOT_BTN_SPECS):
        d.rounded_rectangle((bx0, by0, bx1, by1), radius=8, fill=col, outline="black", width=2)
        d.text(((bx0 + bx1) // 2, (by0 + by1) // 2), label, font=font(13), fill="white", anchor="mm")

    return im


def port_manager_page(mode_idx):
    """Port & Pin Manager page: 0=DIG IN, 1=ANA IN, 2=DIG OUT, 3=PWM, 4=SERVO."""
    im, d = header_page("PORT & PIN MANAGER")

    # Left Column: Port Selector
    d.rounded_rectangle((10, 54, 150, 312), radius=10, fill="white", outline="#d0d5dd", width=2)
    d.rounded_rectangle((10, 54, 150, 82), radius=8, fill="#e9ecf5")
    d.text((80, 68), "PORTS & PINS", font=font(12), fill="#303a55", anchor="mm")

    # Up/Down scroll buttons
    d.rounded_rectangle((14, 88, 146, 114), radius=6, fill="#6320ef")
    d.text((80, 101), "▲ PREV PINS", font=font(11), fill="white", anchor="mm")

    for i in range(4):
        sy0 = 120 + i * 36
        sy1 = sy0 + 32
        d.rounded_rectangle((14, sy0, 146, sy1), radius=6, fill="white", outline="#e0e4ec", width=2)

    d.rounded_rectangle((14, 274, 146, 304), radius=6, fill="#6320ef")
    d.text((80, 289), "▼ NEXT PINS", font=font(11), fill="white", anchor="mm")

    # Right Column: Active Port & Mode Tabs
    d.rounded_rectangle((158, 54, 470, 92), radius=10, fill="white", outline="#d0d5dd", width=2)
    d.text((170, 73), "PORT:", font=font(13), fill="#727d91", anchor="lm")

    # Mode Selector Tabs
    tab_names = ["DIG IN", "ANA IN", "DIG OUT", "PWM OUT", "SERVO"]
    for k, mname in enumerate(tab_names):
        mx0 = 158 + k * 63
        mx1 = mx0 + 59
        sel = (k == mode_idx)
        bg = "#0066cc" if sel else "#e9ecf5"
        txt = "white" if sel else "#4a5568"
        d.rounded_rectangle((mx0, 98, mx1, 126), radius=6, fill=bg, outline="#004d99" if sel else "#cbd5e1", width=2)
        d.text(((mx0 + mx1) // 2, 112), mname, font=font(10), fill=txt, anchor="mm")

    # Main Area Box (y: 132..270)
    d.rounded_rectangle((158, 132, 470, 270), radius=10, fill="white", outline="#d0d5dd", width=2)

    # Footer Note Box
    d.rounded_rectangle((158, 276, 470, 310), radius=8, fill="#ffffff", outline="#d0d5dd", width=1)

    if mode_idx == 0:  # DIG IN
        d.rounded_rectangle((172, 142, 456, 186), radius=8, fill="#f0fdf4", outline="#86efac", width=2)
        d.text((314, 293), "Input mode: reads physical logic state (0 or 1)", font=font(11), fill="#556677", anchor="mm")

    elif mode_idx == 1:  # ANA IN
        d.rounded_rectangle((172, 142, 456, 186), radius=8, fill="#eff6ff", outline="#93c5fd", width=2)
        d.rounded_rectangle((172, 210, 456, 230), radius=6, fill="#e2e8f0", outline="#cbd5e1", width=1)
        d.text((314, 293), "ADC mode: reads 16-bit analog voltage (0V to 3.3V)", font=font(11), fill="#556677", anchor="mm")

    elif mode_idx == 2:  # DIG OUT
        d.rounded_rectangle((176, 165, 306, 225), radius=10, fill="#00a76a", outline="#007a4d", width=3)
        d.text((241, 195), "TURN ON\n(HIGH 3.3V)", font=font(13), fill="white", anchor="mm", align="center")
        d.rounded_rectangle((322, 165, 452, 225), radius=10, fill="#dc2626", outline="#991b1b", width=3)
        d.text((387, 195), "TURN OFF\n(LOW 0V)", font=font(13), fill="white", anchor="mm", align="center")
        d.text((314, 293), "Touch ON or OFF to output signal on selected pin", font=font(11), fill="#556677", anchor="mm")

    elif mode_idx == 3:  # PWM OUT
        pwms = ["0%", "25%", "50%", "75%", "100%"]
        for i, p in enumerate(pwms):
            bx0 = 172 + i * 58
            bx1 = bx0 + 52
            d.rounded_rectangle((bx0, 158, bx1, 198), radius=8, fill="#e0f2fe", outline="#0284c7", width=2)
            d.text(((bx0 + bx1) // 2, 178), p, font=font(12), fill="#0369a1", anchor="mm")
        d.rounded_rectangle((200, 212, 295, 252), radius=8, fill="#6320ef", outline="#3b0764", width=2)
        d.text((247, 232), "- 10%", font=font(14), fill="white", anchor="mm")
        d.rounded_rectangle((333, 212, 428, 252), radius=8, fill="#6320ef", outline="#3b0764", width=2)
        d.text((380, 232), "+ 10%", font=font(14), fill="white", anchor="mm")
        d.text((314, 293), "PWM mode: 1kHz duty cycle for Motors and LED dimming", font=font(11), fill="#556677", anchor="mm")

    elif mode_idx == 4:  # SERVO
        angles = ["0°", "45°", "90°", "135°", "180°"]
        for i, a in enumerate(angles):
            bx0 = 172 + i * 58
            bx1 = bx0 + 52
            d.rounded_rectangle((bx0, 158, bx1, 198), radius=8, fill="#fef3c7", outline="#d97706", width=2)
            d.text(((bx0 + bx1) // 2, 178), a, font=font(13), fill="#b45309", anchor="mm")
        d.rounded_rectangle((200, 212, 295, 252), radius=8, fill="#f59e0b", outline="#b45309", width=2)
        d.text((247, 232), "- 15°", font=font(14), fill="white", anchor="mm")
        d.rounded_rectangle((333, 212, 428, 252), radius=8, fill="#f59e0b", outline="#b45309", width=2)
        d.text((380, 232), "+ 15°", font=font(14), fill="white", anchor="mm")
        d.text((314, 293), "Servo mode: 50Hz pulse control (0° to 180° angle)", font=font(11), fill="#556677", anchor="mm")

    return im


def sfont(size, bold=False):
    return ImageFont.truetype(SEGOE_B if bold else SEGOE, size)


def wrap(d, text, f, width):
    lines, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if line and d.textlength(t, font=f) > width:
            lines.append(line)
            line = word
        else:
            line = t
    return lines + [line] if line else lines


def ai_picture(i, w):
    """Type i's picture from the web app screenshot, width w, rounded corners."""
    im = Image.open(AI_REF).convert("RGB").crop(AI_TYPES[i][5])
    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=7, fill=255)
    return im, mask


def ai_card_box(i):
    x0 = 8 + i * 116
    return (x0, 76, x0 + 110, 310)


def ai_page():
    """AI PROJECTS: the web app's "Start a New Project" cards, four across."""
    im, d = header_page("AI PROJECTS")
    x, y = 12, 54
    for k, (label, _) in enumerate(AI_STEPS):            # 1 Add examples -> 2 ... -> 3 ...
        d.ellipse((x, y, x + 16, y + 16), fill=(224, 231, 255))
        d.text((x + 8, y + 8), str(k + 1), font=sfont(10, True), fill=(79, 70, 229), anchor="mm")
        x += 20
        d.text((x, y + 8), label, font=sfont(11), fill=INK, anchor="lm")
        x += d.textlength(label, font=sfont(11)) + 5
        if k < 2:
            d.text((x, y + 8), "→", font=sfont(11), fill=INK, anchor="lm")
            x += 17
    d.text((468, y + 8), "* Choose one to get started", font=ImageFont.truetype(SEGOE_I, 10), fill=MUTED, anchor="rm")
    for i, (title, tag, col, tint, edge, _, desc, needs, button) in enumerate(AI_TYPES):
        x0, y0, x1, y1 = ai_card_box(i)
        d.rounded_rectangle((x0, y0, x1, y1), radius=9, fill="white", outline=edge, width=3)
        pic, mask = ai_picture(i, x1 - x0 - 6)
        im.paste(pic, (x0 + 3, y0 + 3), mask)
        y = y0 + 3 + pic.height + 2
        for line in wrap(d, title, sfont(12, True), x1 - x0 - 14):
            d.text((x0 + 7, y), line, font=sfont(12, True), fill=INK)
            y += 15
        tw = d.textlength(tag, font=sfont(9, True))
        d.rounded_rectangle((x0 + 7, y + 3, x0 + 17 + tw, y + 17), radius=4, fill=tint)
        d.text((x0 + 12, y + 10), tag, font=sfont(9, True), fill=col, anchor="lm")
        y += 22
        for line in wrap(d, desc, sfont(10), x1 - x0 - 14)[:5]:
            d.text((x0 + 7, y), line, font=sfont(10), fill=MUTED)
            y += 12
        d.rectangle((x0 + 7, y1 - 52, x0 + 15, y1 - 45), fill=NEEDS)
        d.text((x0 + 19, y1 - 49), needs, font=sfont(9), fill=NEEDS, anchor="lm")
        bx0, by0, bx1, by1 = x0 + 7, y1 - 36, x1 - 7, y1 - 10
        if i == 0:
            d.rounded_rectangle((bx0, by0, bx1, by1), radius=6, fill=col)
        else:
            d.rounded_rectangle((bx0, by0, bx1, by1), radius=6, fill="white", outline=col, width=2)
        label = button + " →"
        size = 10
        while size > 8 and d.textlength(label, font=sfont(size, True)) > bx1 - bx0 - 8:
            size -= 1
        if d.textlength(label, font=sfont(size, True)) > bx1 - bx0 - 8:
            label = button[4:] + " →"                 # drop "Use "
        d.text(((bx0 + bx1) // 2, (by0 + by1) // 2), label, font=sfont(size, True),
               fill="white" if i == 0 else col, anchor="mm")
    return im


def ai_detail_page(i):
    """One AI project type: big picture, description, what it needs, the three steps."""
    title, tag, col, tint, edge, _, desc, needs, button = AI_TYPES[i]
    im, d = header_page(title.upper())
    d.rounded_rectangle((12, 56, 236, 206), radius=10, fill="white", outline=edge, width=3)
    pic, mask = ai_picture(i, 218)
    im.paste(pic, (15, 59), mask)
    x, y = 250, 58
    for line in wrap(d, title, sfont(17, True), 216):
        d.text((x, y), line, font=sfont(17, True), fill=INK)
        y += 21
    tw = d.textlength(tag, font=sfont(11, True))
    d.rounded_rectangle((x, y + 4, x + tw + 12, y + 22), radius=5, fill=tint)
    d.text((x + 6, y + 13), tag, font=sfont(11, True), fill=col, anchor="lm")
    y += 30
    for line in wrap(d, desc, sfont(13), 216):
        d.text((x, y), line, font=sfont(13), fill=MUTED)
        y += 17
    d.rectangle((x, y + 8, x + 10, y + 17), fill=NEEDS)
    d.text((x + 15, y + 12), needs, font=sfont(12), fill=NEEDS, anchor="lm")
    if i in AI_LIVE_INDEXES:                       # live panel; the board draws the result as dots
        d.text((14, 220), "LIVE RESULT", font=sfont(13, True), fill=INK, anchor="lm")
        d.text((112, 220), "live data from the AI camera (K230)", font=sfont(11), fill=MUTED, anchor="lm")
        d.rounded_rectangle((404, 211, 466, 229), radius=9, fill=(22, 163, 74))
        d.ellipse((412, 216, 420, 224), fill="white")
        d.text((444, 220), "LIVE", font=sfont(10, True), fill="white", anchor="mm")
        d.rounded_rectangle((12, 234, 466, 308), radius=10, fill=tint, outline=edge, width=2)
        d.line((20, 277, 458, 277), fill=edge, width=1)
        return im
    d.text((14, 222), "How it works", font=sfont(13, True), fill=INK, anchor="lm")
    for k, (label, sub) in enumerate(AI_STEPS):
        bx0 = 12 + k * 154
        bx1, by0, by1 = bx0 + 146, 236, 306
        d.rounded_rectangle((bx0, by0, bx1, by1), radius=9, fill=tint, outline=edge, width=2)
        d.ellipse((bx0 + 8, by0 + 9, bx0 + 30, by0 + 31), fill=col)
        d.text((bx0 + 19, by0 + 20), str(k + 1), font=sfont(13, True), fill="white", anchor="mm")
        d.text((bx0 + 37, by0 + 20), label, font=sfont(13, True), fill=INK, anchor="lm")
        for n, line in enumerate(wrap(d, sub, sfont(11), 130)[:2]):
            d.text((bx0 + 9, by0 + 40 + 14 * n), line, font=sfont(11), fill=MUTED)
    return im


def storage_box(i):
    """Card i of the STORAGE page (2 x 2): 0-2 pictures, 3 video."""
    x0, y0 = 14 + (i % 2) * 230, 56 + (i // 2) * 130
    return (x0, y0, x0 + 222, y0 + 122)


def storage_thumb(i):
    """Top-left of card i's 120 x 80 thumbnail."""
    x0, y0, _, _ = storage_box(i)
    return x0 + 10, y0 + 21


def storage_page():
    """STORAGE background; the picture thumbnails are icon controls drawn on top."""
    im, d = header_page("STORAGE")
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
    for i in range(len(SLOTS) + 1):
        x0, y0, x1, y1 = storage_box(i)
        strip, tint = CARD_COLOURS[i] if i < len(SLOTS) else (PURPLE, "#e6dcfd")
        d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=tint, outline="black", width=3)
        tx, ty = storage_thumb(i)
        d.rectangle((tx - 2, ty - 2, tx + 121, ty + 81), fill="#2b2d33", outline="black", width=2)
        if i == len(SLOTS):                        # the video card: a play sign
            d.ellipse((tx + 38, ty + 18, tx + 82, ty + 62), fill=PURPLE)
            d.polygon([(tx + 54, ty + 29), (tx + 54, ty + 51), (tx + 72, ty + 40)], fill="white")
        mx = (tx + 122 + x1) // 2
        title, sub, button = (("IMAGE %d" % SLOTS[i], "memory %d" % SLOTS[i], "OPEN  >") if i < len(SLOTS)
                              else ("VIDEO", "short clip", "PLAY  >"))
        d.text((mx, y0 + 34), title, font=font(16), fill=strip, anchor="mm")
        d.text((mx, y0 + 56), sub, font=small, fill="#555555", anchor="mm")
        d.rounded_rectangle((mx - 38, y1 - 40, mx + 38, y1 - 14), radius=8, fill=strip, outline="black", width=2)
        d.text((mx, y1 - 27), button, font=font(13), fill="white", anchor="mm")
    bx0, by0, bx1, by1 = ANIM_BTN                  # ANIMATIONS button in the header
    d.rounded_rectangle(ANIM_BTN, radius=8, fill=PURPLE, outline="white", width=2)
    d.text(((bx0 + bx1) // 2, (by0 + by1) // 2), "ANIMATIONS", font=font(14), fill="white", anchor="mm")
    return im


def video_library():
    """Placeholder 49_Video.icl: one "no video yet" frame shown as all 256
    icons; the Blockly page replaces the whole library over UART."""
    ns = lib_section()
    im = Image.new("RGB", (240, 160), "#14161c")
    d = ImageDraw.Draw(im)
    d.polygon([(104, 40), (104, 84), (140, 62)], fill="#6320ef")
    d.text((120, 108), "NO VIDEO YET", font=font(18), fill="white", anchor="mm")
    d.text((120, 132), "upload one from Blockly", font=font(12), fill="#9a9ba3", anchor="mm")
    pix = bytearray()
    for r, g, b in im.getdata():
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        pix += bytes((v >> 8, v & 255))
    rec = bytearray(65536)

    def sink(chunk, roff):
        rec[roff:roff + len(chunk)] = bytes(chunk)
        yield from ()
    gen = ns["_dw_jpeg_steps"](bytes(pix), 240, 160, 240, 160, 75, sink)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        rec = bytes(rec[:e.value])
    first = 16 + 4 * 256
    data = bytearray(first + len(rec))
    data[:16] = b"DGUS_3\x00\x00" + struct.pack(">I", len(data) - 8) + b"\x04\x00" + struct.pack("<H", 255)
    for i in range(256):
        data[16 + 4 * i:20 + 4 * i] = struct.pack(">I", first)
    data[first:] = rec
    data[6:8] = struct.pack("<H", icl_tool._crc16(bytes(data[8:]), 0xA001, 0xFFFF))
    return bytes(data)


def animation_control(x, y):
    """14ShowFile Animation Icon record: icons 0-255 of VIDEO_LIB, 5 x 20 ms
    per frame, loop, plays while VIDEO_VP = 0 (stopped at 1)."""
    return (b"\x5a\x01\xff\xff\x00\x0d" + struct.pack(">HHHHHHHHH", VIDEO_VP, x, y, 1, 1, 0, 0, 0, 255)
            + bytes((VIDEO_LIB, 0x01, 0, 0, 0, 5, 0x00, 0x3F)))


# ---------------------------------------------------------------- 3. project files
def jpeg(im):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90, subsampling=0, optimize=True, progressive=False)
    return buf.getvalue()


def touch(page, box, target):
    x0, y0, x1, y1 = box
    return struct.pack(">HHHHHH", page, x0, y0, x1, y1, target) + b"\xff\x00\x00\x00"


def slide(page, prev_page, next_page):
    """Page Sliding touch control (TP_Code 0xFE0B, 32 bytes): drag the page left /
    right to switch, like a phone; the top bar (y < 48) stays where it is. First
    on its page = highest touch priority, as the guide asks, so the cards and
    buttons under it still work."""
    none = 0xFF00
    return (struct.pack(">HHHHHHHH", page, 0, 48, 479, 319, none, none, 0xFE0B) + b"\xfe"
            + struct.pack(">HHHHBHBB", none if prev_page is None else prev_page, none if next_page is None else next_page,
                          48, 319,          # part of the picture that moves
                          10,               # response time, x 40 ms
                          100,              # minimum drag in pixels
                          0,                # no page upload
                          12)               # trial: smaller finishing steps, pixels/DGUS cycle
            + b"\x00\x00")


def return_key(page, box, code, pressed=None, vp=WIFI_KEY_VP, mode=0x00):
    """'Return key code' touch control (TP_Code 0xFE05, 32 bytes): writes code
    into vp (default WIFI_KEY_VP, which the board polls - dwin_wifi_ui.py);
    mode 0x01 writes only the high byte. pressed = page whose picture shows in
    the key's area while it is held."""
    x0, y0, x1, y1 = box
    return (struct.pack(">HHHHHHHH", page, x0, y0, x1, y1, 0xFF00, 0xFF00 if pressed is None else pressed, 0xFE05)
            + b"\xfe" + struct.pack(">HBHB", vp, mode, code, 0) + bytes(9))


def kb_rows(kind):
    """Key rows of keyboard kind 0 (letters), 1 (CAPS), 2 (symbols): (label,
    code or ("page", kind to switch to), width); every row is 10 units wide."""
    def keys(s):
        return [(c, ord(c), 1) for c in s]
    if kind == 2:
        return [keys("1234567890"), keys("!@#$%^&*()"),
                keys("-_=+[]{}\\") + [("DEL", 8, 1)],
                keys("~`:;'\",|?/"),
                [("ABC", ("page", 0), 2), ("<", 60, 1), ("SPACE", 32, 3), (">", 62, 1), ("CONNECT", 13, 3)]]
    up = kind == 1
    case = str.upper if up else str.lower
    return [keys("1234567890"), keys(case("qwertyuiop")),
            keys(case("asdfghjkl")) + [("DEL", 8, 1)],
            [("abc" if up else "CAPS", ("page", 0 if up else 1), 2)] + keys(case("zxcvbnm")) + [(".", 46, 1)],
            [("?123", ("page", 2), 2), ("@", 64, 1), ("SPACE", 32, 3), ("_", 95, 1), ("CONNECT", 13, 3)]]


def bt_rows():
    """Bluetooth name keyboard (page 92): capitals, digits and '-' only."""
    def keys(s):
        return [(c, ord(c), 1) for c in s]
    return [keys("1234567890"), keys("QWERTYUIOP"), keys("ASDFGHJKL") + [("DEL", 8, 1)],
            keys("ZXCVBNM-") + [("CLEAR", 0x0130, 2)],
            [("CANCEL", ("page", BT_PAGE), 4), ("SAVE", 13, 6)]]


def bt_kb_page(pressed):
    """Bluetooth name keyboard; pressed=True draws every key held down (press effect page)."""
    im, d = header_page("BLUETOOTH NAME")
    d.rectangle((0, 48, 479, 319), fill="white")
    d.rounded_rectangle((12, 76, 468, 102), radius=7, fill="#f7f8fc", outline=PURPLE, width=2)
    for box, label, code in kb_keys(None, bt_rows()):
        if code == 13:
            fill, ink = ((15, 110, 50) if pressed else (22, 163, 74)), "white"
        elif pressed:
            fill, ink = PURPLE, "white"
        elif len(label) > 1:
            fill, ink = "#d9ddea", "#303a55"
        else:
            fill, ink = "#eef0f6", "#1e293b"
        d.rounded_rectangle(box, radius=6, fill=fill, outline="#b9bfcf", width=1)
        d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label,
               font=font(17) if len(label) == 1 else font(12), fill=ink, anchor="mm")
    return im


def kb_keys(kind, rows=None):
    """(box, label, code) of every key of keyboard kind (or of the given rows)."""
    out = []
    for r, row in enumerate(rows if rows is not None else kb_rows(kind)):
        u = 0
        for label, code, w in row:
            x0 = 4 + round(u * 47.2)
            x1 = 4 + round((u + w) * 47.2) - 4
            y0 = 130 + r * 38
            out.append(((x0, y0, x1, y0 + 34), label, code))
            u += w
    return out


def kb_page(kind, pressed):
    """Wi-Fi password keyboard; pressed=True draws every key held down (press effect page)."""
    im, d = header_page("WI-FI PASSWORD")
    d.rectangle((0, 48, 479, 319), fill="white")
    d.rounded_rectangle(KB_PW_BOX, radius=7, fill="#f7f8fc", outline=PURPLE, width=2)
    x0, y0, x1, y1 = KB_SHOW_BTN
    d.rounded_rectangle(KB_SHOW_BTN, radius=7, fill=PURPLE if pressed else "#d9ddea", outline="#9aa0b4", width=2)
    d.text(((x0 + x1) // 2, (y0 + y1) // 2), "SHOW", font=font(13), fill="white" if pressed else "#303a55",
           anchor="mm")
    for box, label, code in kb_keys(kind):
        special = not isinstance(code, int) or code in (8, 13) or len(label) > 1
        if code == 13:
            fill, ink = ((15, 110, 50) if pressed else (22, 163, 74)), "white"
        elif pressed:
            fill, ink = PURPLE, "white"
        elif special:
            fill, ink = "#d9ddea", "#303a55"
        else:
            fill, ink = "#eef0f6", "#1e293b"
        d.rounded_rectangle(box, radius=6, fill=fill, outline="#b9bfcf", width=1)
        f = font(17) if len(label) == 1 else font(12)
        d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, font=f, fill=ink, anchor="mm")
    return im


def anim_page(title="ANIMATION", note="Animation from the play animation block"):
    """ANIMATION page background; the frames are an Animation Icon control."""
    im, d = header_page(title)
    d.rectangle((0, 48, 479, 319), fill="black")
    x, y = ANIM_POS
    d.rectangle((x - 3, y - 3, x + 162, y + 106), outline=PURPLE, width=2)
    d.text((240, 292), note, font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13), fill="#9a9ba3", anchor="mm")
    return im


def anim_control(vp=ANIM_VP, lib=ANIM_LIB, pos=ANIM_POS):
    """Animation Icon record: icons 0-255 of lib (the library repeats its
    32 frames to 256 icons), 8 x 20 ms = 160 ms per frame (32 frames = 5.1 s),
    loop, plays while vp = 0."""
    x, y = pos
    return (b"\x5a\x01\xff\xff\x00\x0d" + struct.pack(">HHHHHHHHH", vp, x, y, 1, 1, 0, 0, 0, 255)
            + bytes((lib, 0x01, 0, 0, 0, 8, 0x00, 0x3F)))


def anim_list_box(i):
    """Touch area of memory i on page 70: preview + its label."""
    x, y = ANIM_LIST_POS[i]
    return (x - 6, y - 6, x + 166, y + 124)


def anim_list_page():
    """ANIMATIONS: the three animation memories playing as previews; tap one to open it."""
    im, d = header_page("ANIMATIONS")
    d.rectangle((0, 48, 479, 319), fill="#14161c")
    for i, (x, y) in enumerate(ANIM_LIST_POS):
        d.rounded_rectangle(anim_list_box(i), radius=8, outline=PURPLE, width=2)
        d.text((x + 80, y + 114), "MEMORY %d" % (i + 1), font=font(13), fill="white", anchor="mm")
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    for k, line in enumerate(("Animation memories 1-3", "Tap one to play it big.", "",
                              "Save one with the block", "'save animation to", "DWIN memory'.")):
        d.text((250, 196 + k * 17), line, font=font(14) if k == 0 else small,
               fill="white" if k == 0 else "#9a9ba3")
    return im


def anim_placeholder(slot):
    """Placeholder library for an empty animation memory: one "no animation"
    frame shown as all 256 icons (the board replaces it when one is saved)."""
    ns = lib_section()
    im = Image.new("RGB", (160, 104), "#1d2027")
    d = ImageDraw.Draw(im)
    d.text((80, 40), "NO ANIMATION", font=font(15), fill="white", anchor="mm")
    d.text((80, 64), "memory %d" % slot, font=font(12), fill="#9a9ba3", anchor="mm")
    pix = bytearray()
    for r, g, b in im.getdata():
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        pix += bytes((v >> 8, v & 255))
    rec = bytearray(65536)

    def sink(chunk, roff):
        rec[roff:roff + len(chunk)] = bytes(chunk)
        yield from ()
    gen = ns["_dw_jpeg_steps"](bytes(pix), 160, 104, 160, 104, 75, sink)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        rec = bytes(rec[:e.value])
    first = 16 + 4 * 256
    data = bytearray(first + len(rec))
    data[:16] = b"DGUS_3\x00\x00" + struct.pack(">I", len(data) - 8) + b"\x04\x00" + struct.pack("<H", 255)
    for i in range(256):
        data[16 + 4 * i:20 + 4 * i] = struct.pack(">I", first)
    data[first:] = rec
    data[6:8] = struct.pack("<H", icl_tool._crc16(bytes(data[8:]), 0xA001, 0xFFFF))
    return bytes(data)


# ---------------------------------------------------------------- DWIN Page Studio
def studio_load():
    try:
        with open(STUDIO_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def studio_row_box(i):
    """Row i of a studio list page."""
    return (18, 58 + i * 51, 461, 102 + i * 51)


def studio_list_page(spec):
    """A list page made in DWIN Page Studio: a title and rows, each row opens a page."""
    im, d = header_page(str(spec.get("title", "LIST"))[:26])
    for i, row in enumerate(spec.get("rows", [])[:STUDIO_ROWS]):
        x0, y0, x1, y1 = studio_row_box(i)
        d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill="#f7f8fc", outline="#d9ddea", width=2)
        d.text((x0 + 14, (y0 + y1) // 2), str(row.get("label", "")), font=font(16), fill="#303a55", anchor="lm")
        d.text((x1 - 16, (y0 + y1) // 2), ">", font=font(19), fill=PURPLE, anchor="mm")
    return im


def studio_texts(im, page, texts):
    """Draw the studio's texts for this page (each may first cover old words with a box)."""
    d = ImageDraw.Draw(im)
    for t in texts:
        if t.get("page") != page:
            continue
        if t.get("cover"):
            d.rectangle(tuple(t["cover"]), fill=t.get("cover_color", "#ffffff"))
        if t.get("text"):
            f = ImageFont.truetype(FONT if t.get("bold", True) else "C:/Windows/Fonts/arial.ttf",
                                   max(8, int(t.get("size", 16))))
            d.text((int(t["x"]), int(t["y"])), str(t["text"]), font=f, fill=t.get("color", "#000000"))
    return im


def studio_base_page(p):
    """Picture of an original page (0-39) as the SD card gets it."""
    if p == HOME:
        return home_page()
    return Image.open(os.path.join(BASE, "%02d.bmp" % p)).convert("RGB")


def studio_pages(pages, proj):
    """Add the studio's list pages, save every page as it is before the text
    edits (for the studio's preview), then draw the text edits."""
    nxt = max(pages) + 1
    for spec in sorted(proj.get("list_pages", []), key=lambda s: s["page"]):
        assert spec["page"] == nxt, "studio list pages must be numbered %d, %d, ... in order" % (max(pages) + 1, nxt + 1)
        pages[nxt] = studio_list_page(spec)
        nxt += 1
    os.makedirs(STUDIO_CACHE, exist_ok=True)
    for p in range(LIST_PAGE):
        studio_base_page(p).save(os.path.join(STUDIO_CACHE, "%02d.png" % p))
    for p, im in pages.items():
        im.save(os.path.join(STUDIO_CACHE, "%02d.png" % p))
    texts = proj.get("texts", [])
    for p in sorted({t.get("page") for t in texts if isinstance(t.get("page"), int)}):
        if p not in pages and 0 <= p < LIST_PAGE:
            pages[p] = studio_base_page(p)
        if p in pages:
            studio_texts(pages[p], p, texts)


def studio_touch(recs, proj):
    """Save the buttons as the builder made them (for the studio), then apply
    the studio's button edits and its list pages' rows."""
    base = []
    for r in recs:
        page, x0, y0, x1, y1, target = struct.unpack(">HHHHHH", r[:12])
        base.append({"page": page, "box": [x0, y0, x1, y1], "target": target,
                     "special": r[14] in (0xFE, 0xFD), "code": r[14:16].hex()})
    os.makedirs(STUDIO_CACHE, exist_ok=True)
    with open(os.path.join(STUDIO_CACHE, "buttons.json"), "w", encoding="utf-8") as f:
        json.dump(base, f)
    ed = proj.get("buttons", {})
    key = lambda page, box: (page, tuple(box))
    removed = {key(e["page"], e["box"]) for e in ed.get("remove", [])}
    retarget = {key(e["page"], e["box"]): e["target"] for e in ed.get("retarget", [])}
    out = []
    for r, b in zip(recs, base):
        k = key(b["page"], b["box"])
        if b["special"]:
            out.append(r)
        elif k not in removed:
            out.append(r[:10] + struct.pack(">H", retarget[k]) + r[12:] if k in retarget else r)
    out += [touch(e["page"], tuple(e["box"]), e["target"]) for e in ed.get("add", [])]
    for spec in proj.get("list_pages", []):
        p = spec["page"]
        out += [touch(p, BACK_BOX, spec.get("back", HOME)), touch(p, HOME_BOX, HOME)]
        out += [touch(p, studio_row_box(i), row["target"])
                for i, row in enumerate(spec.get("rows", [])[:STUDIO_ROWS]) if isinstance(row.get("target"), int)]
    return out


def build(pages, pics):
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    for f in sorted(os.listdir(BASE)):
        if f not in SKIP:
            shutil.copy2(os.path.join(BASE, f), os.path.join(OUT, f))
    try:
        from build_sensor_icons import build_sensor_icons_icl
        build_sensor_icons_icl()
    except Exception as e:
        print("Warning: build_sensor_icons_icl failed:", e)
    if HAVE_FONT:                                  # DWIN 0# font instead of the base project's one
        shutil.copy2(os.path.join(HERE, NEW_FONT), os.path.join(OUT, NEW_FONT))
    # display serial speed: T5LCFG.CFG bytes 0x0A-0x0B = 3225600 / baud
    # (board dwin_screen.py tries 460800 first, then 115200)
    cfg = bytearray(open(os.path.join(OUT, "T5LCFG.CFG"), "rb").read())
    div = 3225600 // DISPLAY_BAUD
    assert 3225600 % DISPLAY_BAUD == 0, "the display only has exact rates such as 115200 or 460800"
    cfg[0x0A], cfg[0x0B] = div >> 8, div & 0xFF
    open(os.path.join(OUT, "T5LCFG.CFG"), "wb").write(cfg)
    for p, im in pages.items():
        im.save(os.path.join(OUT, "%02d.bmp" % p))

    # 32.icl: the 40 existing page pictures unchanged (except the home page,
    # whose baked-in clock is removed) + the new ones
    _, imgs = icl_tool.unpack(open(os.path.join(BASE, "32.icl"), "rb").read())
    assert len(imgs) == LIST_PAGE, "expected pages 0-%d in the base 32.icl" % (LIST_PAGE - 1)
    home = pages.get(HOME) or home_page()          # the studio may have put text on it
    home.save(os.path.join(OUT, "%02d.bmp" % HOME))
    new = sorted(p for p in pages if p >= LIST_PAGE)
    assert new == list(range(LIST_PAGE, LIST_PAGE + len(new))), "pages must follow on without gaps"
    jpgs = [jpg for (_, _, _, _, jpg) in imgs] + [jpeg(pages[p]) for p in new]
    jpgs[HOME] = jpeg(home)
    edited = {p for p in pages if p < LIST_PAGE}   # original pages with studio texts
    for p in edited - {HOME}:
        jpgs[p] = jpeg(pages[p])
    icl = icl_tool.pack(jpgs, convert=set(range(LIST_PAGE, len(jpgs))) | {HOME} | edited)
    _, check = icl_tool.unpack(icl)
    for k, (w, h, hl, sl, jpg) in enumerate(check):
        assert (w, h) == (480, 320) and (10 + hl) % 4 == 0 and sl % 4 == 0, "page %d not in DWIN layout" % k
    open(os.path.join(OUT, "32.icl"), "wb").write(icl)

    # 24_SavedPictures.icl: the pictures, replaceable over UART by dwin_save();
    # 49_Video.icl: "no video yet" until Blockly sends one. Left out with
    # --keep-memory, so the display keeps what it has.
    if pics is not None:
        lib = icon_library(pics)
        open(os.path.join(OUT, ICON_LIB_NAME), "wb").write(lib)
        open(os.path.join(OUT, VIDEO_NAME), "wb").write(video_library())
    if PROFILE_INIT:
        open(os.path.join(OUT, PROFILE_NAME), "wb").write(profile_placeholder())

    # 14ShowFile.bin: page table entries for the new pages, each with its icon controls
    controls = {VIDEO_PAGE: [animation_control(*VIDEO_POS)],
                STORAGE_PAGE: [icon_control(*storage_thumb(i), i) for i in range(len(SLOTS))],
                STORE_VIDEO: [animation_control(*VIDEO_POS)],
                SETTINGS_PAGE: [settings_dot_control(SETTINGS_DOTS_VP),
                                variable_icon_control(0x5360, 31, 95, 48, 78, 87),
                                variable_icon_control(0x5362, 31, 168, 48, 78, 87)],
                PROFILE_PAGE: [icon_control(VIEW_POS[0], VIEW_POS[1], 1, PROFILE_LIB)]}
    project_icon_recs = [variable_icon_control(vp, x, y, 48) for (vp, x, y) in PROJECT_CARD_ICONS]
    for p in PROJECT_PAGES:
        controls[p] = [settings_dot_control(PROJECTS_DOTS_VP)] + project_icon_recs
    for p in PORT_PAGES:
        controls[p] = [settings_dot_control(PORT_TEST_DOTS_VP)]
    controls[SETTINGS_DETAIL_FIRST + 1] = [settings_dot_control(BLUETOOTH_DOTS_VP),
                                           variable_icon_control(0x5364, 31, 86, 48, 78, 87)]
    controls[SETTINGS_DETAIL_FIRST + 2] = [settings_dot_control(FIRMWARE_DOTS_VP)]
    controls[SETTINGS_DETAIL_FIRST] = [wifi_dot_control()]
    controls[ANIM_PAGE] = [anim_control()]
    for i, p in enumerate(ANIM_SLOT_PAGES):
        controls[p] = [anim_control(ANIM_SLOT_VP[i], ANIM_SLOT_LIB[i])]
    controls[ANIM_LIST_PAGE] = [anim_control(ANIM_SLOT_VP[i], ANIM_SLOT_LIB[i], ANIM_LIST_POS[i]) for i in range(3)]
    if ANIM_INIT:
        for i, name in enumerate(ANIM_SLOT_NAMES):
            open(os.path.join(OUT, name), "wb").write(anim_placeholder(i + 1))
    for p in KB_PAGES + (BT_KB_PAGE,):
        controls[p] = [gesture_dot_control()]       # same dot area (0x5400) as the gesture page
    assert WIFI_KB_DOTS_VP == GESTURE_VP
    for i in AI_LIVE_INDEXES:                      # AI pages 52-55: live result panel (0x5400)
        controls[AI_FIRST + i] = [gesture_dot_control()]
    # SENSOR GRAPH: three line lists + the legend's dot list
    controls[GRAPH_PAGE] = [graph_line_control(vp) for vp in GRAPH_LINE_VPS] + [gesture_dot_control()]
    controls[IOT_PAGE] = [gesture_dot_control()]
    # LLM CHAT: home page 3 like home page 2; conversation + question dot lists
    home_bar_icons = [icon_control(*PROFILE_THUMB_POS, 0, PROFILE_LIB),
                      variable_icon_control(0x5366, 346, 3, 48, 88, 90),
                      variable_icon_control(0x5368, 384, 3, 48, 88, 90)]
    controls[HOME3] = clock_controls() + home_bar_icons
    controls[CHAT_PAGE] = [settings_dot_control(CHAT_DOTS_VP)]
    controls[CHAT_KB_PAGE] = [settings_dot_control(CHAT_KB_DOTS_VP)]
    controls[HOME2] = clock_controls() + home_bar_icons
    for i in range(len(SLOTS)):
        controls[STORE_PIC + i] = [icon_control(VIEW_POS[0], VIEW_POS[1], len(SLOTS) + i)]
    last = max(pages)
    sf = bytearray(open(os.path.join(BASE, "14ShowFile.bin"), "rb").read())
    assert sf[:7] == b"\x14DGUS_2"
    old_last = sf[9] | sf[10] << 8
    assert old_last == LIST_PAGE - 1, old_last
    for p in range(old_last + 1, last + 1):
        recs_p = controls.get(p, [])
        off = len(sf)
        assert off % 32 == 0 and off + 32 * len(recs_p) < 0x10000
        o = 0x10 + p * 4
        sf[o:o + 4] = bytes((len(recs_p), 0, off >> 8, off & 0xFF))      # count (LE16), offset (BE16)
        sf += b"".join(recs_p)
    # home page 10 is a base page with no controls: give it the clock + top-bar icons
    o = 0x10 + HOME * 4
    assert sf[o] == 0 and sf[o + 1] == 0, "home page already has controls"
    off = len(sf)
    home_recs = clock_controls() + home_bar_icons
    assert off % 32 == 0 and off + 32 * len(home_recs) < 0x10000
    sf[o:o + 4] = bytes((len(home_recs), 0, off >> 8, off & 0xFF))
    sf += b"".join(home_recs)
    sf[9], sf[10] = last & 0xFF, last >> 8
    open(os.path.join(OUT, "14ShowFile.bin"), "wb").write(sf)

    # 13TouchFile.bin: home card -> list, list buttons, picture-page buttons
    tf = open(os.path.join(BASE, "13TouchFile.bin"), "rb").read()
    assert tf[-2:] == b"\xff\xff"
    recs = [tf[i:i + 16] for i in range(0, len(tf) - 2, 16)]
    hit = 0
    for i, r in enumerate(recs):
        if struct.unpack(">HHHHH", r[:10]) == (HOME,) + HOME_PROJECTS_CARD:
            recs[i] = r[:10] + struct.pack(">H", LIST_PAGE) + r[12:]
            hit += 1
    assert hit == 1, "PROJECTS LIST card not found on the home page"
    hit = 0
    for i, r in enumerate(recs):
        if struct.unpack(">HHHHH", r[:10]) == (HOME,) + HOME_NEXT_BTN:
            recs[i] = struct.pack(">HHHHHH", HOME, 326, 260, 470, 308, HOME2) + r[12:]
            hit += 1
    assert hit == 1, "NEXT button not found on the home page"
    hit = 0
    for i, r in enumerate(recs):
        if struct.unpack(">HHHHH", r[:10]) == (HOME,) + HOME_AI_CARD:
            recs[i] = r[:10] + struct.pack(">H", AI_PAGE) + r[12:]
            hit += 1
    assert hit == 1, "AI PROJECTS card not found on the home page"
    hit = 0
    for i, r in enumerate(recs):
        if struct.unpack(">HHHHH", r[:10]) == (HOME,) + HOME_SETTINGS_CARD:
            recs[i] = r[:10] + struct.pack(">H", SETTINGS_PAGE) + r[12:]
            hit += 1
    assert hit == 1, "SETTINGS card not found on the home page"
    hit = 0
    for i, r in enumerate(recs):
        if struct.unpack(">HHHHH", r[:10]) == (HOME, 128, 53, 236, 254):
            recs[i] = r[:10] + struct.pack(">H", CATALOG_FIRST_PAGE) + r[12:]
            hit += 1
    assert hit == 1, "SENSORS & ACTUATORS card not found on the home page"
    recs += [touch(SETTINGS_PAGE, BACK_BOX, HOME), touch(SETTINGS_PAGE, HOME_BOX, HOME)]
    recs += [touch(HOME, PROFILE_TAP_BOX, PROFILE_PAGE),
             touch(HOME2, PROFILE_TAP_BOX, PROFILE_PAGE),
             touch(HOME3, PROFILE_TAP_BOX, PROFILE_PAGE),
             touch(PROFILE_PAGE, BACK_BOX, HOME), touch(PROFILE_PAGE, HOME_BOX, HOME)]
    recs += [touch(ANIM_PAGE, BACK_BOX, HOME), touch(ANIM_PAGE, HOME_BOX, HOME)]
    # SETTINGS brightness buttons: write the level straight into the display's
    # brightness register (VP 0x0082 high byte) - works without the board
    recs += [return_key(SETTINGS_PAGE, box, level, vp=BRIGHT_VP, mode=0x01)
             for box, level in zip(bright_boxes(), BRIGHT_LEVELS)]
    recs += [touch(STORAGE_PAGE, ANIM_BTN, ANIM_LIST_PAGE),
             touch(ANIM_LIST_PAGE, BACK_BOX, STORAGE_PAGE), touch(ANIM_LIST_PAGE, HOME_BOX, HOME)]
    for i, p in enumerate(ANIM_SLOT_PAGES):
        recs += [touch(ANIM_LIST_PAGE, anim_list_box(i), p),
                 touch(p, BACK_BOX, ANIM_LIST_PAGE), touch(p, HOME_BOX, HOME)]
    # Bluetooth: three buttons on page 58 and the name keyboard (board: dwin_wifi_ui)
    recs += [return_key(BT_PAGE, box, code) for box, (_, code) in zip(BT_BTNS, BT_BTN_CODES)]
    recs += [touch(BT_KB_PAGE, BACK_BOX, BT_PAGE), touch(BT_KB_PAGE, HOME_BOX, HOME)]
    for box, label, code in kb_keys(None, bt_rows()):
        recs.append(return_key(BT_KB_PAGE, box, code, BT_KB_PRESSED) if isinstance(code, int)
                    else touch(BT_KB_PAGE, box, code[1]))
    # LLM CHAT: home page 3, the conversation page and the question keyboard (board: dwin_llm_chat)
    recs += [touch(HOME3, (10, 260, 154, 308), HOME2), touch(HOME3, HOME_CHAT_CARD, CHAT_PAGE),
             touch(CHAT_PAGE, BACK_BOX, HOME3), touch(CHAT_PAGE, HOME_BOX, HOME),
             touch(CHAT_PAGE, CHAT_ASK_BTN, CHAT_KB_PAGE),
             touch(CHAT_KB_PAGE, BACK_BOX, CHAT_PAGE), touch(CHAT_KB_PAGE, HOME_BOX, HOME)]
    recs += [return_key(CHAT_PAGE, box, code, vp=CHAT_KEY_VP) for box, _, code in CHAT_BTNS]
    for box, label, code in kb_keys(None, chat_rows()):
        recs.append(return_key(CHAT_KB_PAGE, box, code, CHAT_KB_PRESSED, vp=CHAT_KEY_VP)
                    if isinstance(code, int) else touch(CHAT_KB_PAGE, box, code[1]))
    # Wi-Fi: network rows, radio ON/OFF and SCAN on page 57, then password keyboards
    recs += [return_key(SETTINGS_DETAIL_FIRST, box, 0x0101 + i) for i, box in enumerate(WIFI_ROWS)]
    recs += [return_key(SETTINGS_DETAIL_FIRST, WIFI_ON_BTN, 0x0112),
             return_key(SETTINGS_DETAIL_FIRST, WIFI_OFF_BTN, 0x0113)]
    recs += [return_key(SETTINGS_DETAIL_FIRST, WIFI_SCAN_BTN, 0x0110)]
    for kind, p in enumerate(KB_PAGES):
        recs += [touch(p, BACK_BOX, SETTINGS_DETAIL_FIRST), touch(p, HOME_BOX, HOME),
                 return_key(p, KB_SHOW_BTN, 0x0111, KB_PRESSED[kind])]
        for box, label, code in kb_keys(kind):
            recs.append(return_key(p, box, code, KB_PRESSED[kind]) if isinstance(code, int)
                        else touch(p, box, KB_PAGES[code[1]]))
    for i, (_, _, y) in enumerate(SETTINGS_FIELDS):
        recs += [touch(SETTINGS_PAGE, (18, y - 19, 461, y + 41), SETTINGS_DETAIL_FIRST + i),
                 touch(SETTINGS_DETAIL_FIRST + i, BACK_BOX, SETTINGS_PAGE),
                 touch(SETTINGS_DETAIL_FIRST + i, HOME_BOX, HOME)]
    recs += [touch(AI_PAGE, BACK_BOX, HOME), touch(AI_PAGE, HOME_BOX, HOME)]
    for i in range(len(AI_TYPES)):
        recs += [touch(AI_PAGE, ai_card_box(i), AI_FIRST + i),
                 touch(AI_FIRST + i, BACK_BOX, AI_PAGE), touch(AI_FIRST + i, HOME_BOX, HOME)]
    recs += [touch(HOME2, (10, 260, 154, 308), HOME), touch(HOME2, HOME_PROJECTS_CARD, STORAGE_PAGE),
             touch(HOME2, HOME_PORT_CARD, PORT_PAGE_DIG_IN),
             touch(HOME2, HOME_GRAPH_CARD, GRAPH_PAGE),
             touch(HOME2, HOME_IOT_CARD, IOT_PAGE),
             touch(HOME2, (326, 260, 470, 308), HOME3),
             touch(GRAPH_PAGE, BACK_BOX, HOME2), touch(GRAPH_PAGE, HOME_BOX, HOME),
             *[return_key(GRAPH_PAGE, (18, y, 330, y + 21), 0x0601 + i, vp=GRAPH_KEY_VP)
               for i, y in enumerate(GRAPH_LEGEND_Y)],
             touch(IOT_PAGE, BACK_BOX, HOME2), touch(IOT_PAGE, HOME_BOX, HOME),
             touch(IOT_PAGE, IOT_WIFI_BOX, SETTINGS_DETAIL_FIRST),
             *[return_key(IOT_PAGE, box, code, vp=IOT_KEY_VP)
               for box, (_, code, _) in zip(IOT_BTNS, IOT_BTN_SPECS)],
             touch(STORAGE_PAGE, BACK_BOX, HOME2), touch(STORAGE_PAGE, HOME_BOX, HOME),
             touch(STORAGE_PAGE, storage_box(len(SLOTS)), STORE_VIDEO),
             touch(STORE_VIDEO, BACK_BOX, STORAGE_PAGE), touch(STORE_VIDEO, HOME_BOX, HOME)]
    for i in range(len(SLOTS)):
        recs += [touch(STORAGE_PAGE, storage_box(i), STORE_PIC + i),
                 touch(STORE_PIC + i, BACK_BOX, STORAGE_PAGE), touch(STORE_PIC + i, HOME_BOX, HOME)]
    for i, p in enumerate(PROJECT_PAGES):
        recs += [touch(p, BACK_BOX, PROJECT_PAGES[i - 1] if i else HOME),
                 touch(p, HOME_BOX, HOME),
                 return_key(p, PLAY_BOX, PLAY_KEY_CODE, vp=PROJECTS_KEY_VP),
                 return_key(p, STOP_BOX, STOP_KEY_CODE, vp=PROJECTS_KEY_VP)]
        if i:
            recs.append(touch(p, PROJECT_PREV_BOX, PROJECT_PAGES[i - 1]))
        if i + 1 < len(PROJECT_PAGES):
            recs.append(touch(p, PROJECT_NEXT_BOX, PROJECT_PAGES[i + 1]))

    # Port & Pin Manager pages (74-78)
    for p in PORT_PAGES:
        recs += [touch(p, BACK_BOX, HOME2), touch(p, HOME_BOX, HOME)]
        # Mode selector tabs
        recs += [touch(p, (158, 98, 217, 126), PORT_PAGE_DIG_IN),
                 touch(p, (221, 98, 280, 126), PORT_PAGE_ANA_IN),
                 touch(p, (284, 98, 343, 126), PORT_PAGE_DIG_OUT),
                 touch(p, (347, 98, 406, 126), PORT_PAGE_PWM),
                 touch(p, (410, 98, 469, 126), PORT_PAGE_SERVO)]
        # Left Port Selector
        recs += [return_key(p, (14, 88, 146, 114), 0x0301, vp=PORT_TEST_KEY_VP),
                 return_key(p, (14, 120, 146, 152), 0x0303, vp=PORT_TEST_KEY_VP),
                 return_key(p, (14, 156, 146, 188), 0x0304, vp=PORT_TEST_KEY_VP),
                 return_key(p, (14, 196, 146, 228), 0x0305, vp=PORT_TEST_KEY_VP),
                 return_key(p, (14, 236, 146, 268), 0x0306, vp=PORT_TEST_KEY_VP),
                 return_key(p, (14, 274, 146, 304), 0x0302, vp=PORT_TEST_KEY_VP)]

    # DIG OUT actions (Page 76)
    recs += [return_key(PORT_PAGE_DIG_OUT, (176, 165, 306, 225), 0x0321, vp=PORT_TEST_KEY_VP),
             return_key(PORT_PAGE_DIG_OUT, (322, 165, 452, 225), 0x0320, vp=PORT_TEST_KEY_VP)]

    # PWM OUT actions (Page 77)
    for i in range(5):
        bx0 = 172 + i * 58
        recs.append(return_key(PORT_PAGE_PWM, (bx0, 158, bx0 + 52, 198), 0x0330 + i, vp=PORT_TEST_KEY_VP))
    recs += [return_key(PORT_PAGE_PWM, (200, 212, 295, 252), 0x0335, vp=PORT_TEST_KEY_VP),
             return_key(PORT_PAGE_PWM, (333, 212, 428, 252), 0x0336, vp=PORT_TEST_KEY_VP)]

    # SERVO actions (Page 78)
    for i in range(5):
        bx0 = 172 + i * 58
        recs.append(return_key(PORT_PAGE_SERVO, (bx0, 158, bx0 + 52, 198), 0x0340 + i, vp=PORT_TEST_KEY_VP))
    recs += [return_key(PORT_PAGE_SERVO, (200, 212, 295, 252), 0x0345, vp=PORT_TEST_KEY_VP),
             return_key(PORT_PAGE_SERVO, (333, 212, 428, 252), 0x0346, vp=PORT_TEST_KEY_VP)]

    # SENSORS & ACTUATORS Catalog pages (80-92)
    for i, p in enumerate(CATALOG_PAGES):
        recs += [touch(p, BACK_BOX, HOME), touch(p, HOME_BOX, HOME)]
        if i > 0:
            recs.append(touch(p, (10, 260, 115, 305), CATALOG_PAGES[i - 1]))
        if i + 1 < len(CATALOG_PAGES):
            recs.append(touch(p, (365, 260, 470, 305), CATALOG_PAGES[i + 1]))
    # No swipe on the home pages (user's choice 2026-10-23): only NEXT / PREVIOUS
    # change page. To bring it back:
    # recs = [slide(HOME, None, HOME2), slide(HOME2, HOME, None)] + recs   # stable sort keeps them first
    recs = studio_touch(recs, STUDIO)
    recs.sort(key=lambda r: struct.unpack(">H", r[:2])[0])
    open(os.path.join(OUT, "13TouchFile.bin"), "wb").write(b"".join(recs) + b"\xff\xff")
    print("built %s: 32.icl %d pages (%d KB), %s, touch buttons %d" % (
        OUT, len(jpgs), len(icl) // 1024, "%s %d KB" % (ICON_LIB_NAME, len(lib) // 1024) if pics is not None
        else "pictures and video left as they are in the display", len(recs)))


# ---------------------------------------------------------------- 4. SD card
def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def copy_to_sd(drive):
    root = drive.rstrip("\\/") + "/"
    if not os.path.isdir(root):
        sys.exit("SD card %s not found." % drive)
    if any(os.path.exists(root + f) for f in ("main.py", "boot.py", "lib.py")):
        sys.exit("%s looks like the STM32 board's drive, not the SD card - stopped." % drive)
    dst = root + "DWIN_SET"
    os.makedirs(dst, exist_ok=True)
    for f in (ICON_LIB_NAME, PROFILE_NAME, VIDEO_NAME, OLD_FONT) + ANIM_SLOT_NAMES:   # an old copy would overwrite
        if f not in os.listdir(OUT) and os.path.exists(os.path.join(dst, f)):   # the display's memory
            os.remove(os.path.join(dst, f))
            print("removed old %s from the card (the display keeps its own)" % f)
    for f in sorted(os.listdir(OUT)):
        shutil.copyfile(os.path.join(OUT, f), os.path.join(dst, f))
    extra = sorted(set(os.listdir(dst)) - set(os.listdir(OUT)))
    bad = [f for f in os.listdir(OUT) if sha(os.path.join(OUT, f)) != sha(os.path.join(dst, f))]
    print("SD %s: %d files copied, verified %s%s" % (dst, len(os.listdir(OUT)), "OK" if not bad else "FAILED %s" % bad,
                                                      ("; other files already there: %s" % extra) if extra else ""))
    return not bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sd", help="SD card drive, for example E:")
    ap.add_argument("--no-read", action="store_true", help="use saved_pictures/ instead of reading the display")
    ap.add_argument("--keep-memory", action="store_true",
                    help="pages only; the pictures and the video already in the display stay")
    ap.add_argument("--anim-placeholders", action="store_true",
                    help="also write 'no animation' into animation memories 1-3 (only once: it clears them)")
    ap.add_argument("--init-profile", action="store_true",
                    help="install the initial profile placeholder (only once; later use the uploader)")
    ap.add_argument("--profile-test", action="store_true",
                    help="test the uploaded avatar on HOME2 while keeping boot HOME static")
    a = ap.parse_args()
    global ANIM_INIT, PROFILE_INIT, PROFILE_TEST
    ANIM_INIT = a.anim_placeholders
    PROFILE_INIT = a.init_profile
    PROFILE_TEST = a.profile_test
    os.makedirs(PICS, exist_ok=True)
    if a.keep_memory:
        pics = None
    elif a.no_read:
        pics = {s: (Image.open(os.path.join(PICS, "slot%d.png" % s)).convert("RGB")
                    if os.path.exists(os.path.join(PICS, "slot%d.png" % s)) else None) for s in SLOTS}
    else:
        pics = read_slots()
        for s, im in pics.items():
            p = os.path.join(PICS, "slot%d.png" % s)
            if im is not None:
                im.save(p)
            elif os.path.exists(p):
                os.remove(p)
    pages = {p: list_page(i + 1) for i, p in enumerate(PROJECT_PAGES)}
    pages[42] = picture_page(2)
    pages[43] = picture_page(3)
    pages[VIDEO_PAGE] = video_page()
    pages[HOME2] = home2_page()
    pages[STORAGE_PAGE] = storage_page()
    for i, s in enumerate(SLOTS):
        pages[STORE_PIC + i] = picture_page(s)
    pages[STORE_VIDEO] = video_page()
    pages[AI_PAGE] = ai_page()
    for i in range(len(AI_TYPES)):
        pages[AI_FIRST + i] = ai_detail_page(i)
    pages[SETTINGS_PAGE] = settings_page()
    for i in range(len(SETTINGS_FIELDS)):
        pages[SETTINGS_DETAIL_FIRST + i] = settings_detail_page(i)
    for kind in range(3):
        pages[KB_PAGES[kind]] = kb_page(kind, False)
        pages[KB_PRESSED[kind]] = kb_page(kind, True)
    pages[ANIM_PAGE] = anim_page()
    for i, p in enumerate(ANIM_SLOT_PAGES):
        pages[p] = anim_page("ANIMATION %d" % (i + 1), "Animation memory %d" % (i + 1))
    pages[ANIM_LIST_PAGE] = anim_list_page()
    for i, p in enumerate(PORT_PAGES):
        pages[p] = port_manager_page(i)
    # SENSORS & ACTUATORS Catalog pages (80-92)
    from generate_sensors_catalog import render_catalog_page, TOTAL_PAGES
    for i in range(TOTAL_PAGES):
        pages[CATALOG_FIRST_PAGE + i] = render_catalog_page(i + 1)
    pages[BT_KB_PAGE] = bt_kb_page(False)
    pages[BT_KB_PRESSED] = bt_kb_page(True)
    pages[PROFILE_PAGE] = profile_page()
    pages[GRAPH_PAGE] = graph_page()
    pages[IOT_PAGE] = iot_page()
    pages[HOME3] = home3_page()
    pages[CHAT_PAGE] = chat_page()
    pages[CHAT_KB_PAGE] = chat_kb_page(False)
    pages[CHAT_KB_PRESSED] = chat_kb_page(True)
    global STUDIO
    STUDIO = studio_load()
    studio_pages(pages, STUDIO)
    build(pages, pics)
    if a.sd:
        ok = copy_to_sd(a.sd)
        print("Next: power the display off, insert the SD card, power on, wait for the download to finish,"
              " power off, remove the card, power on." if ok else "SD copy failed.")


if __name__ == "__main__":
    main()
