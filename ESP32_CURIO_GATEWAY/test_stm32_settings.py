"""End-to-end test on the STM32 board (COM88):
Uploads a small program via main.py that:
1. Switches the DWIN display to the SETTINGS page (page 56)
2. Queries live Wi-Fi & Bluetooth status from the ESP32-S3 over UART6
3. Runs a Wi-Fi network scan from the STM32 via ESP32-S3
4. Updates the DWIN Settings VPs (0x5300 Wi-Fi, 0x5320 Bluetooth, 0x5340 Firmware)
"""
import time
import serial
from serial.tools import list_ports

USER_CODE = """def start():
    import iot_bus, dwin_get_data
    dwin_page(56)
    print("ESP32 present:", iot_bus.esp_present(), "net_up:", iot_bus.net_up())
    st = dwin_settings_refresh(query=True)
    print("SETTINGS STATUS:", st)
    nets = dwin_wifi_scan()
    print("WIFI SCAN COUNT:", len(nets))
    for n in nets[:5]:
        print("  SSID:", n.get("ssid"), "RSSI:", n.get("rssi"), "OPEN:", n.get("open"))
    final_vals = dwin_get_data.refresh(force=True)
    print("DWIN DISPLAY FIELDS:", final_vals)
"""


def main():
    ports = [p.device for p in list_ports.comports() if p.vid == 0xF055]
    if not ports:
        raise SystemExit("No STM32 MicroPython port found")
    port = ports[0]
    print("Connecting to STM32 on", port)
    s = serial.Serial(port, 115200, timeout=0.3)
    time.sleep(0.5)
    if s.in_waiting:
        print(s.read(s.in_waiting).decode("utf-8", "replace"), end="")

    # Wait up to 5s for ESP32 periodic NET:/STAT: announcement if board just rebooted
    s.write(b"UPLOAD\n")
    time.sleep(0.3)
    payload = "@@START\n" + USER_CODE + "\n@@END\n"
    s.write(payload.encode("utf-8"))
    time.sleep(0.8)
    if s.in_waiting:
        print(s.read(s.in_waiting).decode("utf-8", "replace"), end="")

    s.write(b"PLAY\n")
    t0 = time.time()
    buf = ""
    while time.time() - t0 < 15.0:
        if s.in_waiting:
            chunk = s.read(s.in_waiting).decode("utf-8", "replace")
            print(chunk, end="", flush=True)
            buf += chunk
            if ">> Ready." in buf:
                break
        time.sleep(0.1)
    s.close()


if __name__ == "__main__":
    main()
