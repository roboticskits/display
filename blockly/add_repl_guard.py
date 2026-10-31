"""One-time patch for index.html: detect when the board sits at the MicroPython
prompt (main.py not running) and restart main.py before PLAY / upload; make the
Soft Reset / Hard Reset buttons work over USB in every board state.
Keeps CRLF line endings; every edit must match exactly once."""
import shutil, os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
BACKUP = os.path.join(os.path.dirname(PATH), "backups", "before_repl_guard", "index.html")

EDITS = [
    # 1. read loop: note main.py / REPL lines and a bare REPL prompt
    ("""              for (let line of lines) {
                line = line.trim();
                if (line) handleBoardMessage(line, 'USB');
              }
              // Yield to the UI thread every 32 reads to prevent starvation""",
     """              for (let line of lines) {
                line = line.trim();
                if (line) { _noteBoardLine(line); handleBoardMessage(line, 'USB'); }
              }
              // A bare ">>> " or "... " left over means the board is sitting
              // at the MicroPython prompt: main.py is not running.
              if (buffer === '>>> ' || buffer === '... ') _boardAtRepl = true;
              // Yield to the UI thread every 32 reads to prevent starvation"""),

    # 2. helpers, placed right before the upload section
    ("""    // =====================================================================
    // Unified Chunked Upload with ACK
    // =====================================================================
""",
     """    // =====================================================================
    // main.py guard (USB)
    // If main.py stops (Ctrl-C from another tool, an error, ...) the board
    // drops to the MicroPython prompt and silently ignores PLAY / UPLOAD.
    // =====================================================================
    let _boardAtRepl = false;
    let _readyWaiter = null;
    const _usbPause = ms => new Promise(r => setTimeout(r, ms));

    function _noteBoardLine(line) {
      if (/^(SYSTEM READY|>> |MAINVER:|LIBVER:|MPY: soft reboot)/.test(line)) _boardAtRepl = false;
      else if (line.indexOf('raw REPL; CTRL-B to exit') >= 0) _boardAtRepl = true;
      if (line.indexOf('SYSTEM READY') === 0 && _readyWaiter) { _readyWaiter(); _readyWaiter = null; }
    }

    // Ctrl-C x3 (stop a program, then main.py), Ctrl-B (leave raw REPL),
    // Ctrl-D (soft reset): the board restarts its Python and runs main.py.
    async function restartMainPy() {
      if (!(stm32Port && stm32Writer)) return false;
      const ready = new Promise(r => { _readyWaiter = r; setTimeout(r, 4000); });
      for (const b of [3, 3, 3, 2]) {
        await stm32Writer.write(new Uint8Array([b]));
        await _usbPause(150);
      }
      await stm32Writer.write(new Uint8Array([4]));
      await ready;
      _readyWaiter = null;
      await _usbPause(200);
      _boardAtRepl = false;
      return true;
    }

    // At the MicroPython prompt a bare newline prints ">>> "; main.py
    // ignores it. If the prompt shows up, restart main.py first.
    async function ensureMainPyRunning() {
      if (!(stm32Port && stm32Writer)) return;
      if (!_boardAtRepl) {
        await stm32Writer.write(stm32Encoder.encode('\\r\\n'));
        await _usbPause(250);
      }
      if (_boardAtRepl) {
        handleBoardMessage('Board was at the Python prompt (main.py not running). Restarting main.py...', 'SYS');
        await restartMainPy();
        handleBoardMessage('main.py restarted.', 'SYS');
      }
    }

    // =====================================================================
    // Unified Chunked Upload with ACK
    // =====================================================================
"""),

    # 3. upload: make sure main.py is listening first
    ("""      try {
        handleBoardMessage(isUSB ? "USB: uploading..." : "WEB (BLE): uploading...", "SYS");
""",
     """      try {
        if (isUSB) await ensureMainPyRunning();
        handleBoardMessage(isUSB ? "USB: uploading..." : "WEB (BLE): uploading...", "SYS");
"""),

    # 4. PLAY / STOP / SOFT RESET / HARD RESET buttons
    ("""        await withOpLock("playmode", async () => {
          await sendUnifiedCommand("PLAY");
        });""",
     """        await withOpLock("playmode", async () => {
          if (stm32Port && stm32Writer) await ensureMainPyRunning();
          await sendUnifiedCommand("PLAY");
        });"""),
    ("""        await withOpLock("stop", async () => {
          await sendUnifiedCommand("STOP");
        });""",
     """        await withOpLock("stop", async () => {
          if (stm32Port && stm32Writer && _boardAtRepl) { await ensureMainPyRunning(); return; }
          await sendUnifiedCommand("STOP");
        });"""),
    ("""        await withOpLock("soft_reset", async () => {
          const ok = await sendUnifiedCommand("SOFT_RESET");""",
     """        await withOpLock("soft_reset", async () => {
          if (stm32Port && stm32Writer) {
            // works whether main.py is idle, running a program or stopped
            handleBoardMessage("Soft Reset...", "SYS");
            await restartMainPy();
            handleBoardMessage("Soft Reset done", "SYS");
            return;
          }
          const ok = await sendUnifiedCommand("SOFT_RESET");"""),
    ("""        await withOpLock("hard_reset", async () => {
          const ok = await sendUnifiedCommand("HARD_RESET");""",
     """        await withOpLock("hard_reset", async () => {
          if (stm32Port && stm32Writer) {
            // stop everything, then reset from the Python prompt
            for (const b of [3, 3, 3, 2]) {
              await stm32Writer.write(new Uint8Array([b]));
              await _usbPause(150);
            }
            await stm32Writer.write(stm32Encoder.encode("import machine\\r\\nmachine.reset()\\r\\n"));
            handleBoardMessage("Hardware Rebooting... reconnect USB when the board is back.", "SYS");
            return;
          }
          const ok = await sendUnifiedCommand("HARD_RESET");"""),
]

src = open(PATH, "rb").read().decode("utf-8")
crlf = "\r\n" in src
for old, new in EDITS:
    if crlf:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    n = src.count(old)
    if n != 1:
        raise SystemExit("edit matched %d times:\n%s" % (n, old[:200]))
    src = src.replace(old, new)

os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
if not os.path.exists(BACKUP):
    shutil.copy2(PATH, BACKUP)
open(PATH, "wb").write(src.encode("utf-8"))
print("patched %d edits, CRLF=%s, backup at %s" % (len(EDITS), crlf, BACKUP))
