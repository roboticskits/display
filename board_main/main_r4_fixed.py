################################################################################
# main.py — CURIO_MAKER | MicroPython v1.27.0 | STM32H723ZGT6
#
# Commands via USB or UART6 at 921600 baud:
#   UPLOAD   erase user.py
#   @@START  begin code stream
#   @@END    end stream, save user.py
#   PLAY     run user.py
#   STOP     interrupt running code
#
# Fixes compared with the previous version (2026-10-16):
#   1. USB receive flow control: the PC now waits when the board's buffer is
#      full. Before, big uploads (for example programs with images) lost bytes.
#   2. Words inside an uploaded program are text, not commands: "DISPLAY" no
#      longer runs the old program mid-upload (PLAY), "UPLOAD" no longer erases
#      user.py, "STOP" no longer cuts out part of the program.
#   3. STOP works again. On MicroPython 1.28 the KeyboardInterrupt raised in a
#      scheduled callback was only printed, so running programs never
#      stopped. Now a watcher task in the program's event loop stops it; a
#      program that never yields is stopped by a hard reset after 3 s.
#      A STOP with nothing running is ignored instead of killing main.py.
#   4. Only the main loop changes BUFFER. The RX timer queues text instead of
#      editing BUFFER while the main loop is cutting it apart (lost chunks).
#   5. RX errors are printed instead of silently dropping data.
################################################################################

import os
import sys
import time
import gc
import asyncio
import micropython
from pyb import USB_VCP
import machine
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
# RX flow control: when the receive buffer is full the PC waits, instead of the
# board silently dropping bytes.
usb.init(flow=USB_VCP.RTS)
uart = UART(6, baudrate=921600, timeout=0, rxbuf=16384)   # ← ESP32-S3 link (PC6/PC7 <-> IO17/IO18)
# On CM MOTHERBOARD R4, PC6 (USART6_TX) goes to IO17 (ESP32 TX1) and PC7 (USART6_RX)
# goes to IO18 (ESP32 RX1), so swap USART6 TX/RX in hardware (CR2.SWAP):
_USART6_BASE = 0x40011400
_cr1 = machine.mem32[_USART6_BASE]
machine.mem32[_USART6_BASE] = _cr1 & ~1
machine.mem32[_USART6_BASE + 4] |= 1 << 15
machine.mem32[_USART6_BASE] = _cr1

# lib.py needs this UART to reach the ESP32 gateway, but must not import main.
if iot_bus:
    iot_bus.set_uart(uart)

# Preload lib bytecode at startup so RAM is clean and sys.modules always has lib
try:
    import lib
except Exception as e:
    print("lib preload:", e)

BUFFER    = ""          # only the main loop touches this
RECEIVING = False
FILENAME  = "user.py"

_INBOX     = []         # text from the RX timer, waiting for the main loop
_STOP_REQ  = False      # set by the RX timer, consumed by the STOP watcher task
_IN_RUN    = False      # True only while run_engine() runs user code
_UPLOADING = False      # RX timer's view: between @@START and @@END
_TAIL      = {}         # end of the previous RX chunk per source, to see split markers


# ── Helpers ───────────────────────────────────────────────────────────────────

_STOP_AT = 0           # ticks_ms when STOP arrived, for the reset fallback
STOP_RESET_MS = 3000   # program ignores STOP this long -> hard reset


# Why not raise KeyboardInterrupt from the RX timer (the old hard_stop)?
# On MicroPython 1.28 an exception raised in a micropython.schedule() callback
# is printed and dropped - it never reaches the running program. So STOP is a
# flag, and a watcher task inside the program's own event loop raises it.
def _run_guarded(coro):
    finished = [False]

    def program():
        try:
            while True:
                try:
                    v = next(coro)
                except StopIteration:
                    return
                yield v
        finally:
            finished[0] = True

    async def watcher():
        global _STOP_REQ
        while not finished[0]:
            if _STOP_REQ:
                _STOP_REQ = False
                raise KeyboardInterrupt     # inside the loop: reaches run_engine
            try:
                import dwin_screen as dw
                k = dw._dw_read(0x5F60, 1)
                if k and k[0] == 0x0502:    # STOP pressed on DWIN display
                    dw._dw_vp(0x5F60, b'\x00\x00')
                    print("\n[DWIN] STOP button pressed.")
                    _STOP_REQ = False
                    raise KeyboardInterrupt
            except KeyboardInterrupt:
                raise
            except Exception:
                pass
            await asyncio.sleep_ms(20)

    try:
        loop = asyncio.new_event_loop()
        loop.create_task(program())
        loop.create_task(watcher())
        run = loop.run_forever
    except AttributeError:                  # a different asyncio: plain run
        asyncio.run(coro)
        return
    run()


def erase_user_code():
    try:
        if FILENAME in os.listdir():
            os.remove(FILENAME)
            print(">> user.py erased.")
        else:
            print(">> Storage clean.")
    except Exception as e:
        print(f"Erase error: {e}")


# ── Upload to user.py ─────────────────────────────────────────────────────────
#
# The program is never held in memory as a whole: incoming text goes into one
# fixed 16 KB buffer (allocated here, at start-up, while the heap is still in
# one piece). A program up to 16 KB is written to user.py in one go at @@END;
# a bigger one is written 16 KB at a time as it arrives, so even a 68 KB upload
# needs no large free block. Few, large writes matter: every file operation
# costs a second or more on this board's flash. (No temporary file + rename:
# that added ~5 s to every upload. An interrupted big upload leaves a partial
# user.py - just upload again.)

USER_HEADER = "import system_status\nfrom lib import *\nimport asyncio\n\n"
_UPL_BUF = bytearray(16384)
_UPL_N = 0          # bytes waiting in _UPL_BUF
_UPL_F = None       # user.py.new while an upload is in progress
_UPL_TAIL = ""      # last characters held back: "@@END" may be split across pieces
_END = "@@END"


def _upl_abort():
    global _UPL_F, _UPL_N, _UPL_TAIL
    if _UPL_F:
        try:
            _UPL_F.close()
        except OSError:
            pass
    _UPL_F, _UPL_N, _UPL_TAIL = None, 0, ""


def _upl_start():
    _upl_abort()
    gc.collect()
    _upl_add(USER_HEADER)


def _upl_add(text):
    """Collect upload text; a program bigger than the buffer goes to user.py
    16 KB at a time (the file is only opened then, so a normal-size program
    costs one open + one write + close - flash operations are slow here)."""
    global _UPL_N, _UPL_F
    b = text.encode()
    i, n, size = 0, len(b), len(_UPL_BUF)
    while i < n:
        k = min(n - i, size - _UPL_N)
        _UPL_BUF[_UPL_N:_UPL_N + k] = b[i:i + k]
        _UPL_N += k
        i += k
        if _UPL_N == size:
            if _UPL_F is None:
                _UPL_F = open(FILENAME, "wb")
            _UPL_F.write(_UPL_BUF)
            _UPL_N = 0


def _upl_finish():
    global _UPL_F, _UPL_N
    if _UPL_F is None:
        _UPL_F = open(FILENAME, "wb")
    if _UPL_N:
        _UPL_F.write(memoryview(_UPL_BUF)[:_UPL_N])
    _UPL_F.close()
    _UPL_F, _UPL_N = None, 0
    print(f">> {FILENAME} saved.")


def _receive(text):
    """Add upload text. Returns None while the upload continues, or the text
    that followed @@END once the upload is complete (and saved)."""
    global _UPL_TAIL
    probe = _UPL_TAIL + text
    i = probe.find(_END)
    if i < 0:
        keep = len(_END) - 1
        if len(probe) > keep:
            _upl_add(probe[:-keep])
            _UPL_TAIL = probe[-keep:]
        else:
            _UPL_TAIL = probe
        return None
    _upl_add(probe[:i])
    _UPL_TAIL = ""
    try:
        _upl_finish()
    except Exception as e:
        print(f"Save error: {e}")
        _upl_abort()
    gc.collect()
    return probe[i + len(_END):]


# ── Video upload into the DWIN display's flash ("DWV") ────────────────────────
#
# The Blockly page sends a video as an icon library for the display:
#   @@DWV:<first 32 KB block>:<blocks>\n     -> DWV:READY
#   <hex of up to 4096 bytes>\n               -> DWV:NEXT   (staged in display VP memory)
#   @@DWB:<block index>:<crc32 of block>\n    -> DWV:OK <i> (flash written) / DWV:ERR ...
#   @@DWV:END\n                               -> DWV:DONE <blocks written>
# 4 KB per step keeps memory use small: the board never holds a whole block.
# The display's flash write (system variable 0x00AA, see lib.py) takes the
# block from its own VP memory. Lowercase hex never contains a command word.

_DWV = None   # [first block, blocks, blocks written, crc, bytes staged, last activity ms]


def _dwv_start(header):
    global _DWV
    try:
        first, n = [int(x) for x in header.split(":")]
        if first < 0 or n < 1 or first + n > 512:
            raise ValueError("bad block range")
        import dwin_screen as lib, struct
        lib.dwin_page(10)                        # leave pages that show the video library
        for vp, _ in lib._DW_REGIONS:            # page 39 must not draw while its memory holds data
            lib._dw_vp(vp, struct.pack(">HH", 1, 0))
        _DWV = [first, n, 0, 0, 0, time.ticks_ms()]
        print("DWV:READY")
    except Exception as e:
        _DWV = None
        print("DWV:ERR start %s" % e)


def _dwv_line(line):
    """Handle one complete line of a video transfer."""
    global _DWV
    import dwin_screen as lib, binascii
    st = _DWV
    st[5] = time.ticks_ms()
    try:
        if line.startswith("@@DWB:"):
            idx, crc = [int(x) for x in line[6:].split(":")]
            if st[4] and crc == st[3] and 0 <= idx < st[1]:
                for _ in lib._dw_flash_block_steps(st[0] + idx, lib._DW_STAGE_A):
                    pass
                st[2] += 1
                print("DWV:OK %d" % idx)
            else:
                print("DWV:ERR %d crc" % idx)
            st[3] = st[4] = 0
        elif line.startswith("@@DWV:END"):
            print("DWV:DONE %d" % st[2])
            _DWV = None
            gc.collect()
        else:
            data = binascii.unhexlify(line)
            if st[4] + len(data) > 32768:
                raise ValueError("block too big")
            for _ in lib._dw_stage_steps(lib._DW_STAGE_A + st[4] // 2, data):
                pass
            st[3] = binascii.crc32(data, st[3])
            st[4] += len(data)
            print("DWV:NEXT")
    except Exception as e:
        st[3] = st[4] = 0
        print("DWV:ERR data %s" % e)


# ── Background RX listener / line dispatcher ──────────────────────────────────
#
#   STOP    -> interrupt the running program (only outside an upload)
#   IOTR:   -> iot_bus.feed()    host reply to an IoT RPC
#   LIVE:   -> live_bus.apply()  live field edit, applied without re-upload
#   else    -> _INBOX -> BUFFER  upload protocol, byte-stream untouched
#
# Anything that is not a recognised control line must reach BUFFER exactly as
# it arrived — that stream carries the user's Python source between @@START
# and @@END. See IOT_EXTENSION_PLAN.md §5.2.

# Trailing fragment that might still become a control line, kept PER SOURCE:
# USB and the ESP32 (UART6) arrive in the same timer tick, and an ESP32 status
# line ("NET:up", "STAT:{...}", about once a second) glued onto the middle of a
# USB upload chunk used to be taken for program text and corrupted user.py.
_RX = {"usb": "", "esp": ""}

_CTRL = ("IOTR:", "LIVE:", "NET:", "STAT:")


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


def _route(msg, src="usb"):
    rx = _RX[src] + msg

    # ── Fast path ────────────────────────────────────────────────────────────
    # No control marker anywhere. Release everything byte-identically, except
    # a trailing fragment that could still GROW into a control line — a chunk
    # boundary can land after just the "I" of "IOTR:".
    if not _has_control(rx):
        cut = rx.rfind("\n") + 1
        frag = rx[cut:]
        if not (frag and _maybe_control(frag)):
            _INBOX.append(rx)
            rx = ""
        else:
            _INBOX.append(rx[:cut])
            rx = frag
        _RX[src] = rx
        return

    # ── Control path ─────────────────────────────────────────────────────────
    # Consume whole lines; each passthrough line keeps its own newline so the
    # upload byte-stream is reproduced exactly.
    out = []
    while True:
        nl = rx.find("\n")
        if nl < 0:
            break
        line = rx[:nl]
        rx = rx[nl + 1:]
        s = line.strip()
        if s.startswith("IOTR:"):
            if iot_bus: iot_bus.feed(s)
        elif s.startswith("LIVE:"):
            if live_bus: live_bus.apply(s)
        elif s.startswith("NET:"):
            # ESP32 announcing whether its Wi-Fi can serve IoT requests.
            if iot_bus: iot_bus.set_net(s[4:].strip() == "up")
        elif s.startswith("STAT:"):
            # ESP32 announcing full Wi-Fi + Bluetooth status for Settings page.
            if iot_bus and hasattr(iot_bus, "set_status"):
                iot_bus.set_status(s[5:].strip())
        else:
            out.append(line + "\n")

    # Trailing fragment with no newline yet: hold it only while it might still
    # be a control line, otherwise release it — "@@END" arrives with no
    # trailing newline and holding it would stall every upload.
    if rx and not _maybe_control(rx):
        out.append(rx)
        rx = ""
    _RX[src] = rx

    if out:
        _INBOX.append("".join(out))


def check_for_stop(timer):
    global _STOP_REQ, _UPLOADING, _TAIL, _STOP_AT
    # Last resort: a program that never yields (plain def, endless loop with
    # no await) cannot see the STOP flag. Reset the board instead, as the old
    # firmware did for every STOP.
    if _STOP_REQ and _IN_RUN and time.ticks_diff(time.ticks_ms(), _STOP_AT) > STOP_RESET_MS:
        print("\n[!] Program did not stop - resetting the board.")
        machine.reset()
    du = usb.read() if usb.any() else b""
    de = uart.read() if uart.any() else b""
    if du:
        _rx_chunk(du, "usb")
    if de:
        _rx_chunk(de, "esp")


def _rx_chunk(data, src):
    global _STOP_REQ, _UPLOADING, _TAIL, _STOP_AT
    try:
        msg = data.decode("utf-8", "ignore")

        # Track whether we are inside an upload, also when a marker is split
        # across two chunks.
        probe = _TAIL.get(src, "") + msg
        _TAIL[src] = msg[-8:]
        was = _UPLOADING
        s, e = probe.rfind("@@START"), probe.rfind("@@END")
        if s > e:
            _UPLOADING = True
        elif e > s:
            _UPLOADING = False

        # STOP is a command only outside an upload; inside, it is program text.
        # Any chunk that touches an upload marker counts as upload data.
        in_upload = was or _UPLOADING or "@@START" in msg or "@@END" in msg
        if not in_upload and "STOP" in msg:
            msg = msg.replace("STOP", "")
            if _IN_RUN and not _STOP_REQ:
                system_status.running = False
                _STOP_REQ = True
                _STOP_AT = time.ticks_ms()

        if msg:
            _route(msg, src)
    except Exception as e:
        print("RX error:", type(e).__name__, e)          # never drop data silently


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

def _drain_inbox():
    """Move queued RX text into BUFFER. Only the main loop calls this."""
    global BUFFER
    if _INBOX:
        parts = []
        while _INBOX:
            parts.append(_INBOX.pop(0))
        BUFFER += "".join(parts)


MAIN_VERSION = "r4.6-video"   # tells the app this board takes fast uploads safely


def _commands(text):
    """Handle commands found in `text` (never inside an upload).
    Returns (result, remaining_text)."""
    # main.py version query - the app uploads faster when it sees "-flow".
    if "MAINVER?" in text:
        text = text.replace("MAINVER?", "")
        print("MAINVER:" + MAIN_VERSION)

    # Version query — how the app decides whether an update is needed.
    if "LIBVER?" in text:
        text = text.replace("LIBVER?", "")
        print("LIBVER:" + lib_version())

    # Library transfer.
    if "@@FILE:" in text and "@@FILEEND" in text:
        head, rest = text.split("@@FILE:", 1)
        payload, tail = rest.split("@@FILEEND", 1)
        text = head + tail
        try:
            header, body = payload.split("\n", 1)
            parts = header.split(":")
            save_library(parts[0], body, parts[1] if len(parts) > 1 else "")
        except Exception as e:
            print("FILE:ERR:malformed header: %s" % e)

    # The app's Soft Reset / Hard Reset buttons send these words.
    if "SOFT_RESET" in text:
        print(">> Soft reset...")
        time.sleep_ms(50)
        machine.soft_reset()
    if "HARD_RESET" in text:
        print(">> Hard reset...")
        time.sleep_ms(50)
        machine.reset()

    if "UPLOAD" in text:
        text = text.replace("UPLOAD", "", 1)
        erase_user_code()
        print(">> Waiting for @@START...")
        return "READY_FOR_DATA", text

    if "PLAY" in text:
        text = text.replace("PLAY", "", 1)
        return "START_EXECUTION", text

    return None, text


def process_comms():
    global BUFFER, RECEIVING, _DWV
    _drain_inbox()

    # Video transfer in progress: every complete line goes to the video handler.
    if _DWV is not None:
        pos = 0
        while _DWV is not None:
            nl = BUFFER.find("\n", pos)
            if nl < 0:
                break
            line = BUFFER[pos:nl].strip()
            pos = nl + 1
            if line:
                _dwv_line(line)
        BUFFER = BUFFER[pos:]
        if _DWV is not None:
            if time.ticks_diff(time.ticks_ms(), _DWV[5]) > 30000:
                print("DWV:ERR timeout")
                _DWV = None
            return None

    # Start of a video transfer (only outside a program upload).
    k = BUFFER.find("@@DWV:")
    if k >= 0 and not RECEIVING and "@@START" not in BUFFER[:k]:
        nl = BUFFER.find("\n", k)
        if nl < 0:
            return None                         # wait for the whole start line
        _commands(BUFFER[:k])                   # answer MAINVER?/LIBVER? sent before it
        header = BUFFER[k + 6:nl].strip()
        BUFFER = BUFFER[nl + 1:]
        if header != "END":
            _dwv_start(header)
        return process_comms()

    # While a program is arriving, its text may contain PLAY ("DISPLAY"),
    # UPLOAD or LIBVER? - never treat them as commands. Only look for @@END.
    # The text is moved out of BUFFER every loop, so BUFFER stays small.
    if RECEIVING:
        data, BUFFER = BUFFER, ""
        rest = _receive(data)
        del data
        if rest is None:
            return None
        BUFFER = rest
        RECEIVING = False
        print(">> Upload complete.")

    # Commands are only looked for in the text before any @@START.
    head, sep, rest = BUFFER.partition("@@START")

    # A library transfer (base64, so it never contains @@START) must arrive
    # whole before it is handled.
    if "@@FILE:" in head and "@@FILEEND" not in head:
        return None

    result, head = _commands(head)
    if not head.strip():
        head = ""               # drop leftover newlines from earlier commands
    BUFFER = head + sep + rest
    if result:
        return result
    if sep:
        RECEIVING = True
        try:
            _upl_start()
        except Exception as e:
            print(f"Save error: {e}")
        BUFFER = rest
        return process_comms()
    return None


# ── Execution engine ──────────────────────────────────────────────────────────

def run_engine():
    global _IN_RUN, _STOP_REQ
    print(">> Executing...")
    system_status.running = True
    _IN_RUN = True

    # Drop replies left over from a previous run — their ids are stale.
    if iot_bus:
        iot_bus.clear()

    try:
        if "user" in sys.modules:
            del sys.modules["user"]

        # Load lib (142 KB of source) BEFORE compiling user.py: a program with a
        # picture or animation holds ~70 KB of hex strings while it is compiled,
        # and lib's compile on top of that ran out of memory. lib stays loaded,
        # so later runs skip this.
        gc.collect()
        import lib
        if hasattr(lib, "_telemetry_sensors"):
            lib._telemetry_sensors.clear()
            lib._telemetry_changed = True
            lib._telemetry_draw()
        gc.collect()

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
            _run_guarded(result)    # uasyncio loop + STOP watcher
        # sync def already ran above

    except KeyboardInterrupt:
        print("\n[!] Stopped.")
    except Exception as e:
        sys.print_exception(e)
    finally:
        _IN_RUN = False
        _STOP_REQ = False
        system_status.running = False
        # Free the finished program now (its picture data can be tens of KB),
        # not at the next PLAY - otherwise the next upload has less memory.
        sys.modules.pop("user", None)
        gc.collect()
        print(">> Ready.")


# ── Main loop ─────────────────────────────────────────────────────────────────

print("SYSTEM READY  |  UPLOAD  PLAY  STOP")

_settings_due = time.ticks_ms()

while True:
    # An error here must never end main.py: the board would drop to the
    # MicroPython prompt and silently ignore PLAY/UPLOAD from the app.
    # (Ctrl-C is a KeyboardInterrupt, not an Exception, so tools like
    # mpremote can still stop main.py.)
    try:
        cmd = process_comms()
        if _DWV is None and not RECEIVING:
            # Home-page clock: time from the internet via ESP32 Wi-Fi,
            # redrawn once a minute (handled inside dwin_get_data).
            try:
                import dwin_get_data
                dwin_get_data.tick()
            except Exception as e:
                print("clock:", e)
        _kb_open = False
        if _DWV is None and not RECEIVING:
            # Wi-Fi setup on the display: network taps and keyboard keys.
            try:
                import dwin_wifi_ui
                dwin_wifi_ui.poll()
                _kb_open = dwin_wifi_ui.busy()
            except Exception as e:
                print("wifi ui:", e)
        if _DWV is None and not RECEIVING and not _kb_open and time.ticks_diff(time.ticks_ms(), _settings_due) >= 0:
            # Keep the display's Settings values current even though its broken
            # TX return path cannot report when the user opens that page.
            try:
                import dwin_get_data
                dwin_get_data.refresh()
            except Exception as e:
                print("settings refresh:", e)
            _settings_due = time.ticks_add(time.ticks_ms(), 2500)
        if _DWV is None and not RECEIVING and not _kb_open:
            # Check DWIN Projects List touch keys (PLAY=0x0501, STOP=0x0502)
            try:
                import dwin_screen as dw
                k = dw._dw_read(0x5F60, 1)
                if k and k[0]:
                    key = k[0]
                    dw._dw_vp(0x5F60, b'\x00\x00')
                    if key == 0x0501:       # PLAY button pressed on DWIN display!
                        print("\n[DWIN] PLAY button pressed.")
                        cmd = "START_EXECUTION"
                    elif key == 0x0502:     # STOP button pressed while idle
                        print("\n[DWIN] STOP button pressed (idle).")
            except Exception:
                pass
        if cmd == "START_EXECUTION":
            if FILENAME in os.listdir():
                run_engine()
            else:
                print("Error: no user.py. Send UPLOAD first.")
    except Exception as e:
        print("main.py error:", e)
        BUFFER = ""
        RECEIVING = False
        _upl_abort()
        gc.collect()
    time.sleep_ms(50)
