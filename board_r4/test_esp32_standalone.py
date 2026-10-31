"""Read-only standalone ESP32-S3 Wi-Fi/BLE diagnostic on CM MOTHERBOARD R4.

Run from the STM32 MicroPython REPL after stopping main.py (Ctrl-C):
    import test_esp32_standalone
    test_esp32_standalone.run()

Uses USART6 at 921600 baud, with the R4's TX/RX swap. It does not change
network credentials, pair BLE devices, write user.py, or flash either board.
The ESP32 gateway firmware must support NET:, STAT:, and local IOT: RPCs.
"""

import json
import sys
import time
import machine
from machine import UART

_USART6 = 0x40011400
_BAUD = 921600


def _open_uart():
    u = UART(6, baudrate=_BAUD, timeout=0, rxbuf=4096)
    cr1 = machine.mem32[_USART6]
    machine.mem32[_USART6] = cr1 & ~1
    machine.mem32[_USART6 + 4] |= 1 << 15  # CR2.SWAP: R4's straight wires
    machine.mem32[_USART6] = cr1
    return u


def _lines(u, timeout_ms, wanted_id=None):
    end = time.ticks_add(time.ticks_ms(), timeout_ms)
    partial = b""
    seen = []
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if u.any():
            partial += u.read()
            while b"\n" in partial:
                raw, partial = partial.split(b"\n", 1)
                line = raw.strip().decode("utf-8", "replace")
                if not line:
                    continue
                if line.startswith(("NET:", "STAT:", "IOTR:")):
                    print("RX", line[:240])
                    seen.append(line)
                    if wanted_id is not None and line.startswith("IOTR:"):
                        try:
                            reply = json.loads(line[5:])
                            if reply.get("id") == wanted_id:
                                return seen, reply
                        except ValueError:
                            pass
            if len(partial) > 4096:
                partial = b""
        time.sleep_ms(20)
    return seen, None


def _query(u, request_id, op, timeout_ms):
    request = "IOT:" + json.dumps({"id": request_id, "op": op}) + "\n"
    print("TX", op)
    u.write(request)
    _, reply = _lines(u, timeout_ms, request_id)
    if reply is None:
        print("NO REPLY", op)
    else:
        print("RESULT", op, "code", reply.get("code"), "error", reply.get("err"))
    return reply


def run():
    # main.py owns UART6 via its receive timer; leave no competing reader.
    # Note: in MicroPython, "__main__" is not in sys.modules until imported.
    try:
        import __main__
        timer = getattr(__main__, "stop_checker", None)
        if timer is not None:
            timer.deinit()
    except Exception:
        pass
    u = _open_uart()
    print("STM32 UART6 -> ESP32: 921600 baud, CR2.SWAP enabled")
    print("Listening 6 s for the ESP32's periodic NET/STAT broadcast...")
    seen, _ = _lines(u, 6000)
    if not seen:
        print("NO ESP32 TRAFFIC. Check power, ground, PC6/PC7 <-> IO17/IO18, and gateway firmware.")
    for request_id, op, timeout_ms in ((100, "wifi_check", 3000),
                                        (101, "status", 3000),
                                        (102, "wifi_status", 3000),
                                        (103, "ble_status", 3000),
                                        (104, "wifi_scan", 10000)):
        rep = _query(u, request_id, op, timeout_ms)
        if rep and str(rep.get("err", "")).startswith("bad-op:"):
            print("NOTE: ESP32 replied '%s' -> ESP32 is alive on UART6 but running old firmware without %s." % (
                rep.get("err"), op))
    print("Diagnostic finished; reset the STM32 to restart main.py.")


if __name__ == "__main__":
    run()
