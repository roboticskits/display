"""Build CURIO_DISPLAY_BOARD_REFERENCE.xlsx: one workbook describing the STM32
board code and the DWIN display for the next developer.

Most sheets are generated from the code and from the built display files, so
run this again after a change (python make_reference_xlsx.py):
  - functions: parsed (ast) from board_r4/*.py
  - pages, controls, touch buttons: read from DWIN_SET_sd/14ShowFile.bin and
    13TouchFile.bin (run make_sd_card.py first)
  - sensor card icons: board_r4/lib.py _telemetry_icon_for() run on each name
The hand-written tables (hardware, VP map, key codes, ESP32 ops, flash map,
files) are in this script: keep them in step with DEVELOPER_NOTES.txt.
"""
import ast
import os
import re
import struct
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOARD = os.path.join(ROOT, "board_r4")
SD = os.path.join(HERE, "DWIN_SET_sd")
OUT = os.path.join(ROOT, "CURIO_DISPLAY_BOARD_REFERENCE.xlsx")
sys.path.insert(0, HERE)
import make_sd_card as msd                       # noqa: E402  page numbers and layout constants

FONT = "Arial"
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
TITLE_FILL = PatternFill("solid", fgColor="D9E1F2")
WARN_FILL = PatternFill("solid", fgColor="FCE4D6")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def hx(v, digits=4):
    return "0x%0*X" % (digits, v)


# ------------------------------------------------------------------ page names
def page_names():
    names = {}
    try:
        import dwin_studio                       # its NAMES table is the master list
        names.update(dwin_studio.NAMES)
    except Exception:
        pass
    for i in range(10):
        names.setdefault(i, "Boot %d" % i)
    names.setdefault(msd.HOME, "HOME")
    return names


PAGE_INFO = {   # page -> (what it is, board code that draws on it / handles it)
    msd.HOME: ("Home page 1: PROJECTS LIST, SENSORS & ACTUATOR LIST, AI PROJECTS, SETTINGS cards",
               "Clock = display's own RTC controls; profile avatar = icon from 26_Profile.icl"),
    39: ("Image page: pictures drawn as dot lists (regions A 0x1000 and B 0x8400)",
         "dwin_screen.py dwin_image / dwin_show_saved (lib blocks)"),
    msd.VIDEO_PAGE: ("VIDEO page: Animation Icon control playing 49_Video.icl", "dwin_screen.py video blocks (VP 0x5210)"),
    msd.HOME2: ("Home page 2: STORAGE, PORT & PIN, SENSOR GRAPH, IOT CLOUD cards", "Display RTC clock + profile icon"),
    msd.STORAGE_PAGE: ("STORAGE: 3 saved pictures + video", "Pictures = icons from 24_SavedPictures.icl"),
    msd.AI_PAGE: ("AI PROJECTS: the four AI project types", "Page switches only"),
    msd.SETTINGS_PAGE: ("SETTINGS: Wi-Fi / Bluetooth / Firmware + brightness", "dwin_get_data._draw_settings_dots (0x8030); brightness dwin_wifi_ui._brightness"),
    57: ("WI-FI: status + 4 scanned networks + SCAN", "dwin_get_data._draw_wifi_dots (0x7340); taps dwin_wifi_ui (0x5F00)"),
    58: ("BLUETOOTH: state, VISIBLE ON/OFF, DISCONNECT, RENAME", "dwin_get_data (0x8030); keys dwin_wifi_ui._bt_key (0x5F00)"),
    59: ("FIRMWARE: versions", "dwin_get_data._draw_settings_dots (0x8030)"),
    msd.BT_KB_PAGE: ("Bluetooth name keyboard", "dwin_wifi_ui._bt_draw (0x5400), keys 0x5F00"),
    msd.PROFILE_PAGE: ("PROFILE: full-size user profile picture", "26_Profile.icl (uploaded from the web page)"),
    msd.GRAPH_PAGE: ("SENSOR GRAPH: live line chart of 3 sensors", "lib._graph_draw (lines 0xFB40/0xFBE0/0xFC80, legend 0x5400, keys 0x5F70)"),
    msd.IOT_PAGE: ("IOT & KIT-TO-KIT: Wi-Fi, cloud, kit ID, SEND / RECEIVE / SYNC", "dwin_get_data.draw_iot_page (0x5400), keys 0x5F80 in dwin_wifi_ui.poll"),
    msd.HOME3: ("Home page 3: LLM CHAT card (3 places free for new cards)", "Display RTC clock + profile icon"),
    msd.CHAT_PAGE: ("LLM CHAT conversation: UP / DOWN / CLEAR / ASK", "dwin_llm_chat.py (dots 0x1000, keys 0x5F90); API in lib.py LLM_URL"),
    msd.CHAT_KB_PAGE: ("LLM CHAT question keyboard", "dwin_llm_chat.py (dots 0x4200, keys 0x5F90)"),
    msd.CHAT_KB_PRESSED: ("LLM CHAT keyboard, keys pressed (press-effect picture only)", "-"),
}
for _p in msd.PROJECT_PAGES:
    PAGE_INFO[_p] = ("PROJECTS LIST: 6 live sensor / actuator cards of the running program",
                     "lib._telemetry_draw (dots 0x5500, card icons 0x6110..0x6610); PLAY/STOP keys 0x5F60 in main.py")
for _i in range(4):
    PAGE_INFO[msd.AI_FIRST + _i] = ("AI page %s: live result panel" % ("image voice pose gesture".split()[_i]),
                                    "lib._ai_live_line / _ai_live_idle -> dwin_screen._dw_gesture_show (0x5400)")
for _k, _p in enumerate(msd.KB_PAGES):
    PAGE_INFO[_p] = ("Wi-Fi password keyboard (%s)" % ("abc", "ABC", "?123")[_k], "dwin_wifi_ui._draw (0x5400), keys 0x5F00")
    PAGE_INFO[msd.KB_PRESSED[_k]] = ("Wi-Fi keyboard, keys pressed (press-effect picture only)", "-")
for _p in msd.PORT_PAGES:
    PAGE_INFO[_p] = ("PORT & PIN MANAGER (dig in / ana in / dig out / PWM / servo tabs)", "dwin_port_test.py (dots 0x6600, keys 0x5F50)")
for _p in msd.CATALOG_PAGES:
    PAGE_INFO[_p] = ("SENSORS & ACTUATORS catalog page (static picture)", "Page switches only (generate_sensors_catalog.py)")
for _i in range(11, 15):
    PAGE_INFO[_i] = ("Original project's SENSORS LIST page (base project)", "-")
for _i in range(15, 39):
    PAGE_INFO[_i] = ("Bird face frame (bird emotion animation, base project)", "lib bird face blocks")

CONTROL_TYPES = {0x00: "Variable Icon", 0x01: "Animation Icon", 0x02: "Slider", 0x03: "Artistic variable",
                 0x10: "Data variable", 0x11: "Text display", 0x12: "RTC display", 0x13: "HEX data",
                 0x14: "Text scroll", 0x20: "Real-time curve", 0x21: "Basic Graphic (dot/line list)",
                 0x22: "Table", 0x23: "QR code"}


def read_controls():
    s = open(os.path.join(SD, "14ShowFile.bin"), "rb").read()
    last = s[9] | s[10] << 8
    out = {}
    for p in range(last + 1):
        o = 0x10 + p * 4
        n, off = s[o], s[o + 2] << 8 | s[o + 3]
        out[p] = [s[off + 32 * k: off + 32 * k + 32] for k in range(n)]
    return last, out


def read_touches():
    t = open(os.path.join(SD, "13TouchFile.bin"), "rb").read()
    i, recs = 0, []
    while i + 16 <= len(t) and t[i:i + 2] != b"\xff\xff":
        code = struct.unpack(">H", t[i + 14:i + 16])[0]
        n = 32 if (code >> 8) == 0xFE else 16
        recs.append(t[i:i + n])
        i += n
    return recs


# ------------------------------------------------------------------ key codes
KEY_CODES = [   # (VP, code(s), meaning, pages, handled in)
    (0x0082, "0x0014-0x0064", "Brightness 20 / 40 / 60 / 80 / 100 % (written into the display's own register, high byte)", "56",
     "The display itself; dwin_wifi_ui._brightness checks and saves it"),
    (0x5F00, "0x0101-0x0104", "Wi-Fi network row 1-4 (opens the password keyboard)", "57", "dwin_wifi_ui._key"),
    (0x5F00, "0x0110", "Wi-Fi SCAN", "57", "dwin_wifi_ui._key"),
    (0x5F00, "0x0111", "Show / hide password", "60-62", "dwin_wifi_ui._key"),
    (0x5F00, "0x0020-0x007E", "Typed character (ASCII)", "60-62, 92", "dwin_wifi_ui._key / _bt_key"),
    (0x5F00, "0x0008", "Delete last character", "60-62, 92", "dwin_wifi_ui"),
    (0x5F00, "0x000D", "CONNECT (Wi-Fi) / SAVE (Bluetooth name)", "60-62, 92", "dwin_wifi_ui"),
    (0x5F00, "0x0120", "Bluetooth VISIBLE ON/OFF", "58", "dwin_wifi_ui._bt_key -> ESP32 ble_adv"),
    (0x5F00, "0x0121", "Bluetooth DISCONNECT the phone/app", "58", "dwin_wifi_ui._bt_key -> ESP32 ble_disconnect"),
    (0x5F00, "0x0122", "Bluetooth RENAME (opens keyboard 92)", "58", "dwin_wifi_ui._bt_key"),
    (0x5F00, "0x0130", "Clear the Bluetooth name", "92", "dwin_wifi_ui._bt_key"),
    (0x5F50, "0x0301 / 0x0302", "Port list previous / next", "74-78", "dwin_port_test.poll"),
    (0x5F50, "0x0303-0x0306", "Select port row 1-4", "74-78", "dwin_port_test.poll"),
    (0x5F50, "0x0321 / 0x0320", "Digital out ON / OFF", "76", "dwin_port_test.poll"),
    (0x5F50, "0x0330-0x0334", "PWM 0 / 25 / 50 / 75 / 100 %", "77", "dwin_port_test.poll"),
    (0x5F50, "0x0335 / 0x0336", "PWM -10 % / +10 %", "77", "dwin_port_test.poll"),
    (0x5F50, "0x0340-0x0344", "Servo 0 / 45 / 90 / 135 / 180 deg", "78", "dwin_port_test.poll"),
    (0x5F50, "0x0345 / 0x0346", "Servo -15 / +15 deg", "78", "dwin_port_test.poll"),
    (0x5F60, "0x0501", "PLAY the user program", "40, 41, 71-73", "main.py idle loop"),
    (0x5F60, "0x0502", "STOP the user program", "40, 41, 71-73", "main.py"),
    (0x5F70, "0x0601-0x0603", "Sensor graph legend row 1-3: choose the next sensor for that line", "95", "lib._graph_keys_poll"),
    (0x5F80, "0x0701", "IOT SEND DATA", "96", "dwin_wifi_ui.poll -> iot_bus.ui_send_data"),
    (0x5F80, "0x0702", "IOT RECEIVE DATA", "96", "iot_bus.ui_receive_data"),
    (0x5F80, "0x0703", "IOT SYNC / ID", "96", "iot_bus.ui_sync_id"),
    (0x5F90, "0x0802 / 0x0803", "LLM chat scroll UP / DOWN", "98", "dwin_llm_chat._key"),
    (0x5F90, "0x0804", "LLM chat CLEAR conversation", "98", "dwin_llm_chat._key"),
    (0x5F90, "0x0020-0x007E", "Question character", "99", "dwin_llm_chat._key"),
    (0x5F90, "0x0008 / 0x0805", "Delete / clear the question", "99", "dwin_llm_chat._key"),
    (0x5F90, "0x000D", "SEND the question to the AI", "99", "dwin_llm_chat._key -> lib._llm_send"),
]


def key_meaning(vp, code, page):
    for kvp, codes, meaning, pages, _ in KEY_CODES:
        if kvp != vp:
            continue
        for part in codes.split("/"):
            part = part.strip()
            if "-" in part:
                a, b = (int(x, 16) for x in part.split("-"))
                if a <= code <= b:
                    return meaning + (" '%s'" % chr(code) if 0x20 <= code <= 0x7E else "")
            elif int(part, 16) == code:
                return meaning
    return ""


# ------------------------------------------------------------------ VP map
VP_MAP = [  # (start, end, used for, pages, max / size, set in, notes)
    (0x0010, 0x0013, "Display RTC (system variable)", "10, 45, 97 clock", "4 words", "dwin_get_data (time sync)",
     "This display has no RTC chip: the clock is set by the board after Wi-Fi time sync"),
    (0x0014, 0x0014, "Current page number (system variable, read only)", "all", "1 word", "dwin_wifi_ui.poll reads it every 300 ms", ""),
    (0x0031, 0x0031, "LED_Now: backlight level in use (system)", "56", "1 word", "dwin_wifi_ui._brightness", ""),
    (0x0082, 0x0082, "LED_Config: brightness (high byte 0-100)", "56", "1 word", "SETTINGS buttons / dwin_wifi_ui", "Saved in dwin_brightness.txt"),
    (0x0084, 0x0085, "Page switch command (5A 01 + page)", "all", "2 words", "dwin_screen.dwin_page", ""),
    (0x1000, 0x60DF, "IMAGE PAGE region A dot list (up to 6900 dots)", "39", "20,704 words", "dwin_screen _DW_REGIONS",
     "Also the staging area for flash writes (pictures, video, animations). Other pages borrow parts of it when page 39 is not shown"),
    (0x1000, 0x413A, "LLM CHAT conversation dot list (<= 4200 dots)", "98", "12,602 words", "dwin_llm_chat DOTS_VP", "Inside region A; emptied when the chat pages are left"),
    (0x4200, 0x5396, "LLM CHAT question dot list (<= 1500 dots)", "99", "4,502 words", "dwin_llm_chat KB_DOTS_VP", "Inside region A"),
    (0x5200, 0x5200, "Icon VP, must stay 0 (fixed-icon controls, profile avatar)", "10, 45, 46-49, 97", "1 word", "make_sd_card ICON_VP", "Do not write"),
    (0x5210, 0x5210, "Video animation control (0 = play, 1 = stop)", "44, 50", "1 word", "dwin_screen _DW_VIDEO_VP", ""),
    (0x5220, 0x5226, "Animation controls (0x5220 main, 0x5222/24/26 memories 1-3)", "animation pages", "4 words", "dwin_screen _DW_ANIM_VP", ""),
    (0x5300, 0x534F, "Settings text fields Wi-Fi / Bluetooth / Firmware", "56", "3 x 32 words", "dwin_get_data _VP_WIFI/_BLUETOOTH/_FIRMWARE", ""),
    (0x5400, 0x5E8E, "SHARED dot list (<= 900 dots)", "52-55, 60-62, 92, 95, 96", "2,702 words", "dwin_screen _DW_GESTURE_VP, dwin_wifi_ui DOT_VP",
     "Every page using it redraws it on entry. Keep <= 900 dots so it ends before 0x5F00"),
    (0x5500, 0x5F02, "PROJECTS LIST card text dot list (<= 1200 dots)", "40, 41, 71-73", "3,602 words", "lib PROJECTS_DOTS_VP", "Overlaps the shared area: different pages"),
    (0x5F00, 0x5F00, "Key code: Wi-Fi / Bluetooth keys", "57, 58, 60-62, 92", "1 word", "dwin_wifi_ui KEY_VP", "Board reads it, then writes 0"),
    (0x5F50, 0x5F50, "Key code: Port & Pin Manager", "74-78", "1 word", "dwin_port_test", ""),
    (0x5F60, 0x5F60, "Key code: PROJECTS LIST PLAY / STOP", "40, 41, 71-73", "1 word", "main.py", ""),
    (0x5F70, 0x5F70, "Key code: sensor graph legend rows", "95", "1 word", "lib _GRAPH_KEY_VP", ""),
    (0x5F80, 0x5F80, "Key code: IOT page buttons", "96", "1 word", "dwin_wifi_ui.poll", ""),
    (0x5F90, 0x5F90, "Key code: LLM CHAT keys", "98, 99", "1 word", "dwin_llm_chat KEY_VP", ""),
    (0x6100, 0x6620, "Original project's sensor boxes 1-6 (name 0xN100, icon 0xN110, value 0xN120)", "base pages, 40/41/71-73 icons",
     "6 x 3 fields", "lib _DWIN_BOX_VP", "Card icons on the PROJECTS LIST pages use 0x6110, 0x6210 ... 0x6610. 0x6100-0x8310: original project, do not overwrite"),
    (0x6600, 0x72E6, "Port & Pin Manager dot list (<= 1100 dots)", "74-78", "3,302 words", "dwin_port_test PORT_TEST_DOTS_VP",
     "Inside the original project's area, used only on its own pages"),
    (0x7340, 0x8026, "WI-FI page dot list (<= 1100 dots, pre-filled)", "57", "3,302 words", "dwin_get_data _WIFI_DOTS_VP", ""),
    (0x8030, 0x82E4, "Settings dot list (<= 230 dots)", "56, 58, 59", "692 words", "dwin_get_data SETTINGS_GRAPHICS_VP",
     "Must end before 0x8310. Do NOT use filled rectangles (cmd 0x0004) here: they froze the display (2026-10-30)"),
    (0x8310, 0x8310, "Original project's sensor-page icon", "base", "1 word", "-", "Do not overwrite"),
    (0x8400, 0xFFC3, "IMAGE PAGE region B dot list (up to 10560 dots)", "39", "31,684 words", "dwin_screen _DW_REGIONS", "Also flash staging (0x8402)"),
    (0xFB40, 0xFD1F, "Sensor graph line lists (3 x 160 words)", "95", "160 words each", "lib _GRAPH_VPS", "End of region B: a full picture ends at 0xFB22"),
    (0xFFF0, 0xFFF3, "Scratch (saved-picture slot header)", "-", "4 words", "dwin_screen _DW_SCRATCH_VP", ""),
]

UARTS = [  # (bus, pins, speed, connects to, code, notes)
    ("USART3", "PD8 / PD9 (J5), CR2.SWAP: TX on PD9, RX on PD8", "460800 (falls back to 115200)", "DWIN display DMG48320C035_03W",
     "dwin_screen.py (_DW_BAUDS, _dw_open, _dw_send)", "Display jumpers: display TX2 -> J5 pin 2, RX2 -> J5 pin 5, GND -> pin 1, 5 V from a board 5 V pin (J5 pin 6 is 3.3 V). Baud set in T5LCFG.CFG on the SD card"),
    ("USART6", "PC6 / PC7, CR2.SWAP", "921600", "ESP32-S3 Wi-Fi / BLE gateway (jumpers J4/J5 on the ESP side)",
     "main.py (UART(6)), iot_bus.py", "Lines: IOT:{json} -> ESP32, IOTR:{json} / NET:up|down / STAT:{json} <- ESP32"),
    ("UART1", "PA9 TX / PA10 RX (MOD3 JACK1)", "115200", "AI camera: K230 or ESP32-S3 camera (one at a time)",
     "lib.py async__k230_* / async_voice_* / async_pose_* / async_gesture_* / async__s3_*", "Result lines like 'Detected: cat (93%)' feed the AI live panels 52-55"),
    ("UART2", "PD5 / PD6 (MOD3 JACK2)", "per block", "Free / user UART sensors (GPS, GSM ...)", "lib.py (uart_num argument)", "PD5/PD6 are also MOD1 JACK3/4 DIG"),
    ("USB", "USB CDC (COM88 on this PC)", "-", "PC: Blockly web IDE, REPL, file install", "main.py", "board_main/install_file.py installs a file and checks its CRC"),
    ("I2C1", "PB7 SDA / PB6 SCL (MOD1 jacks pin 1/2)", "100 kHz", "I2C sensors on MOD1", "lib.py I2C(1)", ""),
    ("I2C4", "PD13 SDA / PD12 SCL (MOD2 jacks pin 1/2)", "100-400 kHz", "Accelerometer, gesture, RTC, colour sensors", "lib.py I2C(4)", ""),
    ("SPI2", "PB12-PB15 (MOD3 JACK4)", "5 MHz", "RFID (MFRC522)", "lib.py machine.SPI(2)", ""),
]

JACKS = [  # (module, jack, pin1, pin2, DIG, ANA, notes)
    ("MOD1 analog/digital (I2C1)", "JACK1", "SDA1 PB7", "SCL1 PB6", "D3 (PD3)", "C0 (PC0)", "pins 5 = +5 V, 6 = GND"),
    ("MOD1 analog/digital (I2C1)", "JACK2", "SDA1 PB7", "SCL1 PB6", "D4 (PD4)", "C1 (PC1)", ""),
    ("MOD1 analog/digital (I2C1)", "JACK3", "SDA1 PB7", "SCL1 PB6", "D5 (PD5)", "C2 (PC2)", ""),
    ("MOD1 analog/digital (I2C1)", "JACK4", "SDA1 PB7", "SCL1 PB6", "D6 (PD6)", "F9 (PF9)", ""),
    ("MOD2 analog/digital (I2C4)", "JACK1", "SDA4 PD13", "SCL4 PD12", "D7 (PD7)", "C4 (PC4)", ""),
    ("MOD2 analog/digital (I2C4)", "JACK2", "SDA4 PD13", "SCL4 PD12", "E0 (PE0)", "C5 (PC5)", ""),
    ("MOD2 analog/digital (I2C4)", "JACK3", "SDA4 PD13", "SCL4 PD12", "E1 (PE1)", "A1 (PA1)", ""),
    ("MOD2 analog/digital (I2C4)", "JACK4", "SDA4 PD13", "SCL4 PD12", "G3 (PG3)", "A2 (PA2)", ""),
    ("MOD3 serial / SPI", "JACK1", "UART1 TX PA9", "UART1 RX PA10", "G0 (PG0)", "A4 (PA4)", "AI camera here"),
    ("MOD3 serial / SPI", "JACK2", "UART2 PD5", "UART2 PD6", "G1 (PG1)", "F8 (PF8)", ""),
    ("MOD3 serial / SPI", "JACK3", "UART3 PD8", "UART3 PD9", "G2 (PG2)", "A6 (PA6)", "PD8/PD9 are the display's USART3 (J5)"),
    ("MOD3 serial / SPI", "JACK4", "SPI2 PB12-15", "", "B12 (PB12)", "A7 (PA7)", ""),
    ("MOD4 PWM & motors", "JACK1", "PWM1 PE11 (TIM1_CH2)", "PWM2 PE12", "E3 (PE3)", "A3 (PA3)", "alias PWM_MOD4_J1_1"),
    ("MOD4 PWM & motors", "JACK2", "PWM1 PB9 (TIM4_CH4)", "PWM2 PB8", "G4 (PG4)", "F3 (PF3)", ""),
    ("MOD4 PWM & motors", "JACK3", "PWM1 PE13 (TIM1_CH3)", "PWM2 PB15", "G5 (PG5)", "F4 (PF4)", ""),
    ("MOD4 PWM & motors", "JACK4", "PWM1 PD15 (TIM4_CH4)", "PWM2 PE14", "G6 (PG6)", "F5 (PF5)", ""),
    ("On board", "BUZZER", "", "", "F6 (PF6) alias BUZZ", "", "via Q1 BC847"),
    ("On board", "LED", "", "", "F7 (PF7)", "", "green LD2"),
    ("On board", "BUTTON 1", "", "", "E10 (PE10) alias USRSW", "", "active low, pull-up"),
    ("On board", "BUTTON 2", "", "", "E9 (PE9) alias SW2", "", "active low, pull-up"),
]

ESP_OPS = [  # (op, request fields, reply body, used by, notes)
    ("http", "method, url, body, ctype, headers {..}, timeout (ms)", "code, body (<= 2048 B), err", "lib._iot_call / _llm_send, dwin_get_data (time fallback)",
     "headers + timeout added 2026-10-29 (flash the new firmware for API keys)"),
    ("status", "-", "JSON status", "dwin_get_data (id 1)", ""),
    ("wifi_check", "ssid, pass (optional: join)", "connected state", "dwin_get_data (id 2)", "Local op: works while Wi-Fi is down"),
    ("wifi_scan", "-", "[{ssid, rssi, open}]", "dwin_get_data (id 50), iot_bus.wifi_scan", "Local op"),
    ("wifi_connect", "ssid, pass, force", "{connected, ssid, ip}", "dwin_wifi_ui (id 70), dwin_get_data (id 3)", "Local op"),
    ("wifi_disconnect", "forget", "-", "dwin_get_data (id 51), iot_bus", "Local op"),
    ("wifi_status", "-", "{wifi_up, ssid, ip, rssi}", "iot_bus.wifi_status", "Local op"),
    ("ble_status", "-", "{ble_up, ble_connected, ble_name}", "iot_bus.ble_status", "Local op"),
    ("ble_adv", "on (true/false)", "-", "dwin_wifi_ui (id 72)", "Visible / hidden to phones"),
    ("ble_disconnect", "-", "-", "dwin_wifi_ui (id 73)", ""),
    ("ble_name", "label (max 8: A-Z 0-9 -)", "new name", "dwin_wifi_ui (id 74)", "ESP32 restarts (~10 s)"),
    ("ts_server", "url", "-", "lib (ThingSpeak blocks)", "Cloud server base URL"),
    ("ts_auto", "hw, name / device", "channel info", "lib, iot_bus.ui_sync_id", "Auto-provision a channel"),
    ("ts_connect", "id_ch, wkey, rkey", "-", "lib", ""),
    ("ts_write", "fields {1: value, ...}", "-", "lib, iot_bus.ui_send_data", "Rate limited on the public server"),
    ("ts_read", "field", "value", "lib, iot_bus.ui_receive_data", ""),
    ("time", "-", "-", "dwin_get_data (clock)", "NOT in the firmware (answers bad-op); the board falls back to http GET"),
    ("ts_config", "...", "-", "lib (one block)", "NOT in the firmware (answers bad-op)"),
]

REPLY_IDS = "Fixed reply ids: 1 status, 2 wifi_check, 3 wifi_connect (dwin_get_data); 50 wifi_scan, 51 wifi_disconnect; " \
            "70 Wi-Fi connect (dwin_wifi_ui); 72-74 Bluetooth; 75 LLM chat page; 76 async__llm_ask. iot_bus.call / lib._iot_call count up from 1: " \
            "keep new fixed ids above 50 so they do not meet the counters early on."

FLASH = [  # (flash ID / file, what, from)
    ("0 (0_DWIN_ASC.HZK)", "Font 0 (Arial) for the RTC clock controls; fills IDs 0-11", "SD card"),
    ("13 (13TouchFile.bin)", "Touch buttons of every page (16- and 32-byte records)", "make_sd_card.py"),
    ("14 (14ShowFile.bin)", "Display controls of every page (32 bytes each)", "make_sd_card.py"),
    ("22 (22_Config.bin)", "Copied into VP 0x1000-0xFFFF at boot (all zeros)", "base project"),
    ("24-25 (24_SavedPictures.icl)", "Saved pictures 1-3 + thumbnails (STORAGE)", "board (save picture block) / SD with pictures"),
    ("26 (26_Profile.icl)", "Profile avatar + full picture", "web page uploader (--init-profile once)"),
    ("32-35 (32.icl)", "All page pictures (00.bmp ... 100.bmp)", "make_sd_card.py"),
    ("48 (48_SensorIcons.icl)", "Sensor card icons 0-77 (id = _telemetry_icon_for)", "make_sd_card.py"),
    ("49-63 (49_Video.icl)", "Video frames (up to 3.75 MB)", "Blockly video block (placeholder on SD)"),
    ("T5LCFG.CFG", "Display config: UART baud 460800 (divider 0x07)", "make_sd_card.py DISPLAY_BAUD"),
]

FILES = [  # (file, where, purpose, important?)
    ("main.py", "board", "Starts everything: UART6 gateway reader, idle loop (display pages, keys, clock), runs user.py on PLAY", "Core"),
    ("lib.py / lib.mpy", "board", "All Blockly blocks (sensors, actuators, AI, IoT, LLM, display telemetry). The board loads lib.py before lib.mpy: keep both the same (mpy-cross -march=armv7emdp)", "Core"),
    ("dwin_screen.py", "board", "Display driver: UART3 link (460800), VP read/write, image/video/animation, dot font", "Core (edit directly; do not regenerate with make_dwin_screen.py)"),
    ("dwin_get_data.py", "board", "Settings / Wi-Fi / Bluetooth / IoT page drawing, clock time sync", "Core"),
    ("dwin_wifi_ui.py", "board", "Idle page poller: Wi-Fi + Bluetooth keyboards, brightness, hooks for graph / IoT / AI / LLM pages", "Core"),
    ("dwin_llm_chat.py", "board", "LLM CHAT pages 98-100", "Core"),
    ("dwin_port_test.py", "board", "PORT & PIN MANAGER pages 74-78", "Core"),
    ("iot_bus.py", "board", "ESP32 gateway protocol (IOT:/IOTR:), Wi-Fi/BLE status, IoT page actions", "Core"),
    ("make_dwin_screen.py", "board_r4 (PC)", "Old generator of dwin_screen.py", "Not used: running it undoes direct edits"),
    ("dwin_random_values_uart3.py", "board_r4 (PC)", "Test program (random values to the display)", "Test only"),
    ("test_esp32_standalone.py", "board_r4 (PC)", "ESP32 link test", "Test only"),
    ("dwin/make_sd_card.py", "PC", "Builds the display's DWIN_SET (pages, touches, controls, config) and copies it to the SD card (--keep-memory --sd E:)", "Core tool"),
    ("dwin/dwin_studio.py", "PC", "DWIN Page Studio: edit texts/buttons, list pages after LAST_BUILTIN_PAGE", "Tool"),
    ("dwin/make_reference_xlsx.py", "PC", "Builds this workbook", "Tool"),
    ("board_main/install_file.py", "PC", "Installs one file on the board over USB and checks its CRC, restarts main.py", "Core tool"),
    ("ESP32_CURIO_GATEWAY.ino", "D:/Arun/blockly_img_voice-model_new/esp32-s3_firmware", "ESP32-S3 gateway firmware (Wi-Fi, BLE, HTTP, ThingSpeak)", "Core (flash with Arduino IDE)"),
    ("DEVELOPER_NOTES.txt", "project root", "Change log with the reasons behind each design choice (newest first)", "Read first"),
]

OVERVIEW = [
    ("What this is", "STM32H723 'CM MOTHERBOARD R4' running MicroPython, driving a DWIN DMG48320C035_03W (480x320, T5L DGUS II) display, "
                     "with an ESP32-S3 Wi-Fi/BLE gateway and an AI camera. Users program it with the Blockly web IDE (code goes to user.py)."),
    ("How the display works", "The board writes display memory (VP addresses, 16-bit words) with 5A A5 frames (0x82 write, 0x83 read). "
                              "Text controls do not draw on this display, so all live text is drawn as Basic Graphic dot lists "
                              "(VP: 0x0001, count, then x, y, colour per dot) using the 6x11 font in dwin_screen.py."),
    ("Touch", "Page-switch buttons work inside the display. 'Return key' buttons write a code into a key VP; the board reads that VP, "
              "writes 0 back and acts (see Key Codes)."),
    ("Who draws what", "While no program runs, main.py's idle loop calls dwin_wifi_ui.poll() (~every 50 ms): it reads the page register 0x0014 "
                       "and redraws the page that was opened. While a program runs, lib.py blocks draw (PROJECTS LIST cards, graph, AI panels)."),
    ("Install a board file", "cd board_main ; python install_file.py ../board_r4/<file> <file>. After editing lib.py also build and install lib.mpy. "
                             "Check the board copy first (another developer also installs)."),
    ("Update the display", "cd dwin ; python make_sd_card.py --keep-memory --sd E: then: display off, insert card, on, wait for the download, off, remove, on. "
                           "--keep-memory keeps the pictures, video, animations and profile in the display."),
    ("Regenerate this workbook", "cd dwin ; python make_reference_xlsx.py (after make_sd_card.py, so the page/touch sheets match the card)."),
    ("Watch out", "VP areas are shared between pages (see VP Memory Map); keep dot counts under each area's maximum. "
                  "uasyncio.run() never returns on this board: test through main.py, not the raw REPL. "
                  "Python edit scripts on Windows: write bytes / newline='' or files turn CRLF."),
]


# ------------------------------------------------------------------ functions
SECTION_RE = re.compile(r"^#\s*[-=\u2500#]{2,}\s*([A-Za-z0-9][^-=\u2500#]*?)\s*[-=\u2500#]*\s*$")


def sections(lines):
    """Line number -> nearest section heading above it."""
    out, cur = [], ""
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line.strip())
        if m and len(m.group(1)) > 2:
            cur = m.group(1).strip()
        elif re.match(r"^#{6,}\s*$", line.strip()) and i + 1 < len(lines):
            nxt = lines[i + 1].strip().lstrip("#").strip()
            if nxt and not set(nxt) <= set("-=#"):
                cur = nxt[:70]
        out.append(cur)
    return out


def describe(node, lines):
    doc = ast.get_docstring(node)
    if doc:
        return " ".join(doc.strip().split("\n\n")[0].split())
    i = node.lineno - 2                          # comment block just above
    com = []
    while i >= 0 and lines[i].strip().startswith("#"):
        com.insert(0, lines[i].strip().lstrip("#").strip())
        i -= 1
    return " ".join(c for c in com if c and not set(c) <= set("-=#\u2500"))[:300]


def args_of(node):
    a = node.args
    names = [x.arg for x in a.posonlyargs + a.args]
    defaults = [None] * (len(names) - len(a.defaults)) + list(a.defaults)
    out = []
    for n, d in zip(names, defaults):
        out.append(n if d is None else "%s=%s" % (n, ast.unparse(d)))
    if a.vararg:
        out.append("*" + a.vararg.arg)
    if a.kwarg:
        out.append("**" + a.kwarg.arg)
    return ", ".join(out)


def functions(path):
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    sec = sections(lines)
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, isinstance(node, ast.AsyncFunctionDef), args_of(node), node.lineno,
                        sec[node.lineno - 1], describe(node, lines), node))
    return src, out


def kind_of(name, is_async):
    if name.startswith("async__"):
        return "Block helper (async, not shown on cards)"
    if name.startswith("async_"):
        return "Blockly block (async)"
    if name.startswith("_"):
        return "Internal"
    return "Public (sync)"


def card_key(fn):
    """Card key and kind, the same tests in the same order as lib._telemetry_record."""
    if "buzzer" in fn:
        return "BUZZER:<pin>", "actuator: name only"
    if "servo" in fn:
        return "SERVO:<pin>", "actuator: name only"
    if "motor" in fn:
        return "MOTOR:MAIN", "actuator: name only"
    if any(x in fn for x in ("led", "red", "green", "blue", "rgb")):
        return "LED:<pin>", "actuator: name only"
    if "relay" in fn:
        return "RELAY:<pin>", "actuator: name only"
    if "waterpump" in fn or "pump" in fn:
        return "PUMP:<pin>", "actuator: name only"
    return fn[6:].replace("_", " ").upper() + ":<args>", "sensor: value it returns (no card if it returns None)"


def icon_func(src):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_telemetry_icon_for":
            g = {}
            exec(ast.get_source_segment(src, node), g)
            return g["_telemetry_icon_for"]
    return lambda n: ""


# ------------------------------------------------------------------ writing
def sheet(wb, title, headers, rows, widths, note=None, warn_col=None):
    ws = wb.create_sheet(title)
    r0 = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(name=FONT, italic=True, size=10, color="404040")
        ws.cell(row=1, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        ws.row_dimensions[1].height = 15 * max(1, len(note) // 160 + 1)
        r0 = 2
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=r0, column=c, value=h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BOX
    for r, row in enumerate(rows, r0 + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = BOX
        if warn_col is not None and row[warn_col]:
            for c in range(1, len(headers) + 1):
                ws.cell(row=r, column=c).fill = WARN_FILL
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
    ws.auto_filter.ref = "A%d:%s%d" % (r0, get_column_letter(len(headers)), r0 + len(rows))
    return ws


def main():
    names = page_names()
    last, controls = read_controls()
    touches = read_touches()
    wb = Workbook()
    wb.remove(wb.active)

    # 1. Start here
    ws = wb.create_sheet("Start Here")
    ws["A1"] = "CURIO STM32 BOARD + DWIN DISPLAY - DEVELOPER REFERENCE"
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color="1F3864")
    ws["A2"] = "Generated by dwin/make_reference_xlsx.py from the code and the built display files. Details and history: DEVELOPER_NOTES.txt."
    ws["A2"].font = Font(name=FONT, italic=True, size=10)
    r = 4
    for k, v in OVERVIEW:
        ws.cell(row=r, column=1, value=k).font = Font(name=FONT, bold=True, size=10)
        ws.cell(row=r, column=1).fill = TITLE_FILL
        ws.cell(row=r, column=2, value=v).font = Font(name=FONT, size=10)
        for c in (1, 2):
            ws.cell(row=r, column=c).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=r, column=c).border = BOX
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Sheets").font = Font(name=FONT, bold=True, size=12, color="1F3864")
    r += 1
    for name, what in (("Hardware & UARTs", "Buses, speeds and what is connected"), ("Board Jacks", "MOD1-MOD4 jack pins and on-board parts"),
                       ("Display Pages", "Every display page: what it is and which board code draws it"),
                       ("Display Controls", "Every control on every page (type, VP)"),
                       ("Touch Buttons", "Every touch area: page switch target or key code + key VP"),
                       ("VP Memory Map", "Display memory addresses and who uses them"),
                       ("Key Codes", "Return-key codes and the code that handles them"),
                       ("Sensor Cards", "PROJECTS LIST card slots: page, position, icon VP"),
                       ("Sensor Functions", "Every async_ block in lib.py with its card key and icon"),
                       ("lib.py Functions", "Every function in lib.py"),
                       ("Board Files Functions", "Functions in the other board files"),
                       ("ESP32 Gateway Ops", "IOT:{op} requests the ESP32 understands"),
                       ("Display Flash", "Display flash IDs / SD card files"), ("Files", "Project files and how important they are")):
        ws.cell(row=r, column=1, value=name).font = Font(name=FONT, size=10, bold=True)
        ws.cell(row=r, column=2, value=what).font = Font(name=FONT, size=10)
        r += 1
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 120

    # 2. hardware
    sheet(wb, "Hardware & UARTs", ["Bus", "Pins", "Speed", "Connected to", "Code", "Notes"], UARTS, [10, 34, 18, 34, 40, 70])
    sheet(wb, "Board Jacks", ["Module", "Jack", "Pin 1", "Pin 2", "Pin 3 DIG (Pin name)", "Pin 4 ANA (Pin name)", "Notes"], JACKS,
          [26, 10, 20, 16, 22, 18, 30], note="Pins 5 = +5 V, 6 = GND on every jack. In MicroPython use the short names: Pin('D3'), Pin('C0') ('PD3' raises ValueError).")

    # 3. pages
    rows = []
    for p in range(last + 1):
        what, code = PAGE_INFO.get(p, ("", ""))
        ctl = ", ".join("%s @%s" % (CONTROL_TYPES.get(c[1], hx(c[1], 2)), hx(struct.unpack(">H", c[6:8])[0])) for c in controls.get(p, []))
        rows.append((p, names.get(p, ""), what, code, len(controls.get(p, [])), ctl))
    sheet(wb, "Display Pages", ["Page", "Name", "What it is", "Board code that draws / handles it", "Controls", "Controls (type @ VP)"],
          rows, [7, 26, 52, 58, 9, 60], note="Pages %d-%d are made by make_sd_card.py (pages 0-39 come from the base project in DWIN_SET_bird). "
                                            "LAST_BUILTIN_PAGE = %d: DWIN Page Studio list pages start after it." % (msd.LIST_PAGE, last, msd.LAST_BUILTIN_PAGE))
    rows = []
    for p in range(last + 1):
        for k, c in enumerate(controls.get(p, [])):
            vp = struct.unpack(">H", c[6:8])[0]
            xy = struct.unpack(">HH", c[8:12]) if c[1] in (0x00, 0x01, 0x12) else ("", "")
            rows.append((p, names.get(p, ""), k + 1, hx(c[1], 2), CONTROL_TYPES.get(c[1], "?"), hx(vp), xy[0], xy[1], c.hex()))
    sheet(wb, "Display Controls", ["Page", "Name", "#", "Type code", "Type", "VP", "x", "y", "Raw record (32 bytes)"], rows,
          [7, 26, 5, 10, 28, 9, 7, 7, 70], note="From DWIN_SET_sd/14ShowFile.bin. Basic Graphic controls read a dot/line list at their VP (command, count, then points).")

    # 4. touches
    rows = []
    for t in touches:
        page, x0, y0, x1, y1, target, pressed, code = struct.unpack(">HHHHHHHH", t[:16])
        if code == 0xFE05:
            vp, mode, kc = struct.unpack(">HBH", t[17:22])
            rows.append((page, names.get(page, ""), x0, y0, x1, y1, "Return key", "", hx(vp), hx(kc),
                         pressed if pressed != 0xFF00 else "", key_meaning(vp, kc, page)))
        elif (code >> 8) == 0xFE:
            rows.append((page, names.get(page, ""), x0, y0, x1, y1, "Special " + hx(code), "", "", "", "", ""))
        else:
            rows.append((page, names.get(page, ""), x0, y0, x1, y1, "Page switch", target if target != 0xFF00 else "",
                         "", "", "", ("-> " + names.get(target, "")) if target != 0xFF00 else ""))
    sheet(wb, "Touch Buttons", ["Page", "Page name", "x0", "y0", "x1", "y1", "Type", "Goes to page", "Key VP", "Key code",
                                "Pressed picture page", "Meaning"], rows, [7, 24, 6, 6, 6, 6, 13, 10, 9, 9, 10, 50],
          note="From DWIN_SET_sd/13TouchFile.bin (%d buttons). Return keys write the code into the key VP; the board reads it and writes 0 back." % len(rows))

    # 5. VP map, key codes
    sheet(wb, "VP Memory Map", ["Start", "End", "Used for", "Pages", "Size / max", "Set in (file / constant)", "Notes"],
          [(hx(a), hx(b), u, p, s, f, n) for a, b, u, p, s, f, n in VP_MAP], [9, 9, 50, 22, 14, 40, 70],
          note="16-bit word addresses. A dot list uses 2 + 3 x dots words (+1 end word). Rows in orange are areas you must not write.",
          warn_col=None)
    ws = wb["VP Memory Map"]
    for r in range(3, ws.max_row + 1):
        if "not overwrite" in str(ws.cell(row=r, column=7).value) or "Do not write" in str(ws.cell(row=r, column=7).value):
            for c in range(1, 8):
                ws.cell(row=r, column=c).fill = WARN_FILL
    sheet(wb, "Key Codes", ["Key VP", "Code(s)", "Meaning", "Pages", "Handled in"],
          [(hx(v), c, m, p, h) for v, c, m, p, h in KEY_CODES], [9, 16, 58, 16, 46])

    # 6. sensors
    src, funcs = functions(os.path.join(BOARD, "lib.py"))
    icon = icon_func(src)
    rows = []
    for k in range(30):
        i = k % 6
        rows.append((k + 1, msd.PROJECT_PAGES[k // 6], i + 1, 14 + (i % 3) * 154, 56 + (i // 3) * 103,
                     hx((0x61 + i) << 8 | 0x10), "0x5500 (shared by the page's 6 cards)"))
    sheet(wb, "Sensor Cards", ["Card (order of first use)", "Page", "Slot on page", "Card x", "Card y", "Icon VP (icon id from 48_SensorIcons.icl)",
                               "Text dots VP"], rows, [14, 8, 10, 8, 8, 30, 34],
          note="When a program calls an async_ block, lib._telemetry_record() makes a card key 'NAME:pins' (e.g. 'ULTRASONIC:D3,D4'), label 'NAME (pins)' "
               "and the value text; the first 30 different keys get cards in order. Name label at (x+12, y+8), value at (x+62, y+49). "
               "Ignored: names in _TELEMETRY_IGNORE, async__ helpers, sync functions.")
    seen = {}
    rows = []
    for name, is_async, args, line, sec, desc, node in funcs:
        if not (is_async and name.startswith("async_") and not name.startswith("async__")):
            continue
        dup = "defined again at line %d (this copy is unused)" % seen[name] if name in seen else ""
        seen[name] = line
        key, kind = card_key(name)
        rows.append((name, args, key, kind, icon(name[6:]), sec, line, desc, ""))
    # mark the overridden (earlier) copies
    last_line = {}
    for r_ in rows:
        last_line[r_[0]] = r_[6]
    rows = [r_[:8] + ("overridden by line %d" % last_line[r_[0]] if last_line[r_[0]] != r_[6] else "",) for r_ in rows]
    sheet(wb, "Sensor Functions", ["Function (Blockly block)", "Arguments", "Card key", "Card type", "Card icon id", "lib.py section", "Line",
                                   "Description", "Duplicate?"], rows, [34, 36, 26, 18, 10, 34, 7, 70, 22],
          note="Every async_ block in lib.py. Icon id = lib._telemetry_icon_for(name) (0 = blank). Rows with 'overridden' are earlier copies of a name: "
               "Python keeps the last definition.", warn_col=8)

    # 7. functions
    rows = []
    for name, is_async, args, line, sec, desc, node in funcs:
        rows.append((name, "async" if is_async else "", args, kind_of(name, is_async), sec, line, desc,
                     "overridden by line %d" % max(l for n, _, _, l, *_ in funcs if n == name) if
                     line != max(l for n, _, _, l, *_ in funcs if n == name) else ""))
    sheet(wb, "lib.py Functions", ["Function", "Async", "Arguments", "Kind", "Section", "Line", "Description", "Duplicate?"], rows,
          [36, 7, 40, 26, 34, 7, 80, 20], note="All top-level functions in board_r4/lib.py (%d). Orange = an earlier copy that a later "
                                               "definition replaces." % len(rows), warn_col=7)
    rows = []
    for fname in ("main.py", "dwin_screen.py", "dwin_get_data.py", "dwin_wifi_ui.py", "dwin_llm_chat.py", "dwin_port_test.py", "iot_bus.py"):
        try:
            _, fs = functions(os.path.join(BOARD, fname))
        except SyntaxError as e:
            rows.append((fname, "(could not parse: %s)" % e, "", "", "", "", ""))
            continue
        for name, is_async, args, line, sec, desc, node in fs:
            rows.append((fname, name, "async" if is_async else "", args, sec, line, desc))
    sheet(wb, "Board Files Functions", ["File", "Function", "Async", "Arguments", "Section", "Line", "Description"], rows,
          [18, 32, 7, 40, 30, 7, 80])

    # 8. ESP32, flash, files
    sheet(wb, "ESP32 Gateway Ops", ["op", "Request fields", "Reply", "Used by (reply id)", "Notes"], ESP_OPS, [16, 44, 30, 46, 60],
          note="Board -> ESP32 (UART6): IOT:{\"id\":N,\"op\":\"...\",...}  ESP32 -> board: IOTR:{\"id\":N,\"code\":200,\"body\":\"...\",\"err\":\"\"}. " + REPLY_IDS)
    sheet(wb, "Display Flash", ["Flash ID / file", "Holds", "Made by"], FLASH, [30, 70, 44],
          note="16 MB flash, 256 KB per ID. The SD card's DWIN_SET folder is copied into flash when the display starts with the card inserted.")
    sheet(wb, "Files", ["File", "Where", "Purpose", "Importance"], FILES, [30, 34, 90, 36])

    wb.save(OUT)
    print("saved", OUT, "| sheets:", ", ".join(wb.sheetnames))


if __name__ == "__main__":
    main()
