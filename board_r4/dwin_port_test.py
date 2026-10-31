################################################################################
# dwin_port_test.py — Curio Motherboard R4 Interactive Hardware Manager
# Mapped directly to schematic: "CM_MOTHERBOARD_R4 CIRCUIT (1).pdf"
#
# Motherboard Connectors:
#   MOD1 (Analog / Digital & I2C1): JACK1..4 -> DIG (D3..D6) / ANA (C0..C2, F9) / I2C1 (B6, B7)
#   MOD2 (Analog / Digital / I2C4): JACK1..4 -> DIG (D7, E0, E1, G3) / ANA (C4, C5, A1, A2) / I2C4 (D12, D13)
#   MOD3 (SPI & UART):              JACK1..3 -> UART1..3 / DIG (G0..G2) / ANA (A4, F8, A6)
#                                   JACK4    -> SPI2: CS (B12), MOSI (C3), MISO (B14), SCK (B13)
#   MOD4 (PWM & Actuators):         JACK1..4 -> Dual PWM (E11, B9, E13, D15) / DIG / ANA
#   ONBOARD:                        BUZZER (F6), GREEN LED (F7), SW1 (E10), SW2 (E9)
################################################################################

import machine
from machine import Pin, ADC, PWM
import time
import struct
import dwin_screen as dw
from dwin_get_data import _GLYPHS, _ADOTS

PORT_TEST_DOTS_VP = 0x6600
PORT_TEST_KEY_VP  = 0x5F50
PORT_PAGES = (74, 75, 76, 77, 78)

PORTS_LIST = [
    # Screen 1: MOD1 (Analog / Digital & I2C1) — Primary Sensor Jacks
    {
        "name": "MOD1-J1",
        "title": "MOD1 - J1 (I2C1)",
        "sub": "DIG: D3 - ANA: C0",
        "dig": "D3",
        "ana": "C0",
        "pwm": None,
    },
    {
        "name": "MOD1-J2",
        "title": "MOD1 - J2 (I2C1)",
        "sub": "DIG: D4 - ANA: C1",
        "dig": "D4",
        "ana": "C1",
        "pwm": None,
    },
    {
        "name": "MOD1-J3",
        "title": "MOD1 - J3 (I2C1)",
        "sub": "DIG: D5 - ANA: C2",
        "dig": "D5",
        "ana": "C2",
        "pwm": None,
    },
    {
        "name": "MOD1-J4",
        "title": "MOD1 - J4 (I2C1)",
        "sub": "DIG: D6 - ANA: F9",
        "dig": "D6",
        "ana": "F9",
        "pwm": None,
    },

    # Screen 2: MOD2 (Analog / Digital / I2C4) — Secondary Sensor Jacks
    {
        "name": "MOD2-J1",
        "title": "MOD2 - J1 (I2C4)",
        "sub": "DIG: D7 - ANA: C4",
        "dig": "D7",
        "ana": "C4",
        "pwm": None,
    },
    {
        "name": "MOD2-J2",
        "title": "MOD2 - J2 (I2C4)",
        "sub": "DIG: E0 - ANA: C5",
        "dig": "E0",
        "ana": "C5",
        "pwm": None,
    },
    {
        "name": "MOD2-J3",
        "title": "MOD2 - J3 (I2C4)",
        "sub": "DIG: E1 - ANA: A1",
        "dig": "E1",
        "ana": "A1",
        "pwm": "A1",
    },
    {
        "name": "MOD2-J4",
        "title": "MOD2 - J4 (I2C4)",
        "sub": "DIG: G3 - ANA: A2",
        "dig": "G3",
        "ana": "A2",
        "pwm": "A2",
    },

    # Screen 3: MOD3 (SPI & UART) — Communication & High Speed Bus
    {
        "name": "MOD3-J1",
        "title": "MOD3 - J1 (UART1)",
        "sub": "UART1 - D:G0 - A:A4",
        "dig": "G0",
        "ana": "A4",
        "pwm": "A9",
    },
    {
        "name": "MOD3-J2",
        "title": "MOD3 - J2 (UART2)",
        "sub": "UART2 - D:G1 - A:F8",
        "dig": "G1",
        "ana": "F8",
        "pwm": "F8",
    },
    {
        "name": "MOD3-J3",
        "title": "MOD3 - J3 (UART3)",
        "sub": "UART3 - D:G2 - A:A6",
        "dig": "G2",
        "ana": "A6",
        "pwm": "A6",
    },
    {
        "name": "MOD3-J4",
        "title": "MOD3 - J4 (SPI2)",
        "sub": "SPI2: B12 C3 B14 B13",
        "dig": "B12",
        "ana": "C3",
        "pwm": "B14",
    },

    # Screen 4: MOD4 (PWM & Actuators) — Dual PWM Motors & Servos
    {
        "name": "MOD4-J1",
        "title": "MOD4 - J1 (PWM)",
        "sub": "PWM:E11 - D:E3 - A:A3",
        "dig": "E3",
        "ana": "A3",
        "pwm": "E11",
    },
    {
        "name": "MOD4-J2",
        "title": "MOD4 - J2 (PWM)",
        "sub": "PWM:B9 - D:G4 - A:F3",
        "dig": "G4",
        "ana": "F3",
        "pwm": "B9",
    },
    {
        "name": "MOD4-J3",
        "title": "MOD4 - J3 (PWM)",
        "sub": "PWM:E13 - D:G5 - A:F4",
        "dig": "G5",
        "ana": "F4",
        "pwm": "E13",
    },
    {
        "name": "MOD4-J4",
        "title": "MOD4 - J4 (PWM)",
        "sub": "PWM:D15 - D:G6 - A:F5",
        "dig": "G6",
        "ana": "F5",
        "pwm": "D15",
    },

    # Screen 5: Onboard Peripherals
    {
        "name": "BUZZER",
        "title": "ONBOARD BUZZER",
        "sub": "PIN F6 - ACTIVE DRIVER",
        "dig": "F6",
        "ana": None,
        "pwm": "F6",
    },
    {
        "name": "BRD LED",
        "title": "ONBOARD GREEN LED",
        "sub": "PIN F7 - ACTIVE HIGH",
        "dig": "F7",
        "ana": None,
        "pwm": "F7",
    },
    {
        "name": "SW1 USR",
        "title": "USER BUTTON 1 (SW1)",
        "sub": "PIN E10 - ACTIVE LOW",
        "dig": "E10",
        "ana": None,
        "pwm": None,
    },
    {
        "name": "SW2 USR",
        "title": "USER BUTTON 2 (SW2)",
        "sub": "PIN E9 - ACTIVE LOW",
        "dig": "E9",
        "ana": None,
        "pwm": "E9",
    },
]

_current_port_idx = 0       # default MOD1-J1
_port_scroll_idx  = 0       # visible 4-port page (0, 4, 8, 12, 16)
_current_mode     = 0       # 0: Dig In, 1: Ana In, 2: Dig Out, 3: PWM, 4: Servo
_dig_out_state    = False
_pwm_duty         = 50      # percent
_servo_angle      = 90      # degrees

_active_pwm_pin   = None
_active_pwm_obj   = None
_last_page        = None
_last_draw_ms     = 0
_last_sample_ms   = 0

_buf = bytearray(1200 * 6)


def _cleanup_hardware():
    global _active_pwm_obj, _active_pwm_pin
    if _active_pwm_obj:
        try:
            _active_pwm_obj.deinit()
        except Exception:
            pass
        _active_pwm_obj = None
        _active_pwm_pin = None


def _apply_hardware_output():
    global _active_pwm_obj, _active_pwm_pin
    port = PORTS_LIST[_current_port_idx]

    if _current_mode == 2:  # DIG OUT
        _cleanup_hardware()
        try:
            p = Pin(port["dig"], Pin.OUT)
            p.value(1 if _dig_out_state else 0)
        except Exception as e:
            print("Pin out error:", e)

    elif _current_mode == 3:  # PWM OUT
        pwm_pin = port.get("pwm")
        if not pwm_pin:
            _cleanup_hardware()
            return
        try:
            duty_u16 = int((_pwm_duty / 100.0) * 65535)
            if _active_pwm_pin != pwm_pin or _active_pwm_obj is None:
                _cleanup_hardware()
                _active_pwm_obj = PWM(Pin(pwm_pin), freq=1000, duty_u16=duty_u16)
                _active_pwm_pin = pwm_pin
            else:
                _active_pwm_obj.duty_u16(duty_u16)
        except Exception as e:
            print("PWM error:", e)

    elif _current_mode == 4:  # SERVO
        _cleanup_hardware()
        pwm_pin = port.get("pwm")
        if not pwm_pin:
            return
        try:
            pin = Pin(pwm_pin, Pin.OUT)
            pulse_us = 500 + int(_servo_angle * 2000 // 180)
            low_us = 20000 - pulse_us
            for _ in range(5):
                pin.value(1)
                time.sleep_us(pulse_us)
                pin.value(0)
                time.sleep_us(low_us)
        except Exception as e:
            print("Servo error:", e)


def _draw_dashboard(page, force=False):
    global _last_draw_ms
    now = time.ticks_ms()
    n = 0
    buf = _buf

    def add_str(text, x, y, step, colour, gap=2, space_w=6):
        nonlocal n
        for ch in text.upper():
            if ch == ' ':
                x += space_w
                continue
            g = _GLYPHS.get(ch)
            if not g:
                x += 4 * step + gap
                continue
            cols = len(g[0])
            y_off = 2 if ch == ':' else 0
            for r, row in enumerate(g):
                for c, val in enumerate(row):
                    if val == '#' and n < 1080:
                        struct.pack_into('>HHH', buf, n * 6,
                                         x + c * step, y + y_off + r * step, colour)
                        n += 1
            x += (cols - 1) * step + 3 + gap
        return x

    def add_arial(text, x, y, colour, xmax=450):
        nonlocal n
        for ch in text.upper():
            if ch == ' ':
                x += 6
                continue
            adv, pts = _ADOTS.get(ch, _ADOTS['?'])
            if x + adv > xmax:
                break
            for k in range(0, len(pts), 2):
                if n < 1080:
                    struct.pack_into('>HHH', buf, n * 6,
                                     x + pts[k], y + pts[k + 1], colour)
                    n += 1
            x += adv + 1
        return x

    # 1. Left column: 4 visible port slots
    for i in range(4):
        p_idx = _port_scroll_idx + i
        if p_idx < len(PORTS_LIST):
            pname = PORTS_LIST[p_idx]["name"]
            sy = 120 + i * 36 + 10
            is_active = (p_idx == _current_port_idx)
            lbl = ("> " + pname) if is_active else ("  " + pname)
            col = 0x001F if is_active else 0x31A6   # Blue vs dark grey
            add_str(lbl, 20, sy, 2, col)

    # 2. Right column: Active port header
    port = PORTS_LIST[_current_port_idx]
    add_arial(port["title"], 220, 58, 0x001F, 450)
    add_arial(port["sub"], 220, 76, 0x52AA, 450)

    # 3. Mode-specific dynamic telemetry
    if page == 74:  # DIG IN
        try:
            is_btn = "SW" in port["name"] or "BUTTON" in port["name"]
            pull = Pin.PULL_UP if is_btn else None
            p = Pin(port["dig"], Pin.IN, pull) if pull else Pin(port["dig"], Pin.IN)
            val = p.value()
        except Exception:
            val = 0
        if is_btn:
            state_txt = "BUTTON: PRESSED (0V)" if (val == 0) else "BUTTON: RELEASED (3.3V)"
            state_col = 0x0540 if (val == 0) else 0x7BEF
        elif port["name"] == "MOD3-J4":
            state_txt = "SPI2 BUS: ACTIVE (HIGH)"
            state_col = 0x001F
        else:
            state_txt = "STATE: HIGH (3.3V)" if val else "STATE: LOW (0.0V)"
            state_col = 0x0540 if val else 0x7BEF  # Green vs Grey
        add_arial(state_txt, 182, 156, state_col, 448)
        add_arial("DIGITAL PIN: " + port["dig"] + " (INPUT)", 182, 210, 0x1947, 448)
        add_arial("LOGIC LEVEL: " + ("1 (HIGH)" if val else "0 (LOW)"), 182, 238, 0x31A6, 448)

    elif page == 75:  # ANA IN
        if port.get("ana"):
            try:
                adc = ADC(Pin(port["ana"]))
                raw = adc.read_u16()
                volt = (raw / 65535.0) * 3.3
            except Exception:
                raw = 0
                volt = 0.0
            add_arial("ADC: " + str(raw), 182, 156, 0x027F, 305)
            add_arial("VOLT: " + "{:.2f}".format(volt) + "V", 320, 156, 0x1947, 448)
            # Dotted gauge bar inside the grey box (172, 210, 456, 230)
            bar_w = int((raw / 65535.0) * 260)
            for bx in range(180, 180 + bar_w, 4):
                if n < 1080:
                    struct.pack_into('>HHH', buf, n * 6, bx, 220, 0x001F)
                    n += 1
            add_arial("ANALOG PIN: " + port["ana"] + " (0-3.3V)", 182, 242, 0x31A6, 448)
        else:
            add_arial("NO ANALOG PIN ON THIS PORT", 182, 156, 0xD800, 448)
            add_arial("DIGITAL PERIPHERAL ONLY", 182, 215, 0x52AA, 448)
            add_arial("USE MOD1-MOD4 FOR ADC INPUT", 182, 242, 0x31A6, 448)

    elif page == 76:  # DIG OUT
        out_txt = "STATE: OUTPUT HIGH (3.3V)" if _dig_out_state else "STATE: OUTPUT LOW (0V)"
        out_col = 0x0540 if _dig_out_state else 0xD800  # Green vs Red
        add_arial(out_txt, 182, 138, out_col, 448)
        add_arial("DRIVING PIN: " + port["dig"] + " (OUTPUT)", 182, 244, 0x31A6, 448)

    elif page == 77:  # PWM OUT
        if port.get("pwm"):
            add_arial("DUTY: " + str(_pwm_duty) + "%", 182, 136, 0x001F, 280)
            add_arial("PIN: " + port["pwm"] + " (1KHZ)", 290, 136, 0x31A6, 448)
        else:
            add_arial("PWM NOT AVAILABLE ON THIS PORT", 182, 136, 0xD800, 448)

    elif page == 78:  # SERVO
        if port.get("pwm"):
            add_arial("SERVO: " + str(_servo_angle) + " DEG", 182, 136, 0xFA00, 280)
            add_arial("PIN: " + port["pwm"] + " (50HZ)", 290, 136, 0x31A6, 448)
        else:
            add_arial("SERVO NOT AVAILABLE ON THIS PORT", 182, 136, 0xD800, 448)

    # 4. Footer Note: DO NOT overwrite background explanation text.

    # Emit dot list to DWIN display VP 0x6600
    addr = PORT_TEST_DOTS_VP + 2
    mv = memoryview(buf)
    for i in range(0, n * 6, 120):
        dw._dw_vp(addr + i // 2, mv[i:min(n * 6, i + 120)])
    dw._dw_vp(addr + n * 3, b'\xff\xff')
    dw._dw_vp(PORT_TEST_DOTS_VP, struct.pack('>HH', 1, n))
    _last_draw_ms = now


def poll():
    global _current_port_idx, _port_scroll_idx, _current_mode
    global _dig_out_state, _pwm_duty, _servo_angle, _last_page, _last_sample_ms

    p = dw._dw_read(0x0014, 1)
    if not p:
        return
    page = p[0]

    # Leaving Port Manager pages: clean up outputs
    if page not in PORT_PAGES:
        if _last_page in PORT_PAGES:
            _cleanup_hardware()
            _last_page = page
        return

    # Page entry or mode tab switch
    if page != _last_page:
        _current_mode = page - 74
        _last_page = page
        _apply_hardware_output()
        _draw_dashboard(page, force=True)

    # Read touch return key VP
    k = dw._dw_read(PORT_TEST_KEY_VP, 1)
    if k and k[0] != 0:
        key = k[0]
        dw._dw_vp(PORT_TEST_KEY_VP, b'\x00\x00')   # clear key

        # Port Selector Actions
        if key == 0x0301:   # Prev Pins
            if _port_scroll_idx > 0:
                _port_scroll_idx = max(0, _port_scroll_idx - 4)
                _current_port_idx = _port_scroll_idx
                _apply_hardware_output()
                _draw_dashboard(page, force=True)
        elif key == 0x0302: # Next Pins
            if _port_scroll_idx + 4 < len(PORTS_LIST):
                _port_scroll_idx += 4
                _current_port_idx = _port_scroll_idx
                _apply_hardware_output()
                _draw_dashboard(page, force=True)
        elif 0x0303 <= key <= 0x0306:  # Select Slot 0..3
            sel = _port_scroll_idx + (key - 0x0303)
            if sel < len(PORTS_LIST):
                _current_port_idx = sel
                _apply_hardware_output()
                _draw_dashboard(page, force=True)

        # Digital Output Actions
        elif key == 0x0321: # ON
            _dig_out_state = True
            _apply_hardware_output()
            _draw_dashboard(page, force=True)
        elif key == 0x0320: # OFF
            _dig_out_state = False
            _apply_hardware_output()
            _draw_dashboard(page, force=True)

        # PWM Actions
        elif 0x0330 <= key <= 0x0334: # 0, 25, 50, 75, 100%
            presets = [0, 25, 50, 75, 100]
            _pwm_duty = presets[key - 0x0330]
            _apply_hardware_output()
            _draw_dashboard(page, force=True)
        elif key == 0x0335: # -10%
            _pwm_duty = max(0, _pwm_duty - 10)
            _apply_hardware_output()
            _draw_dashboard(page, force=True)
        elif key == 0x0336: # +10%
            _pwm_duty = min(100, _pwm_duty + 10)
            _apply_hardware_output()
            _draw_dashboard(page, force=True)

        # Servo Actions
        elif 0x0340 <= key <= 0x0344: # 0, 45, 90, 135, 180 deg
            presets = [0, 45, 90, 135, 180]
            _servo_angle = presets[key - 0x0340]
            _apply_hardware_output()
            _draw_dashboard(page, force=True)
        elif key == 0x0345: # -15 deg
            _servo_angle = max(0, _servo_angle - 15)
            _apply_hardware_output()
            _draw_dashboard(page, force=True)
        elif key == 0x0346: # +15 deg
            _servo_angle = min(180, _servo_angle + 15)
            _apply_hardware_output()
            _draw_dashboard(page, force=True)

    # Real-time sampling for input modes (every 250 ms)
    now = time.ticks_ms()
    if page in (74, 75) and time.ticks_diff(now, _last_sample_ms) > 250:
        _draw_dashboard(page)
        _last_sample_ms = now
