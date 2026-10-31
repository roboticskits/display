"""Bird face on the DWIN DGUS display, driven from the CURIO motherboard.

The face frames are pages 15..38 on the display (8 moods x 3 frames:
A, B and blink). The mood buttons on those pages are display-side page
jumps, so this script just watches which page the display is on and keeps
the current mood animated by switching between its frame pages.

run:  import dwin_bird; dwin_bird.run()        (Ctrl+C stops)
      dwin_bird.show("HAPPY")                   open the face at a mood
"""
import time
from machine import UART

UART_ID, BAUD = 1, 115200
FIRST_PAGE, FRAMES = 15, 3
MOODS = ("HAPPY", "SAD", "ANGRY", "SURPRISED", "LOVE", "SLEEPY", "EXCITED", "CURIOUS")
HOME_PAGE = 10

_u = None


def uart():
    global _u
    if _u is None:
        _u = UART(UART_ID, BAUD, timeout=40)
    return _u


def _cmd(frame, reply=True):
    u = uart()
    u.read()
    u.write(frame)
    if reply:
        time.sleep_ms(25)
        return u.read() or b""


def set_page(p):
    _cmd(bytes((0x5A, 0xA5, 0x07, 0x82, 0x00, 0x84, 0x5A, 0x01, p >> 8, p & 0xFF)))


def get_page():
    r = _cmd(bytes((0x5A, 0xA5, 0x04, 0x83, 0x00, 0x14, 0x01)))
    if len(r) >= 9 and r[:4] == b"\x5a\xa5\x06\x83":
        return (r[7] << 8) | r[8]
    return None


def show(mood="HAPPY"):
    set_page(FIRST_PAGE + MOODS.index(mood) * FRAMES)


class _Anim:
    """One animation step at a time, so it can run blocking or as a task."""

    def __init__(self):
        now = time.ticks_ms()
        self.last_toggle = now
        self.next_blink = time.ticks_add(now, 2500)
        self.frame = 0

    def step(self):
        """Returns (delay_ms, blink_base) - blink_base set when a blink is due."""
        page = get_page()
        now = time.ticks_ms()
        if page is None or not (FIRST_PAGE <= page < FIRST_PAGE + len(MOODS) * FRAMES):
            return 150, None                # not on the face: nothing to do
        mood = (page - FIRST_PAGE) // FRAMES
        base = FIRST_PAGE + mood * FRAMES
        if MOODS[mood] != "SLEEPY" and time.ticks_diff(now, self.next_blink) >= 0:
            self.next_blink = time.ticks_add(now, 2500 + (now % 2000))
            set_page(base + 2)              # blink frame; caller restores after 120 ms
            return 120, base
        if time.ticks_diff(now, self.last_toggle) >= 650:
            self.frame ^= 1
            set_page(base + self.frame)
            self.last_toggle = now
        return 80, None


def run(duration_ms=None):
    """Blocking: animate the bird while the display is on one of its pages."""
    a = _Anim()
    start = time.ticks_ms()
    while duration_ms is None or time.ticks_diff(time.ticks_ms(), start) < duration_ms:
        delay, blink_base = a.step()
        time.sleep_ms(delay)
        if blink_base is not None:
            set_page(blink_base + a.frame)


_running = False


def stop():
    """Ends a running task() at its next step."""
    global _running
    _running = False


async def task():
    """asyncio version for user.py:  asyncio.create_task(dwin_bird.task())"""
    global _running
    import asyncio
    a = _Anim()
    _running = True
    while _running:
        delay, blink_base = a.step()
        await asyncio.sleep_ms(delay)
        if blink_base is not None:
            set_page(blink_base + a.frame)
