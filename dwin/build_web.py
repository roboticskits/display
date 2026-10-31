"""Embed img_relay.py into dwin_image_web.html so the page is self-contained.

Run after changing img_relay.py:   python build_web.py
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
html_path = os.path.join(HERE, "dwin_image_web.html")
relay = open(os.path.join(HERE, "img_relay.py"), encoding="utf-8").read()
assert "</script" not in relay.lower(), "relay must not contain a closing script tag"
html = open(html_path, encoding="utf-8").read()
start_tag = '<script type="text/plain" id="relay-src">'
i = html.index(start_tag) + len(start_tag)
j = html.index("</script>", i)
html = html[:i] + relay + html[j:]
open(html_path, "w", encoding="utf-8", newline="\n").write(html)
print("embedded %d bytes of img_relay.py into %s" % (len(relay), os.path.basename(html_path)))
