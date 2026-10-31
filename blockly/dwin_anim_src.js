      // =====================================================================
      // DWIN "play animation" block: a small GIF-style animation stored in the
      // program like the "show image" picture. Click the block's picture to
      // choose a GIF (or a short video): 32 frames, 160 ms each (5.1 s, the
      // source loops if shorter), 160 x 104, JPEG with DwinVideo's encoder, as
      // an icon library of 256 icons (frames repeat), at most ANIM_MAX bytes.
      // It goes into user.py as hex; on the first run the board copies it to
      // the display's flash (font ID 28) and page 66 plays it (lib dwin_anim).
      // =====================================================================
      (function () {
        // 32 frames x 160 ms: 32 divides the 256 icons, so the loop has no jump;
        // the display's Animation Icon controls use 8 DGUS cycles (160 ms) per frame
        const AW = 160, AH = 104, AFPS = 6.25, AFRAMES = 32, ANIM_MAX = 56 * 1024;
        const COLOUR = '#5b3fd6';
        const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
          '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="32">' +
          '<rect width="48" height="32" rx="4" fill="#1d2027"/>' +
          '<text x="24" y="14" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">click to</text>' +
          '<text x="24" y="25" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">choose GIF</text></svg>');
        const say = m => { if (typeof handleBoardMessage === 'function') handleBoardMessage(m, 'SYS'); };

        function canvas() {
          const c = document.createElement('canvas');
          c.width = AW; c.height = AH;
          return [c, c.getContext('2d', { willReadFrequently: true })];
        }
        function fit(g, src, sw, sh) {                 // letterbox into AW x AH, black bars
          g.fillStyle = '#000';
          g.fillRect(0, 0, AW, AH);
          const s = Math.min(AW / sw, AH / sh), dw = sw * s, dh = sh * s;
          g.imageSmoothingQuality = 'high';
          g.drawImage(src, (AW - dw) / 2, (AH - dh) / 2, dw, dh);
          return g.getImageData(0, 0, AW, AH).data;
        }

        // GIF / animated WebP / still image -> 16 frames (ImageDecoder in Chrome)
        async function imageFrames(file) {
          const [, g] = canvas();
          if (typeof ImageDecoder === 'undefined') {
            const bmp = await createImageBitmap(file);
            const one = fit(g, bmp, bmp.width, bmp.height);
            return Array(AFRAMES).fill(one);
          }
          const dec = new ImageDecoder({ data: await file.arrayBuffer(), type: file.type || 'image/gif' });
          await dec.tracks.ready;
          const count = Math.max(1, dec.tracks.selectedTrack.frameCount || 1);
          const imgs = [], ends = [];
          let t = 0;
          for (let i = 0; i < count && t < AFRAMES * 1000 / AFPS * 4; i++) {
            const { image } = await dec.decode({ frameIndex: i });
            t += (image.duration ? image.duration / 1000 : 100) || 100;     // microseconds -> ms
            imgs.push(fit(g, image, image.displayWidth, image.displayHeight));
            ends.push(t);
            image.close();
          }
          dec.close();
          const total = ends[ends.length - 1] || 1;
          const out = [];
          for (let k = 0; k < AFRAMES; k++) {             // the GIF's own timing, looped
            const at = (k * 1000 / AFPS) % total;
            let j = 0;
            while (j < ends.length - 1 && ends[j] <= at) j++;
            out.push(imgs[j]);
          }
          return out;
        }

        // short video -> 32 frames (first 5.1 s, looped if shorter)
        async function videoFrames(file) {
          const url = URL.createObjectURL(file);
          const v = document.createElement('video');
          v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
          const [, g] = canvas();
          try {
            await new Promise((res, rej) => {
              v.onloadeddata = res;
              v.onerror = () => rej(new Error('the browser cannot read this video (try GIF, MP4 or WebM)'));
            });
            const dur = isFinite(v.duration) && v.duration > 0 ? v.duration : AFRAMES / AFPS;
            const out = [];
            for (let k = 0; k < AFRAMES; k++) {
              const t = Math.min((k / AFPS) % dur, Math.max(0, dur - 0.05));
              await new Promise(res => {
                if (Math.abs(v.currentTime - t) < 1e-4 && v.readyState >= 2) { res(); return; }
                const done = () => { v.removeEventListener('seeked', done); res(); };
                v.addEventListener('seeked', done);
                v.currentTime = t;
              });
              out.push(fit(g, v, v.videoWidth, v.videoHeight));
            }
            return out;
          } finally {
            v.removeAttribute('src'); v.load();
            URL.revokeObjectURL(url);
          }
        }

        // frames -> icon library under ANIM_MAX: lower the quality; if still too
        // big, keep every 2nd (then 4th) frame and show each one 2 (4) times, so
        // the animation still lasts 5 s. Icon i shows record floor(i / step) % n.
        function iclOf(recs, step) {
          const count = 256, tableEnd = 16 + 4 * count, offs = [];
          let o = tableEnd;
          recs.forEach(r => { offs.push(o); o += r.length; });
          const out = new Uint8Array(o);
          out.set([0x44, 0x47, 0x55, 0x53, 0x5F, 0x33], 0);
          const be32 = (p, v) => { out[p] = (v >>> 24) & 255; out[p + 1] = (v >>> 16) & 255; out[p + 2] = (v >>> 8) & 255; out[p + 3] = v & 255; };
          be32(8, o - 8);
          out[12] = 4; out[13] = 0;
          out[14] = (count - 1) & 255; out[15] = (count - 1) >> 8;
          for (let i = 0; i < count; i++) be32(16 + 4 * i, offs[Math.floor(i / step) % recs.length]);
          recs.forEach((r, i) => out.set(r, offs[i]));
          const c = DwinVideo.crc16modbus(out.subarray(8));
          out[6] = c & 255; out[7] = c >> 8;
          return out;
        }
        function pack(frames) {
          for (const step of [1, 2, 4]) {
            const use = frames.filter((_, i) => i % step === 0);
            for (const q of [60, 45, 32, 22, 15]) {
              const icl = iclOf(use.map(f => DwinVideo.encodeFrame(f, AW, AH, q)), step);
              if (icl.length <= ANIM_MAX) return { icl, quality: q, frames: use.length };
            }
          }
          throw new Error('this animation has too much detail to fit - try a simpler GIF');
        }
        function toHex(bytes) {
          const parts = new Array(bytes.length);
          for (let i = 0; i < bytes.length; i++) parts[i] = (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16);
          return parts.join('');
        }
        function tagOf(hex) {
          let h = 2166136261;
          for (let i = 0; i < hex.length; i += 3) h = Math.imul(h ^ hex.charCodeAt(i), 16777619) >>> 0;
          return (h >>> 0).toString(16) + (hex.length >>> 1).toString(16);
        }
        function thumb(rgba) {
          const [c, g] = canvas();
          g.putImageData(new ImageData(new Uint8ClampedArray(rgba), AW, AH), 0, 0);
          const t = document.createElement('canvas');
          t.width = 48; t.height = 32;
          t.getContext('2d').drawImage(c, 0, 0, 48, 32);
          return t.toDataURL('image/png');
        }

        async function makeAnim(file) {
          const isVideo = (file.type || '').startsWith('video/');
          const frames = isVideo ? await videoFrames(file) : await imageFrames(file);
          const p = pack(frames);
          const hex = toHex(p.icl);
          return { hex, bytes: p.icl.length, frames: p.frames, quality: p.quality, tag: tagOf(hex),
                   thumb: thumb(frames[0]), name: file.name };
        }

        function pickAnim(block) {
          if (!block || block.isInFlyout) return;
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = 'image/gif,image/webp,image/png,video/*';
          input.onchange = async () => {
            const f = input.files && input.files[0];
            if (!f) return;
            try {
              say('Animation: making frames from ' + f.name + ' ...');
              const data = await makeAnim(f);
              const oldState = JSON.stringify(block.animData || null);
              block.animData = data;
              block.getField('THUMB').setValue(data.thumb);
              const Change = Blockly.Events.get(Blockly.Events.BLOCK_CHANGE);
              Blockly.Events.fire(new Change(block, 'mutation', null, oldState, JSON.stringify(data)));
              say('Animation ready: ' + f.name + ' - ' + data.frames + ' frames, ' + Math.round(data.bytes / 1024) +
                  ' KB (quality ' + data.quality + '). It goes with the program; the first run copies it to the screen (about 10 s).');
            } catch (e) {
              alert('Could not make an animation from that file: ' + e.message);
            }
          };
          input.click();
        }

        const SLOTS = [['1', '1'], ['2', '2'], ['3', '3']];
        const holdsAnim = {                              // blocks that carry an animation picture
          saveExtraState: function () { return this.animData ? Object.assign({}, this.animData) : null; },
          loadExtraState: function (state) {
            this.animData = state && state.hex ? state : null;
            this.getField('THUMB').setValue(this.animData ? this.animData.thumb : PLACEHOLDER);
          },
          mutationToDom: function () {
            const m = Blockly.utils.xml.createElement('mutation');
            if (this.animData) m.setAttribute('anim', JSON.stringify(this.animData));
            return m;
          },
          domToMutation: function (xml) {
            const s = xml.getAttribute('anim');
            this.loadExtraState(s ? JSON.parse(s) : null);
          }
        };
        Blockly.Blocks['dwin_anim_save'] = Object.assign({
          init: function () {
            this.animData = null;
            this.appendDummyInput()
              .appendField('💾 save animation')
              .appendField(new Blockly.FieldImage(PLACEHOLDER, 48, 32, 'click to choose a GIF', () => pickAnim(this)), 'THUMB')
              .appendField('to DWIN memory')
              .appendField(new Blockly.FieldDropdown(SLOTS), 'SLOT');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour(COLOUR);
            this.setTooltip('Click the picture to choose a GIF (or a short video). The run saves it into animation ' +
              'memory 1, 2 or 3 of the DWIN screen (about 10 s; skipped if it is already there). It stays after ' +
              'power-off and shows in STORAGE > ANIMATIONS.');
          }
        }, holdsAnim);
        Blockly.Blocks['dwin_anim_show'] = {
          init: function () {
            this.appendDummyInput()
              .appendField('▶ play saved animation')
              .appendField(new Blockly.FieldDropdown(SLOTS), 'SLOT')
              .appendField('on DWIN screen');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour(COLOUR);
            this.setTooltip('Plays an animation saved with "save animation to DWIN memory". It starts at once, ' +
              'because the animation is already inside the screen.');
          }
        };
        Blockly.Blocks['dwin_anim_play'] = {
          init: function () {
            this.animData = null;
            this.appendDummyInput()
              .appendField('🎞 play animation')
              .appendField(new Blockly.FieldImage(PLACEHOLDER, 48, 32, 'click to choose a GIF', () => pickAnim(this)), 'THUMB')
              .appendField('on DWIN screen');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setColour(COLOUR);
            this.setTooltip('Click the picture to choose a GIF (or a short video). A small 5-second animation is saved in ' +
              'the program like a picture. The first run copies it to the DWIN screen (about 10 s), then it plays ' +
              'on the ANIMATION page and repeats; later runs start at once.');
          },
          saveExtraState: function () { return this.animData ? Object.assign({}, this.animData) : null; },
          loadExtraState: function (state) {
            this.animData = state && state.hex ? state : null;
            this.getField('THUMB').setValue(this.animData ? this.animData.thumb : PLACEHOLDER);
          },
          mutationToDom: function () {
            const m = Blockly.utils.xml.createElement('mutation');
            if (this.animData) m.setAttribute('anim', JSON.stringify(this.animData));
            return m;
          },
          domToMutation: function (xml) {
            const s = xml.getAttribute('anim');
            this.loadExtraState(s ? JSON.parse(s) : null);
          }
        };
        const py = Blockly.Python;
        const reg = py.forBlock || py;
        function animConst(d) {                          // the animation as a user.py constant
          const name = '_dw_anim_' + d.tag;
          const parts = [];
          for (let i = 0; i < d.hex.length; i += 4096) parts.push("    '" + d.hex.slice(i, i + 4096) + "',");
          py.definitions_[name] = name + " = ('" + d.tag + "', " + d.bytes + ", (\n" + parts.join("\n") + "\n))";
          return name;
        }
        reg['dwin_anim_play'] = function (b) {
          const d = b.animData;
          if (!d || !d.hex) return "print('play animation block: no animation chosen')\n";
          return 'await async_dwin_anim(' + animConst(d) + ')\n';
        };
        reg['dwin_anim_save'] = function (b) {
          const d = b.animData;
          if (!d || !d.hex) return "print('save animation block: no animation chosen')\n";
          return 'await async_dwin_anim_save(' + (Number(b.getFieldValue('SLOT')) || 1) + ', ' + animConst(d) + ')\n';
        };
        reg['dwin_anim_show'] = function (b) {
          return 'await async_dwin_anim_show(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\n';
        };
        window.DwinAnim = { makeAnim, pack, AW, AH, AFRAMES, ANIM_MAX };   // for tests
      })();
