"""Make a DGUS V7.6 project of the current display build, to open in the DGUS
tool (File > Open > DWprj.hmi).

    python make_dgus_project.py          (after make_sd_card.py)

Writes DGUS_PROJECT/ in the layout DGUS V7.651 loads (read from its
DwinTerminal.dll):
  DWprj.hmi        INI: [INIT] header as DGUS wrote it for this 480x320 panel
                   + [IMG] NN=NN.bmp for every page
  DWIN_SET/        copy of DWIN_SET_sd: the page pictures (DGUS loads them
                   from here) + 13TouchFile.bin, 14ShowFile.bin, 22_Config.bin,
                   32.icl, 48_SensorIcons.icl, font, T5LCFG.CFG
  DWprj.tft        DGUS's own .NET-serialised BizDraw.Core.Document files,
  TFT/NN.bmp.tft   written with DGUS's own DocumentManager.Save by
                   dgus_tft.ps1 (blank pages). Without DWprj.tft DGUS quietly
                   does not open the project; without TFT/<picture>.tft it
                   stops reading the picture list.
  image/, ICON/    empty, as DGUS's New makes them
To get the buttons/controls into DGUS: open the project, Import the DWIN_SET
folder (its 13/14 .bin files) and Save.

The icon libraries that live only in the display (24 saved pictures, 26
profile, 49 video, animations) are not on the PC, so those icons are empty in
the DGUS preview.

NOTE: the pages are made by make_sd_card.py. Changes saved in DGUS are not
read back by it, and running this script again starts the DGUS files fresh.
Use this project to look at / check the pages, or copy a change into
make_sd_card.py.
"""
import os
import re
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "DWIN_SET_sd")
OUT = os.path.join(HERE, "DGUS_PROJECT")
HEADER = ["[INIT]", "PICFIX=1", "VARCount=64", "Version=0", "ProVersion=649",
          "SCREENDSIZE=480X320", "SPADDRESS=5000"]


def main():
    if not os.path.exists(os.path.join(SRC, "14ShowFile.bin")):
        raise SystemExit("Run make_sd_card.py first (no %s)." % SRC)
    dst = os.path.join(OUT, "DWIN_SET")
    for d in (dst, os.path.join(OUT, "image"), os.path.join(OUT, "TFT")):
        if os.path.isdir(d):
            shutil.rmtree(d)                   # our own files from the last run
    if os.path.exists(os.path.join(OUT, "DWprj.tft")):
        os.remove(os.path.join(OUT, "DWprj.tft"))
    shutil.copytree(SRC, dst)
    for d in ("image", "ICON", "TFT"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    pages = sorted((int(m.group(1)), f) for f in os.listdir(dst)
                   for m in [re.match(r"^(\d+)\.bmp$", f, re.I)] if m)
    lines = HEADER + ["[IMG]"] + ["%02d=%s" % (n, f) for n, f in pages]
    with open(os.path.join(OUT, "DWprj.hmi"), "wb") as f:
        f.write(("\r\n".join(lines) + "\r\n").encode("ascii"))
    # DGUS's own files, written by DGUS's own code (dgus_tft.ps1 loads DwinTerminal.dll)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        os.path.join(HERE, "dgus_tft.ps1"), "-Project", OUT], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    missing = [f for _, f in pages if not os.path.exists(os.path.join(OUT, "TFT", f + ".tft"))]
    if not os.path.exists(os.path.join(OUT, "DWprj.tft")) or missing:
        raise SystemExit("DGUS files not written (DWprj.tft / %d page files missing)." % len(missing))
    print("DGUS project: %s (%d pages, pictures in DWIN_SET)" % (os.path.join(OUT, "DWprj.hmi"), len(pages)))


if __name__ == "__main__":
    main()
