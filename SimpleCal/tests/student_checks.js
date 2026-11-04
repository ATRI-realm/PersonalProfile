/* 从最终 HTML 验证多学生、备份格式、恢复事务和旧档案迁移。 */
const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
for(const marker of ['sc-engine','sc-progress']) {
  vm.runInThisContext(html.match(new RegExp(`^<script id="${marker}">\\s*$(.*?)^</script>\\s*$`,'ms'))[1]);
}
const P=SCProgress, E=SCEngine, cases={};
const clone=x=>JSON.parse(JSON.stringify(x));
function check(name,fn){try{fn();cases[name]=null}catch(e){cases[name]=e.stack}}
function memory(){const data=new Map();return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)}}
function daily(store,wrong=false){
  const run=P.createLearningRun(store.profile,'daily',E);
  run.student={id:store.current.id,revision:store.current.revision};
  for(const q of run.problems){
    P.answer(run,wrong ? (q.answer+1)%101 : q.answer);
    store.transact(p=>P.recordAnswer(p,run),run.student);
  }
  store.transact(p=>P.finishLearning(p,run),run.student);return run;
}
check('fresh library has one default student and supports refresh',()=>{
  const data=memory(),s=new P.StudentStore(data);
  assert.equal(s.current.name,'默认学生');assert.equal(s.library.students.length,1);
  const id=s.current.id;s.rename('小禾','🐼');
  const reloaded=new P.StudentStore(data);assert.equal(reloaded.current.id,id);assert.equal(reloaded.current.name,'小禾');
});
check('legacy profile migrates completely on first write and original key is preserved',()=>{
  const data=memory(),p=P.initial();p.points=60;P.redeem(p,'theme-sky');P.addProduct(p,'书',10);
  const run=P.createRun(p,1,E);for(const q of run.problems){P.answer(run,q.answer);P.recordAnswer(p,run)}
  P.finish(p,run);P.finishLearning(p,run);
  const raw=JSON.stringify(p);data.setItem(P.KEY,raw);
  const s=new P.StudentStore(data);assert.deepEqual(s.profile,p);s.rename('迁移学生','🐱');
  assert.deepEqual(new P.StudentStore(data).profile,p);assert.equal(data.getItem(P.KEY),raw);
});
check('legacy version without learning fields migrates safely',()=>{
  const data=memory(),p=P.initial();delete p.learning;p.points=123;data.setItem(P.KEY,JSON.stringify(p));
  const s=new P.StudentStore(data);assert.equal(s.profile.points,123);assert.deepEqual(s.profile.learning,P.learningInitial());
});
check('students have independent points daily rewards mistakes and progress',()=>{
  const s=new P.StudentStore(memory()),first=s.current.id;daily(s,true);
  s.transact(p=>{p.completed[1]={best:10};p.points=80;P.redeem(p,'theme-sky');P.addProduct(p,'阅读',5)});
  const firstProfile=clone(s.profile);const second=s.add('小禾','🐱');
  assert.deepEqual(s.profile,P.initial());daily(s);assert.equal(s.profile.points,10);assert.equal(s.profile.learning.mistakes.length,0);
  s.select(first);assert.deepEqual(s.profile,firstProfile);s.select(second);assert.equal(s.profile.theme,'forest');
});
check('blank duplicate overlong names invalid avatars and student cap rejected',()=>{
  const s=new P.StudentStore(memory());
  for(const name of ['', ' ', '字'.repeat(21)]) assert.throws(()=>s.add(name,'🌱'));
  assert.throws(()=>s.add('默认学生','🐱'));assert.throws(()=>s.add('学生','unknown'));
  for(let i=1;i<20;i++)s.add(`学生${i}`,'🌱');assert.throws(()=>s.add('第21名','🌱'));
  assert.equal(s.library.students.length,20);assert.throws(()=>s.rename('默认学生','🌱'));
});
check('renaming student retains id revision and all learning data',()=>{
  const s=new P.StudentStore(memory());daily(s);const id=s.current.id,rev=s.current.revision,profile=clone(s.profile);
  s.rename('小林','🚀');assert.equal(s.current.id,id);assert.equal(s.current.revision,rev);assert.deepEqual(s.profile,profile);
});
check('single student backup round trip preserves every profile field',()=>{
  const s=new P.StudentStore(memory());daily(s,true);s.rename('小禾','🦊');
  const backup=P.parseBackup(JSON.stringify(s.export('student'))),copy=new P.StudentStore(memory());
  copy.import(backup);assert.equal(copy.current.name,'小禾');assert.equal(copy.current.avatar,'🦊');assert.deepEqual(copy.profile,s.profile);
  assert.notEqual(copy.current.id,s.current.id);assert.equal(copy.library.students.length,2);
});
check('all student backup restores every profile without overwriting existing students',()=>{
  const s=new P.StudentStore(memory());daily(s,true);const first=s.current.id;s.add('小禾','🐼');daily(s);
  const backup=s.export('all'),t=new P.StudentStore(memory()),original=t.current.id;
  assert.equal(t.import(backup),2);assert.equal(t.library.students.length,3);
  assert.deepEqual(t.library.students.find(x=>x.id===original).profile,P.initial());
  assert.deepEqual(t.library.students[1].profile,s.library.students.find(x=>x.id===first).profile);
  assert.deepEqual(t.library.students[2].profile,s.profile);
});
check('reimport and same-name students get new ids and unambiguous names',()=>{
  const s=new P.StudentStore(memory());const backup=s.export();const ids=new Set([s.current.id]);
  for(let i=0;i<3;i++){s.import(backup);assert.ok(!ids.has(s.current.id));ids.add(s.current.id)}
  assert.equal(new Set(s.library.students.map(x=>x.name)).size,4);assert.ok(s.current.name.includes('导入'));
});
check('replace requires target confirmation and preserves target identity and other students',()=>{
  const s=new P.StudentStore(memory());daily(s);const backup=s.export();s.add('目标学生','🐯');
  const id=s.current.id,rev=s.current.revision,first=clone(s.library.students[0]);
  assert.throws(()=>s.import(backup,'replace'));assert.deepEqual(s.profile,P.initial());
  s.import(backup,'replace',{id,revision:rev});
  assert.equal(s.current.id,id);assert.equal(s.current.name,'目标学生');assert.equal(s.current.avatar,'🐯');
  assert.notEqual(s.current.revision,rev);assert.deepEqual(s.profile,backup.students[0].profile);
  assert.deepEqual(s.library.students[0],first);
});
check('stale replacement preview and cross-tab run writes are rejected',()=>{
  const data=memory(),a=new P.StudentStore(data);a.rename('学生甲','🌱');
  const b=new P.StudentStore(data),run=P.createLearningRun(a.profile,'daily',E);
  const expected={id:a.current.id,revision:a.current.revision},backup=a.export();
  b.import(backup,'replace',expected);
  P.answer(run,0);assert.throws(()=>a.transact(p=>P.recordAnswer(p,run),expected));
  assert.throws(()=>a.import(backup,'replace',expected));assert.equal(a.profile.learning.total,0);
});
check('tabs keep their own student selection and transactions preserve other students',()=>{
  const data=memory(),a=new P.StudentStore(data);a.rename('甲','🌱');const first=a.current.id;
  const second=a.add('乙','🐼');a.select(first);const b=new P.StudentStore(data);b.select(second);
  a.transact(p=>{p.points=31});assert.equal(a.current.id,first);assert.equal(b.current.id,second);
  b.transact(p=>{p.points=72});a.load();assert.equal(a.profile.points,31);assert.equal(b.profile.points,72);
  assert.equal(new P.StudentStore(data).current.id,second);
});
check('failed student writes roll back create switch rename and imports',()=>{
  const data=memory(),s=new P.StudentStore(data);s.rename('甲','🌱');const first=s.current.id;
  const second=s.add('乙','🐼');s.select(first);const before=JSON.stringify(s.library),backup=s.export();
  data.setItem=()=>{throw Error('disk full')};
  for(const action of [()=>s.add('丙','🐱'),()=>s.select(second),()=>s.rename('改名','🚀'),()=>s.import(backup),()=>s.import(backup,'replace',{id:first,revision:s.current.revision})]){
    assert.throws(action);assert.equal(JSON.stringify(s.library),before);assert.equal(s.current.id,first);
  }
});
check('export snapshots cannot mutate live profiles and unsupported scopes fail',()=>{
  const s=new P.StudentStore(memory());const backup=s.export();backup.students[0].profile.points=999;
  assert.equal(s.profile.points,0);assert.throws(()=>s.export('invalid'));assert.throws(()=>s.import(s.export(),'invalid'));
});
check('invalid json foreign formats unsupported versions and duplicate ids rejected',()=>{
  const s=new P.StudentStore(memory()),valid=s.export();
  for(const text of ['{','null','[]','{}',JSON.stringify({...valid,version:99}),JSON.stringify({...valid,format:'other'}),JSON.stringify({...valid,students:[]}),JSON.stringify({...valid,scope:'all',students:[valid.students[0],valid.students[0]]})])assert.throws(()=>P.parseBackup(text));
  assert.throws(()=>P.parseBackup(' '.repeat(P.MAX_BACKUP_BYTES+1)));
});
check('invalid balances methods and injected mathematical expressions are rejected without changes',()=>{
  const s=new P.StudentStore(memory());s.rename('甲','🌱');const before=JSON.stringify(s.library);
  for(const mutate of [p=>p.points=-1,p=>p.owned=['bad'],p=>p.completed={2:{best:10}},p=>p.version=99,
    p=>p.learning.mistakes=[{text:'globalThis.injected=1',answer:1,wrong:2,errors:1,streak:0,day:'2026-10-28'}],
    p=>p.history=[{id:'bad',name:'bad',delta:'1',at:'bad'}],p=>delete p.points]){
    const backup=s.export();mutate(backup.students[0].profile);assert.throws(()=>s.import(backup));assert.equal(JSON.stringify(s.library),before);
  }
  assert.equal(globalThis.injected,undefined);
});
check('all-backup replacement and imports over capacity fail atomically',()=>{
  const s=new P.StudentStore(memory());s.add('第二名','🐼');const multi=s.export('all');
  assert.throws(()=>s.import(multi,'replace',{id:s.current.id,revision:s.current.revision}));
  for(let i=2;i<19;i++)s.add(`学生${i}`,'🌱');const before=JSON.stringify(s.library);
  assert.throws(()=>s.import(multi));assert.equal(JSON.stringify(s.library),before);
});
check('damaged future-version library and damaged legacy data are never overwritten',()=>{
  for(const [key,raw] of [[P.STUDENTS_KEY,'oops'],[P.STUDENTS_KEY,'{"version":2}'],[P.KEY,'oops'],[P.KEY,'{"version":2}']]){
    const data=memory();data.setItem(key,raw);const s=new P.StudentStore(data);assert.ok(s.blocked);
    assert.throws(()=>s.add('新学生','🌱'));assert.equal(data.getItem(key),raw);
  }
});
check('unavailable storage supports multiple students and portable backups in memory',()=>{
  const s=new P.StudentStore(null);assert.ok(s.warning);daily(s,true);const backup=s.export();
  s.add('另一个孩子','🐼');assert.equal(s.profile.points,0);s.import(backup);assert.equal(s.profile.points,10);assert.ok(s.warning);
});
check('BOM and reordered JSON keys are accepted but incomplete profiles fail',()=>{
  const s=new P.StudentStore(memory()),backup=s.export();
  const profile=backup.students[0].profile;backup.students[0].profile=Object.fromEntries(Object.entries(profile).reverse());
  assert.equal(P.parseBackup('\uFEFF'+JSON.stringify(backup)).students.length,1);
  delete backup.students[0].profile.learning;assert.deepEqual(P.parseBackup(JSON.stringify(backup)).students[0].profile.learning,P.learningInitial());
  delete backup.students[0].profile.history;assert.throws(()=>P.parseBackup(JSON.stringify(backup)));
});
process.stdout.write(JSON.stringify(cases));
