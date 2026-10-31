"""LLM CHAT on the DWIN display: type a question, the AI answers.

Pages (SD card, dwin/make_sd_card.py):
  97      home page 3 (LLM CHAT card)
  98      conversation, drawn here as dots at DOTS_VP; UP / DOWN / CLEAR keys,
          ASK opens the keyboard (a page change, no code)
  99      question keyboard (100 = the same keys pressed), text at KB_DOTS_VP
Keys are DWIN return keys writing into KEY_VP:
  0x0802 UP   0x0803 DOWN   0x0804 CLEAR                        (page 98)
  0x20-0x7E character   0x0008 DEL   0x0805 CLEAR   0x000D SEND (page 99)
dwin_wifi_ui.poll() calls poll() while a chat page is on screen (no program
running) and while an answer is awaited. The API (link, key, model) is set in
lib.py: LLM_URL, LLM_KEY, LLM_MODEL; lib.async__llm_ask() lets a program ask
too and shows the exchange here.
DOTS_VP / KB_DOTS_VP lie in the image page's region A (page 39), unused while
these pages show; both lists are emptied when the chat pages are left.
"""
import gc
import struct
import time

PAGE_CHAT, PAGE_KB, PAGE_KB_PRESSED = 98, 99, 100
PAGES = (PAGE_CHAT, PAGE_KB, PAGE_KB_PRESSED)
KEY_VP = 0x5F90
DOTS_VP, DOTS_MAX = 0x1000, 4200                 # ends 0x413A
KB_DOTS_VP, KB_DOTS_MAX = 0x4200, 1500           # ends 0x5396, below the 0x5400 dot area
REQ_ID = 75
X0, Y0, LINE_H, ROWS, COLS = 16, 58, 25, 8, 36   # conversation text (12 x 22 px characters)
Q_X, Q_Y, Q_LINE_H, Q_ROWS, Q_MAX = 20, 59, 22, 3, 120
KEEP = 6                                         # log entries kept (3 questions + answers)
LINE_DOTS = 1000                                 # one line: 36 characters x at most 27 dots

INK, MUTED, BLUE, RED = 0x1947, 0x63B1, 0x2B7F, 0xD0A3

_log = []        # [kind, text]: 'q' question, 'w' waiting, 'a' answer, 'e' error
_q = ""
_scroll = 0      # lines scrolled up from the newest
_t0 = None       # waiting for reply REQ_ID since
_page = None
_shown = False   # our dot lists are in the display's memory
_buf = None
_font = None


def _dw():
    import dwin_screen
    return dwin_screen


def _lib():
    import lib
    return lib


def _wrap(text, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            while len(word) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:width])
                word = word[width:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out


def _dots(buf, n, cap, text, x, y, colour):
    """Add text to the dot list (each font pixel one dot, 2 px apart)."""
    global _font
    dw = _dw()
    if _font is None:
        _font = dw._dw_font
    if _font is None:                   # one string: ''.join() of it char by char needs 16 KB
        h = dw._DW_FONT_HEX
        _font = dw._dw_ba.unhexlify(h if isinstance(h, str) else ''.join(h))
        dw._dw_font = _font
    f, h, w = _font, dw._DW_FONT_H, dw._DW_FONT_W
    for ch in text:
        c = ord(ch) - 32
        if 0 < c < 95:
            g = c * h
            for r in range(h):
                bits = f[g + r]
                if bits:
                    for col in range(w):
                        if bits & (32 >> col):
                            if n >= cap:
                                return n
                            struct.pack_into('>HHH', buf, n * 6, x + col * 2, y + r * 2, colour)
                            n += 1
        x += w * 2
    return n


def _draw(vp, cap, items):
    """Write items [(text, x, y, colour), ...] as one dot list at vp. Each
    line goes out as soon as it is drawn, so the buffer only holds one line
    (one big buffer does not fit the board's heap next to lib)."""
    global _buf, _shown
    if _buf is None:
        gc.collect()
        _buf = bytearray(6 * LINE_DOTS)
    dw = _dw()
    mv = memoryview(_buf)
    total = 0
    for text, x, y, colour in items:
        k = _dots(_buf, 0, min(LINE_DOTS, cap - total), text, x, y, colour)
        for i in range(0, k * 6, 240):
            dw._dw_vp(vp + 2 + total * 3 + i // 2, mv[i:min(k * 6, i + 240)])
        total += k
    dw._dw_vp(vp + 2 + total * 3, b'\xff\xff')
    dw._dw_vp(vp, bytes((0, 1, total >> 8, total & 0xFF)))
    _shown = True


def _lines():
    if not _log:
        if _lib().llm_ready():
            return [("Press ASK and type a question.", MUTED)]
        return [("No AI link yet.", RED), ("Put LLM_URL (and LLM_KEY)", MUTED),
                ("in lib.py on the board.", MUTED)]
    out = []
    for kind, text in _log:
        colour = BLUE if kind == "q" else MUTED if kind == "w" else RED if kind == "e" else INK
        for line in _wrap(("You: " if kind == "q" else "AI: ") + text, COLS):
            out.append((line, colour))
    return out


def _draw_chat():
    global _scroll
    lines = _lines()
    top = max(0, len(lines) - ROWS)
    _scroll = min(_scroll, top)
    start = top - _scroll
    items = [(line, X0, Y0 + i * LINE_H, colour) for i, (line, colour) in enumerate(lines[start:start + ROWS])]
    if start:                                       # more above / below: UP / DOWN
        items.append(("^", 452, Y0, MUTED))
    if _scroll:
        items.append(("v", 452, Y0 + (ROWS - 1) * LINE_H, MUTED))
    _draw(DOTS_VP, DOTS_MAX, items)


def _draw_kb():
    if _q:
        s = _q + "_"
        lines = [s[i:i + COLS] for i in range(0, len(s), COLS)][-Q_ROWS:]
        colour = INK
    else:
        lines, colour = ["Type your question,", "then press SEND."], MUTED
    _draw(KB_DOTS_VP, KB_DOTS_MAX, [(line, Q_X, Q_Y + i * Q_LINE_H, colour) for i, line in enumerate(lines)])


def _leave():
    """Chat pages closed: empty both lists (region A is the image page's) and
    give the buffer back."""
    global _shown, _buf
    if _shown:
        dw = _dw()
        dw._dw_vp(DOTS_VP, b'\x00\x01\x00\x00')
        dw._dw_vp(KB_DOTS_VP, b'\x00\x01\x00\x00')
        _shown = False
    _buf = None


def history():
    """Last two finished (question, answer) pairs, sent along for context."""
    out = []
    for i in range(len(_log) - 1):
        if _log[i][0] == "q" and _log[i + 1][0] == "a":
            out.append((_log[i][1], _log[i + 1][1][:300]))
    return out[-2:]


def show_question(question, go=False):
    """Add 'You: ...' + 'AI: thinking...'; go=True opens page 98 (programs)."""
    global _scroll, _page
    _log.append(["q", question])
    _log.append(["w", "thinking..."])
    del _log[:-KEEP]
    _scroll = 0
    if go:
        _dw().dwin_page(PAGE_CHAT)
        _page = PAGE_CHAT
    if _page == PAGE_CHAT:
        _draw_chat()


def show_answer(ok, text, draw=False):
    global _scroll
    for e in reversed(_log):
        if e[0] == "w":
            e[0], e[1] = ("a" if ok else "e"), text
            break
    else:
        _log.append(["a" if ok else "e", text])
    _scroll = 0
    if draw or _page == PAGE_CHAT:
        _draw_chat()


def ask(question):
    """Display flow: send now, the answer is picked up in poll()."""
    global _t0
    show_question(question)
    err = _lib()._llm_send(REQ_ID, question, history())
    if err:
        show_answer(False, err)
    else:
        _t0 = time.ticks_ms()


def _check(now):
    global _t0
    import iot_bus
    lib = _lib()
    rep = iot_bus.take(REQ_ID)
    if rep is not None:
        _t0 = None
        show_answer(*lib._llm_reply(rep))
    elif time.ticks_diff(now, _t0) > lib.LLM_TIMEOUT_MS + 3000:
        _t0 = None
        show_answer(False, "No reply - check Wi-Fi and LLM_URL.")


def _key(k):
    global _q, _scroll, _page
    if _page == PAGE_CHAT:
        if k == 0x0802:
            _scroll += 3
        elif k == 0x0803:
            _scroll = max(0, _scroll - 3)
        elif k == 0x0804 and _t0 is None:
            del _log[:]
            _scroll = 0
        else:
            return
        _draw_chat()
        return
    if 0x20 <= k <= 0x7E:
        if len(_q) < Q_MAX:
            _q += chr(k)
    elif k == 0x0008:
        _q = _q[:-1]
    elif k == 0x0805:
        _q = ""
    elif k == 0x000D:
        if not _q.strip() or _t0 is not None:
            return
        question, _q = _q.strip(), ""
        _dw().dwin_page(PAGE_CHAT)
        _page = PAGE_CHAT
        ask(question)
        return
    else:
        return
    _draw_kb()


def poll(page, changed):
    """From dwin_wifi_ui.poll: page = page on screen, changed = it just changed."""
    global _page
    if changed:
        _page = page
        if page == PAGE_CHAT:
            _draw_chat()
        elif page == PAGE_KB:
            _draw_kb()
        elif page not in PAGES:
            _leave()
    if page in PAGES:
        dw = _dw()
        k = dw._dw_read(KEY_VP, 1)
        if k and k[0]:
            dw._dw_vp(KEY_VP, b'\x00\x00')
            _key(k[0])
    if _t0 is not None:
        _check(time.ticks_ms())
