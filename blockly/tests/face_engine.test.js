const fs=require('fs');
const html=fs.readFileSync('face.html','utf8');
const code=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/.exec(html)[1];

// ── minimal DOM / env stubs ────────────────────────────────────────
const store={};
const mkEl=(id)=>({id,value:'',textContent:'',innerHTML:'',style:{},checked:false,
  className:'',options:{length:0},width:640,height:480,
  classList:{toggle(){},add(){},remove(){}},
  appendChild(){},getContext(){return new Proxy({},{get:()=>()=>{}}); },
  addEventListener(){}, removeAttribute(){}, setAttribute(){}, measureText:()=>({width:10})});
const els={};
global.document={getElementById:id=>(els[id]||(els[id]=mkEl(id))),
  createElement:t=>mkEl(t),querySelector:()=>null};
global.window={_h:{},addEventListener(t,f){(this._h[t]=this._h[t]||[]).push(f);},removeEventListener(){},postMessage(){}};
global.localStorage={getItem:k=>store[k]||null,setItem:(k,v)=>store[k]=v,removeItem:k=>delete store[k]};
global.navigator={mediaDevices:{getUserMedia:async()=>({getTracks:()=>[]})}};
global.location={search:''};
global.isSecureContext=true;
global.window.isSecureContext=true;
global.performance={now:()=>Date.now()};
global.URL={createObjectURL:()=>'blob:x'};
global.confirm=()=>true;
const net={loadFromUri:async()=>{}};
global.faceapi={nets:{tinyFaceDetector:net,faceLandmark68Net:net,faceExpressionNet:net,faceRecognitionNet:net},
  TinyFaceDetectorOptions:function(){}, LabeledFaceDescriptors:function(l,d){this.label=l;this.descriptors=d;},
  FaceMatcher:function(labelled,thr){
    this.findBestMatch=(desc)=>{
      let best={label:'unknown',distance:1};
      for(const L of labelled) for(const d of L.descriptors){
        let s=0; for(let i=0;i<d.length;i++) s+=(d[i]-desc[i])**2;
        const dist=Math.sqrt(s);
        if(dist<best.distance) best={label:L.label,distance:dist};
      }
      return best.distance<=thr?best:{label:'unknown',distance:best.distance};
    };
  },
  detectAllFaces:()=>{throw new Error('stub');}
};
global.setInterval=()=>0; global.clearInterval=()=>{};

eval(code);

// ── helpers to inject a fake analysed frame ────────────────────────
const F=global.window.FaceBlocks;
let pass=0,fail=0;
const t=(name,cond)=>{ if(cond){pass++;console.log('  PASS',name);} else {fail++;console.log('  FAIL',name);} };

console.log('\n1) no analysis yet -> safe defaults, no crash');
t('count is 0', F.getFaceCount()===0);
t('expression is empty', F.getExpression(1)==='');
t('isExpression false', F.isExpression(1,'happy')===false);
t('position 0', F.getFacePosition(1,'x')===0);
t('part position 0', F.getPartPosition(1,'nose','x')===0);
t('landmark position 0', F.getLandmarkPosition(1,31,'x')===0);
t('isClassDetected false', F.isClassDetected(1)===false);
t('getClassOfFace empty', F.getClassOfFace(1)==='');
t('analysisId 0 (stale guard)', F.analysisId===0);

// Build a fake detection result: two faces, RIGHT one supplied first, so
// ordering has to actually sort them left->right.
function mkFace(x, expr, descSeed){
  const pts=[]; for(let i=0;i<68;i++) pts.push({x:x+i, y:100+i});
  const ex={neutral:0.1,happy:0.1,sad:0.1,angry:0.1,surprised:0.1,disgusted:0.1,fearful:0.1};
  ex[expr]=0.9;
  const L={positions:pts, getLeftEye:()=>[pts[36],pts[37]],getRightEye:()=>[pts[42],pts[43]],
           getMouth:()=>[pts[48],pts[54]],getLeftEyeBrow:()=>[pts[17]],getRightEyeBrow:()=>[pts[22]]};
  return {detection:{box:{x, y:100, width:100, height:100}},
          landmarks:L, expressions:ex,
          descriptor:new Float32Array(128).fill(descSeed)};
}
global.faceapi.detectAllFaces=()=>{const c={
  withFaceLandmarks(){return this;},withFaceExpressions(){return this;},
  withFaceDescriptors(){return this;},
  then(res){res([mkFace(400,'sad',0.9), mkFace(100,'happy',0.1)]);}
}; return c;};

(async()=>{
  await new Promise(r=>setTimeout(r,50));  // let loadModels() finish
  console.log('\n2) ordering, indexing, coordinates');
  await F.analyseImage();
  t('two faces found', F.getFaceCount()===2);
  t('face 1 is LEFT-most (happy at x=100)', F.getExpression(1)==='happy');
  t('face 2 is right-most (sad at x=400)', F.getExpression(2)==='sad');
  t('face numbering is 1-based, face 0 empty', F.getExpression(0)==='');
  t('face 3 out of range -> empty', F.getExpression(3)==='');
  t('analysisId advanced', F.analysisId===1);

  console.log('\n3) expression name mapping (model -> block vocabulary)');
  global.faceapi.detectAllFaces=()=>({withFaceLandmarks(){return this;},
    withFaceExpressions(){return this;},withFaceDescriptors(){return this;},
    then(res){res([mkFace(10,'disgusted',0.5)]);}});
  await F.analyseImage();
  t('disgusted -> "disgust"', F.getExpression(1)==='disgust');
  t('isExpression("disgust") true', F.isExpression(1,'disgust')===true);
  global.faceapi.detectAllFaces=()=>({withFaceLandmarks(){return this;},
    withFaceExpressions(){return this;},withFaceDescriptors(){return this;},
    then(res){res([mkFace(10,'fearful',0.5)]);}});
  await F.analyseImage();
  t('fearful -> "fear"', F.getExpression(1)==='fear');

  console.log('\n4) landmark indexing is 1-based (block 7)');
  const l1=F.getLandmarkPosition(1,1,'x'), l31=F.getLandmarkPosition(1,31,'x');
  t('landmark 1 != landmark 31', l1!==l31);
  t('landmark 0 -> 0 (out of range)', F.getLandmarkPosition(1,0,'x')===0);
  t('landmark 69 -> 0 (out of range)', F.getLandmarkPosition(1,69,'x')===0);
  t('nose part == landmark 31', F.getPartPosition(1,'nose','x')===F.getLandmarkPosition(1,31,'x'));

  console.log('\n4b) detection WITHOUT landmarks must not crash');
  global.faceapi.detectAllFaces=()=>({withFaceLandmarks(){return this;},
    withFaceExpressions(){return this;},withFaceDescriptors(){return this;},
    then(res){res([{detection:{box:{x:1,y:1,width:9,height:9}},landmarks:null,
      expressions:{neutral:0.9},descriptor:new Float32Array(128).fill(0.5)}]);}});
  await F.analyseImage();
  let threw=false;
  try{ F.getLandmarkPosition(1,31,'x'); F.getPartPosition(1,'nose','x'); }catch(e){threw=true;}
  t('no throw when landmarks missing', threw===false);
  t('landmark falls back to 0', F.getLandmarkPosition(1,31,'x')===0);
  t('part falls back to 0', F.getPartPosition(1,'nose','x')===0);
  global.faceapi.detectAllFaces=()=>({withFaceLandmarks(){return this;},
    withFaceExpressions(){return this;},withFaceDescriptors(){return this;},
    then(res){res([mkFace(10,'happy',0.5)]);}});
  await F.analyseImage();

  console.log('\n5) recognition (blocks 8-12)');
  t('before matching, isClassDetected false', F.isClassDetected(1)===false);
  const add=await F.addClass(1,'Jarvis','camera');
  t('addClass ok', add.ok===true && add.name==='Jarvis' && add.samples===1);
  const m=await F.doFaceMatching('camera');
  t('matching returns per-face array', Array.isArray(m) && m.length===1);
  t('class 1 detected', F.isClassDetected(1)===true);
  t('getClassOfFace -> Jarvis', F.getClassOfFace(1)==='Jarvis');
  t('untrained class 2 not detected', F.isClassDetected(2)===false);

  console.log('\n6) reset class (block 9)');
  F.resetClass();
  t('classes cleared', Object.keys(F.classes).length===0);
  t('isClassDetected false after reset', F.isClassDetected(1)===false);
  t('getClassOfFace empty after reset', F.getClassOfFace(1)==='');

  console.log('\n7) RPC bridge (used by "Test Face" in the workspace)');
  const handler = global.window._h['message'][0];
  const replies = [];
  const send = (fn, args) => new Promise(res => {
    const id = Math.random();
    replies.push(res);
    handler({ data: { type:'FACE_RPC', id, fn, args },
              source: { postMessage: m => { replies.shift()(m); } } });
  });

  const pong = await send('ping', []);
  t('ping responds ok', pong.ok===true && pong.value==='pong');

  const unknown = await send('totallyNotAThing', []);
  t('unknown call rejected, not thrown', unknown.ok===false && /unknown call/.test(unknown.error));

  const cnt = await send('analyseImage', ['camera']);
  t('analyseImage returns a face count (clonable)', cnt.ok===true && typeof cnt.value==='number');

  const expr = await send('getExpression', [1]);
  t('getExpression over RPC', expr.ok===true && typeof expr.value==='string');

  await send('addClass', [1,'Jarvis','camera']);
  const match = await send('doFaceMatching', ['camera']);
  t('doFaceMatching returns plain strings', match.ok===true
      && Array.isArray(match.value)
      && match.value.every(v => typeof v==='string'));
  t('no typed arrays cross the boundary',
      JSON.stringify(match.value).indexOf('Float32')===-1);

  const isc = await send('isClassDetected', [1]);
  t('isClassDetected over RPC', isc.ok===true && isc.value===true);

  await send('resetClass', []);
  const isc2 = await send('isClassDetected', [1]);
  t('resetClass over RPC clears it', isc2.value===false);

  console.log('\n8) readiness protocol (getReady / startCamera)');
  const ready = await send('getReady', []);
  t('getReady replies immediately', ready.ok===true && typeof ready.value==='object');
  t('reports models flag', typeof ready.value.models==='boolean');
  t('reports camera flag', typeof ready.value.camera==='boolean');
  t('reports source', typeof ready.value.source==='string');
  t('reports hasImage', typeof ready.value.hasImage==='boolean');

  // The old ensureCamera awaited the permission prompt inside one RPC, so a
  // slow answer blew the timeout. startCamera must return without waiting.
  let returnedFast = false;
  const t0 = Date.now();
  const sc = await send('startCamera', []);
  returnedFast = (Date.now() - t0) < 500;
  t('startCamera returns without awaiting the prompt', sc.ok===true && returnedFast);
  t('the removed blocking call is gone', (await send('ensureCamera', [])).ok===false);

  console.log(`\n==== ${pass} passed, ${fail} failed ====`);
  process.exit(fail?1:0);
})();
