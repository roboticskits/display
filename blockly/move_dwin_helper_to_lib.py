"""One-time patch: the DWIN helper Python now lives in the board's lib.py
(section "DWIN SMART DISPLAY", source board_main/lib_dwin_section.py), so the
blocks stop copying it into every user.py. user.py keeps only the picture data
and the function call, like the sensor blocks.
Patches dwin_blocks_src.js and index.html; keeps line endings; backs up index.html."""
import os, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [os.path.join(HERE, "dwin_blocks_src.js"), os.path.join(HERE, "index.html")]
BACKUP = os.path.join(HERE, "backups", "before_lib_move", "index.html")

HELPER_RE = re.compile(
    r"      // -+ board helper \(Python\)\r?\n      const HELPER = \[\r?\n.*?\r?\n      \]\.join\('\\n'\);\r?\n",
    re.S)
NOTE = ("      // ---------------------------------------------------------- board side\n"
        "      // The Python behind these blocks is in the board's lib.py (section\n"
        "      // \"DWIN SMART DISPLAY\": dwin_image / dwin_clear / dwin_page and their\n"
        "      // async_ versions). user.py only gets the picture data and the call.\n")
DEF_RE = re.compile(r"        py\.definitions_\['dwin_image_helper'\] = HELPER;\r?\n")

os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(FILES[1], BACKUP)

for path in FILES:
    src = open(path, "rb").read().decode("utf-8")
    crlf = "\r\n" in src
    n_helper = len(HELPER_RE.findall(src))
    n_defs = len(DEF_RE.findall(src))
    if n_helper != 1 or n_defs != 3:
        raise SystemExit("%s: expected 1 helper and 3 uses, found %d and %d" % (path, n_helper, n_defs))
    note = NOTE.replace("\n", "\r\n") if crlf else NOTE
    src = HELPER_RE.sub(lambda m: note, src)
    src = DEF_RE.sub("", src)
    open(path, "wb").write(src.encode("utf-8"))
    print("patched", os.path.basename(path), "CRLF" if crlf else "LF")
