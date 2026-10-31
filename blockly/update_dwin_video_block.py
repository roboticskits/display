"""One-time patch: the "play video" block gets a picture you click to choose
the video (like "show image"), and the toolbox button "Upload a video to the
DWIN screen..." goes away. Replaces the video code that add_dwin_video.py put
into index.html (old copy: backups/before_video_block/dwin_video_src.js) with
the current dwin_video_src.js. Keeps CRLF; every anchor must match exactly
once; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
BACKUP_DIR = os.path.join(HERE, "backups", "before_video_block")
OLD_VIDEO = open(os.path.join(BACKUP_DIR, "dwin_video_src.js"), encoding="utf-8").read()
NEW_VIDEO = open(os.path.join(HERE, "dwin_video_src.js"), encoding="utf-8").read()


def crlf(text):
    return text.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r\n")


EDITS = [
    (crlf(OLD_VIDEO), crlf(NEW_VIDEO)),
    ("            { kind: 'button', text: '🎬 Upload a video to the DWIN screen…', callbackKey: 'dwinUploadVideo' },\r\n",
     ""),
]

src = open(HTML, "rb").read().decode("utf-8")
if "pickVideo" in src:
    raise SystemExit("index.html already has the video block picture")
for old, new in EDITS:
    n = src.count(old)
    if n != 1:
        raise SystemExit("anchor found %d times:\n%s" % (n, old[:120]))
    src = src.replace(old, new)
backup = os.path.join(BACKUP_DIR, "index.html")
os.makedirs(BACKUP_DIR, exist_ok=True)
if not os.path.exists(backup):
    shutil.copy2(HTML, backup)
open(HTML, "wb").write(src.encode("utf-8"))
print("index.html patched (%d edits), backup at %s" % (len(EDITS), backup))
