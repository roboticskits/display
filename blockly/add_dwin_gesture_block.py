"""One-time patch: DWIN Screen block "show live gesture data from UART <n> on
DWIN screen" -> await async_dwin_gesture_live(<n>) (board dwin_screen.py /
lib_dwin_section.py). It opens AI PROJECTS > GESTURE CLASSIFICATION (page 55)
and keeps writing the camera's results there until the program is stopped.
Keeps CRLF; every anchor must match exactly once; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
BACKUP = os.path.join(HERE, "backups", "before_gesture_live", "index.html")

BLOCK = r"""      if (window.DwinVideo) window.DwinVideo.registerBlocks();
      (function () {
        Blockly.Blocks['dwin_gesture_live'] = {
          init: function () {
            this.appendDummyInput()
              .appendField('📡 show live gesture data from UART')
              .appendField(new Blockly.FieldNumber(7, 1, 8, 1), 'UART')
              .appendField('on DWIN screen');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour('#5b3fd6');
            this.setTooltip('Opens AI PROJECTS > GESTURE CLASSIFICATION on the DWIN screen and shows the camera\'s ' +
              'results arriving on this UART (115200 baud, lines like "Detected: four (100.0%)") live: gesture, ' +
              'confidence and the last line. Keeps running until the program is stopped.');
          }
        };
        const py = Blockly.Python;
        const reg = py.forBlock || py;
        reg['dwin_gesture_live'] = b => 'await async_dwin_gesture_live(' + (Number(b.getFieldValue('UART')) || 7) + ')\n';
      })();
"""

EDITS = [
    ("      if (window.DwinVideo) window.DwinVideo.registerBlocks();\n", BLOCK),
    ("            { kind: 'block', type: 'dwin_video_stop' },\n",
     "            { kind: 'block', type: 'dwin_video_stop' },\n"
     "            { kind: 'label', text: 'Live data' },\n"
     "            { kind: 'block', type: 'dwin_gesture_live' },\n"),
]

src = open(HTML, "rb").read().decode("utf-8")
if "dwin_gesture_live" in src:
    raise SystemExit("index.html already has the gesture live block")
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
