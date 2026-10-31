"""Build dwin_screen.py for the CM MOTHERBOARD R4 from the R3 lib section
(board_main/lib_dwin_section.py), so both boards keep the same picture /
saved-picture / video code. Changes for R4:
  - its own module (lib.py only does "from dwin_screen import *"): lib.py is
    already 142 KB, one bigger file may not compile in the free memory
  - display on USART3, PD8 / PD9 (connector J5), TX and RX swapped for the
    straight-wired J5 (USART CR2.SWAP); PB10 / PB11 (UART3's default pins,
    JACK3) are released so they do not share the receive input
  - "no-reply" mode: if the display's OK never arrives (its TX does not reach
    the board), frames are sent without waiting and flash jobs get fixed waits
usage: python make_dwin_screen.py   ->  dwin_screen.py

WARNING (2026-10-28): dwin_screen.py has since been edited directly - the
no-reply changes of 2026-10-26 and the automatic 460800/115200 display speed
(_DW_BAUDS, _dw_open, _dw_try). Running this script overwrites them; merge
those edits into this script first."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "board_main", "lib_dwin_section.py")
OUT = os.path.join(HERE, "dwin_screen.py")

HEADER = '''################################################################################
# dwin_screen.py - DWIN SMART DISPLAY on the CM MOTHERBOARD R4 (STM32H723)
#
# Built by make_dwin_screen.py from board_main/lib_dwin_section.py (the R3
# board's lib section); edit that file and rebuild, not this one.
# lib.py ends with "from dwin_screen import *", so Blockly programs use these
# functions as before; main.py's video transfer imports this module directly.
#
# Display on connector J5: USART3, PD8 / PD9, 115200 baud. J5 is wired
# straight (display TX to J5 TX), so the USART swaps TX and RX (CR2.SWAP):
# the STM32 sends on PD9 and listens on PD8. Crossed wiring: _DW_SWAP = False.
#
# No-reply mode: when the display's OK never arrives (its TX does not reach
# PD8), frames are sent without waiting for it, flash and database jobs get
# fixed waits instead of being polled, a saved slot is shown without checking
# it is filled, and a picture can only be saved to the PROJECTS LIST if this
# board drew it (the screen cannot be read back).
################################################################################

import time
import gc
import machine
import micropython
from machine import UART, Pin
import uasyncio as asyncio

_DW_UART_ID = 3
_DW_BAUD = 115200
_DW_SWAP = True                                    # J5 wired straight: TX on PD9, RX on PD8
_DW_USART_BASE = 0x40004800                        # USART3 registers
_dw_blind = None                                   # None = not known yet, True = no replies
'''

OLD_PORT = '''def _dw_port():
    global _dw_uart
    if _dw_uart is None:
        _dw_uart = UART(1, 115200, timeout=0, rxbuf=1024)
    return _dw_uart


def _dw_send(frame):
    """Write one frame, wait up to 40 ms for the display's OK; 3 tries."""
    u = _dw_port()
    for _ in range(3):
        u.write(frame)
        t0 = time.ticks_ms()
        got = b''
        while time.ticks_diff(time.ticks_ms(), t0) < 40:
            n = u.any()
            if n:
                got += u.read(n)
                if _DW_ACK in got:
                    return True
    return False
'''

NEW_PORT = '''def _dw_port():
    global _dw_uart
    if _dw_uart is None:
        _dw_uart = UART(_DW_UART_ID, _DW_BAUD, timeout=0, rxbuf=1024)
        Pin('B10', Pin.IN)                         # UART3's default pins (JACK3) let go,
        Pin('B11', Pin.IN)                         # so only PD8 feeds the receiver
        Pin('D8', Pin.ALT, alt=7)                  # PD8 / PD9 = USART3 (AF7)
        Pin('D9', Pin.ALT, alt=7)
        if _DW_SWAP:
            cr1 = machine.mem32[_DW_USART_BASE]
            machine.mem32[_DW_USART_BASE] = cr1 & ~1               # SWAP changes only while off
            machine.mem32[_DW_USART_BASE + 4] |= 1 << 15
            machine.mem32[_DW_USART_BASE] = cr1
    return _dw_uart


def _dw_send(frame):
    """Write one frame, wait up to 40 ms for the display's OK; 3 tries. With
    no OK at all the display's replies do not reach the board: from then on
    frames are only sent (no-reply mode)."""
    global _dw_blind
    u = _dw_port()
    if _dw_blind:
        u.write(frame)                             # returns when sent
        time.sleep_ms(1)
        return True
    for _ in range(3):
        u.write(frame)
        t0 = time.ticks_ms()
        got = b''
        while time.ticks_diff(time.ticks_ms(), t0) < 40:
            n = u.any()
            if n:
                got += u.read(n)
                if _DW_ACK in got:
                    _dw_blind = False
                    return True
    if _dw_blind is None:
        _dw_blind = True
        print('dwin: no reply from the display (its TX does not reach PD8) - sending without checks')
    return False
'''

EDITS = [
    (OLD_PORT, NEW_PORT),
    # reading: nothing to wait for without replies
    ('''    """Read n words of display VP memory; None if the display does not answer."""
    u = _dw_port()
''', '''    """Read n words of display VP memory; None if the display does not answer."""
    if _dw_blind:
        return None
    u = _dw_port()
'''),
    # database copy: fixed wait without replies
    ('''                          vp >> 8, vp & 0xFF, words >> 8, words & 0xFF)))
    t0 = time.ticks_ms()
    while True:
        s = _dw_read(0x0008, 1)''', '''                          vp >> 8, vp & 0xFF, words >> 8, words & 0xFF)))
    t0 = time.ticks_ms()
    if _dw_blind:                                  # no replies: generous fixed wait
        while time.ticks_diff(time.ticks_ms(), t0) < 150 + words // 8:
            yield
        return
    while True:
        s = _dw_read(0x0008, 1)'''),
    # show: the slot's marker cannot be checked without replies
    ('''    if head != [(m[2 * j] << 8) | m[2 * j + 1] for j in range(4)]:''',
     '''    if not _dw_blind and head != [(m[2 * j] << 8) | m[2 * j + 1] for j in range(4)]:'''),
    # flash block write: fixed wait without replies
    ('''    _dw_vp(0x00AA, bytes((0x5A, 0x02, block >> 8, block & 0xFF, vp >> 8, vp & 0xFF, 0, 20, 0, 0, 0, 0)))
    t0 = time.ticks_ms()
    while True:''', '''    _dw_vp(0x00AA, bytes((0x5A, 0x02, block >> 8, block & 0xFF, vp >> 8, vp & 0xFF, 0, 20, 0, 0, 0, 0)))
    t0 = time.ticks_ms()
    while _dw_blind and time.ticks_diff(time.ticks_ms(), t0) < 1000:   # no replies: fixed wait
        yield
    while not _dw_blind:'''),
    # PROJECTS LIST: the screen cannot be read back without replies
    ('''    if _dw_last is None:
        _dw_last = yield from _dw_screen_pixels_steps()''', '''    if _dw_last is None:
        if _dw_blind:
            raise ValueError('the display cannot be read back (no reply) - draw the picture with show image first')
        _dw_last = yield from _dw_screen_pixels_steps()'''),
]

src = open(SRC, encoding="utf-8").read().replace("\r\n", "\n")
start = src.index("import struct as _dw_struct")
body = src[start:]
for old, new in EDITS:
    n = body.count(old)
    if n != 1:
        raise SystemExit("anchor found %d times:\n%s" % (n, old[:160]))
    body = body.replace(old, new)
open(OUT, "w", encoding="utf-8", newline="\n").write(HEADER + "\n" + body)
print("wrote %s (%d bytes)" % (OUT, len(HEADER) + 1 + len(body)))
