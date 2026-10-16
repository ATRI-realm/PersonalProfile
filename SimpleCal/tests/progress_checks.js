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
