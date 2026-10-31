"""One-time patch: the "show image" block writes its picture as a tuple of
4096-character hex strings instead of one long string. A single 37 KB string
literal made `import user` fail on the board ("memory allocation failed,
allocating 37445 bytes"); short pieces need no large free block. lib.py's
_dw_plan accepts both forms. Patches dwin_blocks_src.js and index.html;
keeps line endings; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [os.path.join(HERE, "dwin_blocks_src.js"), os.path.join(HERE, "index.html")]
BACKUP = os.path.join(HERE, "backups", "before_chunked_image", "index.html")

OLD = """        py.definitions_[name] = name + " = (" + d.w + ", " + d.h + ", " + d.enc + ", '" + d.hex + "')";
"""
NEW = """        // the picture as short strings: one long literal needs one large free
        // block on the board when user.py is imported
        const parts = [];
        for (let i = 0; i < d.hex.length; i += 4096) parts.push("    '" + d.hex.slice(i, i + 4096) + "',");
        py.definitions_[name] = name + " = (" + d.w + ", " + d.h + ", " + d.enc + ", (\\n" + parts.join("\\n") + "\\n))";
"""

os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(FILES[1], BACKUP)
for path in FILES:
    src = open(path, "rb").read().decode("utf-8")
    crlf = "\r\n" in src
    old = OLD.replace("\n", "\r\n") if crlf else OLD
    new = NEW.replace("\n", "\r\n") if crlf else NEW
    if src.count(old) != 1:
        raise SystemExit("%s: expected the old line once, found %d" % (os.path.basename(path), src.count(old)))
    open(path, "wb").write(src.replace(old, new).encode("utf-8"))
    print("patched", os.path.basename(path), "CRLF" if crlf else "LF")
