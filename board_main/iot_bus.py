################################################################################
# iot_bus.py — mailbox for host→board IoT RPC replies & live ESP32 status.
#
# main.py's RX timer calls feed() with each complete "IOTR:{...}" line and
# set_status() with each "STAT:{...}" line from the ESP32-S3 gateway.
# lib.py / dwin_get_data.py can query live Wi-Fi & Bluetooth status or invoke
# wifi_scan(), wifi_connect(), wifi_disconnect(), wifi_status(), ble_status().
################################################################################

import json
import sys
import time

_PREFIX_LEN = 5          # len("IOTR:")
_MAX_PENDING = 8         # a healthy board never has more than 1 in flight

_inbox = {}
_next_id = 100

# ── Outbound channel selection ───────────────────────────────────────────────
# Two different hosts can answer an IoT request:
#   • the browser/phone over USB or BLE
#   • the ESP32-S3 over UART6, using its own Wi-Fi (no computer attached)
#
# The ESP32 announces its state with "NET:up" / "NET:down" and "STAT:{...}".

_uart = None
_net_up = False
_esp_seen = False        # any NET: or STAT: line proves an ESP32 is attached
_last_seen_ms = 0

_status = {
    "wifi_up": False,
    "wifi_enabled": True,
    "ssid": "",
    "ip": "",
    "rssi": 0,
    "scan_count": -1,
    "top_ssid": "",
    "scan": [],
    "ble_up": False,
    "ble_connected": False,
    "ble_adv": False,
    "ble_name": "ESP32-BLE-CURIO_V2",
}


def set_uart(u):
    """Called once by main.py — lib.py has no access to the UART otherwise."""
    global _uart
    _uart = u


def set_net(up):
    """Called by main.py when a NET: line arrives from the ESP32."""
    global _net_up, _esp_seen, _last_seen_ms
    if not _esp_seen or up != _net_up:
        try:
            print("iot_bus: ESP32 seen, net " + ("up" if up else "down"))
        except Exception:
            pass
    _net_up = bool(up)
    _esp_seen = True
    _last_seen_ms = time.ticks_ms()
    _status["wifi_up"] = _net_up
    if not _status["ble_up"]:
        _status["ble_up"] = True


def set_status(raw_json):
    """Called by main.py when a STAT:{...} line arrives from the ESP32."""
    global _esp_seen, _net_up, _last_seen_ms
    try:
        obj = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        if not isinstance(obj, dict):
            return
        _esp_seen = True
        _last_seen_ms = time.ticks_ms()
        if "wifi_up" in obj:
            _net_up = bool(obj["wifi_up"])
            _status["wifi_up"] = _net_up
        for k in ("ssid", "ip", "rssi", "scan_count", "top_ssid", "wifi_enabled",
                  "ble_up", "ble_connected", "ble_adv", "ble_visible", "ble_name"):
            if k in obj:
                _status[k] = obj[k]
        if not _status["wifi_enabled"]:
            _status["scan"] = []
    except Exception:
        pass


def status():
    """Return a snapshot of the latest ESP32 Wi-Fi and Bluetooth status."""
    d = dict(_status)
    d["esp_present"] = esp_present()
    return d


def net_up():
    return _net_up and _uart is not None


def esp_present():
    return _esp_seen and _uart is not None


def _uart_write(line):
    try:
        _uart.write(line)
    except Exception:
        pass


def send(line, esp_only=False):
    """Put one control line on whichever channel can answer it."""
    if _uart is not None and (_net_up or esp_only):
        _uart_write(line)
        return

    try:
        sys.stdout.write(line)
    except Exception:
        pass
    if _uart is not None:
        _uart_write(line)


def feed(line):
    """Parse one 'IOTR:{...}' line into the inbox. Never raises — this runs
    from the RX timer callback and must not disturb the running program."""
    global _esp_seen, _last_seen_ms
    try:
        obj = json.loads(line[_PREFIX_LEN:])
        rid = obj.get("id")
        if rid is None:
            return
        _esp_seen = True
        _last_seen_ms = time.ticks_ms()
        if rid in _ui_pending:
            _handle_ui_reply(rid, obj)
            return
        if len(_inbox) >= _MAX_PENDING:
            _inbox.clear()
        _inbox[rid] = obj
    except Exception:
        try:
            print("iot_bus: bad reply, %d bytes" % len(line))
        except Exception:
            pass


def take(rid):
    """Pop the reply for `rid`, or None if it has not arrived yet."""
    return _inbox.pop(rid, None)


def clear():
    """Drop any stale replies — called when a new program starts."""
    _inbox.clear()


def call(op, timeout_ms=10000, esp_only=True, **params):
    """Send an IOT:{...} RPC request and wait up to timeout_ms for IOTR:{...}."""
    global _next_id
    _next_id += 1
    rid = _next_id
    req = {"id": rid, "op": op}
    req.update(params)
    line = "IOT:" + json.dumps(req) + "\n"
    send(line, esp_only=esp_only)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        rep = take(rid)
        if rep is not None:
            return rep
        time.sleep_ms(20)
    return {"id": rid, "code": 0, "body": "", "err": "timeout"}


async def async_call(op, timeout_ms=10000, esp_only=True, **params):
    """Async version of call()."""
    import uasyncio as asyncio
    global _next_id
    _next_id += 1
    rid = _next_id
    req = {"id": rid, "op": op}
    req.update(params)
    line = "IOT:" + json.dumps(req) + "\n"
    send(line, esp_only=esp_only)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        rep = take(rid)
        if rep is not None:
            return rep
        await asyncio.sleep_ms(20)
    return {"id": rid, "code": 0, "body": "", "err": "timeout"}


def wifi_scan(timeout_ms=10000):
    """Scan available 2.4 GHz Wi-Fi networks via ESP32 gateway.
    Returns list of dicts: [{"ssid": "...", "rssi": -50, "open": False}, ...]
    """
    rep = call("wifi_scan", timeout_ms=timeout_ms, esp_only=True)
    if rep.get("code") == 200 and rep.get("body"):
        try:
            nets = json.loads(rep["body"])
            if isinstance(nets, list):
                _status["scan"] = nets
                _status["scan_count"] = len(nets)
                _status["top_ssid"] = nets[0].get("ssid", "") if nets else ""
                return nets
        except Exception:
            pass
    return []


def wifi_connect(ssid, password="", force=False, timeout_ms=18000):
    """Connect ESP32 gateway to Wi-Fi network `ssid` with `password`.
    Returns True if connected, False otherwise.
    """
    rep = call("wifi_connect", timeout_ms=timeout_ms, esp_only=True,
               ssid=str(ssid), **{"pass": str(password), "force": bool(force)})
    ok = (rep.get("code") == 200)
    if rep.get("body"):
        try:
            info = json.loads(rep["body"])
            _status["wifi_up"] = bool(info.get("connected", ok))
            _status["ssid"] = info.get("ssid", "")
            _status["ip"] = info.get("ip", "")
            _status["rssi"] = info.get("rssi", 0)
        except Exception:
            pass
    return ok


def wifi_disconnect(forget=False, timeout_ms=5000):
    """Disconnect ESP32 gateway from Wi-Fi."""
    rep = call("wifi_disconnect", timeout_ms=timeout_ms, esp_only=True, forget=bool(forget))
    _status["wifi_up"] = False
    _status["ssid"] = ""
    _status["ip"] = ""
    _status["rssi"] = 0
    return rep.get("code") == 200


def wifi_status(query=False, timeout_ms=4000):
    """Return Wi-Fi status dict. If query=True, actively polls the ESP32."""
    if query:
        rep = call("wifi_status", timeout_ms=timeout_ms, esp_only=True)
        if rep.get("code") == 200 and rep.get("body"):
            try:
                info = json.loads(rep["body"])
                _status["wifi_up"] = bool(info.get("connected"))
                if "enabled" in info:
                    _status["wifi_enabled"] = bool(info["enabled"])
                _status["ssid"] = info.get("ssid", "")
                _status["ip"] = info.get("ip", "")
                _status["rssi"] = info.get("rssi", 0)
                return info
            except Exception:
                pass
    return {
        "gateway_present": esp_present(),
        "connected": _status["wifi_up"],
        "enabled": _status["wifi_enabled"],
        "ssid": _status["ssid"],
        "ip": _status["ip"],
        "rssi": _status["rssi"],
        "scan_count": _status["scan_count"],
        "top_ssid": _status["top_ssid"],
        "scan": _status["scan"],
    }


def ble_status(query=False, timeout_ms=4000):
    """Return Bluetooth LE status dict. If query=True, actively polls the ESP32."""
    if query:
        rep = call("ble_status", timeout_ms=timeout_ms, esp_only=True)
        if rep.get("code") == 200 and rep.get("body"):
            try:
                info = json.loads(rep["body"])
                _status["ble_up"] = bool(info.get("available", True))
                _status["ble_connected"] = bool(info.get("connected", False))
                _status["ble_adv"] = bool(info.get("advertising", True))
                _status["ble_name"] = info.get("name", _status["ble_name"])
                return info
            except Exception:
                pass
    return {
        "gateway_present": esp_present(),
        "available": _status["ble_up"] if esp_present() else False,
        "connected": _status["ble_connected"] if esp_present() else False,
        "advertising": _status["ble_adv"] if esp_present() else False,
        "name": _status["ble_name"],
    }


# ── IoT Cloud & Kit-to-Kit Communication State (DWIN Page 96) ────────────────
_STATE_FILE = "iot_state.json"
_ui_pending = {}
_state_loaded = False
_iot_state = {
    "kit_id": "",
    "cloud_ok": False,
    "channel_id": "",
    "tx_data": "READY TO SEND",
    "tx_status": "TAP SEND DATA",
    "rx_data": "WAITING...",
    "rx_status": "TAP RECEIVE",
    "seq": 0,
    "rev": 1,
}


def device_id():
    """Return this board's hardware ID (from the STM32's 96-bit factory UID)."""
    try:
        import machine, ubinascii
        return "curio-" + ubinascii.hexlify(machine.unique_id()).decode()
    except Exception:
        return "curio-0000"


def kit_id():
    """Return the deterministic short Kit Name / ID (e.g. 'CURIO-XXXX')."""
    hw = device_id()
    h = 0
    for ch in hw:
        h = ((h * 31) + ord(ch)) & 0xFFFF
    code = "CURIO-%04X" % h
    bname = _status.get("ble_name", "")
    prefix = "ESP32-BLE-CURIO_V2-"
    if bname.startswith(prefix) and len(bname) > len(prefix):
        tag = bname[len(prefix):][:8].upper()
        return "%s (%s)" % (code, tag)
    return code


def _load_iot_state():
    global _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    _iot_state["kit_id"] = kit_id()
    try:
        with open(_STATE_FILE, "r") as f:
            saved = json.loads(f.read())
        if isinstance(saved, dict):
            for k in ("cloud_ok", "channel_id", "tx_data", "tx_status",
                      "rx_data", "rx_status", "seq"):
                if k in saved:
                    _iot_state[k] = saved[k]
    except Exception:
        pass


def _save_iot_state():
    _load_iot_state()
    _iot_state["kit_id"] = kit_id()
    _iot_state["rev"] = (_iot_state.get("rev", 0) + 1) & 0x7FFFFFFF
    try:
        with open(_STATE_FILE, "w") as f:
            f.write(json.dumps({
                "kit_id": _iot_state["kit_id"],
                "cloud_ok": _iot_state["cloud_ok"],
                "channel_id": _iot_state["channel_id"],
                "tx_data": _iot_state["tx_data"],
                "tx_status": _iot_state["tx_status"],
                "rx_data": _iot_state["rx_data"],
                "rx_status": _iot_state["rx_status"],
                "seq": _iot_state["seq"],
            }))
    except Exception:
        pass


def _stamp():
    s = (time.ticks_ms() // 1000) % 3600
    return "%02d:%02d" % (s // 60, s % 60)


def record_cloud(ok, channel_id=None, note=""):
    _load_iot_state()
    _iot_state["cloud_ok"] = bool(ok)
    if channel_id:
        _iot_state["channel_id"] = str(channel_id)
    _save_iot_state()


def record_tx(data_str, ok=True, note=""):
    _load_iot_state()
    _iot_state["tx_data"] = str(data_str)[:18].upper()
    if note:
        _iot_state["tx_status"] = str(note)[:18].upper()
    else:
        _iot_state["tx_status"] = ("SENT OK " if ok else "SAVED ") + _stamp()
    if ok and _status.get("wifi_up"):
        _iot_state["cloud_ok"] = True
    _save_iot_state()


def record_rx(data_str, ok=True, note=""):
    _load_iot_state()
    _iot_state["rx_data"] = str(data_str)[:18].upper()
    if note:
        _iot_state["rx_status"] = str(note)[:18].upper()
    else:
        _iot_state["rx_status"] = ("RX OK " if ok else "LOCAL ") + _stamp()
    if ok and _status.get("wifi_up"):
        _iot_state["cloud_ok"] = True
    _save_iot_state()


def get_iot_state():
    _load_iot_state()
    st = status()
    w_up = bool(st.get("wifi_up"))
    esp_ok = bool(st.get("esp_present"))
    if w_up:
        if _iot_state.get("cloud_ok"):
            ch = _iot_state.get("channel_id", "")
            cloud_str = ("CONNECTED #" + ch) if ch else "CONNECTED"
        else:
            cloud_str = "READY (ONLINE)"
    elif esp_ok:
        cloud_str = "OFFLINE (NO WIFI)"
    else:
        cloud_str = "OFFLINE"
    return {
        "esp_present": esp_ok,
        "wifi_up": w_up,
        "ssid": st.get("ssid", ""),
        "kit_id": kit_id(),
        "cloud_ok": bool(_iot_state.get("cloud_ok")) and w_up,
        "cloud_str": cloud_str,
        "channel_id": _iot_state.get("channel_id", ""),
        "tx_data": _iot_state.get("tx_data", "READY TO SEND"),
        "tx_status": _iot_state.get("tx_status", "TAP SEND DATA"),
        "rx_data": _iot_state.get("rx_data", "WAITING..."),
        "rx_status": _iot_state.get("rx_status", "TAP RECEIVE"),
        "rev": _iot_state.get("rev", 1),
    }


def _send_ui_op(tag, op, meta="", **params):
    global _next_id
    _next_id += 1
    rid = _next_id
    if len(_ui_pending) >= 6:
        _ui_pending.clear()
    _ui_pending[rid] = (tag, meta)
    req = {"id": rid, "op": op}
    req.update(params)
    send("IOT:" + json.dumps(req) + "\n", esp_only=False)
    return rid


def _handle_ui_reply(rid, obj):
    tag, meta = _ui_pending.pop(rid, (None, ""))
    code = obj.get("code", 0)
    body = str(obj.get("body", "")).strip()
    if tag == "tx":
        ok = (code == 200 and body not in ("", "0"))
        if ok:
            record_tx(meta, ok=True, note="CLOUD OK " + _stamp())
        else:
            record_tx(meta, ok=False, note="SAVED " + _stamp())
    elif tag == "rx":
        if code == 200 and body:
            record_rx(body, ok=True, note="CLOUD RX " + _stamp())
        else:
            _load_iot_state()
            last_tx = _iot_state.get("tx_data", "EMPTY")
            record_rx(last_tx, ok=False, note="LOCAL BUF " + _stamp())
    elif tag == "sync":
        if code == 200 and body:
            try:
                info = json.loads(body)
                ch = str(info.get("channel_id", ""))
                record_cloud(True, channel_id=ch)
                record_rx(info.get("name", kit_id()), ok=True, note="SYNCED #" + ch)
                return
            except Exception:
                pass
        record_cloud(bool(_status.get("wifi_up")))


def ui_send_data(data_str=None):
    """Non-blocking Send Data action triggered from DWIN Page 96 or user script."""
    _load_iot_state()
    if not data_str:
        try:
            import lib
            ts = getattr(lib, "_telemetry_sensors", None)
            if isinstance(ts, list) and ts:
                for entry in ts:
                    if len(entry) >= 3 and entry[2]:
                        lbl = str(entry[1]).split(" ")[0][:6].upper()
                        val = str(entry[2]).split(" ")[0][:6].upper()
                        data_str = "%s:%s" % (lbl, val)
                        break
            elif isinstance(ts, dict) and ts:
                k = sorted(ts.keys())[0]
                data_str = "%s:%s" % (str(k)[:6].upper(), str(ts[k])[:6])
        except Exception:
            pass
    if not data_str:
        seq = int(_iot_state.get("seq", 0)) + 1
        _iot_state["seq"] = seq
        data_str = "KIT MSG #%d" % seq
    val_str = str(data_str)[:18].upper()
    if _status.get("wifi_up"):
        record_tx(val_str, ok=True, note="SENDING...")
        _send_ui_op("tx", "ts_write", meta=val_str, fields={"1": val_str})
    else:
        record_tx(val_str, ok=False, note="SAVED " + _stamp())
        _send_ui_op("tx", "ts_write", meta=val_str, fields={"1": val_str})


def ui_receive_data():
    """Non-blocking Receive Data action triggered from DWIN Page 96."""
    _load_iot_state()
    if _status.get("wifi_up") or esp_present():
        _iot_state["rx_status"] = "CHECKING..."
        _save_iot_state()
        _send_ui_op("rx", "ts_read", field=1)
    else:
        last_tx = _iot_state.get("tx_data", "READY")
        record_rx(last_tx, ok=False, note="LOCAL LOOP " + _stamp())


def ui_sync_id():
    """Non-blocking Sync / Kit ID provisioning action triggered from DWIN Page 96."""
    _load_iot_state()
    if _uart is not None:
        _uart_write("STATUS?\n")
    _iot_state["rx_status"] = "SYNCING ID..."
    _save_iot_state()
    _send_ui_op("sync", "ts_auto", hw=device_id())

