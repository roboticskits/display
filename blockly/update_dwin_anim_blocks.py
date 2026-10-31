"""One-time patch: animation memories. Replaces the animation code that
add_dwin_anim_block.py put into index.html (old copy:
backups/anim_memories_before_2026-10-23/dwin_anim_src.js) with the current
dwin_anim_src.js (adds "save animation to DWIN memory [1-3]" and "play saved
animation [1-3]") and puts both blocks into the toolbox after "play animation".
Keeps CRLF; every anchor must match exactly once; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
OLD = os.path.join(HERE, "..", "backups", "anim_memories_before_2026-10-23", "dwin_anim_src.js")
BACKUP = os.path.join(HERE, "backups", "before_anim_memories", "index.html")


def crlf(text):
    return text.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r\n")


EDITS = [
    (crlf(open(OLD, encoding="utf-8").read()), crlf(open(os.path.join(HERE, "dwin_anim_src.js"), encoding="utf-8").read())),
    ("            { kind: 'block', type: 'dwin_anim_play' },\r\n",
     "            { kind: 'block', type: 'dwin_anim_play' },\r\n"
     "            { kind: 'block', type: 'dwin_anim_save' },\r\n"
     "            { kind: 'block', type: 'dwin_anim_show' },\r\n"),
]

src = open(HTML, "rb").read().decode("utf-8")
if "dwin_anim_save" in src:
    raise SystemExit("index.html already has the animation memory blocks")
for old, new in EDITS:
    n = src.count(old)
    if n != 1:
        raise SystemExit("anchor found %d times:\n%s" % (n, old[:120]))
    src = src.replace(old, new)
os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(HTML, BACKUP)
open(HTML, "wb").write(src.encode("utf-8"))
print("index.html patched (%d edits), backup at %s" % (len(EDITS), BACKUP))
