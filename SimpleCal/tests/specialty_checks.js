/* 验证专项题库、逐步讲解、推荐依据、迁移和数据归属。 */
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
for(const id of ['sc-engine','sc-progress'])vm.runInThisContext(html.match(new RegExp(`^<script id="${id}">\\s*$(.*?)^</script>\\s*$`,'ms'))[1]);
const P=SCProgress,E=SCEngine,cases={},now=new Date(2026,10,4,12);
function check(name,fn){try{fn();cases[name]=null}catch(error){cases[name]=error.stack}}
function answer(p,text,value,assisted=false,date=now){
  const q={text,answer:E.internal.evalText(text).value};
  const run={id:`test-${Math.random()}`,kind:'review',problems:[q],answers:[],hinted:assisted ? {0:true} : {},startedAt:date.getTime()};
  P.answer(run,value);P.recordAnswer(p,run,date);return run;
}
const memory=()=>{const data=new Map();return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)}};
check('classification excludes exact tens nonborrowing mixed operations and other ranges',()=>{
  for(const [text,id] of [['8 + 7','carry20'],['9 + 9','carry20'],['13 − 8','borrow20'],['11 - 9','borrow20']])assert.equal(P.specialtyFor({text}),id);
  for(const text of ['8 + 2','10 + 8','12 + 7','13 − 2','10 − 8','20 − 9','3 + 4 + 5','2 × 8','8 ÷ 2','not arithmetic'])assert.equal(P.specialtyFor({text}),null,text);
});
check('each specialty has exactly 36 valid unique facts and always generates ten unique questions',()=>{
  for(const skill of P.SPECIALTIES){
    const pool=P.specialtyPool(skill.id);assert.equal(pool.length,36);assert.equal(new Set(pool.map(q=>q.text)).size,36);
    for(let i=0;i<30;i++){
      const run=P.createSpecialtyRun(skill.id);assert.equal(run.kind,'special');assert.equal(run.problems.length,10);
      assert.equal(new Set(run.problems.map(q=>q.text)).size,10);
      for(const q of run.problems){assert.equal(P.specialtyFor(q),skill.id);assert.equal(E.internal.evalText(q.text).value,q.answer);assert.ok(q.answer>=1&&q.answer<=18)}
    }
  }
  assert.throws(()=>P.createSpecialtyRun('other'));
});
check('all explanations split the second operand and finish at the original answer',()=>{
  for(const skill of P.SPECIALTIES)for(const q of P.specialtyPool(skill.id)){
    const help=P.explanation(q),[,a,b]=E.internal.evalText(q.text).operations[0];assert.equal(help.steps.length,3);
    const pieces=help.steps[0].equation.match(/\d+/g).map(Number);assert.equal(pieces[0],b);assert.equal(pieces[1]+pieces[2],b);
    assert.ok(pieces[1]>0&&pieces[2]>0);
    for(const step of help.steps){const [lhs,rhs]=step.equation.split(' = ');assert.equal(E.internal.evalText(lhs).value,E.internal.evalText(rhs).value)}
    assert.equal(Number(help.steps[2].equation.split(' = ')[1]),q.answer);
    assert.ok(help.steps[1].equation.endsWith('= 10'));
  }
  assert.equal(P.explanation({text:'2 × 4'}),null);
});
check('carry and borrow examples match the taught algorithms',()=>{
  assert.deepEqual(P.explanation({text:'8 + 7'}).steps.map(s=>s.equation),['7 = 2 + 5','8 + 2 = 10','10 + 5 = 15']);
  assert.deepEqual(P.explanation({text:'13 − 8'}).steps.map(s=>s.equation),['8 = 3 + 5','13 − 3 = 10','10 − 5 = 5']);
});
check('fewer than ten independent attempts never implies a weakness',()=>{
  const p=P.initial();for(let i=0;i<9;i++)answer(p,'8 + 7',0);
  assert.equal(P.specialtyRecommendations(p,now)[0].status,'insufficient');
  answer(p,'8 + 7',0);assert.equal(P.specialtyRecommendations(p,now)[0].status,'practice');
});
check('eighty percent boundary is steady and lower correctness recommends practice',()=>{
  const p=P.initial();for(let i=0;i<10;i++)answer(p,'13 − 8',i<8?5:0);
  assert.equal(P.specialtyRecommendations(p,now)[1].status,'steady');
  answer(p,'13 − 8',0);assert.equal(P.specialtyRecommendations(p,now)[1].status,'practice');
});
check('recommendations use latest twenty independent attempts in local fourteen day window',()=>{
  const p=P.initial();for(let i=0;i<20;i++)answer(p,'8 + 7',0);
  for(let i=0;i<20;i++)answer(p,'8 + 7',15);
  let rec=P.specialtyRecommendations(p,now)[0];assert.equal(rec.total,20);assert.equal(rec.correct,20);assert.equal(rec.status,'steady');
  rec=P.specialtyRecommendations(p,new Date(2026,10,18,12))[0];assert.equal(rec.total,0);assert.equal(rec.status,'insufficient');
});
check('old future and assisted attempts do not distort recommendations',()=>{
  const p=P.initial();
  for(let i=0;i<20;i++){answer(p,'8 + 7',0,false,new Date(2026,9,21,12));answer(p,'8 + 7',0,false,new Date(2026,10,5,12));answer(p,'8 + 7',15,true)}
  assert.equal(P.specialtyRecommendations(p,now)[0].total,0);
  for(let i=0;i<10;i++)answer(p,'8 + 7',15,false,new Date(2026,9,22,12));
  assert.equal(P.specialtyRecommendations(p,now)[0].total,10);
});
check('skill evidence is collected across levels daily and review and independent between skills',()=>{
  const p=P.initial();for(const kind of ['level','daily','review']){
    const run={id:kind,kind,problems:[{text:'13 − 8',answer:5}],answers:[]};P.answer(run,0);P.recordAnswer(p,run,now);
  }
  assert.equal(p.learning.skillHistory.length,3);assert.equal(P.specialtyRecommendations(p,now)[1].total,3);
  assert.equal(P.specialtyRecommendations(p,now)[0].total,0);
});
check('hinted answers remain correct in practice but cannot advance mistake mastery',()=>{
  const p=P.initial();answer(p,'8 + 7',0);answer(p,'8 + 7',15);answer(p,'8 + 7',15);
  assert.equal(p.learning.mistakes[0].streak,2);const run=answer(p,'8 + 7',15,true);
  assert.equal(run.answers[0].assisted,true);assert.equal(p.learning.correct,3);assert.equal(p.learning.mistakes[0].streak,0);
  assert.equal(P.specialtyRecommendations(p,now)[0].total,3);
  for(let i=0;i<3;i++)answer(p,'8 + 7',15);assert.equal(p.learning.mistakes[0].streak,3);
});
check('specialty completion records topic and hint counts without points or level unlocks',()=>{
  const p=P.initial(),r=P.createSpecialtyRun('carry20');r.hinted[0]=true;
  for(const q of r.problems){P.answer(r,q.answer);P.recordAnswer(p,r,now)}
  const result=P.finishLearning(p,r,now);assert.equal(result.reward,0);assert.equal(p.points,0);assert.deepEqual(p.completed,{});
  const session=p.learning.sessions[0];assert.equal(session.kind,'special');assert.equal(session.skillId,'carry20');assert.equal(session.assisted,1);
  assert.deepEqual(P.normalize(JSON.parse(JSON.stringify(p))),p);
});
check('answer deduplication also protects specialty evidence',()=>{
  const p=P.initial(),run=answer(p,'8 + 7',0);P.recordAnswer(p,run,now);
  assert.equal(p.learning.skillHistory.length,1);assert.equal(p.learning.total,1);
});
check('legacy learning and old backups gain empty evidence without fabricating attempts',()=>{
  const store=new P.StudentStore(memory());store.transact(p=>{p.points=77});const backup=store.export();
  delete backup.students[0].profile.learning.skillHistory;
  const imported=P.parseBackup(JSON.stringify(backup));assert.deepEqual(imported.students[0].profile.learning.skillHistory,[]);
  store.import(imported);assert.equal(store.profile.points,77);assert.deepEqual(store.profile.learning.skillHistory,[]);
  assert.equal(P.specialtyRecommendations(store.profile,now)[0].status,'insufficient');
});
check('specialty history and sessions survive student switching backup and restore',()=>{
  const store=new P.StudentStore(memory()),first=store.current.id;
  store.transact(p=>{const r=answer(p,'13 − 8',5,true);r.skillId='borrow20';r.kind='special';P.finishLearning(p,r,now)});
  const saved=JSON.stringify(store.profile);const backup=store.export();store.add('另一个学生','🐼');assert.deepEqual(store.profile.learning.skillHistory,[]);
  store.select(first);assert.equal(JSON.stringify(store.profile),saved);store.import(backup);assert.equal(JSON.stringify(store.profile),saved);
});
check('failed persistence rolls back specialty counts and hint evidence together',()=>{
  const data=memory(),store=new P.StudentStore(data);store.rename('学生','🌱');
  data.setItem=()=>{throw Error('full')};
  assert.throws(()=>store.transact(p=>answer(p,'8 + 7',15,true)));
  assert.equal(store.profile.learning.total,0);assert.deepEqual(store.profile.learning.skillHistory,[]);
});
check('evidence retention is bounded and malformed imported evidence is rejected',()=>{
  const p=P.initial();for(let i=0;i<120;i++)answer(p,'8 + 7',15);assert.equal(p.learning.skillHistory.length,100);
  const store=new P.StudentStore(memory()),backup=store.export();backup.students[0].profile.learning.skillHistory=[{id:'bad',skillId:'other',day:'2026-11-04',correct:true,assisted:false}];
  assert.throws(()=>P.parseBackup(JSON.stringify(backup)));
});
const pools=Object.fromEntries(P.SPECIALTIES.map(s=>[s.id,P.specialtyPool(s.id).map(q=>({...q,steps:P.explanation(q).steps}))]));
process.stdout.write(JSON.stringify({cases,pools}));
