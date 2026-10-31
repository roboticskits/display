# Curio STM32 + DWIN display

Source code for the Curio R4 STM32 board, DWIN display pages, ESP32-S3 Wi-Fi/Bluetooth gateway, and Blockly interface.

## Project layout

- `board_r4/`: R4 MicroPython application and display integration.
- `board_main/`: board deployment files and installer.
- `ESP32_CURIO_GATEWAY/`: ESP32-S3 Arduino gateway sketch and serial tests.
- `dwin/`: DWIN page generator, tools, font, and design assets.
- `blockly/`: browser interface and its local static dependencies.
- `dwin_media_uploader.html`: image uploader for the display.
- `DEVELOPER_NOTES.txt`: development history, hardware details, and current status.

The Wi-Fi ON/OFF implementation is documented at the top of `DEVELOPER_NOTES.txt`. The last hardware test confirmed the display controls and a running ESP32 gateway.

## Local configuration and display files

Wi-Fi credentials are entered on the display and saved by the ESP32; the published `DEFAULT_WIFI_PASS` fallback is empty. If automatic first-boot connection is needed, configure the board locally before deploying it and keep credentials out of Git.

Generated `DWIN_SET` packages, display memory images, personal media, old backups, and compiled firmware are excluded. Rebuild display files with `dwin/make_sd_card.py` using a local DWIN package or a connected display, as described in its module header and the developer notes.
