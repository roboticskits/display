import random
import time
from machine import Pin

# ============================================================
# HARDWARE UART FOR DWIN DISPLAY (USART3 on PD8 / PD9, connector J5)
# J5 is wired straight (display TX -> J5 TX, display RX -> J5 RX), so the
# STM32's TX and RX are swapped inside USART3 (CR2.SWAP):
#   TX = PD9 (J5 pin 5, RXD_DISP)   RX = PD8 (J5 pin 2, TXD_DISP)
# With a crossed cable set DWIN_SWAP = False.
# ============================================================

import machine
from machine import UART

DWIN_BAUD = 115200          # the display's speed (T5LCFG.CFG of the SD card)
DWIN_SWAP = True
_USART3 = 0x40004800        # USART3 registers (STM32H723)


class DwinUART:

    def __init__(self, baudrate=DWIN_BAUD, swap=DWIN_SWAP):
        self.uart = UART(3, baudrate, timeout=0, rxbuf=512)
        Pin("D8", Pin.ALT, alt=7)                       # PD8 / PD9 = USART3 (AF7)
        Pin("D9", Pin.ALT, alt=7)
        cr1 = machine.mem32[_USART3]
        machine.mem32[_USART3] = cr1 & ~1               # UE off: SWAP may only change then
        cr2 = machine.mem32[_USART3 + 4]
        machine.mem32[_USART3 + 4] = (cr2 | (1 << 15)) if swap else (cr2 & ~(1 << 15))
        machine.mem32[_USART3] = cr1                    # UE back on

    def write(self, data):
        """Send bytes or bytearray buffer over TX."""
        self.uart.write(data)

    def read_bytes(self, expected_len, timeout_ms=100):
        """Read a fixed number of bytes from the display."""
        buffer = bytearray()
        start_time = time.ticks_ms()
        while len(buffer) < expected_len:
            if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                break
            data = self.uart.read(expected_len - len(buffer))
            if data:
                buffer.extend(data)
        return bytes(buffer)

    def flush_input(self):
        while self.uart.read():
            pass


dwin = DwinUART()


# ============================================================
# DWIN VP ADDRESS DEFINITIONS
# ============================================================

VP_TEMPERATURE = 0x1100
VP_HUMIDITY = 0x1102
VP_ULTRASONIC = 0x1104
VP_LIGHT = 0x1106
VP_GAS = 0x1108
VP_WATER_LEVEL = 0x1110

VP_IR_SENSOR = 0x1200
VP_PIR_MOTION = 0x1202

VP_READ_DEMO = 0x1300


# ============================================================
# SENSOR PIN DEFINITIONS (FOR REFERENCE)
# ============================================================

DHT_PIN = "C0"
ULTRASONIC_TRIG_PIN = "C1"
ULTRASONIC_ECHO_PIN = "D4"
IR_PIN = "F9"
PIR_PIN = "D3"
LIGHT_PIN = "C2"
GAS_PIN = "A0"
WATER_PIN = "A1"


# ============================================================
# UPDATE INTERVALS (ms)
# ============================================================

DHT_INTERVAL_MS = 2000
ULTRASONIC_INTERVAL_MS = 200
LIGHT_INTERVAL_MS = 500
GAS_INTERVAL_MS = 500
WATER_INTERVAL_MS = 500
IR_INTERVAL_MS = 1000
PIR_INTERVAL_MS = 1000
DWIN_READ_INTERVAL_MS = 1000


# ============================================================
# DWIN PROTOCOL FUNCTIONS (WRITE & READ)
# ============================================================


def dwin_write_u16(vp, value):
    """Write 16-bit Unsigned Integer to DWIN VP."""
    value = max(0, min(65535, int(value)))

    packet = bytes(
        [
            0x5A,
            0xA5,
            0x05,  # Length
            0x82,  # Write command
            (vp >> 8) & 0xFF,
            vp & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )

    dwin.write(packet)


def dwin_write_text(vp, text, length=15):
    """Write ASCII string to DWIN VP."""
    data = text.encode("ascii")

    if len(data) > length:
        data = data[:length]
    elif len(data) < length:
        data = data + b" " * (length - len(data))

    packet = (
        bytes(
            [
                0x5A,
                0xA5,
                3 + len(data),
                0x82,
                (vp >> 8) & 0xFF,
                vp & 0xFF,
            ]
        )
        + data
    )

    dwin.write(packet)


def dwin_read_vp(vp, num_words=1):
    """Send read request command (0x83) and receive value back from DWIN."""
    request = bytes(
        [
            0x5A,
            0xA5,
            0x04,  # Frame length
            0x83,  # Read VP Command
            (vp >> 8) & 0xFF,
            vp & 0xFF,
            num_words & 0xFF,
        ]
    )

    dwin.flush_input()
    dwin.write(request)

    # DWIN Response: 0x5A 0xA5 | Length | 0x83 | VP_H | VP_L | Words | Val_H | Val_L
    expected_bytes = 7 + (num_words * 2)
    response = dwin.read_bytes(expected_bytes, timeout_ms=100)

    if response and len(response) >= expected_bytes and response[3] == 0x83:
        value_h = response[7]       # response[6] is the word count
        value_l = response[8]
        return (value_h << 8) | value_l

    return None


# ============================================================
# SIMULATED SENSOR UPDATES (RANDOM DATA)
# ============================================================


def update_temperature_humidity():
    # Random Temperature: 20°C to 40°C (DWIN decimal point format: send x10)
    temperature = random.randint(20, 40)
    # Random Humidity: 30% to 90%
    humidity = random.randint(30, 90)

    dwin_write_u16(VP_TEMPERATURE, temperature * 10)
    dwin_write_u16(VP_HUMIDITY, humidity * 10)

    print(f"[SIMULATED] Temp: {temperature} °C | Humidity: {humidity} %")


def update_ultrasonic():
    # Random Distance: 5 cm to 350 cm
    distance = random.randint(5, 350)
    dwin_write_u16(VP_ULTRASONIC, distance)
    print(f"[SIMULATED] Ultrasonic: {distance} cm")


def update_light():
    # Random Lux: 0 to 1000 lux
    light_lux = random.randint(0, 1000)
    dwin_write_u16(VP_LIGHT, light_lux)
    print(f"[SIMULATED] Light: {light_lux} lux")


def update_gas():
    # Random Gas Concentration: 50 to 1500 ppm
    gas_ppm = random.randint(50, 1500)
    dwin_write_u16(VP_GAS, gas_ppm)
    print(f"[SIMULATED] Gas: {gas_ppm} ppm")


def update_water_level():
    # Random Water Level: 0% to 100%
    water_percent = random.randint(0, 100)
    dwin_write_u16(VP_WATER_LEVEL, water_percent)
    print(f"[SIMULATED] Water Level: {water_percent} %")


def update_ir():
    # Random status: DETECTED / NOT DETECTED
    status = random.choice(["DETECTED", "NOT DETECTED"])
    dwin_write_text(VP_IR_SENSOR, status, 15)
    print(f"[SIMULATED] IR Sensor: {status}")


def update_pir():
    # Random status: MOTION / NO MOTION
    status = random.choice(["MOTION", "NO MOTION"])
    dwin_write_text(VP_PIR_MOTION, status, 15)
    print(f"[SIMULATED] PIR Motion: {status}")


def check_dwin_input():
    """Reads input data from DWIN VP 0x1300 over Bit-Bang UART."""
    val = dwin_read_vp(VP_READ_DEMO)
    if val is not None:
        print(f"Received from DWIN (VP {hex(VP_READ_DEMO)}): {val}")


# ============================================================
# MAIN INITIALIZATION & LOOP
# ============================================================

print("=============================================")
print("STM32 -> DWIN SIMULATED SENSOR DATA (USART3, PD8/PD9)")
print("=============================================")

start_time = time.ticks_ms()

last_dht_time = time.ticks_add(start_time, -DHT_INTERVAL_MS)
last_ultrasonic_time = time.ticks_add(start_time, -ULTRASONIC_INTERVAL_MS)
last_light_time = time.ticks_add(start_time, -LIGHT_INTERVAL_MS)
last_gas_time = time.ticks_add(start_time, -GAS_INTERVAL_MS)
last_water_time = time.ticks_add(start_time, -WATER_INTERVAL_MS)
last_ir_time = time.ticks_add(start_time, -IR_INTERVAL_MS)
last_pir_time = time.ticks_add(start_time, -PIR_INTERVAL_MS)
last_dwin_read_time = time.ticks_add(start_time, -DWIN_READ_INTERVAL_MS)


try:
    while True:
        current_time = time.ticks_ms()

        # Simulated DHT11
        if (
            time.ticks_diff(current_time, last_dht_time)
            >= DHT_INTERVAL_MS
        ):
            last_dht_time = current_time
            update_temperature_humidity()

        # Simulated Ultrasonic
        if (
            time.ticks_diff(current_time, last_ultrasonic_time)
            >= ULTRASONIC_INTERVAL_MS
        ):
            last_ultrasonic_time = current_time
            update_ultrasonic()

        # Simulated Light Sensor
        if (
            time.ticks_diff(current_time, last_light_time)
            >= LIGHT_INTERVAL_MS
        ):
            last_light_time = current_time
            update_light()

        # Simulated Gas Sensor
        if (
            time.ticks_diff(current_time, last_gas_time)
            >= GAS_INTERVAL_MS
        ):
            last_gas_time = current_time
            update_gas()

        # Simulated Water Level Sensor
        if (
            time.ticks_diff(current_time, last_water_time)
            >= WATER_INTERVAL_MS
        ):
            last_water_time = current_time
            update_water_level()

        # Simulated IR Sensor
        if (
            time.ticks_diff(current_time, last_ir_time)
            >= IR_INTERVAL_MS
        ):
            last_ir_time = current_time
            update_ir()

        # Simulated PIR Sensor
        if (
            time.ticks_diff(current_time, last_pir_time)
            >= PIR_INTERVAL_MS
        ):
            last_pir_time = current_time
            update_pir()

        # Read Data from DWIN
        if (
            time.ticks_diff(current_time, last_dwin_read_time)
            >= DWIN_READ_INTERVAL_MS
        ):
            last_dwin_read_time = current_time
            check_dwin_input()

        time.sleep_ms(10)

except KeyboardInterrupt:
    print("Simulated program stopped.")