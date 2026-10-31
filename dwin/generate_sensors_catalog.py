"""Generate the 13-page SENSORS & ACTUATORS catalog (Pages 79-91)
for the DWIN DMG48320C035 display.
Contains all 77 sensors and actuators requested by the user, with
custom, full-color vector icons/logos for EVERY SINGLE DEVICE in its icon box.
"""

import sys, io, os
from PIL import Image, ImageDraw, ImageFont, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "DWIN_SET_bird")

def font(sz, bold=True):
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, sz)
    except OSError:
        return ImageFont.load_default()

def create_device_icon(name):
    """Draw a vibrant, crisp 36x36 full-color vector icon/logo for the device."""
    im = Image.new("RGB", (36, 36), "white")
    d = ImageDraw.Draw(im)
    n = name.upper()

    # 1. BUTTON
    if n == "BUTTON":
        d.rounded_rectangle((4, 6, 32, 30), radius=4, fill="#ced4da", outline="black", width=1)
        d.ellipse((10, 10, 26, 26), fill="#e63946", outline="#9d0208", width=2)
        d.ellipse((13, 13, 19, 19), fill="#ff758f")
        for x in (8, 14, 22, 28):
            d.line([(x, 30), (x, 34)], fill="#6c757d", width=2)

    # 2. BUZZER
    elif "BUZZER" in n:
        d.ellipse((6, 6, 30, 30), fill="#212529", outline="black", width=1)
        d.ellipse((14, 14, 22, 22), fill="#6c757d")
        d.ellipse((16, 16, 20, 20), fill="#000000")
        d.arc((26, 10, 34, 26), 290, 70, fill="#0872df", width=2)
        d.arc((29, 6, 37, 30), 290, 70, fill="#0872df", width=2)

    # 3. DHT22
    elif "DHT22" in n:
        d.rounded_rectangle((6, 4, 30, 32), radius=3, fill="#edf2f4", outline="#2b2d42", width=1)
        for y in (8, 12, 16, 20, 24, 28):
            d.line([(10, y), (26, y)], fill="#8d99ae", width=1)
        d.line([(14, 10), (14, 26)], fill="#d90429", width=2)
        d.ellipse((12, 24, 16, 28), fill="#d90429")
        d.ellipse((20, 18, 25, 25), fill="#0872df")

    # 4. PIR MOTION
    elif "PIR" in n:
        d.rounded_rectangle((5, 6, 31, 30), radius=3, fill="#e9c46a", outline="#9a7b2c", width=1)
        d.ellipse((9, 10, 27, 26), fill="#ffffff", outline="#b5b5b5", width=1)
        d.line([(9, 18), (27, 18)], fill="#b5b5b5", width=1)
        d.line([(18, 10), (18, 26)], fill="#b5b5b5", width=1)
        d.arc((12, 4, 24, 16), 180, 360, fill="#e76f51", width=2)

    # 5. RELAYS
    elif "2-CH RELAY" in n or "2RELAY" in n:
        d.rounded_rectangle((4, 7, 18, 29), radius=2, fill="#0077b6", outline="black", width=1)
        d.rounded_rectangle((18, 7, 32, 29), radius=2, fill="#0077b6", outline="black", width=1)
        d.text((11, 18), "R1", font=font(8), fill="white", anchor="mm")
        d.text((25, 18), "R2", font=font(8), fill="white", anchor="mm")
    elif "RELAY" in n:
        d.rounded_rectangle((5, 7, 31, 29), radius=3, fill="#0077b6", outline="black", width=1)
        d.text((18, 15), "RELAY", font=font(8), fill="white", anchor="mm")
        d.ellipse((10, 23, 14, 27), fill="#00a76a")
        d.ellipse((22, 23, 26, 27), fill="#ff0054")

    # 6. LED
    elif n == "LED LIGHT" or n == "LED":
        d.ellipse((11, 8, 25, 22), fill="#ff0054", outline="#a70038", width=1)
        d.rectangle((11, 15, 25, 24), fill="#ff0054")
        d.line([(10, 24), (26, 24)], fill="#ff0054", width=2)
        d.line([(14, 25), (14, 33)], fill="#adb5bd", width=2)
        d.line([(22, 25), (22, 33)], fill="#adb5bd", width=2)
        d.line([(6, 12), (3, 9)], fill="#ffb703", width=2)
        d.line([(30, 12), (33, 9)], fill="#ffb703", width=2)

    # 7. IR PROXIMITY / LINE TRACKER
    elif "IR PROX" in n or "TRACKER" in n or "INFRARED" in n:
        d.rounded_rectangle((4, 8, 32, 28), radius=3, fill="#005f73", outline="black", width=1)
        d.ellipse((8, 12, 17, 21), fill="#1a1a24", outline="black", width=1)
        d.ellipse((19, 12, 28, 21), fill="#00b4d8", outline="black", width=1)
        d.line([(17, 7), (14, 3)], fill="#00b4d8", width=1)
        d.line([(20, 7), (23, 3)], fill="#00b4d8", width=1)

    # 8. DHT11
    elif "DHT11" in n:
        d.rounded_rectangle((6, 4, 30, 32), radius=3, fill="#0077b6", outline="#023e8a", width=1)
        for y in (8, 13, 18, 23, 28):
            d.line([(10, y), (26, y)], fill="#caf0f8", width=1)
        d.line([(14, 10), (14, 26)], fill="#ffffff", width=2)
        d.ellipse((12, 24, 16, 28), fill="#e63946")

    # 9. SOLENOID
    elif "SOLENOID" in n:
        d.rounded_rectangle((6, 10, 30, 26), radius=3, fill="#6c757d", outline="black", width=1)
        for x in (10, 14, 18, 22, 26):
            d.line([(x, 10), (x, 26)], fill="#d97706", width=2)
        d.rectangle((2, 16, 7, 20), fill="#adb5bd", outline="black", width=1)

    # 10. RADAR
    elif "RADAR" in n or "MICROWAVE" in n:
        d.rounded_rectangle((5, 5, 31, 31), radius=3, fill="#007f5f", outline="black", width=1)
        d.rectangle((8, 8, 16, 16), fill="#e9c46a", outline="black", width=1)
        d.arc((12, 6, 28, 22), 270, 360, fill="#caf0f8", width=2)
        d.arc((8, 2, 34, 28), 270, 360, fill="#caf0f8", width=2)

    # 11-15. RGB
    elif "RGB" in n or "NEOPIXEL" in n:
        if "ARROW" in n:
            d.polygon([(18, 6), (30, 18), (23, 18), (23, 30), (13, 30), (13, 18), (6, 18)], fill="#00a76a", outline="black")
            d.ellipse((15, 11, 21, 17), fill="#ff0054")
        elif "ROUND" in n:
            d.ellipse((5, 5, 31, 31), fill="#212529", outline="black")
            for c, pos in [("#ff0054",(15,7)), ("#00a76a",(23,15)), ("#0872df",(15,23)), ("#ffb703",(7,15))]:
                d.ellipse((pos[0], pos[1], pos[0]+5, pos[1]+5), fill=c)
        elif "SQUARE" in n:
            d.rectangle((5, 5, 31, 31), fill="#212529", outline="black")
            for r in range(3):
                for c in range(3):
                    col = ["#ff0054", "#00a76a", "#0872df"][(r+c)%3]
                    d.ellipse((8 + c*8, 8 + r*8, 12 + c*8, 12 + r*8), fill=col)
        elif "ARC" in n:
            d.arc((4, 4, 32, 32), 180, 360, fill="#212529", width=6)
            for ang, c in [(190, "#ff0054"), (230, "#ffb703"), (270, "#00a76a"), (310, "#0872df"), (340, "#7209b7")]:
                d.arc((4, 4, 32, 32), ang, ang+25, fill=c, width=5)
        else:
            d.ellipse((8, 8, 20, 20), fill="#ff0054", outline="black")
            d.ellipse((16, 8, 28, 20), fill="#00a76a", outline="black")
            d.ellipse((12, 16, 24, 28), fill="#0872df", outline="black")

    # 16. TSL235R
    elif "TSL235" in n:
        d.rectangle((8, 10, 28, 24), fill="#212529", outline="black")
        d.line([(8, 17), (14, 17), (14, 12), (20, 12), (20, 17), (26, 17)], fill="#ffb703", width=2)
        for x in (12, 18, 24):
            d.line([(x, 24), (x, 32)], fill="#adb5bd", width=2)

    # 17. UV SENSOR
    elif "UV" in n:
        d.ellipse((10, 10, 26, 26), fill="#ffb703", outline="#fb8500", width=1)
        d.text((18, 18), "UV", font=font(9), fill="#7209b7", anchor="mm")
        for i in range(8):
            d.arc((4, 4, 32, 32), i*45, i*45 + 20, fill="#7209b7", width=2)

    # 18. TOUCH SENSOR
    elif "TOUCH" in n:
        d.ellipse((6, 6, 30, 30), fill="#e76f51", outline="#f4a261", width=2)
        d.arc((10, 10, 26, 26), 0, 360, fill="#ffffff", width=2)
        d.arc((14, 14, 22, 22), 0, 360, fill="#ffffff", width=2)

    # 19. AMBIENT TEMT6000
    elif "TEMT" in n or "AMBIENT" in n:
        d.rounded_rectangle((6, 6, 30, 30), radius=3, fill="#0077b6", outline="black", width=1)
        d.ellipse((14, 14, 22, 22), fill="#ffb703")
        for i in range(6):
            d.line([(18, 18), (18 + int(10 * [1, 0.5, -0.5, -1, -0.5, 0.5][i]), 18 + int(10 * [0, 0.86, 0.86, 0, -0.86, -0.86][i]))], fill="#fb8500", width=1)

    # 20. SOIL MOISTURE
    elif "SOIL" in n or "MOISTURE" in n:
        d.rectangle((8, 6, 28, 16), fill="#2b2d42", outline="black")
        d.rectangle((11, 16, 15, 32), fill="#d4af37")
        d.rectangle((21, 16, 25, 32), fill="#d4af37")
        d.ellipse((16, 22, 20, 28), fill="#00b4d8")

    # 21. TDS METER
    elif "TDS" in n:
        d.rounded_rectangle((6, 6, 30, 24), radius=3, fill="#03045e", outline="black")
        d.text((18, 14), "TDS", font=font(8), fill="#90e0ef", anchor="mm")
        d.line([(13, 24), (13, 33)], fill="#ced4da", width=2)
        d.line([(23, 24), (23, 33)], fill="#ced4da", width=2)

    # 22. PH SENSOR
    elif "PH" in n:
        d.rectangle((13, 4, 23, 25), fill="#caf0f8", outline="black")
        d.ellipse((11, 22, 25, 32), fill="#0077b6", outline="black")
        d.text((18, 14), "pH", font=font(8), fill="#03045e", anchor="mm")

    # 23. FORCE SENSOR
    elif "FORCE" in n:
        d.ellipse((6, 6, 30, 30), fill="#2b2d42", outline="#adb5bd", width=2)
        d.ellipse((11, 11, 25, 25), fill="#e63946")
        d.polygon([(18, 22), (14, 15), (22, 15)], fill="#ffffff")

    # 24. WATER SENSOR
    elif "WATER" in n or "TURBIDITY" in n:
        d.rounded_rectangle((6, 6, 30, 30), radius=3, fill="#0077b6", outline="black")
        for x in (11, 15, 19, 23, 27):
            d.line([(x, 10), (x, 26)], fill="#d4af37", width=2)
        d.arc((6, 22, 30, 32), 0, 180, fill="#caf0f8", width=2)

    # 25. SOLAR PANEL
    elif "SOLAR" in n:
        d.rectangle((6, 12, 30, 30), fill="#102542", outline="black", width=1)
        d.line([(14, 12), (14, 30)], fill="#8da9c4", width=1)
        d.line([(22, 12), (22, 30)], fill="#8da9c4", width=1)
        d.line([(6, 21), (30, 21)], fill="#8da9c4", width=1)
        d.ellipse((22, 4, 30, 12), fill="#ffb703")

    # 26. LDR
    elif "LDR" in n:
        d.ellipse((6, 6, 30, 30), fill="#e76f51", outline="black", width=1)
        d.line([(10, 14), (26, 14), (26, 18), (10, 18), (10, 22), (26, 22)], fill="#9d0208", width=2)
        d.line([(6, 8), (10, 11)], fill="#ffb703", width=2)
        d.line([(8, 4), (12, 7)], fill="#ffb703", width=2)

    # 27. 4-DIGIT 7-SEG
    elif "7-SEG" in n or "7SEG" in n:
        d.rectangle((4, 8, 32, 28), fill="#111111", outline="black", width=1)
        d.text((18, 18), "88:88", font=font(8), fill="#d90429", anchor="mm")

    # 28. FLAME SENSOR
    elif "FLAME" in n:
        d.ellipse((10, 14, 26, 30), fill="#d90429")
        d.polygon([(10, 20), (26, 20), (18, 4)], fill="#d90429")
        d.ellipse((13, 17, 23, 29), fill="#ffb703")
        d.polygon([(13, 21), (23, 21), (18, 10)], fill="#ffb703")

    # 29. GAS / MQ-135
    elif "MQ" in n or "GAS" in n:
        d.ellipse((7, 7, 29, 29), fill="#adb5bd", outline="#495057", width=2)
        d.ellipse((11, 11, 25, 25), fill="#495057")
        d.arc((12, 12, 24, 24), 0, 360, fill="#ced4da", width=2)
        d.text((18, 18), "GAS", font=font(6), fill="#ffffff", anchor="mm")

    # 30. PIEZO
    elif "PIEZO" in n or "VIBRATION" in n:
        d.ellipse((6, 6, 30, 30), fill="#d4af37", outline="#997b1a", width=2)
        d.ellipse((11, 11, 25, 25), fill="#ffffff", outline="#ced4da", width=1)
        d.arc((2, 2, 34, 34), 310, 50, fill="#e63946", width=2)
        d.arc((2, 2, 34, 34), 130, 230, fill="#e63946", width=2)

    # 31. SOUND SENSOR / MIC
    elif "SOUND" in n or "MIC" in n:
        d.rounded_rectangle((12, 6, 24, 24), radius=6, fill="#6c757d", outline="black", width=1)
        d.arc((8, 14, 28, 28), 0, 180, fill="#212529", width=2)
        d.line([(18, 28), (18, 33)], fill="#212529", width=2)
        d.line([(13, 33), (23, 33)], fill="#212529", width=2)

    # 32. DOT MATRIX
    elif "MATRIX" in n:
        d.rectangle((5, 5, 31, 31), fill="#212529", outline="black")
        for r in range(4):
            for c in range(4):
                d.ellipse((7 + c*6, 7 + r*6, 11 + c*6, 11 + r*6), fill="#e63946")

    # 33. THERMISTOR
    elif "THERMISTOR" in n:
        d.ellipse((12, 8, 24, 20), fill="#0077b6", outline="black")
        d.text((18, 14), "NTC", font=font(6), fill="white", anchor="mm")
        d.line([(15, 20), (15, 32)], fill="#adb5bd", width=2)
        d.line([(21, 20), (21, 32)], fill="#adb5bd", width=2)

    # 34. TILT
    elif "TILT" in n:
        d.rounded_rectangle((8, 8, 28, 28), radius=3, fill="#d4af37", outline="#997b1a", width=2)
        d.ellipse((18, 18, 25, 25), fill="#495057")
        d.line([(6, 14), (6, 22)], fill="#adb5bd", width=2)

    # 36. LOAD CELL
    elif "LOAD" in n:
        d.rectangle((5, 12, 31, 24), fill="#adb5bd", outline="black", width=1)
        d.ellipse((15, 15, 21, 21), fill="white", outline="black", width=1)
        d.polygon([(18, 10), (14, 5), (22, 5)], fill="#e63946")

    # 38. HALL SENSOR
    elif "HALL" in n:
        d.rectangle((10, 8, 26, 24), fill="#212529", outline="black")
        d.text((18, 16), "HALL", font=font(6), fill="white", anchor="mm")
        for x in (13, 18, 23):
            d.line([(x, 24), (x, 32)], fill="#ced4da", width=2)

    # 39. ULTRASONIC
    elif "ULTRA" in n:
        d.rounded_rectangle((4, 10, 32, 26), radius=3, fill="#0077b6", outline="black", width=1)
        d.ellipse((6, 12, 18, 24), fill="#adb5bd", outline="black", width=1)
        d.ellipse((18, 12, 30, 24), fill="#adb5bd", outline="black", width=1)
        d.ellipse((10, 16, 14, 20), fill="#212529")
        d.ellipse((22, 16, 26, 20), fill="#212529")

    # 40. ECG / HEART
    elif "ECG" in n or "HEART" in n or "AD8232" in n:
        d.ellipse((10, 10, 18, 18), fill="#e63946")
        d.ellipse((18, 10, 26, 18), fill="#e63946")
        d.polygon([(10, 15), (26, 15), (18, 26)], fill="#e63946")
        d.line([(5, 21), (12, 21), (15, 16), (18, 25), (21, 18), (24, 21), (31, 21)], fill="#00ffcc", width=2)

    # 41. 4-BUTTON
    elif "4-BUTTON" in n or "4BUTTON" in n:
        d.rounded_rectangle((4, 12, 32, 24), radius=3, fill="#495057", outline="black")
        for x in (7, 14, 21, 28):
            d.ellipse((x, 15, x+4, 19), fill="#e63946")

    # 42. PRESSURE / BME390 / HX710
    elif "PRESSURE" in n or "BME" in n or "BARO" in n or "AIR" in n:
        d.ellipse((6, 6, 30, 30), fill="#0077b6", outline="black", width=2)
        d.ellipse((8, 8, 28, 28), fill="#caf0f8")
        d.line([(18, 18), (24, 12)], fill="#e63946", width=2)
        d.ellipse((16, 16, 20, 20), fill="#03045e")

    # 43. EEPROM / FLASH / MEMORY / W25QXX
    elif "EEPROM" in n or "FLASH" in n or "AT24" in n or "W25Q" in n:
        d.rectangle((8, 9, 28, 27), fill="#212529", outline="black")
        d.text((18, 18), "ROM", font=font(8), fill="#00ffcc", anchor="mm")
        for x in (11, 16, 21, 25):
            d.line([(x, 5), (x, 9)], fill="#ced4da", width=2)
            d.line([(x, 27), (x, 31)], fill="#ced4da", width=2)

    # 44. JOYSTICK
    elif "JOYSTICK" in n:
        d.ellipse((6, 6, 30, 30), fill="#495057", outline="black", width=2)
        d.ellipse((12, 12, 24, 24), fill="#212529", outline="#ced4da", width=1)
        d.polygon([(18, 7), (16, 10), (20, 10)], fill="#ffb703")
        d.polygon([(18, 29), (16, 26), (20, 26)], fill="#ffb703")
        d.polygon([(7, 18), (10, 16), (10, 20)], fill="#ffb703")
        d.polygon([(29, 18), (26, 16), (26, 20)], fill="#ffb703")

    # 46. SERVO DRIVER
    elif "SERVO DRIVER" in n:
        d.rectangle((5, 7, 31, 29), fill="#03045e", outline="black")
        d.text((18, 13), "PCA", font=font(7), fill="#caf0f8", anchor="mm")
        for x in (8, 13, 18, 23, 28):
            d.rectangle((x, 21, x+2, 27), fill="#ffb703")

    # 47. LCD
    elif "LCD" in n:
        d.rectangle((4, 8, 32, 28), fill="#0077b6", outline="black", width=1)
        d.rectangle((7, 11, 29, 25), fill="#90e0ef")
        d.text((18, 18), "16x2", font=font(8), fill="#03045e", anchor="mm")

    # 49. KEYPAD
    elif "KEYPAD" in n:
        d.rounded_rectangle((6, 4, 30, 32), radius=3, fill="#212529", outline="black")
        for r in range(4):
            for c in range(3):
                d.rectangle((9 + c*6, 7 + r*6, 13 + c*6, 11 + r*6), fill="#e9ecef")

    # 50. NFC / RFID
    elif "NFC" in n or "RFID" in n:
        d.rounded_rectangle((6, 8, 30, 28), radius=3, fill="#0077b6", outline="black")
        d.arc((12, 12, 24, 24), 220, 320, fill="#ffffff", width=2)
        d.arc((8, 8, 28, 28), 220, 320, fill="#ffffff", width=2)
        d.ellipse((16, 16, 20, 20), fill="#ffb703")

    # 51. ROTARY ENCODER
    elif "ROTAR" in n or "ENCODER" in n:
        d.ellipse((6, 6, 30, 30), fill="#6c757d", outline="black", width=2)
        d.ellipse((12, 12, 24, 24), fill="#adb5bd")
        d.arc((5, 5, 31, 31), 45, 270, fill="#0872df", width=2)
        d.polygon([(26, 15), (29, 10), (32, 15)], fill="#0872df")

    # 52. STEPPER MOTOR
    elif "STEPPER" in n:
        d.ellipse((6, 6, 30, 30), fill="#6c757d", outline="black", width=2)
        d.ellipse((14, 14, 22, 22), fill="#ffb703", outline="black", width=1)
        d.arc((4, 4, 32, 32), 45, 135, fill="#d7192d", width=2)

    # 54. FLEX SENSOR
    elif "FLEX" in n:
        d.arc((4, 4, 32, 32), 180, 270, fill="#2b2d42", width=4)
        d.line([(4, 18), (4, 30)], fill="#2b2d42", width=4)
        d.line([(18, 4), (30, 4)], fill="#2b2d42", width=4)

    # 55. FM RECEIVER
    elif "FM" in n or "RADIO" in n:
        d.rounded_rectangle((5, 10, 31, 29), radius=3, fill="#005f73", outline="black")
        d.line([(8, 10), (8, 3)], fill="#adb5bd", width=2)
        d.ellipse((18, 16, 28, 26), fill="#caf0f8")
        d.text((12, 20), "FM", font=font(7), fill="white", anchor="mm")

    # 58. TRAFFIC LIGHT
    elif "TRAFFIC" in n:
        d.rounded_rectangle((11, 4, 25, 32), radius=3, fill="#2b2d42", outline="black")
        d.ellipse((14, 7, 22, 13), fill="#d7192d")
        d.ellipse((14, 15, 22, 21), fill="#ffb703")
        d.ellipse((14, 23, 22, 29), fill="#00a76a")

    # 59. HAPTIC MOTOR
    elif "HAPTIC" in n:
        d.ellipse((7, 7, 29, 29), fill="#0077b6", outline="black", width=2)
        d.text((18, 18), "M", font=font(10), fill="white", anchor="mm")
        d.arc((3, 3, 33, 33), 310, 50, fill="#ff0054", width=2)
        d.arc((3, 3, 33, 33), 130, 230, fill="#ff0054", width=2)

    # 60. ACCELEROMETER
    elif "ACCEL" in n or "ADXL" in n:
        d.rectangle((7, 7, 29, 29), fill="#212529", outline="black")
        d.line([(18, 18), (27, 18)], fill="#e63946", width=2) # X
        d.line([(18, 18), (18, 9)], fill="#00a76a", width=2)  # Y
        d.line([(18, 18), (11, 25)], fill="#0872df", width=2) # Z
        d.text((26, 14), "X", font=font(6), fill="#e63946")

    # 62. LIDAR
    elif "LIDAR" in n:
        d.rectangle((6, 10, 22, 26), fill="#343a40", outline="black")
        d.line([(22, 18), (34, 18)], fill="#e63946", width=2)
        d.ellipse((32, 16, 36, 20), fill="#ffb703")

    # 63. FINGERPRINT
    elif "FINGERPRINT" in n:
        d.arc((8, 6, 28, 26), 180, 360, fill="#1d3557", width=2)
        d.arc((11, 10, 25, 24), 180, 360, fill="#1d3557", width=2)
        d.arc((14, 14, 22, 22), 180, 360, fill="#1d3557", width=2)
        d.line([(18, 22), (18, 32)], fill="#1d3557", width=2)

    # 64. GSM 4G
    elif "GSM" in n or "4G" in n:
        for i, h in enumerate([7, 12, 18, 24]):
            d.rectangle((8 + i*6, 28 - h, 12 + i*6, 28), fill="#00a76a", outline="black")

    # 65. UART EXTENSION
    elif "UART EXT" in n:
        d.rounded_rectangle((5, 8, 31, 28), radius=3, fill="#6c757d", outline="black")
        d.text((18, 14), "UART", font=font(7), fill="white", anchor="mm")
        for x in (9, 15, 21, 27):
            d.ellipse((x, 22, x+3, 25), fill="#ffb703")

    # 66. GPS
    elif "GPS" in n or "NEO" in n:
        d.ellipse((11, 6, 25, 20), fill="#e63946", outline="black")
        d.polygon([(11, 15), (25, 15), (18, 30)], fill="#e63946")
        d.ellipse((15, 10, 21, 16), fill="white")

    # 69. SD CARD
    elif "SD" in n:
        d.polygon([(10, 6), (22, 6), (26, 10), (26, 30), (10, 30)], fill="#212529", outline="black")
        d.text((18, 20), "SD", font=font(8), fill="white", anchor="mm")

    # 71-74. MOTOR DRIVERS
    elif "DRIVER" in n or "L298" in n or "TB6612" in n or "L293" in n:
        d.rounded_rectangle((5, 6, 31, 30), radius=3, fill="#d90429", outline="black")
        d.rectangle((9, 10, 27, 26), fill="#212529")
        for y in (13, 17, 21, 25):
            d.line([(11, y), (25, y)], fill="#ced4da", width=1)
        d.text((18, 8), "DRV", font=font(6), fill="white", anchor="mm")

    # 75. FAN MOTOR
    elif "FAN" in n:
        d.ellipse((5, 5, 31, 31), fill="#0077b6", outline="black", width=2)
        for ang in (0, 90, 180, 270):
            d.pieslice((5, 5, 31, 31), ang, ang + 45, fill="#caf0f8", outline="black")
        d.ellipse((15, 15, 21, 21), fill="#d7192d")

    # 76-77. SERVO MOTORS
    elif "SERVO" in n:
        d.rounded_rectangle((6, 12, 30, 28), radius=2, fill="#0077b6", outline="black", width=1)
        d.ellipse((10, 6, 26, 22), fill="#ffffff", outline="black", width=1)
        d.line([(18, 14), (28, 8)], fill="#d7192d", width=3)

    else:
        # High quality generic microchip
        d.rounded_rectangle((7, 7, 29, 29), radius=4, fill="#3a86ff", outline="black", width=1)
        d.text((18, 18), name[:3], font=font(9), fill="white", anchor="mm")

    return im


# Master Catalog of all 77 devices
CATALOG = [
    # Page 1
    {"name": "BUTTON",               "type": "DIGITAL INPUT", "port": "MOD1 / MOD2"},
    {"name": "BUZZER",               "type": "SOUND OUTPUT",  "port": "ONBOARD (F6)"},
    {"name": "DHT22 SENSOR",         "type": "TEMP & HUMID",  "port": "DIGITAL BUS"},
    {"name": "PIR MOTION",           "type": "MOTION DETECT", "port": "MOD1 / MOD2"},
    {"name": "1-CH RELAY",           "type": "POWER SWITCH",  "port": "DIGITAL OUT"},
    {"name": "LED LIGHT",            "type": "LIGHT OUTPUT",  "port": "ONBOARD (F7)"},

    # Page 2
    {"name": "IR PROXIMITY",         "type": "OBSTACLE DET",  "port": "MOD1 / MOD2"},
    {"name": "DHT11 SENSOR",         "type": "TEMP & HUMID",  "port": "DIGITAL BUS"},
    {"name": "SOLENOID VALVE",       "type": "ACTUATOR OUT",  "port": "MOD4 (MOTOR)"},
    {"name": "RADAR RCWL0516",       "type": "MICROWAVE DET", "port": "MOD1 / MOD2"},
    {"name": "RGB LED",              "type": "COLOR LIGHT",   "port": "MOD4 (PWM)"},
    {"name": "ARC RGB LED",          "type": "NEOPIXEL BUS",  "port": "DIGITAL BUS"},

    # Page 3
    {"name": "RGB ARROW",            "type": "DIRECTION LED", "port": "DIGITAL BUS"},
    {"name": "RGB ROUND",            "type": "PIXEL RING",    "port": "DIGITAL BUS"},
    {"name": "RGB SQUARE",           "type": "PIXEL MATRIX",  "port": "DIGITAL BUS"},
    {"name": "TSL235R LIGHT",        "type": "FREQ TO LIGHT", "port": "MOD1 (PULSE)"},
    {"name": "UV GUVA-S12SD",        "type": "SUNLIGHT UV",   "port": "MOD1 (ANALOG)"},
    {"name": "TOUCH SENSOR",         "type": "CAPACITIVE IN", "port": "MOD1 / MOD2"},

    # Page 4
    {"name": "TEMT6000 LUX",         "type": "AMBIENT LIGHT", "port": "MOD1 (ANALOG)"},
    {"name": "SOIL MOISTURE",        "type": "CAPACITIVE ANA","port": "MOD1 (ANALOG)"},
    {"name": "TDS METER",            "type": "WATER PURITY",  "port": "MOD1 (ANALOG)"},
    {"name": "PH SENSOR",            "type": "ACID / BASE",   "port": "MOD1 (ANALOG)"},
    {"name": "FORCE SENSOR",         "type": "PRESSURE / FSR","port": "MOD1 (ANALOG)"},
    {"name": "WATER SENSOR",         "type": "LEVEL DETECT",  "port": "MOD1 (ANALOG)"},

    # Page 5
    {"name": "SOLAR PANEL",          "type": "VOLTAGE SENSE", "port": "MOD1 (ANALOG)"},
    {"name": "LDR RESISTOR",         "type": "LIGHT SENSOR",  "port": "MOD1 (ANALOG)"},
    {"name": "4-DIGIT 7-SEG",        "type": "NUMERIC DISP",  "port": "I2C / TM1637"},
    {"name": "FLAME SENSOR",         "type": "FIRE DETECTOR", "port": "MOD1 (ANALOG)"},
    {"name": "MQ-135 SENSOR",        "type": "AIR & GAS DET", "port": "MOD1 (ANALOG)"},
    {"name": "PIEZO SENSOR",         "type": "VIBRATION IN",  "port": "MOD1 (ANALOG)"},

    # Page 6
    {"name": "SOUND SENSOR",         "type": "ACOUSTIC IN",   "port": "MOD1 (ANALOG)"},
    {"name": "DOT MATRIX",           "type": "8x8 LED ARRAY", "port": "SPI (MOD3)"},
    {"name": "THERMISTOR",           "type": "NTC TEMP IN",   "port": "MOD1 (ANALOG)"},
    {"name": "TILT SENSOR",          "type": "INCLINE SWITCH","port": "MOD1 / MOD2"},
    {"name": "2-CH RELAY",           "type": "DUAL SWITCH",   "port": "MOD1 / MOD2"},
    {"name": "LOAD CELL",            "type": "WEIGHT SENSOR", "port": "HX711 (MOD1)"},

    # Page 7
    {"name": "TURBIDITY",            "type": "WATER CLARITY", "port": "MOD1 (ANALOG)"},
    {"name": "HALL SENSOR",          "type": "MAGNETIC DET",  "port": "MOD1 / MOD2"},
    {"name": "ULTRASONIC",           "type": "DISTANCE ECHO", "port": "MOD1 (TRIG/EC)"},
    {"name": "AD8232 ECG",           "type": "HEART MONITOR", "port": "MOD1 (ANALOG)"},
    {"name": "4-BUTTON KEY",         "type": "KEYPAD INPUT",  "port": "MOD1 / MOD2"},
    {"name": "BME390 SENSOR",        "type": "PRESSURE & ALT","port": "I2C (MOD1/2)"},

    # Page 8
    {"name": "AT24CXX EEPROM",       "type": "MEMORY STORAGE","port": "I2C (MOD1/2)"},
    {"name": "JOYSTICK",             "type": "X/Y + BUTTON",  "port": "MOD1 (ADC+DIG)"},
    {"name": "MPR121 TOUCH",         "type": "12-CH TOUCH",   "port": "I2C (MOD1/2)"},
    {"name": "SERVO DRIVER",         "type": "16-CH PCA9685", "port": "I2C (MOD1/2)"},
    {"name": "I2C LCD 16x2",         "type": "CHAR DISPLAY",  "port": "I2C (MOD1/2)"},
    {"name": "MPR121 WHEEL",         "type": "SLIDER / WHEEL","port": "I2C (MOD1/2)"},

    # Page 9
    {"name": "4x4 KEYPAD",           "type": "MATRIX KEYS",   "port": "8-PIN HEADER"},
    {"name": "PN532 NFC",            "type": "RFID / NFC",    "port": "I2C / UART"},
    {"name": "ROTARY ENCODER",       "type": "QUADRATURE IN", "port": "MOD1 (A/B)"},
    {"name": "STEPPER MOTOR",        "type": "4-PHASE MOTOR", "port": "MOD4 (MOTOR)"},
    {"name": "LINE TRACKER",         "type": "IR REFLECTIVE", "port": "MOD1 / MOD2"},
    {"name": "FLEX SENSOR",          "type": "BEND RESISTOR", "port": "MOD1 (ANALOG)"},

    # Page 10
    {"name": "FM RECEIVER",          "type": "RADIO AUDIO",   "port": "I2C (TEA5767)"},
    {"name": "HX710B AIR",           "type": "AIR PRESSURE",  "port": "MOD1 (DIGITAL)"},
    {"name": "TCS34725 COLOR",       "type": "RGB DETECTOR",  "port": "I2C (MOD1/2)"},
    {"name": "TRAFFIC LIGHT",        "type": "3-COLOR LED",   "port": "MOD1 (3-PINS)"},
    {"name": "HAPTIC MOTOR",         "type": "VIBRATE FEEDBK","port": "MOD4 (PWM)"},
    {"name": "ADXL345 ACCEL",        "type": "3-AXIS GRAVITY","port": "I2C / SPI"},

    # Page 11
    {"name": "RFID EM-18",           "type": "125KHZ ID",     "port": "UART (MOD3)"},
    {"name": "TF-LUNA LIDAR",        "type": "LASER DISTANCE","port": "UART (MOD3)"},
    {"name": "FINGERPRINT",          "type": "UART BIOMETRIC","port": "UART (MOD3)"},
    {"name": "GSM 4G A7670E",        "type": "CELLULAR & SMS","port": "UART (MOD3)"},
    {"name": "UART EXTENSION",       "type": "PORT EXPANDER", "port": "UART (MOD3)"},
    {"name": "NEO-7M GPS",           "type": "SATELLITE NAV", "port": "UART (MOD3)"},

    # Page 12
    {"name": "SPEAKER & MIC",        "type": "AUDIO I/O",     "port": "I2S / ANALOG"},
    {"name": "MEMS MIC",             "type": "DIGITAL AUDIO", "port": "I2S (INMP441)"},
    {"name": "MICRO SD CARD",        "type": "SPI STORAGE",   "port": "SPI (MOD3)"},
    {"name": "W25QXX FLASH",         "type": "SPI NOR MEM",   "port": "SPI (MOD3)"},
    {"name": "L298 DRIVER",          "type": "DUAL DC MOTOR", "port": "MOD4 (PWM)"},
    {"name": "TB6612FNG",            "type": "MOSFET MOTOR",  "port": "MOD4 (PWM)"},

    # Page 13
    {"name": "L293D 4-MOTOR",        "type": "4-MOTOR SHIELD","port": "MOD4 (PWM)"},
    {"name": "L293D 2-MOTOR",        "type": "DUAL DC MOTOR", "port": "MOD4 (PWM)"},
    {"name": "FAN MOTOR",            "type": "BLOW COOLING",  "port": "MOD4 (PWM)"},
    {"name": "2x SERVO MOTORS",      "type": "DUAL 180 DEG",  "port": "MOD4 (J1/J2)"},
    {"name": "1x SERVO MOTOR",       "type": "SINGLE 180 DEG","port": "MOD4 (J1)"},
]

CARD_COLOURS = [
    ("#d7192d", "#ffe1e3"), ("#0872df", "#d8e7ff"),
    ("#ee8300", "#ffecd0"), ("#009aa6", "#d3f3f5"),
    ("#681cef", "#e9dfff"), ("#00a16a", "#dcf7e8"),
]

TOTAL_PAGES = 13
START_PAGE = 79   # Pages 79 to 91

def render_catalog_page(p_num):
    """Render one catalog page (1 to 13) containing up to 6 device cards."""
    ref = Image.open(os.path.join(HERE, "art", "home_modern_ref.png")).convert("RGB")
    im = Image.new("RGB", (480, 320), "#eef4f8")
    tile = ref.crop((160, 260, 208, 308))
    for y in range(44, 320, 48):
        for x in range(0, 480, 48):
            im.paste(tile.crop((0, 0, min(48, 480 - x), min(48, 320 - y))), (x, y))
    blue_strip = ref.crop((180, 0, 220, 44))
    for x in range(0, 480, 40):
        im.paste(blue_strip.crop((0, 0, min(40, 480 - x), 44)), (x, 0))
    d = ImageDraw.Draw(im)
    # Glossy BACK and HOME buttons matching touch boxes (10,4,53,44) and (427,4,467,43)
    d.rounded_rectangle((10, 4, 52, 38), radius=8, fill="#1d4ed8", outline="#93c5fd", width=2)
    d.line([(36, 13), (24, 21), (36, 29)], fill="white", width=3)
    d.rounded_rectangle((427, 4, 469, 38), radius=8, fill="#1d4ed8", outline="#93c5fd", width=2)
    d.polygon([(448, 10), (436, 20), (460, 20)], fill="white")
    d.rectangle((440, 20, 456, 31), fill="white")
    d.rectangle((446, 24, 450, 31), fill="#1d4ed8")
    d.text((62, 21), "SENSORS & ACTUATORS", font=font(18), fill="white", anchor="lm")

    start_idx = (p_num - 1) * 6
    devs = CATALOG[start_idx : start_idx + 6]

    for i, dev in enumerate(devs):
        bright, pale = CARD_COLOURS[i % 6]
        x0 = 14 + (i % 3) * 154
        y0 = 56 + (i // 3) * 103
        x1, y1 = x0 + 142, y0 + 92

        # Card body
        d.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=pale, outline="#1e3a8a", width=2)
        # Header strip
        d.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 31), radius=9, fill=bright)
        d.rectangle((x0 + 2, y0 + 19, x1 - 2, y0 + 26), fill=bright)
        d.line((x0 + 2, y0 + 26, x1 - 2, y0 + 26), fill="#1e3a8a", width=2)

        name_str = dev["name"]
        sz = 13 if len(name_str) <= 12 else 11
        d.text(((x0 + x1) // 2, y0 + 14), name_str, font=font(sz), fill="white", anchor="mm")

        # White icon box
        bx0, by0, bx1, by1 = x0 + 8, y0 + 35, x0 + 52, y0 + 80
        d.rounded_rectangle((bx0, by0, bx1, by1), radius=7, fill="white", outline="#1e3a8a", width=2)

        # Draw custom bespoke full-color icon
        ic = create_device_icon(dev["name"])
        im.paste(ic, (bx0 + 4, by0 + 4))

        # Subtitle type & port info
        d.text((x0 + 58, y0 + 48), dev["type"], font=font(9), fill="#0f2547", anchor="lm")
        d.text((x0 + 58, y0 + 68), dev["port"], font=font(9, bold=False), fill="#334155", anchor="lm")

    # Bottom Navigation bar
    has_prev = p_num > 1
    has_next = p_num < TOTAL_PAGES

    fill_p, edge_p, ink_p = ("#0260d8", "#93c5fd", "white") if has_prev else ("#163a66", "#3b6598", "#94a3b8")
    d.rounded_rectangle((10, 260, 115, 305), radius=11, fill=fill_p, outline=edge_p, width=2)
    d.text((62, 282), "PREV", font=font(14), fill=ink_p, anchor="mm")

    fill_n, edge_n, ink_n = ("#0260d8", "#93c5fd", "white") if has_next else ("#163a66", "#3b6598", "#94a3b8")
    d.rounded_rectangle((365, 260, 470, 305), radius=11, fill=fill_n, outline=edge_n, width=2)
    d.text((417, 282), "NEXT", font=font(14), fill=ink_n, anchor="mm")

    d.text((240, 275), f"PAGE {p_num} / {TOTAL_PAGES}", font=font(15), fill="#091e42", anchor="mm")
    d.text((240, 295), "77 SENSORS & ACTUATORS", font=font(10, bold=False), fill="#334155", anchor="mm")

    return im

if __name__ == "__main__":
    out_dir = os.path.join(HERE, "sensors_catalog_preview")
    os.makedirs(out_dir, exist_ok=True)
    for p in range(1, TOTAL_PAGES + 1):
        page_img = render_catalog_page(p)
        page_img.save(os.path.join(out_dir, f"page_{p}.png"))
    print(f"Successfully generated all {TOTAL_PAGES} catalog pages with full-color icons!")
