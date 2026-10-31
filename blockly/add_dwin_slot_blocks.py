"""One-time patch: add the "save picture to DWIN memory" and "show saved
picture" blocks (lib.py: async_dwin_save / async_dwin_show_saved) to
dwin_blocks_src.js and index.html, plus the toolbox entries in index.html.
Keeps line endings; every anchor must match exactly once; backs up index.html."""
import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dwin_blocks_src.js")
HTML = os.path.join(HERE, "index.html")
BACKUP = os.path.join(HERE, "backups", "before_slot_blocks", "index.html")

BLOCK_ANCHOR = """            '(happy 15, sad 18, angry 21, surprised 24, love 27, sleepy 30, excited 33, curious 36), 39 = image page.');
        }
      };
"""
BLOCKS = """      const SLOTS = [['1', '1'], ['2', '2'], ['3', '3']];
      Blockly.Blocks['dwin_save_slot'] = {
        init: function () {
          this.appendDummyInput()
            .appendField('💾 save picture on DWIN screen to memory')
            .appendField(new Blockly.FieldDropdown(SLOTS), 'SLOT');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Saves the picture now on the DWIN image page into the screen\\'s own memory ' +
            '(1, 2 or 3). It stays there after power-off. Takes about 1.5 seconds.');
        }
      };
      Blockly.Blocks['dwin_show_slot'] = {
        init: function () {
          this.appendDummyInput()
            .appendField('📂 show saved picture')
            .appendField(new Blockly.FieldDropdown(SLOTS), 'SLOT')
            .appendField('on DWIN screen');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Shows a picture saved with "save picture to memory". It appears at once, ' +
            'because the picture is already inside the screen.');
        }
      };
"""
GEN_ANCHOR = """      reg['dwin_page'] = function (b) {
        return 'await async_dwin_page(' + (Number(b.getFieldValue('PAGE')) || 0) + ')\\n';
      };
"""
GENS = """      reg['dwin_save_slot'] = function (b) {
        return 'await async_dwin_save(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\\n';
      };
      reg['dwin_show_slot'] = function (b) {
        return 'await async_dwin_show_saved(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\\n';
      };
"""
TOOLBOX_ANCHOR = """            { kind: 'block', type: 'dwin_page' },
"""
TOOLBOX = """            { kind: 'block', type: 'dwin_save_slot' },
            { kind: 'block', type: 'dwin_show_slot' },
"""


def patch(path, edits):
    src = open(path, "rb").read().decode("utf-8")
    crlf = "\r\n" in src
    for anchor, add in edits:
        a = anchor.replace("\n", "\r\n") if crlf else anchor
        b = add.replace("\n", "\r\n") if crlf else add
        if src.count(a) != 1:
            raise SystemExit("%s: anchor found %d times:\n%s" % (os.path.basename(path), src.count(a), anchor[:120]))
        if b in src:
            raise SystemExit("%s: already patched" % os.path.basename(path))
        src = src.replace(a, a + b)
    open(path, "wb").write(src.encode("utf-8"))
    print("patched", os.path.basename(path), "CRLF" if crlf else "LF")


os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(HTML, BACKUP)
patch(SRC, [(BLOCK_ANCHOR, BLOCKS), (GEN_ANCHOR, GENS)])
patch(HTML, [(BLOCK_ANCHOR, BLOCKS), (GEN_ANCHOR, GENS), (TOOLBOX_ANCHOR, TOOLBOX)])
