"""One-time patch: add the DWIN video feature (dwin_video_src.js) to index.html:
the code after the DWIN image blocks, toolbox entries (label, upload button,
play/stop blocks), DwinVideo.registerBlocks() after defineDwinImageBlocks(),
and a hook in handleBoardMessage for the board's "DWV:" replies.
Keeps CRLF; every anchor must match exactly once; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
BACKUP = os.path.join(HERE, "backups", "before_video", "index.html")
VIDEO = open(os.path.join(HERE, "dwin_video_src.js"), encoding="utf-8").read()

EDITS = [
    ("""        return 'await async_dwin_show_saved(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\\n';
      };
    }
  </script>
""",
     """        return 'await async_dwin_show_saved(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\\n';
      };
    }

""" + VIDEO.rstrip("\n") + """
  </script>
"""),
    ("""            { kind: 'block', type: 'dwin_show_slot' },
""",
     """            { kind: 'block', type: 'dwin_show_slot' },
            { kind: 'label', text: 'Video' },
            { kind: 'button', text: '🎬 Upload a video to the DWIN screen…', callbackKey: 'dwinUploadVideo' },
            { kind: 'block', type: 'dwin_video_play' },
            { kind: 'block', type: 'dwin_video_stop' },
"""),
    ("""      defineDwinImageBlocks();
""",
     """      defineDwinImageBlocks();
      if (window.DwinVideo) window.DwinVideo.registerBlocks();
"""),
    ("""      if (!msg || msg === '-') return;   // skip legacy clear-placeholder
""",
     """      if (!msg || msg === '-') return;   // skip legacy clear-placeholder

      // DWIN video upload replies ("DWV:..."): handshakes are not shown
      if (window.DwinVideo && window.DwinVideo.onBoardLine(msg)) return;
"""),
]

src = open(HTML, "rb").read().decode("utf-8")
if "window.DwinVideo" in src:
    raise SystemExit("index.html already has the video feature")
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
