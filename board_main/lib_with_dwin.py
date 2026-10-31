################################################################################
# lib.py — CURIO_MAKER PROJECTS | MicroPython v1.27.0 | STM32H723ZGT6
#
# EVERY function has a SYNC version AND an ASYNC version.
#
# SYNC  → call directly, no await:
#   IR()  motion()  flame()  buzzer()  servo()  ...
#
# ASYNC → use with  await  inside  async def:
#   async_IR()  async_motion()  async_flame()  async_buzzer()  ...
#
# ASYNC RULES:
#   INSTANT functions  (pin read/write, ~0ms):
#     → call sync + await asyncio.sleep_ms(0)  to yield once
#     → safe to use inside asyncio.gather()
#
#   BLOCKING functions (have time.sleep inside):
#     → time.sleep(s)      replaced with  await asyncio.sleep(s)
#     → time.sleep_ms(ms)  replaced with  await asyncio.sleep_ms(ms)
#     → time.sleep_us(us)  KEPT sync (µs precision required for PWM/pulse)
#
# SERVO NOTE:
#   Software PWM used — PE14 only has Timer1 Ch4 (AF1).
#   Timer1 is already used by motor_speed at 20kHz.
#   Bit-bang: 5 pulses × 20ms = 100ms, servo reaches angle and holds.
################################################################################

from machine import Pin, I2C, ADC, UART, SPI
import machine
import time
import pyb
import gc
import dht
import uasyncio as asyncio
# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
ON  = True
OFF = False
baseline = 30000

# ─────────────────────────────────────────────────────────────────────────────
# TIMING STORE
# ─────────────────────────────────────────────────────────────────────────────

_timings = {}
_t_start = {}

def _t0(name):
    _t_start[name] = time.ticks_ms()

def _t1(name):
    if name in _t_start:
        _timings[name] = time.ticks_diff(time.ticks_ms(), _t_start[name])

def print_timings():
    if not _timings:
        print("[timings] no data"); return
    print()
    print("  +------------------------------+----------+")
    print("  | Function                     |   Time   |")
    print("  +------------------------------+----------+")
    for fn, ms in _timings.items():
        print("  | {:<28}  | {:>6} ms |".format(fn, ms))
    print("  +------------------------------+----------+")
    print()

def reset_timings():
    _timings.clear()
    _t_start.clear()


################################################################################
# 1. IR SENSOR
################################################################################

def IR(pin_name):
    if "_ir_cache" not in globals():
        global _ir_cache; _ir_cache = {}
    if pin_name not in _ir_cache:
        _ir_cache[pin_name] = Pin(pin_name, Pin.IN)
    return _ir_cache[pin_name].value()

async def async_IR(pin_name):
    _t0("async_IR")
    result = IR(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_IR")
    return result


################################################################################
# 2. MOTION SENSOR
################################################################################

def motion(pin_name):
    if "_motion_cache" not in globals():
        global _motion_cache; _motion_cache = {}
    if pin_name not in _motion_cache:
        _motion_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_UP)
    return _motion_cache[pin_name].value()

async def async_motion(pin_name):
    _t0("async_motion")
    result = motion(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_motion")
    return result


################################################################################
# 3. TILT SENSOR
################################################################################

def tilt(pin_name):
    if "_tilt_cache" not in globals():
        global _tilt_cache; _tilt_cache = {}
    if pin_name not in _tilt_cache:
        _tilt_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_UP)
    return _tilt_cache[pin_name].value()

async def async_tilt(pin_name):
    _t0("async_tilt")
    result = tilt(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_tilt")
    return result


################################################################################
# 4. BUTTON
################################################################################

_btn_cache = {}

def button(pin_name):

    if pin_name not in _btn_cache:
        _btn_cache[pin_name] = Pin(
            pin_name,
            Pin.IN,
            Pin.PULL_DOWN
        )

    return _btn_cache[pin_name].value()


async def async_button(pin_name):

    _t0("async_button")

    result = button(pin_name)

    await asyncio.sleep_ms(0)

    _t1("async_button")

    return result


################################################################################
# 5. FLAME SENSOR
################################################################################

def flame(pin_name):
    if "_flame_cache" not in globals():
        global _flame_cache; _flame_cache = {}
    if pin_name not in _flame_cache:
        _flame_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_UP)
    return _flame_cache[pin_name].value()

async def async_flame(pin_name):
    _t0("async_flame")
    result = flame(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_flame")
    return result


################################################################################
# 6. DC MOTOR (direction only)
################################################################################

def motor(in1_pin, in2_pin, direction):
    if "_dc_cache" not in globals():
        global _dc_cache; _dc_cache = {}
    key = (in1_pin, in2_pin)
    if key not in _dc_cache:
        _dc_cache[key] = (Pin(in1_pin, Pin.OUT), Pin(in2_pin, Pin.OUT))
    in1, in2 = _dc_cache[key]
    s1, s2 = {"forward": (1, 0), "backward": (0, 1), "stop": (0, 0)}.get(direction, (0, 0))
    in1.value(s1); in2.value(s2)

async def async_motor(in1_pin, in2_pin, direction):
    _t0("async_motor")
    motor(in1_pin, in2_pin, direction)
    await asyncio.sleep_ms(0)
    _t1("async_motor")


################################################################################
# 6b. DC MOTOR WITH SPEED (PWM)
################################################################################

def motor_speed(pin1, pin2, speed, action):
    global _m_tim, _m_p1, _m_p2, _m_pwm, _m_pins
    if   speed <= 20: speed = 20
    elif speed <= 40: speed = 40
    elif speed <= 60: speed = 60
    elif speed <= 80: speed = 80
    else:             speed = 100
    if "_m_pins" not in globals() or _m_pins != (pin1, pin2):
        if "_m_tim" in globals() and _m_tim: _m_tim.deinit()
        _m_p1  = pyb.Pin(pin1, pyb.Pin.OUT_PP)
        _m_p2  = pyb.Pin(pin2, pyb.Pin.OUT_PP)
        _m_tim = pyb.Timer(1, freq=20000)
        _m_pwm = _m_tim.channel(3, pyb.Timer.PWM, pin=_m_p1)
        _m_pins = (pin1, pin2)
    if action == "stop" or speed <= 0:
        _m_pwm.pulse_width_percent(0); _m_p1.low(); _m_p2.low(); return
    if action == "forward":
        _m_p1.high(); _m_p2.low()
    elif action == "backward":
        _m_p1.low(); _m_p2.high()
    duty = 100 if speed > 100 else (0 if speed < 0 else speed)
    _m_pwm.pulse_width_percent(duty)

async def async_motor_speed(pin1, pin2, speed, action):
    _t0("async_motor_speed")
    motor_speed(pin1, pin2, speed, action)
    await asyncio.sleep_ms(0)
    _t1("async_motor_speed")


################################################################################
# 7. STEPPER MOTOR
################################################################################

_step_seq = [[1,0,0,1],[1,1,0,0],[0,1,1,0],[0,0,1,1]]

def get_stepper(pin1, pin2, pin3, pin4, angle, direction, steps_per_revolution=200, delay_ms=100):
    if "_stp_cache" not in globals():
        global _stp_cache; _stp_cache = {}
    key = (pin1, pin2, pin3, pin4)
    if key not in _stp_cache:
        _stp_cache[key] = (Pin(pin1, Pin.OUT), Pin(pin2, Pin.OUT),
                           Pin(pin3, Pin.OUT), Pin(pin4, Pin.OUT))
    IN1, IN2, IN3, IN4 = _stp_cache[key]
    steps = int((angle / 360.0) * steps_per_revolution)
    if direction == 'reverse': steps = -steps
    pins = (IN1, IN2, IN3, IN4)
    for _ in range(abs(steps)):
        for s in _step_seq:
            for i in range(4): pins[i].value(s[i])
            time.sleep_ms(delay_ms)

async def async_get_stepper(pin1, pin2, pin3, pin4, angle, direction, steps_per_revolution=200, delay_ms=100):
    """Non-blocking stepper. Yields every step — other tasks run between steps."""
    _t0("async_get_stepper")
    if "_stp_cache" not in globals():
        global _stp_cache; _stp_cache = {}
    key = (pin1, pin2, pin3, pin4)
    if key not in _stp_cache:
        _stp_cache[key] = (Pin(pin1, Pin.OUT), Pin(pin2, Pin.OUT),
                           Pin(pin3, Pin.OUT), Pin(pin4, Pin.OUT))
    IN1, IN2, IN3, IN4 = _stp_cache[key]
    steps = int((angle / 360.0) * steps_per_revolution)
    if direction == 'reverse': steps = -steps
    pins = (IN1, IN2, IN3, IN4)
    for _ in range(abs(steps)):
        for s in _step_seq:
            for i in range(4): pins[i].value(s[i])
            await asyncio.sleep_ms(delay_ms)   # yields — other tasks run here
    _t1("async_get_stepper")


################################################################################
# 8. PUMP
################################################################################

def waterpump(pin_name, state):
    if "_p_cache" not in globals():
        global _p_cache; _p_cache = {}
    if pin_name not in _p_cache:
        _p_cache[pin_name] = pyb.Pin(pin_name, pyb.Pin.OUT_PP)
        _p_cache[pin_name].low()
    _p_cache[pin_name].high() if state else _p_cache[pin_name].low()

async def async_waterpump(pin_name, state):
    _t0("async_waterpump")
    waterpump(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_waterpump")


################################################################################
# 9. RELAY
################################################################################

def relay(pin_name, state):
    if "_r_cache" not in globals():
        global _r_cache; _r_cache = {}
    if pin_name not in _r_cache:
        _r_cache[pin_name] = Pin(pin_name, Pin.OUT, value=0)
    _r_cache[pin_name].value(1 if state else 0)

async def async_relay(pin_name, state):
    _t0("async_relay")
    relay(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_relay")


################################################################################
# 10. BUZZER
################################################################################
# 
# def buzzer(pin_name, freq, on_time_ms, off_time_ms):
#     if "_buz_cache" not in globals():
#         global _buz_cache; _buz_cache = {}
#     if pin_name not in _buz_cache:
#         _buz_cache[pin_name] = Pin(pin_name, Pin.OUT)
#     buzzer_pin = _buz_cache[pin_name]
#     if freq <= 0 or on_time_ms == 0:
#         buzzer_pin.off()
#         if off_time_ms > 0: time.sleep_ms(off_time_ms)
#         return
#     period_us = int(1_000_000 / freq)
#     half = period_us // 2
#     end_time = time.ticks_add(time.ticks_ms(), on_time_ms)
#     while time.ticks_diff(end_time, time.ticks_ms()) > 0:
#         buzzer_pin.on();  time.sleep_us(half)
#         buzzer_pin.off(); time.sleep_us(half)
#     buzzer_pin.off()
#     if off_time_ms > 0: time.sleep_ms(off_time_ms)
# 
# async def async_buzzer(pin_name, freq, on_time_ms, off_time_ms):
#     """Non-blocking buzzer. Yields every half-period — other tasks run.
#     sleep_us kept sync (µs precision required for tone frequency)."""
#     _t0("async_buzzer")
#     if "_buz_cache" not in globals():
#         global _buz_cache; _buz_cache = {}
#     if pin_name not in _buz_cache:
#         _buz_cache[pin_name] = Pin(pin_name, Pin.OUT)
#     buzzer_pin = _buz_cache[pin_name]
#     if freq <= 0 or on_time_ms == 0:
#         buzzer_pin.off()
#         if off_time_ms > 0: await asyncio.sleep_ms(off_time_ms)
#         _t1("async_buzzer"); return
#     half_ms = max(1, 500 // freq)
#     end_time = time.ticks_add(time.ticks_ms(), on_time_ms)
#     while time.ticks_diff(end_time, time.ticks_ms()) > 0:
#         buzzer_pin.value(1); await asyncio.sleep_ms(half_ms)   # yields here
#         buzzer_pin.value(0); await asyncio.sleep_ms(half_ms)   # yields here
#     buzzer_pin.off()
#     if off_time_ms > 0: await asyncio.sleep_ms(off_time_ms)
#     _t1("async_buzzer")
# ################################################################################
# # 10. BUZZER
# ################################################################################
################################################################################
# 10. BUZZER
################################################################################

_buz_cache = {}


def buzzer(pin_name, freq, on_time_ms, off_time_ms):

    if pin_name not in _buz_cache:
        _buz_cache[pin_name] = Pin(pin_name, Pin.OUT)

    buzzer_pin = _buz_cache[pin_name]

    # OFF condition
    if freq <= 0 or on_time_ms <= 0:
        buzzer_pin.off()
        if off_time_ms > 0:
            time.sleep_ms(off_time_ms)
        return

    # Generate tone
    period_us = int(1_000_000 / freq)
    half_us = period_us // 2

    end_time = time.ticks_add(
        time.ticks_ms(),
        on_time_ms
    )

    while time.ticks_diff(end_time, time.ticks_ms()) > 0:
        buzzer_pin.on()
        time.sleep_us(half_us)
        buzzer_pin.off()
        time.sleep_us(half_us)

    buzzer_pin.off()

    if off_time_ms > 0:
        time.sleep_ms(off_time_ms)



################################################################################
# ASYNC BUZZER
################################################################################

_buz_active = {}


async def _async_buzzer_worker(pin_name, freq, on_time_ms, off_time_ms):
    buzzer_pin = _buz_cache.get(pin_name)
    if buzzer_pin is None:
        return
    try:
        period_us = int(1_000_000 / freq)
        half_us = period_us // 2

        end_time = time.ticks_add(
            time.ticks_ms(),
            on_time_ms
        )

        cnt = 0
        while time.ticks_diff(end_time, time.ticks_ms()) > 0:
            buzzer_pin.on()
            time.sleep_us(half_us)
            buzzer_pin.off()
            time.sleep_us(half_us)
            cnt += 1
            if cnt >= 25:
                cnt = 0
                await asyncio.sleep_ms(0)

        buzzer_pin.off()

        if off_time_ms > 0:
            await asyncio.sleep_ms(off_time_ms)
    except Exception:
        pass
    finally:
        try:
            buzzer_pin.off()
        except Exception:
            pass
        _buz_active.pop(pin_name, None)


async def async_buzzer(pin_name, freq, on_time_ms, off_time_ms):

    _t0("async_buzzer")

    if pin_name not in _buz_cache:
        _buz_cache[pin_name] = Pin(pin_name, Pin.OUT)

    buzzer_pin = _buz_cache[pin_name]

    # OFF condition
    if freq <= 0 or on_time_ms <= 0:
        buzzer_pin.off()
        _buz_active.pop(pin_name, None)
        _t1("async_buzzer")
        return

    # Non-blocking: If buzzer is already playing on this pin, don't block and don't retrigger
    if pin_name in _buz_active:
        _t1("async_buzzer")
        return

    _buz_active[pin_name] = True
    asyncio.create_task(_async_buzzer_worker(pin_name, freq, on_time_ms, off_time_ms))
    await asyncio.sleep_ms(0)

    _t1("async_buzzer")

################################################################################
# 11. JOYSTICK
################################################################################

def joy_stick(pin_x_name, pin_y_name):
    global xAngle, yAngle
    if "_j_init" not in globals():
        global _j_init, _j_x_adc, _j_y_adc, _CX, _CY, _TX, _TY
        _j_x_adc = ADC(Pin(pin_x_name)); _j_y_adc = ADC(Pin(pin_y_name))
        xAngle, yAngle = 503, 508
        _CX, _CY = 32768, 32768; _TX, _TY = 5000, 8000; _j_init = True
    x = _j_x_adc.read_u16(); y = _j_y_adc.read_u16()
    dx, dy = x - _CX, y - _CY; adx, ady = abs(dx), abs(dy)
    direction = "CENTER"
    if ady > adx and ady > _TY:
        if dy < 0: direction = "FRONT"; xAngle -= 1
        else:      direction = "BACK";  xAngle += 1
    elif adx > ady and adx > _TX:
        if dx < 0: direction = "LEFT";  yAngle -= 1
        else:      direction = "RIGHT"; yAngle += 1
    return direction

async def async_joy_stick(pin_x_name, pin_y_name):
    _t0("async_joy_stick")
    result = joy_stick(pin_x_name, pin_y_name)
    await asyncio.sleep_ms(0)
    _t1("async_joy_stick")
    return result


################################################################################
# 12. TEMPERATURE SENSOR (DHT11/22)
################################################################################

# _dht_bits = bytearray(40)
# 
# def temp(pin_name):
#     if "_dht_pin_cache" not in globals():
#         global _dht_pin_cache; _dht_pin_cache = {}
#     if pin_name not in _dht_pin_cache:
#         _dht_pin_cache[pin_name] = machine.Pin(pin_name, machine.Pin.OUT)
#     DHT_PIN = _dht_pin_cache[pin_name]
#     DHT_PIN.init(machine.Pin.OUT); DHT_PIN.value(0); time.sleep_ms(20)
#     DHT_PIN.value(1); DHT_PIN.init(machine.Pin.IN, machine.Pin.PULL_UP)
#     if machine.time_pulse_us(DHT_PIN, 0, 150) < 0: return None, None
#     if machine.time_pulse_us(DHT_PIN, 1, 150) < 0: return None, None
#     for i in range(40):
#         dur = machine.time_pulse_us(DHT_PIN, 1, 150)
#         if dur < 0: return None, None
#         _dht_bits[i] = 1 if dur > 45 else 0
#     b = [0, 0, 0, 0, 0]
#     for i in range(5):
#         byte = 0
#         for j in range(8): byte = (byte << 1) | _dht_bits[i*8 + j]
#         b[i] = byte
#     if (sum(b[:4]) & 0xFF) == b[4]: return b[2]
#     return None, None
# 
# async def async_temp(pin_name):
#     """Non-blocking DHT read. 20ms start pulse → await sleep_ms(20)."""
#     _t0("async_temp")
#     if "_dht_pin_cache" not in globals():
#         global _dht_pin_cache; _dht_pin_cache = {}
#     if pin_name not in _dht_pin_cache:
#         _dht_pin_cache[pin_name] = machine.Pin(pin_name, machine.Pin.OUT)
#     DHT_PIN = _dht_pin_cache[pin_name]
#     DHT_PIN.init(machine.Pin.OUT); DHT_PIN.value(0)
#     await asyncio.sleep_ms(20)                         # yields — other tasks run
#     DHT_PIN.value(1); DHT_PIN.init(machine.Pin.IN, machine.Pin.PULL_UP)
#     if machine.time_pulse_us(DHT_PIN, 0, 150) < 0:
#         _t1("async_temp"); return None, None
#     if machine.time_pulse_us(DHT_PIN, 1, 150) < 0:
#         _t1("async_temp"); return None, None
#     for i in range(40):
#         dur = machine.time_pulse_us(DHT_PIN, 1, 150)
#         if dur < 0: _t1("async_temp"); return None, None
#         _dht_bits[i] = 1 if dur > 45 else 0
#     b = [0, 0, 0, 0, 0]
#     for i in range(5):
#         byte = 0
#         for j in range(8): byte = (byte << 1) | _dht_bits[i*8 + j]
#         b[i] = byte
#     _t1("async_temp")
#     if (sum(b[:4]) & 0xFF) == b[4]: return b[2]
#     return None, None
# 

################################################################################
# 13. AIR QUALITY SENSOR
################################################################################

def air_quality_sensor(pin_name):
    global baseline
    if "_aq_cache" not in globals():
        global _aq_cache; _aq_cache = {}
    if pin_name not in _aq_cache:
        _aq_cache[pin_name] = ADC(Pin(pin_name))
    sensor = _aq_cache[pin_name]
    total = 0
    for _ in range(10):
        total += sensor.read_u16()
        time.sleep_ms(2)
    return max(0, (total // 10) - baseline)

async def async_air_quality_sensor(pin_name):
    """Non-blocking air quality. Yields every 2ms sample — other tasks run."""
    _t0("async_air_quality_sensor")
    global baseline
    if "_aq_cache" not in globals():
        global _aq_cache; _aq_cache = {}
    if pin_name not in _aq_cache:
        _aq_cache[pin_name] = ADC(Pin(pin_name))
    sensor = _aq_cache[pin_name]
    total = 0
    for _ in range(10):
        total += sensor.read_u16()
        await asyncio.sleep_ms(2)                      # yields here
    _t1("async_air_quality_sensor")
    return max(0, (total // 10) - baseline)


################################################################################
# 14. SOIL MOISTURE
################################################################################

def soil_moisture(pin_name):
    if "_soil_init" not in globals():
        global _soil_init, _soil_adcs, _AIR, _WATER, _SAMPLES
        _soil_adcs = {}; _AIR = 58000; _WATER = 25000; _SAMPLES = 20; _soil_init = True
    if pin_name not in _soil_adcs:
        _soil_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _soil_adcs[pin_name]
    total = 0
    for _ in range(_SAMPLES):
        total += sensor.read_u16(); time.sleep_ms(10)
    raw = total // _SAMPLES; diff = _AIR - _WATER
    pct = 100 - ((raw - _WATER) * 100 // diff)
    if pct < 0: pct = 0
    elif pct > 100: pct = 100
    if pct <= 30: return "DRY"
    elif pct <= 70: return "MOIST"
    else: return "WET"

async def async_soil_moisture(pin_name):
    """Non-blocking soil moisture. Yields every 5ms sample."""
    _t0("async_soil_moisture")
    if "_soil_init" not in globals():
        global _soil_init, _soil_adcs, _AIR, _WATER, _SAMPLES
        _soil_adcs = {}; _AIR = 58000; _WATER = 25000; _SAMPLES = 20; _soil_init = True
    if pin_name not in _soil_adcs:
        _soil_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _soil_adcs[pin_name]
    total = 0
    for _ in range(_SAMPLES):
        total += sensor.read_u16()
        await asyncio.sleep_ms(5)                      # yields here
    raw = total // _SAMPLES; diff = _AIR - _WATER
    pct = 100 - ((raw - _WATER) * 100 // diff)
    if pct < 0: pct = 0
    elif pct > 100: pct = 100
    _t1("async_soil_moisture")
    if pct <= 30: return "DRY"
    elif pct <= 70: return "MOIST"
    else: return "WET"


################################################################################
# 15. ULTRASONIC
################################################################################
# 
# def ultrasonic(trigger_pinName, Echo_pin):
#     if "_us_cache" not in globals():
#         global _us_cache; _us_cache = {}
#     key = (trigger_pinName, Echo_pin)
#     if key not in _us_cache:
#         _us_cache[key] = (Pin(trigger_pinName, Pin.OUT), Pin(Echo_pin, Pin.IN))
#     trigger_pin, echo_pin = _us_cache[key]
#     trigger_pin.low();  time.sleep_us(2)
#     trigger_pin.high(); time.sleep_us(10)
#     trigger_pin.low()
#     pulse_start = pulse_end = time.ticks_us()
#     while echo_pin.value() == 0: pulse_start = time.ticks_us()
#     while echo_pin.value() == 1: pulse_end   = time.ticks_us()
#     return round(time.ticks_diff(pulse_end, pulse_start) / 2 * 0.0343)
# 
# async def async_ultrasonic(trigger_pinName, Echo_pin):
#     """Non-blocking ultrasonic. Trigger kept sync (µs precision).
#     Yields once after read — safe to use inside gather()."""
#     _t0("async_ultrasonic")
#     result = ultrasonic(trigger_pinName, Echo_pin)
#     await asyncio.sleep_ms(0)                          # yields once
#     _t1("async_ultrasonic")
#     return result
def ultrasonic(trigger_pinName, Echo_pin):
    global _us_cache

    if "_us_cache" not in globals():
        _us_cache = {}

    key = (trigger_pinName, Echo_pin)

    if key not in _us_cache:
        _us_cache[key] = (
            Pin(trigger_pinName, Pin.OUT),
            Pin(Echo_pin, Pin.IN)
        )

    trigger_pin, echo_pin = _us_cache[key]

    # Trigger pulse
    trigger_pin.low()
    time.sleep_us(2)

    trigger_pin.high()
    time.sleep_us(10)

    trigger_pin.low()

    # Wait for echo HIGH
    timeout = time.ticks_us()

    while echo_pin.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 30000:
            return -1

    pulse_start = time.ticks_us()

    # Wait for echo LOW
    timeout = time.ticks_us()

    while echo_pin.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 30000:
            return -1

    pulse_end = time.ticks_us()

    duration = time.ticks_diff(pulse_end, pulse_start)

    distance = duration / 58.0

    return round(distance)


async def async_ultrasonic(trigger_pinName, Echo_pin):
    _t0("async_ultrasonic")

    result = ultrasonic(trigger_pinName, Echo_pin)

    await asyncio.sleep_ms(0)

    _t1("async_ultrasonic")

    return result

################################################################################
# 16. LDR
################################################################################
# 
# def LDR(pin_name):
#     if "_ldr_init" not in globals():
#         global _ldr_init, _ldr_adcs; _ldr_adcs = {}; _ldr_init = True
#     if pin_name not in _ldr_adcs:
#         _ldr_adcs[pin_name] = ADC(Pin(pin_name))
#     raw = _ldr_adcs[pin_name].read_u16()
#     if raw < 20000: return "BRIGHT"
#     elif raw < 45000: return "DIM"
#     else: return "DARK"
# 
# async def async_LDR(pin_name):
#     _t0("async_LDR")
#     result = LDR(pin_name)
#     await asyncio.sleep_ms(0)
#     _t1("async_LDR")
#     return result


################################################################################
# 17. FLEXIFORCE
################################################################################

def flexi_sensor(pin_name):
    if "_flex_cache" not in globals():
        global _flex_cache; _flex_cache = {}
    if pin_name not in _flex_cache:
        _flex_cache[pin_name] = ADC(Pin(pin_name))
    return _flex_cache[pin_name].read_u16()

async def async_flexi_sensor(pin_name):
    _t0("async_flexi_sensor")
    result = flexi_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_flexi_sensor")
    return result


################################################################################
# 18. ECG
################################################################################

def ecg(pin_name):
    if "_ecg_cache" not in globals():
        global _ecg_cache; _ecg_cache = {}
    if pin_name not in _ecg_cache:
        adc = ADC(Pin(pin_name))
        _ecg_cache[pin_name] = adc
    val = _ecg_cache[pin_name].read_u16()
    return val, (val / 65535.0) * 3.3

async def async_ecg(pin_name):
    _t0("async_ecg")
    result = ecg(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_ecg")
    return result


################################################################################
# 19. SOLENOID VALVE
################################################################################

def get_solenoid(pin_name, state):
    if "_sol_cache" not in globals():
        global _sol_cache; _sol_cache = {}
    if pin_name not in _sol_cache:
        _sol_cache[pin_name] = Pin(pin_name, Pin.OUT)
    if state == 1:
        _sol_cache[pin_name].value(1); print("Solenoid is ON")
    elif state == 0:
        _sol_cache[pin_name].value(0); print("Solenoid is OFF")
    else:
        print("Invalid state! Use 1 for 'on' and 0 for 'off'.")

async def async_get_solenoid(pin_name, state):
    _t0("async_get_solenoid")
    get_solenoid(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_get_solenoid")


################################################################################
# 20. MAGNETIC DOOR LOCK
################################################################################

def get_door(pin_name):
    if "_door_cache" not in globals():
        global _door_cache; _door_cache = {}
    if pin_name not in _door_cache:
        _door_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_UP)
    return _door_cache[pin_name].value()

async def async_get_door(pin_name):
    _t0("async_get_door")
    result = get_door(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_get_door")
    return result


################################################################################
# 21. KEYPAD
################################################################################

def keypad(r1, r2, r3, r4, c1, c2, c3, c4):
    if "_k_init" not in globals():
        global _k_init, _k_rows, _k_cols, _k_map
        _k_map = [['1','2','3','A'],['4','5','6','B'],['7','8','9','C'],['*','0','#','D']]
        _k_rows = [pyb.Pin(p, pyb.Pin.OUT_PP) for p in (r1, r2, r3, r4)]
        for r in _k_rows: r.high()
        col_list = [c1, c2, c3]
        if c4: col_list.append(c4)
        _k_cols = [pyb.Pin(p, pyb.Pin.IN, pyb.Pin.PULL_UP) for p in col_list]
        _k_init = True
    for r_idx, row in enumerate(_k_rows):
        row.low()
        for c_idx, col in enumerate(_k_cols):
            if col.value() == 0:
                time.sleep_ms(20)
                while col.value() == 0: pass
                row.high()
                return _k_map[r_idx][c_idx]
        row.high()
    return None

async def async_keypad(r1, r2, r3, r4, c1, c2, c3, c4):
    """Non-blocking keypad. Debounce sleep replaced with await."""
    _t0("async_keypad")
    if "_k_init" not in globals():
        global _k_init, _k_rows, _k_cols, _k_map
        _k_map = [['1','2','3','A'],['4','5','6','B'],['7','8','9','C'],['*','0','#','D']]
        _k_rows = [pyb.Pin(p, pyb.Pin.OUT_PP) for p in (r1, r2, r3, r4)]
        for r in _k_rows: r.high()
        col_list = [c1, c2, c3]
        if c4: col_list.append(c4)
        _k_cols = [pyb.Pin(p, pyb.Pin.IN, pyb.Pin.PULL_UP) for p in col_list]
        _k_init = True
    for r_idx, row in enumerate(_k_rows):
        row.low()
        for c_idx, col in enumerate(_k_cols):
            if col.value() == 0:
                await asyncio.sleep_ms(20)             # yields — debounce
                while col.value() == 0: pass
                row.high()
                _t1("async_keypad")
                return _k_map[r_idx][c_idx]
        row.high()
    _t1("async_keypad")
    return None


################################################################################
# 22. WATER LEVEL SENSOR
################################################################################

def water_sen(pin_name):
    if "_wlv_cache" not in globals():
        global _wlv_cache; _wlv_cache = {}
    if pin_name not in _wlv_cache:
        _wlv_cache[pin_name] = ADC(Pin(pin_name))
    return _wlv_cache[pin_name].read_u16()

async def async_water_sen(pin_name):
    _t0("async_water_sen")
    result = water_sen(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_water_sen")
    return result


################################################################################
# 23. TDS WATER SENSOR
################################################################################

_TDS_VREF = 3.3

def tds_sensor(pin_name):
    if "_tds_cache" not in globals():
        global _tds_cache; _tds_cache = {}
    if pin_name not in _tds_cache:
        _tds_cache[pin_name] = ADC(Pin(pin_name))
    raw = _tds_cache[pin_name].read_u16() >> 4
    v   = raw * _TDS_VREF / 4095
    tds = (133.42 * v**3 - 255.86 * v**2 + 857.39 * v) * 0.5
    return int(tds)

async def async_tds_sensor(pin_name):
    _t0("async_tds_sensor")
    result = tds_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_tds_sensor")
    return result


################################################################################
# 24. AMBIENT LIGHT SENSOR (APDS9900)
################################################################################

def ambient():
    if "_apds_init" not in globals():
        global _apds_init, _apds_bus, _abuf
        global _ADDR, _CMD, _EN, _AT, _CT, _C0, _C1
        from micropython import const
        _ADDR = const(0x39); _CMD = const(0x80); _EN  = const(0x00)
        _AT   = const(0x01); _CT  = const(0x0F); _C0  = const(0x14)
        _C1   = const(0x16)
        _apds_bus = None
        for _bid in (1, 4):
            try:
                _b = I2C(_bid, freq=100000)
                if _ADDR in _b.scan():
                    _apds_bus = _b
                    break
            except Exception:
                pass
        if _apds_bus is None:
            _apds_bus = I2C(1, freq=100000)
        _abuf = bytearray(2)
        try:
            _apds_bus.writeto_mem(_ADDR, _CMD | _EN, b'\x01'); time.sleep_ms(10)
            _apds_bus.writeto_mem(_ADDR, _CMD | _EN, b'\x03')
            _apds_bus.writeto_mem(_ADDR, _CMD | _AT, b'\xDB')
            _apds_bus.writeto_mem(_ADDR, _CMD | _CT, b'\x00')
            _apds_init = True
        except Exception as e:
            print("[ambient init error]:", e)
            return 0
    try:
        _apds_bus.readfrom_mem_into(_ADDR, _CMD | _C0, _abuf)
        ch0 = (_abuf[1] << 8) | _abuf[0]
        _apds_bus.readfrom_mem_into(_ADDR, _CMD | _C1, _abuf)
        ch1 = (_abuf[1] << 8) | _abuf[0]
    except Exception:
        return 0
    if ch0 == 0: return 0
    ratio = ch1 / ch0
    if ratio < 0.5:   lux = 0.0304 * ch0 - 0.062 * ch0 * (ratio ** 1.4)
    elif ratio < 0.61: lux = 0.0128 * ch0 - 0.0153 * ch1
    elif ratio < 1.30: lux = 0.00146 * ch0 - 0.00112 * ch1
    else:              lux = 0
    return int(lux)

async def async_ambient():
    _t0("async_ambient")
    result = ambient()
    await asyncio.sleep_ms(0)
    _t1("async_ambient")
    return result


################################################################################
# 25. RFID
################################################################################

def rfid():
    if "_rfid_init" not in globals():
        global _rfid_init, _rfid_cs, _rfid_spi
        _rfid_cs  = machine.Pin('B12', machine.Pin.OUT, value=1)
        _rfid_spi = machine.SPI(2, baudrate=5000000, polarity=0, phase=0)
        _rfid_init = True
    cs = _rfid_cs; spi = _rfid_spi
    def write_reg(reg, val):
        addr = (reg << 1) & 0x7E
        cs.value(0); spi.write(bytes([addr, val])); cs.value(1)
    def read_reg(reg):
        addr = ((reg << 1) & 0x7E) | 0x80
        cs.value(0); spi.write(bytes([addr])); val = spi.read(1); cs.value(1)
        return val[0]
    def transceive(data):
        write_reg(0x01, 0x00); write_reg(0x02, 0x7F); write_reg(0x0A, 0x80)
        for b in data: write_reg(0x09, b)
        write_reg(0x01, 0x0C); write_reg(0x0D, read_reg(0x0D) | 0x80)
        time.sleep_ms(30)
        return [read_reg(0x09) for _ in range(read_reg(0x0A))]
    write_reg(0x01, 0x0F); time.sleep_ms(10)
    write_reg(0x2A, 0x8D); write_reg(0x2B, 0x3E)
    write_reg(0x2D, 30);   write_reg(0x2C, 0)
    write_reg(0x15, 0x40); write_reg(0x11, 0x3D)
    write_reg(0x14, read_reg(0x14) | 0x03); write_reg(0x0D, 0x07)
    if transceive([0x26]):
        write_reg(0x0D, 0x00)
        uid = transceive([0x93, 0x20])
        if len(uid) >= 4:
            return "{:02X}{:02X}{:02X}{:02X}".format(uid[0], uid[1], uid[2], uid[3])
    return None

async def async_rfid():
    _t0("async_rfid")
    result = rfid()
    await asyncio.sleep_ms(0)
    _t1("async_rfid")
    return result


################################################################################
# 26. ACCELEROMETER (ADXL345)
################################################################################

def accelerometer():
    if "_acc_init" not in globals():
        global _acc_init, _acc_i2c, _acc_buf, _acc_data
        _acc_i2c  = I2C(4, freq=100000); _acc_buf = bytearray(6)
        _acc_data = [0.0, 0.0, 0.0]
        _acc_i2c.writeto_mem(0x53, 0x2D, b'\x08'); time.sleep_ms(10)
        _acc_init = True
    _acc_i2c.readfrom_mem_into(0x53, 0x32, _acc_buf)
    for i, idx in enumerate((0, 2, 4)):
        v = (_acc_buf[idx+1] << 8) | _acc_buf[idx]
        if v > 32767: v -= 65536
        _acc_data[i] = v * 0.0039
    return _acc_data

async def async_accelerometer():
    _t0("async_accelerometer")
    result = accelerometer()
    await asyncio.sleep_ms(0)
    _t1("async_accelerometer")
    return result


################################################################################
# 27. GESTURE (APDS9960)
################################################################################

def gesture():
    if "_g_init" not in globals():
        global _g_init, _g_i2c, _g_buf
        _g_i2c = I2C(4, freq=400000); _g_buf = bytearray(4)
        _g_i2c.writeto_mem(0x39, 0x80, b'\x45')
        _g_i2c.writeto_mem(0x39, 0xAB, b'\x01')
        _g_init = True
    status = _g_i2c.readfrom_mem(0x39, 0xAF, 1)[0]
    if not (status & 0x01): return "NONE"
    _g_i2c.readfrom_mem_into(0x39, 0xFC, _g_buf)
    u, d, l, r = _g_buf[0], _g_buf[1], _g_buf[2], _g_buf[3]
    if   u > d and u > l and u > r and u > 30: return "UP"
    elif d > u and d > l and d > r and d > 30: return "DOWN"
    elif l > r and l > u and l > d and l > 30: return "LEFT"
    elif r > l and r > u and r > d and r > 30: return "RIGHT"
    return "NONE"

async def async_gesture():
    _t0("async_gesture")
    result = gesture()
    await asyncio.sleep_ms(0)
    _t1("async_gesture")
    return result


################################################################################
# 28. RTC (DS3231 / DS1307)
################################################################################

def rtc():
    if "_rtc_init" not in globals():
        global _rtc_init, _rtc_i2c, _rtc_buf, _rtc_time
        _rtc_i2c  = I2C(4, freq=100000); _rtc_buf = bytearray(7)
        _rtc_time = [0] * 7; _rtc_init = True
    _rtc_i2c.readfrom_mem_into(0x68, 0x00, _rtc_buf)
    def bcd(b): return (b >> 4) * 10 + (b & 0x0F)
    _rtc_time[5] = bcd(_rtc_buf[0]); _rtc_time[4] = bcd(_rtc_buf[1])
    _rtc_time[3] = bcd(_rtc_buf[2]); _rtc_time[2] = bcd(_rtc_buf[4])
    _rtc_time[1] = bcd(_rtc_buf[5] & 0x7F); _rtc_time[0] = bcd(_rtc_buf[6]) + 2000
    _rtc_time[6] = _rtc_buf[3]
    return _rtc_time

async def async_rtc():
    _t0("async_rtc")
    result = rtc()
    await asyncio.sleep_ms(0)
    _t1("async_rtc")
    return result


################################################################################
# 29. LCD (I2C PCF8574 — 16×2)
################################################################################

# def lcd(value, _state={"lcd": None}):
#     if _state["lcd"] is None:
#         class I2cLcd:
#             def __init__(self, i2c, addr):
#                 self.i2c = i2c; self.addr = addr; self.backlight = 0x08; self._init_lcd()
#             def _write(self, data): self.i2c.writeto(self.addr, bytes([data | self.backlight]))
#             def _pulse(self, data):
#                 self._write(data | 0x04); time.sleep_us(1)
#                 self._write(data & ~0x04); time.sleep_us(50)
#             def _send(self, value, mode):
#                 self._pulse((value & 0xF0) | mode); self._pulse(((value << 4) & 0xF0) | mode)
#             def command(self, cmd): self._send(cmd, 0)
#             def putchar(self, ch):  self._send(ord(ch), 0x01)
#             def clear(self):        self.command(0x01); time.sleep_ms(2)
#             def putstr(self, s):
#                 for ch in s: self.putchar(ch)
#             def _init_lcd(self):
#                 time.sleep_ms(50)
#                 for c in (0x33, 0x32, 0x28, 0x0C, 0x06): self.command(c)
#                 self.clear()
#         _state["lcd"] = I2cLcd(I2C(1, freq=100000), 0x27)
#     _state["lcd"].clear(); _state["lcd"].putstr(str(value))
# 
# async def async_lcd(value):
#     """Non-blocking LCD write. Yields once after write."""
#     _t0("async_lcd")
#     lcd(value)
#     await asyncio.sleep_ms(0)
#     _t1("async_lcd")
# 
################################################################################
# 29. LCD (I2C PCF8574 — 16x2)
################################################################################

################################################################################
# 29. LCD (I2C PCF8574 — 16x2)
################################################################################
# 
# _lcd_cache = {}
# _lcd_last_text = {}
# 
# 
# class I2cLcd:
# 
#     def __init__(self, i2c, addr):
# 
#         self.i2c = i2c
#         self.addr = addr
#         self.backlight = 0x08
# 
#         self._init_lcd()
# 
# 
#     def _write(self, data):
# 
#         self.i2c.writeto(
#             self.addr,
#             bytes([data | self.backlight])
#         )
# 
# 
#     def _pulse(self, data):
# 
#         self._write(data | 0x04)
#         time.sleep_us(1)
# 
#         self._write(data & ~0x04)
#         time.sleep_us(50)
# 
# 
#     def _send(self, value, mode):
# 
#         high = (value & 0xF0) | mode
#         low = ((value << 4) & 0xF0) | mode
# 
#         self._pulse(high)
#         self._pulse(low)
# 
# 
#     def command(self, cmd):
# 
#         self._send(cmd, 0)
# 
# 
#     def putchar(self, ch):
# 
#         self._send(ord(ch), 0x01)
# 
# 
#     def putstr(self, text):
# 
#         for ch in text:
#             self.putchar(ch)
# 
# 
#     def clear(self):
# 
#         self.command(0x01)
#         time.sleep_ms(3)
# 
# 
#     def move_to(self, col, row):
# 
#         if row == 0:
#             address = 0x80 + col
#         else:
#             address = 0xC0 + col
# 
#         self.command(address)
# 
# 
#     def _init_lcd(self):
# 
#         # Wait after power-up
#         time.sleep_ms(50)
# 
#         # ------------------------------------------------------
#         # Force HD44780 into known 4-bit mode
#         # ------------------------------------------------------
# 
#         self._pulse(0x30)
# # 
#         self._pulse(0x30)
#         time.sleep_ms(1)
# 
#         self._pulse(0x30)
#         time.sleep_ms(1)
# 
#         # Switch to 4-bit mode
#         self._pulse(0x20)
#         time.sleep_ms(1)
# 
#         # ------------------------------------------------------
#         # Normal LCD configuration
#         # ------------------------------------------------------
# 
#         self.command(0x28)   # 4-bit, 2-line, 5x8 font
#         time.sleep_ms(1)
# 
#         self.command(0x0C)   # Display ON, cursor OFF
#         time.sleep_ms(1)
# 
#         self.command(0x06)   # Cursor moves right
#         time.sleep_ms(1)
# 
#         self.command(0x01)   # Clear display
#         time.sleep_ms(3)
# 
# 
# 
# ################################################################################
# # LCD MAIN FUNCTION
# ################################################################################
# 
# def lcd(i2c_name, value):
# 
#     global _lcd_cache
#     global _lcd_last_text
# 
# 
#     # ------------------------------------------------------
#     # Select I2C bus
#     # ------------------------------------------------------
# 
#     if i2c_name == "I2C1":
#         bus = 1
# 
#     elif i2c_name == "I2C2":
#         bus = 2
# 
#     elif i2c_name == "I2C3":
#         bus = 3
# 
#     elif i2c_name == "I2C4":
#         bus = 4
# 
#     else:
# 
#         raise ValueError(
#             "Invalid I2C bus. Use I2C1, I2C2, I2C3 or I2C4"
#         )
# 
# 
#     # ------------------------------------------------------
#     # Create LCD only once
#     # ------------------------------------------------------
# 
#     if i2c_name not in _lcd_cache:
# 
#         i2c = I2C(
#             bus,
#             freq=100000
#         )
# 
#         _lcd_cache[i2c_name] = I2cLcd(
#             i2c,
#             0x27
#         )
# 
#         _lcd_last_text[i2c_name] = None
# 
# 
#     display = _lcd_cache[i2c_name]
# 
#     text = str(value)
# 
# 
#     # ------------------------------------------------------
#     # Do not rewrite same text continuously
#     # ------------------------------------------------------
# 
#     if _lcd_last_text[i2c_name] == text:
# 
#         return
# 
# 
#     _lcd_last_text[i2c_name] = text
# 
# 
#     # ------------------------------------------------------
#     # Clear and write text
#     # ------------------------------------------------------
# 
#     display.clear()
# 
# 
#     # First line
#     display.move_to(0, 0)
#     display.putstr(text[:16])
# 
# 
#     # Second line
#     if len(text) > 16:
# 
#         display.move_to(0, 1)
#         display.putstr(text[16:32])
# 
# 
# 
# ################################################################################
# # ASYNC LCD
# ################################################################################
# 
# async def async_lcd(i2c_name, value):
# 
#     _t0("async_lcd")
# 
#     lcd(i2c_name, value)
# 
#     await asyncio.sleep_ms(0)
# 
#     _t1("async_lcd")
################################################################################
# 30. LED
################################################################################

def led(pin_name, state):
    """Simple LED on/off. state: 1=ON, 0=OFF. Instant."""
    if "_led_cache" not in globals():
        global _led_cache; _led_cache = {}
    if pin_name not in _led_cache:
        _led_cache[pin_name] = Pin(pin_name, Pin.OUT)
    _led_cache[pin_name].value(1 if state else 0)

async def async_led(pin_name, state):
    _t0("async_led")
    led(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_led")

def _led_blink(pin_name, on_time, off_time):
    if "_led_cache" not in globals():
        global _led_cache; _led_cache = {}
    if pin_name not in _led_cache:
        _led_cache[pin_name] = Pin(pin_name, Pin.OUT)
    lpin = _led_cache[pin_name]
    if on_time == 0: lpin.value(0); return
    lpin.value(1); time.sleep(on_time)
    lpin.value(0)
    if off_time > 0: time.sleep(off_time)

def red_blink(pin_name, on_time, off_time):    _led_blink(pin_name, on_time, off_time)
def green_blink(pin_name, on_time, off_time):  _led_blink(pin_name, on_time, off_time)
def yellow_blink(pin_name, on_time, off_time): _led_blink(pin_name, on_time, off_time)

async def _async_led_blink(pin_name, on_time, off_time):
    if "_led_cache" not in globals():
        global _led_cache; _led_cache = {}
    if pin_name not in _led_cache:
        _led_cache[pin_name] = Pin(pin_name, Pin.OUT)
    lpin = _led_cache[pin_name]
    if on_time == 0: lpin.value(0); return
    lpin.value(1)
    await asyncio.sleep(on_time)              # yields — other tasks run
    lpin.value(0)
    if off_time > 0:
        await asyncio.sleep(off_time)         # yields — other tasks run

async def async_red_blink(pin_name, on_time, off_time):
    _t0("async_red_blink")
    await _async_led_blink(pin_name, on_time, off_time)
    _t1("async_red_blink")

async def async_green_blink(pin_name, on_time, off_time):
    _t0("async_green_blink")
    await _async_led_blink(pin_name, on_time, off_time)
    _t1("async_green_blink")

async def async_yellow_blink(pin_name, on_time, off_time):
    _t0("async_yellow_blink")
    await _async_led_blink(pin_name, on_time, off_time)
    _t1("async_yellow_blink")


################################################################################
# 32. COLOUR SENSOR (TCS34725)
################################################################################

def colour():
    if "_clr_init" not in globals():
        global _clr_init, _clr_i2c, _clr_buf, _clr_rgbc
        _clr_i2c  = I2C(4, freq=100000); _clr_buf = bytearray(8); _clr_rgbc = [0, 0, 0, 0]
        _clr_i2c.writeto_mem(0x29, 0x80 | 0x00, b'\x03')
        _clr_i2c.writeto_mem(0x29, 0x80 | 0x01, b'\xEB')
        _clr_init = True
    _clr_i2c.readfrom_mem_into(0x29, 0x80 | 0x14, _clr_buf)
    clear = (_clr_buf[1] << 8) | _clr_buf[0]; red   = (_clr_buf[3] << 8) | _clr_buf[2]
    green = (_clr_buf[5] << 8) | _clr_buf[4]; blue  = (_clr_buf[7] << 8) | _clr_buf[6]
    if clear > 0:
        _clr_rgbc[0] = (red   * 255) // clear; _clr_rgbc[1] = (green * 255) // clear
        _clr_rgbc[2] = (blue  * 255) // clear; _clr_rgbc[3] = clear
    else:
        _clr_rgbc[0] = _clr_rgbc[1] = _clr_rgbc[2] = _clr_rgbc[3] = 0
    return _clr_rgbc

async def async_colour():
    _t0("async_colour")
    result = colour()
    await asyncio.sleep_ms(0)
    _t1("async_colour")
    return result


################################################################################
# 33. FLEX SENSOR
################################################################################

_FLEX_VREF = 3.3

def flex(pin_name):
    if "_flex2_cache" not in globals():
        global _flex2_cache; _flex2_cache = {}
    if pin_name not in _flex2_cache:
        _flex2_cache[pin_name] = ADC(Pin(pin_name))
    v = (_flex2_cache[pin_name].read_u16() / 65535) * _FLEX_VREF
    if v < 0.20:   return "NO FORCE"
    elif v < 0.60: return "VERY LIGHT"
    elif v < 1.20: return "LIGHT"
    elif v < 2.00: return "MEDIUM"
    elif v < 2.80: return "HIGH"
    else:          return "MAX FORCE"

async def async_flex(pin_name):
    _t0("async_flex")
    result = flex(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_flex")
    return result


################################################################################
# 34. TURBIDITY SENSOR
################################################################################

def waterturbidity(pin_name):
    if "_turb_init" not in globals():
        global _turb_init, _turb_adcs, _VREF, _SAMP, _CLEAR_V, _CLOUDY_V
        _turb_adcs = {}; _VREF = 3.3; _SAMP = 20; _CLEAR_V = 2.5; _CLOUDY_V = 1.5
        _turb_init = True
    if pin_name not in _turb_adcs:
        _turb_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _turb_adcs[pin_name]
    total = 0
    for _ in range(_SAMP):
        total += sensor.read_u16(); time.sleep_ms(10)
    v = (total // _SAMP) * _VREF / 65535
    if v >= _CLEAR_V:  return "CLEAR"
    elif v >= _CLOUDY_V: return "CLOUDY"
    else: return "DIRTY"

async def async_waterturbidity(pin_name):
    """Non-blocking turbidity. Yields every 5ms sample."""
    _t0("async_waterturbidity")
    if "_turb_init" not in globals():
        global _turb_init, _turb_adcs, _VREF, _SAMP, _CLEAR_V, _CLOUDY_V
        _turb_adcs = {}; _VREF = 3.3; _SAMP = 20; _CLEAR_V = 2.5; _CLOUDY_V = 1.5
        _turb_init = True
    if pin_name not in _turb_adcs:
        _turb_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _turb_adcs[pin_name]
    total = 0
    for _ in range(_SAMP):
        total += sensor.read_u16()
        await asyncio.sleep_ms(5)                      # yields here
    v = (total // _SAMP) * _VREF / 65535
    _t1("async_waterturbidity")
    if v >= _CLEAR_V:  return "CLEAR"
    elif v >= _CLOUDY_V: return "CLOUDY"
    else: return "DIRTY"


################################################################################
# 35. LOAD CELL (HX711)
################################################################################

def load_cell(data_pin, clock_pin, calibrate=1.0):
    if "_hx_init" not in globals():
        global _hx_init, _hx_data, _hx_clk, _hx_offset
        _hx_data = machine.Pin(data_pin, machine.Pin.IN)
        _hx_clk  = machine.Pin(clock_pin, machine.Pin.OUT)
        _hx_clk.low(); _hx_offset = 0
        total = 0
        for _ in range(5):
            while _hx_data.value(): pass
            val = 0
            for _ in range(24):
                _hx_clk.high(); val = (val << 1) | _hx_data.value(); _hx_clk.low()
            _hx_clk.high(); _hx_clk.low(); total += (val ^ 0x800000)
        _hx_offset = total // 5; _hx_init = True
    total_raw = 0
    for _ in range(5):
        while _hx_data.value(): pass
        raw = 0
        for _ in range(24):
            _hx_clk.high(); raw = (raw << 1) | _hx_data.value(); _hx_clk.low()
        _hx_clk.high(); _hx_clk.low(); total_raw += (raw ^ 0x800000) - _hx_offset
    return (total_raw // 5) / calibrate

async def async_load_cell(data_pin, clock_pin, calibrate=1.0):
    _t0("async_load_cell")
    result = load_cell(data_pin, clock_pin, calibrate)
    await asyncio.sleep_ms(0)
    _t1("async_load_cell")
    return result


################################################################################
# 37. PIEZO VIBRATION SENSOR
################################################################################

def vibration_sensor(pin_name):
    if "_vib_init" not in globals():
        global _vib_init, _vib_pins, _last_tap_time
        _vib_pins = {}; _last_tap_time = 0; _vib_init = True
    if pin_name not in _vib_pins:
        _vib_pins[pin_name] = Pin(pin_name, Pin.IN)
    now = time.ticks_ms()
    if _vib_pins[pin_name].value() == 1:
        if time.ticks_diff(now, _last_tap_time) > 300:
            _last_tap_time = now; return "TAP"
    return "NO_TAP"

async def async_vibration_sensor(pin_name):
    _t0("async_vibration_sensor")
    result = vibration_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_vibration_sensor")
    return result


################################################################################
# 38. GAS SENSOR (MQ series)
################################################################################

def gas_sensor(pin_name):
    if "_gas_init" not in globals():
        global _gas_init, _gas_adcs, _GAS_LIMIT
        _gas_adcs = {}; _GAS_LIMIT = 25000; _gas_init = True
    if pin_name not in _gas_adcs:
        _gas_adcs[pin_name] = ADC(Pin(pin_name))
    raw = _gas_adcs[pin_name].read_u16()
    if raw > (_GAS_LIMIT + 10000): return "DANGER"
    elif raw > _GAS_LIMIT:         return "WARNING"
    else:                          return "CLEAN"

async def async_gas_sensor(pin_name):
    _t0("async_gas_sensor")
    result = gas_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_gas_sensor")
    return result


################################################################################
# 39. SERVO MOTOR  (software PWM — no timer conflict)
#
# Original used pyb.Timer(2) which conflicts with motor_speed Timer(1).
# Software bit-bang: 5 pulses × 20ms = 100ms, servo reaches angle and holds.
# Pulse: 500µs=0°  1500µs=90°  2500µs=180°
################################################################################

def servo(pin_name, angle):
    if "_svo_cache" not in globals():
        global _svo_cache; _svo_cache = {}
    if pin_name not in _svo_cache:
        _svo_cache[pin_name] = Pin(pin_name, Pin.OUT)
    pin      = _svo_cache[pin_name]
    angle    = max(0, min(180, angle))
    pulse_us = 500 + int(angle * 2000 // 180)
    low_us   = 20000 - pulse_us
    for _ in range(5):
        pin.value(1); time.sleep_us(pulse_us)
        pin.value(0); time.sleep_us(low_us)

async def async_servo(pin_name, angle):
    """Non-blocking servo. HIGH kept sync (µs precision).
    LOW converted to await sleep_ms — yields 5 times."""
    _t0("async_servo")
    if "_svo_cache" not in globals():
        global _svo_cache; _svo_cache = {}
    if pin_name not in _svo_cache:
        _svo_cache[pin_name] = Pin(pin_name, Pin.OUT)
    pin      = _svo_cache[pin_name]
    angle    = max(0, min(180, angle))
    pulse_us = 500 + int(angle * 2000 // 180)
    low_ms   = max(1, (20000 - pulse_us) // 1000)
    for _ in range(5):
        pin.value(1); time.sleep_us(pulse_us)
        pin.value(0)
        await asyncio.sleep_ms(low_ms)                 # yields here
    _t1("async_servo")

async def async_servo_move(pin_name, angle1, delay_ms, angle2):
    """Non-blocking servo sweep: angle1 → yield delay_ms → angle2."""
    _t0("async_servo_move")
    await async_servo(pin_name, angle1)
    await asyncio.sleep_ms(delay_ms)
    await async_servo(pin_name, angle2)
    _t1("async_servo_move")


################################################################################
# 40. GSM SIM MODULE
################################################################################

def GSM(uart_num, phone_number, message):
    if "_gsm_init" not in globals():
        global _gsm_init, _gsm_uart
        _gsm_uart = machine.UART(uart_num, baudrate=9600); _gsm_init = True
    def send_at(cmd, wait_ms=1000):
        _gsm_uart.write(cmd + "\r\n"); time.sleep_ms(wait_ms)
        if _gsm_uart.any(): _gsm_uart.read()
    send_at("AT"); send_at("AT+CMGF=1"); send_at('AT+CPMS="SM","SM","SM"')
    _gsm_uart.write('AT+CMGS="{}"\r\n'.format(phone_number))
    start = time.ticks_ms(); got_prompt = False
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        if _gsm_uart.any():
            if b'>' in _gsm_uart.read(): got_prompt = True; break
    if not got_prompt: return "ERROR: NO PROMPT"
    _gsm_uart.write(message); _gsm_uart.write(bytes([26]))
    time.sleep_ms(5000); return "SENT"

async def async_GSM(uart_num, phone_number, message):
    """Non-blocking GSM send. All AT command waits replaced with await."""
    _t0("async_GSM")
    if "_gsm_init" not in globals():
        global _gsm_init, _gsm_uart
        _gsm_uart = machine.UART(uart_num, baudrate=9600); _gsm_init = True
    async def send_at(cmd, wait_ms=1000):
        _gsm_uart.write(cmd + "\r\n")
        await asyncio.sleep_ms(wait_ms)                # yields here
        if _gsm_uart.any(): _gsm_uart.read()
    await send_at("AT"); await send_at("AT+CMGF=1"); await send_at('AT+CPMS="SM","SM","SM"')
    _gsm_uart.write('AT+CMGS="{}"\r\n'.format(phone_number))
    start = time.ticks_ms(); got_prompt = False
    while time.ticks_diff(time.ticks_ms(), start) < 5000:
        if _gsm_uart.any():
            if b'>' in _gsm_uart.read(): got_prompt = True; break
        await asyncio.sleep_ms(10)                     # yields here
    if not got_prompt: _t1("async_GSM"); return "ERROR: NO PROMPT"
    _gsm_uart.write(message); _gsm_uart.write(bytes([26]))
    await asyncio.sleep_ms(5000)                       # yields here
    _t1("async_GSM"); return "SENT"


################################################################################
# 41. GPS (NMEA $GPRMC)
################################################################################

def gps(uart_num):
    if "_gps_init" not in globals():
        global _gps_init, _gps_uart, _gps_data
        _gps_uart = machine.UART(uart_num, baudrate=9600)
        _gps_data = [0.0, 0.0, 0.0]; _gps_init = True
    if not _gps_uart.any(): return None
    line = _gps_uart.readline()
    if line and line.startswith(b'$GPRMC'):
        try:
            p = line.decode().split(',')
            if p[2] == 'A':
                lat_r = float(p[3]); ld = int(lat_r/100)
                _gps_data[0] = ld + (lat_r - ld*100) / 60
                if p[4] == 'S': _gps_data[0] *= -1
                lon_r = float(p[5]); lo = int(lon_r/100)
                _gps_data[1] = lo + (lon_r - lo*100) / 60
                if p[6] == 'W': _gps_data[1] *= -1
                _gps_data[2] = float(p[7]) * 1.852
                return _gps_data
        except: pass
    return None

async def async_gps(uart_num):
    _t0("async_gps")
    result = gps(uart_num)
    await asyncio.sleep_ms(0)
    _t1("async_gps")
    return result


################################################################################
# 42. CAPACITIVE TOUCH SENSOR (TTP223)
################################################################################

def touch_sensor(pin_name, toggle=False):
    if "_t_init" not in globals():
        global _t_init, _t_pins, _t_states, _t_last
        _t_pins = {}; _t_states = {}; _t_last = {}; _t_init = True
    if pin_name not in _t_pins:
        _t_pins[pin_name] = Pin(pin_name, Pin.IN)
        _t_states[pin_name] = False; _t_last[pin_name] = 0
    is_touched = _t_pins[pin_name].value() == 1
    if toggle:
        now = time.ticks_ms()
        if is_touched and time.ticks_diff(now, _t_last[pin_name]) > 500:
            _t_states[pin_name] = not _t_states[pin_name]; _t_last[pin_name] = now
        return _t_states[pin_name]
    return is_touched

async def async_touch_sensor(pin_name, toggle=False):
    _t0("async_touch_sensor")
    result = touch_sensor(pin_name, toggle)
    await asyncio.sleep_ms(0)
    _t1("async_touch_sensor")
    return result


################################################################################
# 43. PELTIER
################################################################################

def peltier(state, mode, pin_a, pin_b):
    if "_pel_init" not in globals():
        global _pel_init, _p_pins
        _p_pins = {"A": Pin(pin_a, Pin.OUT), "B": Pin(pin_b, Pin.OUT)}; _pel_init = True
    if not state:
        _p_pins["A"].low(); _p_pins["B"].low(); return "OFF"
    m = mode.upper()
    if m == "COOLING":
        _p_pins["A"].high(); _p_pins["B"].low(); return "COOLING_ACTIVE"
    elif m == "HOT":
        _p_pins["A"].low(); _p_pins["B"].high(); return "HEATING_ACTIVE"

async def async_peltier(state, mode, pin_a, pin_b):
    _t0("async_peltier")
    result = peltier(state, mode, pin_a, pin_b)
    await asyncio.sleep_ms(0)
    _t1("async_peltier")
    return result


################################################################################
# 44. SOUND SENSOR
################################################################################

def sound(pin_name):
    if "_snd_cache" not in globals():
        global _snd_cache; _snd_cache = {}
    if pin_name not in _snd_cache:
        _snd_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_UP)
    return _snd_cache[pin_name].value()

async def async_sound(pin_name):
    _t0("async_sound")
    result = sound(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_sound")
    return result


################################################################################
# 45. DTMF (MT8870)
################################################################################

def DTMF(std_pin, q1, q2, q3, q4):
    if "_dtmf_init" not in globals():
        global _dtmf_init, _d_std, _d_pins, _d_map
        _d_std  = Pin(std_pin, Pin.IN)
        _d_pins = [Pin(q, Pin.IN) for q in (q1, q2, q3, q4)]
        _d_map  = {1:'1',2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',
                   9:'9',10:'0',11:'*',12:'#',13:'A',14:'B',15:'C',0:'D'}
        _dtmf_init = True
    if _d_std.value() == 1:
        val = 0
        for i, p in enumerate(_d_pins):
            if p.value(): val |= (1 << i)
        while _d_std.value() == 1: pass
        return _d_map.get(val, None)
    return None

async def async_DTMF(std_pin, q1, q2, q3, q4):
    _t0("async_DTMF")
    result = DTMF(std_pin, q1, q2, q3, q4)
    await asyncio.sleep_ms(0)
    _t1("async_DTMF")
    return result


################################################################################
# 46. GSR SKIN SENSOR
################################################################################

def gsr_sensor(pin_name):
    if "_gsr_init" not in globals():
        global _gsr_init, _gsr_adcs, _gsr_samples
        _gsr_adcs = {}; _gsr_samples = 5; _gsr_init = True
    if pin_name not in _gsr_adcs:
        _gsr_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _gsr_adcs[pin_name]
    total = 0
    for _ in range(_gsr_samples):
        total += sensor.read_u16(); time.sleep_ms(2)
    raw = total // _gsr_samples
    if raw > 45000:   return "HIGH_STRESS"
    elif raw > 30000: return "AROUSED"
    else:             return "RELAXED"

async def async_gsr_sensor(pin_name):
    """Non-blocking GSR. Yields every 2ms sample."""
    _t0("async_gsr_sensor")
    if "_gsr_init" not in globals():
        global _gsr_init, _gsr_adcs, _gsr_samples
        _gsr_adcs = {}; _gsr_samples = 5; _gsr_init = True
    if pin_name not in _gsr_adcs:
        _gsr_adcs[pin_name] = ADC(Pin(pin_name))
    sensor = _gsr_adcs[pin_name]
    total = 0
    for _ in range(_gsr_samples):
        total += sensor.read_u16()
        await asyncio.sleep_ms(2)                      # yields here
    raw = total // _gsr_samples
    _t1("async_gsr_sensor")
    if raw > 45000:   return "HIGH_STRESS"
    elif raw > 30000: return "AROUSED"
    else:             return "RELAXED"

################################################################################
# END OF lib.py
################################################################################
 
# 
# async def async_ai_output(selection):
#     """
#     Self-contained UART filter.
#     Handles line-based text (Face, Color, QR) and packet-based data (Line Following).
#     """
#     # 1. Initialize UART(3) inside the function
#     uart = machine.UART(3, baudrate=115200)
#     
#     # 2. Clean the input selection string
#     key = selection.lower().strip().replace(" ", "_")
#     print(f"UART Filter Started: {selection}")
# 
#     buffer = ""
# 
#     while True:
#         if uart.any():
#             raw = uart.read()
#             if raw:
#                 try:
#                     data = raw.decode("utf-8")
#                     for ch in data:
#                         # Process characters into a buffer until a line-end or packet-end
#                         if ch == '\n' or ch == '\r' or ch == '#':
#                             if ch == '#': buffer += ch # Include '#' for packet parsing
#                             
#                             msg = buffer.strip()
#                             if not msg:
#                                 buffer = ""
#                                 continue
# 
#                             # --- LINE FOLLOWING FILTER ($left,right#) ---
#                             if key == "line_following" and msg.startswith("$") and msg.endswith("#"):
#                                 body = msg[1:-1] # Remove $ and #
#                                 parts = body.split(",")
#                                 if len(parts) == 2:
#                                     print(f"Line Speed -> Left: {parts[0]} Right: {parts[1]}")
# 
#                             # --- FACE DETECTION FILTER ---
#                             elif key == "face_detection" and msg.startswith("face_count:"):
#                                 count = msg.split(":")[1]
#                                 print("Faces detected:", count)
# 
#                             # --- COLOR RECOGNITION FILTER ---
#                             elif key == "color_delection" and msg.startswith("color_recog:"):
#                                 print("Color Data:", msg.split(":", 1)[1])
# 
#                             # --- MULTI-COLOR FILTER ---
#                             elif key == "multi_color_recognition" and msg.startswith("multi_color:"):
#                                 print("RGB Values:", msg.split(":", 1)[1])
# 
#                             # --- ITEM COUNT FILTER ---
#                             elif key == "same_color_object_counting" and msg.startswith("item_count:"):
#                                 print("Total Items:", msg.split(":", 1)[1])
# 
#                             # --- QR CODE FILTER ---
#                             elif key == "qr_code_recognition" and msg.startswith("qrcode:"):
#                                 print("QR Content:", msg.split(":", 1)[1])
# 
#                             # --- GENERIC STREAM (Live Camera / Train) ---
#                             elif key in ["train", "live_camera"]:
#                                 print(f"Stream: {msg}")
# 
#                             buffer = "" # Reset buffer after processing
#                         else:
#                             buffer += ch
#                             if len(buffer) > 128: # Prevent memory overflow
#                                 buffer = ""
#                 except:
#                     buffer = ""
# 
#         # Yield to system to prevent blocking
#         await asyncio.sleep_ms(20)

#######################################################################################################################

# async def async_ai_block(selection):
#     # 1. Setup hardware and map inside the function
#     uart = machine.UART(3, baudrate=115200)
#     
#     ai_map = {
#         "face_detection": "1",
#         "color_delection": "6",
#         "multi_color_recognition": "8",
#         "same_color_object_counting": "7",
#         "qr_code_recognition": "9",
#         "live_camera": "3",
#         "train": "4"
#     }
#    
#     # 2. Convert text to ID and send
#     key = selection.lower().strip().replace(" ", "_")
#     cmd_id = ai_map.get(key)
# 
#     if cmd_id:
#         uart.write(f"{cmd_id}\n")
#         print(f"Sent ID: {cmd_id}")
#     
#     # 3. Simple non-blocking delay
#         await asyncio.sleep_ms(100)


# ============================================================
# K230 IMAGE CLASSIFICATION & RESULT CHECK
# ============================================================
from machine import Pin, I2C, ADC, UART, SPI
import machine
import time
import pyb
import gc
import math
try:
    import system_status
except ImportError:
    system_status = None
import uasyncio as asyncio



# ---- live AI result on the DWIN display (AI PROJECTS pages 52-55) ------------
# The classify functions below call _ai_live_start(mode): the display opens that
# AI page. Their background readers call _ai_live_line(text) for every line from
# the K230: the page's LIVE RESULT panel (dot list at VP 0x5400, drawn by
# dwin_screen._dw_gesture_show) shows the label, the confidence and, about once
# a second, the raw line. It only draws while that page is on screen, because
# 0x5400 is shared with the keyboards and the sensor cards.
_AI_PAGES = {"image": 52, "voice": 53, "pose": 54, "gesture": 55}
_ai_live = {"mode": None, "shown": None, "line_t": 0, "page": None, "page_t": 0, "blank": None}
# All four AI pages show the same dot list (0x5400). So another AI page than the
# running mode's says NOT ACTIVE, and with no program running (dwin_wifi_ui
# calls _ai_live_idle) an AI page says NOT RUNNING, instead of an old result.


def _ai_live_parse(text):
    """'Detected: Class1 (93.5%)' -> ('CLASS1', '93.5%'); 'not detected' ->
    ('NOT DETECTED', ''); a raw word ('forward', 'pose1') -> ('FORWARD', '')."""
    low = text.lower()
    if low.startswith("not detected") or low in ("none", "unknown"):
        return "NOT DETECTED", ""
    if ":" in text:
        head, rest = text.split(":", 1)
        rest = rest.strip()
        try:                                            # 'dog:88' / 'dog:0.88'
            v = float(rest.replace("%", ""))
            return head.strip().upper(), "%.1f%%" % (v * 100 if v <= 1 else v)
        except ValueError:
            pass
        j = rest.find("(")
        if j >= 0:
            return rest[:j].strip().upper(), rest[j + 1:].replace(")", "").strip()
        return rest.upper(), ""
    if "(" in text:                                     # 'cat (93%)'
        j = text.find("(")
        return text[:j].strip().upper(), text[j + 1:].replace(")", "").strip()
    if "," in text:                                     # 'cat,0.93'
        name, rest = text.split(",", 1)
        try:
            v = float(rest.strip())
            return name.strip().upper(), "%.1f%%" % (v * 100 if v <= 1 else v)
        except ValueError:
            return name.strip().upper(), rest.strip()
    return text.upper(), ""


def _ai_live_start(mode):
    _ai_live["mode"], _ai_live["shown"], _ai_live["page"] = mode, None, _AI_PAGES[mode]
    try:
        import dwin_screen as dw
        dw.dwin_page(_AI_PAGES[mode])
        dw._dw_gesture_show("waiting...", "", "AI camera: %s classification" % mode)
    except Exception as e:
        print("ai live:", e)


def _ai_live_line(text):
    mode = _ai_live["mode"]
    if mode is None or not text:
        return
    try:
        import dwin_screen as dw
        now = time.ticks_ms()
        if time.ticks_diff(now, _ai_live["page_t"]) > 500:      # which page is on screen
            p = dw._dw_read(0x0014, 1)
            _ai_live["page_t"] = now
            if p:
                if p[0] != _ai_live["page"]:
                    _ai_live["shown"] = None                     # redraw all when it comes back
                _ai_live["page"] = p[0]
        page = _ai_live["page"]
        if page != _AI_PAGES[mode]:
            if page in (52, 53, 54, 55) and _ai_live["blank"] != page:
                dw._dw_gesture_show("NOT ACTIVE", "", "%s classification is running" % mode.upper())
                _ai_live["blank"] = page
            return
        _ai_live["blank"] = None
        res = _ai_live_parse(text)
        if res != _ai_live["shown"]:
            dw._dw_gesture_show(res[0], res[1], text)
            _ai_live["shown"], _ai_live["line_t"] = res, now
        elif time.ticks_diff(now, _ai_live["line_t"]) > 1000:  # raw line about once a second
            dw._dw_gesture_show(None, None, text)
            _ai_live["line_t"] = now
    except Exception as e:
        print("ai live:", e)


def _ai_live_idle(page):
    """No program running: the AI page that was just opened says so."""
    try:
        import dwin_screen as dw
        dw._dw_gesture_show("NOT RUNNING", "", "run a program with the AI blocks")
        _ai_live["shown"], _ai_live["blank"] = None, page
    except Exception as e:
        print("ai live:", e)


async def async__k230_get_ai_classify_image(selection):
    """
    Sends the default command '4' followed by the parsed class ID.
    Example: selection="class 1" -> sends '4', then sends '1'
    """
    _ai_live_start("image")
    uart = machine.UART(1, baudrate=115200)
    # 1. Send the default command '4' first
    uart.write("4\n")
    
    # 2. Extract the number from the selection (e.g., "class 2" -> "2")
    # This removes the word "class" and any extra spaces
    class_id = selection.lower().replace("class", "").strip()
     
    # 3. Send the class ID if it exists
    if class_id:
        uart.write(f"{class_id}\n")
        print(f"Sent Default: 4 | Sent Class ID: {class_id}")
    else:
        print("Error: No class ID provided in selection.")
    
    # 4. Non-blocking delay to let the hardware process
    await asyncio.sleep_ms(100)
    
    
# Minimal state holder (dict works on MicroPython; function attributes do not)
_state = {}


async def async__k230_result(selection):
    """
    Fully self-contained function:
    - Initializes UART on first call
    - Starts background reader on first call
    - Returns True if the camera currently sees `selection`, else False
    """
    # --- One-time setup on first call ---
    if "started" not in _state:
        _state["started"] = True
        _state["uart"] = machine.UART(1, baudrate=115200)
        _state["label"] = ""

        async def _uart_reader_task():
            buf = b""
            while True:
                if _state["uart"].any():
                    new_data = _state["uart"].read()
                    if new_data:
                        buf += new_data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode().strip()
                        if ":" in text:
                            label = text.split(":", 1)[1].split("(")[0].strip()
                            _state["label"] = label.lower()
                        elif text.lower().startswith("not detected"):
                            _state["label"] = ""         # nothing seen now
                        _ai_live_line(text)
                    except:
                        pass
                await asyncio.sleep_ms(5)

        asyncio.create_task(_uart_reader_task())
        await asyncio.sleep_ms(0)  # Let the reader initialize

    # --- Check if current label matches ---
    if _state["label"] == selection.lower():
        return True
    return False


###############################################################################################################################



# ---- ESP32-S3 camera board: image classification (UART1) -------------------
# Same jack as the K230 (MOD3 JACK 1, UART1 115200): one camera at a time.
# async__s3_get_ai_classify_image() sends "1" (start classifying) once per
# program run and opens the IMAGE CLASSIFICATION page; a background reader keeps
# the latest result and feeds the page's LIVE RESULT panel (_ai_live_line).
# async__s3_result(label) is True when the latest result is `label` (then it is
# cleared, so one detection counts once).
_s3 = {"uart": None, "label": "", "conf": 0, "trig_t": None, "gen": 0, "alive_t": 0}


def _s3_uart():
    if _s3["uart"] is None:
        _s3["uart"] = machine.UART(1, baudrate=115200)
    return _s3["uart"]


def _s3_parse(text):
    """'Detected: cat (93%)', 'cat (93%)', 'cat,0.93', 'cat:93' or 'cat' -> ('cat', 93.0)."""
    t = text.strip()
    if t.lower().startswith("not detected"):
        return "", 0
    if t.lower().startswith("detected:"):
        t = t[9:].strip()
    for sep in ("(", ",", ":"):
        if sep in t:
            name, rest = t.split(sep, 1)
            num = "".join(c for c in rest if c in "0123456789.")
            try:
                conf = float(num) if num else 0
            except ValueError:
                conf = 0
            if sep == "," and 0 < conf <= 1:
                conf *= 100                            # 0.93 -> 93 %
            return name.strip().lower(), conf
    return t.lower(), 0


def _s3_start_reader():
    """Start the reader unless one is running (a new PLAY needs a new one)."""
    if _s3["gen"] and time.ticks_diff(time.ticks_ms(), _s3["alive_t"]) < 500:
        return
    _s3["gen"] += 1
    gen = _s3["gen"]
    _s3["alive_t"] = time.ticks_ms()

    async def _reader():
        buf = b""
        u = _s3_uart()
        while gen == _s3["gen"]:                       # an older reader stops itself
            _s3["alive_t"] = time.ticks_ms()
            n = u.any()
            if n:
                buf += u.read(n)
                if len(buf) > 1024:
                    buf = buf[-256:]
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode().strip()
                    except Exception:
                        continue
                    if text:
                        _s3["label"], _s3["conf"] = _s3_parse(text)
                        _ai_live_line(text)
            await asyncio.sleep_ms(5)

    asyncio.create_task(_reader())


async def async__s3_get_ai_classify_image(label):
    """Start image classification on the ESP32-S3 camera board (UART1): sends
    '1' once per program run (repeated calls in a loop do not resend it) and
    opens the IMAGE CLASSIFICATION page on the display."""
    now = time.ticks_ms()
    first = _s3["trig_t"] is None or time.ticks_diff(now, _s3["trig_t"]) > 3000
    _s3["trig_t"] = now
    if first:
        _ai_live_start("image")
        try:
            _s3_uart().write(b"1\n")
            print("[ESP32-S3] Sent classification trigger '1'")
        except Exception as e:
            print("[ESP32-S3] Trigger write error:", e)
    _s3_start_reader()
    await asyncio.sleep_ms(100)


async def async__s3_result(label):
    """True if the ESP32-S3 camera's latest result is `label` (then cleared)."""
    _s3_start_reader()
    if _s3["label"] and _s3["label"] == str(label).strip().lower():
        _s3["label"], _s3["conf"] = "", 0
        return True
    await asyncio.sleep_ms(0)
    return False


async def async_voice_classify(selection):
    """
    Sends the default command '4' followed by the parsed class ID.
    Example: selection="class 1" -> sends '4', then sends '1'
    """
    _ai_live_start("voice")
    uart = machine.UART(1, baudrate=115200)
    # 1. Send the default command '4' first
    uart.write("15\n")
    
    # 2. Extract the number from the selection (e.g., "class 2" -> "2")
    # This removes the word "class" and any extra spaces
    class_id = selection.lower().replace("class", "").strip()
    
    # 3. Send the class ID if it exists
    if class_id:
        uart.write(f"{class_id}\n")
        print(f"Sent Default: 15 | Sent Class ID: {class_id}")
    else:
        print("Error: No class ID provided in selection.")
    
    # 4. Non-blocking delay to let the hardware process
    await asyncio.sleep_ms(100)
    

_voice_state = {}

async def async_voice_heard(selection):
    """
    Fully self-contained Voice function for raw text streams:
    - Initializes UART and background reader on the first call.
    - Captures raw strings directly (e.g., "word1", "forward", "stop").
    - Returns True if the raw string matches `selection`, then clears it.
    - Returns False immediately otherwise (non-blocking).
    """
    # --- One-time setup on first call ---
    if "started" not in _voice_state:
        _voice_state["started"] = True
        _voice_state["uart"] = machine.UART(1, baudrate=115200)  # Adjust UART ID/pins if needed
        _voice_state["phrase"] = ""

        async def _uart_reader_task():
            buf = b""
            while True:
                if _voice_state["uart"].any():
                    new_data = _voice_state["uart"].read()
                    if new_data:
                        buf += new_data
                
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        # Decode the raw line directly as the class name
                        text = line.decode().strip()
                        if text:  # Ensure it isn't an empty line
                            _voice_state["phrase"] = text.lower()
                            _ai_live_line(text)
                    except:
                        pass
                await asyncio.sleep_ms(5)

        asyncio.create_task(_uart_reader_task())
        await asyncio.sleep_ms(0)  # Yield briefly to let reader register

    # --- Check match and reset state ---
    if _voice_state["phrase"] == selection.lower():
        _voice_state["phrase"] = ""  # Clear it immediately so it doesn't double-trigger
        return True
        
    return False

##############################################################################################################################


# The same voice functions under the K230 names some Blockly pages generate
async__k230_voice_classify = async_voice_classify
async__k230_voice_heard = async_voice_heard


async def async_pose_classify(selection):
    """
    Sends the default command '4' followed by the parsed class ID.
    Example: selection="class 1" -> sends '4', then sends '1'
    """
    _ai_live_start("pose")
    uart = machine.UART(1, baudrate=115200)
    # 1. Send the default command '4' first
    uart.write("16\n")
    
    # 2. Extract the number from the selection (e.g., "class 2" -> "2")
    # This removes the word "class" and any extra spaces
    class_id = selection.lower().replace("class", "").strip()
    
    # 3. Send the class ID if it exists
    if class_id:
        uart.write(f"{class_id}\n")
        print(f"Sent Default: 16 | Sent Class ID: {class_id}")
    else:
        print("Error: No class ID provided in selection.")
    
    # 4. Non-blocking delay to let the hardware process
    await asyncio.sleep_ms(100)
    

_pose_state = {}

async def async_pose_detected(selection):
    """
    Self-contained Pose Detection function:
    - Optimized specifically for raw 'pose1' or 'pose2' text streams.
    - Provisions UART and spins up the background reader on the very first call.
    - Returns True immediately on a match, then cleans the match state.
    - Returns False immediately otherwise (non-blocking).
    """
    global _pose_state
    
    # --- One-time hardware & background worker provision ---
    if "started" not in _pose_state:
        _pose_state["started"] = True
        _pose_state["uart"] = machine.UART(1, baudrate=115200) # Adjust UART ID/pins if needed
        _pose_state["active_pose"] = ""

        async def _uart_reader_task():
            buf = b""
            while True:
                if _pose_state["uart"].any():
                    new_data = _pose_state["uart"].read()
                    if new_data:
                        buf += new_data
                
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode().strip()
                        if text:  # Save the raw line directly as the active pose
                            _pose_state["active_pose"] = text.lower()
                            _ai_live_line(text)
                    except:
                        pass
                await asyncio.sleep_ms(5)

        asyncio.create_task(_uart_reader_task())
        await asyncio.sleep_ms(0) # Give the event loop a tick to spin up the task

    # --- Match Validation and Auto-Reset ---
    if _pose_state["active_pose"] == selection.lower():
        _pose_state["active_pose"] = "" # Clear state to prevent loop multi-firing
        return True
        
    return False

##############################################################################################################################


async def async__k230_gesture_classify(selection):
    """
    Sends the default command '19' (handpose_classifier) followed by the parsed class ID.
    """
    _ai_live_start("gesture")
    uart = machine.UART(1, baudrate=115200)
    uart.write("19\n")

    class_id = selection.lower().replace("class", "").strip()
    if class_id:
        uart.write(f"{class_id}\n")
        print(f"Sent Default: 19 | Sent Class ID: {class_id}")
    else:
        print("Error: No class ID provided in selection.")

    await asyncio.sleep_ms(100)


_gesture_state = {}

async def async__k230_gesture_detected(selection):
    """
    Self-contained K230 Gesture Detection function:
    - Provisions UART(1) and spins up the background reader on the first call.
    - Accepts both 'Detected: <label> (<conf>%)' and raw '<label>' lines.
    - Returns True immediately on a match, then clears the match state.
    - Returns False immediately otherwise (non-blocking).
    """
    global _gesture_state

    if "started" not in _gesture_state:
        _gesture_state["started"] = True
        _gesture_state["uart"] = machine.UART(1, baudrate=115200)
        _gesture_state["active_gesture"] = ""

        async def _uart_reader_task():
            buf = b""
            while True:
                if _gesture_state["uart"].any():
                    new_data = _gesture_state["uart"].read()
                    if new_data:
                        buf += new_data

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode().strip()
                        if text:
                            _ai_live_line(text)
                            if ":" in text:
                                text = text.split(":", 1)[1].split("(")[0].strip()
                            low = text.lower()
                            if low not in ("not detected", "none", "unknown"):
                                _gesture_state["active_gesture"] = low
                    except:
                        pass
                await asyncio.sleep_ms(5)

        asyncio.create_task(_uart_reader_task())
        await asyncio.sleep_ms(0)

    if _gesture_state["active_gesture"] == selection.lower():
        _gesture_state["active_gesture"] = ""
        return True

    return False

async_gesture_classify = async__k230_gesture_classify
async_gesture_detected = async__k230_gesture_detected



################################################################################
# 14. PIR SENSOR
################################################################################

def pir_sensor(pin_name):
    if "_pir_cache" not in globals():
        global _pir_cache; _pir_cache = {}
    if pin_name not in _pir_cache:
        _pir_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _pir_cache[pin_name].value()

async def async_pir_sensor(pin_name):
    _t0("async_pir_sensor")
    result = pir_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_pir_sensor")
    return result


################################################################################
# 15. MICROWAVE RADAR (RCWL0516)
################################################################################

def radar_sensor(pin_name):
    if "_radar_cache" not in globals():
        global _radar_cache; _radar_cache = {}
    if pin_name not in _radar_cache:
        _radar_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _radar_cache[pin_name].value()

async def async_radar_sensor(pin_name):
    _t0("async_radar_sensor")
    result = radar_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_radar_sensor")
    return result


################################################################################
# 16. PIEZO VIBRATION SENSOR
################################################################################

def vibration_sensor(pin_name):
    if "_vib_cache" not in globals():
        global _vib_cache; _vib_cache = {}
    if pin_name not in _vib_cache:
        _vib_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _vib_cache[pin_name].value()

async def async_vibration_sensor(pin_name):
    _t0("async_vibration_sensor")
    result = vibration_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_vibration_sensor")
    return result


################################################################################
# 17. SOUND SENSOR
################################################################################

def sound_sensor(pin_name):
    if "_sound_cache" not in globals():
        global _sound_cache; _sound_cache = {}
    if pin_name not in _sound_cache:
        _sound_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _sound_cache[pin_name].value()

async def async_sound_sensor(pin_name):
    _t0("async_sound_sensor")
    result = sound_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_sound_sensor")
    return result


################################################################################
# 18. CAPACITIVE MOISTURE SENSOR (ANALOG)
################################################################################

def moisture_sensor(pin_name):
    if "_moist_cache" not in globals():
        global _moist_cache; _moist_cache = {}
    if pin_name not in _moist_cache:
        _moist_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _moist_cache[pin_name].read_u16()
    moisture_level = int((raw_value * 100) / 65535)
    return moisture_level

async def async_moisture_sensor(pin_name):
    _t0("async_moisture_sensor")
    result = moisture_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_moisture_sensor")
    return result


################################################################################
# 19. FORCE SENSOR (ANALOG)
################################################################################

def force_sensor(pin_name):
    if "_force_cache" not in globals():
        global _force_cache; _force_cache = {}
    if pin_name not in _force_cache:
        _force_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _force_cache[pin_name].read_u16()
    force_level = int((raw_value * 100) / 65535)
    return force_level

async def async_force_sensor(pin_name):
    _t0("async_force_sensor")
    result = force_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_force_sensor")
    return result


################################################################################
# 20. MQ135 GAS SENSOR (ANALOG)
################################################################################

def gas_sensor(pin_name):
    if "_gas_cache" not in globals():
        global _gas_cache; _gas_cache = {}
    if pin_name not in _gas_cache:
        _gas_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _gas_cache[pin_name].read_u16()
    gas_level = int((raw_value * 100) / 65535)
    return gas_level

async def async_gas_sensor(pin_name):
    _t0("async_gas_sensor")
    result = gas_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_gas_sensor")
    return result


################################################################################
# 21. SOLENOID LOCK (DIGITAL OUTPUT)
################################################################################

def solenoid(pin_name, state):
    if "_solenoid_cache" not in globals():
        global _solenoid_cache; _solenoid_cache = {}
    if pin_name not in _solenoid_cache:
        _solenoid_cache[pin_name] = Pin(pin_name, Pin.OUT, value=0)
        
    if state:
        _solenoid_cache[pin_name].high()
    else:
        _solenoid_cache[pin_name].low()

async def async_solenoid(pin_name, state):
    _t0("async_solenoid")
    solenoid(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_solenoid")


################################################################################
# 22. BUZZER
################################################################################

# def buzzer(pin_name, state):
#     if "_buzzer_cache" not in globals():
#         global _buzzer_cache; _buzzer_cache = {}
#     if pin_name not in _buzzer_cache:
#         _buzzer_cache[pin_name] = Pin(pin_name, Pin.OUT, value=0)
#         
#     _buzzer_cache[pin_name].value(1 if state else 0)
# 
# async def async_buzzer(pin_name, state):
#     _t0("async_buzzer")
#     buzzer(pin_name, state)
#     await asyncio.sleep_ms(0)
#     _t1("async_buzzer")
# 

################################################################################
# 23. SINGLE RELAY MODULE
################################################################################

def relay_single(pin_name, state):
    if "_relay_cache" not in globals():
        global _relay_cache; _relay_cache = {}
    if pin_name not in _relay_cache:
        _relay_cache[pin_name] = Pin(pin_name, Pin.OUT, value=0)
        
    _relay_cache[pin_name].value(1 if state else 0)

async def async_relay_single(pin_name, state):
    _t0("async_relay_single")
    relay_single(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_relay_single")


################################################################################
# 24. BASIC LED MODULE
################################################################################

def basic_led(pin_name, state):
    if "_led_cache" not in globals():
        global _led_cache; _led_cache = {}
    if pin_name not in _led_cache:
        _led_cache[pin_name] = Pin(pin_name, Pin.OUT, value=0)
        
    _led_cache[pin_name].value(1 if state else 0)

async def async_basic_led(pin_name, state):
    _t0("async_basic_led")
    basic_led(pin_name, state)
    await asyncio.sleep_ms(0)
    _t1("async_basic_led")


################################################################################
# 25. TDS METER (WATER QUALITY) - ANALOG
################################################################################

def tds_meter(pin_name):
    if "_tds_cache" not in globals():
        global _tds_cache; _tds_cache = {}
    if pin_name not in _tds_cache:
        _tds_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _tds_cache[pin_name].read_u16()
    tds_percent = int((raw_value * 100) / 65535)
    return tds_percent

async def async_tds_meter(pin_name):
    _t0("async_tds_meter")
    result = tds_meter(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_tds_meter")
    return result


################################################################################
# 26. PH SENSOR - ANALOG
################################################################################

def ph_sensor(pin_name):
    if "_ph_cache" not in globals():
        global _ph_cache; _ph_cache = {}
    if pin_name not in _ph_cache:
        _ph_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _ph_cache[pin_name].read_u16()
    ph_percent = int((raw_value * 100) / 65535)
    return ph_percent

async def async_ph_sensor(pin_name):
    _t0("async_ph_sensor")
    result = ph_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_ph_sensor")
    return result


################################################################################
# 27. THERMISTOR (ANALOG TEMPERATURE)
################################################################################

def thermistor(pin_name):
    if "_therm_cache" not in globals():
        global _therm_cache; _therm_cache = {}
    if pin_name not in _therm_cache:
        _therm_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _therm_cache[pin_name].read_u16()
    therm_percent = int((raw_value * 100) / 65535)
    return therm_percent

async def async_thermistor(pin_name):
    _t0("async_thermistor")
    result = thermistor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_thermistor")
    return result


################################################################################
# 28. FLEX SENSOR - ANALOG
################################################################################

def flex_sensor(pin_name):
    if "_flex_cache" not in globals():
        global _flex_cache; _flex_cache = {}
    if pin_name not in _flex_cache:
        _flex_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _flex_cache[pin_name].read_u16()
    flex_percent = int((raw_value * 100) / 65535)
    return flex_percent

async def async_flex_sensor(pin_name):
    _t0("async_flex_sensor")
    result = flex_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_flex_sensor")
    return result


################################################################################
# 29. ROTATION SENSOR (POTENTIOMETER) - ANALOG
################################################################################

def rotation_sensor(pin_name):
    if "_rot_cache" not in globals():
        global _rot_cache; _rot_cache = {}
    if pin_name not in _rot_cache:
        _rot_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _rot_cache[pin_name].read_u16()
    rotation_percent = int((raw_value * 100) / 65535)
    return rotation_percent

async def async_rotation_sensor(pin_name):
    _t0("async_rotation_sensor")
    result = rotation_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_rotation_sensor")
    return result


################################################################################
# 30. MEMS MICROPHONE - ANALOG ENVELOPE
################################################################################

def mems_microphone(pin_name):
    if "_mems_cache" not in globals():
        global _mems_cache; _mems_cache = {}
    if pin_name not in _mems_cache:
        _mems_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _mems_cache[pin_name].read_u16()
    volume_percent = int((raw_value * 100) / 65535)
    return volume_percent

async def async_mems_microphone(pin_name):
    _t0("async_mems_microphone")
    result = mems_microphone(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_mems_microphone")
    return result


################################################################################
# 31. ANALOG JOYSTICK (X, Y, and Button)
################################################################################

def joystick(x_pin, y_pin, sw_pin):
    if "_joy_cache" not in globals():
        global _joy_cache; _joy_cache = {}
        
    key = (x_pin, y_pin, sw_pin)
    if key not in _joy_cache:
        _joy_cache[key] = {
            "x": ADC(Pin(x_pin)),
            "y": ADC(Pin(y_pin)),
            "sw": Pin(sw_pin, Pin.IN, Pin.PULL_UP)
        }
        
    hw = _joy_cache[key]
    
    # Read X and Y and map to 0-100%
    x_val = int((hw["x"].read_u16() / 65535.0) * 100)
    y_val = int((hw["y"].read_u16() / 65535.0) * 100)
    
    # Button is inverted (0 when pressed due to PULL_UP)
    btn_pressed = 1 if hw["sw"].value() == 0 else 0
    
    return {"x": x_val, "y": y_val, "button": btn_pressed}

async def async_joystick(x_pin, y_pin, sw_pin):
    _t0("async_joystick")
    result = joystick(x_pin, y_pin, sw_pin)
    await asyncio.sleep_ms(0)
    _t1("async_joystick")
    return result


################################################################################
# 32. DUAL MOTOR DRIVER (L298 / L293 / TB6612FNG)
################################################################################

def dual_motor(pin1, pin2, speed, action):
    # Route directly to your existing motor_speed logic
    motor_speed(pin1, pin2, speed, action)

async def async_dual_motor(pin1, pin2, speed, action):
    _t0("async_dual_motor")
    dual_motor(pin1, pin2, speed, action)
    await asyncio.sleep_ms(0)
    _t1("async_dual_motor")


################################################################################
# 33. DUAL RELAY MODULE
################################################################################

def dual_relay(pin1, state1, pin2, state2):
    # Reuses the relay_single logic
    relay_single(pin1, state1)
    relay_single(pin2, state2)

async def async_dual_relay(pin1, state1, pin2, state2):
    _t0("async_dual_relay")
    dual_relay(pin1, state1, pin2, state2)
    await asyncio.sleep_ms(0)
    _t1("async_dual_relay")


################################################################################
# 34. 4-BUTTON MODULE
################################################################################

def four_button(pin1, pin2, pin3, pin4):
    return {
        "btn1": button(pin1),
        "btn2": button(pin2),
        "btn3": button(pin3),
        "btn4": button(pin4)
    }

async def async_four_button(pin1, pin2, pin3, pin4):
    _t0("async_four_button")
    result = four_button(pin1, pin2, pin3, pin4)
    await asyncio.sleep_ms(0)
    _t1("async_four_button")
    return result


################################################################################
# 35. TF-LUNA LIDAR SENSOR (UART - 115200 Baud)
################################################################################

def lidar_luna(port_num):
    if "_luna_cache" not in globals():
        global _luna_cache; _luna_cache = {}
    if port_num not in _luna_cache:
        _luna_cache[port_num] = UART(port_num, baudrate=115200)
        
    uart = _luna_cache[port_num]
    
    if uart.any():
        return uart.read()
    return None

async def async_lidar_luna(port_num):
    _t0("async_lidar_luna")
    result = lidar_luna(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_lidar_luna")
    return result


################################################################################
# 36. EM18 RFID READER (UART - 9600 Baud)
################################################################################

def rfid_em18(port_num):
    if "_em18_cache" not in globals():
        global _em18_cache; _em18_cache = {}
    if port_num not in _em18_cache:
        _em18_cache[port_num] = UART(port_num, baudrate=9600)
        
    uart = _em18_cache[port_num]
    
    if uart.any():
        return uart.read()
    return None

async def async_rfid_em18(port_num):
    _t0("async_rfid_em18")
    result = rfid_em18(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_rfid_em18")
    return result


################################################################################
# 37. UART FINGERPRINT SCANNER (57600 Baud)
################################################################################

def fingerprint_scanner(port_num):
    if "_finger_cache" not in globals():
        global _finger_cache; _finger_cache = {}
    if port_num not in _finger_cache:
        _finger_cache[port_num] = UART(port_num, baudrate=57600)
        
    uart = _finger_cache[port_num]
    
    if uart.any():
        return uart.read()
    return None

async def async_fingerprint_scanner(port_num):
    _t0("async_fingerprint")
    result = fingerprint_scanner(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_fingerprint")
    return result


################################################################################
# 38. BME390 / BME280 PRESSURE SENSOR (I2C)
################################################################################

def bme390_pressure(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    devices = i2c.scan()
    if not devices:
        return 0
    return devices[0] 

async def async_bme390_pressure(port_num):
    _t0("async_bme390")
    result = bme390_pressure(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_bme390")
    return result


################################################################################
# 39. AT24CXX EEPROM (I2C MEMORY READ & WRITE)
################################################################################

def eeprom_write(port_num, memory_address, data_byte):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    EEPROM_I2C_ADDR = 0x50 
    
    try:
        i2c.writeto_mem(EEPROM_I2C_ADDR, memory_address, bytes([data_byte]), addrsize=16)
        time.sleep_ms(10) 
        return True
    except Exception as e:
        return False

async def async_eeprom_write(port_num, memory_address, data_byte):
    _t0("async_eeprom_write")
    result = eeprom_write(port_num, memory_address, data_byte)
    await asyncio.sleep_ms(0)
    _t1("async_eeprom_write")
    return result


def eeprom_read(port_num, memory_address):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    EEPROM_I2C_ADDR = 0x50 
    
    try:
        data = i2c.readfrom_mem(EEPROM_I2C_ADDR, memory_address, 1, addrsize=16)
        return data[0]
    except Exception as e:
        return 0

async def async_eeprom_read(port_num, memory_address):
    _t0("async_eeprom_read")
    result = eeprom_read(port_num, memory_address)
    await asyncio.sleep_ms(0)
    _t1("async_eeprom_read")
    return result


################################################################################
# 40. I2C LCD 1602 SCREEN
################################################################################

def i2c_lcd_init(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    return _i2c_cache[port_num]

async def async_i2c_lcd_init(port_num):
    _t0("async_i2c_lcd")
    i2c_lcd_init(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_i2c_lcd")


################################################################################
# 41. 4X4 MEMBRANE KEYPAD (I2C via PCF8574)
################################################################################

def keypad_4x4_i2c(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    KEYPAD_I2C_ADDR = 0x20 
    
    KEYMAP = [
        ['1', '2', '3', 'A'],
        ['4', '5', '6', 'B'],
        ['7', '8', '9', 'C'],
        ['*', '0', '#', 'D']
    ]
    
    try:
        row_masks = [0xFE, 0xFD, 0xFB, 0xF7]
        for r_idx in range(4):
            i2c.writeto(KEYPAD_I2C_ADDR, bytes([row_masks[r_idx]]))
            state = i2c.readfrom(KEYPAD_I2C_ADDR, 1)[0]
            
            if not (state & (1 << 4)): return KEYMAP[r_idx][0]
            if not (state & (1 << 5)): return KEYMAP[r_idx][1]
            if not (state & (1 << 6)): return KEYMAP[r_idx][2]
            if not (state & (1 << 7)): return KEYMAP[r_idx][3]
            
        return None
    except Exception as e:
        return None

async def async_keypad_4x4_i2c(port_num):
    _t0("async_keypad_i2c")
    result = keypad_4x4_i2c(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_keypad_i2c")
    return result


################################################################################
# 42. MICRO SD CARD STORAGE (SPI)
################################################################################

def mount_sd_card(spi_port_num, cs_pin):
    if "_sd_cache" not in globals():
        global _sd_cache; _sd_cache = {}
        
    key = (spi_port_num, cs_pin)
    if key not in _sd_cache:
        import os
        from machine import SDCard
        try:
            spi = SPI(spi_port_num)
            sd = SDCard(spi=spi, cs=Pin(cs_pin))
            vfs = os.VfsFat(sd)
            os.mount(vfs, "/sd")
            _sd_cache[key] = True
        except Exception:
            _sd_cache[key] = False
            
    return _sd_cache[key]

async def async_mount_sd_card(spi_port_num, cs_pin):
    _t0("async_mount_sd")
    result = mount_sd_card(spi_port_num, cs_pin)
    await asyncio.sleep_ms(0)
    _t1("async_mount_sd")
    return result


################################################################################
# 43. RGB LED (WS2812B - machine.bitstream)
################################################################################

def rgb_led(pin_name, r, g, b, led_index=1):
    if "_rgb_cache" not in globals():
        global _rgb_cache; _rgb_cache = {}
        
    if pin_name not in _rgb_cache:
        _rgb_cache[pin_name] = {
            "pin": Pin(pin_name, Pin.OUT),
            "data": bytearray(64 * 3)
        }
        
    hw = _rgb_cache[pin_name]
    data = hw["data"]
    idx = led_index - 1
    
    if 0 <= idx < 64:
        offset = idx * 3
        # WS2812B requires GRB order (not RGB!)
        data[offset]     = max(0, min(255, int(g)))
        data[offset + 1] = max(0, min(255, int(r)))
        data[offset + 2] = max(0, min(255, int(b)))
        
        # T0H, T0L, T1H, T1L in nanoseconds
        machine.bitstream(hw["pin"], 0, (400, 850, 800, 450), data)

async def async_rgb_led(pin_name, r, g, b, led_index=1):
    _t0("async_rgb_led")
    rgb_led(pin_name, r, g, b, led_index)
    await asyncio.sleep_ms(0)
    _t1("async_rgb_led")


async def async_rgb_round(pin_name, r, g, b, led_index=1):
    _t0("async_rgb_round"); rgb_led(pin_name, r, g, b, led_index); await asyncio.sleep_ms(0); _t1("async_rgb_round")

async def async_rgb_square(pin_name, r, g, b, led_index=1):
    _t0("async_rgb_square"); rgb_led(pin_name, r, g, b, led_index); await asyncio.sleep_ms(0); _t1("async_rgb_square")


################################################################################
# 44. LDR (LIGHT DEPENDENT RESISTOR) - ANALOG
################################################################################

def ldr_sensor(pin_name):
    if "_ldr_cache" not in globals():
        global _ldr_cache; _ldr_cache = {}
    if pin_name not in _ldr_cache:
        _ldr_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _ldr_cache[pin_name].read_u16()
    return int((raw_value * 100) / 65535)

async def async_ldr_sensor(pin_name):
    _t0("async_ldr_sensor")
    result = ldr_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_ldr_sensor")
    return result


################################################################################
# 45. WATER SENSOR - ANALOG
################################################################################

def water_sensor(pin_name):
    if "_water_cache" not in globals():
        global _water_cache; _water_cache = {}
    if pin_name not in _water_cache:
        _water_cache[pin_name] = ADC(Pin(pin_name))
        
    raw_value = _water_cache[pin_name].read_u16()
    return int((raw_value * 100) / 65535)

async def async_water_sensor(pin_name):
    _t0("async_water_sensor")
    result = water_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_water_sensor")
    return result


################################################################################
# 46. FLAME SENSOR - DIGITAL
################################################################################

def flame_sensor(pin_name):
    if "_flame_cache" not in globals():
        global _flame_cache; _flame_cache = {}
    if pin_name not in _flame_cache:
        _flame_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _flame_cache[pin_name].value()

async def async_flame_sensor(pin_name):
    _t0("async_flame_sensor")
    result = flame_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_flame_sensor")
    return result


################################################################################
# 47. INFRARED PROXIMITY SENSOR - DIGITAL
################################################################################

def ir_proximity(pin_name):
    if "_ir_prox_cache" not in globals():
        global _ir_prox_cache; _ir_prox_cache = {}
    if pin_name not in _ir_prox_cache:
        _ir_prox_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _ir_prox_cache[pin_name].value()

async def async_ir_proximity(pin_name):
    _t0("async_ir_proximity")
    result = ir_proximity(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_ir_proximity")
    return result


################################################################################
# 48. 4-DIGIT 7-SEGMENT DISPLAY
################################################################################

def display_7segment(port_num, value):
    if "_7seg_cache" not in globals():
        global _7seg_cache; _7seg_cache = {}
        
    if port_num not in _7seg_cache:
        _7seg_cache[port_num] = True 
        
    display_text = str(value)
    pass

async def async_7segment(port_num, value):
    _t0("async_7segment")
    display_7segment(port_num, value)
    await asyncio.sleep_ms(0)
    _t1("async_7segment")


################################################################################
# 49. DHT22 TEMPERATURE & HUMIDITY SENSOR
################################################################################

def dht22_sensor(pin_name):
    return dht22_temp(pin_name)

async def async_dht22_sensor(pin_name):
    _t0("async_dht22_sensor")
    result = dht22_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_dht22_sensor")
    return result


################################################################################
# 50. TILT SENSOR - DIGITAL
################################################################################

def tilt_sensor(pin_name):
    if "_tilt_cache" not in globals():
        global _tilt_cache; _tilt_cache = {}
    if pin_name not in _tilt_cache:
        _tilt_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _tilt_cache[pin_name].value()

async def async_tilt_sensor(pin_name):
    _t0("async_tilt_sensor")
    result = tilt_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_tilt_sensor")
    return result


################################################################################
# 51. LINE TRACKER SENSOR - DIGITAL
################################################################################

def tracker_sensor(pin_name):
    if "_tracker_cache" not in globals():
        global _tracker_cache; _tracker_cache = {}
    if pin_name not in _tracker_cache:
        _tracker_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _tracker_cache[pin_name].value()

async def async_tracker_sensor(pin_name):
    _t0("async_tracker_sensor")
    result = tracker_sensor(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_tracker_sensor")
    return result


################################################################################
# 52. CAPACITIVE TOUCH (336A / SINGLE PIN) - DIGITAL
################################################################################

def touch_336a(pin_name):
    if "_touch_cache" not in globals():
        global _touch_cache; _touch_cache = {}
    if pin_name not in _touch_cache:
        _touch_cache[pin_name] = Pin(pin_name, Pin.IN, Pin.PULL_DOWN)
    return _touch_cache[pin_name].value()

async def async_touch_336a(pin_name):
    _t0("async_touch_336a")
    result = touch_336a(pin_name)
    await asyncio.sleep_ms(0)
    _t1("async_touch_336a")
    return result


################################################################################
# 53. PN532 NFC/RFID READER (I2C)
################################################################################

def pn532_rfid(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    
    devices = i2c.scan()
    if 0x24 in devices:
        return True 
    return False

async def async_pn532_rfid(port_num):
    _t0("async_pn532")
    result = pn532_rfid(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_pn532")
    return result


################################################################################
# 54. CAPACITIVE TOUCH MPR121 (12-Channel I2C)
################################################################################

def touch_mpr121(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    i2c = _i2c_cache[port_num]
    MPR121_I2C_ADDR = 0x5A
    
    try:
        data = i2c.readfrom_mem(MPR121_I2C_ADDR, 0x00, 2)
        return (data[1] << 8) | data[0]
    except Exception:
        return 0

async def async_touch_mpr121(port_num):
    _t0("async_touch_mpr121")
    result = touch_mpr121(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_touch_mpr121")
    return result


################################################################################
# 55. PCA9685 SERVO DRIVER (16-Channel I2C)
################################################################################

def servo_driver_pca9685(port_num):
    if "_i2c_cache" not in globals():
        global _i2c_cache; _i2c_cache = {}
    if port_num not in _i2c_cache:
        _i2c_cache[port_num] = I2C(port_num, freq=100000)
        
    return _i2c_cache[port_num]

async def async_servo_driver_pca9685(port_num):
    _t0("async_servo_driver")
    servo_driver_pca9685(port_num)
    await asyncio.sleep_ms(0)
    _t1("async_servo_driver")


################################################################################
# 56. SPEAKER / MEMS MIC MODULE (Analog Audio)
################################################################################

def speaker_mic(mic_pin, speaker_pin):
    if "_audio_cache" not in globals():
        global _audio_cache; _audio_cache = {}
        
    key = (mic_pin, speaker_pin)
    if key not in _audio_cache:
        _audio_cache[key] = {
            "mic": ADC(Pin(mic_pin)),
            "spk": Pin(speaker_pin, Pin.OUT, value=0)
        }
        
    hw = _audio_cache[key]
    raw_value = hw["mic"].read_u16()
    return int((raw_value * 100) / 65535)

async def async_speaker_mic(mic_pin, speaker_pin):
    _t0("async_speaker_mic")
    result = speaker_mic(mic_pin, speaker_pin)
    await asyncio.sleep_ms(0)
    _t1("async_speaker_mic")
    return result
################################################################################
# DHT22 TEMPERATURE + HUMIDITY
################################################################################

_dht22_cache = {}


def _get_dht22(pin_name):

    if pin_name not in _dht22_cache:

        sensor = dht.DHT22(
            Pin(pin_name)
        )

        _dht22_cache[pin_name] = {
            "sensor": sensor,
            "temperature": None,
            "humidity": None,
            "last_measure": 0
        }

    return _dht22_cache[pin_name]


def _dht22_measure(pin_name):

    data = _get_dht22(
        pin_name
    )

    now = time.ticks_ms()

    # DHT22 should not be measured more frequently
    # than approximately once every 2 seconds.

    if (
        data["temperature"] is None
        or
        time.ticks_diff(
            now,
            data["last_measure"]
        ) >= 2000
    ):

        try:

            data["sensor"].measure()

            data["temperature"] = (
                data["sensor"].temperature()
            )

            data["humidity"] = (
                data["sensor"].humidity()
            )

            data["last_measure"] = now

        except Exception as e:

            print(
                "DHT22 ERROR:",
                e
            )

            return None

    return data


# ----------------------------------------------------------------------------
# DHT22 TEMPERATURE
# ----------------------------------------------------------------------------

def dht22_temp(pin_name):

    data = _dht22_measure(
        pin_name
    )

    if data is None:
        return None

    return data["temperature"]


async def async_dht22_temp(pin_name):

    _t0("async_dht22_temp")

    result = dht22_temp(
        pin_name
    )

    await asyncio.sleep_ms(0)

    _t1("async_dht22_temp")

    return result


# ----------------------------------------------------------------------------
# DHT22 HUMIDITY
# ----------------------------------------------------------------------------

def dht22_humidity(pin_name):

    data = _dht22_measure(
        pin_name
    )

    if data is None:
        return None

    return data["humidity"]


async def async_dht22_humidity(pin_name):

    _t0("async_dht22_humidity")

    result = dht22_humidity(
        pin_name
    )

    await asyncio.sleep_ms(0)

    _t1("async_dht22_humidity")

    return result
################################################################################
# 16. LDR
################################################################################

_ldr_cache = {}


def LDR(pin_name):

    if pin_name not in _ldr_cache:

        _ldr_cache[pin_name] = ADC(
            Pin(pin_name)
        )

    raw = _ldr_cache[
        pin_name
    ].read_u16()

    # Same logic as your working test

    if raw > 30000:

        return "DARK"

    else:

        return "LIGHT"


async def async_LDR(pin_name):

    _t0("async_LDR")

    result = LDR(
        pin_name
    )

    await asyncio.sleep_ms(0)

    _t1("async_LDR")

    return result



################################################################################
# BLOCKLY FUNCTION NAME COMPATIBILITY
#
# The Curio Blockly generator currently produces:
#     async_air_quality("PIN")
#
# The original library function is:
#     async_air_quality_sensor("PIN")
#
# Keep both names supported.
################################################################################

async def async_air_quality(pin_name):
    return await async_air_quality_sensor(pin_name)


################################################################################
# 29. DWIN LCD — SINGLE FUNCTION CALL, DYNAMIC NAME, AUTOMATIC BOX (FIFO)
#
# Blockly generates ONE call per LCD block:
#
#     await async_lcd("I2C1", async_tilt, "D4")
#     await async_lcd("I2C1", async_ultrasonic, "D2", "D3")
#     await async_lcd("I2C1", async_dht22_temp, "D5")
#
# What happens inside, with NO name table stored in the library:
#
#   1. NAME   — taken from the function itself, at run time:
#                 async_tilt        -> "TILT"
#                 async_ultrasonic  -> "ULTRASONIC"
#                 async_dht22_temp  -> "DHT22 TEMP"
#                 async_gas_sensor  -> "GAS SENSOR"
#               Any new sensor function you add to lib.py works the same way,
#               nothing else needs to be edited.
#   2. VALUE  — the function is called with the pins and awaited.
#   3. BOX    — the position of the LCD block in Blockly:
#                 1st LCD block -> BOX 1, 2nd -> BOX 2 ... 6th -> BOX 6
#               Shuffle, replace or remove blocks and the display follows
#               on the next loop.
#   4. WRITE  — name -> NAME VP, value -> VALUE VP of that box.
#               Only changed text is sent; everything is re-sent every 2 s.
#   5. RETURN — the sensor value, so it can still be used in logic.
#
# Also accepted:
#     await async_lcd("I2C1", 42)                      -> name "VALUE"
#     await async_lcd("I2C1", count, label="Count")    -> name "Count"
#     await async_lcd("I2C1", async_IR, "D3", label="Door")
#
# i2c_name is kept for Blockly compatibility and is not used.
################################################################################

# ── CONFIG ───────────────────────────────────────────────────────────────────
_DWIN_UART_ID    = 1       # !! The K230 functions also use UART1.
                           #    Move the DWIN to a free UART when the wiring
                           #    allows, then change only this number.
_DWIN_BAUD       = 115200
_DWIN_TX_GAP_MS  = 5       # pause after each frame (yields, does not block)
_DWIN_REFRESH_MS = 2000    # re-send name + value even when unchanged
_DWIN_NAME_LEN   = 12      # bytes in the NAME text VP
_DWIN_VALUE_LEN  = 15      # bytes in the VALUE text VP
_DWIN_RESTART_MS = 1500    # pause this long = program (re)started -> BOX 1

# (name VP, icon VP, value VP) for BOX 1 .. BOX 6
_DWIN_BOX_VP = (
    (0x6100, 0x6110, 0x6120),
    (0x6200, 0x6210, 0x6220),
    (0x6300, 0x6310, 0x6320),
    (0x6400, 0x6410, 0x6420),
    (0x6500, 0x6510, 0x6520),
    (0x6600, 0x6610, 0x6620),
)
_DWIN_MAX_BOXES = len(_DWIN_BOX_VP)

# DGUS Variable Icon IDs. Reserve icon 0 as a transparent/blank image.
# Populate the icon library in DGUS with these IDs, or change this table
# to match the IDs in your actual .ICL resource.
_DWIN_SENSOR_ICONS = {
    # Icon IDs matched to the supplied 00.bmp through 101.bmp sheet.
    "ULTRASONIC": 2, "IR": 1, "MOTION": 64,
    "TEMP": 3, "DHT22_TEMP": 3, "DHT22_HUMIDITY": 9,
    "DHT22_HUM": 9, "HUMIDITY": 9,
    "SOIL_MOISTURE": 41, "LDR": 86, "AMBIENT": 86,
    "FLAME": 19, "AIR_QUALITY_SENSOR": 31,
    "WATER_SEN": 10, "WATER_LEVEL": 10, "TDS_SENSOR": 13,
    "BUTTON": 70, "TILT": 44, "ACCELEROMETER": 44,
    "GESTURE": 61, "COLOUR": 16, "RFID": 73,
    "RTC": 93, "JOY_STICK": 56, "BUZZER": 60,
    "PRESSURE": 42, "ECG": 78, "VOLTAGE": 82,
    "CURRENT": 81, "MAGNETIC": 51, "KEYPAD": 69,
    "GAS_SENSOR": 21, "UV": 15,
}
_DWIN_ICON_BLANK = 0

def _dwin_icon_for_function(fn_name):
    if not fn_name:
        return _DWIN_ICON_BLANK
    n = str(fn_name)
    if n.startswith("async_"):
        n = n[6:]
    return _DWIN_SENSOR_ICONS.get(n.upper(), _DWIN_ICON_BLANK)


# ── STATE (built at run time) ────────────────────────────────────────────────
_dwin_uart_obj   = None
_dwin_ready      = False                      # first call blanks the screen
_dwin_index      = 0                          # next box in the current loop
_dwin_loop_keys  = []                         # sensors seen in the current loop
_dwin_loop_names = []                         # names used in the current loop
_dwin_drawn      = 0                          # boxes in use on the screen
_dwin_sent       = [[None, None, 0] for _ in range(_DWIN_MAX_BOXES)]
_dwin_icon_sent  = [None] * _DWIN_MAX_BOXES
                                              # box -> [name, value, refresh]
_dwin_warned     = False
_dwin_anchor     = None                       # sensor that starts each loop
_dwin_last_ms    = None                       # end time of the last LCD call
_dwin_loop_gaps  = []                         # (pause before call, key)


# ── UART FRAMES ──────────────────────────────────────────────────────────────
def _dwin_uart():
    global _dwin_uart_obj
    if _dwin_uart_obj is None:
        _dwin_uart_obj = UART(_DWIN_UART_ID, baudrate=_DWIN_BAUD)
    return _dwin_uart_obj


async def _dwin_send_text(vp, text, length):
    data = str("" if text is None else text).encode("ascii", "ignore")[:length]
    data += b" " * (length - len(data))           # erase older, longer text
    frame = bytearray((0x5A, 0xA5, 3 + len(data), 0x82,
                       (vp >> 8) & 0xFF, vp & 0xFF))
    frame.extend(data)
    _dwin_uart().write(frame)                      # whole frame in one write
    await asyncio.sleep_ms(_DWIN_TX_GAP_MS)


async def _dwin_send_u16(vp, value):
    v = int(value) & 0xFFFF
    _dwin_uart().write(bytes((0x5A, 0xA5, 0x05, 0x82,
                              (vp >> 8) & 0xFF, vp & 0xFF,
                              (v >> 8) & 0xFF, v & 0xFF)))
    await asyncio.sleep_ms(_DWIN_TX_GAP_MS)


async def _dwin_blank_box(i):
    name_vp, icon_vp, value_vp = _DWIN_BOX_VP[i]
    await _dwin_send_text(name_vp, "", _DWIN_NAME_LEN)
    await _dwin_send_text(value_vp, "", _DWIN_VALUE_LEN)
    await _dwin_send_u16(icon_vp, _DWIN_ICON_BLANK)
    _dwin_sent[i] = [None, None, 0]
    _dwin_icon_sent[i] = _DWIN_ICON_BLANK


# ── VALUE TEXT ───────────────────────────────────────────────────────────────
def _dwin_format(v):
    if v is None:
        return "--"
    if v is True or v is False:
        return "1" if v else "0"
    if isinstance(v, float):
        return "{:.2f}".format(v).rstrip("0").rstrip(".")
    if isinstance(v, (list, tuple)):               # accelerometer, colour, GPS
        return " ".join(_dwin_format(x) for x in v[:3])
    if isinstance(v, dict):                        # joystick, four_button
        return " ".join(str(k)[:1].upper() + _dwin_format(x)
                        for k, x in v.items())
    if isinstance(v, (bytes, bytearray)):          # raw UART sensors
        return "".join("{:02X}".format(b) for b in v)
    return str(v)


# ── NAME FROM THE FUNCTION ITSELF (no table) ─────────────────────────────────
def _dwin_function_name(fn):
    """Return the Python name of the function object, e.g. 'async_tilt'."""
    for k, obj in globals().items():               # its name in lib.py
        if obj is fn:
            return k
    name = getattr(fn, "__name__", None)           # a function defined elsewhere
    if name and name not in ("<lambda>", "_recorded"):
        return name
    return "sensor"


def _dwin_display_name(fn_name):
    """'async_tilt' -> 'TILT', 'async_dht22_temp' -> 'DHT22 TEMP'."""
    n = fn_name
    if n.startswith("async_"):
        n = n[6:]
    n = n.strip("_").replace("_", " ").upper()
    if len(n) > _DWIN_NAME_LEN and n.endswith(" SENSOR"):
        n = n[:-7]                                 # keep it readable
    return n[:_DWIN_NAME_LEN] if n else "SENSOR"


# ── BOX = POSITION OF THE LCD BLOCK IN BLOCKLY ──────────────────────────────
#
#   1st LCD block in the loop -> BOX 1, 2nd -> BOX 2, ... 6th -> BOX 6
#
# How the library knows where the Blockly loop starts (no fixed timing):
#   a) Program start / Stop -> Upload / Live: a pause of 1.5 s or more before
#      an LCD block -> that block is BOX 1.
#   b) Every loop it measures the pause before each LCD block. The block after
#      the LONGEST pause (your Delay block) is the first block of the loop.
#   c) If a sensor shown earlier in this loop comes again, the loop is over.
#
#   - Shuffle blocks   -> names and values follow the new order next loop.
#   - Replace a sensor -> the new one takes the SAME box.
#   - Remove a sensor  -> the boxes after it move up, unused boxes are blanked.
#   - More than 6      -> extra LCD blocks are not shown (6 boxes only).
#   Keep the Delay block as the LAST block of the loop.
################################################################################

async def _dwin_new_loop():
    """Close the current loop: blank boxes it no longer uses, restart at BOX 1."""
    global _dwin_index, _dwin_drawn
    used = _dwin_index
    for i in range(used, _dwin_drawn):             # sensors were removed
        await _dwin_blank_box(i)
    _dwin_drawn = used
    _dwin_index = 0
    del _dwin_loop_keys[:]
    del _dwin_loop_names[:]
    del _dwin_loop_gaps[:]


def _dwin_learn_anchor():
    """The block after the clearly longest pause starts the loop."""
    global _dwin_anchor
    gaps = _dwin_loop_gaps
    if len(gaps) < 2:
        return
    best = 0
    for i in range(1, len(gaps)):
        if gaps[i][0] > gaps[best][0]:
            best = i
    second = 0
    for i in range(len(gaps)):
        if i != best and gaps[i][0] > second:
            second = gaps[i][0]
    if gaps[best][0] >= 50 and gaps[best][0] * 2 >= second * 3:   # 1.5x longer
        _dwin_anchor = gaps[best][1]


async def _dwin_next_box(key, base, args, now):
    """Return (box index, name) for this LCD block, or (None, None) if > 6."""
    global _dwin_index, _dwin_drawn, _dwin_warned, _dwin_anchor

    if _dwin_last_ms is None:
        gap = _DWIN_RESTART_MS
    else:
        gap = time.ticks_diff(now, _dwin_last_ms)

    if gap >= _DWIN_RESTART_MS:                    # a) program (re)started
        if _dwin_loop_keys:
            await _dwin_new_loop()
        _dwin_anchor = key
    elif _dwin_loop_keys and (key == _dwin_anchor or key in _dwin_loop_keys):
        _dwin_learn_anchor()                       # b) and c) loop finished
        await _dwin_new_loop()

    _dwin_loop_keys.append(key)
    _dwin_loop_gaps.append((gap, key))

    if _dwin_index >= _DWIN_MAX_BOXES:             # 7th+ block: no box left
        if not _dwin_warned:
            print("LCD: only", _DWIN_MAX_BOXES, "boxes - extra blocks not shown")
            _dwin_warned = True
        return None, None

    name = base[:_DWIN_NAME_LEN]
    if name in _dwin_loop_names:                   # same sensor on two pins
        tag = str(args[0]) if args else str(_dwin_index + 1)
        name = name[:_DWIN_NAME_LEN - len(tag) - 1] + " " + tag
    _dwin_loop_names.append(name)

    box = _dwin_index
    _dwin_index += 1
    if box + 1 > _dwin_drawn:
        _dwin_drawn = box + 1
    return box, name


async def _dwin_show(box, name, value, now, icon_id=0):
    text = _dwin_format(value)
    sent = _dwin_sent[box]
    stale = time.ticks_diff(now, sent[2]) >= _DWIN_REFRESH_MS
    name_vp, icon_vp, value_vp = _DWIN_BOX_VP[box]
    if stale or sent[0] != name:
        await _dwin_send_text(name_vp, name, _DWIN_NAME_LEN)
        sent[0] = name
    if stale or _dwin_icon_sent[box] != icon_id:
        await _dwin_send_u16(icon_vp, icon_id)
        _dwin_icon_sent[box] = icon_id
    if stale or sent[1] != text:
        await _dwin_send_text(value_vp, text, _DWIN_VALUE_LEN)
        sent[1] = text
    if stale:
        sent[2] = now


# ── THE SINGLE FUNCTION CALL ─────────────────────────────────────────────────
async def async_lcd(i2c_name, value, *args, label=None, **kwargs):
    global _dwin_ready, _dwin_last_ms
    _t0("async_lcd")

    if not _dwin_ready:                     # first call after boot / upload
        _dwin_ready = True
        for i in range(_DWIN_MAX_BOXES):
            await _dwin_blank_box(i)

    fn_name = None   # plain values have no automatic sensor icon
    if callable(value):
        # sensor mode: name from the function, value from calling it
        fn_name = _dwin_function_name(value)
        base = label if label else _dwin_display_name(fn_name)
        key = fn_name + repr(args)          # same sensor + same pins = same box
        try:
            result = value(*args, **kwargs)
            if hasattr(result, "send"):     # async def -> await it
                result = await result
        except Exception as e:
            print("LCD sensor error:", fn_name, args, e)
            result = "ERR"
        _dwin_clear_last_call()
    else:
        # value mode: Blockly already called the sensor, e.g.
        #     await async_lcd("I2C1", await async_tilt("D4"))
        # The auto-wrapper (end of this section) recorded which async_*
        # function produced this value, so its name is still known here.
        result = value
        rec = _dwin_last_call
        _dwin_clear_last_call()
        if rec is not None and (value is rec[2] or value == rec[2]):
            fn_name, rec_args = rec[0], rec[1]
            base = label if label else _dwin_display_name(fn_name)
            key = fn_name + repr(rec_args)
            args = rec_args
        else:
            base = label if label else "VALUE"
            # several plain values in one loop: number them so only the
            # FIRST one coming back again marks a new loop
            k = "value:" + str(base) + ":"
            n = 0
            for x in _dwin_loop_keys:
                if x.startswith(k):
                    n += 1
            key = k + str(n)

    box, name = await _dwin_next_box(key, str(base), args, time.ticks_ms())
    if box is not None:
        await _dwin_show(box, name, result, time.ticks_ms(),
                         _dwin_icon_for_function(fn_name))
    _dwin_last_ms = time.ticks_ms()

    _t1("async_lcd")
    return result


def lcd(i2c_name, value, *args, **kwargs):
    """Sync form for scripts outside asyncio: lcd("I2C1", async_tilt, "D4")."""
    return asyncio.run(async_lcd(i2c_name, value, *args, **kwargs))


# ── OPTIONAL HELPERS ─────────────────────────────────────────────────────────
async def async_lcd_reset():
    """Blank the screen and start again from BOX 1 (optional, e.g. at START)."""
    global _dwin_index, _dwin_drawn, _dwin_anchor, _dwin_last_ms
    for i in range(_DWIN_MAX_BOXES):
        await _dwin_blank_box(i)
    _dwin_index = 0
    _dwin_drawn = 0
    _dwin_anchor = None
    _dwin_last_ms = None
    del _dwin_loop_gaps[:]
    del _dwin_loop_keys[:]
    del _dwin_loop_names[:]


async def async_lcd_icon(box_number, icon_id):
    """Set the icon VP of BOX 1..6."""
    i = int(box_number) - 1
    if 0 <= i < _DWIN_MAX_BOXES:
        await _dwin_send_u16(_DWIN_BOX_VP[i][1], icon_id)
        _dwin_icon_sent[i] = int(icon_id) & 0xFFFF


################################################################################
# AUTO NAME RECORDER — makes the OLD Blockly form work with no generator change
#
# Every function in lib.py whose name starts with "async_" is wrapped once,
# here, at import time. The list is built DYNAMICALLY from globals(), so there
# is no sensor table: any async_ function you add later is covered too.
#
# When a wrapped function finishes, it records (its name, its args, its result).
# async_lcd() reads that record if the value it receives IS that result.
#
#     await async_lcd("I2C1", await async_tilt("D4"))
#         -> async_tilt finishes, records ("async_tilt", ("D4",), 0)
#         -> async_lcd gets 0, matches the record -> name "TILT"
#
# This is safe under asyncio.gather: control returns from the sensor to
# async_lcd() inside the same task with no scheduler switch in between.
################################################################################

_dwin_last_call = None          # (function name, args, result) or None


# ==============================================================================
# PROJECT SENSORS LIVE TELEMETRY: 30 CARDS ON FIVE DWIN PAGES (VP 0x5500)
# ==============================================================================
#
# DEVELOPER GUIDE: HOW TO ADD A NEW SENSOR / ACTUATOR IN lib.py
# ------------------------------------------------------------------------------
# 1. HOW TO ADD A NEW SENSOR (AUTOMATIC DISPLAY):
#    Simply write your driver function starting with "async_" anywhere in lib.py:
#
#        async def async_my_sensor(pin_name):
#            val = ADC(Pin(pin_name)).read_u16()
#            await asyncio.sleep_ms(0)
#            return val
#
#    HOW IT WORKS AUTOMATICALLY:
#    - At startup, _dwin_install_recorders() auto-discovers all "async_" functions.
#    - When code calls "await async_my_sensor('A0')", the display automatically:
#        a) Allocates the next available card on the Projects List (Cards 1 to 6).
#        b) Puts "MY SENSOR (A0)" in the colored top header.
#        c) Puts the returned value to the right of the icon box.
#        d) Leaves the 40x40 icon box clean white (default icon 0).
#    - YOU DO NOT NEED TO WRITE ANY DWIN SERIAL OR DISPLAY PACKET CODE!
#
# 2. HOW TO ATTACH AN ICON (OPTIONAL):
#    Inside _telemetry_icon_for() below, add your keyword to map to an icon ID (1..77):
#
#        if 'MY SENSOR' in t:
#            return 29   # e.g., reuses Gas Sensor icon (ID 29)
#
#    If you do NOT add an icon, it defaults to 0 (clean white square, zero error).
#
# 3. HOW TO FORMAT UNITS (OPTIONAL, e.g. "PPM", "LUX", "CM"):
#    Inside _telemetry_record() below, add:
#
#        elif "MY SENSOR" in name:
#            val_str = str(result) + " PPM"
#
# 4. HOW TO RUN SILENTLY (RUN IN CODE ONLY - NEVER SEND TO DISPLAY):
#    If a sensor/function should run in code but NEVER appear on the display screen:
#    - Method A: Add its name to the _TELEMETRY_IGNORE tuple below:
#                _TELEMETRY_IGNORE = ("async_sleep", ..., "async_my_sensor")
#    - Method B: Prefix the name with an underscore:
#                async def async__internal_sensor(pin): ...
#    - Method C: Write a standard synchronous function (no "async_" prefix):
#                def read_sensor_raw(pin): ...
# ==============================================================================
PROJECT_PAGES = (40, 41, 71, 72, 73)
PROJECTS_DOTS_VP = 0x5500
PROJECTS_MAX_DOTS = 1200
PROJECTS_MAX_ITEMS = 30

_telemetry_sensors = []      # [[key, label, val_str, col_rgb565], ...]
_telemetry_last_draw_ms = 0
_telemetry_changed = False
_telemetry_last_page = None
_telemetry_buf = None

# Functions in this tuple run purely in code and are NEVER sent to the display:
_TELEMETRY_IGNORE = (
    "async_sleep", "async_dwin", "async_lcd"
)

_COL_LABEL = 0xFFFF   # white for card header
_COL_GOOD  = 0x1529   # green
_COL_VAL   = 0x233D   # blue
_COL_GREY  = 0x9536   # grey
_COL_ORANGE= 0xDBA0   # orange
_COL_BLUE  = 0x233D   # blue
_telemetry_last_icons = [None] * 6

def _telemetry_icon_for(key_or_name):
    if not key_or_name:
        return 0
    t = str(key_or_name).upper().replace('_', ' ')
    if 'BUTTON' in t or ('KEY' in t and 'KEYPAD' not in t):
        return 41 if '4' in t else 1
    if 'BUZZER' in t:
        return 2
    if 'DHT22' in t:
        return 3
    if 'PIR' in t or 'MOTION' in t:
        return 4
    if 'DUAL RELAY' in t or '2 RELAY' in t or '2-CH' in t:
        return 35
    if 'RELAY' in t:
        return 5
    if 'RGB ROUND' in t:
        return 14
    if 'RGB SQUARE' in t:
        return 15
    if 'RGB' in t:
        return 11
    if 'LED' in t or 'RED' in t or 'GREEN' in t or 'YELLOW' in t:
        return 6
    if 'TRACKER' in t:
        return 53
    if 'IR' in t or 'INFRARED' in t or 'PROXIMITY' in t:
        return 7
    if 'DHT11' in t:
        return 8
    if 'SOLENOID' in t or 'DOOR' in t:
        return 9
    if 'RADAR' in t or 'RCWL' in t:
        return 10
    if 'TSL235' in t:
        return 16
    if 'UV' in t:
        return 17
    if 'MPR121' in t and 'WHEEL' in t:
        return 48
    if 'MPR121' in t:
        return 45
    if 'TOUCH' in t:
        return 18
    if 'TEMT' in t or 'LUX' in t:
        return 19
    if 'SOIL' in t or 'MOISTURE' in t:
        return 20
    if 'TDS' in t:
        return 21
    if 'PH' in t:
        return 22
    if 'FORCE' in t:
        return 23
    if 'TURBIDITY' in t:
        return 37
    if 'WATER' in t and 'PUMP' not in t:
        return 24
    if 'SOLAR' in t:
        return 25
    if 'LDR' in t:
        return 26
    if '7SEG' in t or 'SEGMENT' in t:
        return 27
    if 'FLAME' in t:
        return 28
    if 'MQ' in t or 'GAS' in t or 'AIR QUALITY' in t:
        return 29
    if 'PIEZO' in t or 'VIBRATION' in t:
        return 30
    if 'MEMS' in t:
        return 68
    if 'SOUND' in t or 'MIC' in t:
        return 31
    if 'DOT MATRIX' in t or 'MATRIX' in t:
        return 32
    if 'THERM' in t or 'TEMP' in t:
        return 33
    if 'TILT' in t:
        return 34
    if 'LOAD CELL' in t:
        return 36
    if 'HALL' in t:
        return 38
    if 'ULTRASONIC' in t:
        return 39
    if 'ECG' in t or 'AD8232' in t:
        return 40
    if 'BME' in t or 'PRESSURE' in t or 'HX710' in t:
        return 42
    if 'EEPROM' in t or 'AT24' in t:
        return 43
    if 'JOY' in t:
        return 44
    if 'SERVO DRIVER' in t or 'PCA9685' in t:
        return 46
    if 'LCD' in t:
        return 47
    if 'KEYPAD' in t:
        return 49
    if 'PN532' in t:
        return 50
    if 'ROTAT' in t or 'ENCODER' in t:
        return 51
    if 'STEPPER' in t:
        return 52
    if 'FLEX' in t:
        return 54
    if 'FM' in t:
        return 55
    if 'COLOR' in t or 'COLOUR' in t or 'TCS' in t:
        return 57
    if 'TRAFFIC' in t:
        return 58
    if 'HAPTIC' in t:
        return 59
    if 'ACCEL' in t or 'ADXL' in t:
        return 60
    if 'RFID' in t or 'EM18' in t:
        return 61
    if 'LIDAR' in t or 'LUNA' in t:
        return 62
    if 'FINGER' in t:
        return 63
    if 'GSM' in t or '4G' in t or 'A7670' in t:
        return 64
    if 'UART' in t:
        return 65
    if 'GPS' in t or 'NEO' in t:
        return 66
    if 'SD' in t:
        return 69
    if 'FLASH' in t or 'W25Q' in t:
        return 70
    if 'TB6612' in t:
        return 72
    if 'L298' in t:
        return 71
    if 'FAN' in t:
        return 75
    if 'MOTOR' in t:
        return 74
    if 'SERVO' in t:
        return 77
    return 0


def _telemetry_draw(page=None, force=False):
    """Draw the six visible cards using Basic Graphic 0x21 dot text on VP 0x5500.

    All five card pages share VP 0x5500; when the user taps PREV/NEXT, the board
    detects the new page and redraws its six cards immediately.
    """
    global _telemetry_last_page, _telemetry_changed, _telemetry_buf, _telemetry_last_icons
    try:
        import struct
        import dwin_screen as dw
        from dwin_get_data import _GLYPHS, _ADOTS
    except Exception:
        return False
    if page is None:
        p = dw._dw_read(0x0014, 1)
        if p:
            page = p[0]
        else:
            page = 40  # Default to Page 40 (Card list) so telemetry renders even in blind/one-way mode
    if page not in PROJECT_PAGES:
        if page == 96:
            try:
                import iot_bus, dwin_get_data as g
                k = dw._dw_read(0x5F80, 1)
                if k and k[0]:
                    dw._dw_vp(0x5F80, b'\x00\x00')
                    if k[0] == 0x0701:
                        iot_bus.ui_send_data()
                    elif k[0] == 0x0702:
                        iot_bus.ui_receive_data()
                    elif k[0] == 0x0703:
                        iot_bus.ui_sync_id()
                    g.draw_iot_page(force=True)
                else:
                    g.draw_iot_page(force=(page != _telemetry_last_page))
            except Exception:
                pass
        _telemetry_last_page = page
        return False

    try:
        k = dw._dw_read(0x5F60, 1)
        if k and k[0] == 0x0502:
            dw._dw_vp(0x5F60, b'\x00\x00')
            print("\n[DWIN] STOP button pressed during telemetry.")
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        raise
    except Exception:
        pass

    if _telemetry_buf is None or len(_telemetry_buf) < 6 * PROJECTS_MAX_DOTS:
        _telemetry_buf = bytearray(6 * PROJECTS_MAX_DOTS)

    n = 0
    buf = _telemetry_buf

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
                    if val == '#' and n < PROJECTS_MAX_DOTS:
                        struct.pack_into('>HHH', buf, n * 6,
                                         x + c * step, y + y_off + r * step, colour)
                        n += 1
            x += (cols - 1) * step + 3 + gap
        return x

    def add_arial(text, x, y, colour, xmax):
        nonlocal n
        for ch in text.upper():
            if ch == ' ':
                x += 5
                continue
            adv, pts = _ADOTS.get(ch, _ADOTS['?'])
            if x + adv > xmax:
                break
            for k in range(0, len(pts), 2):
                if n < PROJECTS_MAX_DOTS:
                    struct.pack_into('>HHH', buf, n * 6,
                                     x + pts[k], y + pts[k + 1], colour)
                    n += 1
            x += adv + 1
        return x

    page_idx = PROJECT_PAGES.index(page)
    entries = _telemetry_sensors[page_idx * 6 : (page_idx + 1) * 6]

    for i in range(len(entries)):
        _, label, val_str, col = entries[i][:4]
        x = 14 + (i % 3) * 154
        y = 56 + (i // 3) * 103

        clean_lbl = str(label).replace(' (', ' ').replace(')', '')[:10]
        clean_val = str(val_str).replace('0 [DETECT]', 'DETECT').replace('1 [CLEAR]', 'CLEAR')
        clean_val = clean_val.replace(' ', '')[:8]

        # Colored header strip: white text
        add_str(clean_lbl, x + 12, y + 8, 2, 0xFFFF)
        # Pale body: value text to the right of the icon box in Arial Bold
        if clean_val:
            add_arial(clean_val, x + 60, y + 48, col, x + 142)

    # Emit dot list to DWIN display VP 0x5500
    addr = PROJECTS_DOTS_VP + 2
    mv = memoryview(buf)
    for i in range(0, n * 6, 120):
        dw._dw_vp(addr + i // 2, mv[i:min(n * 6, i + 120)])
    dw._dw_vp(addr + n * 3, b'\xff\xff')
    dw._dw_vp(PROJECTS_DOTS_VP, struct.pack('>HH', 1, n))

    # Update the 6 card variable icon controls (VP 0x6110, 0x6210, 0x6310, 0x6410, 0x6510, 0x6610)
    for i in range(6):
        ic = entries[i][4] if i < len(entries) and len(entries[i]) >= 5 else 0
        if force or _telemetry_last_icons[i] != ic or page != _telemetry_last_page:
            dw._dw_vp(_DWIN_BOX_VP[i][1], bytes((ic >> 8, ic & 0xFF)))
            _telemetry_last_icons[i] = ic

    _telemetry_last_page = page
    _telemetry_changed = False
    return True


# ---- SENSOR GRAPH page (95): live line chart of up to 3 sensors ------------
# _telemetry_record() hands every numeric sensor result to _graph_feed(). Every
# 0.5 s the latest value of each of the first three numeric sensors goes into a
# 64-point history (about 30 s). While page 95 is on screen the board writes each
# history as a Basic Graphic line list (VP 0xFB40 / 0xFBE0 / 0xFC80 = GRAPH_LINE_VPS
# in make_sd_card.py), scaled to its own min..max, and the legend (name + value)
# as dots at 0x5400. dwin_wifi_ui redraws it when the page is opened while idle.
GRAPH_PAGE = 95
_GRAPH_VPS = (0xFB40, 0xFBE0, 0xFC80)
_GRAPH_COLOURS = (0xE8E4, 0x2B7F, 0x1D67)        # red, blue, green (= GRAPH_COLOURS)
_GRAPH_N = 64
_GRAPH_AREA = (26, 60, 464, 232)                 # where the points go (inside GRAPH_AREA)
_GRAPH_LEGEND_Y = (246, 268, 290)
_GRAPH_MS = 500
_GRAPH_MAX = 8                                   # sensors with a history (3 are shown)
_GRAPH_KEY_VP = 0x5F70                           # legend row taps: 0x0601-0x0603 (= GRAPH_KEY_VP)
_graph = {"keys": [], "names": {}, "latest": {}, "hist": {}, "t": 0, "slots": [0, 1, 2],
          "page": None, "page_t": 0, "legend": None, "buf": None}


def _graph_reset():
    for k in ("keys", "names", "latest", "hist"):
        _graph[k] = [] if k == "keys" else {}
    _graph["slots"] = [0, 1, 2]
    _graph["legend"] = None


def _graph_keys_poll():
    """A tapped legend row shows the next sensor not already on another row."""
    try:
        import dwin_screen as dw
        k = dw._dw_read(_GRAPH_KEY_VP, 1)
        if not k or not 0x0601 <= k[0] <= 0x0603:
            return False
        dw._dw_vp(_GRAPH_KEY_VP, b'\x00\x00')
        row, n, slots = k[0] - 0x0601, len(_graph["keys"]), _graph["slots"]
        for step in range(1, n + 1):
            cand = (slots[row] + step) % n
            if cand not in slots:
                slots[row] = cand
                break
        _graph["legend"] = None
        return True
    except Exception as e:
        print("graph keys:", e)
        return False


def _graph_feed(key, label, value):
    g = _graph
    if key not in g["hist"]:
        if len(g["keys"]) >= _GRAPH_MAX:
            return
        g["keys"].append(key)
        g["names"][key] = label.split(" (")[0][:10]
        g["hist"][key] = []
    g["latest"][key] = value
    now = time.ticks_ms()
    if time.ticks_diff(now, g["t"]) < _GRAPH_MS:
        return
    g["t"] = now
    for k in g["keys"]:
        if k in g["latest"]:
            h = g["hist"][k]
            h.append(g["latest"][k])
            if len(h) > _GRAPH_N:
                del h[0]
    _graph_draw(now)


def _graph_value(v):
    return ("%.1f" % v) if isinstance(v, float) else str(v)


def _graph_draw(now=None, force=False):
    """Draw the lines and the legend if page 95 is on screen."""
    try:
        import struct
        import dwin_screen as dw
        now = now or time.ticks_ms()
        if force or time.ticks_diff(now, _graph["page_t"]) > 500:
            p = dw._dw_read(0x0014, 1)
            _graph["page_t"] = now
            if p:
                if p[0] != _graph["page"]:
                    _graph["legend"] = None          # redraw the legend when the page comes back
                _graph["page"] = p[0]
        if _graph["page"] != GRAPH_PAGE:
            return
        _graph_keys_poll()                             # a row tapped: show another sensor
        x0, y0, x1, y1 = _GRAPH_AREA
        step = (x1 - x0) / (_GRAPH_N - 1)
        allk = _graph["keys"]
        keys = [allk[s] for s in _graph["slots"] if s < len(allk)]
        for i, vp in enumerate(_GRAPH_VPS):
            h = _graph["hist"].get(keys[i]) if i < len(keys) else None
            if not h or len(h) < 2:
                dw._dw_vp(vp, struct.pack(">HH", 2, 0))
                continue
            lo, hi = min(h), max(h)
            n = len(h)
            buf = bytearray(6 + 4 * n)
            struct.pack_into(">HHH", buf, 0, 2, n - 1, _GRAPH_COLOURS[i])   # line command, segments, colour
            for j, v in enumerate(h):
                y = (y0 + y1) // 2 if hi == lo else int(y1 - (v - lo) * (y1 - y0) / (hi - lo))
                struct.pack_into(">HH", buf, 6 + 4 * j, int(x1 - (n - 1 - j) * step), y)
            mv = memoryview(buf)
            for o in range(6, len(buf), 240):         # points first, then the header
                dw._dw_vp(vp + o // 2, mv[o:min(len(buf), o + 240)])
            dw._dw_vp(vp, mv[0:6])
        more = len(allk) > 3                           # say that rows can be changed
        legend = tuple("%s %s%s" % (_graph["names"][k], _graph_value(_graph["latest"].get(k, "")),
                                    " >" if more else "") for k in keys)
        if force or legend != _graph["legend"]:
            if _graph["buf"] is None:
                _graph["buf"] = bytearray(6 * 1100)
            b = _graph["buf"]
            n = 0
            for text, y in zip(legend, _GRAPH_LEGEND_Y):
                n = dw._dw_text_dots(b, n, text[:30], 48, y, 2, 0x1947)
            n = min(n, 900)                            # ends before the key VP 0x5F00
            mv = memoryview(b)
            for o in range(0, n * 6, 120):
                dw._dw_vp(0x5402 + o // 2, mv[o:min(n * 6, o + 120)])
            dw._dw_vp(0x5402 + n * 3, b'\xff\xff')
            dw._dw_vp(0x5400, struct.pack(">HH", 1, n))
            _graph["legend"] = legend
    except Exception as e:
        print("graph:", e)


def _telemetry_record(fn_name, args, result):
    global _telemetry_changed, _telemetry_last_draw_ms
    if fn_name in _TELEMETRY_IGNORE:
        return
    if not _telemetry_sensors:                   # main.py empties it when a program starts
        _graph_reset()
    col = _COL_VAL
    val_str = ""

    # ── Actuators / Outputs (Name only, no live value) ──
    if "buzzer" in fn_name:
        pin = str(args[0]) if len(args) > 0 else ""
        key = "BUZZER:" + pin
        label = ("BUZZER (" + pin + ")") if pin else "BUZZER"
        val_str = ""
        col = _COL_VAL

    elif "servo" in fn_name:
        pin = str(args[0]) if len(args) > 0 else ""
        key = "SERVO:" + pin
        label = ("SERVO (" + pin + ")") if pin else "SERVO"
        val_str = ""
        col = _COL_VAL

    elif "motor" in fn_name:
        key = "MOTOR:MAIN"
        label = "MOTORS"
        val_str = ""
        col = _COL_VAL

    elif any(x in fn_name for x in ("led", "red", "green", "blue", "rgb")):
        pin = str(args[0]) if len(args) > 0 else ""
        key = "LED:" + pin
        label = ("LED (" + pin + ")") if pin else "LED"
        val_str = ""
        col = _COL_VAL

    elif "relay" in fn_name:
        pin = str(args[0]) if len(args) > 0 else ""
        key = "RELAY:" + pin
        label = ("RELAY (" + pin + ")") if pin else "RELAY"
        val_str = ""
        col = _COL_VAL

    elif "waterpump" in fn_name or "pump" in fn_name:
        pin = str(args[0]) if len(args) > 0 else ""
        key = "PUMP:" + pin
        label = ("PUMP (" + pin + ")") if pin else "PUMP"
        val_str = ""
        col = _COL_VAL

    elif result is None:
        return

    else:
        # ── Sensors / Inputs ──
        raw = fn_name[6:] if fn_name.startswith("async_") else fn_name
        name = raw.replace("_", " ").upper()
        if name.startswith("_"):
            return

        pin_str = ",".join(str(a) for a in args) if args else ""
        key = name + ":" + pin_str
        label = (name + " (" + pin_str + ")") if pin_str else name
        if len(label) > 18:
            label = label[:18]

        if result is True or result is False:
            val_str = "1" if result else "0"
            col = _COL_GOOD if result else _COL_GREY
        elif isinstance(result, int):
            if any(x in name for x in ("IR", "MOTION", "FLAME", "BUTTON", "TILT")):
                if result == 0:
                    val_str = "0 [DETECT]"
                    col = _COL_GOOD
                else:
                    val_str = "1 [CLEAR]"
                    col = _COL_GREY
            else:
                val_str = str(result)
        elif isinstance(result, float):
            val_str = "{:.1f}".format(result)
            if "ULTRA" in name:
                val_str += " CM"
        else:
            val_str = str(result)[:14].upper()
        if (isinstance(result, int) or isinstance(result, float)) and result is not True and result is not False:
            _graph_feed(key, label, result)          # SENSOR GRAPH page

    for entry in _telemetry_sensors:
        if entry[0] == key:
            if entry[2] != val_str:
                entry[2] = val_str
                entry[3] = col
                _telemetry_changed = True
            if len(entry) < 5:
                entry.append(_telemetry_icon_for(fn_name) or _telemetry_icon_for(label) or _telemetry_icon_for(key))
            break
    else:
        if len(_telemetry_sensors) < PROJECTS_MAX_ITEMS:
            icon_id = _telemetry_icon_for(fn_name) or _telemetry_icon_for(label) or _telemetry_icon_for(key)
            _telemetry_sensors.append([key, label, val_str, col, icon_id])
            _telemetry_changed = True

    now = time.ticks_ms()
    if time.ticks_diff(now, _telemetry_last_draw_ms) > 250:
        _telemetry_draw()
        _telemetry_last_draw_ms = now


def _dwin_clear_last_call():
    global _dwin_last_call
    _dwin_last_call = None


def _dwin_make_recorder(fn, fn_name):
    async def _recorded(*args, **kwargs):
        global _dwin_last_call
        is_act = any(act in fn_name for act in ("buzzer", "servo", "motor", "led", "red", "green", "blue", "rgb", "relay", "pump", "waterpump"))
        if is_act:
            _telemetry_record(fn_name, args, None)
        result = fn(*args, **kwargs)
        if hasattr(result, "send"):
            result = await result
        _dwin_last_call = (fn_name, args, result)
        if not is_act:
            _telemetry_record(fn_name, args, result)
        return result
    return _recorded


def _dwin_install_recorders():
    g = globals()
    for name in list(g.keys()):
        if not name.startswith("async_") or name.startswith("async_lcd"):
            continue
        obj = g[name]
        if callable(obj):
            g[name] = _dwin_make_recorder(obj, name)


def lcd_boxes():
    """Debug: print what each box shows now."""
    for i in range(_DWIN_MAX_BOXES):
        n, v, _ = _dwin_sent[i]
        print("BOX", i + 1, ":", n or "-", v or "")


# Wrap every async_ function defined ABOVE this line (keep this call LAST).
_dwin_install_recorders()

################################################################################
# END OF lib.py
################################################################################

# ============================================
# COMMON FINGERPRINT SENSOR LIBRARY
# MicroPython + uasyncio
# EF01 UART fingerprint protocol
# ============================================

from machine import UART
import uasyncio as asyncio
import time

# ============================================
# CONFIGURATION
# ============================================

FP_BAUDRATE = 57600
FP_DEFAULT_MAX_ID = 200

_FP_ADDRESS = b"\xFF\xFF\xFF\xFF"
_FP_UARTS = {}
_FP_LOCKS = {}


# ============================================
# UART INITIALIZATION
# ============================================

def _fp_get_uart(port="UART1"):

    if isinstance(port, str):
        if not port.startswith("UART"):
            raise ValueError("Invalid UART port")
        uart_id = int(port[4:])
    else:
        uart_id = int(port)

    if uart_id not in _FP_UARTS:
        _FP_UARTS[uart_id] = UART(
            uart_id,
            baudrate=FP_BAUDRATE,
            bits=8,
            parity=None,
            stop=1,
            timeout=50
        )

    return _FP_UARTS[uart_id]


def _fp_get_lock(port):
    key = str(port)

    if key not in _FP_LOCKS:
        _FP_LOCKS[key] = asyncio.Lock()

    return _FP_LOCKS[key]


# ============================================
# PACKET BUILDING
# ============================================

def _fp_make_packet(command, params=b""):

    content = bytes([command]) + params
    length = len(content) + 2

    packet = bytearray(b"\xEF\x01")
    packet.extend(_FP_ADDRESS)

    packet.append(0x01)
    packet.append((length >> 8) & 0xFF)
    packet.append(length & 0xFF)

    packet.extend(content)

    checksum = sum(packet[6:]) & 0xFFFF

    packet.append((checksum >> 8) & 0xFF)
    packet.append(checksum & 0xFF)

    return packet


# ============================================
# COMMON ASYNC COMMAND
# ============================================

async def _fp_command(
    port,
    command,
    params=b"",
    timeout_ms=3000
):

    uart = _fp_get_uart(port)

    # Clear old incoming bytes
    while uart.any():
        uart.read()

    packet = _fp_make_packet(command, params)
    uart.write(packet)

    start = time.ticks_ms()
    data = bytearray()

    while time.ticks_diff(
        time.ticks_ms(), start
    ) < timeout_ms:

        if uart.any():
            chunk = uart.read()

            if chunk:
                data.extend(chunk)

        if len(data) >= 9:

            # Check packet header and address
            if data[:2] != b"\xEF\x01":
                raise OSError("Invalid fingerprint header")

            if data[2:6] != _FP_ADDRESS:
                raise OSError("Invalid fingerprint address")

            if data[6] != 0x07:
                raise OSError("Invalid response type")

            length = (data[7] << 8) | data[8]
            total = 9 + length

            if length < 3 or length > 512:
                raise OSError("Invalid packet length")

            if len(data) >= total:

                response = data[:total]

                received = (
                    (response[-2] << 8) |
                    response[-1]
                )

                calculated = (
                    sum(response[6:-2]) & 0xFFFF
                )

                if received != calculated:
                    raise OSError(
                        "Fingerprint checksum error"
                    )

                # Return confirmation code
                # and any additional response data
                return (
                    response[9],
                    bytes(response[10:-2])
                )

        await asyncio.sleep_ms(10)

    raise OSError("Fingerprint UART timeout")


# ============================================
# GET FINGER IMAGE
# ============================================

async def _fp_get_image(port):

    status, data = await _fp_command(
        port, 0x01, timeout_ms=1500
    )

    return status


# ============================================
# GENERATE CHARACTER
# ============================================

async def _fp_generate(port, buffer_id):

    status, data = await _fp_command(
        port,
        0x02,
        bytes([buffer_id])
    )

    return status == 0


# ============================================
# WAIT FOR FINGER
# ============================================

async def _fp_wait_finger(
    port,
    timeout_ms=20000
):

    start = time.ticks_ms()

    while time.ticks_diff(
        time.ticks_ms(), start
    ) < timeout_ms:

        status = await _fp_get_image(port)

        if status == 0:
            return True

        if status != 0x02:
            raise OSError(
                "Fingerprint image error: %d" %
                status
            )

        await asyncio.sleep_ms(100)

    return False


# ============================================
# WAIT FOR FINGER REMOVAL
# ============================================

async def _fp_wait_remove(
    port,
    timeout_ms=15000
):

    start = time.ticks_ms()

    while time.ticks_diff(
        time.ticks_ms(), start
    ) < timeout_ms:

        status = await _fp_get_image(port)

        if status == 0x02:
            return True

        if status != 0:
            raise OSError(
                "Fingerprint removal error: %d" %
                status
            )

        await asyncio.sleep_ms(100)

    return False


# ============================================
# CREATE TEMPLATE MODEL
# ============================================

async def _fp_create_model(port):

    status, data = await _fp_command(
        port, 0x05
    )

    return status == 0


# ============================================
# STORE FINGERPRINT
# ============================================

async def _fp_store(port, user_id):

    params = bytes([
        0x01,
        (user_id >> 8) & 0xFF,
        user_id & 0xFF
    ])

    status, data = await _fp_command(
        port, 0x06, params
    )

    return status == 0


# ============================================
# READ TEMPLATE INDEX
# ============================================

async def _fp_index_page(port, page):

    status, data = await _fp_command(
        port,
        0x1F,
        bytes([page])
    )

    if status != 0:
        raise OSError(
            "Fingerprint index unsupported/error"
        )

    if len(data) < 32:
        raise OSError("Invalid index response")

    return data[:32]


# ============================================
# LIST STORED FINGERPRINT IDS
# ============================================

async def async_fingerprint_ids(
    port="UART1",
    max_id=FP_DEFAULT_MAX_ID
):

    if max_id < 1 or max_id > 1000:
        raise ValueError("Invalid max_id")

    lock = _fp_get_lock(port)

    async with lock:

        ids = []

        total_pages = (max_id // 256) + 1

        for page in range(total_pages):

            index = await _fp_index_page(
                port, page
            )

            for byte_no, value in enumerate(index):

                for bit in range(8):

                    finger_id = (
                        page * 256 +
                        byte_no * 8 +
                        bit
                    )

                    if finger_id < 1:
                        continue

                    if finger_id > max_id:
                        break

                    if value & (1 << bit):
                        ids.append(finger_id)

        return ids


# ============================================
# COUNT STORED FINGERPRINTS
# ============================================

async def async_fingerprint_count(
    port="UART1"
):

    lock = _fp_get_lock(port)

    async with lock:

        status, data = await _fp_command(
            port, 0x1D
        )

        if status != 0 or len(data) < 2:
            raise OSError(
                "Fingerprint count failed"
            )

        return (data[0] << 8) | data[1]


# ============================================
# ENROLL FINGERPRINT
# ============================================

async def async_fingerprint_enroll(
    port="UART1",
    user_id=None,
    timeout_ms=20000,
    max_id=FP_DEFAULT_MAX_ID
):

    if max_id < 1 or max_id > 1000:
        raise ValueError("Invalid max_id")

    lock = _fp_get_lock(port)

    async with lock:

        # Read actual occupied locations
        occupied = set()

        pages = (max_id // 256) + 1

        for page in range(pages):

            index = await _fp_index_page(
                port, page
            )

            for b, value in enumerate(index):

                for bit in range(8):

                    fid = (
                        page * 256 +
                        b * 8 + bit
                    )

                    if 1 <= fid <= max_id:
                        if value & (1 << bit):
                            occupied.add(fid)

        # Automatically choose a free ID
        if user_id is None:

            user_id = None

            for fid in range(1, max_id + 1):

                if fid not in occupied:
                    user_id = fid
                    break

            if user_id is None:
                print("Fingerprint memory full")
                return None

        else:
            user_id = int(user_id)

            if not 1 <= user_id <= max_id:
                raise ValueError(
                    "Fingerprint ID out of range"
                )

        # Protect existing fingerprints
        if user_id in occupied:
            print(
                "Fingerprint ID already occupied:",
                user_id
            )
            return None

        print("ENROLL ID:", user_id)

        # First image
        print("Place finger")

        if not await _fp_wait_finger(
            port, timeout_ms
        ):
            print("First scan timeout")
            return None

        if not await _fp_generate(port, 1):
            print("First image failed")
            return None

        print("Remove finger")

        if not await _fp_wait_remove(
            port, timeout_ms
        ):
            print("Finger removal timeout")
            return None

        # Second image
        print("Place same finger again")

        if not await _fp_wait_finger(
            port, timeout_ms
        ):
            print("Second scan timeout")
            return None

        if not await _fp_generate(port, 2):
            print("Second image failed")
            return None

        if not await _fp_create_model(port):
            print("Fingerprints do not match")
            return None

        if not await _fp_store(port, user_id):
            print("Fingerprint storage failed")
            return None

        print("ENROLL SUCCESS:", user_id)

        return user_id


# ============================================
# SEARCH FINGERPRINT
# ============================================

async def async_fingerprint_match(
    port="UART1",
    max_id=FP_DEFAULT_MAX_ID
):

    if not 1 <= max_id <= 1000:
        raise ValueError("Invalid max_id")

    lock = _fp_get_lock(port)

    async with lock:

        status = await _fp_get_image(port)

        # No finger placed
        if status == 0x02:
            return None

        if status != 0:
            raise OSError(
                "Fingerprint capture failed"
            )

        if not await _fp_generate(port, 1):
            return None

        params = bytes([
            0x01,
            0x00, 0x00,
            (max_id >> 8) & 0xFF,
            max_id & 0xFF
        ])

        status, data = await _fp_command(
            port,
            0x04,
            params
        )

        # No matched fingerprint
        if status == 0x09:
            return None

        if status != 0:
            raise OSError(
                "Fingerprint search failed"
            )

        if len(data) < 4:
            raise OSError(
                "Invalid search response"
            )

        user_id = (
            (data[0] << 8) |
            data[1]
        )

        return user_id


# ============================================
# DELETE ONE FINGERPRINT
# ============================================

async def async_fingerprint_delete(
    port="UART1",
    user_id=1
):

    user_id = int(user_id)

    if not 1 <= user_id <= 1000:
        raise ValueError("Invalid fingerprint ID")

    params = bytes([
        (user_id >> 8) & 0xFF,
        user_id & 0xFF,
        0x00,
        0x01
    ])

    lock = _fp_get_lock(port)

    async with lock:

        status, data = await _fp_command(
            port,
            0x0C,
            params
        )

        return status == 0


# ============================================
# DELETE ALL FINGERPRINTS
# ============================================

async def async_fingerprint_empty(
    port="UART1",
    confirm=False
):

    if confirm is not True:
        print(
            "Set confirm=True to erase all"
        )
        return False

    lock = _fp_get_lock(port)

    async with lock:

        status, data = await _fp_command(
            port, 0x0D
        )

        return status == 0

# -- DWIN screen: pictures, saved pictures, video (dwin_screen.py, R4 board) --
try:
    from dwin_screen import *
except Exception as _dw_err:
    print('lib: DWIN screen functions not loaded:', _dw_err)


# ==============================================================================
# IoT CLOUD & KIT-TO-KIT COMMUNICATION (ESP32-S3 Gateway + DWIN Page 96)
# ==============================================================================

_iot_seq = 0
_ts_write_key = ""
_ts_read_key  = ""
_ts_channel   = ""
_ts_base      = ""
_ts_auto_mode = False
_ts_last      = {}


async def _iot_call(op, params, timeout_ms=10000, esp_only=False):
    global _iot_seq
    import json
    import iot_bus
    _iot_seq = (_iot_seq + 1) & 0x7FFF
    rid = _iot_seq
    msg = {"id": rid, "op": op}
    msg.update(params)
    iot_bus.send("IOT:" + json.dumps(msg) + "\n", esp_only=esp_only)
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
        rep = iot_bus.take(rid)
        if rep is not None:
            return rep.get("code", 0), rep.get("body", ""), rep.get("err", "")
        await asyncio.sleep_ms(20)
    return 0, "", "timeout"


# ---- LLM CHAT -----------------------------------------------------------------
# PUT YOUR AI LINK HERE. The display's LLM CHAT page (home page 3) and
# async__llm_ask() use it. The request goes out through the ESP32 Wi-Fi gateway
# (iot_bus "http" op), so Wi-Fi must be connected (Settings > Wi-Fi).
#   OpenAI-style API (OpenAI, Groq, OpenRouter, ...): needs the ESP32 firmware
#   with "headers" support (2026-10-29) for the key.
#     LLM_URL = "https://api.openai.com/v1/chat/completions"
#     LLM_KEY = "sk-..."                    sent as "Authorization: Bearer <key>"
#     LLM_MODEL = "gpt-4o-mini"
#   Google Gemini (the key goes in the link, works with the old firmware too):
#     LLM_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
#     LLM_KEY = "AIza..."
#   Your own server / link, no key:
#     "https://example.com/ask?q={q}"  -> GET, the question replaces {q}
#     "https://example.com/ask"        -> POST {"question": "..."}
#     The reply can be plain text or JSON ("answer", "reply", "text", ...).
LLM_URL = ""
LLM_KEY = ""
LLM_MODEL = ""
LLM_SYSTEM = ("You are a friendly helper for school students using a robotics kit. "
              "Answer in plain text without markdown, in under 60 words.")
LLM_MAX_TOKENS = 200
LLM_TIMEOUT_MS = 30000
_LLM_PROGRAM_ID = 76                     # reply id for async__llm_ask (the display uses 75)


def llm_ready():
    """True when an AI link is set in LLM_URL."""
    return bool(LLM_URL.strip())


def _llm_quote(s):
    out = []
    for b in s.encode():
        c = chr(b)
        out.append(c if (b < 128 and c.isalpha()) or c.isdigit() or c in "-_.~" else "%%%02X" % b)
    return "".join(out)


def _llm_request(question, history=()):
    """(method, url, body, content type, headers) for LLM_URL; history is the
    last [(question, answer), ...] so the AI knows what was asked before."""
    import json
    url = LLM_URL.strip()
    if "{q}" in url:
        return "GET", url.replace("{q}", _llm_quote(question)), "", "", None
    if "generativelanguage.googleapis.com" in url and "/openai" not in url:
        turns = []
        for q, a in history:
            turns.append({"role": "user", "parts": [{"text": q}]})
            turns.append({"role": "model", "parts": [{"text": a}]})
        turns.append({"role": "user", "parts": [{"text": question}]})
        if LLM_KEY and "key=" not in url:
            url += ("&" if "?" in url else "?") + "key=" + LLM_KEY
        body = {"contents": turns, "systemInstruction": {"parts": [{"text": LLM_SYSTEM}]}}
        return "POST", url, json.dumps(body), "application/json", None
    if LLM_KEY or LLM_MODEL:                                # OpenAI-style chat completions
        msgs = [{"role": "system", "content": LLM_SYSTEM}]
        for q, a in history:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": question})
        body = {"messages": msgs, "max_tokens": LLM_MAX_TOKENS}
        if LLM_MODEL:
            body["model"] = LLM_MODEL
        hdr = {"Authorization": "Bearer " + LLM_KEY} if LLM_KEY else None
        return "POST", url, json.dumps(body), "application/json", hdr
    return "POST", url, json.dumps({"question": question}), "application/json", None


def _llm_send(rid, question, history=()):
    """Send the question through the ESP32 gateway; the reply arrives as
    iot_bus.take(rid). Returns None when sent, else why it was not."""
    import json
    import iot_bus
    if not llm_ready():
        return "No AI link yet. Put LLM_URL (and LLM_KEY) in lib.py."
    if not iot_bus.esp_present():
        return "ESP32 Wi-Fi gateway not found."
    if not iot_bus.net_up():
        return "Wi-Fi is not connected (Settings > Wi-Fi)."
    method, url, body, ctype, hdr = _llm_request(question, history)
    req = {"id": rid, "op": "http", "method": method, "url": url, "body": body, "ctype": ctype,
           "timeout": LLM_TIMEOUT_MS - 2000}
    if hdr:
        req["headers"] = hdr
    iot_bus.take(rid)
    iot_bus.send("IOT:" + json.dumps(req) + "\n", esp_only=True)
    return None


def _llm_json_str(body, key):
    """The string value of "key" in JSON text that may be cut off, or ''."""
    tag = '"%s"' % key
    i = body.find(tag)
    while i >= 0:
        j = i + len(tag)
        while j < len(body) and body[j] in ' \t\r\n':
            j += 1
        if j < len(body) and body[j] == ':':
            j += 1
            while j < len(body) and body[j] in ' \t\r\n':
                j += 1
            if j < len(body) and body[j] == '"':
                out = []
                j += 1
                while j < len(body) and body[j] != '"':
                    c = body[j]
                    if c == '\\' and j + 1 < len(body):
                        j += 1
                        c = body[j]
                        if c == 'n':
                            c = '\n'
                        elif c in 'tr':
                            c = ' '
                        elif c == 'u':
                            try:
                                c = chr(int(body[j + 1:j + 5], 16))
                                j += 4
                            except ValueError:
                                c = '?'
                    out.append(c)
                    j += 1
                return ''.join(out)
        i = body.find(tag, i + 1)
    return ''


def _llm_pick(o):
    """First answer text inside a decoded JSON reply (OpenAI, Gemini, simple)."""
    if isinstance(o, str):
        return o
    if isinstance(o, list):
        for v in o:
            t = _llm_pick(v)
            if t:
                return t
    elif isinstance(o, dict):
        for k in ("choices", "candidates", "message", "content", "parts", "text", "answer",
                  "reply", "response", "output", "result", "data", "error"):
            if k in o:
                t = _llm_pick(o[k])
                if t:
                    return t
    return ""


def _llm_clean(text):
    """Plain ASCII for the display font: smart quotes, dashes, markdown out."""
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("…", "..."), ("°", " deg"),
                 ("**", ""), ("__", ""), ("`", ""), ("#", "")):
        text = text.replace(a, b)
    return "".join(c if " " <= c <= "~" or c == "\n" else " " for c in text).strip()


def _llm_text(body):
    import json
    body = (body or "").strip()
    try:
        return _llm_pick(json.loads(body))
    except ValueError:
        pass
    if body[:1] in "{[":                                # cut off at the gateway's 2 KB limit
        for k in ("content", "text", "answer", "reply", "response", "message"):
            t = _llm_json_str(body, k)
            if t:
                return t
    return body


def _llm_reply(rep):
    """(ok, text) from the gateway's reply to _llm_send."""
    code, err = rep.get("code", 0), rep.get("err", "") or ""
    if not code:
        if err == "offline":
            return False, "Wi-Fi is not connected (Settings > Wi-Fi)."
        return False, "Network error: " + (err or "no reply")
    text = _llm_clean(_llm_text(rep.get("body", "")))
    if code != 200:
        if code in (401, 403):
            return False, "Error %d: check LLM_KEY. %s" % (code, text[:100])
        return False, "Error %d: %s" % (code, text[:120] or err)
    return (True, text) if text else (False, "Empty reply from the AI.")


async def async__llm_ask(question):
    """Ask the AI set in LLM_URL; returns the answer text ('' on an error).
    The question and the answer also show on the display's LLM CHAT page."""
    import iot_bus
    question = str(question).strip()
    chat = None
    try:
        import dwin_llm_chat as chat
        chat.show_question(question, go=True)
    except Exception as e:
        print("llm chat page:", e)
    err = _llm_send(_LLM_PROGRAM_ID, question, chat.history() if chat else ())
    ok, text = False, err
    if err is None:
        t0 = time.ticks_ms()
        text = "No reply - check Wi-Fi and LLM_URL."
        while time.ticks_diff(time.ticks_ms(), t0) < LLM_TIMEOUT_MS + 3000:
            rep = iot_bus.take(_LLM_PROGRAM_ID)
            if rep is not None:
                ok, text = _llm_reply(rep)
                break
            await asyncio.sleep_ms(50)
    if chat:
        chat.show_answer(ok, text, draw=True)
    print(("AI: " if ok else "AI error: ") + text)
    return text if ok else ""


def device_id():
    """Return this board's hardware ID (from the STM32's 96-bit factory UID)."""
    import iot_bus
    return iot_bus.device_id()


def kit_id():
    """Return this kit's short ID (e.g. 'CURIO-XXXX')."""
    import iot_bus
    return iot_bus.kit_id()


async def async_ts_server(url):
    """Point ThingSpeak / Curio Cloud blocks at a self-hosted server."""
    global _ts_base
    _ts_base = str(url).strip().rstrip("/")
    await _iot_call("ts_server", {"url": _ts_base}, timeout_ms=3000)
    print("[IoT] server ->", _ts_base or "api.thingspeak.com")


async def async_ts_auto(name=""):
    """Zero-config setup: register/retrieve this kit's cloud channel and update Page 96."""
    global _ts_write_key, _ts_read_key, _ts_channel, _ts_auto_mode
    import json, iot_bus
    _t0("async_ts_auto")
    _ts_auto_mode = True
    hw = device_id()
    code, body, err = await _iot_call("ts_auto", {"hw": hw, "name": str(name)}, timeout_ms=10000)
    _t1("async_ts_auto")
    if code == 200 and body:
        try:
            info = json.loads(body)
            _ts_channel   = str(info.get("channel_id", ""))
            _ts_write_key = str(info.get("write_key", ""))
            _ts_read_key  = str(info.get("read_key", ""))
            iot_bus.record_cloud(True, channel_id=_ts_channel)
            print("[IoT] auto ready ->", info.get("name", hw), "channel", _ts_channel)
            return True
        except Exception as e:
            err = str(e)
    print("[IoT] auto setup failed:", err or code)
    return False


async def async_ts_connect(channel_id, write_key="", read_key=""):
    """Manual setup with an explicit channel ID and API keys."""
    global _ts_write_key, _ts_read_key, _ts_channel, _ts_auto_mode
    import iot_bus
    _ts_auto_mode = False
    _ts_channel   = str(channel_id).strip()
    _ts_write_key = str(write_key).strip()
    _ts_read_key  = str(read_key).strip()
    iot_bus.record_cloud(True, channel_id=_ts_channel)
    await _iot_call("ts_config", {
        "ch": _ts_channel, "wk": _ts_write_key, "rk": _ts_read_key, "base": _ts_base
    }, timeout_ms=3000)
    await asyncio.sleep_ms(0)


async def async_ts_send(field, value):
    """Send one value to field 1..8 and update DWIN Page 96 TX box."""
    return await async_ts_send_multi({int(field): value})


async def async_ts_send_multi(fields_dict):
    """Send a dict of {field_number: value} and update DWIN Page 96 TX box."""
    import iot_bus
    _t0("async_ts_send")
    clean = {}
    first_str = ""
    for k, v in fields_dict.items():
        idx = int(k)
        if 1 <= idx <= 8 and v is not None:
            clean[str(idx)] = v
            if not first_str:
                first_str = "F%d:%s" % (idx, str(v)[:9])
    if not clean:
        _t1("async_ts_send")
        return 0
    if not _ts_write_key and _ts_auto_mode:
        await async_ts_auto()
    params = {"wk": _ts_write_key, "fields": clean}
    if _ts_base:
        params["base"] = _ts_base
    code, body, err = await _iot_call("ts_write", params)
    _t1("async_ts_send")
    body_s = str(body).strip()
    if code == 200 and body_s.isdigit() and int(body_s) > 0:
        iot_bus.record_tx(first_str, ok=True)
        return int(body_s)
    iot_bus.record_tx(first_str or "TX", ok=False)
    print("[IoT] send failed:", err or ("HTTP " + str(code)))
    return 0


async def async_ts_fetch(field=0):
    """Fetch the latest entry from the channel and update DWIN Page 96 RX box."""
    global _ts_last
    import json, iot_bus
    _t0("async_ts_fetch")
    if not _ts_channel and _ts_auto_mode:
        await async_ts_auto()
    if not _ts_channel and not iot_bus.esp_present():
        _t1("async_ts_fetch")
        return None
    f = int(field) if field else 0
    params = {"ch": _ts_channel, "rk": _ts_read_key, "field": f}
    if _ts_base:
        params["base"] = _ts_base
    code, body, err = await _iot_call("ts_read", params)
    _t1("async_ts_fetch")
    if code != 200 or not body:
        print("[IoT] fetch failed:", err or ("HTTP " + str(code)))
        return None
    if f > 0:
        s = body.strip()
        _ts_last[f] = s
        iot_bus.record_rx("F%d:%s" % (f, s[:9]), ok=True)
        try:
            return int(s) if "." not in s else float(s)
        except Exception:
            return s
    try:
        data = json.loads(body)
        for i in range(1, 9):
            k = "field" + str(i)
            if k in data and data[k] is not None:
                _ts_last[i] = data[k]
        if 1 in _ts_last:
            iot_bus.record_rx(str(_ts_last[1])[:12], ok=True)
        return _ts_last
    except Exception as e:
        print("[IoT] JSON error:", e)
        return None


def ts_field(field):
    """Return the cached value of field 1..8 from the most recent async_ts_fetch(0)."""
    v = _ts_last.get(int(field))
    if v is None:
        return 0
    try:
        return int(v) if "." not in str(v) else float(v)
    except Exception:
        return v


def iot_send(data, field=1):
    """Send kit-to-kit / cloud data and update DWIN Page 96 Send Data (TX)."""
    import iot_bus
    iot_bus.ui_send_data(str(data))
    return True


async def async_iot_send(data, field=1):
    """Async version: send data to cloud / kit-to-kit and update DWIN Page 96."""
    res = await async_ts_send(field, data)
    return res


def iot_receive():
    """Trigger kit-to-kit / cloud receive and return latest received data on DWIN Page 96."""
    import iot_bus
    iot_bus.ui_receive_data()
    return iot_bus.get_iot_state().get("rx_data", "")


async def async_iot_receive(field=1):
    """Async version: fetch latest data from cloud / kit-to-kit and update DWIN Page 96."""
    return await async_ts_fetch(field)

