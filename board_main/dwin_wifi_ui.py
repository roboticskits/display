"""Wi-Fi setup on the DWIN display: tap a network, type the password, connect.

Pages (SD card, dwin/make_sd_card.py):
  57      WI-FI: status + 4 network rows + ON / OFF / SCAN buttons
  60-62   keyboard: letters, CAPS, symbols (63-65 = the same keys pressed)
Every key is a DWIN "return key" touch control: it writes its code into
KEY_VP. The board polls that address (main.py calls poll() every loop while
no program runs), clears it and acts on the code:
  0x0101-0x0104  network row 1-4 on page 57     0x0110  SCAN
  0x0112         Wi-Fi radio ON                  0x0113  Wi-Fi radio OFF
  0x20-0x7E      character                      0x0008  delete
  0x000D         CONNECT                        0x0111  show / hide password
The keyboard's text (network, password, status) is a dot list at DOT_VP,
drawn with dwin_screen's 6 x 11 font (text controls do not draw on this
display). Connecting goes through the ESP32 gateway (iot_bus wifi_connect),
without blocking: poll() picks up the reply.
"""
import gc
import json
import sys
import time

KEY_VP = 0x5F00
DOT_VP = 0x5400                       # same dot area as the gesture page (different page)
DOT_MAX = 900                         # 0x5402 + 3 x 900 ends before KEY_VP (0x5F00)
PAGE_WIFI = 57
PAGE_KB = (60, 61, 62)
REQ_ID = 70
TOGGLE_ID = 71
CONNECT_TIMEOUT_MS = 25000
CHOICE_FILE = "wifi_choice.txt"       # written after a successful connect from the display
CHAT_PAGES = (98, 99, 100)            # LLM CHAT (dwin_llm_chat.py)

INK, MUTED, GREEN, RED = 0x1947, 0x63B1, 0x0C66, 0xD0A3

_ssid = ""
_pw = ""
_show = False
_msg = ""
_msg_colour = MUTED
_connect_t0 = None
_done_t0 = None
_toggle_t0 = None
_toggle_target = True
_page = None
_page_t = 0
_buf = bytearray(6 * 1100)


def _dw():
    import dwin_screen
    return dwin_screen


def _set_msg(text, colour=MUTED):
    global _msg, _msg_colour
    _msg, _msg_colour = text, colour


def _draw():
    """Redraw the keyboard pages' text: network, password field, status."""
    global _buf
    gc.collect()
    dw = _dw()
    if _buf is None:
        _buf = bytearray(6 * 1100)              # _dw_text_dots may fill up to its own 1100
    buf = _buf
    shown = _pw if _show else "*" * len(_pw)
    n = dw._dw_text_dots(buf, 0, "Wi-Fi: " + _ssid[:30], 16, 52, 2, INK)
    n = dw._dw_text_dots(buf, n, (shown[-30:] + "_") if len(shown) < 30 else shown[-30:], 20, 79, 2, INK)
    n = min(DOT_MAX, dw._dw_text_dots(buf, n, _msg[:38], 16, 106, 2, _msg_colour))
    mv = memoryview(buf)
    vp = DOT_VP + 2
    for i in range(0, n * 6, 120):
        dw._dw_vp(vp + i // 2, mv[i:min(n * 6, i + 120)])
    dw._dw_vp(vp + n * 3, b'\xff\xff')
    dw._dw_vp(DOT_VP, bytes((0, 1, n >> 8, n & 0xFF)))


def _rows():
    rows = []
    try:
        import dwin_get_data
        rows = [n for n in getattr(dwin_get_data, "wifi_rows", []) if isinstance(n, dict) and n.get("ssid")]
    except Exception:
        pass
    if not rows:
        try:
            import iot_bus
            st = iot_bus.status()
            rows = [n for n in (st.get("scan") or []) if isinstance(n, dict) and n.get("ssid")][:4]
            if not rows:
                fallback = st.get("top_ssid") or st.get("ssid") or ""
                if fallback:
                    rows = [{"ssid": fallback, "open": False}]
        except Exception:
            pass
    return rows


def _toggle_wifi(on):
    global _toggle_t0, _toggle_target
    import iot_bus
    import dwin_get_data as g
    if not iot_bus.esp_present():
        iot_bus._status["wifi_action"] = "Gateway not detected"
        g._draw_wifi_dots(force=True)
        return
    iot_bus.take(TOGGLE_ID)
    _toggle_target = bool(on)
    _toggle_t0 = time.ticks_ms()
    iot_bus._status["wifi_action"] = "Switching Wi-Fi..."
    iot_bus._uart_write('IOT:' + json.dumps({"id": TOGGLE_ID, "op": "wifi_enable", "on": bool(on)}) + '\n')
    g._draw_wifi_dots(force=True)


def _check_toggle(now):
    global _toggle_t0
    if _toggle_t0 is None:
        return
    import iot_bus
    import dwin_get_data as g
    rep = iot_bus.take(TOGGLE_ID)
    if rep is None and time.ticks_diff(now, _toggle_t0) <= CONNECT_TIMEOUT_MS:
        return
    _toggle_t0 = None
    if rep is None:
        iot_bus._status["wifi_action"] = "Wi-Fi switch timed out"
    elif rep.get("code") != 200:
        iot_bus._status["wifi_action"] = ("Update ESP32 firmware" if
                                           str(rep.get("err", "")).startswith("bad-op:") else
                                           "Wi-Fi switch failed")
    else:
        try:
            info = json.loads(rep.get("body") or "{}")
        except ValueError:
            info = {}
        iot_bus._status["wifi_enabled"] = bool(info.get("enabled", _toggle_target))
        iot_bus._status["wifi_up"] = bool(info.get("connected", False))
        iot_bus._status["wifi_action"] = ""
        if not _toggle_target:
            iot_bus._status["scan"] = []
            iot_bus._status["scan_count"] = -1
        else:
            g._scan_request_ms = 0
            g._scan_unstuck = False
            g._auto_connect_tried = 0
    g._draw_wifi_dots(force=True)
    g._update_settings_icons(force=True)


def _open_keyboard(row):
    global _ssid, _pw, _show, _connect_t0, _done_t0, _page
    rows = _rows()
    if row >= len(rows) or not rows[row].get("ssid"):
        return
    net = rows[row]
    _ssid, _pw, _show, _connect_t0, _done_t0 = net["ssid"], "", False, None, None
    _set_msg("Open network - press CONNECT" if net.get("open") else "Type password, then press CONNECT")
    _dw().dwin_page(PAGE_KB[0])
    _page = PAGE_KB[0]
    try:
        _draw()
    except Exception as e:
        print("wifi kb draw:", e)


def _connect():
    global _connect_t0
    import iot_bus
    if not iot_bus.esp_present():
        _set_msg("Wi-Fi module (ESP32) not found", RED)
        _draw()
        return
    iot_bus.take(REQ_ID)
    req = {"id": REQ_ID, "op": "wifi_connect", "ssid": _ssid, "pass": _pw, "force": True}
    iot_bus._uart_write("IOT:" + json.dumps(req) + "\n")
    _connect_t0 = time.ticks_ms()
    _set_msg("Connecting to %s ..." % _ssid[:20])
    _draw()


def _check_connect():
    global _connect_t0, _done_t0
    import iot_bus
    rep = iot_bus.take(REQ_ID)
    if rep is None:
        if time.ticks_diff(time.ticks_ms(), _connect_t0) > CONNECT_TIMEOUT_MS:
            _connect_t0 = None
            _set_msg("No answer from Wi-Fi module", RED)
            _draw()
        return
    _connect_t0 = None
    info = {}
    try:
        info = json.loads(rep.get("body") or "{}")
    except Exception:
        pass
    if rep.get("code") == 200 and info.get("connected", True):
        iot_bus._status["wifi_up"] = True
        iot_bus._status["ssid"] = info.get("ssid", _ssid)
        iot_bus._status["ip"] = info.get("ip", "")
        try:
            with open(CHOICE_FILE, "w") as f:          # dwin_get_data rejoins it when it is back
                f.write(json.dumps({"ssid": _ssid, "pass": _pw}))
        except OSError:
            pass
        _set_msg("Connected!  IP %s" % info.get("ip", ""), GREEN)
        _done_t0 = time.ticks_ms()
    else:
        print("wifi connect failed:", rep)
        _set_msg("Failed - check the password", RED)
    _draw()


def _key(k):
    global _pw, _show
    if k in (0x0112, 0x0113):
        if _toggle_t0 is None:
            _toggle_wifi(k == 0x0112)
        return
    if _toggle_t0 is not None:
        return
    try:
        import iot_bus
        if not iot_bus.status().get("wifi_enabled", True) and (0x0101 <= k <= 0x0104 or k == 0x0110):
            return
    except Exception:
        pass
    if 0x0101 <= k <= 0x0104:
        _open_keyboard(k - 0x0101)
        return
    if k == 0x0110:
        try:
            import dwin_get_data
            import iot_bus
            if iot_bus.esp_present():
                iot_bus._uart_write('IOT:{"id":50,"op":"wifi_scan"}\n')
                dwin_get_data._scan_request_ms = time.ticks_ms()
                dwin_get_data._scan_pending = True
            else:
                dwin_get_data._scan_request_ms = 0
                dwin_get_data._scan_pending = False
            dwin_get_data._draw_wifi_dots(force=True)
        except Exception as e:
            print("wifi scan:", e)
        return
    if _connect_t0 is not None:                         # ignore typing while connecting
        return
    if 0x20 <= k <= 0x7E:
        if len(_pw) < 63:
            _pw += chr(k)
    elif k == 0x0008:
        _pw = _pw[:-1]
    elif k == 0x0111:
        _show = not _show
    elif k == 0x000D:
        _connect()
        return
    else:
        return
    if _msg_colour == RED:
        _set_msg("Type password, then press CONNECT")
    _draw()


# ---- Bluetooth (page 58 buttons + rename keyboard page 92) ---------------------
# Page 58 keys: 0x0120 visible ON/OFF, 0x0121 disconnect the phone/app,
# 0x0122 rename. Page 92 (93 = keys pressed): A-Z, 0-9, '-' as ASCII, 0x0008
# delete, 0x0130 clear, 0x000D SAVE; CANCEL / BACK are plain page switches.
# The ESP32 ops ble_adv / ble_disconnect / ble_name answer at once; a rename
# restarts the ESP32 (Bluetooth and Wi-Fi drop for ~10 s).
PAGE_BT = 58
PAGE_BT_KB = 92
BT_IDS = {72: "adv", 73: "disc", 74: "name"}
_bt_label = ""
_bt_msg = ""
_bt_msg_colour = MUTED
_bt_back_t0 = None


def _bt_draw():
    """Rename keyboard text: the fixed start of the name, the label, a hint."""
    global _buf
    gc.collect()
    dw = _dw()
    if _buf is None:
        _buf = bytearray(6 * 1100)
    buf = _buf
    n = dw._dw_text_dots(buf, 0, "Label after the name:", 16, 52, 2, INK)
    n = dw._dw_text_dots(buf, n, _bt_label + "_", 20, 79, 2, INK)
    n = min(DOT_MAX, dw._dw_text_dots(buf, n, _bt_msg[:38], 16, 106, 2, _bt_msg_colour))
    mv = memoryview(buf)
    for i in range(0, n * 6, 120):
        dw._dw_vp(DOT_VP + 2 + i // 2, mv[i:min(n * 6, i + 120)])
    dw._dw_vp(DOT_VP + 2 + n * 3, b'\xff\xff')
    dw._dw_vp(DOT_VP, bytes((0, 1, n >> 8, n & 0xFF)))


def _bt_send(rid, op, **params):
    import iot_bus
    if not iot_bus.esp_present():
        return False
    iot_bus.take(rid)
    req = {"id": rid, "op": op}
    req.update(params)
    iot_bus._uart_write("IOT:" + json.dumps(req) + "\n")
    return True


def _bt_redraw():
    try:
        import dwin_get_data as g
        g._draw_settings_dots(PAGE_BT, force=True)
    except Exception as e:
        print("bluetooth page:", e)


def _bt_say(text, colour=MUTED):
    global _bt_msg, _bt_msg_colour
    _bt_msg, _bt_msg_colour = text, colour
    _bt_draw()


def _bt_key(k):
    global _bt_label, _bt_back_t0
    import iot_bus
    if k == 0x0120:                                     # visible ON / OFF
        on = not iot_bus._status.get("ble_visible", True)
        if _bt_send(72, "ble_adv", on=on):
            iot_bus._status["ble_visible"] = on
        _bt_redraw()
    elif k == 0x0121:                                   # disconnect the phone / app
        _bt_send(73, "ble_disconnect")
    elif k == 0x0122:                                   # rename: open the keyboard
        import dwin_get_data as g
        _bt_label = g.ble_label()
        _bt_say("Max 8: A-Z 0-9 -")
        _dw().dwin_page(PAGE_BT_KB)
    elif _bt_back_t0 is not None:                       # saved: ignore keys until back on 58
        return
    elif k == 0x000D:                                   # SAVE
        if _bt_send(74, "ble_name", label=_bt_label):
            _bt_say("Saved - restarting", GREEN)
            _bt_back_t0 = time.ticks_ms()
        else:
            _bt_say("ESP32 not found", RED)
    elif k == 0x0008:
        _bt_label = _bt_label[:-1]
        _bt_say(_bt_msg, _bt_msg_colour)
    elif k == 0x0130:
        _bt_label = ""
        _bt_say(_bt_msg, _bt_msg_colour)
    elif (0x30 <= k <= 0x39 or 0x41 <= k <= 0x5A or k == 0x2D) and len(_bt_label) < 8:
        _bt_label += chr(k)
        _bt_say(_bt_msg, _bt_msg_colour)


def _bt_poll(now):
    """Replies from the ESP32, and the way back to page 58 after SAVE."""
    global _bt_back_t0, _page
    import iot_bus
    for rid, what in BT_IDS.items():
        rep = iot_bus.take(rid)
        if rep is not None:
            if what == "name" and rep.get("code") == 200:
                iot_bus._status["ble_name"] = rep.get("body") or iot_bus._status.get("ble_name", "")
            if _page == PAGE_BT:
                _bt_redraw()
    if _bt_back_t0 is not None and time.ticks_diff(now, _bt_back_t0) > 2000:
        _bt_back_t0 = None
        import dwin_get_data as g
        g.bt_override = ("RESTARTING", time.ticks_add(now, 10000))
        _dw().dwin_page(PAGE_BT)
        _page = PAGE_BT
        _bt_redraw()


# ---- display brightness (SETTINGS page buttons) --------------------------------
# The buttons write the level straight into the display's brightness register
# (VP 0x0082 high byte, 0-100). While SETTINGS is open the board checks the
# display really uses it (LED_Now, VP 0x0031) and applies it otherwise, and it
# remembers the level: the display goes back to full brightness at power-on.
PAGE_SETTINGS = 56
BRIGHT_FILE = "dwin_brightness.txt"
_bright_restored = False
_bright_saved = None
_bright_t = 0


def _brightness(dw, now):
    global _bright_restored, _bright_saved, _bright_t
    if not _bright_restored:
        _bright_restored = True
        try:
            with open(BRIGHT_FILE) as f:
                _bright_saved = int(f.read())
            cfg = dw._dw_read(0x0082, 1)
            if cfg and 10 <= _bright_saved <= 100:
                dw._dw_vp(0x0082, bytes((_bright_saved, cfg[0] & 0xFF)))
        except (OSError, ValueError):
            pass
    if _page != PAGE_SETTINGS or time.ticks_diff(now, _bright_t) < 400:
        return
    _bright_t = now
    cfg = dw._dw_read(0x0082, 1)
    cur = dw._dw_read(0x0031, 1)
    if not cfg or not cur:
        return
    want = cfg[0] >> 8
    if not 10 <= want <= 100:
        return
    if want != (cur[0] & 0xFF):
        dw._dw_vp(0x0082, bytes((want, cfg[0] & 0xFF)))
    if want != _bright_saved:
        _bright_saved = want
        try:
            with open(BRIGHT_FILE, "w") as f:
                f.write(str(want))
        except OSError:
            pass


def busy():
    """True while a keyboard is open: main.py then skips its slow redraws."""
    return (_page in PAGE_KB or _page == PAGE_BT_KB or _page in CHAT_PAGES or
            _connect_t0 is not None or _toggle_t0 is not None)


def poll():
    """Called from main.py's idle loop (about every 50 ms)."""
    global _page, _page_t, _done_t0
    dw = _dw()
    now = time.ticks_ms()
    _check_toggle(now)
    if time.ticks_diff(now, _page_t) > 80:
        p = dw._dw_read(0x0014, 1)
        _page_t = now
        if p:
            previous_page = _page
            _page = p[0]
            if (_page != previous_page and
                    previous_page in (52, 53, 54, 55, 60, 61, 62, 63, 64, 65, 92, 93, 95, 96) and
                    _page not in (60, 61, 62, 63, 64, 65, 92, 93)):
                # Immediately clear shared VP 0x5400 on page exit so old dots never
                # flash for a split-second when opening another 0x5400 page later.
                dw._dw_vp(DOT_VP, b'\x00\x00\x00\x00')
                try:
                    import dwin_get_data as g
                    g._last_iot_sig = None
                except Exception:
                    pass
                lib = sys.modules.get('lib')
                if lib and hasattr(lib, '_graph'):
                    lib._graph['legend'] = None
            if _page != previous_page and _page in (40, 41, 71, 72, 73):
                lib = sys.modules.get('lib')
                if lib and hasattr(lib, '_telemetry_draw'):
                    lib._telemetry_draw(page=_page, force=True)
            if _page != previous_page and _page in (52, 53, 54, 55):   # AI pages, no program running
                lib = sys.modules.get('lib')
                if lib and hasattr(lib, '_ai_live_idle'):
                    lib._ai_live_idle(_page)
            if _page != previous_page and (_page in CHAT_PAGES or previous_page in CHAT_PAGES):
                try:
                    import dwin_llm_chat
                    dwin_llm_chat.poll(_page, True)
                except Exception as e:
                    print('llm chat:', e)
            if _page != previous_page and _page == 95:   # SENSOR GRAPH: show the last history
                lib = sys.modules.get('lib')
                if lib and hasattr(lib, '_graph_draw'):
                    lib._graph_draw(force=True)
            if _page != previous_page and _page == 96:   # IOT & KIT-TO-KIT page
                try:
                    import dwin_get_data as g
                    g.draw_iot_page(force=True)
                    g._last_graphics_page = 96
                except Exception:
                    pass
            if _page != previous_page and _page in (74, 75, 76, 77, 78):
                try:
                    import dwin_port_test
                    dwin_port_test.poll()
                except Exception:
                    pass
            if _page != previous_page and _page in (56, 57, 58, 59):
                # Wi-Fi has a dedicated, prefilled buffer for instant entry.
                # The other Settings pages share one buffer and need redraw.
                try:
                    import dwin_get_data as g
                    if _page == PAGE_WIFI:
                        header = dw._dw_read(g._WIFI_DOTS_VP, 2)
                        if not g.wifi_rows or not header or header[0] != 1 or not 0 < header[1] <= g._WIFI_DOTS_MAX:
                            g._draw_wifi_dots(force=True)
                    else:
                        g._draw_settings_dots(_page, force=True)
                    g._last_graphics_page = _page
                except Exception as e:
                    print('settings page redraw:', e)
    _brightness(dw, now)
    chat = sys.modules.get('dwin_llm_chat')
    if _page in CHAT_PAGES or (chat and chat._t0 is not None):   # LLM CHAT keys / awaited answer
        try:
            import dwin_llm_chat
            dwin_llm_chat.poll(_page, False)
        except Exception as e:
            print('llm chat:', e)
        if _page in CHAT_PAGES:
            return
    if _page == 95:                                    # SENSOR GRAPH: legend row taps (idle)
        lib = sys.modules.get('lib')
        if lib and hasattr(lib, '_graph_keys_poll') and lib._graph_keys_poll():
            lib._graph_draw(force=True)
        return
    if _page == 96:                                    # IOT & KIT-TO-KIT: SEND / RECEIVE / SYNC buttons
        try:
            import iot_bus
            import dwin_get_data as g
            k = dw._dw_read(0x5F80, 1)
            if k and k[0]:
                dw._dw_vp(0x5F80, b'\x00\x00')
                code = k[0]
                if code == 0x0701:
                    iot_bus.ui_send_data()
                elif code == 0x0702:
                    iot_bus.ui_receive_data()
                elif code == 0x0703:
                    iot_bus.ui_sync_id()
                g.draw_iot_page(force=True)
            else:
                g.draw_iot_page(force=False)
        except Exception:
            pass
        return
    if _page in (74, 75, 76, 77, 78):
        try:
            import dwin_port_test
            dwin_port_test.poll()
        except Exception:
            pass
        return
    if _page in (PAGE_BT, PAGE_BT_KB) or _bt_back_t0 is not None:
        k = dw._dw_read(KEY_VP, 1)
        if k and k[0]:
            dw._dw_vp(KEY_VP, b'\x00\x00')
            _bt_key(k[0])
        _bt_poll(now)
        return
    if _page != PAGE_WIFI and _page not in PAGE_KB:
        return
    k = dw._dw_read(KEY_VP, 1)
    if k and k[0]:
        dw._dw_vp(KEY_VP, b'\x00\x00')
        _key(k[0])
    if _connect_t0 is not None:
        _check_connect()
    if _done_t0 is not None and time.ticks_diff(now, _done_t0) > 2000:
        _done_t0 = None
        dw.dwin_page(PAGE_WIFI)
        _page = PAGE_WIFI
        try:
            import dwin_get_data
            dwin_get_data._draw_wifi_dots(force=True)
        except Exception:
            pass
