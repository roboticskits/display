"""Test the ESP32-S3 Curio Gateway over the J2 TTL serial port (default COM89, 115200 baud).

Usage:
  python test_esp32_ttl.py                      # check status + BLE + Wi-Fi scan
  python test_esp32_ttl.py --ssid MyWiFi --pass MyPassword   # also connect to Wi-Fi
"""
import argparse
import json
import time
import serial


def send_cmd(ser, line, timeout=8.0):
    print("\n>>>", line)
    ser.reset_input_buffer()
    ser.write((line + "\n").encode("utf-8"))
    t0 = time.time()
    buf = ""
    while time.time() - t0 < timeout:
        n = ser.in_waiting
        chunk = ser.read(n if n > 0 else 1)
        if chunk:
            buf += chunk.decode("utf-8", "replace")
            if "IOTR:" in buf and "\n" in buf[buf.index("IOTR:"):]:
                time.sleep(0.15)
                if ser.in_waiting:
                    buf += ser.read(ser.in_waiting).decode("utf-8", "replace")
                break
    for ln in buf.splitlines():
        print("   ", ln)
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM89", help="TTL serial port (default COM89)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--ssid", default="", help="Optional Wi-Fi SSID to connect")
    ap.add_argument("--password", "--pass", dest="password", default="", help="Wi-Fi password")
    args = ap.parse_args()

    ser = serial.Serial()
    ser.port = args.port
    ser.baudrate = args.baud
    ser.timeout = 0.25
    ser.dtr = False
    ser.rts = False
    ser.open()

    print(f"Opened {args.port} @ {args.baud} baud")
    time.sleep(0.5)
    if ser.in_waiting:
        print(ser.read(ser.in_waiting).decode("utf-8", "replace"))

    # 1. Combined status
    send_cmd(ser, json.dumps({"id": 1, "op": "status"}).replace('{"', 'IOT:{"', 1), timeout=3.0)

    # 2. Bluetooth LE status
    send_cmd(ser, 'IOT:{"id":2,"op":"ble_status"}', timeout=3.0)

    # 3. Wi-Fi status
    send_cmd(ser, 'IOT:{"id":3,"op":"wifi_status"}', timeout=3.0)

    # 4. Wi-Fi scan (available networks)
    send_cmd(ser, 'IOT:{"id":4,"op":"wifi_scan"}', timeout=10.0)

    # 5. Optional Wi-Fi connect
    if args.ssid:
        req = {"id": 5, "op": "wifi_connect", "ssid": args.ssid, "pass": args.password, "force": True}
        send_cmd(ser, "IOT:" + json.dumps(req), timeout=20.0)
        send_cmd(ser, 'IOT:{"id":6,"op":"wifi_status"}', timeout=3.0)

    ser.close()


if __name__ == "__main__":
    main()
