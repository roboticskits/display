"""One-time patch: DWIN Screen block "play animation [click picture] on DWIN
screen" (dwin_anim_src.js) -> await async_dwin_anim(...) (board lib section).
Inserts the code after DwinVideo.registerBlocks() and the block into the
toolbox after "stop video". Keeps CRLF; every anchor must match exactly once;
backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
BACKUP = os.path.join(HERE, "backups", "before_anim", "index.html")
ANIM = open(os.path.join(HERE, "dwin_anim_src.js"), encoding="utf-8").read()

EDITS = [
    ("      if (window.DwinVideo) window.DwinVideo.registerBlocks();\n",
     "      if (window.DwinVideo) window.DwinVideo.registerBlocks();\n" + ANIM.rstrip("\n") + "\n"),
    ("            { kind: 'block', type: 'dwin_video_stop' },\n",
     "            { kind: 'block', type: 'dwin_video_stop' },\n"
     "            { kind: 'block', type: 'dwin_anim_play' },\n"),
]

src = open(HTML, "rb").read().decode("utf-8")
if "dwin_anim_play" in src:
    raise SystemExit("index.html already has the animation block")
for old, new in EDITS:
    a, b = old.replace("\n", "\r\n"), new.replace("\r\n", "\n").replace("\n", "\r\n")
    n = src.count(a)
    if n != 1:
        raise SystemExit("anchor found %d times:\n%s" % (n, old[:120]))
    src = src.replace(a, b)
os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(HTML, BACKUP)
open(HTML, "wb").write(src.encode("utf-8"))
print("index.html patched (%d edits), backup at %s" % (len(EDITS), BACKUP))
