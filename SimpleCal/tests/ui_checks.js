/* 在轻量 DOM 测试替身中执行最终 HTML 的全部脚本与事件处理器；不替代浏览器视觉检查。 */
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const data = new Map();
const downloads=[];
const storage = { getItem:key=>data.get(key) ?? null, setItem:(key,value)=>data.set(key,value) };
function mount() {
  class Element {
    constructor(tag='div',attrs={}) {
      this.tagName=tag; this.attrs={...attrs}; this.children=[]; this.listeners={}; this.dataset={};
      this.hidden='hidden' in attrs; this.disabled='disabled' in attrs; this.checked='checked' in attrs;
      this.value=attrs.value || ''; this.className=attrs.class || ''; this.textContent='';
      this.style={setProperty(name,value){this[name]=value}};
      for (const [key,value] of Object.entries(attrs)) if(key.startsWith('data-')) this.dataset[key.slice(5)]=value;
      this.classList={contains:name=>this.className.split(' ').includes(name),toggle:(name,on)=>{
        const values=new Set(this.className.split(' ').filter(Boolean));
        if(on===undefined) on=!values.has(name); if(on) values.add(name); else values.delete(name);
        this.className=[...values].join(' ');
      },add:name=>this.classList.toggle(name,true)};
    }
    append(...items){this.children.push(...items)}
    replaceChildren(...items){this.children=[...items]}
    setAttribute(name,value){this.attrs[name]=value}
    getAttribute(name){return this.attrs[name] ?? null}
    removeAttribute(name){delete this.attrs[name]}
    addEventListener(name,fn){this.listeners[name]=fn}
    focus(){}
    showModal(){this.open=true}
    close(){this.open=false}
    fire(name='click'){assert.ok(this.listeners[name],`Missing ${name} handler`); return this.listeners[name]({preventDefault(){},target:this})}
    querySelector(selector){return this.optionsMap?.[selector]}
    click(){downloads.push({href:this.href,name:this.download})}
    remove(){}
  }
  const elements=[], ids=new Map();
  for (const match of html.split('<script')[0].matchAll(/<([a-z][a-z0-9-]*)(\s[^>]*|)>/g)) {
    const attrs={};
    for (const a of match[2].matchAll(/([a-z][a-z0-9-]*)(?:="([^"]*)")?/g)) attrs[a[1]]=a[2] ?? '';
    const element=new Element(match[1],attrs); elements.push(element);
    if(attrs.id) { assert.ok(!ids.has(attrs.id),`Duplicate id ${attrs.id}`); ids.set(attrs.id,element); }
  }
  const byId=id=>{assert.ok(ids.has(id),`Unknown element ${id}`);return ids.get(id)};
  for (const match of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>(.*?)<\/select>/gs)) {
    const opts=[...match[2].matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/gs)];
    const selected=opts.find(x=>x[2].includes('selected')) || opts[0];
    byId(match[1]).value=selected[1]; byId(match[1]).selectedOptions=[{text:selected[3]}];
    byId(match[1]).optionsMap=Object.fromEntries(opts.map(x=>[`option[value="${x[1]}"]`,new Element('option')]));
  }
  const document={body:new Element('body'),createElement:tag=>new Element(tag),getElementById:byId,
    querySelector(selector){if(selector==='.brand')return elements.find(x=>x.classList.contains('brand'));throw Error(`Unknown query ${selector}`)},
    querySelectorAll(selector){
      if(selector==='[data-view]')return elements.filter(x=>'view' in x.dataset);
      if(selector==='[data-study]')return elements.filter(x=>'study' in x.dataset);
      if(selector==='#opsBox button.on')return elements.filter(x=>'op' in x.dataset && x.classList.contains('on'));
      if(selector==='.settings input, .settings select')return elements.filter(x=>['rangeInput','countInput','kindInput','parenInput','columnsInput','allowZeroInput','zeroResultInput','trivialInput'].includes(x.attrs.id));
      throw Error(`Unknown query ${selector}`);
    }};
  const context={document,localStorage:storage,location:{hash:'',protocol:'file:',hostname:''},history:{replaceState(){}},addEventListener(){},
    AbortController,fetch(){throw Error('Unexpected network request')},
    setTimeout(){return 1},clearTimeout(){},console,Date,Blob,URL:class extends URL {
      static createObjectURL(blob){context.lastBlob=blob;return 'blob:backup-test'}
      static revokeObjectURL(){}
    }};
  context.window=context; vm.createContext(context);
  for(const marker of ['sc-engine','sc-progress','sc-app']) {
    const source=html.match(new RegExp(`^<script id="${marker}">\\s*$(.*?)^</script>\\s*$`,'ms'))[1];
    vm.runInContext(source,context,{filename:marker+'.js'});
  }
  assert.equal(byId('storageWarning').hidden,true,byId('storageWarning').textContent);
  assert.equal(byId('practiceHint').hidden,true,byId('practiceHint').textContent);
  const profile=()=>{const root=JSON.parse(storage.getItem(context.SCProgress.STUDENTS_KEY));return root?.students.find(x=>x.id===root.activeId).profile};
  const navigate=view=>elements.find(x=>x.dataset.view===view).fire();
  const study=name=>elements.find(x=>x.dataset.study===name).fire();
  const submit=value=>{byId('answerInput').value=String(value);byId('answerForm').fire('submit')};
  const next=()=>byId('answerForm').fire('submit');
  const solve=(wrongFirst=false)=>{
    let i=0;
    while(!byId('playArea').hidden) {
      assert.ok(i<10,'Run should end within ten questions');
      const text=byId('questionExpr').textContent.replace(/ = \?$/,'');
      const answer=context.SCEngine.internal.evalText(text).value;
      submit(wrongFirst && i===0 ? (answer+1)%101 : answer); next(); i++;
    }
    return i;
  };
  return {byId,navigate,study,submit,next,solve,profile,context};
}
let ui=mount();
ui.navigate('study'); assert.equal(ui.byId('studyView').hidden,false);
ui.study('mistake'); assert.equal(ui.byId('reviewStart').disabled,true);
ui.study('daily'); ui.byId('dailyStart').fire();
assert.equal(ui.byId('runLevelLabel').textContent,'每日练习 · 今日 10 题');
ui.submit(''); assert.equal(ui.byId('answerInput').attrs['aria-invalid'],'true');
assert.equal(storage.getItem(ui.context.SCProgress.KEY),null);
assert.equal(ui.solve(true),10);
assert.equal(ui.profile().points,10); assert.equal(ui.profile().learning.total,10);
assert.equal(ui.profile().learning.correct,9); assert.equal(ui.profile().learning.mistakes.length,1);
assert.equal(ui.byId('resultReward').textContent,'✦ +10 积分已到账');
ui.byId('resultMap').fire(); assert.equal(ui.byId('studyView').hidden,false);
ui.study('record'); assert.equal(ui.byId('sessionList').children.length,1);
assert.equal(ui.byId('weekChart').children.length,7);
ui=mount(); ui.navigate('study'); ui.study('mistake');
assert.equal(ui.byId('savedMistakes').children.length,1);
assert.equal(ui.byId('reviewStart').disabled,false);
for(let i=0;i<3;i++) {
  ui.byId('reviewStart').fire(); assert.equal(ui.solve(),1); ui.byId('resultMap').fire();
}
assert.equal(ui.profile().learning.mistakes[0].streak,3);
assert.equal(ui.byId('reviewStart').disabled,true); assert.equal(ui.profile().points,10);
ui.byId('mistakeFilter').value='mastered'; ui.byId('mistakeFilter').fire('change');
assert.equal(ui.byId('savedMistakes').children.length,1);
ui.study('daily'); ui.byId('dailyStart').fire(); ui.solve();
assert.equal(ui.profile().points,10); assert.equal(ui.profile().learning.total,23);
ui.byId('resultMap').fire(); ui.navigate('challenge'); ui.byId('continueBtn').fire(); ui.solve();
assert.equal(ui.profile().points,30); assert.equal(ui.profile().completed[1].best,10);
ui.byId('resultMap').fire(); ui.navigate('study'); ui.byId('dailyStart').fire();
const savedCount=ui.profile().learning.total;
const write=storage.setItem; storage.setItem=()=>{throw Error('disk full')};
ui.submit(0); assert.equal(ui.profile().learning.total,savedCount);
assert.equal(ui.byId('answerInput').disabled,false);
assert.match(ui.byId('answerFeedback').textContent,/保存失败/);
storage.setItem=write; ui.submit(0); assert.equal(ui.profile().learning.total,savedCount+1);
ui.navigate('shop'); assert.equal(ui.byId('leaveDialog').open,true);
ui.byId('keepPlaying').fire(); assert.equal(ui.byId('leaveDialog').open,false);
ui.navigate('shop'); ui.byId('leaveRun').fire(); assert.equal(ui.byId('shopView').hidden,false);
ui=mount(); assert.equal(ui.profile().learning.total,savedCount+1);
// 文件读取、下载和恢复确认由测试替身承接，页面使用的仍是实际事件处理器。
(async()=>{
  ui.byId('manageStudents').fire(); assert.equal(ui.byId('profilesView').hidden,false);
  const originalProfile=JSON.stringify(ui.profile());
  ui.byId('editStudentName').value='小禾'; ui.byId('editStudentAvatar').value='🐼';
  ui.byId('editStudentForm').fire('submit'); assert.equal(ui.byId('currentStudentLabel').textContent,'🐼 小禾');
  assert.equal(JSON.stringify(ui.profile()),originalProfile);
  ui.byId('newStudentName').value='小林'; ui.byId('newStudentAvatar').value='🐱';
  ui.byId('addStudentForm').fire('submit'); assert.equal(ui.byId('currentStudentLabel').textContent,'🐱 小林');
  assert.equal(ui.profile().points,0); assert.equal(ui.profile().learning.total,0);
  assert.equal(ui.byId('studentList').children.length,2);
  ui.navigate('study'); ui.byId('dailyStart').fire(); ui.solve(); assert.equal(ui.profile().points,10);
  ui.byId('resultMap').fire(); ui.byId('manageStudents').fire();
  ui.byId('exportStudent').fire(); const single=await ui.context.lastBlob.text();
  const singleBackup=JSON.parse(single); assert.equal(singleBackup.students.length,1);
  assert.equal(singleBackup.students[0].name,'小林'); assert.equal(singleBackup.students[0].profile.points,10);
  assert.match(downloads.at(-1).name,/SimpleCal备份-小林-.*\.json/);
  ui.byId('exportAll').fire(); const all=await ui.context.lastBlob.text();
  assert.equal(JSON.parse(all).students.length,2);
  const load=async(text,size=text.length)=>{
    ui.byId('backupFile').files=[{size,text:async()=>text}];
    await ui.byId('backupFile').fire('change');
  };
  const before=storage.getItem(ui.context.SCProgress.STUDENTS_KEY);
  await load(single); assert.equal(ui.byId('importDialog').open,true);
  assert.equal(ui.byId('importMode').value,'new'); assert.equal(ui.byId('importPreview').children.length,1);
  assert.equal(storage.getItem(ui.context.SCProgress.STUDENTS_KEY),before);
  ui.byId('cancelImport').fire(); assert.equal(ui.byId('importDialog').open,false);
  assert.equal(storage.getItem(ui.context.SCProgress.STUDENTS_KEY),before);
  await load('not json'); assert.match(ui.byId('backupStatus').textContent,/JSON/);
  assert.equal(storage.getItem(ui.context.SCProgress.STUDENTS_KEY),before);
  await load(single,ui.context.SCProgress.MAX_BACKUP_BYTES+1); assert.match(ui.byId('backupStatus').textContent,/过大/);
  await load(all); assert.equal(ui.byId('importMode').querySelector('option[value="replace"]').disabled,true);
  ui.byId('cancelImport').fire();
  await load(single); ui.byId('confirmImport').fire();
  assert.equal(ui.byId('importDialog').open,false); assert.equal(ui.byId('studentList').children.length,3);
  assert.match(ui.byId('currentStudentLabel').textContent,/小林（导入1）/);
  assert.equal(JSON.stringify(ui.profile()),JSON.stringify(singleBackup.students[0].profile));
  // 导入后的学生可以继续练习；恢复时保留其身份，只替换学习数据。
  ui.navigate('challenge');ui.byId('continueBtn').fire();ui.solve();assert.equal(ui.profile().points,30);
  ui.byId('resultMap').fire();ui.byId('manageStudents').fire();
  const targetName=ui.byId('currentStudentLabel').textContent;
  await load(single);ui.byId('importMode').value='replace';ui.byId('importMode').fire('change');
  assert.match(ui.byId('importImpact').textContent,/替换/);assert.match(ui.byId('confirmImport').textContent,/确认替换/);
  const oldSet=storage.setItem;storage.setItem=()=>{throw Error('full')};
  ui.byId('confirmImport').fire();assert.equal(ui.byId('importDialog').open,true);
  assert.match(ui.byId('importError').textContent,/保存失败/);assert.equal(ui.profile().points,30);
  storage.setItem=oldSet;ui.byId('confirmImport').fire();assert.equal(ui.profile().points,10);
  assert.equal(ui.byId('currentStudentLabel').textContent,targetName);
  // 预览期间其他标签页替换目标时，旧确认不能继续覆盖。
  await load(single);ui.byId('importMode').value='replace';ui.byId('importMode').fire('change');
  const external=new ui.context.SCProgress.StudentStore(storage);
  external.import(external.export(),'replace',{id:external.current.id,revision:external.current.revision});
  const externalSaved=storage.getItem(ui.context.SCProgress.STUDENTS_KEY);
  ui.byId('confirmImport').fire();assert.match(ui.byId('importError').textContent,/已更新/);
  assert.equal(storage.getItem(ui.context.SCProgress.STUDENTS_KEY),externalSaved);ui.byId('cancelImport').fire();
  // 切换旧学生后积分和答题数原样保留；刷新仍停留在这名学生。
  ui.byId('studentList').children[0].children.at(-1).fire();
  assert.equal(ui.byId('currentStudentLabel').textContent,'🐼 小禾');assert.equal(JSON.stringify(ui.profile()),originalProfile);
  ui=mount();assert.equal(ui.byId('currentStudentLabel').textContent,'🐼 小禾');
  // 答题中进入档案管理，需走已有的离开确认流程。
  ui.navigate('study');ui.byId('dailyStart').fire();ui.submit(0);
  const count=ui.profile().learning.total;ui.byId('manageStudents').fire();assert.equal(ui.byId('leaveDialog').open,true);
  ui.byId('keepPlaying').fire();assert.equal(ui.byId('playArea').hidden,false);
  ui.byId('manageStudents').fire();ui.byId('leaveRun').fire();assert.equal(ui.byId('profilesView').hidden,false);
  ui.byId('studentList').children[1].children.at(-1).fire();assert.equal(ui.byId('currentStudentLabel').textContent,'🐱 小林');
  assert.equal(ui.profile().learning.total,10);
  ui.byId('studentList').children[0].children.at(-1).fire();assert.equal(ui.profile().learning.total,count);
  // 专项训练、逐步提示和基于独立作答的推荐。
  ui.byId('newStudentName').value='专项同学';ui.byId('newStudentAvatar').value='🚀';ui.byId('addStudentForm').fire('submit');
  ui.navigate('study');ui.byId('browseSpecialties').fire();assert.equal(ui.byId('specialPane').hidden,false);
  const cards=()=>ui.byId('specialtyCards').children;
  assert.match(cards()[0].children[3].textContent,/先练一组/);
  cards()[0].children.at(-1).fire();assert.match(ui.byId('runLevelLabel').textContent,/20 以内进位加法/);
  assert.equal(ui.byId('hintBtn').hidden,false);assert.equal(ui.byId('hintPanel').hidden,true);
  ui.byId('hintBtn').fire();assert.equal(ui.byId('hintSteps').children.length,1);
  assert.equal(ui.byId('hintBtn').attrs['aria-expanded'],'true');assert.match(ui.byId('hintNote').textContent,/不用于薄弱项/);
  ui.byId('hintBtn').fire();ui.byId('hintBtn').fire();assert.equal(ui.byId('hintSteps').children.length,3);
  assert.equal(ui.byId('hintBtn').disabled,true);
  let expression=ui.byId('questionExpr').textContent.replace(/ = \?$/,'');
  ui.submit(ui.context.SCEngine.internal.evalText(expression).value);ui.next();
  assert.equal(ui.profile().learning.skillHistory[0].assisted,true);
  assert.equal(ui.byId('hintPanel').hidden,true);assert.equal(ui.byId('hintBtn').disabled,false);
  for(let i=0;i<9;i++){ui.submit(0);ui.next()}
  assert.equal(ui.profile().points,0);assert.equal(ui.profile().learning.sessions[0].skillId,'carry20');
  assert.equal(ui.profile().learning.sessions[0].assisted,1);assert.match(ui.byId('resultText').textContent,/1 题使用了提示/);
  ui.byId('resultMap').fire();assert.equal(ui.byId('specialPane').hidden,false);
  assert.match(cards()[0].children[3].textContent,/9 次独立作答/);
  // 结果页可再练相同专项；不足十次不做薄弱项判断。
  cards()[0].children.at(-1).fire();
  ui.submit(0);const unaidedCount=ui.profile().learning.skillHistory.filter(x=>!x.assisted).length;
  ui.byId('hintBtn').fire();assert.match(ui.byId('hintNote').textContent,/答题后的方法回顾/);
  assert.equal(ui.profile().learning.skillHistory.filter(x=>!x.assisted).length,unaidedCount);
  ui.next();for(let i=0;i<9;i++){ui.submit(0);ui.next()}
  ui.byId('resultMain').fire();assert.match(ui.byId('runLevelLabel').textContent,/进位加法/);
  ui.byId('backToMap').fire();ui.byId('leaveRun').fire();assert.equal(ui.byId('specialPane').hidden,false);
  assert.match(cards()[0].children[3].textContent,/建议再巩固/);
  ui.study('daily');
  let recommend=ui.byId('recommendationBody').children[0];
  assert.match(recommend.children[0].textContent,/进位加法/);recommend.children[1].children[0].fire();
  assert.match(ui.byId('runLevelLabel').textContent,/进位加法/);
  ui.byId('backToMap').fire();ui.byId('leaveRun').fire();
  cards()[1].children.at(-1).fire();assert.match(ui.byId('runLevelLabel').textContent,/退位减法/);
  // 提示前提交失败不应留下计数，重试仍正确保留提示标记。
  ui.byId('hintBtn').fire();expression=ui.byId('questionExpr').textContent.replace(/ = \?$/,'');
  const beforeHint=ui.profile().learning.total,save=storage.setItem;storage.setItem=()=>{throw Error('full')};
  ui.submit(ui.context.SCEngine.internal.evalText(expression).value);assert.equal(ui.profile().learning.total,beforeHint);
  storage.setItem=save;ui.submit(ui.context.SCEngine.internal.evalText(expression).value);
  assert.equal(ui.profile().learning.total,beforeHint+1);assert.equal(ui.profile().learning.skillHistory.at(-1).assisted,true);
  ui.next();ui.solve();ui.byId('resultMap').fire();ui.study('record');
  assert.match(ui.byId('sessionList').children[0].children[0].textContent,/退位减法/);
  assert.match(ui.byId('sessionList').children[0].children[1].textContent,/提示 1 题/);
  ui=mount();ui.navigate('study');ui.study('special');assert.match(cards()[0].children[3].textContent,/建议再巩固/);
  ui.byId('manageStudents').fire();ui.byId('exportStudent').fire();
  const skillBackup=JSON.parse(await ui.context.lastBlob.text());assert.ok(skillBackup.students[0].profile.learning.skillHistory.length>0);
  // AI 只在主动点击时请求，成功显示后才计入提示，翻页和退出都会取消旧请求。
  ui.navigate('study');ui.study('special');cards()[0].children.at(-1).fire();
  let requests=0;
  ui.context.fetch=()=>{requests++;throw Error('Offline page should not request the API')};
  await ui.byId('aiHintBtn').fire();
  assert.equal(requests,0);assert.match(ui.byId('aiHintStatus').textContent,/本地服务/);
  assert.equal(ui.byId('hintBtn').hidden,false);
  Object.assign(ui.context.location,{protocol:'http:',hostname:'127.0.0.1'});
  const correct=()=>ui.context.SCEngine.internal.evalText(ui.byId('questionExpr').textContent.replace(/ = \?$/,'')).value;
  let pending, signal;
  ui.context.fetch=(url,options)=>{
    requests++;
    assert.equal(url,'/api/explain');assert.equal(options.method,'POST');
    assert.deepEqual(JSON.parse(options.body),{expression:ui.byId('questionExpr').textContent.replace(/ = \?$/,'')});
    signal=options.signal;
    return new Promise(resolve=>{pending=resolve});
  };
  const success=()=>({ok:true,json:async()=>({steps:[{text:'先把算式凑成整十。',equation:'8 + 2 = 10'}]})});
  let wait=ui.byId('aiHintBtn').fire();ui.byId('aiHintBtn').fire();
  assert.equal(requests,1);assert.match(ui.byId('aiHintStatus').textContent,/正在生成/);
  pending({ok:false,json:async()=>({error:'余额不足'})});await wait;
  assert.match(ui.byId('aiHintStatus').textContent,/余额不足/);assert.equal(ui.byId('aiHintBtn').disabled,false);
  assert.equal(ui.byId('hintBtn').hidden,false);
  ui.submit(correct());assert.equal(ui.profile().learning.skillHistory.at(-1).assisted,false);
  wait=ui.byId('aiHintBtn').fire();pending(success());await wait;
  assert.match(ui.byId('aiHintNote').textContent,/回顾/);
  assert.equal(ui.profile().learning.skillHistory.at(-1).assisted,false);
  ui.next();assert.equal(ui.byId('aiHintPanel').hidden,true);
  wait=ui.byId('aiHintBtn').fire();pending(success());await wait;
  assert.equal(ui.byId('aiHintPanel').hidden,false);
  assert.equal(ui.byId('aiHintSteps').children[0].children[1].textContent,'8 + 2 = 10');
  ui.submit(correct());assert.equal(ui.profile().learning.skillHistory.at(-1).assisted,true);
  ui.next();wait=ui.byId('aiHintBtn').fire();ui.submit(correct());
  assert.equal(ui.profile().learning.skillHistory.at(-1).assisted,false);
  ui.next();assert.equal(signal.aborted,true);
  pending(success());await wait;assert.equal(ui.byId('aiHintPanel').hidden,true);
  wait=ui.byId('aiHintBtn').fire();ui.byId('backToMap').fire();ui.byId('leaveRun').fire();
  assert.equal(signal.aborted,true);pending(success());await wait;assert.equal(ui.byId('aiHintPanel').hidden,true);
  process.stdout.write('PASS: optional AI request, retry, assisted accounting, review and stale responses.\n');
  // GitHub Pages reads its cloud origin from the page and waits for health without repeating a paid POST.
  cards()[0].children.at(-1).fire();
  Object.assign(ui.context.location,{protocol:'https:',hostname:'atri-realm.github.io'});
  const calls=[];
  ui.context.fetch=(url,options)=>{
    calls.push({url,options});
    if (url.endsWith('/healthz')) {
      return Promise.resolve(calls.length===1 ? {ok:false} : {ok:true,json:async()=>({status:'ok'})});
    }
    return Promise.resolve(success());
  };
  const config=ui.byId('simplecalCloudOrigin');
  config.setAttribute('content','');await ui.byId('aiHintBtn').fire();
  assert.match(ui.byId('aiHintStatus').textContent,/尚未配置/);assert.deepEqual(calls,[]);
  config.setAttribute('content','http://service.example');await ui.byId('aiHintBtn').fire();
  assert.deepEqual(calls,[]);
  config.setAttribute('content','https://service.example/');
  let retry, warm;
  ui.context.setTimeout=(callback,delay)=>{
    if(delay===4000) retry=callback;
    if(delay===12000) warm=callback;
    return delay;
  };
  wait=ui.byId('aiHintBtn').fire();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.length,1);warm();assert.match(ui.byId('aiHintStatus').textContent,/正在启动/);
  retry();await wait;
  assert.deepEqual(calls.map(call=>call.url), ['https://service.example/healthz', 'https://service.example/healthz', 'https://service.example/api/explain']);
  assert.equal(calls[2].options.method,'POST');assert.equal(calls[2].options.credentials,'omit');
  assert.deepEqual(JSON.parse(calls[2].options.body),{expression:ui.byId('questionExpr').textContent.replace(/ = \?$/,'')});
  assert.equal(ui.byId('aiHintPanel').hidden,false);
  process.stdout.write('PASS: GitHub Pages cloud endpoint, startup and single explanation request.\n');
  process.stdout.write('PASS: specialty selection/replay/exit, progressive hints, post-answer review, assisted results, recommendation thresholds, persistence rollback, refresh and backup.\n');
  process.stdout.write('PASS: profile edit/create/switch, independent daily rewards, backup downloads, import preview/cancel/validation/new/replace, write rollback, stale confirmation and refresh.\n');
})().catch(error=>{console.error(error);process.exitCode=1});
process.stdout.write('PASS: startup, daily completion/replay, saved mistakes/mastery, records, reload, level rewards, failed-write retry and leaving partial runs.\n');
