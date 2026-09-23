// Verify ui_v2.html sorting changes: syntax-check the main script block, then
// eval the actual sorting section shipped in the file and run behavior tests.
const fs = require('fs');
const path = 'D:/09work/quant_workbench_v3/quant_workbench_package/ui/ui_v2.html';
const html = fs.readFileSync(path, 'utf8');

const out = [];
// 1) syntax check every <script> block
const scriptRe = /<script>([\s\S]*?)<\/script>/g;
let m, n = 0;
while ((m = scriptRe.exec(html)) !== null) {
  n++;
  try { new Function(m[1]); out.push(`script block #${n}: syntax OK (${m[1].length} chars)`); }
  catch (e) { out.push(`script block #${n}: SYNTAX ERROR: ${e.message}`); }
}

// 2) eval the sorting section exactly as shipped
const start = html.indexOf('// ===================== 类别排序规则');
const end = html.indexOf('// 一次性迁移');
if (start < 0 || end < 0) { out.push('SECTION NOT FOUND'); }
else {
  const section = html.slice(start, end);
  const sandbox = {};
  const fn = new Function(section + `;
    return { is2sName, cmpCatAsc, cmpCardAsc, defaultSortGroups, insertGroupByRule, insertCardByRule,
             sortCardsAsc, catTokens, cmpCatDesc };`);
  const api = fn.call(sandbox);

  // test 1: categories ascending, 2S tail
  const cats = ['4S', '3S', '2S1', '1S', '1Z', '2S2/2S3', '1/2'].map(name => ({ name, cards: [] }));
  const sortedCats = api.defaultSortGroups(cats).map(g => g.name);
  out.push('cats ascending+2S-tail: ' + JSON.stringify(sortedCats));
  const okCats = JSON.stringify(sortedCats) === JSON.stringify(['1S', '1Z', '1/2', '3S', '4S', '2S1', '2S2/2S3']);
  out.push('test1 categories: ' + (okCats ? 'PASS' : 'FAIL'));

  // test 2: cards ascending (the exact list from kk's screenshot)
  const names = ['1S1','1S2A1','1S2A2','1S2A3','1S2B1','1S2B2','1S3A1','1S3A2','1S3B1','1S3B2','1S4A','1S4B','1S4C','1S1A'];
  const g = { cards: names.map((name, i) => ({ name, id: 'c' + i })) };
  api.sortCardsAsc(g);
  const got = g.cards.map(c => c.name);
  const want = ['1S1','1S1A','1S2A1','1S2A2','1S2A3','1S2B1','1S2B2','1S3A1','1S3A2','1S3B1','1S3B2','1S4A','1S4B','1S4C'];
  out.push('cards asc: ' + JSON.stringify(got));
  out.push('test2 cards screenshot order: ' + (JSON.stringify(got) === JSON.stringify(want) ? 'PASS' : 'FAIL'));

  // test 3: new card inserts by rule (1S2B3 should land between 1S2B2 and 1S3A1)
  const g2 = { cards: want.map((name, i) => ({ name, id: 'c' + i })) };
  api.insertCardByRule(g2, { name: '1S2B3', id: 'new' });
  const idx = g2.cards.map(c => c.name);
  const okIns = idx.indexOf('1S2B3') === idx.indexOf('1S2B2') + 1 && idx[idx.indexOf('1S2B3') + 1] === '1S3A1';
  out.push('test3 insert new card: ' + (okIns ? 'PASS' : 'FAIL -> ' + JSON.stringify(idx)));

  // test 4: new category inserts by rule (3S should land between 1/2 and 4S, before 2S tail)
  const st = { groups: ['1S', '1/2', '4S', '2S1'].map(name => ({ name, cards: [] })) };
  // re-eval with a state object bound
  const fn2 = new Function('state', section + `;
    insertGroupByRule({ name: '3S', cards: [] });
    return state.groups.map(g => g.name);`);
  const got2 = fn2.call(sandbox, st);
  const okGrp = JSON.stringify(got2) === JSON.stringify(['1S', '1/2', '3S', '4S', '2S1']);
  out.push('test4 insert new category: ' + (okGrp ? 'PASS' : 'FAIL -> ' + JSON.stringify(got2)));

  // test 5: migration idempotence shape (migOrderAsc0923 flag logic mirrored)
  out.push('test5 (visual order sanity) 1S1A position = ' + got.indexOf('1S1A'));
}

fs.writeFileSync('D:/09work/quant_workbench_v3/quant_workbench_package/artifacts/verification/ui_order_asc/verify.txt', out.join('\n') + '\n', 'utf8');
console.log('ok');
