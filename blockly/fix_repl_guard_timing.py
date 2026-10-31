"""Follow-up patch for index.html (after add_repl_guard.py): the board shows its
">>> " prompt about 1.5 s after Ctrl-C ends main.py, and keys sent in that gap
are lost. So instead of fixed delays, send Ctrl-C/Ctrl-B and WAIT for the prompt
(retrying), then soft-reset. Keeps CRLF; every edit must match exactly once."""
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

EDITS = [
    ("""              if (buffer === '>>> ' || buffer === '... ') _boardAtRepl = true;""",
     """              if (buffer === '>>> ' || buffer === '... ') {
                _boardAtRepl = true;
                if (_promptWaiter) { _promptWaiter(true); _promptWaiter = null; }
              }"""),

    ("""    let _boardAtRepl = false;
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
""",
     """    let _boardAtRepl = false;
    let _readyWaiter = null;    // resolved by "SYSTEM READY"
    let _promptWaiter = null;   // resolved by a ">>> " prompt (true) or ">> Ready." (false)
    const _usbPause = ms => new Promise(r => setTimeout(r, ms));

    function _noteBoardLine(line) {
      if (/^(SYSTEM READY|>> |MAINVER:|LIBVER:|MPY: soft reboot)/.test(line)) _boardAtRepl = false;
      else if (line.indexOf('raw REPL; CTRL-B to exit') >= 0) _boardAtRepl = true;
      if (line.indexOf('SYSTEM READY') === 0 && _readyWaiter) { _readyWaiter(true); _readyWaiter = null; }
      // a program was stopped but main.py is still running: Ctrl-C again
      if (line.indexOf('>> Ready.') === 0 && _promptWaiter) { _promptWaiter(false); _promptWaiter = null; }
    }

    function _waitFor(kind, ms) {
      return new Promise(r => {
        const done = v => { if (kind === 'prompt') { if (_promptWaiter === done) _promptWaiter = null; }
                            else if (_readyWaiter === done) _readyWaiter = null;
                            r(v); };
        if (kind === 'prompt') _promptWaiter = done; else _readyWaiter = done;
        setTimeout(() => done(false), ms);
      });
    }

    // Bring the board to the ">>> " prompt: Ctrl-C stops a running program
    // and then main.py; Ctrl-B leaves the raw REPL. The prompt appears about
    // 1.5 s after main.py ends and keys sent before that are lost, so wait
    // for it and retry.
    async function _toPrompt() {
      for (let i = 0; i < 4; i++) {
        const seen = _waitFor('prompt', 2500);
        await stm32Writer.write(new Uint8Array([3]));
        await _usbPause(60);
        await stm32Writer.write(new Uint8Array([2]));
        if (await seen) return true;
      }
      return false;
    }

    // Stop everything, then Ctrl-D (soft reset): the board restarts its
    // Python and runs main.py again.
    async function restartMainPy() {
      if (!(stm32Port && stm32Writer)) return false;
      await _toPrompt();
      await _usbPause(100);
      const ready = _waitFor('ready', 6000);
      await stm32Writer.write(new Uint8Array([4]));
      const ok = await ready;
      await _usbPause(200);
      _boardAtRepl = false;
      return ok;
    }
"""),

    ("""        const ok = await restartMainPy();""", None),   # sentinel: must not exist

    ("""            // stop everything, then reset from the Python prompt
            for (const b of [3, 3, 3, 2]) {
              await stm32Writer.write(new Uint8Array([b]));
              await _usbPause(150);
            }
            await stm32Writer.write""",
     """            // stop everything, then reset from the Python prompt
            await _toPrompt();
            await _usbPause(100);
            await stm32Writer.write"""),

    ("""            handleBoardMessage("Soft Reset...", "SYS");
            await restartMainPy();
            handleBoardMessage("Soft Reset done", "SYS");""",
     """            handleBoardMessage("Soft Reset...", "SYS");
            const ok = await restartMainPy();
            handleBoardMessage(ok ? "Soft Reset done, main.py running" : "Soft Reset: board did not answer", "SYS");"""),
]

src = open(PATH, "rb").read().decode("utf-8")
for old, new in EDITS:
    old = old.replace("\n", "\r\n")
    if new is None:
        if old in src:
            raise SystemExit("unexpected text present: " + old)
        continue
    new = new.replace("\n", "\r\n")
    n = src.count(old)
    if n != 1:
        raise SystemExit("edit matched %d times:\n%s" % (n, old[:200]))
    src = src.replace(old, new)
open(PATH, "wb").write(src.encode("utf-8"))
print("patched OK")
