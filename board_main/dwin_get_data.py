"""Standalone & background Wi-Fi / Bluetooth / Firmware & Live Clock manager for DWIN.

Merges:
1. DWIN Settings pages (56-59): Wi-Fi connection, scan list, Bluetooth & Firmware status (VP 0x5300-0x5340; graphic VPs 0x7340 and 0x8030).
2. DWIN Live Internet Clock: NTP & HTTPS time sync and Pages 10 & 45 RTC controls (VP 0x0010).

Works in TWO ways:
1. AUTOMATIC (No Blockly needed):
   main.py calls dwin_get_data.refresh() every 2.5s (and dwin_get_data.tick() every 1s).
   - Tapping SETTINGS on the DWIN display shows live Wi-Fi, Bluetooth, and scan lists.
   - The Home top bar continuously shows live 12-hour time, AM/PM, and full date.
2. STANDALONE (Run directly as a .py file on the board):
   Can be executed directly (`import dwin_get_data; dwin_get_data.main()`).
"""
import gc
import os
import sys
import time
import json
import struct
import binascii
import machine
from machine import UART

# ==============================================================================
# DWIN VP Memory Definitions
# ==============================================================================
_VP_WIFI = 0x5300
_VP_BLUETOOTH = 0x5320
_VP_FIRMWARE = 0x5340
_FIELD_BYTES = 28

_WIFI_DOTS_VP = 0x7340       # dedicated page 57 buffer, ready before navigation
_WIFI_DOTS_MAX = 1100        # ends at 0x8026
_wifi_buf = bytearray(6 * _WIFI_DOTS_MAX)
SETTINGS_GRAPHICS_VP = 0x8030  # pages 56,58,59 share; max 230 dots ends at 0x82E4
SETTINGS_DOTS_VP = SETTINGS_GRAPHICS_VP
BLUETOOTH_DOTS_VP = SETTINGS_GRAPHICS_VP
FIRMWARE_DOTS_VP = SETTINGS_GRAPHICS_VP
CLOCK_VP = SETTINGS_GRAPHICS_VP  # legacy dot renderer, unused with RTC display controls
# True: the display draws the clock itself (RTC display controls on pages 10/45,
# need the 0_DWIN_ASC.HZK font on the SD card); the board only writes the time
# into VP 0x0010 once a minute. Keep True: current SD pages have no dot-clock control.
CLOCK_ON_DISPLAY = True
_disp_rtc_ms = None        # (hour, minute) last written to the display
CLOCK_MAX = 400            # legacy renderer; HOME uses the display RTC control
TZ_OFFSET_S = 5 * 3600 + 30 * 60      # India Standard Time (+05:30)
RESYNC_MS = 15 * 60 * 1000             # resync every 15 minutes
RETRY_MS = 30000
REPLY_TIMEOUT_MS = 15000
TIME_URL = "https://timeapi.io/api/Time/current/zone?timeZone=UTC"
_ID_NTP, _ID_HTTP = 60, 61

WHITE, YELLOW, GREY = 0xFFFF, 0xFEA0, 0x8C71
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# Default Wi-Fi credentials for automatic standalone connection if not in ESP32 NVS
DEFAULT_WIFI_SSID = "Curio_Labs"
DEFAULT_WIFI_PASS = ""

# 1-dot-thick 5x7 glyphs designed specifically for DWIN's 3x3 hardware dot renderer
_GLYPHS = {
    '0': (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    '1': (".#.", "##.", ".#.", ".#.", ".#.", ".#.", "###"),
    '2': ("####.", "....#", "....#", ".###.", "#....", "#....", "#####"),
    '3': ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    '4': ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    '5': ("#####", "#....", "#....", "####.", "....#", "....#", "####."),
    '6': (".####", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    '7': ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    '8': (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    '9': (".###.", "#...#", "#...#", ".####", "....#", "....#", "####."),
    ':': ("#", ".", ".", ".", "#", ".", "."),
    '-': (".....", ".....", ".....", ".###.", ".....", ".....", "....."),
    '.': ("...", "...", "...", "...", "...", "...", ".#."),
    'A': (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    'B': ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    'C': (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    'D': ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    'E': ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    'F': ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    'G': (".####", "#....", "#....", "#..##", "#...#", "#...#", ".####"),
    'H': ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    'I': (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    'J': ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    'K': ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    'L': ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    'M': ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    'N': ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    'O': (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    'P': ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    'Q': (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    'R': ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    'S': (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    'T': ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    'U': ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    'V': ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    'W': ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    'X': ("#...#", ".#.#.", "..#..", "..#..", "..#..", ".#.#.", "#...#"),
    'Y': ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    'Z': ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    '_': (".....", ".....", ".....", ".....", ".....", ".....", "#####"),
    '?': (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    '#': (".#.#.", "#####", ".#.#.", ".#.#.", "#####", ".#.#.", "....."),
    '(': ("..#.", ".#..", "#...", "#...", "#...", ".#..", "..#."),
    ')': ("#...", ".#..", "..#.", "..#.", "..#.", ".#..", "#..."),
    '/': ("....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."),
}

# Overlapping 3x3 hardware dot positions (0x0001) covering Arial Bold 18pt
_ADOTS = {k: (adv, binascii.unhexlify(hx)) for k, (adv, hx) in (
    ('A', (13, '05010207050808080704010a090b03040402000b07050208090a06020a0b')),
    ('B', (13, '01010401070101040406070601070909010a040b070b0803010b08060801080a')),
    ('C', (13, '0401080201040107080a040b020a0601060b0202090309090108')),
    ('D', (13, '010104010104090401070907010a040b0701070a010b0909060b0802')),
    ('E', (12, '0101040107010104040607060107010a040b070b0801010b080b')),
    ('F', (11, '010104010701010404060107010a0606010b')),
    ('G', (14, '040107010104010707070a07050b020a090a0903070b02020a090a020108')),
    ('H', (13, '0101090101040904040601070907010a090a0606010b090b')),
    ('I', (5, '010101040107010a010b')),
    ('J', (10, '060106040607050a020b0009040b010a')),
    ('K', (13, '0101010405050107010a07020708090b04060901010b0603080902070605')),
    ('L', (11, '010101040107010a040b070b010b')),
    ('M', (15, '01010a010104090401070b070609010a0b0a04040b04060b0301080605070b01010b0b0b090207080508')),
    ('N', (13, '010109010104090401070907010a080a04040507090b0708010b020209080709')),
    ('O', (14, '0401070101040a0401070a08040b070b020a02020902090a0a050108')),
    ('P', (12, '010104010803010404060107010a07060701010b0804')),
    ('Q', (14, '0401070101040a0401070a070709040b090b020a060b020209020a0a0b0c01080708')),
    ('R', (13, '010104010701010404060107010a090307060709090b010b0805060708010809')),
    ('S', (12, '0301060104060808030b060b0103010a080207060205080a0201')),
    ('T', (11, '00010301060104040407040a0801040b')),
    ('U', (13, '010109010104090401070907020a080a050b0108040b060b')),
    ('V', (12, '040a000108020205070503080608050b01020901040b')),
    ('W', (17, '0701010403090a0900010e010d0409050b0b0604030b0c0805070207080204090d05090606020208')),
    ('X', (12, '04040407010108010709020a080b06030506000b03030209')),
    ('Y', (12, '04050202080107040408040b0001030405050901')),
    ('Z', (11, '010104010701010a040b070b0307000b0603080b0406010b0109')),
    ('0', (10, '0603060801020109040b040100050605060a020b010806020201')),
    ('1', (10, '0402010304050408040b04010104')),
    ('2', (10, '020a060305060201010b050b030805010102020b060b06040407')),
    ('3', (10, '0602050502010608010a040b04010102060a0405020b')),
    ('4', (10, '05020107050805050204050b00080708020805010403')),
    ('5', (10, '0105020106060609010b040b05000304060001040405060a')),
    ('6', (10, '010301060109050104050609030b02010606050b0601010a')),
    ('7', (10, '0601030704040100020a0401020b0502')),
    ('8', (10, '0603010302060506010a06090301040b0501010702010606060a010b')),
    ('9', (10, '0603060601060609010b0201040b050101030307050a')),
    ('-', (6, '01080308')),
    ('.', (5, '010b')),
    ('_', (10, '000f030f060f070f')),
    (':', (6, '0104010b')),
    ('/', (5, '01040008')),
    ('(', (6, '0104010a02010007010d020f')),
    (')', (6, '0204020a01010207010d010f')),
    ('#', (10, '0203060301080508000b040b0004050507080201060101050703020800090303')),
    ('?', (11, '040b0703040702010501060501020601')),
    ('+', (11, '01060406070603030309')),
    ('%', (16, '020102040901080406070b09050a0b0c040c000203020c0a000303030c0b')),
    ('!', (6, '010101040107010b')),
    ('@', (18, '0a050b02090a050b0401060404070d0a020307000e030e06010c0d0e040f070f0a0f0a070a0b0a01010504090704060b0e070b0b0505')),
    ('&', (13, '03050709020201080506090b0501020b0603050b090802060702070a050701090301')),
    ('*', (7, '0203010102040302')),
)}

# BLUETOOTH page (58): where the board draws the state and the name label
# (= BT_STATE_POS / BT_LABEL_POS in dwin/make_sd_card.py). The name is always
# BLE_PREFIX, plus "-" and a label set on the display (ESP32 op ble_name).
BT_STATE_POS = (31, 86)
BT_LABEL_POS = (246, 160)
BT_DOTS_MAX = 244          # 0x8032 + 3 x 244 stays below the sensor icon VP 0x8310
BLE_PREFIX = "ESP32-BLE-CURIO_V2"
bt_override = None         # (text, until ms): e.g. "RESTARTING" while the ESP32 renames


def ble_label(st=None):
    """The label part of the ESP32's Bluetooth name ('' if none)."""
    import iot_bus
    name = (st or iot_bus.status()).get("ble_name") or ""
    return name[len(BLE_PREFIX) + 1:] if name.startswith(BLE_PREFIX + "-") else ""

# Settings state
_last = None
_last_send_ms = 0
_last_probe_ms = 0
_last_scan_ms = 0
_auto_connect_tried = 0       # automatic join attempts since power-on
_auto_connect_ms = None
_scan_unstuck = False         # already told the ESP32 to stop retrying for this empty scan
_last_wifi_dots = None
_last_wifi_dots_ms = 0
_last_settings_graphics = {}
_last_graphics_page = None
_scan_request_ms = 0
_scan_pending = False
wifi_rows = []            # networks shown in the 4 rows of page 57 (dicts from the scan)

# Clock state
_clock_synced_ms = None
_clock_source = ""
_clock_pending = None
_clock_req_ms = 0
_clock_last_try_ms = None
_clock_last_key = None
_clock_last_draw_ms = 0
_clock_buf = None


# ==============================================================================
# Low-level UART & Background Maintenance
# ==============================================================================
def _ensure_esp_uart():
    """Ensure iot_bus has UART6 (with R4 CR2.SWAP) initialized when running standalone."""
    import iot_bus
    if iot_bus._uart is None:
        u = UART(6, baudrate=921600, timeout=0, rxbuf=16384)
        usart6_base = 0x40011400
        cr1 = machine.mem32[usart6_base]
        machine.mem32[usart6_base] = cr1 & ~1
        machine.mem32[usart6_base + 4] |= 1 << 15
        machine.mem32[usart6_base] = cr1
        iot_bus.set_uart(u)
    return iot_bus._uart


def _poll_esp_uart_nonblocking():
    """If main.py's timer is not active (standalone mode), parse any waiting UART6 lines."""
    import iot_bus
    u = _ensure_esp_uart()
    if u is None or not u.any():
        return
    try:
        raw = u.read()
        if not raw:
            return
        for line in raw.decode("utf-8", "ignore").splitlines():
            s = line.strip()
            if s.startswith("IOTR:"):
                iot_bus.feed(s)
            elif s.startswith("NET:"):
                iot_bus.set_net(s[4:].strip() == "up")
            elif s.startswith("STAT:"):
                iot_bus.set_status(s[5:].strip())
    except Exception:
        pass


def _wifi_target():
    """(ssid, password) to join automatically: the network last connected from
    the display (dwin_wifi_ui writes wifi_choice.txt), else the default.
    The ESP32 only retries its saved network at power-on, so the board does it."""
    try:
        with open("wifi_choice.txt") as f:
            c = json.loads(f.read())
        if c.get("ssid"):
            return c["ssid"], c.get("pass", "")
    except (OSError, ValueError):
        pass
    return DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS


def _background_maintenance():
    """Non-blocking probes so Settings works automatically without any user blocks."""
    global _last_probe_ms, _auto_connect_tried, _auto_connect_ms
    global _scan_request_ms, _scan_pending, _scan_unstuck
    try:
        import iot_bus
        if iot_bus._uart is None:
            return
        now = time.ticks_ms()
        st = iot_bus.status()
        if not st.get("wifi_enabled", True) and _scan_pending:
            iot_bus.take(50)
            _scan_pending = False

        if _scan_pending:
            rep = iot_bus.take(50)
            if rep is not None:
                _scan_pending = False
                if rep.get("code") == 200:
                    iot_bus._status["legacy_fw"] = False
                    try:
                        nets = json.loads(rep.get("body", "[]"))
                        if isinstance(nets, list):
                            iot_bus._status["scan"] = nets
                            iot_bus._status["scan_count"] = len(nets)
                            if not nets and not st.get("wifi_up") and not _scan_unstuck:
                                # The ESP32 keeps retrying a saved network that is not
                                # around, and its scans fail while it does. Stop that
                                # (the network stays saved) and scan again.
                                _scan_unstuck = True
                                iot_bus._uart_write('IOT:{"id":51,"op":"wifi_disconnect"}\n')
                                iot_bus._uart_write('IOT:{"id":50,"op":"wifi_scan"}\n')
                                _scan_request_ms, _scan_pending = now, True
                            elif nets:
                                _scan_unstuck = False
                    except Exception:
                        pass
                elif str(rep.get("err", "")).startswith("bad-op:"):
                    iot_bus._status["legacy_fw"] = True
            elif time.ticks_diff(now, _scan_request_ms) > 20000:
                _scan_pending = False

        if not st.get("esp_present"):
            if _last_probe_ms == 0 or time.ticks_diff(now, _last_probe_ms) > 2000:
                _last_probe_ms = now
                iot_bus._uart_write('IOT:{"id":1,"op":"status"}\n')
                iot_bus._uart_write('IOT:{"id":2,"op":"wifi_check"}\n')
            return

        if not st.get("wifi_enabled", True):
            # OFF is a saved user choice. Do not scan or auto-join behind their back.
            iot_bus._status["scan"] = []
            return

        if not _scan_pending and (_scan_request_ms == 0 or
                                  time.ticks_diff(now, _scan_request_ms) > 60000):
            _scan_request_ms = now
            _scan_pending = True
            iot_bus._uart_write('IOT:{"id":50,"op":"wifi_scan"}\n')

        if not st.get("wifi_up"):
            ssid, pw = _wifi_target()
            # up to 3 tries per power-on, 2 minutes apart (a join blocks the ESP32 ~15 s)
            if (ssid and _auto_connect_tried < 3 and
                    (_auto_connect_ms is None or time.ticks_diff(now, _auto_connect_ms) > 120000)):
                nets = st.get("scan", [])
                if any(isinstance(n, dict) and n.get("ssid") == ssid for n in nets):
                    _auto_connect_tried += 1
                    _auto_connect_ms = now
                    req = {"id": 3, "op": "wifi_connect", "ssid": ssid, "pass": pw}
                    iot_bus._uart_write("IOT:" + json.dumps(req) + "\n")
    except Exception:
        pass


# ==============================================================================
# Clock Synchronization & Rendering
# ==============================================================================
def _epoch_2000():
    return time.gmtime(0)[0] == 2000


# Software clock. The R4's hardware RTC runs slow (measured 2026-10-24: 13 s
# per 30 s real time, LSE selected), so the clock counts from ticks_ms (CPU
# crystal) after each internet sync and corrects the RTC once a minute.
_soft_base = None          # local time (seconds since epoch) at _soft_ticks
_soft_ticks = 0


def _write_rtc(t):
    lt = time.localtime(t)
    machine.RTC().datetime((lt[0], lt[1], lt[2], lt[6] + 1, lt[3], lt[4], lt[5], 0))


def _local_seconds():
    """Current local time in seconds since epoch (software clock if synced)."""
    global _soft_base, _soft_ticks
    if _soft_base is None:
        return time.time()
    el = time.ticks_diff(time.ticks_ms(), _soft_ticks)
    if el >= 3600000:      # re-base hourly so ticks_ms wrap-around never matters
        _soft_base += el // 1000
        _soft_ticks = time.ticks_add(_soft_ticks, (el // 1000) * 1000)
        el = time.ticks_diff(time.ticks_ms(), _soft_ticks)
    return _soft_base + el // 1000


def _local_now():
    return time.localtime(_local_seconds())


def _set_rtc_from_utc_tuple(y, mo, d, h, mi, s):
    global _soft_base, _soft_ticks
    t = time.mktime((y, mo, d, h, mi, s, 0, 0)) + TZ_OFFSET_S
    _soft_base, _soft_ticks = t, time.ticks_ms()
    _write_rtc(t)


def _set_rtc_from_unix(unix_s):
    t = int(unix_s) - (946684800 if _epoch_2000() else 0)
    lt = time.gmtime(t)
    _set_rtc_from_utc_tuple(lt[0], lt[1], lt[2], lt[3], lt[4], lt[5])


def _clock_request(rid):
    global _clock_pending, _clock_req_ms, _clock_last_try_ms
    import iot_bus
    if rid == _ID_NTP:
        req = {"id": rid, "op": "time"}
    else:
        req = {"id": rid, "op": "http", "method": "GET", "url": TIME_URL}
    iot_bus._uart_write("IOT:" + json.dumps(req) + "\n")
    _clock_pending = rid
    _clock_req_ms = _clock_last_try_ms = time.ticks_ms()


def _clock_handle_reply(rep):
    global _clock_synced_ms, _clock_source, _clock_pending, _clock_last_key
    rid = _clock_pending
    _clock_pending = None
    ok = False
    try:
        if rep.get("code") == 200:
            if rid == _ID_NTP:
                _set_rtc_from_unix(int(rep.get("body", "0")))
                _clock_source = "ntp"
            else:
                j = json.loads(rep.get("body", "{}"))
                _set_rtc_from_utc_tuple(j["year"], j["month"], j["day"],
                                        j["hour"], j["minute"], j["seconds"])
                _clock_source = "http"
            ok = True
    except Exception as e:
        print("clock: bad time reply:", e)
    if ok:
        _clock_synced_ms = time.ticks_ms()
        _clock_last_key = None
        print("clock: time set from %s: %s" % (_clock_source, now_text()))
    elif rid == _ID_NTP:
        _clock_request(_ID_HTTP)
    return ok


def _clock_sync_step(now):
    global _clock_pending
    try:
        import iot_bus
    except ImportError:
        return
    if iot_bus._uart is None:
        return
    if _clock_pending is not None:
        rep = iot_bus.take(_clock_pending)
        if rep is not None:
            _clock_handle_reply(rep)
        elif time.ticks_diff(now, _clock_req_ms) > REPLY_TIMEOUT_MS:
            if _clock_pending == _ID_NTP:
                _clock_request(_ID_HTTP)
            else:
                _clock_pending = None
        return
    if not iot_bus.net_up():
        return
    due = (_clock_synced_ms is None or time.ticks_diff(now, _clock_synced_ms) > RESYNC_MS)
    if due and (_clock_last_try_ms is None or time.ticks_diff(now, _clock_last_try_ms) > RETRY_MS):
        _clock_request(_ID_NTP)


def sync_now():
    global _clock_synced_ms, _clock_last_try_ms
    _clock_synced_ms = None
    _clock_last_try_ms = None


def valid():
    return _clock_synced_ms is not None or time.localtime()[0] >= 2025


def now_text():
    lt = _local_now()
    return "%04d-%02d-%02d %02d:%02d:%02d" % lt[:6]


def screen_parts(lt=None, ok=True, net=True):
    if not ok:
        return ("--:--", "", "NO WI-FI TIME" if not net else "SYNCING TIME...")
    h = lt[3] % 12 or 12
    return ("%d:%02d" % (h, lt[4]), "AM" if lt[3] < 12 else "PM",
            "%s %02d %s %04d" % (_DAYS[lt[6]], lt[2], _MONTHS[lt[1] - 1], lt[0]))


def render_clock(parts, buf, limit=CLOCK_MAX):
    """Emit 1 hardware dot per active cell in _GLYPHS.
    step=3 produces 15x21 time digits; step=2 produces 10x14 AM/PM and date characters."""
    n = 0

    def add_str(text, x, y, sx, sy, colour, gap, space_w):
        nonlocal n
        for ch in text:
            if ch == ' ':
                x += space_w
                continue
            g = _GLYPHS.get(ch)
            if not g:
                continue
            cols = len(g[0])
            y_off = 3 if ch == ':' else 0
            for r, row in enumerate(g):
                for c, val in enumerate(row):
                    if val == '#' and n < limit:
                        struct.pack_into('>HHH', buf, n * 6,
                                         x + c * sx, y + y_off + r * sy, colour)
                        n += 1
            x += (cols - 1) * sx + 3 + gap
        return x

    t, ampm, date = parts
    x = add_str(t, 10, 14, 3, 3, WHITE, gap=4, space_w=8)
    if ampm:
        x = add_str(ampm, x + 2, 21, 2, 2, YELLOW, gap=3, space_w=6)
    date_x = max(124, x + 10)
    add_str(date, date_x, 18, 2, 2, WHITE if ampm else GREY, gap=3, space_w=7)
    return n


render = render_clock


def _draw_clock(parts):
    global _clock_buf
    import dwin_screen as dw
    if _clock_buf is None:
        _clock_buf = bytearray(6 * CLOCK_MAX)
    n = render_clock(parts, _clock_buf)
    vp = CLOCK_VP + 2
    mv = memoryview(_clock_buf)
    for i in range(0, n * 6, 120):                   # 20 dots per UART frame
        dw._dw_vp(vp + i // 2, mv[i:min(n * 6, i + 120)])
    dw._dw_vp(vp + n * 3, b'\xff\xff')              # end of list
    dw._dw_vp(CLOCK_VP, struct.pack('>HH', 1, n))   # draw command + count
    return n


def _set_display_rtc():
    """Write the board's time into the display's clock register (VP 0x0010); the
    RTC display controls on the home pages draw it with the display's own font.
    This display has no clock chip and does not count by itself (tested
    2026-10-24), so tick() writes it once a minute: one 14-byte frame."""
    import dwin_screen as dw
    lt = _local_now()
    if lt[0] < 2025:
        return False
    # Correct hardware RTC once a minute as well
    try:
        _write_rtc(_local_seconds())
    except Exception:
        pass
    # DWIN VP 0x0010: Year-2000, Month, Day, Weekday (1=Mon..7=Sun), Hour, Minute, Second, 0
    weekday = (lt[6] + 1) if lt[6] < 7 else 1
    dw._dw_vp(0x0010, bytes((lt[0] - 2000, lt[1], lt[2], weekday, lt[3], lt[4], lt[5], 0)))
    return True


def tick():
    """Update NTP/HTTP time synchronization and refresh the Home top-bar live clock."""
    global _clock_last_key, _clock_last_draw_ms, _disp_rtc_ms
    now = time.ticks_ms()
    _clock_sync_step(now)
    if CLOCK_ON_DISPLAY:
        # the display draws the clock itself: give it the time when the minute changes
        minute = _local_now()[3:5]
        if valid() and (minute != _disp_rtc_ms or _clock_last_key is None):
            if _set_display_rtc():
                _disp_rtc_ms, _clock_last_key = minute, "display"
        return
    ok = valid()
    lt = _local_now()
    net = True
    if not ok:
        try:
            import iot_bus
            net = iot_bus.net_up()
        except ImportError:
            net = False
    parts = screen_parts(lt, ok, net)
    if parts != _clock_last_key or time.ticks_diff(now, _clock_last_draw_ms) > 60000:
        _draw_clock(parts)
        _clock_last_key, _clock_last_draw_ms = parts, now


clock_tick = tick


def clock_status():
    return {"valid": valid(), "time": now_text(), "source": _clock_source,
            "synced_ago_s": None if _clock_synced_ms is None else time.ticks_diff(time.ticks_ms(), _clock_synced_ms) // 1000,
            "pending": _clock_pending}


status = clock_status


# ==============================================================================
# Settings (Wi-Fi, Bluetooth, Firmware) Presentation & Rendering
# ==============================================================================
def get_data():
    """Return live Wi-Fi, Bluetooth, and Firmware statuses observed from ESP32 + STM32."""
    _background_maintenance()
    try:
        import iot_bus
        st = iot_bus.status() if hasattr(iot_bus, "status") else {}
        gateway_present = st.get("esp_present", iot_bus.esp_present())
        if not gateway_present:
            wifi = "Gateway not detected"
            bluetooth = "Gateway not detected"
        else:
            if not st.get("wifi_enabled", True):
                wifi = "Wi-Fi OFF"
            elif st.get("wifi_up") or iot_bus.net_up():
                ssid = st.get("ssid") or "ESP32"
                ip = st.get("ip") or ""
                if ip and len(ssid) + len(ip) + 3 <= _FIELD_BYTES:
                    wifi = "%s (%s)" % (ssid, ip)
                else:
                    wifi = "Connected: %s" % ssid
            else:
                cnt = st.get("scan_count", -1)
                top = st.get("top_ssid", "")
                if cnt > 0 and top:
                    wifi = "Avail(%d): %s" % (cnt, top)
                elif cnt == 0:
                    wifi = "Disconnected (0 nets)"
                else:
                    wifi = "Scanning Wi-Fi..."

            if st.get("ble_connected"):
                bluetooth = "Connected (%s)" % (st.get("ble_name") or "BLE")
            elif st.get("ble_up", True):
                bluetooth = "Ready: %s" % (st.get("ble_name") or "ESP32-BLE-CURIO_V2")
            else:
                bluetooth = "BLE unavailable"
    except ImportError:
        wifi = "Gateway status unavailable"
        bluetooth = "Status unavailable"

    try:
        mp = os.uname().release
    except Exception:
        mp = sys.version.split(';')[1].strip().split(' on ')[0] if ';' in sys.version else "unknown"
    firmware = "MP %s / app r4.6-video" % mp
    return {"wifi": wifi, "bluetooth": bluetooth, "firmware": firmware}


def _field(value):
    raw = str(value).encode('ascii', 'replace')[:_FIELD_BYTES]
    return raw + bytes(_FIELD_BYTES - len(raw))


def _wifi_screen_lines(st):
    if not st.get("esp_present"):
        return ("Gateway not detected", "Check ESP32 power", "No scan data",)
    action = st.get("wifi_action") or ""
    if not st.get("wifi_enabled", True):
        return ("Wi-Fi is OFF", action or "Tap ON to reconnect", "Networks hidden while OFF")
    if st.get("legacy_fw") and not st.get("ssid") and not st.get("scan"):
        status_txt = "Wi-Fi link up (ESP32)" if st.get("wifi_up") else "ESP32 gateway online"
        detail = "Old ESP32 fw (no STAT/scan)"
        return (status_txt, detail, "Flash updated gateway .ino", "for SSID, IP & scan list")
    if st.get("wifi_up"):
        ssid = st.get("ssid") or ""
        status_txt = "ON: " + ssid if ssid else "Wi-Fi link up"
        detail = st["ip"] if st.get("ip") else "IP unavailable"
    else:
        status_txt, detail = "Wi-Fi disconnected", "Select a network"
    if action:
        detail = action
    nets = st.get("scan") or []
    rows = []
    for n in nets[:4]:
        if isinstance(n, dict) and n.get("ssid"):
            rows.append(n["ssid"])
    if not rows:
        fallback = st.get("top_ssid") or st.get("ssid") or ""
        if fallback:
            rows = [fallback]
        else:
            count = st.get("scan_count", -1)
            rows = ["Scanning..." if _scan_pending else
                    ("%d seen; list unavailable" % count if count > 0 else
                     "No networks found" if count == 0 else "Scan unavailable")]
    return (status_txt, detail) + tuple(rows)


def _draw_wifi_dots(force=False):
    """Prepare Page 57's dedicated dot list before the user opens Wi-Fi."""
    global _last_wifi_dots, _last_wifi_dots_ms, wifi_rows
    import dwin_screen as dw
    import iot_bus
    now = time.ticks_ms()
    st = iot_bus.status()
    enabled = st.get("wifi_enabled", True)
    nets = [n for n in (st.get("scan") or []) if isinstance(n, dict) and n.get("ssid")] if enabled else []
    if enabled and not nets:
        fallback = st.get("top_ssid") or st.get("ssid") or ""
        if fallback:
            nets = [{"ssid": fallback, "open": False}]
    wifi_rows = nets[:4]
    lines = _wifi_screen_lines(st)
    if (not force and lines == _last_wifi_dots and _last_wifi_dots_ms and
            time.ticks_diff(now, _last_wifi_dots_ms) < 30000):
        return
    buf = _wifi_buf
    count = 0

    def add(label, x, y, colour, budget):
        nonlocal count
        used = 0
        for char in str(label).upper()[:36]:
            if char == ' ':
                x += 6
                continue
            adv, pts = _ADOTS.get(char, _ADOTS['?'])
            dots = len(pts) // 2
            if used + dots > budget or count + dots > _WIFI_DOTS_MAX or x + adv > 442:
                break
            for k in range(0, len(pts), 2):
                struct.pack_into('>HHH', buf, count * 6,
                                 x + pts[k], y + pts[k + 1], colour)
                count += 1
            used += dots
            x += adv + 1
        return used

    add(lines[0], 31, 106, 0x1947, 250)
    add(lines[1], 31, 127, 0x63B1, 200)
    rows = lines[2:6]
    for i, name in enumerate(rows):
        remaining_rows = len(rows) - i - 1
        budget = min(300, _WIFI_DOTS_MAX - count - 100 * remaining_rows)
        add(name, 31, 202 + 28 * i, 0x1947, max(0, budget))

    vp = _WIFI_DOTS_VP + 2
    data = memoryview(buf)
    for pos in range(0, count * 6, 120):
        dw._dw_vp(vp + pos // 2, data[pos:min(count * 6, pos + 120)])
    dw._dw_vp(vp + count * 3, b'\xff\xff')
    dw._dw_vp(_WIFI_DOTS_VP, struct.pack('>HH', 1, count))
    _last_wifi_dots, _last_wifi_dots_ms = lines, now


def _draw_settings_graphic(vp, labels, positions, limit, force=False):
    """Render short status labels as DWIN Basic Graphic dots.

    The display's 0x11 text fields are garbled even with the new 0# font.
    Each bitmap cell becomes one 3x3 hardware dot, as for the working clock.
    """
    global _last_settings_graphics
    now = time.ticks_ms()
    old = _last_settings_graphics.get(vp)
    labels = tuple(labels)
    if not force and old and old[0] == labels and time.ticks_diff(now, old[1]) < 30000:
        return
    import dwin_screen as dw
    buf = _wifi_buf
    n = 0
    for label, (x0, y0) in zip(labels, positions):
        x = x0
        for ch in str(label).upper()[:24]:
            if ch == ' ':
                x += 6
                continue
            entry = _ADOTS.get(ch)
            if entry:
                adv, pts = entry
                for k in range(0, len(pts), 2):
                    if n < limit:
                        struct.pack_into('>HHH', buf, n * 6, x + pts[k], y0 + pts[k + 1], 0x1947)
                        n += 1
                x += adv + 1
            else:
                x += 6
            if x > 450:
                break
    data = memoryview(buf)
    for pos in range(0, n * 6, 120):
        dw._dw_vp(vp + 2 + pos // 2, data[pos:min(n * 6, pos + 120)])
    dw._dw_vp(vp + 2 + n * 3, b'\xff\xff')
    dw._dw_vp(vp, struct.pack('>HH', 1, n))
    _last_settings_graphics[vp] = (labels, now)


_VP_WIFI_ICON = 0x5360
_VP_BT_ICON = 0x5362
_VP_BT_STATE_ICON = 0x5364
_VP_HOME_BT_ICON = 0x5366
_VP_HOME_WIFI_ICON = 0x5368
_STATUS_ICONS = {
    'NO GATEWAY': 78,
    'OFFLINE': 79,
    'ONLINE': 80,
    'OFF': 81,
    'READY': 82,
    'PAIRED': 83,
    'VISIBLE': 84,
    'HIDDEN': 85,
    'CONNECTED': 86,
    'RESTARTING': 87,
}
_last_status_icons = None


def _update_settings_icons(force=False):
    """Send 2-byte Variable Icon IDs for Wi-Fi & Bluetooth status (stored in 48_SensorIcons.icl)."""
    global _last_status_icons
    import iot_bus
    import dwin_screen as dw
    st = iot_bus.status()
    if not st.get('esp_present'):
        wifi, ble, state = 'NO GATEWAY', 'OFF', 'NO GATEWAY'
        home_bt, home_wifi = 88, 88
    else:
        wifi = 'OFF' if not st.get('wifi_enabled', True) else ('ONLINE' if st.get('wifi_up') else 'OFFLINE')
        ble = 'PAIRED' if st.get('ble_connected') else ('READY' if st.get('ble_up') else 'OFF')
        if st.get('ble_connected'):
            state = 'CONNECTED'
        else:
            state = 'VISIBLE' if st.get('ble_visible', True) else 'HIDDEN'
        home_bt = 89 if st.get('ble_connected') else 88
        home_wifi = 90 if st.get('wifi_up') else 88
    if bt_override and time.ticks_diff(bt_override[1], time.ticks_ms()) > 0:
        state = bt_override[0]
    icons = (
        _STATUS_ICONS.get(wifi, 78),
        _STATUS_ICONS.get(ble, 81),
        _STATUS_ICONS.get(state, 78),
        home_bt,
        home_wifi,
    )
    if force or icons != _last_status_icons:
        dw._dw_vp(_VP_WIFI_ICON, struct.pack('>H', icons[0]))
        dw._dw_vp(_VP_BT_ICON, struct.pack('>H', icons[1]))
        dw._dw_vp(_VP_BT_STATE_ICON, struct.pack('>H', icons[2]))
        dw._dw_vp(_VP_HOME_BT_ICON, struct.pack('>H', icons[3]))
        dw._dw_vp(_VP_HOME_WIFI_ICON, struct.pack('>H', icons[4]))
        _last_status_icons = icons


def _draw_settings_dots(page, force=False):
    import iot_bus
    st = iot_bus.status()
    _update_settings_icons(force=force)
    fw = 'R4.6'
    if page == 56:
        # Wi-Fi and Bluetooth status use in-display Arial Bold Variable Icons (0x5360, 0x5362);
        # Firmware stays drawn as dots from the STM32 board.
        _draw_settings_graphic(SETTINGS_DOTS_VP, (fw,),
                               ((31, 242),), 100, force)
    elif page == 58:
        # Bluetooth status uses in-display Arial Bold Variable Icon (0x5364);
        # custom Bluetooth name label stays drawn as dots.
        _draw_settings_graphic(BLUETOOTH_DOTS_VP, (ble_label(st) or 'NONE',),
                               (BT_LABEL_POS,), BT_DOTS_MAX, force)
    elif page == 59:
        _draw_settings_graphic(FIRMWARE_DOTS_VP, ('MP ' + os.uname().release, fw),
                               ((31, 101), (31, 124)), 150, force)


_IOT_DOTS_VP = 0x5400
_IOT_DOTS_MAX = 880
_last_iot_sig = None
_last_iot_ms = 0


def draw_iot_page(force=False):
    """Render live Wi-Fi, Cloud, Kit ID, Send Data (TX), and Receive Data (RX) on Page 96."""
    global _last_iot_sig, _last_iot_ms
    import dwin_screen as dw
    import iot_bus
    now = time.ticks_ms()
    st = iot_bus.get_iot_state()
    if st["wifi_up"]:
        ssid = (st.get("ssid") or "").strip()
        wifi_txt = ("ON:" + ssid[:9]) if ssid else "CONNECTED"
        wifi_col = 0x04A3
    elif st["esp_present"]:
        wifi_txt = "OFFLINE"
        wifi_col = 0xD984
    else:
        wifi_txt = "NO GATEWAY"
        wifi_col = 0x63B1

    if st["wifi_up"] and st["cloud_ok"]:
        ch = st.get("channel_id") or ""
        cloud_txt = ("SYNCED #" + ch[:4]) if ch else "CONNECTED"
        cloud_col = 0x04A3
    elif st["wifi_up"]:
        cloud_txt = "READY ONLINE"
        cloud_col = 0x4A5C
    else:
        cloud_txt = "OFFLINE"
        cloud_col = 0x63B1

    kit_txt = st.get("kit_id") or "CURIO-0000"
    tx1 = (st.get("tx_data") or "READY")[:16]
    tx2 = (st.get("tx_status") or "TAP SEND")[:16]
    rx1 = (st.get("rx_data") or "WAITING")[:16]
    rx2 = (st.get("rx_status") or "TAP RECEIVE")[:16]

    sig = (wifi_txt, cloud_txt, kit_txt, tx1, tx2, rx1, rx2)
    if not force and sig == _last_iot_sig and time.ticks_diff(now, _last_iot_ms) < 15000:
        return

    buf = _wifi_buf
    n = 0
    items = (
        (wifi_txt, 22, 85, 228, wifi_col, 150),
        (cloud_txt, 254, 85, 460, cloud_col, 150),
        (kit_txt, 92, 148, 460, 0x1947, 200),
        (tx1, 22, 213, 228, 0x1947, 130),
        (tx2, 22, 240, 228, 0x04A3, 120),
        (rx1, 254, 213, 460, 0x1947, 130),
        (rx2, 254, 240, 460, 0x233B, 120),
    )
    for text, x0, y0, xmax, col, budget in items:
        x = x0
        used = 0
        for ch in str(text).upper():
            if ch == ' ':
                x += 6
                continue
            adv, pts = _ADOTS.get(ch, _ADOTS['?'])
            if x + adv > xmax:
                break
            dots = len(pts) // 2
            if used + dots > budget or n + dots > _IOT_DOTS_MAX:
                break
            for k in range(0, len(pts), 2):
                struct.pack_into('>HHH', buf, n * 6, x + pts[k], y0 + pts[k + 1], col)
                n += 1
            used += dots
            x += adv + 1

    mv = memoryview(buf)
    for pos in range(0, n * 6, 120):
        dw._dw_vp(_IOT_DOTS_VP + 2 + pos // 2, mv[pos:min(n * 6, pos + 120)])
    dw._dw_vp(_IOT_DOTS_VP + 2 + n * 3, b'\xff\xff')
    dw._dw_vp(_IOT_DOTS_VP, struct.pack('>HH', 1, n))
    _last_iot_sig, _last_iot_ms = sig, now



def refresh(force=False):
    """Push changed fields to DWIN RAM, refresh Wi-Fi dots, and tick the live clock."""
    global _last, _last_send_ms, _last_graphics_page, _last_iot_sig
    gc.collect()
    import dwin_screen
    now = time.ticks_ms()
    periodic_resync = (_last_send_ms == 0 or time.ticks_diff(now, _last_send_ms) >= 10000)
    values = get_data()
    sent = []
    for name, vp in (("wifi", _VP_WIFI), ("bluetooth", _VP_BLUETOOTH), ("firmware", _VP_FIRMWARE)):
        value = _field(values[name])
        if force or periodic_resync or _last is None or value != _last.get(name):
            if dwin_screen._dw_vp(vp, value):
                sent.append(name)
    if _last is None:
        _last = {}
    for name in sent:
        _last[name] = _field(values[name])
    if sent:
        _last_send_ms = now
    # Wi-Fi has a dedicated VP, so keep it ready even while SETTINGS is visible.
    _draw_wifi_dots(force=force)
    _update_settings_icons(force=force or periodic_resync)
    # The other three pages share a VP: draw only the visible one.
    page_data = dwin_screen._dw_read(0x0014, 1)
    page = page_data[0] if page_data else None
    redraw = force or page != _last_graphics_page
    if _last_graphics_page == 96 and page != 96:
        dwin_screen._dw_vp(_IOT_DOTS_VP, b'\x00\x00\x00\x00')
        _last_iot_sig = None
    if page in (56, 58, 59):
        _draw_settings_dots(page, force=redraw)
    elif page == 96:
        draw_iot_page(force=redraw)
    else:
        # Keep Page 56's Firmware ('R4.6') pre-loaded while on Home pages
        _draw_settings_dots(56, force=False)
    _last_graphics_page = page
    tick()
    return values


# ==============================================================================
# Public Control APIs (Used by Blockly and dwin_screen)
# ==============================================================================
def scan_wifi():
    """Scan available Wi-Fi networks on the ESP32 gateway and refresh Settings VPs."""
    import iot_bus
    _ensure_esp_uart()
    nets = iot_bus.wifi_scan()
    refresh(force=True)
    return nets


def connect_wifi(ssid, password="", force=False):
    """Connect ESP32 gateway to Wi-Fi and refresh Settings VPs."""
    import iot_bus
    _ensure_esp_uart()
    ok = iot_bus.wifi_connect(ssid, password, force=force)
    refresh(force=True)
    return ok


def disconnect_wifi(forget=False):
    """Disconnect ESP32 gateway from Wi-Fi and refresh Settings VPs."""
    import iot_bus
    _ensure_esp_uart()
    ok = iot_bus.wifi_disconnect(forget=forget)
    refresh(force=True)
    return ok


def check_status(query=True):
    """Actively query Wi-Fi and BLE status from ESP32 and refresh Settings VPs."""
    import iot_bus
    _ensure_esp_uart()
    w = iot_bus.wifi_status(query=query)
    b = iot_bus.ble_status(query=query)
    vals = refresh(force=True)
    return {"display": vals, "wifi": w, "bluetooth": b}


# ==============================================================================
# Standalone CLI / Debug Runner
# ==============================================================================
def main(open_settings_page=False):
    """Standalone runner: can be executed directly without Blockly."""
    import dwin_screen
    _ensure_esp_uart()
    print("==================================================")
    print("STANDALONE DWIN SETTINGS & CLOCK (Wi-Fi + BLE + FW)")
    print("==================================================")
    if open_settings_page:
        dwin_screen.dwin_page(56)

    _poll_esp_uart_nonblocking()
    vals = refresh(force=True)
    print("Initial display fields:", vals)
    print("Initial clock:", now_text())

    last_print = None
    try:
        while True:
            _poll_esp_uart_nonblocking()
            vals = refresh(force=False)
            if vals != last_print:
                print("[SETTINGS] Wi-Fi: %-26s | Clock: %s" % (vals["wifi"], now_text()))
                last_print = dict(vals)
            time.sleep_ms(500)
    except KeyboardInterrupt:
        print("Standalone DWIN settings stopped.")


def start():
    main(open_settings_page=False)


if __name__ == "__main__":
    main(open_settings_page=False)
