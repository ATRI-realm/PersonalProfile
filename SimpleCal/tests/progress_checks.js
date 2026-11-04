/* 无外部依赖：从最终交付的 HTML 加载闯关和商店逻辑。 */
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
for (const marker of ['sc-engine', 'sc-progress']) {
  const match = html.match(new RegExp(`^<script id="${marker}">\\s*$(.*?)^</script>\\s*$`, 'ms'));
  assert.ok(match, `Missing ${marker}`);
  vm.runInThisContext(match[1], { filename: marker + '.js' });
}
const P = SCProgress;
const E = SCEngine;
const cases = {};
function check(name, test) {
  try { test(); cases[name] = null; }
  catch (error) { cases[name] = error.stack; }
}
function solved(profile, id = 1, score = 10) {
  const run = P.createRun(profile, id, E);
  run.problems.forEach((p, i) => P.answer(run, i < score ? p.answer : (p.answer + 1) % 101));
  return run;
}
function memory() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}
check('locked levels cannot be started', () => {
  assert.throws(() => P.createRun(P.initial(), 2, E));
  assert.throws(() => P.createRun(P.initial(), 99, E));
});
check('valid input includes zero and fullwidth digits', () => {
  assert.equal(P.parseAnswer(' ０ '), 0);
  assert.equal(P.parseAnswer('１００'), 100);
  assert.equal(P.parseAnswer('08'), 8);
});
check('empty decimal exponent sign and overflow inputs rejected', () => {
  for (const input of ['', ' ', '-1', '+2', '2.5', '1e1', '0x10', '101', 'NaN', '2 3', '1234']) {
    assert.throws(() => P.parseAnswer(input), input);
  }
  const run = P.createRun(P.initial(), 1, E);
  assert.throws(() => P.answer(run, ''));
  assert.equal(run.answers.length, 0);
});
check('incomplete runs cannot be settled', () => {
  const p = P.initial();
  assert.throws(() => P.finish(p, P.createRun(p, 1, E)));
  assert.equal(p.points, 0);
});
check('seven answers fail and eight answers pass', () => {
  const p = P.initial();
  assert.deepEqual(P.finish(p, solved(p, 1, 7)), { score: 7, passed: false, reward: 0 });
  assert.equal(P.unlocked(p, 2), false);
  assert.deepEqual(P.finish(p, solved(p, 1, 8)), { score: 8, passed: true, reward: 20 });
  assert.equal(p.points, 20);
  assert.equal(P.unlocked(p, 2), true);
});
check('replay improves best score without duplicate reward', () => {
  const p = P.initial();
  P.finish(p, solved(p, 1, 8));
  const run = solved(p);
  const result = P.finish(p, run);
  assert.equal(result.reward, 0);
  assert.equal(p.completed[1].best, 10);
  assert.equal(p.points, 20);
  assert.equal(p.history.length, 1);
  run.settled = true;
  assert.throws(() => P.finish(p, run));
  assert.throws(() => P.answer(run, 0));
});
check('all levels produce exact unique valid questions and award once', () => {
  const p = P.initial();
  for (const level of P.LEVELS) {
    const run = solved(p, level.id);
    assert.equal(run.problems.length, 10);
    assert.equal(new Set(run.problems.map(x => x.text)).size, 10);
    const cfg = E.internal.configFromPayload(P.levelConfig(level.id));
    for (const problem of run.problems) {
      assert.equal(E.internal.evalText(problem.text).value, problem.answer);
      assert.ok(E.internal.evalText(problem.text).values.every(v => v >= 0 && v <= level.max));
      if (level.id === 5) {
        assert.ok(problem.answer >= 2 && problem.answer <= 9);
        assert.ok(problem.tree.right.value >= 2 && problem.tree.right.value <= 9);
      }
      if (level.paren === 'always') assert.ok(problem.text.includes('('));
      if (level.paren === 'none') assert.ok(!problem.text.includes('('));
    }
    assert.equal(P.finish(p, run).reward, level.reward);
  }
  assert.equal(p.points, P.LEVELS.reduce((sum, l) => sum + l.reward, 0));
  assert.equal(Object.keys(p.completed).length, 12);
  assert.equal(P.nextLevel(p).id, 12);
});
check('last level requires nine correct answers', () => {
  const p = P.initial();
  for (let i = 1; i <= 11; i++) P.finish(p, solved(p, i));
  assert.equal(P.finish(p, solved(p, 12, 8)).passed, false);
  assert.equal(P.finish(p, solved(p, 12, 9)).passed, true);
});
check('rendered multiplication cannot escape table', () => {
  const leaf = value => ({ value, op: null, left: null, right: null });
  const root = { value: 12, op: '*', left: leaf(2), right: { value: 6, op: '/', left: leaf(18), right: leaf(3) } };
  const cfg = E.internal.configFromPayload({});
  assert.equal(E.internal.renderExpr(root, cfg), '2 × (18 ÷ 3)');
  assert.ok(E.internal.validateProblem({ root, text: '2 × 18 ÷ 3', answer: 12 }, cfg).some(s => s.includes('实际乘法')));
});
check('division sampling gives each legal pair exactly one ticket', () => {
  for (const minimum of [0, 1, 3]) {
    const cfg = E.internal.configFromPayload({ min_value: minimum, max_value: 20 });
    const expected = [];
    for (let a = minimum; a <= 20; a++) for (let b = Math.max(1, minimum); b <= 20; b++) {
      if (a % b === 0) expected.push(`${a}/${b}`);
    }
    const actual = expected.map((_, i) => E.internal.genPair(cfg, { randint: (low, high) => {
      assert.equal(low, 0); assert.equal(high, expected.length - 1); return i;
    } }, '/').join('/'));
    assert.deepEqual(actual.sort(), expected.sort());
  }
});
check('insufficient points never alter balance or history', () => {
  const p = P.initial();
  const before = JSON.stringify(p);
  assert.throws(() => P.redeem(p, 'theme-sky'));
  assert.equal(JSON.stringify(p), before);
  assert.throws(() => P.redeem(p, 'missing'));
});
check('redemption at exact price activates theme and writes history', () => {
  const p = P.initial(); p.points = 60;
  P.redeem(p, 'theme-sky');
  assert.equal(p.points, 0);
  assert.equal(p.theme, 'sky');
  assert.deepEqual(p.owned, ['theme-sky']);
  assert.equal(p.history[0].delta, -60);
  assert.throws(() => P.redeem(p, 'theme-sky'));
  assert.equal(p.history.length, 1);
});
check('only owned themes can be used and default is free', () => {
  const p = P.initial();
  assert.throws(() => P.setTheme(p, 'lilac'));
  p.points = 60; P.redeem(p, 'theme-sky'); P.setTheme(p, 'forest');
  assert.equal(p.theme, 'forest'); P.setTheme(p, 'sky'); assert.equal(p.theme, 'sky');
});
check('custom rewards can be redeemed repeatedly with a record each time', () => {
  const p = P.initial(); p.points = 100;
  P.addProduct(p, '一本书', 50);
  const id = p.products[0].id;
  P.redeem(p, id); P.redeem(p, id);
  assert.equal(p.points, 0);
  assert.equal(p.history.length, 2);
  assert.notEqual(p.history[0].id, p.history[1].id);
  assert.throws(() => P.redeem(p, id));
});
check('custom reward validation rejects invalid or excessive entries', () => {
  const p = P.initial();
  for (const price of [0, -1, 1.5, NaN, Infinity, 100000]) assert.throws(() => P.addProduct(p, '书', price));
  assert.throws(() => P.addProduct(p, '', 1));
  assert.throws(() => P.addProduct(p, '字'.repeat(31), 1));
  for (let i = 0; i < 30; i++) P.addProduct(p, `书${i}`, 1);
  assert.throws(() => P.addProduct(p, '超额', 1));
});
check('store restores balance progress ownership theme products and history', () => {
  const data = memory(); const s = new P.Store(data);
  s.transact(p => { P.finish(p, solved(p)); P.addProduct(p, '阅读', 10); });
  s.transact(p => P.redeem(p, p.products[0].id));
  assert.deepEqual(new P.Store(data).profile, s.profile);
});
check('storage write failures roll back rewards and purchases', () => {
  const data = memory(); const s = new P.Store(data);
  s.transact(p => { p.points = 60; });
  data.setItem = () => { throw Error('disk full'); };
  assert.throws(() => s.transact(p => P.redeem(p, 'theme-sky')));
  assert.equal(s.profile.points, 60);
  assert.equal(s.profile.owned.length, 0);
  assert.throws(() => s.transact(p => P.finish(p, solved(p))));
  assert.equal(s.profile.completed[1], undefined);
});
check('stale tabs cannot spend the same points twice', () => {
  const data = memory(); const a = new P.Store(data); const b = new P.Store(data);
  a.transact(p => { p.points = 100; P.addProduct(p, '奖励', 60); });
  b.load();
  a.transact(p => P.redeem(p, p.products[0].id));
  assert.throws(() => b.transact(p => P.redeem(p, p.products[0].id)));
  assert.equal(b.profile.points, 40);
});
check('corrupt or future-version storage is protected from overwrite', () => {
  for (const raw of ['invalid json', '{"version":2,"points":100}']) {
    const data = memory(); data.setItem(P.KEY, raw); const s = new P.Store(data);
    assert.ok(s.warning); assert.throws(() => s.transact(p => { p.points = 1; }));
    assert.equal(data.getItem(P.KEY), raw);
  }
});
check('unavailable storage remains usable with an explicit warning', () => {
  const s = new P.Store(null);
  assert.ok(s.warning);
  s.transact(p => P.finish(p, solved(p)));
  s.transact(p => P.addProduct(p, '奖励', 20));
  assert.equal(s.profile.points, 20);
  assert.equal(s.profile.products.length, 1);
});
check('profile normalization removes invalid values and discontinuous unlocks', () => {
  const p = P.normalize({ version: 1, points: -10, theme: 'sky', owned: ['bad'],
    completed: { 2: { best: 10 } }, products: [{ id: 'evil', name: 'oops', price: -1 }], history: [{ name: 'bad' }] });
  assert.deepEqual(p, P.initial());
});
// 每日练习、错题掌握与学习统计的业务边界。
const day1 = new Date(2026,9,28,23,59), day2 = new Date(2026,9,29,0,1);
function attempt(p, text, answer, value, now=day1) {
  const run = { id:`test-${Math.random()}`, kind:'review', startedAt:now.getTime(),
    problems:[{text,answer}], answers:[], settled:false };
  P.answer(run,value); P.recordAnswer(p,run,now); return run;
}
function dailySolved(p,now=day1) {
  const run=P.createLearningRun(p,'daily',E);
  for (const q of run.problems) { P.answer(run,q.answer); P.recordAnswer(p,run,now); }
  return run;
}
check('old profiles keep points themes levels and get empty learning fields',()=>{
  const p=P.initial(); P.finish(p,solved(p)); p.points=200; P.redeem(p,'theme-sky');
  delete p.learning; const migrated=P.normalize(JSON.parse(JSON.stringify(p)));
  assert.equal(migrated.points,140); assert.equal(migrated.theme,'sky'); assert.equal(migrated.completed[1].best,10);
  assert.deepEqual(migrated.learning,P.learningInitial());
});
check('daily generates ten unique valid questions without unlocking levels',()=>{
  const p=P.initial(),r=P.createLearningRun(p,'daily',E);
  assert.equal(r.problems.length,10); assert.equal(new Set(r.problems.map(x=>x.text)).size,10);
  for (const q of r.problems) assert.equal(E.internal.evalText(q.text).value,q.answer);
  assert.equal(r.kind,'daily'); assert.deepEqual(p.completed,{});
  assert.throws(()=>P.createLearningRun(p,'invalid',E)); assert.throws(()=>P.createLearningRun(p,'review',E));
});
check('wrong answers persist immediately and identical problems merge',()=>{
  const p=P.initial(); attempt(p,'8 + 7',15,14); attempt(p,'8 + 7',15,13);
  assert.equal(p.learning.total,2); assert.equal(p.learning.correct,0); assert.equal(p.learning.mistakes.length,1);
  assert.equal(p.learning.mistakes[0].errors,2); assert.equal(p.learning.mistakes[0].wrong,13);
  assert.deepEqual(P.normalize(JSON.parse(JSON.stringify(p))).learning,p.learning);
});
check('three consecutive correct answers master a mistake and errors reactivate it',()=>{
  const p=P.initial(); attempt(p,'8 + 7',15,14);
  for (let i=0;i<2;i++) attempt(p,'8 + 7',15,15);
  assert.equal(P.pendingMistakes(p).length,1);
  attempt(p,'8 + 7',15,14); assert.equal(p.learning.mistakes[0].streak,0);
  for (let i=0;i<3;i++) attempt(p,'8 + 7',15,15);
  assert.equal(P.pendingMistakes(p).length,0);
  attempt(p,'8 + 7',15,14); assert.equal(P.pendingMistakes(p).length,1);
});
check('daily inserts up to three pending mistakes and review only pending ones',()=>{
  const p=P.initial(); for(let i=1;i<=12;i++) attempt(p,`${i} + 1`,i+1,0);
  const d=P.createLearningRun(p,'daily',E),r=P.createLearningRun(p,'review',E);
  assert.equal(d.problems.length,10); assert.equal(new Set(d.problems.map(x=>x.text)).size,10);
  assert.equal(r.problems.length,10);
  for (const q of d.problems.slice(0,3)) assert.ok(p.learning.mistakes.some(m=>m.text===q.text));
  for (const q of r.problems) assert.ok(p.learning.mistakes.some(m=>m.text===q.text));
});
check('per-answer receipts prevent duplicate counts and invalid input leaves no record',()=>{
  const p=P.initial(),r=attempt(p,'6 ÷ 2',3,3);
  P.recordAnswer(p,r,day1); assert.equal(p.learning.total,1);
  assert.throws(()=>P.answer(r,'')); assert.equal(p.learning.total,1);
});
check('daily reward is once per local day across runs reloads and tabs',()=>{
  const data=memory(),a=new P.Store(data),b=new P.Store(data);
  const first=dailySolved(a.profile); assert.equal(a.transact(p=>P.finishLearning(p,first,day1)).reward,10);
  b.load(); const second=dailySolved(b.profile);
  assert.equal(b.transact(p=>P.finishLearning(p,second,day1)).reward,0);
  const c=new P.Store(data); const third=dailySolved(c.profile,day2);
  assert.equal(c.transact(p=>P.finishLearning(p,third,day2)).reward,10); assert.equal(c.profile.points,20);
  assert.equal(c.profile.history.length,2); assert.deepEqual(c.profile.completed,{});
});
check('midnight completion rewards completion day and backward clock cannot reward again',()=>{
  const p=P.initial(),r=dailySolved(p);
  assert.equal(P.finishLearning(p,r,day2).reward,10); assert.equal(p.learning.dailyRewardDay,'2026-10-29');
  assert.equal(P.finishLearning(p,dailySolved(p),day1).reward,0);
  assert.equal(P.finishLearning(p,dailySolved(p,day2),day2).reward,0);
});
check('unfinished runs and duplicate completion cannot give rewards or sessions',()=>{
  const p=P.initial(),r=P.createLearningRun(p,'daily',E);
  assert.throws(()=>P.finishLearning(p,r,day1)); assert.equal(p.points,0); assert.equal(p.learning.sessions.length,0);
  const done=dailySolved(p); P.finishLearning(p,done,day1);
  assert.throws(()=>P.finishLearning(p,done,day1)); assert.equal(p.learning.sessions.length,1); assert.equal(p.points,10);
});
check('review gives no points and records duration and correctness',()=>{
  const p=P.initial(),r=attempt(p,'8 + 7',15,14);
  P.finishLearning(p,r,day1); assert.equal(p.points,0); assert.equal(p.learning.sessions[0].score,0);
  assert.equal(p.learning.sessions[0].seconds,0);
});
check('operation counters support unicode minus and mixed operations without double counting',()=>{
  const p=P.initial(); attempt(p,'9 − 2',7,7); attempt(p,'2 × 3 + 4',10,9); attempt(p,'1 + 2 + 3',6,6);
  assert.deepEqual(p.learning.ops['-'],{total:1,correct:1}); assert.deepEqual(p.learning.ops['*'],{total:1,correct:0});
  assert.deepEqual(p.learning.ops['+'],{total:2,correct:1}); assert.equal(p.learning.total,3);
});
check('recent week and streak use local calendar days including month boundaries',()=>{
  const p=P.initial();
  for(const date of [new Date(2026,8,30,23),new Date(2026,9,1,1),new Date(2026,9,2,12)]) attempt(p,'2 + 3',5,5,date);
  const s=P.learningSummary(p,new Date(2026,9,3,1));
  assert.equal(s.streak,3); assert.equal(s.recent,3); assert.equal(s.correct,3); assert.equal(s.activeDays,3);
  assert.equal(P.learningSummary(p,new Date(2026,9,4,1)).streak,0);
});
check('failed writes roll back answer records daily rewards and sessions',()=>{
  const data=memory(),store=new P.Store(data),r=P.createLearningRun(store.profile,'daily',E);
  P.answer(r,0); data.setItem=()=>{throw Error('full')};
  assert.throws(()=>store.transact(p=>P.recordAnswer(p,r,day1))); assert.equal(store.profile.learning.total,0);
  assert.equal(store.profile.learning.mistakes.length,0);
  const done=dailySolved(P.initial()); assert.throws(()=>store.transact(p=>P.finishLearning(p,done,day1)));
  assert.equal(store.profile.points,0); assert.equal(store.profile.learning.dailyRewardDay,''); assert.equal(store.profile.learning.sessions.length,0);
});
check('normalization rejects damaged learning data and retains legitimate counts',()=>{
  const p=P.initial(); p.learning={total:10,correct:20,days:{oops:{total:3},'2026-02-30':{total:3}},
    mistakes:[{text:'broken',answer:2,wrong:3,errors:1,streak:0,day:'2026-10-28'}],sessions:[{id:'bad'}],receipts:[null],dailyRewardDay:'oops'};
  const l=P.normalize(p).learning; assert.equal(l.total,10); assert.equal(l.correct,10);
  assert.deepEqual(l.days,{}); assert.deepEqual(l.mistakes,[]); assert.deepEqual(l.sessions,[]); assert.deepEqual(l.receipts,[]);
});
check('history limits preserve cumulative counters and pending mistake retention',()=>{
  const p=P.initial();
  for(let i=0;i<370;i++) { const d=new Date(2025,0,1+i,12); const r=attempt(p,'2 + 3',5,5,d); P.finishLearning(p,r,d); }
  assert.equal(Object.keys(p.learning.days).length,365); assert.equal(p.learning.sessions.length,100); assert.equal(p.learning.total,370);
  for(let i=0;i<510;i++) attempt(p,`1 + ${i % 99} + 0${' '.repeat(Math.floor(i/99))}`,1+i%99,0);
  assert.equal(p.learning.mistakes.length,500);
});
// 输出题目供 Python 独立校验器复核全部关卡，含自建的表内除法题。
const samples = [];
for (let trial = 0; trial < 10; trial++) {
  const p = P.initial();
  for (const l of P.LEVELS) {
    const run = solved(p, l.id);
    samples.push({ config: P.levelConfig(l.id), problems: run.problems });
    P.finish(p, run);
  }
}
process.stdout.write(JSON.stringify({ cases, samples }));
