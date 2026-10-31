    // =====================================================================
    // DWIN VIDEO  (short silent clip, played by the DWIN screen itself)
    //
    // "play video" block: click its picture to choose a video. The browser
    // cuts it into frames (240 x 160, 10 per second, at most 256 = 25.6 s),
    // encodes each frame as a JPEG in the display's icon format (baseline
    // 4:4:4, standard Huffman tables, scan 4-byte aligned - the same encoder
    // as dwin_save in the board's lib.py), packs them into an icon library
    // (49_Video.icl: display flash font IDs 49-63, max 3.75 MB) and streams it
    // at once through the board (main.py "DWV" transfer, 4 KB per step) into
    // the display's flash - too big to travel with the program like the "show
    // image" picture, so the block keeps only a small preview. The SD-card
    // project plays it on page 44 (VIDEO) with an Animation Icon control
    // (icons 0-255, 5 x 20 ms per frame, looping).
    // A clip shorter than 256 frames is repeated to fill the 256 icons; the
    // repeated icons point to the same data, so they cost nothing.
    // =====================================================================
    window.DwinVideo = (() => {
      const W = 240, H = 160, FPS = 10, ICONS = 256;
      const LIB_ID = 49, FIRST_BLOCK = LIB_ID * 8, BLOCK = 32768;
      const MAX_BYTES = 15 * 256 * 1024;            // font IDs 49..63

      // ---------------------------------------------------------- JPEG encoder
      const ZZ = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48,
        41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15,
        23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63];
      const QL = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40,
        57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24,
        35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98,
        112, 100, 103, 99];
      const QC = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99,
        99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99].concat(new Array(32).fill(99));
      const DC_BITS = [[0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0]];
      const DC_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
      const AC_BITS = [[0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D], [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77]];
      const hexBytes = s => { const a = []; for (let i = 0; i < s.length; i += 2) a.push(parseInt(s.substr(i, 2), 16)); return a; };
      const AC_VALS = [hexBytes(
        '01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a' +
        '3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a9293' +
        '9495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6' +
        'e7e8e9eaf1f2f3f4f5f6f7f8f9fa'), hexBytes(
        '000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a26' +
        '2728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788' +
        '898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3' +
        'e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa')];

      function huff(bits, vals) {
        const code = new Int32Array(256), size = new Int32Array(256);
        let c = 0, k = 0;
        for (let ln = 1; ln <= 16; ln++) {
          for (let i = 0; i < bits[ln - 1]; i++) { code[vals[k]] = c; size[vals[k]] = ln; c++; k++; }
          c <<= 1;
        }
        return [code, size];
      }
      const DCL = huff(DC_BITS[0], DC_VALS), ACL = huff(AC_BITS[0], AC_VALS[0]);
      const DCC = huff(DC_BITS[1], DC_VALS), ACC = huff(AC_BITS[1], AC_VALS[1]);

      function qtable(base, q) {
        const s = q < 50 ? Math.floor(5000 / q) : 200 - 2 * q;
        return base.map(b => Math.min(255, Math.max(1, Math.floor((b * s + 50) / 100))));
      }

      class Bits {
        constructor(cap) { this.buf = new Uint8Array(cap); this.p = 0; this.acc = 0; this.n = 0; }
        room(k) {
          if (this.p + k <= this.buf.length) return;
          const nb = new Uint8Array(Math.max(this.buf.length * 2, this.p + k));
          nb.set(this.buf); this.buf = nb;
        }
        bytes(a) { this.room(a.length); this.buf.set(a, this.p); this.p += a.length; }
        put(code, size) {                           // size <= 16, acc keeps < 8 bits
          this.acc = (this.acc << size) | code;
          this.n += size;
          this.room(8);
          while (this.n >= 8) {
            this.n -= 8;
            const b = (this.acc >> this.n) & 0xFF;
            this.buf[this.p++] = b;
            if (b === 0xFF) this.buf[this.p++] = 0;
          }
          this.acc &= (1 << this.n) - 1;
        }
      }

      // 8x8 forward DCT, libjpeg 'islow' integer method (output x8) - identical to lib.py
      function fdct(d) {
        for (let i = 0; i < 64; i += 8) {
          const t0 = d[i] + d[i + 7], t7 = d[i] - d[i + 7], t1 = d[i + 1] + d[i + 6], t6 = d[i + 1] - d[i + 6];
          const t2 = d[i + 2] + d[i + 5], t5 = d[i + 2] - d[i + 5], t3 = d[i + 3] + d[i + 4], t4 = d[i + 3] - d[i + 4];
          const t10 = t0 + t3, t13 = t0 - t3, t11 = t1 + t2, t12 = t1 - t2;
          d[i] = (t10 + t11) * 4;
          d[i + 4] = (t10 - t11) * 4;
          let z1 = (t12 + t13) * 4433;
          d[i + 2] = Math.floor((z1 + t13 * 6270 + 1024) / 2048);
          d[i + 6] = Math.floor((z1 - t12 * 15137 + 1024) / 2048);
          z1 = t4 + t7; const z2 = t5 + t6; let z3 = t4 + t6, z4 = t5 + t7;
          const z5 = (z3 + z4) * 9633;
          const a4 = t4 * 2446, a5 = t5 * 16819, a6 = t6 * 25172, a7 = t7 * 12299;
          const b1 = z1 * -7373, b2 = z2 * -20995;
          z3 = z3 * -16069 + z5; z4 = z4 * -3196 + z5;
          d[i + 7] = Math.floor((a4 + b1 + z3 + 1024) / 2048);
          d[i + 5] = Math.floor((a5 + b2 + z4 + 1024) / 2048);
          d[i + 3] = Math.floor((a6 + b2 + z3 + 1024) / 2048);
          d[i + 1] = Math.floor((a7 + b1 + z4 + 1024) / 2048);
        }
        for (let i = 0; i < 8; i++) {
          const t0 = d[i] + d[i + 56], t7 = d[i] - d[i + 56], t1 = d[i + 8] + d[i + 48], t6 = d[i + 8] - d[i + 48];
          const t2 = d[i + 16] + d[i + 40], t5 = d[i + 16] - d[i + 40], t3 = d[i + 24] + d[i + 32], t4 = d[i + 24] - d[i + 32];
          const t10 = t0 + t3, t13 = t0 - t3, t11 = t1 + t2, t12 = t1 - t2;
          d[i] = Math.floor((t10 + t11 + 2) / 4);
          d[i + 32] = Math.floor((t10 - t11 + 2) / 4);
          let z1 = (t12 + t13) * 4433;
          d[i + 16] = Math.floor((z1 + t13 * 6270 + 16384) / 32768);
          d[i + 48] = Math.floor((z1 - t12 * 15137 + 16384) / 32768);
          z1 = t4 + t7; const z2 = t5 + t6; let z3 = t4 + t6, z4 = t5 + t7;
          const z5 = (z3 + z4) * 9633;
          const a4 = t4 * 2446, a5 = t5 * 16819, a6 = t6 * 25172, a7 = t7 * 12299;
          const b1 = z1 * -7373, b2 = z2 * -20995;
          z3 = z3 * -16069 + z5; z4 = z4 * -3196 + z5;
          d[i + 56] = Math.floor((a4 + b1 + z3 + 16384) / 32768);
          d[i + 40] = Math.floor((a5 + b2 + z4 + 16384) / 32768);
          d[i + 24] = Math.floor((a6 + b2 + z3 + 16384) / 32768);
          d[i + 8] = Math.floor((a7 + b1 + z4 + 16384) / 32768);
        }
      }

      function block(d, q, prev, dct, act, bw) {
        fdct(d);
        const h = q[0] >> 1, v0 = d[0];
        const dc = v0 >= 0 ? Math.floor((v0 + h) / q[0]) : -Math.floor((h - v0) / q[0]);
        const diff = dc - prev;
        let a = diff < 0 ? -diff : diff, nb = 0;
        while (a) { nb++; a >>= 1; }
        bw.put(dct[0][nb], dct[1][nb]);
        if (nb) bw.put(diff > 0 ? diff : diff + (1 << nb) - 1, nb);
        let run = 0;
        for (let k = 1; k < 64; k++) {
          const qq = q[k];
          let v = d[ZZ[k]];
          v = v >= 0 ? Math.floor((v + (qq >> 1)) / qq) : -Math.floor(((qq >> 1) - v) / qq);
          if (v === 0) { run++; continue; }
          while (run > 15) { bw.put(act[0][0xF0], act[1][0xF0]); run -= 16; }
          a = v < 0 ? -v : v; nb = 0;
          while (a) { nb++; a >>= 1; }
          const s = (run << 4) | nb;
          bw.put(act[0][s], act[1][s]);
          bw.put(v > 0 ? v : v + (1 << nb) - 1, nb);
          run = 0;
        }
        if (run) bw.put(act[0][0], act[1][0]);
        return dc;
      }

      // RGBA pixels (w x h, multiples of 8) -> DWIN icon record: w, h, header
      // length, scan length (10 bytes) + JPEG with SOS segment and scan padded
      // so the scan starts and ends 4-byte aligned.
      function encodeFrame(rgba, w, h, quality) {
        const ql = qtable(QL, quality), qc = qtable(QC, quality);
        const qlz = ZZ.map(z => ql[z] * 8), qcz = ZZ.map(z => qc[z] * 8);
        let hd = [0xFF, 0xD8, 0xFF, 0xE0, 0, 16, 0x4A, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0];
        [[0, ql], [1, qc]].forEach(([tid, qt]) => { hd = hd.concat([0xFF, 0xDB, 0, 67, tid], ZZ.map(z => qt[z])); });
        hd = hd.concat([0xFF, 0xC0, 0, 17, 8, h >> 8, h & 255, w >> 8, w & 255, 3, 1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1]);
        [[0x00, DC_BITS[0], DC_VALS], [0x10, AC_BITS[0], AC_VALS[0]], [0x01, DC_BITS[1], DC_VALS], [0x11, AC_BITS[1], AC_VALS[1]]]
          .forEach(([tc, bits, vals]) => { const ln = 19 + vals.length; hd = hd.concat([0xFF, 0xC4, ln >> 8, ln & 255, tc], bits, vals); });
        const pad = ((-(10 + hd.length + 14)) % 4 + 4) % 4;
        hd = hd.concat([0xFF, 0xDA, 0, 12 + pad, 3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0], new Array(pad).fill(0));
        const hl = hd.length;
        const bw = new Bits(w * h + 4096);
        bw.p = 10;
        bw.bytes(hd);
        const Y = new Int32Array(64), U = new Int32Array(64), V = new Int32Array(64);
        let py = 0, pu = 0, pv = 0;
        for (let by = 0; by < h; by += 8) {
          for (let bx = 0; bx < w; bx += 8) {
            let k = 0;
            for (let r = 0; r < 8; r++) {
              let i = ((by + r) * w + bx) * 4;
              for (let c = 0; c < 8; c++, i += 4, k++) {
                const R = rgba[i], G = rgba[i + 1], B = rgba[i + 2];
                Y[k] = ((77 * R + 150 * G + 29 * B + 128) >> 8) - 128;
                U[k] = (-43 * R - 85 * G + 128 * B + 128) >> 8;
                V[k] = (128 * R - 107 * G - 21 * B + 128) >> 8;
              }
            }
            py = block(Y, qlz, py, DCL, ACL, bw);
            pu = block(U, qcz, pu, DCC, ACC, bw);
            pv = block(V, qcz, pv, DCC, ACC, bw);
          }
        }
        if (bw.n) bw.put((1 << (8 - bw.n)) - 1, 8 - bw.n);
        bw.bytes([0xFF, 0xD9]);
        while ((bw.p - 10 - hl) % 4) bw.bytes([0]);
        const sl = bw.p - 10 - hl;
        bw.buf.set([w >> 8, w & 255, h >> 8, h & 255, hl >> 8, hl & 255, (sl >>> 24) & 255, (sl >> 16) & 255, (sl >> 8) & 255, sl & 255], 0);
        return bw.buf.slice(0, bw.p);
      }

      // ---------------------------------------------------------- icon library
      function crc16modbus(a) {
        let c = 0xFFFF;
        for (let i = 0; i < a.length; i++) {
          c ^= a[i];
          for (let b = 0; b < 8; b++) c = (c & 1) ? (c >>> 1) ^ 0xA001 : c >>> 1;
        }
        return c;
      }
      const CRC32T = (() => {
        const t = new Uint32Array(256);
        for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
        return t;
      })();
      function crc32(a) {
        let c = 0xFFFFFFFF;
        for (let i = 0; i < a.length; i++) c = CRC32T[(c ^ a[i]) & 255] ^ (c >>> 8);
        return (c ^ 0xFFFFFFFF) >>> 0;
      }

      // 'DGUS_3' + CRC-16/MODBUS (LE) of bytes 8.. + length - 8 (BE32) + 04 00 +
      // last index (LE16) + offsets (BE32) + records; icon i shows record i % n.
      function buildIcl(records, count) {
        const tableEnd = 16 + 4 * count;
        const offs = [];
        let o = tableEnd;
        records.forEach(r => { offs.push(o); o += r.length; });
        const out = new Uint8Array(o);
        out.set([0x44, 0x47, 0x55, 0x53, 0x5F, 0x33], 0);
        const be32 = (p, v) => { out[p] = (v >>> 24) & 255; out[p + 1] = (v >>> 16) & 255; out[p + 2] = (v >>> 8) & 255; out[p + 3] = v & 255; };
        be32(8, o - 8);
        out[12] = 4; out[13] = 0;
        out[14] = (count - 1) & 255; out[15] = (count - 1) >> 8;
        for (let i = 0; i < count; i++) be32(16 + 4 * i, offs[i % records.length]);
        records.forEach((r, i) => out.set(r, offs[i]));
        const c = crc16modbus(out.subarray(8));
        out[6] = c & 255; out[7] = c >> 8;
        return out;
      }

      // ---------------------------------------------------------- video -> frames
      const pause = ms => new Promise(r => setTimeout(r, ms));
      function seekTo(v, t) {
        return new Promise(res => {
          if (Math.abs(v.currentTime - t) < 1e-4 && v.readyState >= 2) { res(); return; }
          const done = () => { v.removeEventListener('seeked', done); res(); };
          v.addEventListener('seeked', done);
          v.currentTime = t;
        });
      }
      async function readFrames(file, progress) {
        const url = URL.createObjectURL(file);
        const v = document.createElement('video');
        v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
        try {
          await new Promise((res, rej) => {
            v.onloadeddata = res;
            v.onerror = () => rej(new Error('the browser cannot read this video (try MP4 H.264 or WebM)'));
          });
          let dur = v.duration;
          if (!isFinite(dur)) {                     // e.g. WebM from a recorder: find the length
            await new Promise(res => {
              const t = setTimeout(res, 5000);
              v.ondurationchange = () => { if (isFinite(v.duration)) { clearTimeout(t); res(); } };
              v.currentTime = 1e7;
            });
            v.ondurationchange = null;
            dur = isFinite(v.duration) ? v.duration : 1;
          }
          const n = Math.max(1, Math.min(ICONS, Math.floor(dur * FPS + 1e-6)));
          const c = document.createElement('canvas');
          c.width = W; c.height = H;
          const g = c.getContext('2d', { willReadFrequently: true });
          const frames = [];
          for (let k = 0; k < n; k++) {
            await seekTo(v, Math.min(k / FPS, Math.max(0, dur - 0.05)));
            g.fillStyle = '#000';
            g.fillRect(0, 0, W, H);
            const s = Math.min(W / v.videoWidth, H / v.videoHeight);
            const dw = v.videoWidth * s, dh = v.videoHeight * s;
            g.drawImage(v, (W - dw) / 2, (H - dh) / 2, dw, dh);
            frames.push(g.getImageData(0, 0, W, H).data);
            if (progress) progress(k + 1, n);
          }
          return { frames, seconds: n / FPS, full: dur };
        } finally {
          v.removeAttribute('src'); v.load();
          URL.revokeObjectURL(url);
        }
      }
      async function encodeAll(frames, progress) {
        for (const q of [75, 60, 45, 30]) {
          const recs = [];
          let total = 16 + 4 * ICONS;
          for (let i = 0; i < frames.length && total <= MAX_BYTES; i++) {
            const r = encodeFrame(frames[i], W, H, q);
            recs.push(r);
            total += r.length;
            if (i % 16 === 15) { if (progress) progress(i + 1, frames.length, q); await pause(0); }
          }
          if (total <= MAX_BYTES && recs.length === frames.length) return { recs, quality: q };
        }
        throw new Error('this video is too detailed to fit the screen memory, even at low quality');
      }

      // ---------------------------------------------------------- transfer
      let waiter = null;
      function onBoardLine(line) {                  // called by handleBoardMessage
        if (!line || !line.startsWith('DWV:')) return false;
        if (waiter && waiter.re.test(line)) { const w = waiter; waiter = null; w.resolve(line); }
        return !/^DWV:(ERR|DONE)/.test(line);       // hide the handshakes, show errors and DONE
      }
      function waitFor(re, ms) {
        return new Promise((resolve, reject) => {
          const me = { re, resolve: line => { clearTimeout(t); resolve(line); } };
          const t = setTimeout(() => { if (waiter === me) waiter = null; reject(new Error('the board did not answer')); }, ms);
          waiter = me;
        });
      }
      const HEX = Array.from({ length: 256 }, (_, i) => (i < 16 ? '0' : '') + i.toString(16));
      const toHex = a => { let s = ''; for (let i = 0; i < a.length; i++) s += HEX[a[i]]; return s; };
      const enc = new TextEncoder();
      const send = s => stm32Writer.write(enc.encode(s));

      async function sendIcl(icl, progress) {
        if (typeof ensureMainPyRunning === 'function') await ensureMainPyRunning();
        const nblocks = Math.ceil(icl.length / BLOCK);
        let p = waitFor(/^DWV:(READY|ERR)/, 30000);
        await send('@@DWV:' + FIRST_BLOCK + ':' + nblocks + '\n');
        let r = await p;
        if (!r.startsWith('DWV:READY')) throw new Error('board: ' + r);
        const order = [];
        for (let b = 1; b < nblocks; b++) order.push(b);
        order.push(0);                               // header block last
        for (let i = 0; i < order.length; i++) {
          const b = order[i];
          const blk = icl.subarray(b * BLOCK, Math.min(icl.length, (b + 1) * BLOCK));
          let ok = false;
          for (let attempt = 0; attempt < 3 && !ok; attempt++) {
            for (let s = 0; s < blk.length; s += 4096) {
              p = waitFor(/^DWV:(NEXT|ERR)/, 30000);
              await send(toHex(blk.subarray(s, s + 4096)) + '\n');
              r = await p;
              if (!r.startsWith('DWV:NEXT')) break;
            }
            p = waitFor(/^DWV:(OK|ERR)/, 30000);
            await send('@@DWB:' + b + ':' + crc32(blk) + '\n');
            ok = (await p).startsWith('DWV:OK');
          }
          if (!ok) throw new Error('part ' + (i + 1) + ' of the video failed 3 times');
          if (progress) progress(i + 1, order.length);
        }
        p = waitFor(/^DWV:DONE/, 30000);
        await send('@@DWV:END\n');
        await p;
      }

      // ---------------------------------------------------------- UI
      const say = m => { if (typeof handleBoardMessage === 'function') handleBoardMessage(m, 'SYS'); };
      const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="32">' +
        '<rect width="48" height="32" rx="4" fill="#1d2027"/>' +
        '<text x="24" y="14" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">click to</text>' +
        '<text x="24" y="25" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">choose</text></svg>');
      function pickFile() {
        return new Promise(res => {
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = 'video/*';
          input.onchange = () => res(input.files && input.files[0] ? input.files[0] : null);
          input.click();
        });
      }
      // 48 x 32 preview of a frame, with a small play sign
      function thumbOf(rgba) {
        const c = document.createElement('canvas');
        c.width = W; c.height = H;
        c.getContext('2d').putImageData(new ImageData(rgba, W, H), 0, 0);
        const t = document.createElement('canvas');
        t.width = 48; t.height = 32;
        const g = t.getContext('2d');
        g.drawImage(c, 0, 0, 48, 32);
        g.fillStyle = 'rgba(0,0,0,0.55)';
        g.beginPath(); g.arc(24, 16, 9, 0, 2 * Math.PI); g.fill();
        g.fillStyle = '#fff';
        g.beginPath(); g.moveTo(21, 11); g.lineTo(29, 16); g.lineTo(21, 21); g.closePath(); g.fill();
        return t.toDataURL('image/png');
      }
      // Click on the block's picture: choose a video and send it to the screen
      // now (only tests pass the file).
      async function pickVideo(block, file) {
        if (!block || block.isInFlyout) return;
        if (typeof stm32Port === 'undefined' || !stm32Port || !stm32Writer) {
          alert('Connect the board over USB first (the plug icon), then click the picture again.');
          return;
        }
        if (typeof _operationLock !== 'undefined' && _operationLock) {
          say('⚠️ Another operation is in progress. Please wait.');
          return;
        }
        file = file || await pickFile();
        if (!file) return;
        const work = async () => {
          try {
            say('Video: reading frames from ' + file.name + ' ...');
            const { frames, seconds, full } = await readFrames(file, (k, n) => { if (k % 32 === 0 || k === n) say('Video: frame ' + k + ' / ' + n); });
            say('Video: making the pictures ...');
            const { recs, quality } = await encodeAll(frames, null);
            const icl = buildIcl(recs, ICONS);
            const parts = Math.ceil(icl.length / BLOCK);
            const minutes = Math.max(1, Math.round(parts * 3.8 / 60));
            const clip = seconds.toFixed(1) + ' s' + (full > seconds + 0.05 ? ' (the first ' + seconds.toFixed(1) + ' s of ' + full.toFixed(1) + ' s)' : '');
            if (!confirm('Video ready: ' + frames.length + ' frames, ' + clip + ', ' + Math.round(icl.length / 1024) +
                ' KB (quality ' + quality + ').\n\nSend it to the screen now? It takes about ' + minutes +
                ' min - keep the board connected and do not press other buttons.')) { say('Video: not sent.'); return; }
            const t0 = Date.now();
            await sendIcl(icl, (i, n) => { if (i % 5 === 0 || i === n) say('Video: sent ' + i + ' / ' + n + ' parts'); });
            if (!block.isDisposed()) {
              const info = { name: file.name, frames: frames.length, seconds: seconds,
                             kb: Math.round(icl.length / 1024), thumb: thumbOf(frames[0]) };
              const oldState = JSON.stringify(block.videoInfo || null);
              block.videoInfo = info;
              block.getField('THUMB').setValue(info.thumb);
              const Change = Blockly.Events.get(Blockly.Events.BLOCK_CHANGE);
              Blockly.Events.fire(new Change(block, 'mutation', null, oldState, JSON.stringify(info)));
            }
            say('Video uploaded in ' + Math.round((Date.now() - t0) / 1000) + ' s. It plays when your program runs ' +
                'the "play video" block (on the screen also: PROJECTS LIST > VIDEO).');
          } catch (e) {
            say('Video upload failed: ' + e.message);
            alert('Video upload failed: ' + e.message);
          }
        };
        if (typeof withOpLock === 'function') await withOpLock('dwin_video', work);
        else await work();
      }

      // ---------------------------------------------------------- blocks
      function registerBlocks() {
        const COLOUR = '#5b3fd6';
        Blockly.Blocks['dwin_video_play'] = {
          init: function () {
            this.videoInfo = null;
            this.appendDummyInput()
              .appendField('🎬 play video')
              .appendField(new Blockly.FieldImage(PLACEHOLDER, 48, 32, 'click to choose a video',
                () => pickVideo(this)), 'THUMB')
              .appendField('on DWIN screen');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour(COLOUR);
            this.setTooltip('Click the picture to choose a video from your computer. It goes into the DWIN screen\'s ' +
              'own memory at once (keep the board connected; up to a few minutes). When the program runs this block, ' +
              'the screen shows the VIDEO page and plays it (it repeats). The screen keeps one video: the last one sent.');
          },
          saveExtraState: function () {
            return this.videoInfo ? Object.assign({}, this.videoInfo) : null;
          },
          loadExtraState: function (state) {
            this.videoInfo = state && state.thumb ? state : null;
            this.getField('THUMB').setValue(this.videoInfo ? this.videoInfo.thumb : PLACEHOLDER);
          },
          mutationToDom: function () {
            const m = Blockly.utils.xml.createElement('mutation');
            if (this.videoInfo) m.setAttribute('video', JSON.stringify(this.videoInfo));
            return m;
          },
          domToMutation: function (xml) {
            const s = xml.getAttribute('video');
            this.loadExtraState(s ? JSON.parse(s) : null);
          }
        };
        Blockly.Blocks['dwin_video_stop'] = {
          init: function () {
            this.appendDummyInput().appendField('⏹ stop video on DWIN screen');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour(COLOUR);
            this.setTooltip('Stops the video (its first picture stays on the screen).');
          }
        };
        const py = Blockly.Python;
        const reg = py.forBlock || py;
        reg['dwin_video_play'] = () => 'await async_dwin_video_play()\n';
        reg['dwin_video_stop'] = () => 'await async_dwin_video_stop()\n';
      }

      return { encodeFrame, buildIcl, crc32, crc16modbus, readFrames, encodeAll, sendIcl, onBoardLine,
               thumbOf, pickVideo, registerBlocks, W, H, FPS, ICONS, LIB_ID, MAX_BYTES };
    })();
