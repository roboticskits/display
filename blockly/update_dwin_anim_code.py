"""Replace the animation code inside index.html with the current
dwin_anim_src.js. Give the copy of dwin_anim_src.js that is in index.html now
(a backup taken before editing the .js):
    python update_dwin_anim_code.py ..\\backups\\anim_5s_before_2026-10-23\\dwin_anim_src.js
Keeps CRLF; the old code must be found exactly once; backs up index.html next
to the given old copy (index.html)."""
import os, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")


def crlf(text):
    return text.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r\n")


if len(sys.argv) != 2:
    sys.exit(__doc__)
old_js = sys.argv[1]
old = crlf(open(old_js, encoding="utf-8").read())
new = crlf(open(os.path.join(HERE, "dwin_anim_src.js"), encoding="utf-8").read())
src = open(HTML, "rb").read().decode("utf-8")
n = src.count(old)
if n != 1:
    sys.exit("old animation code found %d times - nothing changed" % n)
backup = os.path.join(os.path.dirname(os.path.abspath(old_js)), "index.html")
if not os.path.exists(backup):
    shutil.copy2(HTML, backup)
open(HTML, "wb").write(src.replace(old, new).encode("utf-8"))
print("index.html updated, backup at", backup)
