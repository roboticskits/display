    // =====================================================================
    // DWIN SCREEN BLOCKS  (image on the DWIN DMG48320C035 display, UART1)
    //
    // "show image" holds a picture chosen with the file picker. The picture
    // is shrunk to 160 x 106, packed as RGB565 (zlib-compressed when that is
    // smaller) and written into user.py as lowercase hex, so it travels with
    // the normal UPLOAD. On the board the helper below draws it on display
    // page 39 (two Basic Graphic controls, 3 x 3 dots per pixel, about 9 s).
    // Generated Python must never contain the words the board's main.py
    // reacts to (S-T-O-P, P-L-A-Y, U-P-L-O-A-D, and "disPLAY" in capitals).
    // =====================================================================
    function defineDwinImageBlocks() {
      const IMG_W = 160, IMG_H = 106;
      const COLOUR = '#5b3fd6';
      const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="32">' +
        '<rect width="48" height="32" rx="4" fill="#1d2027"/>' +
        '<text x="24" y="14" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">click to</text>' +
        '<text x="24" y="25" font-size="8" fill="#c9cdd6" text-anchor="middle" font-family="sans-serif">choose</text></svg>');

      // ---------------------------------------------------------- image packing
      async function deflateBytes(bytes) {
        if (typeof CompressionStream === 'undefined') return null;
        const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate'));
        return new Uint8Array(await new Response(stream).arrayBuffer());
      }
      function toHex(bytes) {
        const parts = new Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) parts[i] = (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16);
        return parts.join('');
      }
      async function packImage(bitmap) {
        const c = document.createElement('canvas');
        c.width = IMG_W;
        c.height = IMG_H;
        const g = c.getContext('2d');
        g.fillStyle = '#000';
        g.fillRect(0, 0, IMG_W, IMG_H);
        const s = Math.min(IMG_W / bitmap.width, IMG_H / bitmap.height);
        const dw = bitmap.width * s, dh = bitmap.height * s;
        g.imageSmoothingQuality = 'high';
        g.drawImage(bitmap, (IMG_W - dw) / 2, (IMG_H - dh) / 2, dw, dh);
        const d = g.getImageData(0, 0, IMG_W, IMG_H).data;
        const px = new Uint8Array(IMG_W * IMG_H * 2);
        for (let i = 0, j = 0; i < d.length; i += 4, j += 2) {
          const v = ((d[i] & 0xf8) << 8) | ((d[i + 1] & 0xfc) << 3) | (d[i + 2] >> 3);
          px[j] = v >> 8;
          px[j + 1] = v & 0xff;
        }
        let enc = 0, payload = px;
        try {
          const z = await deflateBytes(px);
          if (z && z.length < px.length * 0.9) { enc = 1; payload = z; }
        } catch (e) { console.warn('deflate failed, sending raw', e); }
        const t = document.createElement('canvas');
        t.width = 48;
        t.height = 32;
        t.getContext('2d').drawImage(c, 0, 0, 48, 32);
        return { w: IMG_W, h: IMG_H, enc: enc, hex: toHex(payload), thumb: t.toDataURL('image/png') };
      }
      function pickImage(block) {
        if (!block || block.isInFlyout) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.onchange = async () => {
          const f = input.files && input.files[0];
          if (!f) return;
          try {
            const bmp = await createImageBitmap(f);
            const data = await packImage(bmp);
            const oldState = JSON.stringify(block.imgData || null);
            block.imgData = data;
            block.getField('THUMB').setValue(data.thumb);
            const Change = Blockly.Events.get(Blockly.Events.BLOCK_CHANGE);
            Blockly.Events.fire(new Change(block, 'mutation', null, oldState, JSON.stringify(data)));
            const kb = (data.hex.length / 1024).toFixed(0);
            if (typeof handleBoardMessage === 'function') {
              handleBoardMessage('Image ready: ' + f.name + ' (' + kb + ' KB in the upload)', 'SYS');
            }
          } catch (e) {
            alert('Could not read that image: ' + e.message);
          }
        };
        input.click();
      }

      defineDwinImageBlocks.packImage = packImage;   // for tests

      // ---------------------------------------------------------- blocks
      Blockly.Blocks['dwin_show_image'] = {
        init: function () {
          this.imgData = null;
          this.appendDummyInput()
            .appendField('🖼️ show image')
            .appendField(new Blockly.FieldImage(PLACEHOLDER, 48, 32, 'click to choose an image',
              () => pickImage(this)), 'THUMB')
            .appendField('on DWIN screen');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Click the picture to choose an image from your computer. It is sent with the ' +
            'program and drawn on the DWIN screen (about 9 seconds).');
        },
        saveExtraState: function () {
          return this.imgData ? Object.assign({}, this.imgData) : null;
        },
        loadExtraState: function (state) {
          this.imgData = state && state.hex ? state : null;
          this.getField('THUMB').setValue(this.imgData ? this.imgData.thumb : PLACEHOLDER);
        },
        mutationToDom: function () {
          const m = Blockly.utils.xml.createElement('mutation');
          if (this.imgData) m.setAttribute('img', JSON.stringify(this.imgData));
          return m;
        },
        domToMutation: function (xml) {
          const s = xml.getAttribute('img');
          this.loadExtraState(s ? JSON.parse(s) : null);
        }
      };
      Blockly.Blocks['dwin_clear_image'] = {
        init: function () {
          this.appendDummyInput().appendField('🧽 clear image on DWIN screen');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Removes the picture drawn by "show image".');
        }
      };
      Blockly.Blocks['dwin_page'] = {
        init: function () {
          this.appendDummyInput()
            .appendField('📄 DWIN screen page')
            .appendField(new Blockly.FieldNumber(10, 0, 255, 1), 'PAGE');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Switches the DWIN screen to a page: 10 = home, 15-38 = bird faces ' +
            '(happy 15, sad 18, angry 21, surprised 24, love 27, sleepy 30, excited 33, curious 36), 39 = image page.');
        }
      };
      const SLOTS = [['1', '1'], ['2', '2'], ['3', '3']];
      Blockly.Blocks['dwin_save_slot'] = {
        init: function () {
          this.appendDummyInput()
            .appendField('💾 save picture on DWIN screen to memory')
            .appendField(new Blockly.FieldDropdown(SLOTS), 'SLOT');
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(COLOUR);
          this.setTooltip('Saves the picture now on the DWIN image page into the screen\'s own memory ' +
            '(1, 2 or 3) and updates the PROJECTS LIST pages. It stays there after power-off. Takes about 10-20 seconds.');
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

      // ---------------------------------------------------------- board side
      // The Python behind these blocks is in the board's lib.py (section
      // "DWIN SMART DISPLAY": dwin_image / dwin_clear / dwin_page and their
      // async_ versions). user.py only gets the picture data and the call.

      // ---------------------------------------------------------- generators
      const py = Blockly.Python;
      const reg = py.forBlock || py;
      function shortHash(s) {
        let h = 2166136261;
        for (let i = 0; i < s.length; i += 7) h = Math.imul(h ^ s.charCodeAt(i), 16777619) >>> 0;
        return (h >>> 0).toString(16);
      }
      reg['dwin_show_image'] = function (b) {
        const d = b.imgData;
        if (!d || !d.hex) return "print('show image block: no image chosen')\n";
        const name = '_dw_img_' + shortHash(d.hex);
        // the picture as short strings: one long literal needs one large free
        // block on the board when user.py is imported
        const parts = [];
        for (let i = 0; i < d.hex.length; i += 4096) parts.push("    '" + d.hex.slice(i, i + 4096) + "',");
        py.definitions_[name] = name + " = (" + d.w + ", " + d.h + ", " + d.enc + ", (\n" + parts.join("\n") + "\n))";
        return 'await async_dwin_image(' + name + ')\n';
      };
      reg['dwin_clear_image'] = function () {
        return 'await async_dwin_clear()\n';
      };
      reg['dwin_page'] = function (b) {
        return 'await async_dwin_page(' + (Number(b.getFieldValue('PAGE')) || 0) + ')\n';
      };
      reg['dwin_save_slot'] = function (b) {
        return 'await async_dwin_save(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\n';
      };
      reg['dwin_show_slot'] = function (b) {
        return 'await async_dwin_show_saved(' + (Number(b.getFieldValue('SLOT')) || 1) + ')\n';
      };
    }
