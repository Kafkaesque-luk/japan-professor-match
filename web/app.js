/* professor-match terminal — vanilla, no build, backend-agnostic */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const LS = window.localStorage;

  const REGION_LABELS = { hokkaido: '北海道', tohoku: '東北', kanto: '関東', chubu: '中部',
    kinki: '近畿', chugoku: '中国', shikoku: '四国', kyushu: '九州' };
  const TYPE_LABELS = { national: '国公立', private: '私立' };
  const TIERS = [
    { key: 'popular_choices', name: '海选匹配', sub: '最对口' },
    { key: 'niche_research', name: '年富力强', sub: '33–55 岁' },
    { key: 'hidden_gems', name: '潜力洼地', sub: '非顶尖校' },
  ];

  // window.PM_CONFIG (from config.js / inline) sets deployment defaults; localStorage overrides.
  const CFG = window.PM_CONFIG || {};
  const lsBase = LS.getItem('pm_api_base');
  const state = {
    apiBase: lsBase !== null ? lsBase : (CFG.apiBase || ''),
    adminToken: LS.getItem('pm_admin_token') || '',
    matchPath: CFG.matchPath || '/api/match',
    metaMode: CFG.metaMode || 'auto',     // 'auto' = try /api/meta then bundled | 'bundled'
    healthMode: CFG.healthMode || 'auto', // 'auto' = try /api/health | 'none' = skip (live demo)
    meta: null, health: null, result: null,
    sel: { regions: new Set(), ranks: new Set(), types: new Set() },
    activeTier: 'popular_choices',
  };
  const bundledMeta = () => window.PM_META || { regions: [], ranks: [], school_types: [], disciplines: [] };

  function api(path, opts) {
    opts = opts || {};
    const base = state.apiBase.replace(/\/$/, '');
    const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    return fetch(base + path, Object.assign({}, opts, { headers })).then(async (r) => {
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || body.message || (r.status + ' ' + r.statusText));
      // CRMEB-style envelope {status, message, data} (the live PHP demo) -> unwrap.
      if (body && typeof body === 'object' && 'data' in body && 'status' in body && 'message' in body) {
        if (Number(body.status) === 200) return body.data;
        throw new Error(body.message || ('status ' + body.status));
      }
      return body;  // FastAPI returns the result directly
    });
  }

  // ---- helpers ----
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function pct(v) { const n = Number(v) || 0; return Math.round(n <= 1 ? n * 100 : n) + '%'; }
  function errBox(msg) { return '<div class="err" style="margin-bottom:20px">' + esc(msg) + '</div>'; }

  // ---- views ----
  function switchView(v) {
    $$('.tabs button').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
    $('#view-match').hidden = v !== 'match';
    $('#view-setup').hidden = v !== 'setup';
  }

  // ---- filter chips ----
  function chip(group, val, label) {
    const on = state.sel[group].has(val) ? ' on' : '';
    return '<span class="chip' + on + '" data-group="' + group + '" data-val="' + esc(val) + '">' + esc(label) + '</span>';
  }
  function renderChips() {
    const m = state.meta || { regions: [], ranks: [], school_types: [], disciplines: [] };
    $('#rankChips').innerHTML = m.ranks.map((r) => chip('ranks', r, r)).join('');
    $('#regionChips').innerHTML = m.regions.map((r) => chip('regions', r, REGION_LABELS[r] || r)).join('');
    $('#typeChips').innerHTML = m.school_types.map((t) => chip('types', t, TYPE_LABELS[t] || t)).join('');
    $('#discipline').innerHTML = '<option value="">不限（按文本自动识别）</option>'
      + (m.disciplines || []).map((d) => '<option value="' + esc(d) + '">' + esc(d) + '</option>').join('');
  }
  function onChipClick(e) {
    const c = e.target.closest('.chip');
    if (!c) return;
    const set = state.sel[c.dataset.group];
    if (set.has(c.dataset.val)) set.delete(c.dataset.val); else set.add(c.dataset.val);
    c.classList.toggle('on');
  }

  // ---- match ----
  function buildFilters() {
    const unis = $('#universities').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean).slice(0, 3);
    return {
      region: [...state.sel.regions],
      university_ranks: [...state.sel.ranks],
      school_types: [...state.sel.types],
      universities: unis,
      discipline: $('#discipline').value || null,
    };
  }
  function skeleton() {
    let rows = '';
    for (let i = 0; i < 5; i++) {
      rows += '<div class="prof"><div class="prof-main">'
        + '<div class="skeleton" style="height:14px;width:40%"></div>'
        + '<div class="skeleton" style="height:11px;width:25%;margin-top:6px"></div></div></div>';
    }
    return '<div class="card"><div class="school">' + rows + '</div></div>';
  }
  function runMatch() {
    const userInput = $('#userInput').value.trim();
    $('#matchError').innerHTML = '';
    if (!userInput) { $('#matchError').innerHTML = errBox('请先输入研究兴趣'); return; }
    $('#runBtn').disabled = true; $('#runHint').textContent = '匹配中…';
    $('#results').innerHTML = skeleton();
    api(state.matchPath, { method: 'POST', body: JSON.stringify({ user_input: userInput, filters: buildFilters() }) })
      .then((res) => { state.result = res; state.activeTier = 'popular_choices'; renderResults(); })
      .catch((e) => { $('#results').innerHTML = ''; $('#matchError').innerHTML = errBox(e.message); })
      .finally(() => { $('#runBtn').disabled = false; $('#runHint').textContent = ''; });
  }
  function tierCount(key) {
    const groups = (state.result && state.result[key]) || [];
    return groups.reduce((n, g) => n + (g.professor_count || g.professors.length), 0);
  }
  function renderResults() {
    const r = state.result;
    if (!r) return;
    const kw = (r.expanded_keywords || []).filter(Boolean);
    const disc = r.applied_discipline
      ? '<div class="disc-ind">学科方向 <span class="v">' + esc(r.applied_discipline) + '</span>'
        + (r.discipline_source === 'inferred' ? '<span class="auto">自动识别</span>' : '') + '</div>'
      : '';
    const kwHtml = kw.length ? '<div class="kw"><b>扩展关键词：</b>' + kw.map(esc).join('、') + '</div>' : '';
    const tabs = TIERS.map((t) =>
      '<button class="tier-tab ' + (state.activeTier === t.key ? 'active' : '') + '" data-tier="' + t.key + '">'
      + '<span class="t-name">' + t.name + ' <span class="t-count">' + tierCount(t.key) + '</span></span>'
      + '<span class="t-sub">' + t.sub + '</span></button>').join('');
    const groups = r[state.activeTier] || [];
    const body = groups.length ? groups.map(renderSchool).join('')
      : '<div class="empty">该档暂无结果（诚实空桶）。</div>';
    $('#results').innerHTML = '<div class="card">' + disc + kwHtml
      + '<div class="tier-tabs">' + tabs + '</div>' + body + '</div>';
  }
  function renderSchool(g) {
    return '<div class="school"><div class="school-head">'
      + '<span class="school-name">' + esc(g.school_name) + '</span>'
      + '<span class="school-meta">' + (g.professor_count || g.professors.length) + ' 位 · 平均 ' + pct(g.avg_score) + '</span>'
      + '</div>' + g.professors.map(renderProf).join('') + '</div>';
  }
  function renderProf(p) {
    const age = p.age_estimate ? '<span class="badge age">约 ' + p.age_estimate.age + ' 岁</span>' : '';
    const rank = p.school_rank_label ? '<span class="badge rank">' + esc(p.school_rank_label) + '</span>' : '';
    const title = p.position ? '<div class="prof-title">' + esc(p.position) + '</div>' : '';
    return '<div class="prof"><div class="prof-main">'
      + '<div class="prof-name">' + esc(p.store_name || '—') + '</div>' + title + '</div>'
      + '<div class="badges">' + age + rank + '<span class="badge score">' + pct(p.match_score) + '</span></div></div>';
  }
  function onTierClick(e) {
    const t = e.target.closest('.tier-tab');
    if (!t) return;
    state.activeTier = t.dataset.tier;
    renderResults();
  }

  // ---- setup ----
  function setPill(ok, h) {
    const pill = $('#connPill');
    pill.classList.toggle('ok', ok); pill.classList.toggle('bad', !ok);
    $('#connText').textContent = ok ? (h.professor_count + ' 教授 · ' + h.embedding_provider) : '连接失败';
  }
  function loadMeta() {
    if (state.metaMode === 'bundled') { state.meta = bundledMeta(); renderChips(); return Promise.resolve(); }
    return api('/api/meta')
      .then((m) => { state.meta = m; renderChips(); })
      .catch(() => { state.meta = bundledMeta(); renderChips(); });  // fall back to bundled
  }
  function loadHealth() {
    if (state.healthMode === 'none') {
      $('#connPill').classList.add('ok');
      $('#connText').textContent = '在线演示 · 满血';
      $('#healthKvs').innerHTML = '<div class="muted">连接线上满血部署（只读演示，按 IP/全局限流）。</div>';
      return Promise.resolve();
    }
    return api('/api/health')
      .then((h) => { state.health = h; renderHealth(); setPill(true, h); })
      .catch((e) => { setPill(false); $('#healthKvs').innerHTML = errBox('健康检查失败：' + e.message); });
  }
  function renderHealth() {
    const h = state.health;
    if (!h) return;
    const rows = [
      ['状态', h.status], ['教授数', h.professor_count], ['演示模式', h.demo_mode ? '是' : '否'],
      ['嵌入提供方', h.embedding_provider], ['LLM 提供方', h.llm_provider],
      ['嵌入密钥', h.has_embedding_key ? '已配置' : '未配置'], ['Qdrant', h.qdrant_url],
    ];
    $('#healthKvs').innerHTML = rows.map(([k, v]) => '<div class="k">' + k + '</div><div>' + esc(String(v)) + '</div>').join('');
  }
  function persistConn() {
    state.apiBase = $('#apiBase').value.trim(); LS.setItem('pm_api_base', state.apiBase);
    state.adminToken = $('#adminToken').value.trim(); LS.setItem('pm_admin_token', state.adminToken);
  }
  function loadConfig() {
    if (!state.adminToken) { $('#cfgHint').textContent = '需先填管理令牌'; return; }
    api('/api/admin/config', { headers: { 'X-Admin-Token': state.adminToken } })
      .then((c) => {
        $('#cfg_embedding_provider').value = c.embedding_provider || 'dashscope';
        $('#cfg_llm_provider').value = c.llm_provider || 'dashscope';
        $('#cfgHint').textContent = '已读取（Qwen ' + (c.qwen_api_key_set ? '已设' : '未设')
          + ' · OpenAI ' + (c.openai_api_key_set ? '已设' : '未设') + '）';
      })
      .catch((e) => { $('#cfgHint').textContent = '读取失败：' + e.message; });
  }
  function saveConfig() {
    if (!state.adminToken) { $('#cfgHint').textContent = '需先填管理令牌'; return; }
    const payload = {
      embedding_provider: $('#cfg_embedding_provider').value,
      llm_provider: $('#cfg_llm_provider').value,
    };
    const qk = $('#cfg_qwen_api_key').value.trim(); if (qk) payload.qwen_api_key = qk;
    const ok = $('#cfg_openai_api_key').value.trim(); if (ok) payload.openai_api_key = ok;
    api('/api/admin/config', { method: 'POST', headers: { 'X-Admin-Token': state.adminToken }, body: JSON.stringify(payload) })
      .then((r) => {
        $('#cfgHint').textContent = '已保存：' + (r.applied || []).join(', ');
        $('#cfg_qwen_api_key').value = ''; $('#cfg_openai_api_key').value = '';
        loadHealth();
      })
      .catch((e) => { $('#cfgHint').textContent = '保存失败：' + e.message; });
  }

  // ---- init ----
  function init() {
    $('#apiBase').value = state.apiBase;
    $('#adminToken').value = state.adminToken;
    $$('.tabs button').forEach((b) => b.addEventListener('click', () => switchView(b.dataset.view)));
    $('#view-match').addEventListener('click', onChipClick);
    $('#runBtn').addEventListener('click', runMatch);
    $('#results').addEventListener('click', onTierClick);
    $('#testBtn').addEventListener('click', () => { persistConn(); loadMeta(); loadHealth(); });
    $('#loadCfgBtn').addEventListener('click', () => { persistConn(); loadConfig(); });
    $('#saveCfgBtn').addEventListener('click', saveConfig);
    loadMeta();
    loadHealth();
  }
  document.addEventListener('DOMContentLoaded', init);
})();
