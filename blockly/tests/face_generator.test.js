/*
 * Verifies the JavaScript generators used by "Test Face".
 *
 * Loads the real Blockly 12.5.1 core + JS generator from offline_libs, defines
 * the face blocks, builds a headless workspace and checks the emitted code.
 * The point is to catch a generator that silently produces nothing, or that
 * aborts the whole program when it meets a board-only hardware block.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const LIB = path.join(__dirname, '..', 'offline_libs', 'blockly');

// Blockly's UMD build wants a browser-ish global; a headless Workspace needs
// very little of it.
const sandbox = {
  console, setTimeout, clearTimeout, setInterval, clearInterval,
  navigator: { userAgent: 'node', platform: 'node' },
  performance: { now: () => Date.now() },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

function load(file) {
  vm.runInContext(fs.readFileSync(path.join(LIB, file), 'utf8'), sandbox, { filename: file });
}
load('blockly_compressed.js');
load('blocks_compressed.js');
load('javascript_compressed.js');

const Blockly = sandbox.Blockly;
const jsGen = (sandbox.javascript && sandbox.javascript.javascriptGenerator)
  || (Blockly.JavaScript);

let pass = 0, fail = 0;
const t = (name, cond) => { cond ? (pass++, console.log('  PASS', name)) : (fail++, console.log('  FAIL', name)); };

console.log('\n1) libraries load headlessly');
t('Blockly core present', !!Blockly && typeof Blockly.Workspace === 'function');
t('JavaScript generator present', !!jsGen && typeof jsGen.workspaceToCode === 'function');
t('generator uses forBlock registry', !!jsGen.forBlock);

// ── Face blocks, same shape as index.html defines them ──────────────
Blockly.defineBlocksWithJsonArray([
  {
    type: 'face_analyse', message0: 'analyse image from %1',
    args0: [{ type: 'field_dropdown', name: 'SRC', options: [['camera', 'camera'], ['image', 'image']] }],
    previousStatement: null, nextStatement: null, colour: '#0d9488',
  },
  { type: 'face_count', message0: 'get # faces', output: 'Number', colour: '#0d9488' },
  {
    type: 'face_is_expression', message0: 'is expression of face %1 %2 ?',
    args0: [
      { type: 'field_number', name: 'FACE', value: 1 },
      { type: 'field_dropdown', name: 'EXPR', options: [['happy', 'happy'], ['sad', 'sad']] }],
    output: 'Boolean', colour: '#0d9488',
  },
  {
    type: 'face_landmark_position', message0: 'get %1 of landmark %2 of face %3',
    args0: [
      { type: 'field_dropdown', name: 'AXIS', options: [['x position', 'x'], ['y position', 'y']] },
      { type: 'field_number', name: 'INDEX', value: 31 },
      { type: 'field_number', name: 'FACE', value: 1 }],
    output: 'Number', colour: '#0d9488',
  },
  {
    type: 'face_add_class', message0: 'add class %1 as %2 from %3',
    args0: [
      { type: 'field_number', name: 'CLASSNO', value: 1 },
      { type: 'field_input', name: 'NAME', text: 'Jarvis' },
      { type: 'field_dropdown', name: 'SRC', options: [['camera', 'camera']] }],
    previousStatement: null, nextStatement: null, colour: '#0d9488',
  },
  // Stands in for a servo/motor block: no JS generator anywhere.
  {
    type: 'board_only_block', message0: 'board only thing',
    previousStatement: null, nextStatement: null, colour: '#999',
  },
]);

// ── The generators, copied in shape from index.html ─────────────────
const G = jsGen.forBlock;
const S = s => JSON.stringify(String(s == null ? '' : s));
const ORDER_AWAIT = jsGen.ORDER_AWAIT !== undefined ? jsGen.ORDER_AWAIT : 0;

G['face_analyse'] = b => `await FaceRT.call('analyseImage', ${S(b.getFieldValue('SRC'))});\n`;
G['face_count'] = () => [`await FaceRT.call('getFaceCount')`, ORDER_AWAIT];
G['face_is_expression'] = b =>
  [`await FaceRT.call('isExpression', ${b.getFieldValue('FACE')}, ${S(b.getFieldValue('EXPR'))})`, ORDER_AWAIT];
G['face_landmark_position'] = b =>
  [`await FaceRT.call('getLandmarkPosition', ${b.getFieldValue('FACE')}, ${b.getFieldValue('INDEX')}, ${S(b.getFieldValue('AXIS'))})`, ORDER_AWAIT];
G['face_add_class'] = b =>
  `await FaceRT.call('addClass', ${b.getFieldValue('CLASSNO')}, ${S(b.getFieldValue('NAME'))}, ${S(b.getFieldValue('SRC'))});\n`;

const KNOWN = new Set(Object.keys(G));
jsGen.blockToCode_orig = jsGen.blockToCode_orig || jsGen.blockToCode;
jsGen.blockToCode = function (block, opt_thisOnly) {
  if (block && !KNOWN.has(block.type) && !jsGen.forBlock[block.type]) {
    const skip = `FaceRT.skip(${S(block.type)});\n`;
    return block.outputConnection ? ['0', ORDER_AWAIT] : skip;
  }
  return jsGen.blockToCode_orig.call(this, block, opt_thisOnly);
};

// ── Build a headless program ────────────────────────────────────────
// Block creation fires a BlockCreate event, which serialises to DOM and needs
// a real document. Code generation does not, so switch events off.
Blockly.Events.disable();
const ws = new Blockly.Workspace();

console.log('\n2) simple statement block');
const a = ws.newBlock('face_analyse');
a.setFieldValue('camera', 'SRC');
let code = jsGen.workspaceToCode(ws);
t('emits an awaited analyseImage', /await FaceRT\.call\('analyseImage', "camera"\)/.test(code));

console.log('\n3) value blocks inside an if');
const iff = ws.newBlock('controls_if');
const cond = ws.newBlock('face_is_expression');
cond.setFieldValue('1', 'FACE');
cond.setFieldValue('happy', 'EXPR');
iff.getInput('IF0').connection.connect(cond.outputConnection);
a.nextConnection.connect(iff.previousConnection);
code = jsGen.workspaceToCode(ws);
t('if wraps the awaited condition', /if\s*\(await FaceRT\.call\('isExpression', 1, "happy"\)\)/.test(code));
t('order kept: analyse before the if', code.indexOf('analyseImage') < code.indexOf('isExpression'));

console.log('\n4) field values reach the call verbatim');
const lm = ws.newBlock('face_landmark_position');
lm.setFieldValue('y', 'AXIS'); lm.setFieldValue('31', 'INDEX'); lm.setFieldValue('2', 'FACE');
const c4 = jsGen.blockToCode(lm)[0];
t('landmark args in order (face, index, axis)',
  /getLandmarkPosition', 2, 31, "y"/.test(c4));

console.log('\n5) free text is escaped, not interpolated raw');
const ac = ws.newBlock('face_add_class');
ac.setFieldValue('He said "hi"', 'NAME');
const c5 = jsGen.blockToCode(ac);
t('quotes in a class name are escaped', c5.includes('\\"hi\\"'));
t('escaped name cannot break the call', (c5.match(/"/g) || []).length % 2 === 0);

console.log('\n6) a board-only block must not abort the program');
const hw = ws.newBlock('board_only_block');
iff.nextConnection.connect(hw.previousConnection);
let threw = false, code6 = '';
try { code6 = jsGen.workspaceToCode(ws); } catch (e) { threw = true; console.log('   threw:', e.message); }
t('workspaceToCode did not throw', threw === false);
t('hardware block became a logged skip', /FaceRT\.skip\("board_only_block"\)/.test(code6));
t('face logic still emitted alongside it', /analyseImage/.test(code6) && /isExpression/.test(code6));

console.log('\n7) generated code is syntactically valid JS');
let syntaxOk = true, syntaxErr = '';
try {
  new Function('FaceRT', 'FaceTest', '"use strict"; return (async () => {\n' + code6 + '\n})();');
} catch (e) { syntaxOk = false; syntaxErr = e.message; }
t('wraps into a runnable async function', syntaxOk || (console.log('   ' + syntaxErr), false));

console.log(`\n==== ${pass} passed, ${fail} failed ====`);
process.exit(fail ? 1 : 0);
