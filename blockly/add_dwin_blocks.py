"""Insert the DWIN screen blocks (dwin_blocks_src.js) into index.html.

Safe to run once; it refuses to run twice. Backup of the original:
D:/Arun/display_with_stm32/backups/before_dwin_blocks/index.html
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, "index.html")
html = open(path, encoding="utf-8").read()
assert "defineDwinImageBlocks" not in html, "DWIN blocks are already in index.html"
src = open(os.path.join(HERE, "dwin_blocks_src.js"), encoding="utf-8").read()


def insert_before(text, anchor, new):
    assert text.count(anchor) == 1, "anchor not unique: %r" % anchor[:60]
    return text.replace(anchor, new + anchor)


def replace_once(text, old, new):
    assert text.count(old) == 1, "text not unique: %r" % old[:60]
    return text.replace(old, new)


# 1. block definitions + generators, as their own script before the toolbox config
html = insert_before(html, "  <script>\n    window.toolboxConfig = {",
                     "  <script>\n" + src + "  </script>\n\n")

# 2. toolbox category, placed right after Tx-Rx
category = """        // ── DWIN Screen ── image / page blocks for the DWIN display on UART1
        {
          kind: 'category', name: '🖼️ DWIN Screen', colour: '#5b3fd6', id: 'cat_dwin', contents: [
            { kind: 'block', type: 'dwin_show_image' },
            { kind: 'block', type: 'dwin_clear_image' },
            { kind: 'block', type: 'dwin_page' },
          ]
        },

"""
lines = html.split("\n")
idx = [i for i, l in enumerate(lines) if "kind: 'category'" in l and "id: 'cat_iot'," in l]
assert len(idx) == 1, "IoT category not found exactly once"
k = idx[0] - 1
assert lines[k].strip() == "{", "unexpected layout above the IoT category"
while lines[k - 1].strip().startswith("//"):   # keep the IoT comment block with it
    k -= 1
lines.insert(k, category.rstrip("\n") + "\n")
html = "\n".join(lines)

# 3. register the blocks with the others, before the workspace is created
html = replace_once(html, "      defineGenerators();\n",
                    "      defineGenerators();\n      defineDwinImageBlocks();\n")

# 4. faster USB upload for large programs (USB has flow control)
old_loop = """        for (let i = 0; i < rawData.length; i += CHUNK_SIZE) {
          const chunk = rawData.slice(i, i + CHUNK_SIZE);
          await sendData(chunk);
          await sleep(15);
        }"""
new_loop = """        // Big programs (for example with a DWIN image) over USB: the USB link
        // has flow control, so larger chunks are safe and far faster.
        const fastUsb = isUSB && rawData.length > 4096;
        const step = fastUsb ? 512 : CHUNK_SIZE;
        const gap = fastUsb ? 2 : 15;
        for (let i = 0; i < rawData.length; i += step) {
          const chunk = rawData.slice(i, i + step);
          await sendData(chunk);
          await sleep(gap);
        }"""
html = replace_once(html, old_loop, new_loop)

# the file uses Windows line endings: text mode read gave "\n", write back as "\r\n"
open(path, "w", encoding="utf-8", newline="\r\n").write(html)
print("index.html updated: %d bytes" % len(html.encode("utf-8")))
