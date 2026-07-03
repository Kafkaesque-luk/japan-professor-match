/* japan-professor-match terminal — vanilla, no build, backend-agnostic.
 * Desktop web layout carrying every element of the production app's professor pages:
 * three-tier tabs, school groups, professor cards (avatar / title badge / age tag /
 * score pill / keyword chips), a papers-first detail page, and a working stateless
 * AI persona chat (the production five-layer prompt on the backend). */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const LS = window.localStorage;
  const P = window.PM_PROF;

  const REGION_LABELS = { hokkaido: '北海道', tohoku: '東北', kanto: '関東', chubu: '中部',
    kinki: '近畿', chugoku: '中国', shikoku: '四国', kyushu: '九州' };
  const TYPE_LABELS = { national: '国公立', private: '私立' };
  const TIERS = [
    { key: 'popular_choices', name: '海选匹配', sub: '最对口',
      info: '与研究方向语义匹配度最高的教授，覆盖面最广。', note: '',
      emptyText: '暂无匹配结果', emptyHint: '调整研究方向或筛选范围后重新匹配' },
    { key: 'niche_research', name: '年富力强', sub: '33-55岁',
      info: '55 岁以下、距退休较远、更可能在招收新生的教授。', note: '年龄据公开履历推算，仅供参考。',
      emptyText: '这批匹配里暂无可确认年龄的年富力强教授',
      emptyHint: '年富力强仅收录能可信推算年龄、且 55 岁以下的教授；可换研究方向或放宽筛选再试' },
    { key: 'hidden_gems', name: '潜力洼地', sub: '非顶尖校',
      info: '研究方向契合、院校排名相对靠后，录取竞争更小。', note: '',
      emptyText: '暂无潜力洼地推荐', emptyHint: '潜力洼地聚焦非顶尖校的强匹配；可换研究方向或放宽筛选再试' },
  ];

  // window.PM_CONFIG (from config.js / inline) sets deployment defaults; localStorage overrides.
  const CFG = window.PM_CONFIG || {};
  const lsBase = LS.getItem('pm_api_base');
  const state = {
    apiBase: lsBase !== null ? lsBase : (CFG.apiBase || ''),
    adminToken: LS.getItem('pm_admin_token') || '',
    matchPath: CFG.matchPath || '/api/match',
    detailPath: CFG.detailPath || '/api/professor/{id}',      // '{id}' placeholder
    chatPath: CFG.chatPath || '/api/professor/{id}/chat',     // '{id}' placeholder（PHP 版无占位符也可）
    metaMode: CFG.metaMode || 'auto',     // 'auto' = try /api/meta then bundled | 'bundled'
    healthMode: CFG.healthMode || 'auto', // 'auto' = try /api/health | 'none' = skip (live demo)
    meta: null, health: null, result: null,
    sel: { regions: new Set(), ranks: new Set(), types: new Set() },
    activeTier: 'popular_choices',
    view: 'list',            // 'list' | 'detail'
    detailCache: new Map(),  // product_id -> detail payload
    listScrollY: 0,
    showTabInfo: false,
    papersExpanded: false,
    typingTimer: null,
    chat: null,              // { pid, name, image, institution, title, msgs, sending, error }
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
  function errBox(msg) { return '<div class="err" style="margin-bottom:20px">' + esc(msg) + '</div>'; }

  let toastTimer = null;
  function toast(msg) {
    const el = $('#pmToast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 1800);
  }

  // Inline SVG icons (no icon font in the standalone terminal).
  const SVG = {
    back: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.9-10-9.5C.5 8 2.5 4.5 6 4.5c2.2 0 3.7 1.2 4.5 2.6.8-1.4 2.3-2.6 4.5-2.6 3.5 0 5.5 3.5 4 7-2.5 4.6-10 9.5-10 9.5z" stroke-linejoin="round"/></svg>',
    share: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="2.5"/><circle cx="17" cy="5.5" r="2.5"/><circle cx="17" cy="18.5" r="2.5"/><line x1="8.2" y1="10.8" x2="14.8" y2="6.8"/><line x1="8.2" y1="13.2" x2="14.8" y2="17.2"/></svg>',
    pin: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M12 21s-6-5.3-6-10a6 6 0 1 1 12 0c0 4.7-6 10-6 10z"/><circle cx="12" cy="11" r="2"/></svg>',
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M4 5c0 8 7 15 15 15l2-4-4.5-2-2 2c-2.5-1-5.5-4-6.5-6.5l2-2L8 3 4 5z" stroke-linejoin="round"/></svg>',
    spark: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linejoin="round"><path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3z"/></svg>',
    file: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><polyline points="13 3 13 9 19 9"/></svg>',
    beaker: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v6L4 19a2 2 0 0 0 1.8 3h12.4A2 2 0 0 0 20 19L15 9V3"/><line x1="7" y1="3" x2="17" y2="3"/></svg>',
    cert: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linejoin="round"><circle cx="12" cy="9" r="5"/><path d="M9 13.5L7.5 21l4.5-2.5L16.5 21 15 13.5"/></svg>',
    trophy: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3h8v5a4 4 0 0 1-8 0V3z"/><path d="M8 4H4v2a4 4 0 0 0 4 4"/><path d="M16 4h4v2a4 4 0 0 1-4 4"/><line x1="12" y1="12" x2="12" y2="17"/><path d="M8 21h8l-1-4h-6l-1 4z"/></svg>',
    medal: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linejoin="round"><circle cx="12" cy="14" r="5"/><path d="M9 9L6 3M15 9l3-6M12 9V3"/></svg>',
    link: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" width="10" height="10"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7L12.5 19"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" width="10" height="10"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  };

  function avatarUrl(p) {
    return P.getProfessorAvatar(p.image || '', Number(p.product_id) || 0);
  }
  const AVATAR_ONERR = ' onerror="this.onerror=null;this.src=\'' + P.FALLBACK_AVATAR + '\'"';

  // ---- views (terminal tabs) ----
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

  function skeletonCards(n) {
    let rows = '';
    for (let i = 0; i < n; i++) {
      rows += '<div class="skeleton-card" style="animation-delay:' + (i * 0.08) + 's">'
        + '<div class="skeleton-avatar"></div><div class="skeleton-content">'
        + '<div class="skeleton-line skeleton-line-title"></div>'
        + '<div class="skeleton-line skeleton-line-text"></div>'
        + '<div class="skeleton-line skeleton-line-text short"></div></div></div>';
    }
    return '<div class="skeleton-container">' + rows + '</div>';
  }

  function showArea(which) {
    $('#resultsArea').hidden = which !== 'results';
    $('#detailArea').hidden = which !== 'detail';
    // the match form only belongs to the list view — the detail page owns the whole width
    $('#matchFormCard').hidden = which === 'detail';
    $('#matchError').hidden = which === 'detail';
  }

  function runMatch() {
    const userInput = $('#userInput').value.trim();
    $('#matchError').innerHTML = '';
    if (!userInput) { $('#matchError').innerHTML = errBox('请先输入研究兴趣'); return; }
    $('#runBtn').disabled = true; $('#runHint').textContent = '匹配中…';
    stopTyping();
    state.view = 'list';
    showArea('results');
    $('#resultsArea').innerHTML =
      '<div class="keywords-section"><span class="keywords-label">扩展关键词：</span>'
      + '<span class="keywords-text"></span><span class="typing-cursor">|</span></div>'
      + skeletonCards(6);
    $('#resultsArea').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    api(state.matchPath, { method: 'POST', body: JSON.stringify({ user_input: userInput, filters: buildFilters() }) })
      .then((res) => {
        state.result = res;
        state.activeTier = 'popular_choices';
        state.detailCache.clear();
        state.showTabInfo = false;
        renderList({ typeKeywords: true });
      })
      .catch((e) => {
        $('#resultsArea').hidden = true;
        $('#matchError').innerHTML = errBox(e.message);
      })
      .finally(() => { $('#runBtn').disabled = false; $('#runHint').textContent = ''; });
  }

  function tierCount(key) {
    const groups = (state.result && state.result[key]) || [];
    return groups.reduce((n, g) => n + (g.professor_count || (g.professors || []).length), 0);
  }

  // ---- results (desktop layout, all app elements) ----
  function renderList(opts) {
    opts = opts || {};
    const r = state.result;
    if (!r) return;
    state.view = 'list';
    showArea('results');
    const tierIdx = TIERS.findIndex((t) => t.key === state.activeTier);
    const tier = TIERS[tierIdx] || TIERS[0];
    const tabs = TIERS.map((t) =>
      '<button class="app-tab ' + (state.activeTier === t.key ? 'active' : '') + '" data-tier="' + t.key + '">'
      + '<span class="tab-name">' + t.name + '</span>'
      + '<span class="tab-count">(' + tierCount(t.key) + ')</span>'
      + '<span class="tab-sub">' + t.sub + '</span>'
      + (state.activeTier === t.key ? '<span class="tab-info-btn" data-info="1">?</span>' : '')
      + '</button>').join('');
    const infoPop = state.showTabInfo
      ? '<div class="tab-info-pop"><div class="tab-info-caret" style="left:' + ['16.66%', '50%', '83.33%'][tierIdx] + '"></div>'
        + '<span class="tab-info-text">' + esc(tier.info) + '</span>'
        + (tier.note ? '<span class="tab-info-note">' + esc(tier.note) + '</span>' : '') + '</div>'
      : '';
    const disc = r.applied_discipline
      ? '<div class="discipline-indicator"><span class="di-label">学科方向</span>'
        + '<span class="di-value">' + esc(r.applied_discipline) + '</span>'
        + (r.discipline_source === 'inferred' ? '<span class="di-auto">自动识别</span>' : '') + '</div>'
      : '';
    const kws = (r.expanded_keywords || []).filter(Boolean);
    const kwFull = kws.join('、');
    const kwHtml = kws.length
      ? '<div class="keywords-section"><span class="keywords-label">扩展关键词：</span>'
        + '<span class="keywords-text" id="kwTyping"></span>'
        + (opts.typeKeywords ? '<span class="typing-cursor" id="kwCursor">|</span>' : '') + '</div>'
      : '';
    const groups = r[state.activeTier] || [];
    let body;
    if (!groups.length) {
      body = '<div class="empty-state"><div class="empty-icon-circle">' + SVG.search + '</div>'
        + '<span class="empty-text">' + esc(tier.emptyText) + '</span>'
        + '<span class="empty-hint">' + esc(tier.emptyHint) + '</span></div>';
    } else {
      let idx = 0;
      body = groups.map((g, gi) => {
        const html = renderSchoolGroup(g, gi, idx);
        idx += (g.professors || []).length;
        return html;
      }).join('');
    }
    $('#resultsArea').innerHTML =
      '<div class="app-tab-bar">' + tabs + infoPop + '</div>' + disc + kwHtml + body;
    if (kws.length) {
      if (opts.typeKeywords) startTyping(kwFull);
      else $('#kwTyping').textContent = kwFull;
    }
    if (opts.restoreScroll) window.scrollTo(0, state.listScrollY);
  }

  function renderSchoolGroup(g, gIndex, baseIdx) {
    const profs = (g.professors || []).map((p, i) => renderProfCard(p, baseIdx + i)).join('');
    return '<div class="school-group">'
      + '<div class="group-header-simple">'
      + '<span class="header-rank">#' + (gIndex + 1) + '</span>'
      + '<span class="header-school">' + esc(g.school_name || '未知学校') + '</span>'
      + '<span class="header-score">综合匹配度 ' + P.matchPercent(g.avg_score) + '%</span>'
      + '<span class="header-count">' + (g.professor_count || (g.professors || []).length) + '位教授</span>'
      + '</div><div class="prof-grid">' + profs + '</div></div>';
  }

  function renderProfCard(p, globalIdx) {
    const td = P.extractTitleAndDepartment(p.position || '');
    const titleBadge = (td.title && td.isValid)
      ? '<span class="category-badge"><span class="category-text">' + esc(td.title) + '</span></span>' : '';
    const age = p.age_estimate
      ? '<span class="prof-age-tag' + (Number(p.age_estimate.retire_in) <= 0 ? ' prof-age-tag-retired' : '') + '">约'
        + esc(p.age_estimate.age) + '岁</span>'
      : '';
    const tierBadge = (state.activeTier === 'hidden_gems')
      ? '<span class="tier-badge">' + esc(P.rankTierLabel(p.school_rank)) + '</span>' : '';
    const score = (p.similarity_score !== undefined || p.match_score !== undefined)
      ? '<span class="match-score-badge"><span class="score-number">'
        + P.matchPercent(p.similarity_score !== undefined ? p.similarity_score : p.match_score) + '%</span></span>'
      : '';
    // Gold line: institution (= the group's school key) + parsed department, like the app.
    const goldParts = [];
    if (p.school_name) goldParts.push(esc(p.school_name));
    if (td.department) goldParts.push(esc(td.department));
    const gold = goldParts.length
      ? '<div class="repurchase-rank-gold">' + goldParts.join(' | ') + '</div>' : '';
    const kws = Array.isArray(p.research_keywords) ? p.research_keywords.slice(0, 3) : [];
    const chipsHtml = kws.length
      ? '<div class="bottom-info-content">' + kws.map((k) => '<span class="info-item">' + esc(k) + '</span>').join('') + '</div>'
      : '';
    return '<div class="interview-card professor-card-slide-in" data-pid="' + Number(p.product_id) + '"'
      + ' style="animation-delay:' + (Math.min(globalIdx, 20) * 0.04) + 's">'
      + '<div class="interview-card-layout">'
      + '<div class="interview-avatar-section"><img class="interview-avatar" src="' + esc(avatarUrl(p)) + '"' + AVATAR_ONERR + ' alt="" loading="lazy"></div>'
      + '<div class="interview-info-section">'
      + '<div class="interview-header-row">'
      + '<div class="header-left-group">'
      + '<span class="merchant-name">' + esc(p.store_name || '未知教授') + '</span>'
      + titleBadge + age + tierBadge
      + '</div>' + score + '</div>'
      + gold
      + '</div></div>'
      + '<div class="interview-bottom-row">'
      + '<div class="interview-bottom-info-inline">' + chipsHtml + '</div>'
      + '<div class="interview-collect-btn" data-collect="1">' + SVG.heart + '</div>'
      + '</div></div>';
  }

  // ---- keywords typewriter ----
  function stopTyping() {
    if (state.typingTimer) { clearInterval(state.typingTimer); state.typingTimer = null; }
  }
  function startTyping(full) {
    stopTyping();
    const el = $('#kwTyping');
    if (!el) return;
    let i = 0;
    state.typingTimer = setInterval(() => {
      i += 2;
      el.textContent = full.slice(0, i);
      if (i >= full.length) {
        stopTyping();
        const cur = $('#kwCursor');
        if (cur) cur.remove();
      }
    }, 30);
  }

  // ---- detail (desktop: hero + papers-first main column + info sidebar) ----
  function detailUrl(pid) { return state.detailPath.replace('{id}', String(pid)); }
  function chatUrl(pid) { return state.chatPath.replace('{id}', String(pid)); }

  function openDetail(pid, fromHistory) {
    if (!fromHistory) {
      state.listScrollY = window.scrollY;
      history.pushState({ pmDetail: pid }, '', '#p' + pid);
    }
    state.view = 'detail';
    state.papersExpanded = false;
    showArea('detail');
    window.scrollTo(0, 0);
    if (state.detailCache.has(pid)) {
      renderDetail(state.detailCache.get(pid));
      return;
    }
    $('#detailArea').innerHTML = detailTopbar() + skeletonCards(4);
    api(detailUrl(pid))
      .then((d) => {
        state.detailCache.set(pid, d);
        if (state.view === 'detail') renderDetail(d);
      })
      .catch((e) => {
        if (state.view !== 'detail') return;
        $('#detailArea').innerHTML = detailTopbar() + errBox('详情加载失败：' + e.message);
      });
  }

  function detailTopbar() {
    return '<div class="detail-topbar"><button class="back-btn" id="navBack">' + SVG.back + '返回匹配结果</button></div>';
  }

  function closeDetail() {
    if (location.hash.indexOf('#p') === 0) history.back();
    else showListAgain();
  }
  function showListAgain() {
    stopTyping();
    state.view = 'list';
    if (state.result) renderList({ restoreScroll: true });
    else showArea('results');
  }

  function statVal(stats, a, b) {
    if (!stats || typeof stats !== 'object') return undefined;
    if (stats[a] !== undefined) return stats[a];
    return stats[b];
  }

  function renderDetail(d) {
    const ext = P.coerceExtend(d.extend) || {};
    const aff = (ext.affiliation && typeof ext.affiliation === 'object') ? ext.affiliation : {};
    const pi = (ext.professor_info && typeof ext.professor_info === 'object') ? ext.professor_info : {};
    const td = P.extractTitleAndDepartment(d.position || aff.position || '');
    const institution = aff.institution || d.school_name || '';
    const nameEn = pi.name_en || '';
    const researchKeywords = Array.isArray(ext.research_keywords) ? ext.research_keywords.filter(Boolean) : [];
    const researchArea = P.formatResearchArea(ext.research_areas);
    const education = P.parseEducationList(ext.education);
    const career = P.parseCareerHistory(ext.career_history);
    const awards = Array.isArray(ext.awards) ? ext.awards.map(P.parseAward).filter(Boolean) : [];
    const patents = Array.isArray(ext.patents) ? ext.patents.filter(Boolean) : [];
    const rawPapers = (ext.publications && Array.isArray(ext.publications.papers)) ? ext.publications.papers : [];
    const papers = rawPapers.map((pp) => { try { return P.parsePaperCitation(pp); } catch (e) { return null; } }).filter(Boolean);
    const stats = (ext.statistics && typeof ext.statistics === 'object') ? ext.statistics : null;
    const selfIntro = typeof ext.self_introduction === 'string' ? ext.self_introduction.trim() : '';
    const age = d.age_estimate;

    // hero
    let meta = '';
    if (age || (td.title && td.isValid)) {
      meta = '<div class="professor-meta-row"><div class="meta-ribbon-emblem"></div>';
      if (age) {
        const retireIn = Number(age.retire_in);
        meta += '<div class="professor-age-mini"><span class="age-mini-num">约' + esc(age.age) + '岁</span>'
          + '<span class="age-mini-sep">·</span>'
          + (retireIn > 0
            ? '<span class="age-mini-retire">距退休' + retireIn + '年</span>'
            : '<span class="age-mini-retire age-mini-over">已达退休年龄</span>')
          + '<span class="age-mini-note">推算</span></div>';
      }
      if (td.title && td.isValid) {
        meta += '<div class="professor-title-section ' + P.titleRankClass(td.title) + '" style="margin-left:auto">'
          + '<span class="professor-title-label">职称</span>'
          + '<span class="professor-title-value">' + esc(td.title) + '</span></div>';
      }
      meta += '</div>';
    }
    const hero = '<div class="detail-hero">'
      + '<img class="hero-avatar" src="' + esc(avatarUrl(d)) + '"' + AVATAR_ONERR + ' alt="">'
      + '<div class="hero-info">'
      + '<div><span class="professor-name-main">' + esc(d.store_name || '') + '</span>'
      + (nameEn ? '<span class="professor-name-en">' + esc(nameEn) + '</span>' : '') + '</div>'
      + (institution
        ? '<div class="location-row">' + SVG.pin + '<span>' + esc(institution)
          + (td.department ? ' | ' + esc(td.department) : '') + '</span></div>'
        : '')
      + meta
      + '<div class="hero-actions">'
      + '<button class="footer-btn professor-ai-btn" data-open-chat="' + Number(d.product_id) + '">' + iconInline(SVG.spark, 15) + 'AI模拟对话</button>'
      + '<button class="footer-btn professor-contact-btn" data-demo-toast="联系教授">' + iconInline(SVG.phone, 15) + '联系教授</button>'
      + '<div class="footer-icon-item" data-demo-toast="收藏">' + SVG.heart + '<span class="icon-label">收藏</span></div>'
      + '<div class="footer-icon-item" data-copy-link="1">' + SVG.share + '<span class="icon-label">分享</span></div>'
      + '</div></div></div>';

    // sidebar: 基本信息 / 研究关键词 / 研究分野 / 学术成果统计 / 自我介绍
    let basic = '<div class="section-card"><div class="section-title">基本信息</div><div class="professor-info-grid">';
    if (institution) basic += infoRow('所属机构', esc(institution));
    if (td.department) basic += infoRow('院系', esc(td.department));
    if (td.title && td.isValid) basic += '<div class="info-row-prof"><span class="info-label-prof">职称</span><span class="info-value-prof highlight">' + esc(td.title) + '</span></div>';
    if (pi.researchmap_id) {
      basic += '<div class="info-row-prof"><span class="info-label-prof">ResearchMap</span>'
        + '<a class="info-value-prof link" href="https://researchmap.jp/' + encodeURIComponent(pi.researchmap_id) + '" target="_blank" rel="noopener">'
        + esc(pi.researchmap_id) + '</a></div>';
    }
    const orcid = pi.orcid || pi.orcid_id || '';
    if (orcid) {
      basic += '<div class="info-row-prof"><span class="info-label-prof">ORCID</span>'
        + '<a class="info-value-prof link" href="https://orcid.org/' + encodeURIComponent(orcid) + '" target="_blank" rel="noopener">'
        + esc(orcid) + '</a></div>';
    }
    basic += '</div></div>';

    const kwCard = researchKeywords.length
      ? '<div class="section-card"><div class="section-title">研究关键词</div><div class="keywords-container">'
        + researchKeywords.map((k) => '<span class="keyword-tag">' + esc(k) + '</span>').join('') + '</div></div>' : '';

    const areaCard = researchArea
      ? '<div class="section-card"><div class="section-title">研究分野</div><div class="research-area-content">'
        + '<span class="research-area-text">' + esc(researchArea) + '</span></div></div>' : '';

    let statsCard = '';
    if (stats) {
      const items = [
        ['papers-icon', SVG.file, statVal(stats, 'papers', 'papers_count'), '论文'],
        ['projects-icon', SVG.beaker, statVal(stats, 'projects', 'research_projects_count'), '项目'],
        ['patents-icon', SVG.cert, statVal(stats, 'patents', 'patents_count'), '专利'],
        ['awards-icon', SVG.trophy, statVal(stats, 'awards', 'awards_count'), '获奖'],
      ].filter((it) => it[2] !== undefined);
      if (items.length) {
        statsCard = '<div class="section-card"><div class="section-title">学术成果统计</div><div class="statistics-grid">'
          + items.map((it) => '<div class="stat-card"><div class="stat-icon ' + it[0] + '">' + it[1] + '</div>'
            + '<div class="stat-content"><div class="stat-value">' + (Number(it[2]) || 0) + '</div>'
            + '<div class="stat-label">' + it[3] + '</div></div></div>').join('')
          + '</div></div>';
      }
    }

    const intro = selfIntro
      ? '<div class="section-card"><div class="section-title">自我介绍</div><div class="self-intro-text">' + esc(selfIntro) + '</div></div>' : '';

    // main column: papers first (always rendered), then timelines / awards / patents
    let papersCard;
    if (papers.length) {
      const shown = state.papersExpanded ? papers : papers.slice(0, 10);
      papersCard = '<div class="section-card"><div class="section-title">研究论文<span class="section-count">(' + papers.length + ')</span></div>'
        + '<div class="papers-list">' + shown.map((pp, i) => paperItem(pp, i)).join('') + '</div>'
        + (papers.length > 10 && !state.papersExpanded
          ? '<div class="papers-more" id="papersMore">展开全部 ' + papers.length + ' 篇</div>' : '')
        + '</div>';
    } else {
      papersCard = '<div class="section-card"><div class="section-title">研究论文<span class="section-count">(0)</span></div>'
        + '<div class="papers-empty">该教授的公开档案暂未收录论文记录。可通过上方 ResearchMap 链接查看其学术主页。</div></div>';
    }

    const eduCard = education.length
      ? sectionTimeline('教育背景', education.map((e) => ({
          year: e.year,
          title: (e.degree && e.degree !== e.institution) ? e.degree : (e.institution || '学位'),
          desc: (e.degree && e.degree !== e.institution) ? e.institution : '',
        }))) : '';

    const careerCard = career.length
      ? sectionTimeline('职业经历', career.map((c) => ({ year: c.year, title: c.position, desc: c.institution }))) : '';

    const awardsCard = awards.length
      ? '<div class="section-card"><div class="section-title">获奖情况<span class="section-count">(' + awards.length + ')</span></div>'
        + '<div class="awards-list">' + awards.map((a) =>
          '<div class="award-item"><div class="award-icon">' + SVG.medal + '</div><div class="award-content">'
          + '<span class="award-name">' + esc(a.name) + '</span>'
          + (a.year ? '<span class="award-year">' + esc(a.year) + '</span>' : '') + '</div></div>').join('')
        + '</div></div>' : '';

    const patentsCard = patents.length
      ? '<div class="section-card"><div class="section-title">专利列表<span class="section-count">(' + patents.length + ')</span></div>'
        + '<div class="patents-list">' + patents.map((t, i) =>
          '<div class="patent-item"><div class="patent-number">' + (i + 1) + '</div>'
          + '<div class="patent-content"><span class="patent-title">' + esc(typeof t === 'string' ? t : (t.title || '')) + '</span></div></div>').join('')
        + '</div></div>' : '';

    $('#detailArea').innerHTML = detailTopbar() + hero
      + '<div class="detail-columns">'
      + '<div class="detail-main">' + papersCard + eduCard + careerCard + awardsCard + patentsCard + '</div>'
      + '<div class="detail-aside">' + basic + kwCard + areaCard + statsCard + intro + '</div>'
      + '</div>';
  }

  function iconInline(svg, size) {
    return '<span style="display:inline-flex;width:' + size + 'px;height:' + size + 'px">'
      + svg.replace('<svg ', '<svg style="width:100%;height:100%;stroke:currentColor" ') + '</span>';
  }
  function infoRow(label, valueHtml) {
    return '<div class="info-row-prof"><span class="info-label-prof">' + label + '</span>'
      + '<span class="info-value-prof">' + valueHtml + '</span></div>';
  }
  function sectionTimeline(title, items) {
    return '<div class="section-card"><div class="section-title">' + title + '</div><div class="timeline-container">'
      + items.map((it) => '<div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content">'
        + (it.year ? '<span class="timeline-year">' + esc(it.year) + '</span>' : '')
        + '<span class="timeline-title">' + esc(it.title || '') + '</span>'
        + (it.desc ? '<span class="timeline-desc">' + esc(it.desc) + '</span>' : '')
        + '</div></div>').join('')
      + '</div></div>';
  }
  function paperItem(pp) {
    const links = (pp.external_urls || []).map((u, ui) =>
      '<a class="paper-link" href="' + esc(u) + '" target="_blank" rel="noopener">' + SVG.link
      + (ui === 0 ? 'PDF' : 'Link ' + (ui + 1)) + '</a>').join('');
    return '<div class="paper-item">'
      + '<div class="paper-title">' + esc(pp.title || pp.original_citation) + '</div>'
      + (pp.authors ? '<div class="paper-authors">' + esc(pp.authors) + '</div>' : '')
      + ((pp.venue || pp.year)
        ? '<div class="paper-venue">' + (pp.venue ? '<span>' + esc(pp.venue) + '</span>' : '')
          + (pp.year ? '<span>' + esc(pp.year) + '</span>' : '') + '</div>' : '')
      + '<div class="paper-meta"><div class="paper-meta-left">'
      + (pp.has_peer_review ? '<span class="peer-review-badge">査読有り</span>' : '')
      + (pp.badges || []).map((b) => '<span class="role-badge">' + esc(b) + '</span>').join('')
      + links + '</div>'
      + '<span class="copy-citation-btn" data-cite="' + esc(pp.original_citation) + '">' + SVG.copy + '引用をコピー</span>'
      + '</div></div>';
  }

  // ---- AI simulated dialog (stateless persona chat drawer) ----
  function openChat(pid) {
    const d = state.detailCache.get(pid);
    state.chat = {
      pid: pid,
      name: (d && d.store_name) || '',
      image: d ? avatarUrl(d) : P.FALLBACK_AVATAR,
      msgs: [],           // {role: 'user'|'assistant', content}
      sending: false,
      error: '',
    };
    $('#chatDrawer').hidden = false;
    renderChat();
    // opening greeting: empty message + empty history -> persona's self-introduction
    requestChat('', []);
  }
  function closeChat() {
    state.chat = null;
    $('#chatDrawer').hidden = true;
  }

  function requestChat(message, history) {
    const c = state.chat;
    if (!c) return;
    c.sending = true;
    c.error = '';
    renderChat();
    api(chatUrl(c.pid), {
      method: 'POST',
      body: JSON.stringify({ professor_id: c.pid, message: message, history: history }),
    })
      .then((res) => {
        if (!state.chat || state.chat.pid !== c.pid) return;
        if (res.professor_name) c.name = res.professor_name;
        c.msgs.push({ role: 'assistant', content: res.reply || '' });
        c.sending = false;
        renderChat();
      })
      .catch((e) => {
        if (!state.chat || state.chat.pid !== c.pid) return;
        c.sending = false;
        c.error = e.message || '对话失败，请稍后再试';
        renderChat();
      });
  }

  function sendChat() {
    const c = state.chat;
    if (!c || c.sending) return;
    const input = $('#chatInput');
    const text = (input.value || '').trim();
    if (!text) return;
    if (text.length > 500) { toast('消息长度不能超过500字'); return; }
    const history = c.msgs.slice();  // history = everything before this user message
    c.msgs.push({ role: 'user', content: text });
    input.value = '';
    requestChat(text, history);
  }

  function renderChat() {
    const c = state.chat;
    if (!c) return;
    const msgs = c.msgs.map((m) =>
      '<div class="chat-msg ' + m.role + '"><div class="chat-bubble">' + esc(m.content) + '</div></div>').join('');
    const typing = c.sending
      ? '<div class="chat-msg assistant"><div class="chat-bubble"><span class="chat-typing"><i></i><i></i><i></i></span></div></div>'
      : '';
    const err = c.error ? '<div class="chat-err">' + esc(c.error) + '</div>' : '';
    $('#chatDrawer').innerHTML =
      '<div class="chat-head">'
      + '<img src="' + esc(c.image) + '"' + AVATAR_ONERR + ' alt="">'
      + '<div class="chat-head-info">'
      + '<div class="chat-head-name">' + esc(c.name || 'AI模拟对话') + '</div>'
      + '<div class="chat-head-sub">AI模拟对话 · 基于公开履历的角色扮演，非本人</div>'
      + '</div>'
      + '<button class="chat-close" id="chatClose">×</button>'
      + '</div>'
      + '<div class="chat-msgs" id="chatMsgs">' + msgs + typing + err + '</div>'
      + '<div class="chat-input-bar">'
      + '<textarea id="chatInput" rows="1" maxlength="500" placeholder="介绍一下你的研究背景，或问问教授的研究方向…"></textarea>'
      + '<button class="chat-send" id="chatSend"' + (c.sending ? ' disabled' : '') + '>发送</button>'
      + '</div>'
      + '<div class="chat-note">回复由大模型按教授公开履历实时生成，仅供预沟通参考 · Enter 发送，Shift+Enter 换行</div>';
    const box = $('#chatMsgs');
    box.scrollTop = box.scrollHeight;
    const input = $('#chatInput');
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    if (!c.sending) input.focus();
    $('#chatSend').addEventListener('click', sendChat);
    $('#chatClose').addEventListener('click', closeChat);
  }

  // ---- results/detail event delegation ----
  function onMatchAreaClick(e) {
    const back = e.target.closest('#navBack');
    if (back) { closeDetail(); return; }
    const openChatBtn = e.target.closest('[data-open-chat]');
    if (openChatBtn) { openChat(Number(openChatBtn.getAttribute('data-open-chat'))); return; }
    const collect = e.target.closest('[data-collect]');
    if (collect) { e.stopPropagation(); toast('演示模式暂不支持收藏'); return; }
    const demoBtn = e.target.closest('[data-demo-toast]');
    if (demoBtn) { toast('演示模式不含此功能，完整体验请至 App'); return; }
    const copyLink = e.target.closest('[data-copy-link]');
    if (copyLink) {
      (navigator.clipboard ? navigator.clipboard.writeText(location.href) : Promise.reject())
        .then(() => toast('页面链接已复制'))
        .catch(() => toast('复制失败'));
      return;
    }
    const cite = e.target.closest('[data-cite]');
    if (cite) {
      const text = cite.getAttribute('data-cite') || '';
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
        .then(() => toast('已复制'))
        .catch(() => toast('复制失败'));
      return;
    }
    const more = e.target.closest('#papersMore');
    if (more) {
      state.papersExpanded = true;
      const pid = parsePidFromHash();
      if (pid && state.detailCache.has(pid)) {
        const keep = window.scrollY;
        renderDetail(state.detailCache.get(pid));
        window.scrollTo(0, keep);
      }
      return;
    }
    const infoBtn = e.target.closest('[data-info]');
    if (infoBtn) { state.showTabInfo = !state.showTabInfo; renderList({ restoreScroll: true }); return; }
    const tab = e.target.closest('.app-tab');
    if (tab) {
      if (state.activeTier !== tab.dataset.tier) {
        state.activeTier = tab.dataset.tier;
        state.showTabInfo = false;
        renderList({});
      }
      return;
    }
    if (state.showTabInfo && state.view === 'list') {
      state.showTabInfo = false;
      renderList({ restoreScroll: true });
      return;
    }
    const card = e.target.closest('.interview-card');
    if (card) { openDetail(Number(card.dataset.pid)); }
  }

  function parsePidFromHash() {
    const m = /^#p(\d+)$/.exec(location.hash || '');
    return m ? Number(m[1]) : 0;
  }
  window.addEventListener('popstate', () => {
    const pid = parsePidFromHash();
    if (pid && state.result) openDetail(pid, true);
    else if (state.view === 'detail') showListAgain();
  });

  // ---- setup ----
  function setPill(ok, h) {
    const pill = $('#connPill');
    pill.classList.toggle('ok', ok); pill.classList.toggle('bad', !ok);
    $('#connText').textContent = ok ? ('自部署 · ' + h.professor_count + ' 位教授样本 · ' + h.embedding_provider) : '连接失败';
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
      $('#connText').textContent = '在线演示 · 满血 · 约30万教授全量索引';
      $('#healthKvs').innerHTML = '<div class="muted">连接线上满血部署（生产全量约 30 万教授；只读演示，按 IP/全局限流）。</div>';
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
    $('#view-match').addEventListener('click', (e) => { onChipClick(e); });
    $('#resultsArea').addEventListener('click', onMatchAreaClick);
    $('#detailArea').addEventListener('click', onMatchAreaClick);
    $('#runBtn').addEventListener('click', runMatch);
    $('#testBtn').addEventListener('click', () => { persistConn(); loadMeta(); loadHealth(); });
    $('#loadCfgBtn').addEventListener('click', () => { persistConn(); loadConfig(); });
    $('#saveCfgBtn').addEventListener('click', saveConfig);
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    loadMeta();
    loadHealth();
  }
  document.addEventListener('DOMContentLoaded', init);
})();
