################################################################################
# main.py — CURIO_MAKER | MicroPython v1.27.0 | STM32H723ZGT6
#
# Commands via USB or UART6 at 921600 baud:
#   UPLOAD   erase user.py
#   @@START  begin code stream
#   @@END    end stream, save user.py
#   PLAY     run user.py
#   STOP     interrupt running code
################################################################################

import os
import sys
import time
import gc
import asyncio
import micropython
from pyb import USB_VCP
from machine import UART, Timer

# ── System status ─────────────────────────────────────────────────────────────
try:
    import system_status
except ImportError:
    with open("system_status.py", "w") as f:
        f.write("running = True\n")
    import system_status

# ── Host channels (optional — board still boots without them) ─────────────────
try:
    import iot_bus
except ImportError:
    iot_bus = None

try:
    import live_bus
except ImportError:
    live_bus = None

# ── Hardware ──────────────────────────────────────────────────────────────────
usb  = USB_VCP()
uart = UART(6, baudrate=921600, timeout=0, rxbuf=16384)   # ← ESP32-S3 link (J4/J5)

# lib.py needs this UART to reach the ESP32 gateway, but must not import main.
if iot_bus:
    iot_bus.set_uart(uart)

BUFFER    = ""
RECEIVING = False
FILENAME  = "user.py"


# ── Helpers ───────────────────────────────────────────────────────────────────

def hard_stop(_):
    raise KeyboardInterrupt


def erase_user_code():
    try:
        if FILENAME in os.listdir():
            os.remove(FILENAME)
            print(">> user.py erased.")
        else:
            print(">> Storage clean.")
    except Exception as e:
        print(f"Erase error: {e}")


def save_user_code(content):
    header = "import system_status\nfrom lib import *\nimport asyncio\n\n"
    try:
        with open(FILENAME, "w") as f:
            f.write(header + content)
        print(f">> {FILENAME} saved.")
    except Exception as e:
        print(f"Save error: {e}")
    gc.collect()


# ── Background RX listener / line dispatcher ──────────────────────────────────
#
#   STOP    -> interrupt the running program
#   IOTR:   -> iot_bus.feed()    host reply to an IoT RPC
#   LIVE:   -> live_bus.apply()  live field edit, applied without re-upload
#   else    -> BUFFER            upload protocol, byte-stream untouched
#
# Anything that is not a recognised control line must reach BUFFER exactly as
# it arrived — that stream carries the user's Python source between @@START
# and @@END. See IOT_EXTENSION_PLAN.md §5.2.

_RX = ""          # holds a trailing fragment that might still become a control line

_CTRL = ("IOTR:", "LIVE:", "NET:")


def _maybe_control(frag):
    """True if `frag` is a control line, or could still grow into one."""
    for p in _CTRL:
        if frag.startswith(p) or p.startswith(frag):
            return True
    return False


def _has_control(s):
    for p in _CTRL:
        if p in s:
            return True
    return False


def _route(msg):
    global BUFFER, _RX

    _RX += msg

    # ── Fast path ────────────────────────────────────────────────────────────
    # No control marker anywhere. Release everything byte-identically, except
    # a trailing fragment that could still GROW into a control line — a chunk
    # boundary can land after just the "I" of "IOTR:".
    if not _has_control(_RX):
        cut = _RX.rfind("\n") + 1
        frag = _RX[cut:]
        if not (frag and _maybe_control(frag)):
            BUFFER += _RX
            _RX = ""
        else:
            BUFFER += _RX[:cut]
            _RX = frag
        return

    # ── Control path ─────────────────────────────────────────────────────────
    # Consume whole lines; each passthrough line keeps its own newline so the
    # upload byte-stream is reproduced exactly.
    out = []
    while True:
        nl = _RX.find("\n")
        if nl < 0:
            break
        line = _RX[:nl]
        _RX = _RX[nl + 1:]
        s = line.strip()
        if s.startswith("IOTR:"):
            if iot_bus: iot_bus.feed(s)
        elif s.startswith("LIVE:"):
            if live_bus: live_bus.apply(s)
        elif s.startswith("NET:"):
            # ESP32 announcing whether its Wi-Fi can serve IoT requests.
            if iot_bus: iot_bus.set_net(s[4:].strip() == "up")
        else:
            out.append(line + "\n")

    # Trailing fragment with no newline yet: hold it only while it might still
    # be a control line, otherwise release it — "@@END" arrives with no
    # trailing newline and holding it would stall every upload.
    if _RX and not _maybe_control(_RX):
        out.append(_RX)
        _RX = ""

    if out:
        BUFFER += "".join(out)


def check_for_stop(timer):
    data = b""
    if usb.any():  data += usb.read()
    if uart.any(): data += uart.read()
    if not data: return
    try:
        msg = data.decode("utf-8", "ignore")
        if "STOP" in msg:
            system_status.running = False
            micropython.schedule(hard_stop, 0)
            return
        _route(msg)
    except Exception:
        pass


stop_checker = Timer(-1)
stop_checker.init(period=10, mode=Timer.PERIODIC, callback=check_for_stop)


# ── Library update ────────────────────────────────────────────────────────────
#
#   host: LIBVER?                              -> board answers LIBVER:1.4.0
#   host: @@FILE:lib.mpy:<sha256>\n<base64>@@FILEEND
#
# Base64 because this link is a text protocol — check_for_stop() decodes it as
# UTF-8, which would mangle raw bytes. ~33% overhead on a 6.6 KB file is not
# worth inventing a binary path through the one function that must never break.
#
# The write is deliberately paranoid. A half-written lib.mpy is a board that no
# longer boots its library, and a student cannot rescue that. So: write to a
# temp name, verify the hash, and only then swap — keeping one generation of
# rollback.

import binascii
import hashlib

UPDATABLE = ("lib.mpy",)          # NOT main.py: it is the code doing the update


def lib_version():
    try:
        import lib
        return getattr(lib, "VERSION", "?")
    except Exception:
        return "?"


def _sha256_hex(data):
    try:
        return binascii.hexlify(hashlib.sha256(data).digest()).decode()
    except Exception:
        return ""


def save_library(name, b64_body, want_sha):
    name = name.strip()
    if name not in UPDATABLE:
        print("FILE:ERR:not updatable: " + name)
        return

    try:
        raw = binascii.a2b_base64("".join(b64_body.split()))
    except Exception as e:
        print("FILE:ERR:bad base64: %s" % e)
        return

    got_sha = _sha256_hex(raw)
    if want_sha and got_sha and got_sha != want_sha.strip().lower():
        print("FILE:ERR:checksum mismatch")
        return

    tmp = name + ".new"
    try:
        with open(tmp, "wb") as f:
            f.write(raw)
    except Exception as e:
        print("FILE:ERR:write failed: %s" % e)
        return

    # Re-read what actually landed. Writing and verifying separately is the
    # whole point — flash can fail after a successful write() call.
    try:
        with open(tmp, "rb") as f:
            back = f.read()
        if _sha256_hex(back) != got_sha:
            print("FILE:ERR:verify failed after write")
            try: os.remove(tmp)
            except Exception: pass
            return
    except Exception as e:
        print("FILE:ERR:verify failed: %s" % e)
        return

    try:
        if name in os.listdir():
            try: os.remove(name + ".bak")
            except Exception: pass
            os.rename(name, name + ".bak")
        os.rename(tmp, name)
    except Exception as e:
        print("FILE:ERR:swap failed: %s" % e)
        return

    print("FILE:OK:%s %d bytes" % (name, len(raw)))
    print(">> Reset the board to load the new library.")


# ── Communication protocol ────────────────────────────────────────────────────

def process_comms():
    global BUFFER, RECEIVING

    # Version query — how the app decides whether an update is needed.
    if "LIBVER?" in BUFFER:
        BUFFER = BUFFER.replace("LIBVER?", "")
        print("LIBVER:" + lib_version())

    # Library transfer. Checked BEFORE @@START so the "@@" prefix cannot be
    # mistaken for the start of a user-code upload.
    if "@@FILE:" in BUFFER and "@@FILEEND" in BUFFER:
        head, rest = BUFFER.split("@@FILE:", 1)
        payload, tail = rest.split("@@FILEEND", 1)
        BUFFER = head + tail
        try:
            header, body = payload.split("\n", 1)
            parts = header.split(":")
            save_library(parts[0], body, parts[1] if len(parts) > 1 else "")
        except Exception as e:
            print("FILE:ERR:malformed header: %s" % e)

    if "UPLOAD" in BUFFER:
        BUFFER = BUFFER.replace("UPLOAD", "")
        erase_user_code()
        print(">> Waiting for @@START...")
        return "READY_FOR_DATA"

    if "@@START" in BUFFER:
        RECEIVING = True
        parts  = BUFFER.split("@@START", 1)
        BUFFER = parts[1] if len(parts) > 1 else ""

    if RECEIVING and "@@END" in BUFFER:
        code_body, remaining = BUFFER.split("@@END", 1)
        save_user_code(code_body)
        BUFFER    = remaining
        RECEIVING = False
        print(">> Upload complete.")

    if "PLAY" in BUFFER:
        BUFFER = BUFFER.replace("PLAY", "")
        return "START_EXECUTION"

    return None


# ── Execution engine ──────────────────────────────────────────────────────────

def run_engine():
    print(">> Executing...")
    system_status.running = True

    # Drop replies left over from a previous run — their ids are stale.
    if iot_bus:
        iot_bus.clear()

    try:
        if "user" in sys.modules:
            del sys.modules["user"]

        import user

        # Prefer main() — supports gather() pattern
        # Fall back to start() for simple projects
        if hasattr(user, "main"):
            fn = user.main
        elif hasattr(user, "start"):
            fn = user.start
        else:
            print("Error: user.py needs main() or start().")
            return

        result = fn()

        # Detect async def — returns coroutine object
        if hasattr(result, "send") and hasattr(result, "throw"):
            asyncio.run(result)     # run on uasyncio event loop
        # sync def already ran above

    except KeyboardInterrupt:
        print("\n[!] Stopped.")
    except Exception as e:
        sys.print_exception(e)
    finally:
        system_status.running = False
        gc.collect()
        print(">> Ready.")


# ── Main loop ─────────────────────────────────────────────────────────────────

print("SYSTEM READY  |  UPLOAD  PLAY  STOP")

while True:
    cmd = process_comms()
    if cmd == "START_EXECUTION":
        if FILENAME in os.listdir():
            run_engine()
        else:
            print("Error: no user.py. Send UPLOAD first.")
    time.sleep_ms(50)
