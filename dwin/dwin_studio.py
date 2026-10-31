"""DWIN Page Studio - edit the DWIN display's SD-card project without code.

    python dwin_studio.py          (or double-click DWIN_Page_Studio.bat)

- Left: every page of the SD-card project. Middle: the page, with its touch
  buttons drawn on it (red = opens a page, grey = special: keyboard keys,
  brightness ...). Right: what you can change on that page.
- Buttons: change which page a button opens, remove it, or drag a new one.
- Texts: put new words on any page; a "cover box" first hides the old words.
- List page: make a new page with a title and up to 5 rows; each row opens a
  page you choose (e.g. a new list behind a home-page button).
- Deploy to SD card: pick the card (or its DWIN_SET folder); the files are
  built and copied, then checked. Saved pictures, video and animations in the
  display are not touched (pages only, like make_sd_card.py --keep-memory).
Everything you change is kept in studio_project.json; make_sd_card.py applies it.
"""
import os
import sys
import json
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_sd_card as msd                        # page drawing helpers, constants

SCALE = 1.25
BUILDER = os.path.join(HERE, "make_sd_card.py")
LAST_BUILTIN = msd.LAST_BUILTIN_PAGE             # last page the builder makes itself (93 now)
NAMES = {msd.HOME: "HOME", msd.HOME2: "HOME page 2", 39: "Image page", msd.LIST_PAGE: "PROJECTS LIST",
         msd.VIDEO_PAGE: "VIDEO", msd.STORAGE_PAGE: "STORAGE", msd.STORE_VIDEO: "STORAGE video",
         msd.AI_PAGE: "AI PROJECTS", msd.SETTINGS_PAGE: "SETTINGS", 57: "WI-FI", 58: "BLUETOOTH", 59: "FIRMWARE",
         60: "Keyboard abc", 61: "Keyboard ABC", 62: "Keyboard ?123", 63: "Keyboard abc (pressed)",
         64: "Keyboard ABC (pressed)", 65: "Keyboard ?123 (pressed)", msd.ANIM_PAGE: "ANIMATION",
         msd.ANIM_LIST_PAGE: "ANIMATIONS"}
for _i in range(10):
    NAMES[_i] = "Boot %d" % _i
for _i in range(11, 15):
    NAMES[_i] = "SENSORS LIST %d" % (_i - 10)
for _i, _m in enumerate(("happy", "sad", "angry", "surprised", "love", "sleepy", "excited", "curious")):
    for _f in range(3):
        NAMES[15 + 3 * _i + _f] = "Bird %s %d" % (_m, _f + 1)
for _i in range(3):
    NAMES[msd.FIRST_PIC + _i] = "Picture %d" % (_i + 1)
    NAMES[msd.STORE_PIC + _i] = "STORAGE picture %d" % (_i + 1)
    NAMES[msd.ANIM_SLOT_PAGES[_i]] = "ANIMATION %d" % (_i + 1)
for _i, _t in enumerate(msd.AI_TYPES):
    NAMES[msd.AI_FIRST + _i] = _t[0]
for _i, _p in enumerate(getattr(msd, "PROJECT_EXTRA_PAGES", ())):
    NAMES[_p] = "PROJECTS LIST %d" % (_i + 3)
for _i, _m in enumerate(("digital in", "analog in", "digital out", "PWM out", "servo")):
    NAMES[74 + _i] = "PORT & PIN: " + _m
for _i, _p in enumerate(getattr(msd, "CATALOG_PAGES", ())):
    NAMES[_p] = "SENSOR CATALOG %d" % (_i + 1)
if hasattr(msd, "BT_KB_PAGE"):
    NAMES[msd.BT_KB_PAGE] = "Bluetooth name keyboard"
    NAMES[msd.BT_KB_PRESSED] = "Bluetooth keyboard (pressed)"
for _a, _n in (("PROFILE_PAGE", "PROFILE"), ("GRAPH_PAGE", "SENSOR GRAPH"), ("IOT_PAGE", "IOT & KIT-TO-KIT"),
               ("HOME3", "HOME page 3"), ("CHAT_PAGE", "LLM CHAT"), ("CHAT_KB_PAGE", "LLM CHAT keyboard"),
               ("CHAT_KB_PRESSED", "LLM CHAT keyboard (pressed)")):
    if hasattr(msd, _a):
        NAMES[getattr(msd, _a)] = _n
SPECIAL = {"fe05": "key (sends a code)", "fe0b": "swipe", "fe00": "number input"}


def empty_project():
    return {"texts": [], "buttons": {"remove": [], "retarget": [], "add": []}, "list_pages": []}


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DWIN Page Studio")
        self.geometry("1300x760")
        try:
            self.state("zoomed")          # full screen on Windows
        except tk.TclError:
            pass
        self.proj = empty_project()
        try:
            with open(msd.STUDIO_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            self.proj.update(loaded)
            for k in ("remove", "retarget", "add"):
                self.proj["buttons"].setdefault(k, [])
        except (OSError, ValueError):
            pass
        self.dirty = False
        self.page = msd.HOME
        self.mode = None
        self.drag = None
        self.sel_button = None
        self.base_buttons = []
        self.log_q = queue.Queue()
        self._ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if not os.path.exists(os.path.join(msd.STUDIO_CACHE, "buttons.json")):
            self.status("First start: building the page pictures (about 30 s) ...")
            self.run_builder(None)
        else:
            self.load_cache()
        self.after(100, self.pump_log)

    # ------------------------------------------------------------------ UI
    def _ui(self):
        top = ttk.Frame(self, padding=4)
        top.pack(fill="x")
        ttk.Button(top, text="Save", command=self.save).pack(side="left")
        ttk.Button(top, text="Rebuild preview", command=lambda: self.run_builder(None)).pack(side="left", padx=4)
        ttk.Button(top, text="Deploy to SD card ...", command=self.deploy).pack(side="left", padx=4)
        ttk.Button(top, text="Help", command=self.help).pack(side="left", padx=4)
        self.status_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.status_var, foreground="#5b3fd6").pack(side="left", padx=12)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=4)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Pages").pack(anchor="w")
        self.pages_lb = tk.Listbox(left, width=26, height=40, exportselection=False)
        self.pages_lb.pack(side="left", fill="y")
        sb = ttk.Scrollbar(left, command=self.pages_lb.yview)
        sb.pack(side="left", fill="y")
        self.pages_lb.config(yscrollcommand=sb.set)
        self.pages_lb.bind("<<ListboxSelect>>", self.on_page_select)

        mid = ttk.Frame(body, padding=4)
        mid.pack(side="left", fill="both")
        self.page_title = tk.StringVar()
        ttk.Label(mid, textvariable=self.page_title, font=("Arial", 12, "bold")).pack(anchor="w")
        self.canvas = tk.Canvas(mid, width=int(480 * SCALE), height=int(320 * SCALE), bg="#222", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.hint = tk.StringVar(value="Click a red box to select a button.")
        ttk.Label(mid, textvariable=self.hint, foreground="#555").pack(anchor="w", pady=2)
        self.log = tk.Text(mid, height=8, width=80, font=("Consolas", 9))
        self.log.pack(fill="x")

        right = ttk.Notebook(body, width=360)
        right.pack(side="left", fill="y", padx=4, pady=4)
        # buttons tab
        tb = ttk.Frame(right, padding=6)
        right.add(tb, text="Buttons")
        self.btn_lb = tk.Listbox(tb, height=16, exportselection=False)
        self.btn_lb.pack(fill="x")
        self.btn_lb.bind("<<ListboxSelect>>", self.on_btn_select)
        ttk.Button(tb, text="Change the page it opens ...", command=self.btn_retarget).pack(fill="x", pady=2)
        ttk.Button(tb, text="Remove / restore", command=self.btn_remove).pack(fill="x", pady=2)
        ttk.Button(tb, text="Add a button (drag a box on the page)",
                   command=lambda: self.set_mode("add_button")).pack(fill="x", pady=2)
        ttk.Label(tb, text="Red = opens a page.  Green = added by you.\nGrey = special (keys, brightness): "
                           "not editable.\nStriked = removed.", foreground="#555").pack(anchor="w", pady=6)
        # texts tab
        tt = ttk.Frame(right, padding=6)
        right.add(tt, text="Texts")
        self.txt_lb = tk.Listbox(tt, height=14, exportselection=False)
        self.txt_lb.pack(fill="x")
        ttk.Button(tt, text="Add text (click on the page)", command=lambda: self.set_mode("add_text")).pack(fill="x", pady=2)
        ttk.Button(tt, text="Edit text ...", command=self.txt_edit).pack(fill="x", pady=2)
        ttk.Button(tt, text="Cover old words (drag a box)", command=lambda: self.set_mode("cover")).pack(fill="x", pady=2)
        ttk.Button(tt, text="Move text (click new place)", command=lambda: self.set_mode("move_text")).pack(fill="x", pady=2)
        ttk.Button(tt, text="Delete text", command=self.txt_delete).pack(fill="x", pady=2)
        ttk.Label(tt, text="Tip: to change a word, add a cover box over the old\nword "
                           "(same colour as the background), then write\nthe new word on top.",
                  foreground="#555").pack(anchor="w", pady=6)
        # list page tab
        tl = ttk.Frame(right, padding=6)
        right.add(tl, text="List page")
        ttk.Button(tl, text="New list page", command=self.list_new).pack(fill="x", pady=2)
        self.list_info = tk.StringVar(value="Select a list page (LIST ...) in the page list.")
        ttk.Label(tl, textvariable=self.list_info, foreground="#555").pack(anchor="w", pady=4)
        f = ttk.Frame(tl)
        f.pack(fill="x")
        ttk.Label(f, text="Title").grid(row=0, column=0, sticky="w")
        self.l_title = ttk.Entry(f, width=30)
        self.l_title.grid(row=0, column=1, columnspan=2, sticky="we", pady=2)
        ttk.Label(f, text="BACK opens").grid(row=1, column=0, sticky="w")
        self.l_back = ttk.Combobox(f, width=28, state="readonly")
        self.l_back.grid(row=1, column=1, columnspan=2, sticky="we", pady=2)
        self.l_rows = []
        for i in range(msd.STUDIO_ROWS):
            ttk.Label(f, text="Row %d" % (i + 1)).grid(row=2 + 2 * i, column=0, sticky="w")
            e = ttk.Entry(f, width=30)
            e.grid(row=2 + 2 * i, column=1, columnspan=2, sticky="we")
            ttk.Label(f, text="  opens").grid(row=3 + 2 * i, column=0, sticky="w")
            c = ttk.Combobox(f, width=28, state="readonly")
            c.grid(row=3 + 2 * i, column=1, columnspan=2, sticky="we", pady=(0, 4))
            self.l_rows.append((e, c))
        ttk.Button(tl, text="Apply to this list page", command=self.list_apply).pack(fill="x", pady=4)
        ttk.Button(tl, text="Delete this list page (only the last one)", command=self.list_delete).pack(fill="x")

    # ------------------------------------------------------------------ data
    def list_specs(self):
        return sorted(self.proj["list_pages"], key=lambda s: s["page"])

    def last_page(self):
        return LAST_BUILTIN + len(self.proj["list_pages"])

    def name(self, p):
        for s in self.proj["list_pages"]:
            if s["page"] == p:
                return "LIST: " + s.get("title", "")
        return NAMES.get(p, "page %d" % p)

    def page_label(self, p):
        return "%2d  %s" % (p, self.name(p))

    def page_choices(self):
        return [self.page_label(p) for p in range(self.last_page() + 1)]

    @staticmethod
    def label_page(label):
        return int(label.split()[0])

    def load_cache(self):
        try:
            with open(os.path.join(msd.STUDIO_CACHE, "buttons.json"), encoding="utf-8") as f:
                self.base_buttons = json.load(f)
        except (OSError, ValueError):
            self.base_buttons = []
        self.fill_pages()
        self.show_page(self.page)

    def fill_pages(self):
        self.pages_lb.delete(0, "end")
        for p in range(self.last_page() + 1):
            self.pages_lb.insert("end", self.page_label(p))
        choices = self.page_choices()
        self.l_back["values"] = choices
        for _, c in self.l_rows:
            c["values"] = [""] + choices

    def buttons(self, p):
        """The page's buttons as the SD card will get them: dicts with box,
        target, kind ('base', 'removed', 'added', 'special', 'list')."""
        ed = self.proj["buttons"]
        removed = {tuple(e["box"]) for e in ed["remove"] if e["page"] == p}
        retarget = {tuple(e["box"]): e["target"] for e in ed["retarget"] if e["page"] == p}
        out = []
        for b in self.base_buttons:
            if b["page"] != p:
                continue
            box = tuple(b["box"])
            if b["special"]:
                out.append({"box": box, "target": b["target"], "kind": "special", "code": b["code"]})
            elif box in removed:
                out.append({"box": box, "target": b["target"], "kind": "removed"})
            else:
                out.append({"box": box, "target": retarget.get(box, b["target"]), "kind": "base",
                            "changed": box in retarget})
        for i, e in enumerate(ed["add"]):
            if e["page"] == p:
                out.append({"box": tuple(e["box"]), "target": e["target"], "kind": "added", "index": i})
        for s in self.proj["list_pages"]:
            if s["page"] == p:
                out.append({"box": msd.BACK_BOX, "target": s.get("back", msd.HOME), "kind": "list"})
                out.append({"box": msd.HOME_BOX, "target": msd.HOME, "kind": "list"})
                for i, row in enumerate(s.get("rows", [])[:msd.STUDIO_ROWS]):
                    if isinstance(row.get("target"), int):
                        out.append({"box": msd.studio_row_box(i), "target": row["target"], "kind": "list"})
        return out

    def page_image(self, p):
        spec = next((s for s in self.proj["list_pages"] if s["page"] == p), None)
        if spec is not None:
            im = msd.studio_list_page(spec)
        else:
            path = os.path.join(msd.STUDIO_CACHE, "%02d.png" % p)
            im = Image.open(path).convert("RGB") if os.path.exists(path) else Image.new("RGB", (480, 320), "#333")
        return msd.studio_texts(im, p, self.proj["texts"])

    # ------------------------------------------------------------------ drawing
    def show_page(self, p):
        self.page = p
        self.page_title.set(self.page_label(p))
        self.sel_button = None
        im = self.page_image(p).resize((int(480 * SCALE), int(320 * SCALE)), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.cur_buttons = self.buttons(p)
        self.btn_lb.delete(0, "end")
        for i, b in enumerate(self.cur_buttons):
            x0, y0, x1, y1 = [v * SCALE for v in b["box"]]
            colour = {"base": "#ff3030", "added": "#00c060", "special": "#9aa0a6", "removed": "#ff3030",
                      "list": "#3080ff"}[b["kind"]]
            dash = (4, 3) if b["kind"] in ("removed", "special") else None
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=colour, width=2, dash=dash, tags=("btn", "b%d" % i))
            if b["kind"] == "special":
                label = SPECIAL.get(b["code"], "special")
            else:
                label = "-> %d" % b["target"] + ("  (removed)" if b["kind"] == "removed" else "")
                self.canvas.create_text(x0 + 4, y0 + 2, text="-> %d" % b["target"], anchor="nw",
                                        fill=colour, font=("Arial", 9, "bold"))
            extra = {"added": "  [added]", "list": "  [list row]"}.get(b["kind"], "")
            if b.get("changed"):
                extra += "  [changed]"
            self.btn_lb.insert("end", "%s %s  %s%s" % (label, self.name(b["target"]) if b["kind"] != "special" else "",
                                                       tuple(b["box"]), extra))
        self.txt_lb.delete(0, "end")
        self.cur_texts = [t for t in self.proj["texts"] if t.get("page") == p]
        for t in self.cur_texts:
            self.txt_lb.insert("end", '"%s"  size %s at (%s, %s)%s' % (t.get("text", ""), t.get("size", 16), t.get("x"),
                                                                      t.get("y"), "  + cover" if t.get("cover") else ""))
        spec = next((s for s in self.proj["list_pages"] if s["page"] == p), None)
        self.fill_list_form(spec)
        try:
            self.pages_lb.selection_clear(0, "end")
            self.pages_lb.selection_set(p)
            self.pages_lb.see(p)
        except tk.TclError:
            pass

    def highlight(self, i):
        self.canvas.delete("hl")
        if i is None:
            return
        x0, y0, x1, y1 = [v * SCALE for v in self.cur_buttons[i]["box"]]
        self.canvas.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline="#ffd400", width=3, tags="hl")

    # ------------------------------------------------------------------ events
    def on_page_select(self, _):
        s = self.pages_lb.curselection()
        if s:
            self.set_mode(None)
            self.show_page(s[0])

    def on_btn_select(self, _):
        s = self.btn_lb.curselection()
        self.sel_button = s[0] if s else None
        self.highlight(self.sel_button)

    def set_mode(self, mode):
        self.mode = mode
        self.hint.set({None: "Click a red box to select a button.",
                       "add_button": "Drag a box on the page for the new button.",
                       "add_text": "Click where the new text should start.",
                       "cover": "Select a text first, then drag the box that hides the old words.",
                       "move_text": "Select a text first, then click its new place."}[mode])

    def page_xy(self, e):
        return max(0, min(479, int(e.x / SCALE))), max(0, min(319, int(e.y / SCALE)))

    def on_down(self, e):
        x, y = self.page_xy(e)
        if self.mode in ("add_button", "cover"):
            self.drag = (x, y)
            return
        if self.mode == "add_text":
            self.set_mode(None)
            self.text_dialog({"page": self.page, "x": x, "y": y, "text": "", "size": 16, "color": "#000000",
                              "bold": True}, new=True)
            return
        if self.mode == "move_text":
            t = self.cur_text()
            self.set_mode(None)
            if t:
                t["x"], t["y"] = x, y
                self.changed()
            return
        hits = [i for i, b in enumerate(self.cur_buttons)
                if b["box"][0] <= x <= b["box"][2] and b["box"][1] <= y <= b["box"][3]]
        if hits:
            i = min(hits, key=lambda k: (self.cur_buttons[k]["box"][2] - self.cur_buttons[k]["box"][0]) *
                    (self.cur_buttons[k]["box"][3] - self.cur_buttons[k]["box"][1]))
            self.sel_button = i
            self.btn_lb.selection_clear(0, "end")
            self.btn_lb.selection_set(i)
            self.btn_lb.see(i)
            self.highlight(i)

    def on_move(self, e):
        if self.drag is None:
            return
        x, y = self.page_xy(e)
        self.canvas.delete("drag")
        self.canvas.create_rectangle(self.drag[0] * SCALE, self.drag[1] * SCALE, x * SCALE, y * SCALE,
                                     outline="#ffd400", width=2, dash=(4, 2), tags="drag")

    def on_up(self, e):
        if self.drag is None:
            return
        x, y = self.page_xy(e)
        x0, y0 = self.drag
        self.drag = None
        self.canvas.delete("drag")
        box = [min(x0, x), min(y0, y), max(x0, x), max(y0, y)]
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            return
        mode = self.mode
        self.set_mode(None)
        if mode == "add_button":
            target = self.ask_page("New button opens which page?", msd.HOME)
            if target is not None:
                self.proj["buttons"]["add"].append({"page": self.page, "box": box, "target": target})
                self.changed()
        elif mode == "cover":
            t = self.cur_text()
            if not t:
                messagebox.showinfo("Cover box", "Select (or add) a text in the Texts list first.")
                return
            c = colorchooser.askcolor(color=t.get("cover_color", "#ffffff"), title="Colour of the cover box "
                                      "(pick the page background colour)")
            if c and c[1]:
                t["cover"], t["cover_color"] = box, c[1]
                self.changed()

    # ------------------------------------------------------------------ buttons
    def selected(self):
        if self.sel_button is None or self.sel_button >= len(self.cur_buttons):
            messagebox.showinfo("Buttons", "Select a button first (click it on the page or in the list).")
            return None
        return self.cur_buttons[self.sel_button]

    def btn_retarget(self):
        b = self.selected()
        if not b:
            return
        if b["kind"] in ("special", "list"):
            messagebox.showinfo("Buttons", "Special buttons cannot be changed here. List-page rows are set on "
                                           "the 'List page' tab.")
            return
        target = self.ask_page("This button opens which page?", b["target"])
        if target is None:
            return
        ed = self.proj["buttons"]
        if b["kind"] == "added":
            ed["add"][b["index"]]["target"] = target
        else:
            ed["retarget"] = [e for e in ed["retarget"] if not (e["page"] == self.page and tuple(e["box"]) == b["box"])]
            orig = next(x["target"] for x in self.base_buttons if x["page"] == self.page and tuple(x["box"]) == b["box"])
            if target != orig:
                ed["retarget"].append({"page": self.page, "box": list(b["box"]), "target": target})
        self.changed()

    def btn_remove(self):
        b = self.selected()
        if not b:
            return
        ed = self.proj["buttons"]
        if b["kind"] == "added":
            del ed["add"][b["index"]]
        elif b["kind"] == "removed":
            ed["remove"] = [e for e in ed["remove"] if not (e["page"] == self.page and tuple(e["box"]) == b["box"])]
        elif b["kind"] == "base":
            ed["remove"].append({"page": self.page, "box": list(b["box"])})
        else:
            messagebox.showinfo("Buttons", "Special buttons and list rows cannot be removed here.")
            return
        self.changed()

    def ask_page(self, title, current):
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        ttk.Label(win, text=title, padding=8).pack()
        cb = ttk.Combobox(win, values=self.page_choices(), width=40, state="readonly")
        cb.pack(padx=8)
        if 0 <= current <= self.last_page():
            cb.current(current)
        res = {}

        def ok():
            if cb.get():
                res["p"] = self.label_page(cb.get())
            win.destroy()
        ttk.Button(win, text="OK", command=ok).pack(pady=8)
        self.wait_window(win)
        return res.get("p")

    # ------------------------------------------------------------------ texts
    def cur_text(self):
        s = self.txt_lb.curselection()
        return self.cur_texts[s[0]] if s and s[0] < len(self.cur_texts) else None

    def txt_edit(self):
        t = self.cur_text()
        if not t:
            messagebox.showinfo("Texts", "Select a text first.")
            return
        self.text_dialog(t, new=False)

    def txt_delete(self):
        t = self.cur_text()
        if t and messagebox.askyesno("Texts", 'Delete "%s"?' % t.get("text", "")):
            self.proj["texts"].remove(t)
            self.changed()

    def text_dialog(self, t, new):
        win = tk.Toplevel(self)
        win.title("Text")
        win.transient(self)
        win.grab_set()
        f = ttk.Frame(win, padding=10)
        f.pack()
        ttk.Label(f, text="Text").grid(row=0, column=0, sticky="w")
        e = ttk.Entry(f, width=36)
        e.insert(0, t.get("text", ""))
        e.grid(row=0, column=1, columnspan=2, pady=2)
        ttk.Label(f, text="Size").grid(row=1, column=0, sticky="w")
        size = tk.IntVar(value=int(t.get("size", 16)))
        ttk.Spinbox(f, from_=8, to=60, textvariable=size, width=6).grid(row=1, column=1, sticky="w")
        bold = tk.BooleanVar(value=t.get("bold", True))
        ttk.Checkbutton(f, text="Bold", variable=bold).grid(row=1, column=2, sticky="w")
        colour = {"c": t.get("color", "#000000")}
        sw = tk.Label(f, text="      ", bg=colour["c"], relief="solid")
        sw.grid(row=2, column=1, sticky="w", pady=4)

        def pick():
            c = colorchooser.askcolor(color=colour["c"], title="Text colour")
            if c and c[1]:
                colour["c"] = c[1]
                sw.config(bg=c[1])
        ttk.Button(f, text="Colour ...", command=pick).grid(row=2, column=0, sticky="w")

        def ok():
            t.update({"text": e.get(), "size": int(size.get()), "bold": bool(bold.get()), "color": colour["c"]})
            if new and t["text"]:
                self.proj["texts"].append(t)
            win.destroy()
            self.changed()
        ttk.Button(f, text="OK", command=ok).grid(row=3, column=2, sticky="e", pady=6)
        e.focus_set()
        self.wait_window(win)

    # ------------------------------------------------------------------ list pages
    def fill_list_form(self, spec):
        self.l_title.delete(0, "end")
        for e, c in self.l_rows:
            e.delete(0, "end")
            c.set("")
        if spec is None:
            self.list_info.set("This is not a list page. 'New list page' makes one\n(it gets the next free number).")
            self.l_back.set("")
            return
        self.list_info.set("List page %d. Make a button open it: select a\npage, Buttons tab." % spec["page"])
        self.l_title.insert(0, spec.get("title", ""))
        self.l_back.set(self.page_label(spec.get("back", msd.HOME)))
        for (e, c), row in zip(self.l_rows, spec.get("rows", [])):
            e.insert(0, row.get("label", ""))
            if isinstance(row.get("target"), int):
                c.set(self.page_label(row["target"]))

    def list_new(self):
        p = self.last_page() + 1
        self.proj["list_pages"].append({"page": p, "title": "NEW LIST", "back": msd.HOME,
                                        "rows": [{"label": "Row 1", "target": msd.HOME}]})
        self.dirty = True
        self.fill_pages()
        self.show_page(p)
        self.status("List page %d made - set its title and rows, then make a button open it." % p)

    def list_apply(self):
        spec = next((s for s in self.proj["list_pages"] if s["page"] == self.page), None)
        if spec is None:
            messagebox.showinfo("List page", "Select a list page first.")
            return
        spec["title"] = self.l_title.get().strip() or "LIST"
        if self.l_back.get():
            spec["back"] = self.label_page(self.l_back.get())
        rows = []
        for e, c in self.l_rows:
            if e.get().strip():
                rows.append({"label": e.get().strip(), "target": self.label_page(c.get()) if c.get() else None})
        spec["rows"] = rows
        self.fill_pages()
        self.changed()

    def list_delete(self):
        spec = next((s for s in self.proj["list_pages"] if s["page"] == self.page), None)
        if spec is None or self.page != self.last_page():
            messagebox.showinfo("List page", "Only the last list page can be deleted (page numbers must follow on).")
            return
        if not messagebox.askyesno("List page", "Delete list page %d?" % self.page):
            return
        p = self.page
        self.proj["list_pages"].remove(spec)
        self.proj["texts"] = [t for t in self.proj["texts"] if t.get("page") != p]
        ed = self.proj["buttons"]
        ed["add"] = [e for e in ed["add"] if e["page"] != p and e["target"] != p]
        ed["retarget"] = [e for e in ed["retarget"] if e["target"] != p]
        self.dirty = True
        self.fill_pages()
        self.show_page(msd.HOME)

    # ------------------------------------------------------------------ save / build / deploy
    def changed(self):
        self.dirty = True
        keep = self.btn_lb.curselection()
        self.show_page(self.page)
        if keep and keep[0] < len(self.cur_buttons):
            self.btn_lb.selection_set(keep[0])
            self.sel_button = keep[0]
            self.highlight(keep[0])
        self.status("Changed - not saved yet.")

    def save(self):
        with open(msd.STUDIO_FILE, "w", encoding="utf-8") as f:
            json.dump(self.proj, f, indent=1)
        self.dirty = False
        self.status("Saved to studio_project.json")

    def status(self, text):
        self.status_var.set(text)

    def run_builder(self, sd_root):
        if getattr(self, "busy", False):
            return
        self.save()
        self.busy = True
        cmd = [sys.executable, BUILDER, "--keep-memory"] + (["--sd", sd_root] if sd_root else [])
        self.log.delete("1.0", "end")
        self.status("Deploying to %s ..." % sd_root if sd_root else "Building the pages ...")

        def work():
            try:
                p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in p.stdout:
                    self.log_q.put(line)
                self.log_q.put(("done", p.wait(), sd_root))
            except Exception as ex:
                self.log_q.put(("done", -1, str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def pump_log(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                if isinstance(item, tuple):
                    _, code, sd = item
                    self.busy = False
                    self.load_cache()
                    text = self.log.get("1.0", "end")
                    if code == 0 and sd and "verified OK" in text:
                        self.status("Deployed to %s and checked." % sd)
                        messagebox.showinfo("Deploy", "SD card ready and checked.\n\nNow: power the display off, insert "
                                            "the card, power on, wait for the download to finish, power off, remove "
                                            "the card, power on.")
                    elif code == 0:
                        self.status("Pages built.")
                    else:
                        self.status("Build FAILED - see the messages below.")
                        messagebox.showerror("Build", "The build failed - see the messages under the page.")
                else:
                    self.log.insert("end", item)
                    self.log.see("end")
        except queue.Empty:
            pass
        self.after(100, self.pump_log)

    def deploy(self):
        path = filedialog.askdirectory(title="Choose the SD card (its drive, e.g. E:\\, or its DWIN_SET folder)")
        if not path:
            return
        root = os.path.dirname(path.rstrip("/\\")) if os.path.basename(path.rstrip("/\\")).upper() == "DWIN_SET" else path
        if any(os.path.exists(os.path.join(root, f)) for f in ("main.py", "boot.py", "lib.py")):
            messagebox.showerror("Deploy", "%s looks like the STM32 board's drive, not the SD card." % root)
            return
        if not messagebox.askyesno("Deploy", "Build the pages and copy them to\n\n%s\\DWIN_SET\n\nSaved pictures, "
                                   "video and animations in the display are kept." % root.rstrip("/\\")):
            return
        self.run_builder(root)

    def help(self):
        messagebox.showinfo("DWIN Page Studio", __doc__)

    def on_close(self):
        if self.dirty and messagebox.askyesno("DWIN Page Studio", "Save your changes before closing?"):
            self.save()
        self.destroy()


if __name__ == "__main__":
    Studio().mainloop()
