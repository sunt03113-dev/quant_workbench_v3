
const API = "http://127.0.0.1:8000";

// ===================== 元素引用 =====================
const homeEl = document.getElementById('homePage');
const detailEl = document.getElementById('detailPage');
const matrixEl = document.getElementById('matrix');
const backBtn = document.getElementById('backHome');
const homeActions = document.getElementById('homeActions');
const addGroupTop = document.getElementById('addGroupTop');
const addModelBtn = document.getElementById('addModelBtn');
const addCategoryBtn = document.getElementById('addCategoryBtn');
const addModelModal = document.getElementById('addModelModal');
const addModelClose = document.getElementById('addModelClose');
const addModelCancel = document.getElementById('addModelCancel');
const addModelCreate = document.getElementById('addModelCreate');
const newModelName = document.getElementById('newModelName');
const newModelCategory = document.getElementById('newModelCategory');
const newCatRow = document.getElementById('newCatRow');
const newCatName = document.getElementById('newCatName');
const addModelError = document.getElementById('addModelError');
const trashBtn = document.getElementById('trashBtn');
const trashModal = document.getElementById('trashModal');
const trashList = document.getElementById('trashList');
const trashClose = document.getElementById('trashClose');
const confirmRuleEdit = document.getElementById('confirmRuleEdit');
const ruleTextarea = document.getElementById('ruleTextarea');
const detailTitle = document.getElementById('detailTitle');
const candThead = document.getElementById('candThead');
const candTbody = document.getElementById('candTbody');
const downloadBtn = document.getElementById('downloadBtn');
const askModelBtn = document.getElementById('askModelBtn');
const dataFreshChip = document.getElementById('dataFreshChip');
const universePicker = document.getElementById('universePicker');
const submitStatus = document.getElementById('submitStatus');
const confirmationArea = document.getElementById('confirmationArea');
const previewArea = document.getElementById('previewArea');
const previewSubmitBtn = document.getElementById('previewSubmitBtn');
const batchRunBtn = document.getElementById('batchRunBtn');

let currentCard = null;
let currentRuleStem = null;
let selectedUniverse = null;
let currentPreview = null;  // 存储当前 preview 的完整信息（preview_id + hashes）
let currentGenericPlan = null;  // 通用事件图执行器（Strategy Plan）识别结果

async function apiFetch(path, opts) {
  const resp = await fetch(API + path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = typeof data.detail === 'object'
      ? (data.detail.message || JSON.stringify(data.detail))
      : (data.detail || resp.statusText);
    throw new Error(msg);
  }
  return data;
}

// ===================== 状态模型 =====================
const LS_STATE = 'qw_state_v3';
const TRASH_KEEP_MS = 90 * 24 * 3600 * 1000;

// 转义函数改为 FLOW CORE 内的函数声明（见下方 FLOW CORE 区块），此处不再重复定义。

function seedState() {
  const card = c => (typeof c === 'string'
    ? { id: c, name: c, ruleStem: null, desc: '' } : c);
  const g = (id, cards) => ({ id, name: id, cards: cards.map(card) });
  return {
    groups: [
      g('3',   ['3-1A', '3-1B', '3-1C', '3-1D', '3-1E', '3-1F', '311A', '311B', '321', '3111']),
      g('1/2', ['111A', '111B', '121', '211A', '211B1', '211B2']),
      g('1Z',  ['1Z1A', '1Z1B', '1Z1C', '1Z1D', '1Z1E', '1Z1F', '1Z1G', '1Z2', '1Z3']),
      g('1S',  [{ id: '1S1', name: '1S1', ruleStem: 'strategy_10cm_v6', desc: 'strategy_10cm_v6' },
               '1S2A1', '1S2A2', '1S2A3', '1S2B1', '1S2B2', '1S3A1', '1S3A2',
               '1S3B1', '1S3B2', '1S4A', '1S4B', '1S4C']),
      g('2S1', [{ id: '2S1', name: '2S1', ruleStem: 'strategy_20cm_v1', desc: 'strategy_20cm_v1' }]),
      g('2S2/2S3', ['2S2A2a', '2S2A2b', '2S2B1', '2S2B2a', '2S2B2b', '2S2C1', '2S2C2a', '2S2C2b',
                    '2S2D1', '2S2D2a', '2S2D2b', '2S2D3', '2S3A', '2S3B', '2S3C', '2S4A']),
    ],
    trash: [],
  };
}

let state = null;
function loadState() {
  try { state = JSON.parse(localStorage.getItem(LS_STATE) || 'null'); } catch { state = null; }
  if (!state || !Array.isArray(state.groups)) state = seedState();
  if (!Array.isArray(state.trash)) state.trash = [];
}
function saveState() { localStorage.setItem(LS_STATE, JSON.stringify(state)); }

// ===================== 类别排序规则（kk 2026-09-23 定稿） =====================
// 数字从大到小（自然降序），「2S」开头系列固定垫底；新增类别也按此规则插入。
function is2sName(n) { return /^2S/i.test(String(n || '')); }

function catTokens(name) {
  const s = String(name || ''); const parts = []; let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch >= '0' && ch <= '9') {
      let j = i; while (j < s.length && s[j] >= '0' && s[j] <= '9') j++;
      parts.push({ d: parseInt(s.slice(i, j), 10) }); i = j;
    } else { parts.push({ c: ch }); i++; }
  }
  return parts;
}

// 降序比较：>0 表示 a 应排在 b 前面
function cmpCatDesc(a, b) {
  const A = catTokens(a), B = catTokens(b);
  for (let k = 0; k < Math.max(A.length, B.length); k++) {
    const x = A[k], y = B[k];
    if (!x && !y) return 0;
    if (!x) return -1;
    if (!y) return 1;
    if (x.d !== undefined && y.d !== undefined) { if (x.d !== y.d) return y.d - x.d; }
    else if (x.c !== undefined && y.c !== undefined) { if (x.c !== y.c) return y.c.charCodeAt(0) - x.c.charCodeAt(0); }
    else if (x.d !== undefined) return -1; // 同位数字 vs 字符：字符序列优先
    else return 1;
  }
  return 0;
}

function defaultSortGroups(groups) {
  const main = groups.filter(g => !is2sName(g.name)).sort((a, b) => cmpCatDesc(a.name, b.name));
  const tail = groups.filter(g => is2sName(g.name)).sort((a, b) => cmpCatDesc(a.name, b.name));
  return main.concat(tail);
}

// 新类别按规则插入（不整体重排，保留用户拖拽结果）
function insertGroupByRule(g) {
  if (is2sName(g.name)) { state.groups.push(g); return; }
  let idx = state.groups.length;
  for (let i = 0; i < state.groups.length; i++) {
    const n = state.groups[i].name;
    if (is2sName(n)) { idx = i; break; }              // 垫底区之前
    if (cmpCatDesc(g.name, n) > 0) { idx = i; break; } // 插在第一个比它小的前面
  }
  state.groups.splice(idx, 0, g);
}

// 一次性迁移：2S 拆为 2S1 与 2S2/2S3 + 应用默认排序（幂等）
function migrateState() {
  if (state.mig2sSplit) return;
  const g2s = state.groups.find(g => g.name === '2S');
  if (g2s) {
    let g1 = state.groups.find(g => g.name === '2S1');
    let g23 = state.groups.find(g => g.name === '2S2/2S3');
    if (!g1) { g1 = { id: 'g2s1_' + Date.now(), name: '2S1', cards: [] }; state.groups.push(g1); }
    if (!g23) { g23 = { id: 'g2s23_' + Date.now(), name: '2S2/2S3', cards: [] }; state.groups.push(g23); }
    for (const c of g2s.cards.slice()) {
      if (c.name === '2S1' || String(c.name).startsWith('2S1')) g1.cards.push(c);
      else g23.cards.push(c);
    }
    state.groups = state.groups.filter(g => g !== g2s);
  }
  state.groups = defaultSortGroups(state.groups);
  state.mig2sSplit = true;
  saveState();
}

function purgeOldTrash() {
  const before = state.trash.length;
  state.trash = state.trash.filter(t => Date.now() - t.deletedAt < TRASH_KEEP_MS);
  if (state.trash.length !== before) saveState();
}

// ＋ 菜单：hover 之外的点击切换兜底（点外部关闭）
addGroupTop.addEventListener('click', (e) => {
  e.stopPropagation();
  document.querySelector('.plus-menu').classList.toggle('show');
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.plus-wrap'))
    document.querySelector('.plus-menu').classList.remove('show');
});

// ===================== 首页渲染 =====================
function renderHome() {
  matrixEl.innerHTML = '';
  for (const g of state.groups) matrixEl.appendChild(renderGroup(g));
}

function renderGroup(g) {
  const sec = document.createElement('section');
  sec.className = 'group';
  sec.dataset.gid = g.id;
  sec.innerHTML = `
    <div class="side group-header" draggable="true" title="拖动调整类别顺序 · 点击名称重命名">
      <div class="gname" data-gname="${esc(g.name)}">${esc(g.name)}</div>
      <div class="count">${g.cards.length}</div>
      <button class="group-more" title="类别管理" data-gid="${esc(g.id)}">⋯</button>
    </div>
    <div class="grid group-card-container">
      ${g.cards.map(c => `
        <div class="card" data-cid="${esc(c.id)}" data-stem="${esc(c.ruleStem || '')}" draggable="true">
          <button class="card-more" title="模型管理" data-cid="${esc(c.id)}">⋯</button>
          <div class="rule-name">${esc(c.name)}</div>
          <div class="rule-stock empty"></div>
        </div>`).join('')}
      ${g.cards.length === 0 ? '<div class="empty-hint" style="grid-column:1/-1;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:12px">暂无模型，点击右上角＋新增（或拖入卡片）</div>' : ''}
    </div>`;
  attachGroupEvents(sec, g);
  return sec;
}

function attachGroupEvents(div, g) {
  const container = div.querySelector('.group-card-container');
  const header = div.querySelector('.group-header');

  div.addEventListener('click', (e) => {
    // 「⋯」管理按钮与其菜单上的点击不得触发其他动作
    if (e.target.closest('.card-more') || e.target.closest('.card-menu') || e.target.closest('.group-more')) return;
    // 点击类别名 → 重命名
    const gname = e.target.closest('.gname');
    if (gname) { renameGroup(g); return; }
    const cardEl = e.target.closest('.card');
    if (cardEl) {
      const card = g.cards.find(c => c.id === cardEl.dataset.cid);
      if (!card) return;
      // 点击模型名 → 重命名；点击卡片其余区域 → 进入详情
      if (e.target.closest('.rule-name')) { renameCard(g, card); return; }
      openDetail(card);
    }
  });

  // 卡片拖拽（组内排序 + 跨组移动）
  container.addEventListener('dragstart', (e) => {
    const el = e.target.closest('.card');
    if (!el) return;
    dragCardEl = el; dragFromGroup = g;
    el.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  container.addEventListener('dragover', (e) => {
    if (!dragCardEl) return;
    e.preventDefault();
    const target = e.target.closest('.card');
    if (!target || target === dragCardEl) return;
    const rect = target.getBoundingClientRect();
    const after = (e.clientY - rect.top) > rect.height / 2;
    container.insertBefore(dragCardEl, after ? target.nextSibling : target);
  });
  container.addEventListener('dragleave', (e) => {
    if (!dragCardEl) return;
    if (!container.contains(e.relatedTarget)) container.appendChild(dragCardEl);
  });

  // 类别拖拽（把手 = 左侧类别头）
  header.addEventListener('dragstart', (e) => {
    dragGroupEl = div;
    div.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  header.addEventListener('dragend', () => {
    if (dragGroupEl === div) {
      div.classList.remove('dragging');
      dragGroupEl = null;
      syncOrderFromDOM();
    }
  });

  div.addEventListener('dragend', () => {
    if (dragCardEl) {
      dragCardEl.classList.remove('dragging');
      dragCardEl = null; dragFromGroup = null;
      syncOrderFromDOM();
    }
  });
}

let dragCardEl = null, dragFromGroup = null, dragGroupEl = null;

function renameGroup(g) {
  const name = prompt('重命名类别：', g.name);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) { showToast('类别名不能为空'); return; }
  if (trimmed === g.name) return;
  if (state.groups.some(x => x !== g && x.name === trimmed)) {
    showToast(`类别「${trimmed}」已存在`); return;
  }
  g.name = trimmed;
  saveState(); renderHome();
  showToast(`类别已重命名为「${trimmed}」`, 2500);
}

function renameCard(g, c) {
  const name = prompt('重命名模型：', c.name);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) { showToast('模型名不能为空'); return; }
  if (trimmed === c.name) return;
  const all = state.groups.flatMap(x => x.cards);
  if (all.some(x => x !== c && x.name === trimmed)) {
    showToast(`模型「${trimmed}」已存在`); return;
  }
  c.name = trimmed;
  saveState(); renderHome();
  showToast(`模型已重命名为「${trimmed}」`, 2500);
}

// 类别拖拽跨组悬停：插入到目标组之前/之后
matrixEl.addEventListener('dragover', (e) => {
  if (!dragGroupEl) return;
  e.preventDefault();
  const over = e.target.closest('.group');
  if (!over || over === dragGroupEl || over.parentElement !== matrixEl) return;
  const rect = over.getBoundingClientRect();
  const after = (e.clientY - rect.top) > rect.height / 2;
  matrixEl.insertBefore(dragGroupEl, after ? over.nextSibling : over);
});

function syncOrderFromDOM() {
  const domGroups = [...matrixEl.querySelectorAll(':scope > .group')];
  const ordered = [];
  // 先收集所有卡片对象（支持跨组移动：以 DOM 归属为准重新分组）
  const allCards = new Map(state.groups.flatMap(g => g.cards.map(c => [c.id, c])));
  for (const dg of domGroups) {
    const g = state.groups.find(x => x.id === dg.dataset.gid);
    if (!g) continue;
    g.cards = [...dg.querySelectorAll('.card')]
      .map(el => allCards.get(el.dataset.cid)).filter(Boolean);
    const hint = dg.querySelector('.empty-hint');
    if (hint && g.cards.length) hint.remove();
    ordered.push(g);
  }
  for (const g of state.groups) if (!ordered.includes(g)) ordered.push(g);
  state.groups = ordered;
  saveState();
}

// ===================== ＋ 菜单操作 =====================
// --- 增加模型：自定义弹窗 ---
function openAddModelModal() {
  // 填充类别下拉（动态读取 state）
  newModelCategory.innerHTML = state.groups.map(g =>
    `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('') +
    '<option value="__new__">＋ 新增类别...</option>';
  // 默认选第一个
  newModelCategory.selectedIndex = 0;
  // 重置表单
  newModelName.value = '';
  newCatName.value = '';
  newCatRow.classList.remove('show');
  addModelError.textContent = '';
  // 显示弹窗
  addModelModal.classList.add('show');
  setTimeout(() => newModelName.focus(), 50);
}

addModelBtn.addEventListener('click', openAddModelModal);

addModelClose.addEventListener('click', () => addModelModal.classList.remove('show'));
addModelCancel.addEventListener('click', () => addModelModal.classList.remove('show'));
addModelModal.addEventListener('click', (e) => { if (e.target === addModelModal) addModelModal.classList.remove('show'); });

// 类别选择变化：选择"新增类别"时显示新类别输入框
newModelCategory.addEventListener('change', () => {
  if (newModelCategory.value === '__new__') {
    newCatRow.classList.add('show');
    setTimeout(() => newCatName.focus(), 50);
  } else {
    newCatRow.classList.remove('show');
  }
  addModelError.textContent = '';
});

// 创建模型
addModelCreate.addEventListener('click', () => {
  const name = newModelName.value.trim();
  if (!name) { addModelError.textContent = '模型名称不能为空'; newModelName.focus(); return; }

  // 检查模型名是否重复（跨所有类别）
  const allCards = state.groups.flatMap(g => g.cards);
  if (allCards.some(c => c.name === name)) {
    addModelError.textContent = `模型名称「${name}」已存在，请换一个`;
    newModelName.focus();
    return;
  }

  let targetGroup;
  if (newModelCategory.value === '__new__') {
    const catName = newCatName.value.trim();
    if (!catName) { addModelError.textContent = '新类别名称不能为空'; newCatName.focus(); return; }
    // 检查类别名是否重复
    if (state.groups.some(g => g.name === catName)) {
      addModelError.textContent = `类别「${catName}」已存在，请直接从下拉选择`;
      newCatName.focus();
      return;
    }
    // 创建新类别（按排序规则插入位置）
    targetGroup = { id: 'g' + Date.now(), name: catName, cards: [] };
    insertGroupByRule(targetGroup);
  } else {
    targetGroup = state.groups.find(g => g.id === newModelCategory.value);
    if (!targetGroup) { addModelError.textContent = '请选择有效的类别'; return; }
  }

  // 创建模型
  targetGroup.cards.push({ id: 'c' + Date.now(), name, ruleStem: null, desc: '' });
  saveState();
  renderHome();
  loadCardStocks();
  addModelModal.classList.remove('show');
  showToast(`已新增模型【${name}】`, 2500);
});

// 回车键提交
newModelName.addEventListener('keydown', (e) => { if (e.key === 'Enter') addModelCreate.click(); });
newCatName.addEventListener('keydown', (e) => { if (e.key === 'Enter') addModelCreate.click(); });

// --- 增加类别：保留独立入口（prompt 即可，本次只改模型弹窗）---
addCategoryBtn.addEventListener('click', () => {
  const name = prompt('请输入新类别名称：');
  if (!name?.trim()) return;
  if (state.groups.some(g => g.name === name.trim())) {
    showToast(`类别「${name.trim()}」已存在`);
    return;
  }
  insertGroupByRule({ id: 'g' + Date.now(), name: name.trim(), cards: [] });
  saveState(); renderHome();
  showToast(`已新增类别【${name.trim()}】`, 2500);
});

// ===================== 回收箱 =====================
trashBtn.addEventListener('click', () => { renderTrash(); trashModal.classList.add('show'); });
trashClose.addEventListener('click', () => trashModal.classList.remove('show'));
trashModal.addEventListener('click', (e) => { if (e.target === trashModal) trashModal.classList.remove('show'); });

function renderTrash() {
  if (!state.trash.length) {
    trashList.innerHTML = '<div style="color:#ccc;font-size:13px">回收站为空</div>';
    return;
  }
  trashList.innerHTML = state.trash.map((t, i) => {
    const name = t.type === 'group' ? t.group.name : t.card.name;
    const type = t.type === 'group' ? '类别' : '模型';
    const extra = t.type === 'card' ? `（原属：${esc(t.fromGroupName)}）` : '';
    const date = new Date(t.deletedAt).toLocaleDateString('zh-CN');
    const days = Math.floor((Date.now() - t.deletedAt) / 86400000);
    return `<div class="trash-item">
      <span><i class="fa ${t.type === 'group' ? 'fa-folder-open' : 'fa-file-text-o'}" style="color:#ccc;margin-right:6px"></i>
        <span style="font-weight:500">${esc(name)}</span>
        <span style="font-size:11px;color:#999;margin-left:4px">${type}${extra} · ${date}（${days}天前）</span></span>
      <span style="display:flex;gap:6px">
        <button class="trash-restore" onclick="restoreTrash(${i})">恢复</button>
        <button class="trash-delete" onclick="deleteTrashForever(${i})">彻底删除</button>
      </span></div>`;
  }).join('');
}

window.restoreTrash = function (i) {
  const t = state.trash[i];
  if (!t) return;
  if (t.type === 'card') {
    const target = state.groups.find(g => g.id === t.fromGroupId) || state.groups[0];
    if (!target) { showToast('暂无可用类别，请先创建类别'); return; }
    target.cards.push({ ...t.card });
  } else {
    state.groups.push(JSON.parse(JSON.stringify(t.group)));
  }
  state.trash.splice(i, 1);
  saveState(); renderHome(); renderTrash();
};

window.deleteTrashForever = function (i) {
  const t = state.trash[i];
  if (!t) return;
  const name = t.type === 'group' ? t.group.name : t.card.name;
  if (!confirm(`彻底删除【${name}】？此操作不可恢复。`)) return;
  state.trash.splice(i, 1);
  saveState(); renderTrash();
};

// ===================== 详情页 =====================
// 模型 → 稳定 stem_base：由卡片唯一 ID 推导（小写字母/数字），保证同一模型多次提交
// 永远落到同一个 strategy_<base>_v1.yaml，不再依赖 LLM 返回的 strategy_id。
function cardStemBase(card) {
  const base = (card?.id || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  return base.length >= 2 ? base : ('m' + Date.now());
}

function rulesToNL(baseRules) {
  const dayName = k => {
    const n = parseInt(k.split('_').pop(), 10);
    return n === 0 ? '基准日(D-0)' : `前${n}日(D-${n})`;
  };
  const condText = c => {
    const parts = [];
    if ('limit_up' in c) parts.push(c.limit_up ? '涨停' : '非涨停');
    if (c.amount_max20) parts.push('成交额为近20日最大');
    if (c.amount_not_max20) parts.push('成交额非20日最大');
    if (c.high_max20) parts.push('最高价为近20日最高');
    if (c.high_not_max20) parts.push('最高价非近20日最高');
    return parts.join('且');
  };
  const days = Object.keys(baseRules).sort((a, b) =>
    parseInt(b.split('_').pop(), 10) - parseInt(a.split('_').pop(), 10));
  return days.map(k => `${dayName(k)}${condText(baseRules[k])}`).join('；\n') + '。';
}

async function openDetail(card) {
  currentCard = card;
  currentRuleStem = card.ruleStem || null;
  selectedUniverse = null;
  universePicker.classList.remove('show');
  submitStatus.classList.remove('show');
  submitStatus.innerHTML = '';
  if (typeof _resetFlowUI === 'function') _resetFlowUI();
  if (typeof _setUIState === 'function' && typeof UI_STATES !== 'undefined') {
    _setUIState(UI_STATES.UNSUBMITTED);
  }
  homeActions.style.display = 'none';
  detailTitle.innerText = card.name;
  homeEl.style.display = 'none';
  detailEl.style.display = 'grid';

  if (currentRuleStem) {
    try {
      const d = await apiFetch(`/api/rules/${currentRuleStem}`);
      // 优先回填持久化的规则原文；旧文件无 rule_text 时才从 base_rules 反推
      ruleTextarea.value = d.strategy.rule_text || rulesToNL(d.strategy.base_rules);
    } catch (e) { ruleTextarea.value = ''; }
    loadCandidates(currentRuleStem);
  } else {
    ruleTextarea.value = '';
    downloadBtn.disabled = true;
    askModelBtn.style.display = 'none';
    candThead.innerHTML = '<tr><th>提示</th></tr>';
    candTbody.innerHTML = '<tr><td style="color:#ccc">该模型尚未提交过规则</td></tr>';
  }
  loadFreshChip();
}

backBtn.addEventListener('click', () => {
  homeEl.style.display = 'grid';
  detailEl.style.display = 'none';
  homeActions.style.display = 'flex';
  renderHome();
  loadCardStocks();
});

// ===================== 示例数据（最近 10 条，日期降序） =====================
async function loadCandidates(stem) {
  downloadBtn.disabled = false;
  askModelBtn.style.display = '';
  const modelName = currentCard?.name || stem;
  downloadBtn.onclick = () => {
    const a = document.createElement('a');
    a.href = `${API}/api/backtest/${stem}/candidates/export?model_name=${encodeURIComponent(modelName)}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  candThead.innerHTML = '<tr><th>加载中…</th></tr>';
  candTbody.innerHTML = '';
  try {
    const d = await apiFetch(`/api/backtest/${stem}/candidates?limit=10000`);
    // 按日期列降序（时间倒序），只取最近 10 条；日期列动态识别（D-0日期 / T_2日期 / …）
    const dateCol = d.columns.find(c => String(c).includes('日期'));
    const rows = [...d.rows].sort((a, b) => {
      if (!dateCol) return 0;
      return String(b[dateCol] ?? '').localeCompare(String(a[dateCol] ?? ''));
    }).slice(0, 10);
    candThead.innerHTML = '<tr>' +
      d.columns.map(c => `<th>${esc(c)}</th>`).join('') + '</tr>';
    candTbody.innerHTML = rows.map(r => '<tr>' +
      d.columns.map(c => {
        const v = r[c] ?? '';
        // 百分比字段红色
        const isPct = typeof v === 'string' && v.endsWith('%');
        const cls = isPct ? ' class="red"' : '';
        return `<td${cls}>${esc(v)}</td>`;
      }).join('') + '</tr>').join('');
  } catch (e) {
    candThead.innerHTML = '<tr><th>提示</th></tr>';
    candTbody.innerHTML = `<tr><td style="color:#ccc">${esc(e.message)}</td></tr>`;
  }
}

// ===================== 询问模型（工作台内问答：判定权在后端原引擎，只读） =====================
// 铁律（kk 2026-09-23）：用户除维修外都在工作台内完成质询；后端 /api/ask/row 复用原
// run_plan（收窄宇宙）+ 结果表逐日期比对，结论与数字由代码判定，不一致只报异常不解释。
askModelBtn.addEventListener('click', () => {
  const show = askPanel.style.display === 'none';
  askPanel.style.display = show ? 'block' : 'none';
  if (show) askInput.focus();
});

askSubmit.addEventListener('click', submitAsk);
askInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitAsk(); });

async function submitAsk() {
  const stem = currentRuleStem;
  if (!stem) return;
  const q = askInput.value.trim();
  askSubmit.disabled = true;
  askAnswer.style.display = 'block';
  askAnswer.innerHTML = '<span style="color:#999">核验中…（单股收窄宇宙重跑原引擎 + 与已存结果逐日期比对，通常数秒）</span>';
  try {
    const d = await apiFetch('/api/ask/row', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stem, query: q || null })
    });
    renderAskAnswer(d);
  } catch (e) {
    askAnswer.innerHTML = `<span style="color:#c0392b">✕ ${esc(e.message)}</span>`;
  } finally {
    askSubmit.disabled = false;
  }
}

function renderAskAnswer(d) {
  const mismatch = d.consistency === 'RERUN_VS_STORED_MISMATCH';
  const vColor = mismatch ? '#c0392b' : '#1a7f4b';
  let html = `<div style="font-weight:600;color:${vColor};margin-bottom:6px">${mismatch ? '⚠️ ' : ''}${esc(d.verdict || '')}</div>`;
  const bits = [`universe=${esc(d.universe || '')}`, d.in_pool ? '在池' : '不在池'];
  if (d.name_resolved) bits.push(`${esc(d.name_resolved.name)} → ${esc(d.name_resolved.code)}`);
  html += `<div style="color:#888;margin-bottom:6px">${bits.join(' · ')}</div>`;
  const v = d.values_at_date;
  if (v) {
    html += '<table style="border-collapse:collapse;font-size:12px;margin:6px 0">' +
      '<tr>' + ['开盘', '最高', '最低', '收盘', '前收', '涨停价(20%)', '成交额', '成交额20日最大', '最高价20日最高']
        .map(h => `<th style="border:1px solid #eee;padding:3px 8px;background:#fafafa">${h}</th>`).join('') + '</tr><tr>' +
      [v.open, v.high, v.low, v.close, v.prev_close, v.limit_price_20pct, v.amount,
       v.amount_is_20d_max ? '是' : '否', v.high_is_20d_max ? '是' : '否']
        .map(x => `<td style="border:1px solid #eee;padding:3px 8px;text-align:center">${esc(String(x ?? '—'))}</td>`).join('') +
      '</tr></table>';
  }
  if (d.rerun) {
    const hits = d.rerun.hit_dates || [];
    const shown = hits.slice(0, 20).join('、') + (hits.length > 20 ? ` 等 ${hits.length} 个` : '');
    html += `<div>重跑命中 ${d.rerun.n_hit_dates} 个日期${shown ? '：' + esc(shown) : ''}；复核违例 ${d.rerun.recheck_violations}。</div>`;
  }
  if (d.stored_table) {
    html += `<div>已存结果：该股 ${d.stored_table.n_rows_this_stock} 行 / 全表 ${d.stored_table.n_rows_total} 行；一致性=${esc(d.consistency)}。</div>`;
  }
  if (d.diff && (d.diff.rerun_only.length || d.diff.stored_only.length)) {
    html += `<div style="color:#c0392b">差异：rerun_only=${esc(JSON.stringify(d.diff.rerun_only))}；stored_only=${esc(JSON.stringify(d.diff.stored_only))}</div>`;
  }
  html += `<details style="margin-top:6px"><summary style="cursor:pointer;color:#888">核验证据（原始 JSON）</summary>` +
    `<pre style="background:#fafafa;padding:8px;border-radius:6px;overflow:auto;max-height:300px;font-size:11px">${esc(JSON.stringify(d, null, 1))}</pre></details>`;
  askAnswer.innerHTML = html;
}

// ===================== 数据新鲜度 =====================
let freshToastTimer = null;

function showToast(msg, ms = 4000, variant = '') {
  let el = document.getElementById('toast');
  if (!el) { el = document.createElement('div'); el.id = 'toast'; document.body.appendChild(el); }
  el.className = variant === 'ok' ? 'ok' : variant === 'err' ? 'err' : '';
  const icon = variant === 'ok' ? 'fa-check-circle'
             : variant === 'err' ? 'fa-times-circle' : 'fa-exclamation-circle';
  el.innerHTML = `<i class="fa ${icon}"></i> ${msg}`;
  el.style.display = 'block';
  clearTimeout(freshToastTimer);
  freshToastTimer = setTimeout(() => { el.style.display = 'none'; }, ms);
}

async function loadFreshChip() {
  try {
    const d = await apiFetch('/api/data/latest');
    dataFreshChip.innerText = `◉ 数据截至 ${d.latest_date ?? '无数据'}`;
    if (d.stale) {
      dataFreshChip.style.color = '#e8753b';
      showToast(`今日（${d.today}）行情数据尚未入库，当前按库内最新数据（${d.latest_date}）执行`);
    } else {
      dataFreshChip.style.color = '';
    }
  } catch (e) {
    dataFreshChip.innerText = '◉ 数据状态未知';
  }
}

// ===================== 规则识别 → 澄清 → 确认并回测（统一走 Strategy Plan）=====================
// 正式识别入口：**Builder → Plan → Validator → Reviewer → Ambiguity Resolver**
// （POST /api/plan/recognize）。新自然语言规则不再先走 legacy 转译接口，
// 也不再因为旧 parser / SCL / 模板路径的限制而错误落入「不支持的表达」。

/* ===== FLOW CORE START（纯函数，可独立测试；不得引用 DOM / window）===== */

/** HTML 转义（函数声明会被提升到脚本顶部，全文件可用）。 */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, m =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

const UI_STATES = {
  UNSUBMITTED: 'UNSUBMITTED',   // 从未提交
  EDITED:      'EDITED',        // 提交过，但规则文本又被修改 → 需重新识别
  RECOGNIZING: 'RECOGNIZING',   // 识别中（loading / disabled）
  AMBIGUOUS:   'AMBIGUOUS',     // 存在高影响歧义 → 展示澄清 UI
  READY:       'READY',         // 已确认可执行 → 只保留「确认并回测」
  MULTI_RULE:  'MULTI_RULE',    // 多规则文档 → 逐条展示 / 逐条回测
  FAILED:      'FAILED',        // 识别失败（按真实原因分流）→ 可修改后重新提交
  RUNNING:     'RUNNING',       // 回测运行中
};

/** 按钮可见性/可用性的**唯一**决定处：任何状态都不允许同时出现两个提交动作。 */
function computeActions(state) {
  const st = state || UI_STATES.UNSUBMITTED;
  const recognizing = st === UI_STATES.RECOGNIZING;
  const running = st === UI_STATES.RUNNING;
  return {
    // 「提交规则进行识别」只属于识别前状态
    showRecognize: (st === UI_STATES.UNSUBMITTED || st === UI_STATES.EDITED ||
                    st === UI_STATES.FAILED || recognizing),
    recognizeDisabled: recognizing || running,
    recognizeLabel: recognizing ? '正在识别…' : '提交规则进行识别',
    // 「✓ 确认并回测」只在 READY 出现
    showConfirmBacktest: st === UI_STATES.READY,
    confirmDisabled: running,
    confirmLabel: running ? '正在回测…' : '✓ 确认并回测',
    // 澄清 UI 只在 AMBIGUOUS 出现（此时不再显示识别按钮）
    showAmbiguity: st === UI_STATES.AMBIGUOUS,
    // 多规则：只显示「一键全部回测」，逐条按钮由 renderMultiRule 渲染
    showBatchBacktest: st === UI_STATES.MULTI_RULE,
  };
}

/** 用户修改规则文本后的状态迁移：READY / AMBIGUOUS / FAILED 一律回到 EDITED。 */
function stateAfterEdit(state) {
  const st = state || UI_STATES.UNSUBMITTED;
  if (st === UI_STATES.RECOGNIZING || st === UI_STATES.RUNNING) return st;
  if (st === UI_STATES.UNSUBMITTED) return UI_STATES.UNSUBMITTED;
  return UI_STATES.EDITED;
}

/** 仅「运行态 → 最终完成态」的**首次**跃迁才提示（成功才响铃）。 */
function shouldPlayCompletion(prevStatus, curStatus) {
  return prevStatus === 'running' && curStatus === 'done';
}

/** 完成提示去重器：同一任务只播一次；页面加载已有结果 / 轮询重复返回都不触发。 */
class CompletionAnnouncer {
  constructor() { this._played = new Set(); }
  shouldPlay(key, prevStatus, curStatus) {
    if (!shouldPlayCompletion(prevStatus, curStatus)) return false;
    if (!key) return false;
    if (this._played.has(key)) return false;
    this._played.add(key);
    return true;
  }
  reset() { this._played.clear(); }
}

function completionMessage(nHits) {
  return `✓ 数据提取及回测完成，共命中 ${Number(nHits ?? 0)} 条`;
}

function backtestFailureMessage(err) {
  return `✗ 数据提取/回测失败：${err || '未知错误'}（规则文本已保留，可修改后重试）`;
}

const FAILURE_ICON = {
  AMBIGUOUS: 'fa-question-circle',
  MISSING_BUSINESS_ATOM: 'fa-puzzle-piece',
  MISSING_DATA: 'fa-database',
  INVALID_PLAN: 'fa-exclamation-triangle',
  TECHNICAL_FAILURE: 'fa-refresh',
  UNSAFE_UNKNOWN: 'fa-times-circle',
};

/**
 * 失败按真实原因分流渲染（**没有**任何笼统的『不支持』兜底文案）。
 * 用户只看到 5 个级别：需要确认 / 规则存在冲突 / 缺少计算能力 / 缺少数据 / 请重试。
 * 内部表达（validator code、事件序号、AST、skill id、指纹）**一律不渲染**；
 * 需要点名时只用业务名（缺少能力 / 缺少字段）。
 */
function failureHtml(f) {
  const code = (f && f.code) || 'UNSAFE_UNKNOWN';
  const title = (f && f.title) || '暂时无法安全理解';
  const msg = (f && f.message) || '';
  const hint = (f && f.hint) || '';
  const frag = (f && f.source_fragment) || '';
  const icon = FAILURE_ICON[code] || 'fa-times-circle';
  const d = (f && f.detail) || {};
  let extra = '';
  if (code === 'MISSING_BUSINESS_ATOM' && d.missing_skills && d.missing_skills.length) {
    const names = (d.missing_labels && d.missing_labels.length) ? d.missing_labels : d.missing_skills;
    extra = `缺少业务能力：${names.join('、')}`;
  } else if (code === 'MISSING_DATA' && d.missing_fields && d.missing_fields.length) {
    extra = `缺少数据字段：${d.missing_fields.join('、')}`;
  }
  return `<div class="fail-box fail-${code}">` +
    `<div class="fail-title"><i class="fa ${icon}"></i> ${esc(title)}</div>` +
    (msg ? `<div>${esc(msg)}</div>` : '') +
    (hint ? `<div class="fail-detail">${esc(hint)}</div>` : '') +
    (extra ? `<div class="fail-detail">${esc(extra)}</div>` : '') +
    (frag ? `<div class="fail-detail">原文片段：「${esc(frag)}」</div>` : '') +
    (code === 'TECHNICAL_FAILURE'
      ? '<div class="fail-detail">可直接点击「提交规则进行识别」重试。</div>' : '') +
    '</div>';
}

/* ===== FLOW CORE END ===== */

const announcer = new CompletionAnnouncer();
let uiState = UI_STATES.UNSUBMITTED;
let currentRecognize = null;      // 最近一次 /api/plan/recognize 的完整响应
// currentGenericPlan 在文件头部已声明（{plan, rule_text}），此处不重复声明

function _setUIState(st) { uiState = st; _applyActions(); }

function _applyActions() {
  const a = computeActions(uiState);
  confirmRuleEdit.style.display = a.showRecognize ? '' : 'none';
  confirmRuleEdit.disabled = a.recognizeDisabled;
  confirmRuleEdit.textContent = a.recognizeLabel;
  previewSubmitBtn.style.display = a.showConfirmBacktest ? 'inline-block' : 'none';
  previewSubmitBtn.disabled = a.confirmDisabled;
  previewSubmitBtn.textContent = a.confirmLabel;
  batchRunBtn.style.display = a.showBatchBacktest ? 'inline-block' : 'none';
  if (!a.showAmbiguity) {
    confirmationArea.style.display = 'none';
    confirmationArea.innerHTML = '';
  }
}

function _resetFlowUI() {
  confirmationArea.style.display = 'none';
  confirmationArea.innerHTML = '';
  previewArea.style.display = 'none';
  previewArea.innerHTML = '';
  previewSubmitBtn.style.display = 'none';
  previewSubmitBtn.disabled = false;
  batchRunBtn.style.display = 'none';
  batchRunBtn.disabled = false;
  currentPreview = null;
  currentGenericPlan = null;
}

// ---------------- 完成提示音（浏览器禁止自动播放时静默失败，不影响任务）----------------
let _audioCtx = null;
function playCompletionSound() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return false;
    if (!_audioCtx) _audioCtx = new Ctx();
    if (_audioCtx.state === 'suspended' && _audioCtx.resume) {
      const p = _audioCtx.resume();
      if (p && p.catch) p.catch(() => {});
    }
    const now = _audioCtx.currentTime;
    [[880, 0], [1318.5, 0.17]].forEach(([freq, at]) => {
      const osc = _audioCtx.createOscillator();
      const gain = _audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + at);
      gain.gain.exponentialRampToValueAtTime(0.22, now + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.30);
      osc.connect(gain); gain.connect(_audioCtx.destination);
      osc.start(now + at); osc.stop(now + at + 0.34);
    });
    return true;
  } catch (e) {
    return false;                 // 自动播放被禁 → 静默，不影响任务完成
  }
}

function announceCompletion(key, nHits) {
  playCompletionSound();
  showToast(completionMessage(nHits), 5000, 'ok');
}

// ---------------- 预览渲染 ----------------
// P0-1：预览只渲染**业务语言**（来自 plan_summary），绝不显示 skill id / 内部序号 / AST。
function _eventChips(summary) {
  const s = summary || {};
  return (s.events || []).map(ev => {
    const conds = (ev.conditions || []).join('，');
    const tag = ev.is_condition_event === false ? '（仅输出引用）' : '';
    return `${ev.id}${conds ? '(' + conds + ')' : ''}${tag}`;
  });
}

function _outputChips(summary) {
  const s = summary || {};
  return (s.outputs || []).slice();
}

function _showReadyPlan(plan, review, txt, titleHtml, summary) {
  currentGenericPlan = { plan, rule_text: txt };
  const s = summary || {};
  const sp = plan.strategy_plan || {};
  const rv = review || {};
  const covered = (rv.coverage || []).filter(c => c.status === 'covered').length;
  const total = (rv.coverage || []).length;
  const mis = rv.possible_misinterpretations || [];
  previewArea.style.display = 'block';
  previewArea.innerHTML =
    `<div style="font-size:14px;font-weight:600;color:var(--green);margin-bottom:6px">` +
    `<i class="fa fa-check-circle"></i> ${titleHtml || '系统已理解规则'}</div>` +
    `<div style="font-size:12px;color:#46524d;margin-bottom:4px">板块范围：${esc(s.universe || sp.universe || '—')}</div>` +
    `<div style="font-size:12px;color:#46524d;margin-bottom:4px">事件结构：</div>` +
    `<div style="margin-bottom:6px">${_eventChips(s).map(e => `<span class="chip">${esc(e)}</span>`).join('')}</div>` +
    `<div style="font-size:12px;color:#46524d;margin-bottom:4px">输出字段（含系统默认列）：</div>` +
    `<div style="margin-bottom:6px">${_outputChips(s).map(o => `<span class="chip">${esc(o)}</span>`).join('')}</div>` +
    `<div style="font-size:12px;color:#46524d">语义复核：${covered}/${total} 项约束已覆盖` +
    `${mis.length ? '；提示：' + esc(mis.join('；')) : ''}</div>`;
  _setUIState(UI_STATES.READY);
}

// ---------------- 歧义澄清 UI（一次集中展示所有高影响歧义）----------------
function _renderAmbiguity(d, txt) {
  const rep = d.ambiguity_report || {};
  // 同一歧义不重复展示：按 item.id 去重（同一根因只允许问一次）
  const _seenAmb = new Set();
  const items = (rep.items || []).filter(function (it) {
    const k = it && it.id;
    if (!k || _seenAmb.has(k)) return false;
    _seenAmb.add(k);
    return true;
  });
  if (!items.length) {
    submitStatus.classList.add('show');
    submitStatus.innerHTML = failureHtml(d.failure || { code: 'UNSAFE_UNKNOWN' });
    _setUIState(UI_STATES.FAILED);
    return;
  }
  submitStatus.classList.add('show');
  submitStatus.style.color = '#8A5B00';
  submitStatus.innerHTML = `<i class="fa fa-question-circle"></i> 已识别 ${items.length} 处会影响结果的表述，请一次确认。`;

  confirmationArea.style.display = 'block';
  confirmationArea.innerHTML =
    `<div class="amb-wrap"><div class="amb-head">` +
    `<i class="fa fa-question-circle"></i> 有 ${items.length} 处表述存在多种合理解释` +
    `</div><div class="amb-hint">不同解释会产生不同的回测结果，请逐项选择（或选「其他 / 自定义」）。</div>` +
    `<div class="amb-body">` +
    items.map((it, i) => {
      const loc = it.location || {};
      const frag = loc.snippet || loc.raw || it.description || '';
      const opts = it.candidates.map((c, j) => {
        const checked = c.id === it.default_candidate_id ? ' checked' : '';
        const isCustom = c.id === '__custom__';
        return `<label class="amb-opt${checked ? ' sel' : ''}" data-cand="${esc(c.id)}">` +
          `<input type="radio" name="amb_${i}" value="${esc(c.id)}"${checked}>` +
          `<b>${esc(c.label)}</b>` +
          `<span class="amb-meaning">业务含义：${esc(c.business_meaning)}</span>` +
          (c.result_impact ? `<span class="amb-meaning">结果影响：${esc(c.result_impact)}</span>` : '') +
          `</label>` +
          (isCustom ? `<input type="text" class="amb-custom" data-for="${i}" placeholder="请输入你的解释（例如：只算 D-3 与 D-1 两天）">` : '');
      }).join('');
      return `<div class="amb-item" data-item-id="${esc(it.id)}">` +
        `<div class="amb-q">${i + 1}. ${esc(it.description)}</div>` +
        (frag ? `<div class="amb-loc">位置：<code>${esc(frag)}</code></div>` : '') +
        opts +
        `</div>`;
    }).join('') +
    `</div>` +
    `<div class="amb-actions"><button class="btn-amb" id="ambApplyBtn">应用所选解释并继续</button>` +
    `<span class="amb-hint">确认后系统直接修订执行计划并复核，不会反复追问。</span></div></div>`;

  confirmationArea.querySelectorAll('.amb-item').forEach(el => {
    el.querySelectorAll('input[type=radio]').forEach(r => {
      r.addEventListener('change', () => {
        el.querySelectorAll('.amb-opt').forEach(o => o.classList.remove('sel'));
        const lab = r.closest('.amb-opt');
        if (lab) lab.classList.add('sel');
        const custom = el.querySelector('.amb-custom');
        if (custom) {
          custom.style.display = (r.value === '__custom__') ? 'block' : 'none';
          if (r.value === '__custom__') custom.focus();
        }
      });
    });
  });
  const applyBtn = document.getElementById('ambApplyBtn');
  if (applyBtn) applyBtn.addEventListener('click', () => _applyAmbiguity(d, txt, applyBtn));
  _setUIState(UI_STATES.AMBIGUOUS);
}

async function _applyAmbiguity(d, txt, btn) {
  const choices = [];
  let badCustom = false;
  confirmationArea.querySelectorAll('.amb-item').forEach(el => {
    const picked = el.querySelector('input[type=radio]:checked');
    if (!picked) return;
    const itemId = el.dataset.itemId;
    if (picked.value === '__custom__') {
      const v = (el.querySelector('.amb-custom') || {}).value || '';
      if (!String(v).trim()) { badCustom = true; return; }
      choices.push({ item_id: itemId, candidate_id: '__custom__', custom_text: String(v).trim() });
    } else {
      choices.push({ item_id: itemId, candidate_id: picked.value, custom_text: '' });
    }
  });
  if (badCustom) { showToast('「其他 / 自定义」需要填写具体内容'); return; }
  if (!choices.length) { showToast('请先选择每项的解释'); return; }

  const old = btn.textContent;
  btn.disabled = true; btn.textContent = '正在修订并复核…';
  try {
    const res = await apiFetch('/api/plan/resolve_ambiguity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan: d.plan_draft || d.plan,
        rule_text: txt,
        choices,
        universe_hint: selectedUniverse || '',
      }),
    });
    confirmationArea.style.display = 'none';
    if (res.status === 'READY' && res.plan) {
      submitStatus.style.color = '#2f8a6d';
      submitStatus.innerHTML = '<i class="fa fa-check"></i> 已按你的解释修订执行计划并通过复核。';
      _showReadyPlan(res.plan, res.review, txt, null, res.plan_summary);
    } else {
      submitStatus.style.color = '#f53f3f';
      submitStatus.innerHTML = failureHtml({
        code: 'INVALID_PLAN',
        title: '修订后仍未通过复核',
        message: (res.notes || []).join('；') || res.message || '请修改规则描述后重新提交',
        detail: { errors: res.notes || [] },
      });
      _setUIState(UI_STATES.FAILED);
    }
  } catch (e) {
    submitStatus.style.color = '#f53f3f';
    submitStatus.innerHTML = failureHtml({
      code: 'TECHNICAL_FAILURE', title: '本次规则识别失败，请重试',
      message: '本次规则识别失败，请重试', detail: { raw: e.message },
    });
    _setUIState(UI_STATES.FAILED);
  } finally {
    btn.disabled = false; btn.textContent = old;
  }
}

// ---------------- 单条规则结果分发 ----------------
function _handleSingleRecognize(d, txt) {
  currentRecognize = d;
  const st = d.status;
  if (st === 'READY' && d.plan) {
    submitStatus.classList.add('show');
    submitStatus.style.color = '#2f8a6d';
    submitStatus.innerHTML = '<i class="fa fa-check"></i> 系统已理解规则，确认后即可回测。';
    _showReadyPlan(d.plan, d.review, txt, null, d.plan_summary);
    return;
  }
  if (st === 'NEED_CONFIRMATION') { _renderAmbiguity(d, txt); return; }
  // FAILED / PENDING_CAPABILITY：按真实原因分流
  submitStatus.classList.add('show');
  submitStatus.innerHTML = failureHtml(d.failure || { code: 'UNSAFE_UNKNOWN' });
  _setUIState(UI_STATES.FAILED);
}

// ---------------- 多规则 ----------------
function _renderMultiRule(d, txt) {
  currentRecognize = d;
  const rules = d.rules || [];
  const ready = rules.filter(r => r.status === 'READY');
  previewArea.style.display = 'block';
  previewArea.innerHTML =
    `<div style="font-size:14px;font-weight:600;color:var(--green);margin-bottom:6px">` +
    `<i class="fa fa-check-circle"></i> 已识别 ${rules.length} 条规则` +
    `<span style="font-size:11px;color:#8c95a5;font-weight:400;margin-left:8px">` +
    `本次逐条独立执行，不合并回测</span></div>` +
    rules.map((r, i) => {
      const ok = r.status === 'READY' && r.plan;
      const label = ok ? '已理解，可执行'
        : r.status === 'NEED_CONFIRMATION' ? '需要确认（存在歧义）'
        : r.status === 'PENDING_CAPABILITY' ? '缺少执行能力 / 数据'
        : '识别失败';
      const color = ok ? 'var(--green)' : '#e8753b';
      const detail = ok ? '' : failureHtml(r.failure || { code: 'UNSAFE_UNKNOWN' });
      const chips = ok ? _outputChips(r.plan_summary).map(o => `<span class="chip">${esc(o)}</span>`).join('') : '';
      return `<div class="multi-rule" data-idx="${i}">` +
        `<div class="multi-title" style="color:${color}">${esc(r.rule_name || ('规则' + (i + 1)))} · ${esc(label)}</div>` +
        (ok ? `<div class="multi-meta">输出字段（含系统默认列）：${chips}</div>` : detail) +
        (ok ? `<button class="btn-run multi-run" data-idx="${i}" style="margin-top:4px;height:30px;font-size:12px">✓ 确认并回测</button>` : '') +
        `</div>`;
    }).join('');
  previewArea.querySelectorAll('.multi-run').forEach(b => {
    b.addEventListener('click', async () => {
      const i = parseInt(b.dataset.idx, 10);
      const r = rules[i];
      if (!r || !r.plan) return;
      b.disabled = true; b.textContent = '正在回测…';
      try {
        await _submitGenericPlan(r.plan, r.rule_text || txt, _ruleStem(i));
      } finally { b.disabled = false; b.textContent = '✓ 确认并回测'; }
    });
  });
  submitStatus.classList.add('show');
  submitStatus.style.color = '#2f8a6d';
  submitStatus.innerHTML = `<i class="fa fa-check"></i> 已识别 ${rules.length} 条规则；可逐条确认回测，或一键全部回测。`;
  _setUIState(UI_STATES.MULTI_RULE);
}

function _ruleStem(i) {
  const base = (currentCard ? cardStemBase(currentCard) : 'multi') || 'multi';
  return currentRuleStem || `strategy_${base}_r${i + 1}_v1`;
}

async function _runAllRules() {
  const rules = (currentRecognize && currentRecognize.rules) || [];
  const ready = rules.filter(r => r.status === 'READY' && r.plan);
  if (!ready.length) { showToast('没有可执行的规则'); return; }
  batchRunBtn.disabled = true;
  _setUIState(UI_STATES.RUNNING);
  try {
    for (const r of ready) {
      try { await _submitGenericPlan(r.plan, r.rule_text || '', _ruleStem(r.rule_index ?? 0), false); }
      catch (e) { showToast(`「${r.rule_name}」回测失败：${e.message}`, 4000, 'err'); }
    }
  } finally {
    batchRunBtn.disabled = false;
    _setUIState(UI_STATES.MULTI_RULE);
  }
}

// ---------------- 回测提交（单规则 / 逐规则共用，绝不合并 Plan）----------------
async function _submitGenericPlan(plan, ruleText, stem, persistStem = true) {
  submitStatus.classList.add('show');
  submitStatus.style.color = '#2f8a6d';
  submitStatus.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 正在提取数据并回测…';
  try {
    const d = await apiFetch('/api/plan/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan, rule_text: ruleText || '',
        stem: stem || currentRuleStem || null,
        with_names: true,
      }),
    });
    const v = d.validation || {};
    if (d.status === 'OK' && v.valid) {
      // 用户主动发起 → 运行态首次进入完成态 → 提示**一次**
      const key = 'plan:' + (stem || currentRuleStem || '') + ':' + Date.now();
      if (announcer.shouldPlay(key, 'running', 'done')) announceCompletion(key, d.n_hits);
      submitStatus.style.color = '#22a576';
      submitStatus.innerHTML = `<i class="fa fa-check-circle"></i> ${esc(completionMessage(d.n_hits))}（已通过确定性复核）`;
      _renderGenericHits(d.rows || []);
      if (d.stem) {
        currentRuleStem = d.stem;
        // 回写卡片 -> 持久化 stem：保证重启后该模型的规则/结果仍可从卡片打开
        // （原先只更新内存变量，重载后 ruleStem 仍为 null，见 STEP7 P3 缺陷记录）
        if (currentCard && persistStem) {
          currentCard.ruleStem = d.stem;
          if (!currentCard.desc) currentCard.desc = d.stem;
          saveState();
          renderHome();
        }
        loadCandidates(d.stem);
      }
      return d;
    }
    const codes = [...new Set((v.violations || []).map(x => x.code))].join('、');
    submitStatus.style.color = '#f53f3f';
    submitStatus.innerHTML = `<i class="fa fa-exclamation-triangle"></i> 回测结果未通过确定性复核（${codes || '未知'}），结果不可信，已保留原文。`;
    showToast(backtestFailureMessage('结果未通过确定性复核'), 5000, 'err');
    return d;
  } catch (e) {
    submitStatus.style.color = '#f53f3f';
    submitStatus.innerHTML = `<i class="fa fa-exclamation-triangle"></i> ${esc(backtestFailureMessage(e.message))}`;
    showToast(backtestFailureMessage(e.message), 5000, 'err');
    throw e;
  }
}

function _renderGenericHits(rows) {
  if (!rows || !rows.length) return;
  const keys = Object.keys(rows[0]).filter(k => k !== 'event_rows');
  // 时间倒序：按首个「日期」列降序（D-0日期 / T_2日期 / …）
  const dateKey = keys.find(k => k.includes('日期'));
  if (dateKey) {
    rows = [...rows].sort((a, b) =>
      String(b[dateKey] ?? '').localeCompare(String(a[dateKey] ?? '')));
  }
  const head = keys.map(k => `<th style="padding:4px 8px;text-align:left">${esc(k)}</th>`).join('');
  const body = rows.slice(0, 20).map(r =>
    `<tr>${keys.map(k => `<td style="padding:4px 8px">${esc(String(r[k]))}</td>`).join('')}</tr>`).join('');
  previewArea.style.display = 'block';
  previewArea.innerHTML +=
    `<div style="margin-top:10px;font-size:12px;color:#46524d">命中明细（最多 20 条）：</div>` +
    `<div style="overflow:auto;max-height:260px;margin-top:4px"><table style="border-collapse:collapse;font-size:12px;width:100%">` +
    `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// ---------------- 主入口：识别 ----------------
async function runRecognize() {
  const txt = (ruleTextarea.value || '').trim();
  if (!txt) { showToast('请先输入规则描述'); return; }

  _resetFlowUI();
  _setUIState(UI_STATES.RECOGNIZING);
  submitStatus.classList.add('show');
  submitStatus.style.color = '#2f8a6d';
  submitStatus.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 正在理解规则…';
  try {
    const d = await apiFetch('/api/plan/recognize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ natural_text: txt, universe: selectedUniverse || null }),
    });
    if ((d.n_rules || 1) > 1) { _renderMultiRule(d, txt); return; }
    _handleSingleRecognize(d, txt);
  } catch (e) {
    submitStatus.classList.add('show');
    submitStatus.innerHTML = failureHtml({
      code: 'TECHNICAL_FAILURE', title: '本次规则识别失败，请重试',
      message: '本次规则识别失败，请重试', detail: { raw: e.message },
    });
    _setUIState(UI_STATES.FAILED);
  }
}

confirmRuleEdit.addEventListener('click', runRecognize);

previewSubmitBtn.addEventListener('click', async () => {
  if (!currentGenericPlan) { showToast('请先提交规则进行识别'); return; }
  _setUIState(UI_STATES.RUNNING);
  try {
    await _submitGenericPlan(currentGenericPlan.plan, currentGenericPlan.rule_text,
                             currentRuleStem || _ruleStem(0));
  } catch { /* 已在 _submitGenericPlan 内提示 */ }
  finally { _setUIState(UI_STATES.READY); }
});

batchRunBtn.addEventListener('click', () => { _runAllRules(); });

// 规则文本被修改 → 状态回到 EDITED：恢复「提交规则进行识别」，隐藏旧的「确认并回测」
ruleTextarea.addEventListener('input', () => {
  const next = stateAfterEdit(uiState);
  if (next !== uiState) {
    _resetFlowUI();
    _setUIState(next);
    submitStatus.classList.remove('show');
    submitStatus.innerHTML = '';
  }
});

universePicker.addEventListener('click', (e) => {
  const btn = e.target.closest('.uni-btn');
  if (!btn) return;
  selectedUniverse = btn.dataset.universe;
  universePicker.querySelectorAll('.uni-btn').forEach(b =>
    b.classList.toggle('sel', b === btn));
  // 已选定板块 → 用同一入口重新识别（板块影响涨停价口径，必须重算）
  universePicker.classList.remove('show');
  runRecognize();
});

// ===================== 加载卡片当日新增股票 =====================
// 绿色高亮（.card.active）的唯一业务含义：
//   该 strategy 存在「D-0 日期 == 全局最新交易日」的命中，即最新交易日当天
//   新触发的信号（day_new_hits，后端 store.day_new_hits 计算）。
// 不是「历史有结果 / candidate_count>0 / 本次-上次 diff / 手动重跑差异」。
// 数据源：后端 /api/daily/state（工作日 15:45 每日管线或手动更新后刷新）。
async function loadCardStocks() {
  let state = null;
  try {
    state = await apiFetch('/api/daily/state');
  } catch { /* 后端不可用：卡片保持非高亮，第二行留空 */ }
  const models = (state && state.models) || {};
  document.querySelectorAll('.card[data-stem]').forEach(el => {
    const stem = el.dataset.stem;
    const stockEl = el.querySelector('.rule-stock');
    const m = stem ? models[stem] : null;
    // 当日新增 = 命中行 D-0 日期 == 全局最新交易日；无则留空（不显示占位）
    const names = (m?.day_new_hits || []).map(h => h.name).filter(Boolean);
    // 绿色 = 最新交易日当天确有新触发信号（唯一判据）
    el.classList.toggle('active', names.length > 0);
    if (!stockEl) return;
    if (names.length) {
      stockEl.textContent = names.slice(0, 2).join('、')
        + (names.length > 2 ? ` +${names.length - 2}` : '');
      stockEl.classList.remove('empty');
      stockEl.title = names.join('、');  // 悬停看完整名单
    } else {
      stockEl.textContent = '';
      stockEl.classList.add('empty');
      stockEl.title = '';
    }
  });
}

// ===================== 手动更新数据（P1） =====================
const updateDataBtn = document.getElementById('updateDataBtn');
let updateJobId = null;

updateDataBtn.addEventListener('click', async () => {
  if (updateDataBtn.classList.contains('updating')) return;  // 运行期间禁止重复点击
  updateDataBtn.textContent = '正在更新…';
  updateDataBtn.classList.add('updating');
  try {
    const rep = await apiFetch('/api/daily/run', { method: 'POST' });
    updateJobId = rep.job_id;
    // 轮询任务状态
    const poll = setInterval(async () => {
      try {
        const job = await apiFetch(`/api/daily/jobs/${updateJobId}`);
        if (job.status === 'done') {
          clearInterval(poll);
          updateDataBtn.classList.remove('updating');
          updateDataBtn.classList.add('done');
          updateDataBtn.textContent = '✓ 更新完成';
          await loadCardStocks();
          setTimeout(() => {
            updateDataBtn.classList.remove('done');
            updateDataBtn.textContent = '↻ 更新数据';
          }, 3000);
        } else if (job.status === 'failed') {
          clearInterval(poll);
          updateDataBtn.classList.remove('updating');
          updateDataBtn.textContent = '更新失败';
          showToast(job.error || '更新失败', 4000);
          setTimeout(() => { updateDataBtn.textContent = '↻ 更新数据'; }, 3000);
        }
        } catch {
          // 轮询失败（后端重启/网络中断）：必须恢复按钮，否则永远卡在「正在更新…」
          clearInterval(poll);
          updateDataBtn.classList.remove('updating');
          updateDataBtn.textContent = '↻ 更新数据';
          showToast('更新任务状态查询失败（后端可能已重启或网络中断），请重新点击更新', 4000);
        }
    }, 2000);
  } catch (e) {
    updateDataBtn.classList.remove('updating');
    updateDataBtn.textContent = '更新失败';
    showToast(String(e), 4000);
    setTimeout(() => { updateDataBtn.textContent = '↻ 更新数据'; }, 3000);
  }
});

// ===================== 模型 … 菜单（软删除 / 移入回收站） =====================
document.addEventListener('click', (e) => {
  const moreBtn = e.target.closest('.card-more');
  if (moreBtn) {
    e.stopPropagation();
    const cid = moreBtn.dataset.cid;
    // 关闭其他菜单
    document.querySelectorAll('.card-menu.show').forEach(m => m.classList.remove('show'));
    let menu = moreBtn.nextElementSibling;
    if (!menu || !menu.classList.contains('card-menu')) {
      menu = document.createElement('div');
      menu.className = 'card-menu';
      menu.innerHTML = `<button data-action="rename-model">重命名</button>
        <button class="danger" data-action="delete-model">删除模型</button>`;
      moreBtn.parentNode.appendChild(menu);
    }
    menu.classList.toggle('show');
    menu.querySelector('[data-action="rename-model"]').onclick = () => {
      menu.classList.remove('show');
      const g = state.groups.find(gg => gg.cards.some(c => c.id === cid));
      const c = g && g.cards.find(c => c.id === cid);
      if (g && c) renameCard(g, c);
    };
    menu.querySelector('[data-action="delete-model"]').onclick = () => {
      menu.classList.remove('show');
      deleteCard(cid);
    };
  } else {
    document.querySelectorAll('.card-menu.show').forEach(m => m.classList.remove('show'));
  }

  const groupMore = e.target.closest('.group-more');
  if (groupMore) {
    e.stopPropagation();
    const gid = groupMore.dataset.gid;
    document.querySelectorAll('.card-menu.show').forEach(m => m.classList.remove('show'));
    let menu = groupMore.nextElementSibling;
    if (!menu || !menu.classList.contains('card-menu')) {
      menu = document.createElement('div');
      menu.className = 'card-menu';
      menu.innerHTML = `<button data-action="rename-group">重命名</button>
        <button class="danger" data-action="delete-group">删除类别</button>`;
      groupMore.parentNode.appendChild(menu);
    }
    menu.classList.toggle('show');
    menu.querySelector('[data-action="rename-group"]').onclick = () => {
      menu.classList.remove('show');
      const g = state.groups.find(gg => gg.id === gid);
      if (g) renameGroup(g);
    };
    menu.querySelector('[data-action="delete-group"]').onclick = () => {
      menu.classList.remove('show');
      deleteGroup(gid);
    };
  }
});

function deleteCard(cid) {
  for (const g of state.groups) {
    const idx = g.cards.findIndex(c => c.id === cid);
    if (idx >= 0) {
      const card = g.cards[idx];
      if (!confirm(`确定将模型「${card.name}」移入回收站吗？`)) return;
      g.cards.splice(idx, 1);
      state.trash.push({ type: 'card', card, fromGroupId: g.id, fromGroupName: g.name, deletedAt: Date.now() });
      saveState(); renderHome();
      showToast(`模型「${card.name}」已移入回收站`, 2500);
      return;
    }
  }
}

function deleteGroup(gid) {
  const g = state.groups.find(g => g.id === gid);
  if (!g) return;
  if (g.cards.length > 0) {
    showToast(`该类别下仍有 ${g.cards.length} 个模型，请先移动或删除模型后再删除类别`, 4000);
    return;
  }
  if (!confirm(`确定删除类别「${g.name}」吗？`)) return;
  state.trash.push({ type: 'group', group: JSON.parse(JSON.stringify(g)), deletedAt: Date.now() });
  state.groups = state.groups.filter(x => x.id !== gid);
  saveState(); renderHome();
  showToast(`类别「${g.name}」已删除`, 2500);
}

// ===================== 初始化 =====================
loadState();
purgeOldTrash();
migrateState();
renderHome();
loadCardStocks();
