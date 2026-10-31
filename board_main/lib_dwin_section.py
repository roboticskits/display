

################################################################################
# DWIN SMART DISPLAY  (DMG48320C035_03W on UART1: PA9 TX, PA10 RX, 115200)
#
# Used by the Blockly blocks in the "DWIN Screen" category.
#
#   SYNC : dwin_image(img)        dwin_clear()        dwin_page(page)
#   ASYNC: async_dwin_image(img)  async_dwin_clear()  async_dwin_page(page)
#   saved pictures (kept in the display's own flash, shown instantly):
#   SYNC : dwin_save(slot)        dwin_show_saved(slot)        slot 1-3
#   ASYNC: async_dwin_save(slot)  async_dwin_show_saved(slot)
#
# img is the picture packed by the "show image" block in the browser:
#   (width, height, enc, 'hex')   width x height RGB565 pixels (max 160 x 106)
#   enc 0 = raw, enc 1 = zlib-compressed, hex = lowercase hex text, either one
#   string or a tuple of strings of <= 4096 characters (what Blockly makes now)
#
# Page 39 (from the display's SD card) is a black image page with two Basic
# Graphic controls at VP 0x1000 and VP 0x8400. Each picture pixel is drawn as
# a 3x3 dot, so 160 x 106 fills the 480 x 320 screen. The display redraws the
# dots from its memory on every frame, so the picture stays until cleared.
# Drawing takes about 10 s: the 115200 baud serial link is the limit.
################################################################################

import struct as _dw_struct
import binascii as _dw_ba

_dw_uart = None
_dw_last = None                                    # (w, h, pixels) of the picture on page 39
_dw_pixbuf = None                                  # pixel buffer, allocated once
_dw_zbuf = None                                    # compressed-data buffer, allocated once
_dw_ebuf = None                                    # encoder buffer if _dw_zbuf does not exist
_DW_ACK =b'\x5a\xa5\x03\x82\x4f\x4b'             # display's OK reply to a write
_DW_REGIONS = ((0x1000, 6900), (0x8400, 10560))    # (VP, max dots) on page 39
_DW_IMAGE_PAGE = 39
_DW_DOTS = 40                                      # dots per serial frame


def _dw_port():
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


def _dw_vp(vp, data):
    """Write bytes to a display variable (VP) address."""
    return _dw_send(bytes((0x5A, 0xA5, 3 + len(data), 0x82, vp >> 8, vp & 0xFF)) + data)


def _dw_pixels(n):
    """The one pixel buffer (reused for every picture so memory does not
    fragment from run to run); a memoryview of its first n bytes."""
    global _dw_pixbuf
    if _dw_pixbuf is None or len(_dw_pixbuf) < n:
        _dw_pixbuf = None
        gc.collect()
        _dw_pixbuf = bytearray(max(n, 160 * 106 * 2))
    return memoryview(_dw_pixbuf)[:n]


def _dw_zbuffer(n):
    """The one buffer for compressed picture data (reused, like _dw_pixels)."""
    global _dw_zbuf
    if _dw_zbuf is None or len(_dw_zbuf) < n:
        _dw_zbuf = None
        gc.collect()
        _dw_zbuf = bytearray(max(n, 32 * 1024))
    return memoryview(_dw_zbuf)[:n]


def _dw_unhex(data, out):
    """Hex text -> bytes written into out; returns the byte count. data is one
    string or (Blockly since 2026-10-20) a tuple of short strings, so that
    importing user.py never needs one big block for the picture."""
    if isinstance(data, str):
        data = (data,)
    o = 0
    for part in data:
        for i in range(0, len(part), 4096):
            b = _dw_ba.unhexlify(part[i:i + 4096])
            out[o:o + len(b)] = b
            o += len(b)
    return o


def _dw_plan(img):
    """Unpack the picture and check it fits page 39. None if it does not."""
    global _dw_last
    w, h, enc, data = img
    n = w * h * 2
    _dw_last = None                                   # the old picture's pixels are not needed now
    gc.collect()
    size = (len(data) if isinstance(data, str) else sum(len(p) for p in data)) // 2
    try:
        if enc == 1:
            src = _dw_zbuffer(size)
            pix = _dw_pixels(n)
            _dw_unhex(data, src)
            got = _dw_inflate(src, pix)               # straight into the buffer, no 32 KB window
        else:
            pix = _dw_pixels(n)
            got = _dw_unhex(data, pix) if size == n else -1
    except (ValueError, IndexError):
        got = -1
    gc.collect()
    if got != n:
        print('dwin image: bad data')
        return None
    rows_a = min(h, _DW_REGIONS[0][1] // w)
    if (h - rows_a) * w > _DW_REGIONS[1][1]:
        print('dwin image: too big')
        return None
    return w, h, pix, rows_a


def _dw_rows(w, h, pix, rows_a):
    """Send the picture as dots, one row at a time; yields after each row.
    Each dot is x, y, colour (2 bytes each), 40 dots per frame."""
    x0 = (480 - w * 3) // 2
    y0 = (320 - h * 3) // 2
    frame = bytearray(6 + 6 * _DW_DOTS)
    frame[0] = 0x5A
    frame[1] = 0xA5
    frame[3] = 0x82
    mv = memoryview(frame)
    for vp, r0, r1 in ((_DW_REGIONS[0][0], 0, rows_a), (_DW_REGIONS[1][0], rows_a, h)):
        _dw_vp(vp, _dw_struct.pack('>HH', 1, (r1 - r0) * w))   # draw-dots command + count
        addr = vp + 2
        for j in range(r0, r1):
            y = y0 + j * 3
            yh = y >> 8
            yl = y & 0xFF
            i = 0
            while i < w:
                n = min(_DW_DOTS, w - i)
                x = x0 + i * 3
                s = (j * w + i) * 2
                o = 6
                for _ in range(n):
                    frame[o] = x >> 8
                    frame[o + 1] = x & 0xFF
                    frame[o + 2] = yh
                    frame[o + 3] = yl
                    frame[o + 4] = pix[s]
                    frame[o + 5] = pix[s + 1]
                    o += 6
                    x += 3
                    s += 2
                frame[2] = o - 3
                frame[4] = addr >> 8
                frame[5] = addr & 0xFF
                _dw_send(mv[:o])
                addr += 3 * n
                i += n
            yield
        _dw_vp(addr, b'\xff\xff')                             # end of dot list


def dwin_page(page):
    """Switch the display to a page number."""
    page = int(page)
    _dw_vp(0x0084, bytes((0x5A, 0x01, page >> 8, page & 0xFF)))

async def async_dwin_page(page):
    dwin_page(page)
    await asyncio.sleep_ms(0)


def dwin_clear():
    """Remove the picture from page 39."""
    global _dw_last
    _dw_last = None
    for vp, _ in _DW_REGIONS:
        _dw_vp(vp, _dw_struct.pack('>HH', 1, 0) + b'\xff\xff')

async def async_dwin_clear():
    dwin_clear()
    await asyncio.sleep_ms(0)


def dwin_image(img):
    """Show a picture on page 39 (blocks until it is drawn, about 10 s)."""
    global _dw_last
    plan = _dw_plan(img)
    if plan:
        dwin_page(_DW_IMAGE_PAGE)
        time.sleep_ms(60)
        for _ in _dw_rows(*plan):
            pass
        _dw_last = plan[:3]                            # (w, h, pixels) for dwin_save

async def async_dwin_image(img):
    """Show a picture on page 39. Yields after every row, so other
    tasks keep running while it draws."""
    global _dw_last
    plan = _dw_plan(img)
    if plan:
        dwin_page(_DW_IMAGE_PAGE)
        await asyncio.sleep_ms(60)
        for _ in _dw_rows(*plan):
            await asyncio.sleep_ms(0)
        _dw_last = plan[:3]                            # (w, h, pixels) for dwin_save


# ---- saved pictures, kept in the display's own flash -------------------------
#   SYNC : dwin_save(slot)        dwin_show_saved(slot)        slot = 1, 2 or 3
#   ASYNC: async_dwin_save(slot)  async_dwin_show_saved(slot)
#
# The T5L chip has a 160K-word user database in its on-chip flash (this
# project does not use it). System variable 0x0008 copies between that flash
# and VP memory INSIDE the display, so a saved picture comes back instantly
# with no picture data on the UART, and it survives power-off.
# A slot holds the finished dot lists of both regions: a 4-word header,
# region A (VP 0x1000) and region B (VP 0x8400) = 52392 words; 3 slots fit.

_DW_SLOT_MAGIC = b'DWIM\x00\x01\x00\x00'       # marks a complete saved picture
_DW_SCRATCH_VP = 0xFFF0                        # 4 free words after region B
_DW_SLOT_A = 2 + 3 * _DW_REGIONS[0][1] + 2     # 20704 words (even)
_DW_SLOT_B = 2 + 3 * _DW_REGIONS[1][1] + 2     # 31684 words (even)
_DW_SLOT_WORDS = 4 + _DW_SLOT_A + _DW_SLOT_B
_DW_SLOTS = 3


def _dw_read(vp, n):
    """Read n words of display VP memory; None if the display does not answer."""
    u = _dw_port()
    u.read()
    u.write(bytes((0x5A, 0xA5, 4, 0x83, vp >> 8, vp & 0xFF, n)))
    want = 7 + 2 * n
    t0 = time.ticks_ms()
    got = b''
    while time.ticks_diff(time.ticks_ms(), t0) < 100:
        k = u.any()
        if k:
            got += u.read(k)
            i = got.find(b'\x5a\xa5')
            while 0 <= i and len(got) - i >= want:
                if got[i + 3] == 0x83 and got[i + 4] == vp >> 8 and got[i + 5] == vp & 0xFF:
                    d = got[i + 7:i + want]
                    return [(d[2 * j] << 8) | d[2 * j + 1] for j in range(n)]
                i = got.find(b'\x5a\xa5', i + 2)
    return None


def _dw_db(op, addr, vp, words):
    """Generator: copy between the flash database and VP memory
    (op 0xA5 = VP to flash, 0x5A = flash to VP); yields until finished."""
    _dw_vp(0x0008, bytes((op, addr >> 16, (addr >> 8) & 0xFF, addr & 0xFF,
                          vp >> 8, vp & 0xFF, words >> 8, words & 0xFF)))
    t0 = time.ticks_ms()
    while True:
        s = _dw_read(0x0008, 1)
        if s is not None and s[0] >> 8 == 0:      # display clears the start byte when done
            return
        if time.ticks_diff(time.ticks_ms(), t0) > 10000:
            raise OSError('DWIN flash did not finish')
        yield


def _dw_slot_base(slot):
    slot = int(slot)
    if not 1 <= slot <= _DW_SLOTS:
        raise ValueError('picture slot must be 1 to %d' % _DW_SLOTS)
    return (slot - 1) * _DW_SLOT_WORDS


def _dw_save_steps(slot, result):
    base = _dw_slot_base(slot)
    _dw_vp(_DW_SCRATCH_VP, bytes(8))                  # slot counts as empty while writing
    yield from _dw_db(0xA5, base, _DW_SCRATCH_VP, 4)
    yield from _dw_db(0xA5, base + 4, _DW_REGIONS[0][0], _DW_SLOT_A)
    yield from _dw_db(0xA5, base + 4 + _DW_SLOT_A, _DW_REGIONS[1][0], _DW_SLOT_B)
    _dw_vp(_DW_SCRATCH_VP, _DW_SLOT_MAGIC)            # complete: write the marker last
    yield from _dw_db(0xA5, base, _DW_SCRATCH_VP, 4)
    result.append(True)
    if _DW_PAGES:                                     # also refresh the PROJECTS LIST pages
        try:
            yield from _dw_pages_steps(int(slot))
        except Exception as e:
            print('dwin: saved, but PROJECTS LIST not updated:', e)


def _dw_show_steps(slot, result):
    base = _dw_slot_base(slot)
    yield from _dw_db(0x5A, base, _DW_SCRATCH_VP, 4)
    head = _dw_read(_DW_SCRATCH_VP, 4)
    m = _DW_SLOT_MAGIC
    if head != [(m[2 * j] << 8) | m[2 * j + 1] for j in range(4)]:
        print('dwin: picture slot %d is empty' % int(slot))
        return
    yield from _dw_db(0x5A, base + 4, _DW_REGIONS[0][0], _DW_SLOT_A)
    yield from _dw_db(0x5A, base + 4 + _DW_SLOT_A, _DW_REGIONS[1][0], _DW_SLOT_B)
    global _dw_last
    _dw_last = None                                   # pixels on screen now come from flash
    dwin_page(_DW_IMAGE_PAGE)
    result.append(True)


def dwin_save(slot):
    """Save the picture now on page 39 into the display's flash, slot 1-3.
    Returns True when saved."""
    r = []
    for _ in _dw_save_steps(slot, r):
        time.sleep_ms(5)
    return bool(r)

async def async_dwin_save(slot):
    r = []
    for _ in _dw_save_steps(slot, r):
        await asyncio.sleep_ms(5)
    return bool(r)


def dwin_show_saved(slot):
    """Show a picture saved with dwin_save (instant). False if the slot is empty."""
    r = []
    for _ in _dw_show_steps(slot, r):
        time.sleep_ms(5)
    return bool(r)

async def async_dwin_show_saved(slot):
    r = []
    for _ in _dw_show_steps(slot, r):
        await asyncio.sleep_ms(5)
    return bool(r)


# ---- PROJECTS LIST pages, updated over UART (no SD card) ---------------------
# The SD-card project has a picture library 24_SavedPictures.icl (flash font
# ID 24) shown by icon controls: page 40 (PROJECTS LIST) shows icons 0-2 as
# thumbnails, pages 41-43 show icons 3-5 as large views. Every icon sits at a
# fixed 32 KB flash block, so dwin_save() can replace one in place with the
# display's flash write command (VP 0x00AA). The STM32 makes the JPEGs itself:
# baseline, 4:4:4, standard Huffman tables, in the display's 4-byte layout.

import micropython
import gc

_DW_PAGES = True                    # dwin_save() also refreshes PROJECTS LIST
_DW_LIB_ID = 24                      # 24_SavedPictures.icl
_DW_THUMB = (120, 80)                # icon sizes (must be multiples of 8)
_DW_VIEW = (408, 272)
_DW_STAGE_A = 0x1002                 # 16K words staged here for a 32 KB block write
_DW_STAGE_B = 0x8402                 # (just past each page-39 control's command words)
_DW_QUALITY = 85


# ---- zlib decoder for the picture data ----------------------------------------
# MicroPython's deflate module needs its own 32 KB window block, which a
# fragmented heap often cannot give. This decoder (after puff.c, RFC 1950/1951)
# writes straight into the pixel buffer and uses the picture itself as the
# window, so it needs no large block at all.

_DW_LBASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99,
             115, 131, 163, 195, 227, 258)
_DW_LEXT = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)
_DW_DBASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025,
             1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577)
_DW_DEXT = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12,
            13, 13)
_DW_CLORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)
_dw_fixed_t = None


@micropython.native
def _dw_getbits(st, src, n):
    """n bits, least significant first. st = [byte position, bit buffer, bit count]."""
    pos = st[0]
    buf = st[1]
    cnt = st[2]
    while cnt < n:
        buf |= src[pos] << cnt
        pos += 1
        cnt += 8
    st[0] = pos
    st[1] = buf >> n
    st[2] = cnt - n
    return buf & ((1 << n) - 1)


@micropython.native
def _dw_hdecode(st, src, count, symbol):
    """One Huffman symbol (canonical code given by count/symbol lists)."""
    pos = st[0]
    buf = st[1]
    cnt = st[2]
    code = first = index = 0
    for ln in range(1, 16):
        if cnt == 0:
            buf = src[pos]
            pos += 1
            cnt = 8
        code |= buf & 1
        buf >>= 1
        cnt -= 1
        c = count[ln]
        if code - c < first:
            st[0] = pos
            st[1] = buf
            st[2] = cnt
            return symbol[index + code - first]
        index += c
        first = (first + c) << 1
        code <<= 1
    raise ValueError('bad compressed picture data')


def _dw_htable(lengths, n):
    count = [0] * 16
    for s in range(n):
        count[lengths[s]] += 1
    count[0] = 0
    offs = [0] * 16
    for ln in range(1, 15):
        offs[ln + 1] = offs[ln] + count[ln]
    symbol = [0] * n
    for s in range(n):
        ln = lengths[s]
        if ln:
            symbol[offs[ln]] = s
            offs[ln] += 1
    return count, symbol


@micropython.native
def _dw_codes(st, src, out, o, lc, ls, dc, ds):
    """Decode one compressed block into out from position o; returns the new position."""
    lbase = _DW_LBASE
    lext = _DW_LEXT
    dbase = _DW_DBASE
    dext = _DW_DEXT
    while True:
        sym = _dw_hdecode(st, src, lc, ls)
        if sym < 256:
            out[o] = sym
            o += 1
        elif sym == 256:
            return o
        else:
            sym -= 257
            ln = lbase[sym] + _dw_getbits(st, src, lext[sym])
            d = _dw_hdecode(st, src, dc, ds)
            s = o - dbase[d] - _dw_getbits(st, src, dext[d])
            for _ in range(ln):
                out[o] = out[s]
                o += 1
                s += 1


def _dw_inflate(src, out):
    """Decompress zlib data src into out (a bytearray/memoryview of the exact
    size). Returns the number of bytes written."""
    global _dw_fixed_t
    if (src[0] & 15) != 8 or src[1] & 0x20 or ((src[0] << 8) | src[1]) % 31:
        raise ValueError('picture data is not zlib')
    st = [2, 0, 0]
    o = 0
    while True:
        last = _dw_getbits(st, src, 1)
        kind = _dw_getbits(st, src, 2)
        if kind == 0:                                 # stored block
            st[1] = st[2] = 0
            p = st[0]
            ln = src[p] | (src[p + 1] << 8)
            p += 4
            out[o:o + ln] = src[p:p + ln]
            o += ln
            st[0] = p + ln
        elif kind == 1:                               # fixed Huffman codes
            if _dw_fixed_t is None:
                _dw_fixed_t = (_dw_htable([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8, 288),
                               _dw_htable([5] * 30, 30))
            (lc, ls), (dc, ds) = _dw_fixed_t
            o = _dw_codes(st, src, out, o, lc, ls, dc, ds)
        elif kind == 2:                               # dynamic Huffman codes
            nlen = _dw_getbits(st, src, 5) + 257
            ndist = _dw_getbits(st, src, 5) + 1
            ncode = _dw_getbits(st, src, 4) + 4
            lens = [0] * 19
            for i in range(ncode):
                lens[_DW_CLORDER[i]] = _dw_getbits(st, src, 3)
            cc, cs = _dw_htable(lens, 19)
            lens = [0] * (nlen + ndist)
            i = 0
            while i < nlen + ndist:
                sym = _dw_hdecode(st, src, cc, cs)
                if sym < 16:
                    lens[i] = sym
                    i += 1
                    continue
                if sym == 16:
                    prev, rep = lens[i - 1], 3 + _dw_getbits(st, src, 2)
                elif sym == 17:
                    prev, rep = 0, 3 + _dw_getbits(st, src, 3)
                else:
                    prev, rep = 0, 11 + _dw_getbits(st, src, 7)
                for _ in range(rep):
                    lens[i] = prev
                    i += 1
            lc, ls = _dw_htable(lens[:nlen], nlen)
            dc, ds = _dw_htable(lens[nlen:], ndist)
            o = _dw_codes(st, src, out, o, lc, ls, dc, ds)
        else:
            raise ValueError('bad compressed picture data')
        if last:
            return o


def _dw_icon_blocks(slot):
    """32 KB flash blocks of slot's thumbnail (1 block) and large view (3 blocks)."""
    b = _DW_LIB_ID * 8
    return b + slot, b + 1 + 3 * slot


_DW_ZZ = bytes((0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48,
                41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15,
                23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63))
_DW_QL = bytes((16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40,
                57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24,
                35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98,
                112, 100, 103, 99))
_DW_QC = bytes((17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99,
                99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99) + (99,) * 32)
_DW_DC_BITS = (bytes((0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)),
               bytes((0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)))
_DW_DC_VALS = bytes(range(12))
_DW_AC_BITS = (bytes((0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D)),
               bytes((0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77)))
_DW_AC_VALS = (bytes.fromhex(
    '01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a'
    '3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a9293'
    '9495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6'
    'e7e8e9eaf1f2f3f4f5f6f7f8f9fa'), bytes.fromhex(
    '000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a26'
    '2728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788'
    '898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3'
    'e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa'))


def _dw_huff(bits, vals):
    code, size = [0] * 256, [0] * 256
    c = k = 0
    for ln in range(1, 17):
        for _ in range(bits[ln - 1]):
            code[vals[k]] = c
            size[vals[k]] = ln
            c += 1
            k += 1
        c <<= 1
    return code, size


def _dw_qtable(base, quality):
    s = 5000 // quality if quality < 50 else 200 - 2 * quality
    return [min(255, max(1, (b * s + 50) // 100)) for b in base]


@micropython.native
def _dw_put(st, out, code, size):
    """Add size bits of code to the entropy stream written into out at st[2]
    (a 0xFF byte gets a 0x00 after it). IndexError when out is full."""
    acc = (st[0] << size) | code
    n = st[1] + size
    p = st[2]
    while n >= 8:
        n -= 8
        b = (acc >> n) & 0xFF
        out[p] = b
        p += 1
        if b == 0xFF:
            out[p] = 0
            p += 1
    st[0] = acc & ((1 << n) - 1)
    st[1] = n
    st[2] = p


@micropython.native
def _dw_fdct(d):
    """In-place 8x8 forward DCT (libjpeg 'islow' integer method, output x8)."""
    for i in range(0, 64, 8):
        t0 = d[i] + d[i + 7]; t7 = d[i] - d[i + 7]
        t1 = d[i + 1] + d[i + 6]; t6 = d[i + 1] - d[i + 6]
        t2 = d[i + 2] + d[i + 5]; t5 = d[i + 2] - d[i + 5]
        t3 = d[i + 3] + d[i + 4]; t4 = d[i + 3] - d[i + 4]
        t10 = t0 + t3; t13 = t0 - t3; t11 = t1 + t2; t12 = t1 - t2
        d[i] = (t10 + t11) << 2
        d[i + 4] = (t10 - t11) << 2
        z1 = (t12 + t13) * 4433
        d[i + 2] = (z1 + t13 * 6270 + 1024) >> 11
        d[i + 6] = (z1 - t12 * 15137 + 1024) >> 11
        z1 = t4 + t7; z2 = t5 + t6; z3 = t4 + t6; z4 = t5 + t7
        z5 = (z3 + z4) * 9633
        t4 *= 2446; t5 *= 16819; t6 *= 25172; t7 *= 12299
        z1 *= -7373; z2 *= -20995; z3 = z3 * -16069 + z5; z4 = z4 * -3196 + z5
        d[i + 7] = (t4 + z1 + z3 + 1024) >> 11
        d[i + 5] = (t5 + z2 + z4 + 1024) >> 11
        d[i + 3] = (t6 + z2 + z3 + 1024) >> 11
        d[i + 1] = (t7 + z1 + z4 + 1024) >> 11
    for i in range(8):
        t0 = d[i] + d[i + 56]; t7 = d[i] - d[i + 56]
        t1 = d[i + 8] + d[i + 48]; t6 = d[i + 8] - d[i + 48]
        t2 = d[i + 16] + d[i + 40]; t5 = d[i + 16] - d[i + 40]
        t3 = d[i + 24] + d[i + 32]; t4 = d[i + 24] - d[i + 32]
        t10 = t0 + t3; t13 = t0 - t3; t11 = t1 + t2; t12 = t1 - t2
        d[i] = (t10 + t11 + 2) >> 2
        d[i + 32] = (t10 - t11 + 2) >> 2
        z1 = (t12 + t13) * 4433
        d[i + 16] = (z1 + t13 * 6270 + 16384) >> 15
        d[i + 48] = (z1 - t12 * 15137 + 16384) >> 15
        z1 = t4 + t7; z2 = t5 + t6; z3 = t4 + t6; z4 = t5 + t7
        z5 = (z3 + z4) * 9633
        t4 *= 2446; t5 *= 16819; t6 *= 25172; t7 *= 12299
        z1 *= -7373; z2 *= -20995; z3 = z3 * -16069 + z5; z4 = z4 * -3196 + z5
        d[i + 56] = (t4 + z1 + z3 + 16384) >> 15
        d[i + 40] = (t5 + z2 + z4 + 16384) >> 15
        d[i + 24] = (t6 + z2 + z3 + 16384) >> 15
        d[i + 8] = (t7 + z1 + z4 + 16384) >> 15


@micropython.native
def _dw_block(d, q, prev, dcc, dcs, acc_, acs, st, out):
    """DCT, quantise (q = zigzag divisors x8) and Huffman-code one block.
    Returns the block's DC value."""
    _dw_fdct(d)
    zz = _DW_ZZ
    v = d[0]
    h = q[0] >> 1
    dc = (v + h) // q[0] if v >= 0 else -((h - v) // q[0])
    diff = dc - prev
    a = -diff if diff < 0 else diff
    nb = 0
    while a:
        nb += 1
        a >>= 1
    _dw_put(st, out, dcc[nb], dcs[nb])
    if nb:
        _dw_put(st, out, diff if diff > 0 else diff + (1 << nb) - 1, nb)
    run = 0
    for k in range(1, 64):
        qq = q[k]
        v = d[zz[k]]
        v = (v + (qq >> 1)) // qq if v >= 0 else -(((qq >> 1) - v) // qq)
        if v == 0:
            run += 1
            continue
        while run > 15:
            _dw_put(st, out, acc_[0xF0], acs[0xF0])
            run -= 16
        a = -v if v < 0 else v
        nb = 0
        while a:
            nb += 1
            a >>= 1
        s = (run << 4) | nb
        _dw_put(st, out, acc_[s], acs[s])
        _dw_put(st, out, v if v > 0 else v + (1 << nb) - 1, nb)
        run = 0
    if run:
        _dw_put(st, out, acc_[0], acs[0])
    return dc


@micropython.native
def _dw_row(pix, ra, rb, wy, xa, xb, wx, tw, out):
    """One target row (bilinear between source rows ra, rb; indexes in pixels)
    as RGB bytes, read straight from the RGB565 pixels (no colour planes, so a
    save needs no extra 51 KB)."""
    iy = 256 - wy
    j = 0
    for t in range(tw):
        w = wx[t]
        iw = 256 - w
        r = g = b = 0
        for k in range(4):
            if k == 0:
                p = 2 * (ra + xa[t]); f = iw * iy
            elif k == 1:
                p = 2 * (ra + xb[t]); f = w * iy
            elif k == 2:
                p = 2 * (rb + xa[t]); f = iw * wy
            else:
                p = 2 * (rb + xb[t]); f = w * wy
            c = (pix[p] << 8) | pix[p + 1]
            r += (((c >> 8) & 0xF8) | (c >> 13)) * f
            g += (((c >> 3) & 0xFC) | ((c >> 9) & 3)) * f
            b += (((c << 3) & 0xF8) | ((c >> 2) & 7)) * f
        out[j] = r >> 16
        out[j + 1] = g >> 16
        out[j + 2] = b >> 16
        j += 3


@micropython.native
def _dw_ycc(rows, x3, Y, U, V):
    """8x8 pixels starting at byte x3 of the 8 RGB rows -> level-shifted Y, Cb, Cr."""
    k = 0
    for r in range(8):
        row = rows[r]
        j = x3
        for _ in range(8):
            R = row[j]; G = row[j + 1]; B = row[j + 2]
            Y[k] = ((77 * R + 150 * G + 29 * B + 128) >> 8) - 128
            U[k] = (-43 * R - 85 * G + 128 * B + 128) >> 8
            V[k] = (128 * R - 107 * G - 21 * B + 128) >> 8
            k += 1
            j += 3


def _dw_scale_axis(src, dst):
    """Bilinear sample positions: lists (index0, index1, weight 0-255)."""
    i0, i1, w = [0] * dst, [0] * dst, [0] * dst
    for t in range(dst):
        f = ((2 * t + 1) * src * 256) // (2 * dst) - 128
        if f < 0:
            f = 0
        a = f >> 8
        i0[t] = a
        i1[t] = a + 1 if a + 1 < src else a
        w[t] = f & 255
    return i0, i1, w


def _dw_jpeg_steps(pix, sw, sh, tw, th, quality, sink):
    """Generator: encode the RGB planes scaled to tw x th (multiples of 8) as a
    baseline 4:4:4 JPEG in DWIN icon-record form: w, h, header length, scan
    length (10 bytes) + JPEG whose SOS segment and scan are zero-padded so the
    scan starts and ends 4-byte aligned. The record goes to the generator
    function sink(data, offset) in 4 KB pieces as it is made, the 10-byte
    header last. Yields after every row of blocks; returns the record length."""
    out = _dw_workbuf()                               # small working buffer (reused)
    if tw % 8 or th % 8:
        raise ValueError('JPEG size must be a multiple of 8')
    ql, qc = _dw_qtable(_DW_QL, quality), _dw_qtable(_DW_QC, quality)
    zz = _DW_ZZ
    qlz = [ql[zz[k]] * 8 for k in range(64)]
    qcz = [qc[zz[k]] * 8 for k in range(64)]
    dcl, acl = _dw_huff(_DW_DC_BITS[0], _DW_DC_VALS), _dw_huff(_DW_AC_BITS[0], _DW_AC_VALS[0])
    dcc, acc = _dw_huff(_DW_DC_BITS[1], _DW_DC_VALS), _dw_huff(_DW_AC_BITS[1], _DW_AC_VALS[1])
    hd = bytearray(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
    for tid, qt in ((0, ql), (1, qc)):
        hd += bytes((0xFF, 0xDB, 0, 67, tid)) + bytes([qt[zz[k]] for k in range(64)])
    hd += bytes((0xFF, 0xC0, 0, 17, 8, th >> 8, th & 255, tw >> 8, tw & 255,
                 3, 1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1))
    for tc, bits, vals in ((0x00, _DW_DC_BITS[0], _DW_DC_VALS), (0x10, _DW_AC_BITS[0], _DW_AC_VALS[0]),
                           (0x01, _DW_DC_BITS[1], _DW_DC_VALS), (0x11, _DW_AC_BITS[1], _DW_AC_VALS[1])):
        ln = 19 + len(vals)
        hd += bytes((0xFF, 0xC4, ln >> 8, ln & 255, tc)) + bits + vals
    pad = (-(10 + len(hd) + 14)) % 4                  # SOS padding for 4-byte aligned scan data
    hd += bytes((0xFF, 0xDA, 0, 12 + pad, 3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0)) + bytes(pad)
    hl = len(hd)
    out[10:10 + hl] = hd
    del hd
    xa, xb, wx = _dw_scale_axis(sw, tw)
    ya, yb, wy = _dw_scale_axis(sh, th)
    rows = [bytearray(3 * tw) for _ in range(8)]
    Y, U, V = [0] * 64, [0] * 64, [0] * 64
    st = [0, 0, 10 + hl]                              # bit buffer, bit count, write position
    sent = 0                                          # record bytes already given to sink
    py = pu = pv = 0
    for by in range(th // 8):
        for r in range(8):
            t = by * 8 + r
            _dw_row(pix, ya[t] * sw, yb[t] * sw, wy[t], xa, xb, wx, tw, rows[r])
        for bx in range(tw // 8):
            _dw_ycc(rows, bx * 24, Y, U, V)
            py = _dw_block(Y, qlz, py, dcl[0], dcl[1], acl[0], acl[1], st, out)
            pu = _dw_block(U, qcz, pu, dcc[0], dcc[1], acc[0], acc[1], st, out)
            pv = _dw_block(V, qcz, pv, dcc[0], dcc[1], acc[0], acc[1], st, out)
            if st[2] >= 4096:
                yield from sink(memoryview(out)[:4096], sent)
                sent += 4096
                rest = st[2] - 4096
                out[0:rest] = out[4096:st[2]]
                st[2] = rest
        yield
    if st[1]:
        _dw_put(st, out, (1 << (8 - st[1])) - 1, 8 - st[1])     # pad the last byte with 1s
    p = st[2]
    out[p] = 0xFF
    out[p + 1] = 0xD9
    p += 2
    while (sent + p - 10 - hl) % 4:                   # scan length a multiple of 4
        out[p] = 0
        p += 1
    yield from sink(memoryview(out)[:p], sent)
    total = sent + p
    yield from sink(_dw_struct.pack('>HHHI', tw, th, hl, total - 10 - hl), 0)
    return total


def _dw_workbuf():
    """8 KB working buffer for the JPEG encoder: the compressed-data buffer,
    which is idle while saving (so a save allocates no large block)."""
    global _dw_ebuf
    if _dw_zbuf is not None and len(_dw_zbuf) >= 8192:
        return memoryview(_dw_zbuf)[:8192]
    if _dw_ebuf is None:
        _dw_ebuf = bytearray(8192)
    return memoryview(_dw_ebuf)


def _dw_stage_steps(vp, data):
    """Generator: copy bytes into VP memory starting at vp (240-byte frames)."""
    n = len(data)
    for i in range(0, n, 240):
        c = data[i:i + 240]
        if len(c) & 1:
            c = bytes(c) + b'\x00'
        _dw_vp(vp + i // 2, c)
        if not (i // 240) % 16:
            yield


def _dw_flash_block_steps(block, vp):
    """Generator: write the 32 KB staged at VP vp into 32 KB block 'block' of
    the display's 16 MB flash (system variable 0x00AA, mode 0x02)."""
    _dw_vp(0x00AA, bytes((0x5A, 0x02, block >> 8, block & 0xFF, vp >> 8, vp & 0xFF, 0, 20, 0, 0, 0, 0)))
    t0 = time.ticks_ms()
    while True:
        s = _dw_read(0x00AA, 1)
        if s is not None and s[0] >> 8 == 0:          # display clears the start byte when done
            break
        if time.ticks_diff(time.ticks_ms(), t0) > 10000:
            raise OSError('DWIN flash write did not finish')
        yield
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 50:   # settle before the staging area is reused
        yield


def _dw_flash_sink(block0, cap, state):
    """sink for _dw_jpeg_steps that streams a record into flash blocks
    block0 .. block0+cap-1. Block 0 of the record is staged in region A and
    written last (its header comes last); later blocks go through region B,
    each written as soon as the next one starts. state = [block in region B]."""
    def sink(data, roff):
        n = len(data)
        if roff + n > cap * 32768:
            raise IndexError('icon larger than its flash space')
        i = 0
        while i < n:
            b, o = divmod(roff + i, 32768)
            k = min(n - i, 32768 - o)
            if b == 0:
                base = _DW_STAGE_A
            else:
                if state[0] != b:
                    if state[0] > 0:
                        yield from _dw_flash_block_steps(block0 + state[0], _DW_STAGE_B)
                    state[0] = b
                base = _DW_STAGE_B
            yield from _dw_stage_steps(base + o // 2, data[i:i + k])
            i += k
    return sink


def _dw_screen_pixels_steps():
    """Generator: rebuild (w, h, pixels) from the dot lists in VP memory (slow,
    ~10 s); used when the picture on page 39 was not drawn by dwin_image."""
    counts = [_dw_read(vp + 1, 1) for vp, _ in _DW_REGIONS]
    first = _dw_read(_DW_REGIONS[0][0] + 2, 2)
    if None in counts or first is None or not counts[0][0]:
        raise ValueError('no picture on the image page')
    x0, y0 = first                                    # layout of _dw_rows: centred, 3 px apart
    w = (480 - 2 * x0) // 3
    n = counts[0][0] + counts[1][0]
    h = n // w
    pix = _dw_pixels(2 * w * h)
    for (vp, _), cnt in zip(_DW_REGIONS, counts):
        total, done, addr = 3 * cnt[0], 0, vp + 2
        while done < total:
            k = min(120, total - done)              # multiple of 3: whole dots per read
            a = _dw_read(addr + done, k)
            if a is None:
                raise OSError('display did not answer')
            for d in range(0, k, 3):
                p = ((a[d + 1] - y0) // 3) * w + (a[d] - x0) // 3
                if 0 <= p < w * h:
                    pix[2 * p] = a[d + 2] >> 8
                    pix[2 * p + 1] = a[d + 2] & 0xFF
            done += k
            yield
    return w, h, pix


def _dw_pages_steps(slot):
    """Generator: write slot's thumbnail and large view into the display's
    picture library, then restore page 39 from the saved slot."""
    global _dw_last
    gc.collect()
    if _dw_last is None:
        _dw_last = yield from _dw_screen_pixels_steps()
    w, h, pix = _dw_last
    for vp, _ in _DW_REGIONS:                          # page 39 draws nothing while staging
        _dw_vp(vp, _dw_struct.pack('>HH', 1, 0))
    tb, vb = _dw_icon_blocks(slot)
    for (tw, th), blk, cap in ((_DW_THUMB, tb, 1), (_DW_VIEW, vb, 3)):
        q = _DW_QUALITY
        while True:
            state = [0]
            try:
                yield from _dw_jpeg_steps(pix, w, h, tw, th, q, _dw_flash_sink(blk, cap, state))
                break
            except IndexError:                        # too detailed for its space: lower quality
                if q <= 40:
                    raise ValueError('picture too detailed for the icon space')
                q -= 15
        if state[0] > 0:
            yield from _dw_flash_block_steps(blk + state[0], _DW_STAGE_B)
        yield from _dw_flash_block_steps(blk, _DW_STAGE_A)
    base = _dw_slot_base(slot)                         # staging overwrote page 39's dots
    yield from _dw_db(0x5A, base + 4, _DW_REGIONS[0][0], _DW_SLOT_A)
    yield from _dw_db(0x5A, base + 4 + _DW_SLOT_A, _DW_REGIONS[1][0], _DW_SLOT_B)


# ---- video (uploaded from Blockly, played by the display itself) -------------
# The Blockly page sends the clip as an icon library (240 x 160 JPEG frames) to
# the display's flash, font ID 49 (main.py "DWV" transfer). Page 44 (VIDEO) of
# the SD-card project plays icons 0-255 with an Animation Icon control, 10
# frames per second, repeating, while VP 0x5210 is 0 (its value after power-on).
#   SYNC : dwin_video_play()        dwin_video_stop()
#   ASYNC: async_dwin_video_play()  async_dwin_video_stop()

_DW_VIDEO_PAGE = 44
_DW_VIDEO_VP = 0x5210


def dwin_video_play():
    """Show the VIDEO page and play the uploaded video (it repeats)."""
    _dw_vp(_DW_VIDEO_VP, b'\x00\x00')
    dwin_page(_DW_VIDEO_PAGE)

async def async_dwin_video_play():
    dwin_video_play()
    await asyncio.sleep_ms(0)


def dwin_video_stop():
    """Stop the video; its first picture stays on the screen."""
    _dw_vp(_DW_VIDEO_VP, b'\x00\x01')

async def async_dwin_video_stop():
    dwin_video_stop()
    await asyncio.sleep_ms(0)


# ---- live gesture results on AI PROJECTS > GESTURE CLASSIFICATION ------------
# A camera (K230) sends lines like "Detected: four (100.0%)" on a UART (UART7
# on the R4 board, 115200). Page 55 of the SD-card project has a Basic Graphic
# control (dot list at VP 0x5400, like the image page): the board draws the
# gesture name, the confidence and the last line received as dots with its own
# 6 x 11 font. (The project's font file 0_ASCII_12x24.bin does not draw, so
# text-display controls stay empty on this display.)
#   SYNC : dwin_gesture_live()        (runs until the program is stopped)
#   ASYNC: async_dwin_gesture_live()

_DW_GESTURE_PAGE = 55
_DW_GESTURE_VP = 0x5400                            # dot list: command + count, x/y/colour per dot
_DW_GESTURE_MAX = 1100                             # dots that fit below the project's VPs (0x6100)
_DW_FONT_W, _DW_FONT_H = 6, 11                     # ASCII 32-126, one byte per row, bit 5 = left column
_DW_FONT_HEX = (
    '000000000000000000000000000018181818001800000000001414140000000000000014'
    '143e14143e14140000081e323c1e06363c08000000382a3c081e2a0e00000000001c3018'
    '3e2c3e000000000c08100000000000000000040818181818080400000010080c0c0c0c08'
    '10000000083c1824000000000000000008083e080800000000000000000000000c081000'
    '000000003e00000000000000000000000000180000000002020404080810100000001c36'
    '363636361c000000000c3c0c0c0c0c3f000000001c36060c18363e000000001c36061c06'
    '361c00000000060e16363f0606000000003e303c3606263c000000001c36303c36361c00'
    '0000003e36060c0c1818000000001c36361c36361c000000001c36361e06361c00000000'
    '00000018000018000000000000001800001810200000000c1830180c000000000000003c'
    '003c00000000000000180c060c180000000000001c260c180018000000001c32262a2a27'
    '301c000000003c1c143e363700000000003c363c36363c00000000001e363030361c0000'
    '0000003c363636363c00000000003e303c30363e00000000003e303c3030380000000000'
    '1c36303e361e000000000037363e36363700000000003c181818183c00000000001e0c0c'
    '2c2c3800000000003634383c363b000000000038303030363e00000000002236363e2a2a'
    '0000000000373a3a36363200000000001c363636361c00000000003c36363c3038000000'
    '00001c363636361c06000000003c36363c363b00000000001e323c0e263c00000000003e'
    '1a1818183c000000000037363636361c00000000003736141c1c0800000000002b2a2a3e'
    '1c140000000000331e0c0c1e33000000000033331e0c0c1e00000000003e360c18363e00'
    '0000001c1818181818181c00000020201010080804040000001c0c0c0c0c0c0c1c000000'
    '081c36000000000000000000000000000000003f0000180804000000000000000000001c'
    '361e363f0000000030303c3636363c0000000000001c3630361c000000000e061e363636'
    '1f0000000000001c363e301e000000000e183e1818183e0000000000001b3636361e063c'
    '000030303c36363636000000000c003c0c0c0c3f000000000c003c0c0c0c0c0c38000030'
    '30363c383c37000000003c0c0c0c0c0c3f0000000000003c3e2a2a2a0000000000002c36'
    '3636360000000000001c3636361c0000000000003c3636363c3038000000001b3636361e'
    '060f00000000371d18183c0000000000001e381e073e0000000018183e18181b0e000000'
    '000000363636361f00000000000036361c1c080000000000002b2a3e1e14000000000000'
    '3b1e0c1e37000000000000373636141c1830000000003e2c18363e00000000060c0c180c'
    '0c0c0600000000080808080808080000003018180c1818183000000000001a2c00000000'
    '00'
)
_dw_font = None
_dw_gesture_buf = None
_dw_gesture_state = ['', '', '']                   # name, confidence, line


def dwin_text(vp, text, length):
    """Write text into a display text field of 'length' bytes (ASCII, zero-padded)."""
    b = str(text).encode()[:length]
    _dw_vp(vp, b + bytes(length - len(b)))


def _dw_text_dots(buf, n, text, x, y, step, colour):
    """Add text to the dot list in buf (n dots so far); each font pixel is one
    dot, 'step' pixels apart. Returns the new dot count."""
    global _dw_font
    if _dw_font is None:
        _dw_font = _dw_ba.unhexlify(''.join(_DW_FONT_HEX))
    f = _dw_font
    for ch in text:
        c = ord(ch) - 32
        if 0 < c < 95:
            g = c * _DW_FONT_H
            for r in range(_DW_FONT_H):
                bits = f[g + r]
                col = 0
                while bits and col < _DW_FONT_W:
                    if bits & (32 >> col) and n < _DW_GESTURE_MAX:
                        _dw_struct.pack_into('>HHH', buf, n * 6, x + col * step, y + r * step, colour)
                        n += 1
                    col += 1
        x += _DW_FONT_W * step
        if x > 470:
            break
    return n


def _dw_gesture_show(name, conf, line):
    """Redraw the live panel; None keeps that part as it is."""
    global _dw_gesture_buf
    st = _dw_gesture_state
    for i, t in enumerate((name, conf, line)):
        if t is not None:
            st[i] = str(t)
    if _dw_gesture_buf is None:
        _dw_gesture_buf = bytearray(6 * _DW_GESTURE_MAX)
    buf = _dw_gesture_buf
    n = _dw_text_dots(buf, 0, st[0][:12], 24, 240, 3, 0xF4E1)      # gesture, orange, 3x
    n = _dw_text_dots(buf, n, st[1][:8], 300, 240, 3, 0x1947)      # confidence, ink, 3x
    n = _dw_text_dots(buf, n, st[2][:36], 24, 282, 2, 0x63B1)      # last line, grey, 2x
    vp = _DW_GESTURE_VP + 2
    mv = memoryview(buf)
    for i in range(0, n * 6, 120):                                   # 20 dots per frame
        _dw_vp(vp + i // 2, mv[i:min(n * 6, i + 120)])
    _dw_vp(vp + n * 3, b'\xff\xff')                                 # end of the list
    _dw_vp(_DW_GESTURE_VP, _dw_struct.pack('>HH', 1, n))              # draw-dots command + count


def _dw_gesture_parse(text):
    """'Detected: four (100.0%)' -> ('FOUR', '100.0%'); 'not detected' ->
    ('NOT DETECTED', ''); None if not a result."""
    if text.lower().startswith('not detected'):
        return 'NOT DETECTED', ''
    i = text.find('Detected:')
    if i < 0:
        return None
    rest = text[i + 9:].strip()
    j = rest.find('(')
    if j < 0:
        return rest.upper(), ''
    return rest[:j].strip().upper(), rest[j + 1:].replace(')', '').strip()


def _dw_gesture_steps(uart_id, baud):
    """Generator behind dwin_gesture_live: one step per poll."""
    u = UART(uart_id, baud, timeout=0, rxbuf=2048)
    dwin_page(_DW_GESTURE_PAGE)
    _dw_gesture_show('waiting...', '', 'listening on UART%d, %d baud' % (uart_id, baud))
    buf = b''
    shown = None
    t_line = time.ticks_ms()
    while True:
        n = u.any()
        if n:
            buf += u.read(n)
            if len(buf) > 1024:
                buf = buf[-256:]
            while b'\n' in buf:
                raw, buf = buf.split(b'\n', 1)
                try:
                    text = raw.decode().strip()
                except Exception:
                    text = ''
                if not text:
                    continue
                res = _dw_gesture_parse(text)
                if res is not None and res != shown:
                    _dw_gesture_show(res[0], res[1], None)
                    shown = res
                if time.ticks_diff(time.ticks_ms(), t_line) > 1000:    # raw line at most once a second
                    _dw_gesture_show(None, None, text)
                    t_line = time.ticks_ms()
        yield


def dwin_gesture_live(uart_id=7, baud=115200):
    """Show the gesture results arriving on a UART live on the GESTURE page."""
    for _ in _dw_gesture_steps(uart_id, baud):
        time.sleep_ms(20)

async def async_dwin_gesture_live(uart_id=7, baud=115200):
    for _ in _dw_gesture_steps(uart_id, baud):
        await asyncio.sleep_ms(20)


# ---- Wi-Fi & Bluetooth status / scan / connect for SETTINGS (page 56) --------
# Uses iot_bus + dwin_get_data to talk to the ESP32-S3 gateway over UART6 and
# update the DWIN Settings VPs (0x5300 Wi-Fi, 0x5320 Bluetooth, 0x5340 Firmware).

def dwin_wifi_scan():
    """Scan available Wi-Fi networks on the ESP32 gateway and update Settings."""
    import dwin_get_data
    return dwin_get_data.scan_wifi()

async def async_dwin_wifi_scan():
    res = dwin_wifi_scan()
    await asyncio.sleep_ms(0)
    return res


def dwin_wifi_connect(ssid, password='', force=False):
    """Connect ESP32 gateway to Wi-Fi network `ssid` and update Settings."""
    import dwin_get_data
    return dwin_get_data.connect_wifi(ssid, password, force=force)

async def async_dwin_wifi_connect(ssid, password='', force=False):
    res = dwin_wifi_connect(ssid, password, force=force)
    await asyncio.sleep_ms(0)
    return res


def dwin_wifi_disconnect(forget=False):
    """Disconnect ESP32 gateway from Wi-Fi and update Settings."""
    import dwin_get_data
    return dwin_get_data.disconnect_wifi(forget=forget)

async def async_dwin_wifi_disconnect(forget=False):
    res = dwin_wifi_disconnect(forget=forget)
    await asyncio.sleep_ms(0)
    return res


def dwin_wifi_status(query=True):
    """Check Wi-Fi status from the ESP32 gateway and update Settings."""
    import iot_bus, dwin_get_data
    res = iot_bus.wifi_status(query=query)
    dwin_get_data.refresh(force=True)
    return res

async def async_dwin_wifi_status(query=True):
    res = dwin_wifi_status(query=query)
    await asyncio.sleep_ms(0)
    return res


def dwin_ble_status(query=True):
    """Check Bluetooth LE status from the ESP32 gateway and update Settings."""
    import iot_bus, dwin_get_data
    res = iot_bus.ble_status(query=query)
    dwin_get_data.refresh(force=True)
    return res

async def async_dwin_ble_status(query=True):
    res = dwin_ble_status(query=query)
    await asyncio.sleep_ms(0)
    return res


def dwin_settings_refresh(query=False):
    """Refresh the DWIN Settings page (page 56) Wi-Fi, Bluetooth, and Firmware fields."""
    import dwin_get_data
    if query:
        return dwin_get_data.check_status(query=True)
    return dwin_get_data.refresh(force=True)

async def async_dwin_settings_refresh(query=False):
    res = dwin_settings_refresh(query=query)
    await asyncio.sleep_ms(0)
    return res


# ---- small animation from Blockly (stored in user.py like a picture) ---------
# The "play animation" block packs up to 16 frames of 160 x 104 into an icon
# library (made in the browser with the video encoder) and puts it into
# user.py as hex:  anim = ('tag', nbytes, ('<4096 hex chars>', ...))
# The first run writes the library into the display's flash (font ID 28,
# 32 KB blocks via VP 0x00AA, staged in VP 0x1002); then page 66 (ANIMATION,
# Animation Icon control at VP 0x5220) plays it by itself, looping. Later runs
# with the same animation skip the copy (its tag is kept in dwin_anim.txt).
#   SYNC : dwin_anim(anim)        ASYNC: async_dwin_anim(anim)
# Animation memories 1-3 (like the picture memories): font IDs 29-31, pages
# 67-69 play them (VP 0x5222/0x5224/0x5226), page 70 ANIMATIONS shows all three.
#   SYNC : dwin_anim_save(slot, anim)        dwin_anim_show(slot)
#   ASYNC: async_dwin_anim_save(slot, anim)  async_dwin_anim_show(slot)

_DW_ANIM_PAGE = 66
_DW_ANIM_VP = 0x5220
_DW_ANIM_BLOCK = 28 * 8                            # first 32 KB block of font ID 28
_DW_ANIM_MARK = 'dwin_anim.txt'                    # JSON: which tag each place holds


def _dw_anim_marks():
    try:
        with open(_DW_ANIM_MARK) as f:
            s = f.read()
    except OSError:
        return {}
    try:
        import json
        m = json.loads(s)
        return m if isinstance(m, dict) else {}
    except ValueError:
        return {'play': s}                         # first version kept only the tag


def _dw_anim_place(slot):
    """(mark key, first flash block, VP, page) of the play block (slot 0) or memory 1-3."""
    if slot:
        return str(slot), (28 + slot) * 8, _DW_ANIM_VP + 2 * slot, _DW_ANIM_PAGE + slot
    return 'play', _DW_ANIM_BLOCK, _DW_ANIM_VP, _DW_ANIM_PAGE


def _dw_anim_steps(anim, slot=0, show=True):
    tag, nbytes, parts = anim
    key, first, vp, page = _dw_anim_place(slot)
    marks = _dw_anim_marks()
    if marks.get(key) != tag:
        dwin_page(10)                               # leave the page that shows the library
        for vp, _ in _DW_REGIONS:                   # page 39 must not draw the staged data
            _dw_vp(vp, _dw_struct.pack('>HH', 1, 0))
        per = 16                                    # 2 KB hex pieces per 32 KB block
        blocks = (nbytes + 32767) // 32768
        for b in list(range(1, blocks)) + [0]:      # header block last
            off = 0
            for p in parts[b * per:(b + 1) * per]:
                data = _dw_ba.unhexlify(p)
                yield from _dw_stage_steps(_DW_STAGE_A + off // 2, data)
                off += len(data)
            yield from _dw_flash_block_steps(first + b, _DW_STAGE_A)
        marks[key] = tag
        try:
            import json
            with open(_DW_ANIM_MARK, 'w') as f:
                f.write(json.dumps(marks))
        except OSError:
            pass
    if show:
        _dw_vp(vp, b'\x00\x00')                    # 0 = play
        dwin_page(page)


def dwin_anim(anim):
    """Play a small animation from the 'play animation' block (copied to the display first if new)."""
    for _ in _dw_anim_steps(anim):
        pass

async def async_dwin_anim(anim):
    for _ in _dw_anim_steps(anim):
        await asyncio.sleep_ms(0)


def dwin_anim_save(slot, anim):
    """Save an animation into animation memory 1-3 (skipped if it is already there)."""
    for _ in _dw_anim_steps(anim, max(1, min(3, slot)), False):
        pass

async def async_dwin_anim_save(slot, anim):
    for _ in _dw_anim_steps(anim, max(1, min(3, slot)), False):
        await asyncio.sleep_ms(0)


def dwin_anim_show(slot):
    """Play animation memory 1-3 at once (it is already inside the display)."""
    _, _, vp, page = _dw_anim_place(max(1, min(3, slot)))
    _dw_vp(vp, b'\x00\x00')
    dwin_page(page)

async def async_dwin_anim_show(slot):
    dwin_anim_show(slot)
    await asyncio.sleep_ms(0)

