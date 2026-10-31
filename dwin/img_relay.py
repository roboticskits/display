"""Image relay: receives a picture from the PC over USB and draws it on the
DWIN display through UART1 using the two Basic Graphic controls on page 39.

Each control keeps its dot list in the display's variable memory, so the
picture stays on screen: VP = command 0x0001, VP+1 = dot count,
VP+2.. = x, y, colour per dot, then an FFFF terminator.

Started by the PC app (dwin_image_app.py). Protocol from the PC, binary:
  b"IMG1" + x(2) y(2) w(2) h(2) step(1)   + w*h*2 bytes RGB565 big-endian
             step = size of each dot on screen (3 = 3x3 pixels)
  b"CLR1"                               clear the viewer page
  b"PAG1" + page(2)                     switch display page
  b"PNG1"                               ping, replies PONG
  b"BYE1"                               leave the relay (also after 10 min idle)
Replies are text lines: READY, P<percent>, DONE <ms>, OK, ERR <text>.
"""
import pyb, time, struct, micropython
from machine import UART

REGIONS = ((0x1000, 6900), (0x8400, 10560))     # (VP, max dots that fit)
PAGE = 39
DOTS_PER_FRAME = 40

usb = pyb.USB_VCP()
usb.setinterrupt(-1)                    # binary data may contain Ctrl-C
try:
    import __main__
    __main__.stop_checker.deinit()      # the Blockly engine's USB watcher
except Exception:
    pass
u = UART(1, 115200, timeout=0, rxbuf=1024)


def recv(n, timeout_ms=5000):
    buf = bytearray(n)
    mv = memoryview(buf)
    got = 0
    t0 = time.ticks_ms()
    while got < n:
        k = usb.recv(mv[got:], timeout=200)
        if k:
            got += k
            t0 = time.ticks_ms()
        elif time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            raise OSError("timeout")
    return buf


ACK = b"\x5a\xa5\x03\x82\x4f\x4b"
lost = 0


def send(frame):
    """Write one frame and wait for the display's OK; resend if it is lost."""
    global lost
    for attempt in range(3):
        u.write(frame)
        t0 = time.ticks_ms()
        got = b""
        while time.ticks_diff(time.ticks_ms(), t0) < 40:
            n = u.any()
            if n:
                got += u.read(n)
                if ACK in got:
                    return
        lost += 1


def write_vp(vp, data):
    send(bytes((0x5A, 0xA5, 3 + len(data), 0x82, vp >> 8, vp & 0xFF)) + data)


def set_page(p):
    write_vp(0x0084, bytes((0x5A, 0x01, p >> 8, p & 0xFF)))


def clear():
    for vp, _ in REGIONS:
        write_vp(vp, struct.pack(">HH", 1, 0) + b"\xff\xff")   # zero dots


@micropython.viper
def _fill_dots(out: ptr8, src: ptr8, n: int, x0: int, step: int, y: int):
    o = 0
    for i in range(n):
        x = x0 + i * step
        out[o] = x >> 8
        out[o + 1] = x & 0xFF
        out[o + 2] = y >> 8
        out[o + 3] = y & 0xFF
        out[o + 4] = src[2 * i]
        out[o + 5] = src[2 * i + 1]
        o += 6


def draw_image(x0, y0, w, h, step, pixels):
    """Rows are split across the two regions; dots are stored permanently."""
    frame = bytearray(6 + 6 * DOTS_PER_FRAME)
    frame[0:4] = bytes((0x5A, 0xA5, 0, 0x82))
    mv = memoryview(frame)
    body = mv[6:]
    pix = memoryview(pixels)
    rows_a = min(h, REGIONS[0][1] // w)
    if (h - rows_a) * w > REGIONS[1][1]:
        raise ValueError("image too big for display memory")
    plan = ((REGIONS[0][0], 0, rows_a), (REGIONS[1][0], rows_a, h))
    last_pct = -1
    t0 = time.ticks_ms()
    for vp, r0, r1 in plan:
        write_vp(vp, struct.pack(">HH", 1, (r1 - r0) * w))     # command + count
        addr = vp + 2
        for j in range(r0, r1):
            y = y0 + j * step
            row = pix[j * w * 2:(j + 1) * w * 2]
            i = 0
            while i < w:
                n = w - i
                if n > DOTS_PER_FRAME:
                    n = DOTS_PER_FRAME
                _fill_dots(body, row[2 * i:], n, x0 + i * step, step, y)
                end = 6 + 6 * n
                frame[2] = end - 3
                frame[4] = addr >> 8
                frame[5] = addr & 0xFF
                send(mv[:end])
                addr += 3 * n
                i += n
            pct = (j + 1) * 100 // h
            if pct != last_pct and pct % 2 == 0:
                usb.write(b"P%d\n" % pct)
                last_pct = pct
        write_vp(addr, b"\xff\xff")                             # terminator
    return time.ticks_diff(time.ticks_ms(), t0)


def main():
    usb.write(b"READY\n")
    while True:
        try:
            cmd = bytes(recv(4, 600000))
        except OSError:
            usb.write(b"ERR idle timeout\n")
            return
        try:
            if cmd == b"IMG1":
                x, y, w, h, step = struct.unpack(">HHHHB", recv(9))
                pixels = recv(w * h * 2, 20000)
                set_page(PAGE)
                time.sleep_ms(60)
                global lost
                lost = 0
                ms = draw_image(x, y, w, h, step, pixels)
                usb.write(b"DONE %d lost=%d\n" % (ms, lost))
            elif cmd == b"CLR1":
                set_page(PAGE)
                time.sleep_ms(60)
                clear()
                usb.write(b"OK\n")
            elif cmd == b"PAG1":
                (p,) = struct.unpack(">H", recv(2))
                set_page(p)
                usb.write(b"OK\n")
            elif cmd == b"PNG1":
                usb.write(b"PONG\n")
            elif cmd == b"BYE1":
                usb.write(b"OK\n")
                return
            else:
                usb.write(b"ERR bad command\n")
        except Exception as e:
            usb.write(b"ERR %s\n" % str(e).encode())


main()
