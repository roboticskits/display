"""Copy one file to the Curio board (MOTHER BOARD R3) safely over USB serial.

usage:  python install_file.py <local file> <name on board>
        python install_file.py lib_with_dwin.py lib.py

Why not mpremote cp: main.py's receive timer keeps reading USB after main.py
is stopped, and long copies stall. This script stops that timer, writes the
file in small checked pieces to a temporary name, compares the checksum, and
only then replaces the real file. A failed transfer never leaves a half file
under the real name. At the end the board is soft-reset back into main.py.
Close the Blockly page's USB connection first (the port must be free)."""
import sys, time, binascii, serial
from serial.tools import list_ports

CHUNK = 1024          # raw bytes per piece (sent as base64)

# Checksum a file on the board in 4 KB pieces (reading a 100 KB file in one go
# needs one large free block, which the board often does not have).
CRC_FN = ("def _crc_file(name):\n"
          "    import binascii\n"
          "    c = n = 0\n"
          "    with open(name, 'rb') as f:\n"
          "        while True:\n"
          "            d = f.read(4096)\n"
          "            if not d:\n"
          "                break\n"
          "            c = binascii.crc32(d, c)\n"
          "            n += len(d)\n"
          "    return '%d %d' % (n, c)\n")


class Board:
    def __init__(self):
        ports = [p.device for p in list_ports.comports() if p.vid == 0xF055]
        if not ports:
            sys.exit("Board not found (no MicroPython USB port).")
        self.s = serial.Serial(ports[0], 115200, timeout=0.05)
        self.port = ports[0]

    def _until(self, pat, t):
        buf = b""
        end = time.time() + t
        while time.time() < end:
            buf += self.s.read(4096)
            if pat in buf:
                return buf
        return None

    def enter_raw(self):
        for _ in range(8):
            self.s.write(b"\r\x03"); time.sleep(0.15); self.s.write(b"\x03"); time.sleep(0.4)
            self.s.read(65536)
            self.s.write(b"\x01")
            if self._until(b"raw REPL; CTRL-B to exit\r\n>", 2):
                return True
            time.sleep(1.6)      # the prompt appears ~1.5 s after main.py ends
        return False

    def run(self, code, t=30):
        self.s.write(code.encode() + b"\x04")
        out = self._until(b"\x04>", t)
        if out is None or b"OK" not in out:
            raise RuntimeError("board did not answer: %r" % (out[-120:] if out else None))
        body = out[out.find(b"OK") + 2:-2]
        res, _, err = body.partition(b"\x04")
        if err.strip():
            raise RuntimeError(err.decode(errors="replace").strip())
        return res.decode(errors="replace").strip()

    def back_to_main(self):
        self.s.write(b"\x02"); time.sleep(0.2); self.s.write(b"\x04")
        ok = self._until(b"SYSTEM READY", 10) is not None
        self.s.close()
        return ok


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    local, remote = sys.argv[1], sys.argv[2]
    data = open(local, "rb").read()
    want = "%d %d" % (len(data), binascii.crc32(data))
    tmp = remote + ".new"

    b = Board()
    print("board on", b.port)
    if not b.enter_raw():
        sys.exit("Could not reach the board's Python prompt.")
    b.run("try:\n stop_checker.deinit()\nexcept Exception:\n pass\n")
    b.run("import os, binascii\nf = open(%r, 'wb')\nw = f.write\na = binascii.a2b_base64" % tmp)
    t0 = time.time()
    for i in range(0, len(data), CHUNK):
        piece = binascii.b2a_base64(data[i:i + CHUNK]).strip().decode()
        for attempt in range(3):
            try:
                b.run("w(a(%r))" % piece, 20)
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                b.run("f.seek(%d)" % i)       # resend this piece
        print("\r  %d / %d bytes" % (min(i + CHUNK, len(data)), len(data)), end="", flush=True)
    b.run("f.close()")
    print("  (%.1f s)" % (time.time() - t0))
    b.run(CRC_FN)
    got = b.run("print(_crc_file(%r))" % tmp, 60)
    if got != want:
        b.run("os.remove(%r)" % tmp)
        sys.exit("Checksum mismatch (board %s, file %s) - %s left unchanged." % (got, want, remote))
    b.run("try:\n os.remove(%r)\nexcept OSError:\n pass\nos.rename(%r, %r)" % (remote, tmp, remote))
    final = b.run("print(_crc_file(%r))" % remote, 60)
    print("installed %s: %s (expected %s)" % (remote, final, want))
    print("main.py restarted:", b.back_to_main())
    if final != want:
        sys.exit(1)


if __name__ == "__main__":
    main()
