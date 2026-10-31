"""DWIN Image Sender - pick a picture on the PC, send it through the STM32
board to the DWIN display (live drawing over the UART, no SD card).

Needs: Python 3 with Pillow, pyserial and mpremote (all already installed).
Run:   python dwin_image_app.py
"""
import os, sys, struct, threading, time, io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageOps
from serial.tools import list_ports
from mpremote.transport_serial import SerialTransport

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = os.path.join(HERE, "img_relay.py")
SIZES = {
    "Normal 160 x 106, fills the screen (about 9 s)": (160, 106, 3),
    "Fast 120 x 80, centred (about 5 s)": (120, 80, 3),
}


def find_port():
    for p in list_ports.comports():
        if p.vid == 0xF055 or "USB Serial" in (p.description or ""):
            return p.device
    return None


class Board:
    def __init__(self, port):
        self.t = SerialTransport(port, 115200)
        self.ser = self.t.serial
        self._start_relay()

    def _start_relay(self):
        for attempt in range(4):            # the board's program needs 2 interrupts
            try:
                self.t.enter_raw_repl(soft_reset=False)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.0)
        self.t.exec_raw_no_follow(open(RELAY).read())
        self._wait_line(b"READY", 10)

    def ensure(self):
        """Restart the relay if it has exited (it leaves after 10 min idle)."""
        self.ser.reset_input_buffer()
        self.ser.write(b"PNG1")
        try:
            self._wait_line(b"PONG", 1.5)
        except RuntimeError:
            self._start_relay()

    def _wait_line(self, prefix, timeout, progress=None):
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            n = self.ser.in_waiting
            if not n:                       # never block: the port has no read timeout
                time.sleep(0.01)
                continue
            buf += self.ser.read(n)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip(b"\r\x04> ")
                if line.startswith(b"ERR"):
                    raise RuntimeError(line.decode(errors="replace"))
                if line.startswith(b"P") and progress and line[1:].isdigit():
                    progress(int(line[1:]))
                if line.startswith(prefix):
                    return line.decode(errors="replace")
        raise RuntimeError("timeout waiting for %s" % prefix.decode())

    def send_image(self, im, scale, progress):
        w, h = im.size
        raw = im.convert("RGB").tobytes()
        data = bytearray()
        for k in range(0, len(raw), 3):
            r, g, b = raw[k], raw[k + 1], raw[k + 2]
            data += struct.pack(">H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
        self.ensure()
        x = (480 - w * scale) // 2
        y = (320 - h * scale) // 2
        self.ser.write(b"IMG1" + struct.pack(">HHHHB", x, y, w, h, scale))
        self.ser.write(bytes(data))
        return self._wait_line(b"DONE", 240, progress)

    def clear(self):
        self.ensure()
        self.ser.write(b"CLR1")
        self._wait_line(b"OK", 5)

    def page(self, p):
        self.ensure()
        self.ser.write(b"PAG1" + struct.pack(">H", p))
        self._wait_line(b"OK", 5)

    def close(self, reset=False):
        try:
            self.ser.write(b"BYE1")
            self._wait_line(b"OK", 3)
        except Exception:
            pass
        try:
            self.t.exit_raw_repl()
            if reset:
                self.ser.write(b"\x03import machine; machine.reset()\r\n")
        except Exception:
            pass
        self.t.close()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DWIN Image Sender")
        self.resizable(False, False)
        self.image = None
        self.board = None
        f = ttk.Frame(self, padding=12)
        f.grid()
        ttk.Button(f, text="Choose image...", command=self.choose).grid(row=0, column=0, sticky="w")
        self.lbl_file = ttk.Label(f, text="no image")
        self.lbl_file.grid(row=0, column=1, columnspan=2, sticky="w", padx=8)
        self.canvas = tk.Label(f, bg="black", width=480, height=320)
        self.canvas.grid(row=1, column=0, columnspan=3, pady=8)
        ttk.Label(f, text="Size:").grid(row=2, column=0, sticky="w")
        self.size = ttk.Combobox(f, values=list(SIZES), state="readonly", width=40)
        self.size.current(0)
        self.size.grid(row=2, column=1, columnspan=2, sticky="w")
        self.port_var = tk.StringVar(value=find_port() or "")
        ttk.Label(f, text="Board port:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.port_var, width=10).grid(row=3, column=1, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=3, pady=10, sticky="w")
        self.btn_send = ttk.Button(b, text="Show on display", command=self.send)
        self.btn_send.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(b, text="Clear screen", command=lambda: self.run(self.do_clear)).grid(row=0, column=1, padx=6)
        ttk.Button(b, text="Back to home page", command=lambda: self.run(self.do_home)).grid(row=0, column=2, padx=6)
        ttk.Button(b, text="Disconnect + reset board", command=lambda: self.run(self.do_reset)).grid(row=0, column=3, padx=6)
        self.prog = ttk.Progressbar(f, length=480, maximum=100)
        self.prog.grid(row=5, column=0, columnspan=3)
        self.status = ttk.Label(f, text="Pick an image, then Show on display.")
        self.status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def choose(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All", "*.*")])
        if not path:
            return
        self.image = Image.open(path).convert("RGB")
        self.lbl_file.config(text=os.path.basename(path))
        prev = ImageOps.pad(self.image, (480, 320), color="black")
        self.tkimg = ImageTk.PhotoImage(prev)
        self.canvas.config(image=self.tkimg)

    def connect(self):
        if self.board is None:
            port = self.port_var.get().strip() or find_port()
            if not port:
                raise RuntimeError("board not found: plug in the STM32 board")
            self.set_status("Connecting to %s and starting the relay..." % port)
            self.board = Board(port)
        return self.board

    def set_status(self, text):
        self.after(0, lambda: self.status.config(text=text))

    def run(self, fn):
        def worker():
            try:
                self.after(0, lambda: self.btn_send.config(state="disabled"))
                fn()
            except Exception as e:
                self.set_status("Error: %s" % e)
                if self.board:
                    try:
                        self.board.t.close()
                    except Exception:
                        pass
                    self.board = None
            finally:
                self.after(0, lambda: self.btn_send.config(state="normal"))
        threading.Thread(target=worker, daemon=True).start()

    def send(self):
        if self.image is None:
            messagebox.showinfo("DWIN Image Sender", "Choose an image first.")
            return
        w, h, scale = SIZES[self.size.get()]
        im = ImageOps.pad(self.image, (w, h), color="black")

        def job():
            b = self.connect()
            self.set_status("Sending %d x %d..." % (w, h))
            self.after(0, lambda: self.prog.config(value=0))
            reply = b.send_image(im, scale, lambda p: self.after(0, lambda: self.prog.config(value=p)))
            self.after(0, lambda: self.prog.config(value=100))
            self.set_status("Shown on the display (%s ms). Tap HOME corner on the display or use Back to home." % reply.split()[-1])
        self.run(job)

    def do_clear(self):
        self.connect().clear()
        self.set_status("Viewer page cleared.")

    def do_home(self):
        self.connect().page(10)
        self.set_status("Display is on the home page.")

    def do_reset(self):
        if self.board:
            self.board.close(reset=True)
            self.board = None
        self.set_status("Board reset; its normal program is running again.")

    def on_close(self):
        if self.board:
            try:
                self.board.close(reset=True)
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
