/* GS Tech Radar — frontend application */
'use strict';

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  repos: [],
  techs: [],
  dashboard: {},
  selectedTech: null,
  analysisCache: {},   // tech name → analysis object
  kgData: { nodes: [], edges: [] },
  pollTimers: {},
};

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}
const GET = p => api('GET', p);
const POST = (p, b) => api('POST', p, b);
const DEL = p => api('DELETE', p);

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Tab navigation ────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'metrics') renderMetrics();
    if (btn.dataset.tab === 'kg') initKG();
    if (btn.dataset.tab === 'timeline') renderTimeline();
    if (btn.dataset.tab === 'comparison') refreshCmpSelect();
    if (btn.dataset.tab === 'cheatsheet') renderCheatsheetNav();
  });
});

// ── Repo management ───────────────────────────────────────────────────────────
document.getElementById('add-repo-btn').addEventListener('click', addRepo);
document.getElementById('repo-url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') addRepo();
});

async function addRepo() {
  const input = document.getElementById('repo-url-input');
  const url = input.value.trim();
  if (!url) return;
  try {
    // Import metadata only — user clicks the card to trigger scan
    const r = await POST('/api/repos', { url, auto_scan: false });
    toast(r.status === 'exists' ? `Already imported: id=${r.id}` : `Imported — click the card to scan`, 'info');
    input.value = '';
    await refreshAll();
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function triggerScan(repoId) {
  const r = state.repos.find(r => r.id === repoId);
  if (!r) return;
  await POST(`/api/repos/${repoId}/scan`);
  toast(`Scanning ${r.owner}/${r.name}…`, 'info');
  pollScanStatus(repoId);
  await refreshAll();
}

function pollScanStatus(repoId) {
  if (state.pollTimers[repoId]) return;
  state.pollTimers[repoId] = setInterval(async () => {
    try {
      const s = await GET(`/api/repos/${repoId}/status`);
      if (s.status === 'done' || s.status === 'error') {
        clearInterval(state.pollTimers[repoId]);
        delete state.pollTimers[repoId];
        toast(
          s.status === 'done' ? `Scan done: ${s.message}` : `Scan error: ${s.message}`,
          s.status === 'done' ? 'success' : 'error'
        );
        await refreshAll();
      } else {
        renderRepoList();
      }
    } catch (_) {}
  }, 3000);
}

// ── Data refresh ──────────────────────────────────────────────────────────────
async function refreshAll() {
  const [repos, techs, dashboard, analyses] = await Promise.all([
    GET('/api/repos'),
    GET('/api/techs'),
    GET('/api/dashboard'),
    GET('/api/analyses'),
  ]);
  state.repos = repos;
  state.techs = techs;
  state.dashboard = dashboard;
  // Merge DB analyses into cache (don't overwrite session-fresh ones)
  for (const [name, a] of Object.entries(analyses)) {
    if (!state.analysisCache[name]) state.analysisCache[name] = a;
  }
  renderTopStats();
  renderRepoList();
  renderTechSidebar();
  renderOverviewCards();
}

function renderTopStats() {
  const d = state.dashboard;
  document.getElementById('stat-repos').textContent = d.repo_count || 0;
  document.getElementById('stat-techs').textContent = d.tech_count || 0;
  document.getElementById('stat-commits').textContent = fmt(d.total_commits || 0);
  document.getElementById('stat-prs').textContent = fmt(d.total_prs || 0);
}

function fmt(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n;
}

// ── Repo list sidebar ─────────────────────────────────────────────────────────
function renderRepoList() {
  const el = document.getElementById('repo-list');
  if (!state.repos.length) {
    el.innerHTML = '<div style="padding:12px 14px;font-size:12px;color:var(--fg-dim)">No repos yet</div>';
    return;
  }
  el.innerHTML = state.repos.map(r => {
    const notScanned = !r.last_scanned && r.scan_status !== 'running';
    return `
    <div class="repo-item ${notScanned ? 'not-scanned' : ''}" data-id="${r.id}" title="${notScanned ? 'Click to scan' : r.url}">
      <span class="scan-dot ${r.scan_status || 'none'}"></span>
      <span class="repo-item-name">${r.owner}/${r.name}</span>
      ${notScanned
        ? `<span class="scan-cta" data-scan="${r.id}" title="Scan this repo">▷</span>`
        : `<span class="repo-badge">${r.tech_count || 0}</span>`}
      <span title="Delete" style="cursor:pointer;color:var(--fg-dim);font-size:11px" data-delete="${r.id}">✕</span>
    </div>`;
  }).join('');

  el.querySelectorAll('[data-scan]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await triggerScan(+btn.dataset.scan);
    });
  });
  el.querySelectorAll('.repo-item:not(.not-scanned)').forEach(item => {
    item.addEventListener('click', () => {
      const id = +item.dataset.id;
      const r = state.repos.find(r => r.id === id);
      if (r) window.open(r.url, '_blank');
    });
  });
  el.querySelectorAll('[data-delete]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const id = +btn.dataset.delete;
      if (!confirm('Remove this repo?')) return;
      await DEL(`/api/repos/${id}`);
      await refreshAll();
    });
  });
}

// ── Tech sidebar ──────────────────────────────────────────────────────────────
function renderTechSidebar() {
  const el = document.getElementById('tech-list-sidebar');
  const count = document.getElementById('tech-filter-count');
  count.textContent = `${state.techs.length} techs`;
  el.innerHTML = state.techs.map(t => `
    <div class="tech-pill ${state.selectedTech === t.name ? 'selected' : ''}" data-tech="${t.name}">
      <span class="tech-pill-name">${t.name}</span>
      <span class="tech-cat-badge">${t.category}</span>
    </div>
  `).join('');
  el.querySelectorAll('.tech-pill').forEach(pill => {
    pill.addEventListener('click', () => openTechDrawer(pill.dataset.tech));
  });
}

// ── Overview cards ─────────────────────────────────────────────────────────────
function renderOverviewCards() {
  const grid = document.getElementById('repo-cards-grid');
  const empty = document.getElementById('overview-empty');
  if (!state.repos.length) {
    empty.style.display = 'flex';
    return;
  }
  empty.style.display = 'none';
  const cards = state.repos.map(r => {
    const m = r.metrics || {};
    const notScanned = !r.last_scanned && r.scan_status !== 'running';
    const isRunning = r.scan_status === 'running';
    const techTags = (r.techs || []).slice(0, 6).map(t =>
      `<span class="tech-tag">${t.name}</span>`
    ).join('');

    const techArea = notScanned
      ? `<div class="repo-card-unscan">
           <button class="btn btn-gold btn-sm" data-scan="${r.id}">▷ Scan this repo</button>
           <span style="font-size:11px;color:var(--fg-dim);margin-left:8px">not scanned yet</span>
         </div>`
      : isRunning
        ? `<div class="repo-card-techs"><span class="spinner"></span><span style="font-size:11px;color:var(--amber);margin-left:8px">scanning…</span></div>`
        : `<div class="repo-card-techs">${techTags || '<span style="color:var(--fg-dim);font-size:11px">no techs detected</span>'}</div>`;

    return `
    <div class="repo-card ${notScanned ? 'repo-card-dim' : ''}" data-id="${r.id}">
      <div class="repo-card-header">
        <div>
          <div class="repo-card-title">${r.name}</div>
          <div class="repo-card-owner">${r.owner}</div>
        </div>
        <div class="card-actions">
          <button class="btn btn-ghost btn-sm" onclick="window.open('${r.url}','_blank')">↗</button>
          ${!notScanned ? `<button class="btn btn-ghost btn-sm" data-rescan="${r.id}" title="Re-scan">↺</button>` : ''}
        </div>
      </div>
      ${r.description ? `<div class="repo-card-desc">${r.description}</div>` : ''}
      ${techArea}
      ${!notScanned ? `
      <div class="repo-card-metrics">
        <div class="metric-item"><div class="metric-val">${fmt(r.stars || 0)}</div><div class="metric-label">Stars</div></div>
        <div class="metric-item"><div class="metric-val">${fmt(m.commits_total || 0)}</div><div class="metric-label">Commits</div></div>
        <div class="metric-item"><div class="metric-val">${fmt(m.prs_merged || 0)}</div><div class="metric-label">PRs</div></div>
        <div class="metric-item"><div class="metric-val">${fmt(m.contributors_count || 0)}</div><div class="metric-label">Contributors</div></div>
        <div class="metric-item"><div class="metric-val">${fmt(m.issues_closed || 0)}</div><div class="metric-label">Issues closed</div></div>
        <div class="metric-item"><div class="metric-val">${fmt(r.forks || 0)}</div><div class="metric-label">Forks</div></div>
      </div>` : `
      <div style="display:flex;gap:12px;margin-top:8px">
        <div class="metric-item"><div class="metric-val" style="font-size:18px">${fmt(r.stars || 0)}</div><div class="metric-label">Stars</div></div>
        <div class="metric-item"><div class="metric-val" style="font-size:18px">${fmt(r.forks || 0)}</div><div class="metric-label">Forks</div></div>
        ${r.language ? `<div class="metric-item"><div style="font-size:13px;color:var(--bronze)">${r.language}</div><div class="metric-label">Language</div></div>` : ''}
      </div>`}
    </div>`;
  }).join('');

  Array.from(grid.children).forEach(c => { if (c !== empty) c.remove(); });
  grid.insertAdjacentHTML('afterbegin', cards);

  grid.querySelectorAll('[data-scan]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await triggerScan(+btn.dataset.scan);
    });
  });
  grid.querySelectorAll('[data-rescan]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await triggerScan(+btn.dataset.rescan);
    });
  });
}

// ── Tech drawer ───────────────────────────────────────────────────────────────
const drawer = document.getElementById('tech-drawer');
document.getElementById('drawer-close-btn').addEventListener('click', closeTechDrawer);
document.getElementById('drawer-analyze-btn').addEventListener('click', analyzeCurrentTech);

function openTechDrawer(techName) {
  state.selectedTech = techName;
  renderTechSidebar();
  document.getElementById('drawer-title').textContent = techName;
  document.getElementById('drawer-content').innerHTML = '<div class="spinner"></div>';
  drawer.style.right = '0';

  const cached = state.analysisCache[techName];
  if (cached) {
    renderDrawerContent(cached);
  } else {
    // Show category info while user can trigger analysis
    const tech = state.techs.find(t => t.name === techName);
    document.getElementById('drawer-content').innerHTML = `
      <p style="color:var(--fg-2);margin-bottom:12px">${tech ? `Category: <span style="color:var(--bronze)">${tech.category}</span>` : ''}</p>
      <p style="color:var(--fg-dim);font-size:12px">No analysis yet. Click "Generate Analysis" to fetch state-of-art, comparison, cheatsheet, knowledge graph, and timeline using Claude AI.</p>
    `;
  }
}

function closeTechDrawer() {
  drawer.style.right = '-420px';
  state.selectedTech = null;
  renderTechSidebar();
}

async function analyzeCurrentTech() {
  if (!state.selectedTech) return;
  const btn = document.getElementById('drawer-analyze-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  document.getElementById('drawer-content').innerHTML = '<div class="spinner"></div><p style="color:var(--fg-dim);margin-top:10px;font-size:12px">Calling Claude… may take ~20s</p>';
  try {
    const analysis = await GET(`/api/techs/${encodeURIComponent(state.selectedTech)}/analysis`);
    state.analysisCache[state.selectedTech] = analysis;
    renderDrawerContent(analysis);
    renderCheatsheetNav();
    toast(`Analysis ready for ${state.selectedTech}`, 'success');
  } catch (e) {
    toast(e.message, 'error');
    document.getElementById('drawer-content').innerHTML = `<p style="color:var(--danger)">${e.message}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Regenerate';
  }
}

function renderDrawerContent(a) {
  if (!a) return;
  const soa = a.state_of_art || a.state_of_art || {};
  const statusClass = (a.ecosystem_status || 'stable').toLowerCase();
  document.getElementById('drawer-content').innerHTML = `
    <div style="margin-bottom:14px">
      <span class="soa-status ${statusClass}">${a.ecosystem_status || '—'}</span>
      ${a.current_version ? `<span style="color:var(--fg-dim);font-size:11px;margin-left:8px">v${a.current_version}</span>` : ''}
    </div>
    <p style="color:var(--fg-1);font-size:13px;line-height:1.6;margin-bottom:12px">${a.overview || ''}</p>
    ${a.creator ? `<div style="font-size:12px;color:var(--fg-dim);margin-bottom:4px">Created by <span style="color:var(--bronze)">${a.creator}</span>${a.organization ? ` · ${a.organization}` : ''}${a.year_created ? ` · ${a.year_created}` : ''}</div>` : ''}
    ${soa.headline ? `<div style="font-size:12px;color:var(--fg-2);margin-bottom:12px;padding:8px 10px;background:var(--bg-2);border-radius:6px">${soa.headline}</div>` : ''}
    ${soa.latest_features ? `
      <div style="margin-bottom:12px">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--fg-dim);margin-bottom:6px">Latest features</div>
        ${soa.latest_features.map(f => `<div style="font-size:12px;color:var(--fg-2);margin-bottom:3px">▸ ${f}</div>`).join('')}
      </div>` : ''}
    ${soa.best_practices ? `
      <div style="margin-bottom:12px">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--fg-dim);margin-bottom:6px">Best practices</div>
        ${soa.best_practices.map(f => `<div style="font-size:12px;color:var(--fg-2);margin-bottom:3px">▸ ${f}</div>`).join('')}
      </div>` : ''}
    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-ghost btn-sm" onclick="switchToTab('cheatsheet');renderCheatsheetFor('${state.selectedTech}')">View Cheatsheet</button>
      <button class="btn btn-ghost btn-sm" onclick="loadKGForTech('${state.selectedTech}')">Show in KG</button>
      <button class="btn btn-ghost btn-sm" onclick="switchToTab('timeline');renderTimeline()">Timeline</button>
    </div>
  `;
}

function switchToTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  const btn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');
  const tab = document.getElementById(`tab-${name}`);
  if (tab) tab.classList.add('active');
}

// ── Knowledge Graph ───────────────────────────────────────────────────────────
let kgSim = null;
let kgZoom = null;

function initKG() {
  // Called once when tab first opened
}

async function loadKGForTech(techName) {
  switchToTab('kg');
  try {
    // Fetch KG from server (works even if not in session cache — DB has it)
    const kg = await GET(`/api/kg?techs=${encodeURIComponent(techName)}`);
    if (!kg.nodes || !kg.nodes.length) {
      toast('No KG data yet — generate analysis first', 'info');
      return;
    }
    renderKG(kg);
  } catch (e) {
    toast(e.message, 'error');
  }
}

document.getElementById('kg-load-all-btn').addEventListener('click', async () => {
  try {
    // Call /api/kg with no filter — backend reads all analyzed techs from DB
    const kg = await GET('/api/kg');
    if (!kg.nodes || !kg.nodes.length) {
      toast('No analyses in DB yet — scan a repo and generate analysis first', 'info');
      return;
    }
    renderKG(kg);
  } catch (e) {
    toast(e.message, 'error');
  }
});

document.getElementById('kg-reset-btn').addEventListener('click', () => {
  if (kgZoom) {
    const svg = d3.select('#kg-svg');
    svg.transition().duration(500).call(kgZoom.transform, d3.zoomIdentity);
  }
});

const NODE_COLORS = {
  tech:      '#d4af37',
  language:  '#e6c97a',
  concept:   '#e8d195',
  org:       '#cd7f32',
  person:    '#b08d57',
  standard:  '#f5a524',
  default:   '#8a7a5a',
};

function renderKG(kg) {
  if (!kg || !kg.nodes || !kg.nodes.length) {
    toast('No graph data', 'info');
    return;
  }
  state.kgData = kg;

  const container = document.getElementById('kg-svg').parentElement;
  const W = container.clientWidth;
  const H = container.clientHeight;

  const svg = d3.select('#kg-svg').attr('viewBox', `0 0 ${W} ${H}`);
  svg.selectAll('*').remove();

  // Zoom layer
  const g = svg.append('g');
  kgZoom = d3.zoom().scaleExtent([0.2, 4]).on('zoom', e => g.attr('transform', e.transform));
  svg.call(kgZoom);

  // Arrow marker
  svg.append('defs').append('marker')
    .attr('id', 'arrow').attr('viewBox', '0 -3 6 6').attr('refX', 14).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-3L6,0L0,3').attr('fill', 'rgba(212,175,55,0.4)');

  const nodes = kg.nodes.map(n => ({ ...n }));
  const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
  const edges = kg.edges.filter(e => nodeById[e.source] && nodeById[e.target]).map(e => ({ ...e }));

  const link = g.append('g').selectAll('line')
    .data(edges).join('line')
    .attr('stroke', 'rgba(212,175,55,0.25)').attr('stroke-width', 1)
    .attr('marker-end', 'url(#arrow)');

  const edgeLabel = g.append('g').selectAll('text')
    .data(edges).join('text')
    .attr('fill', 'rgba(140,150,165,0.6)').attr('font-size', 9)
    .attr('text-anchor', 'middle').text(d => d.type || '');

  const nodeG = g.append('g').selectAll('g')
    .data(nodes).join('g').style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end',   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  nodeG.append('circle')
    .attr('r', d => d.type === 'tech' ? 10 : 7)
    .attr('fill', d => NODE_COLORS[d.type] || NODE_COLORS.default)
    .attr('fill-opacity', 0.9)
    .attr('stroke', d => NODE_COLORS[d.type] || NODE_COLORS.default)
    .attr('stroke-opacity', 0.3).attr('stroke-width', 3);

  nodeG.append('text')
    .attr('dy', '0.35em').attr('dx', d => (d.type === 'tech' ? 13 : 10))
    .attr('fill', '#f0e8d6').attr('font-size', 11)
    .attr('font-family', 'Inter, sans-serif').text(d => d.label);

  // Tooltip
  const tooltip = document.getElementById('kg-tooltip');
  nodeG.on('mouseover', (e, d) => {
    tooltip.classList.add('visible');
    document.getElementById('tt-title').textContent = d.label;
    document.getElementById('tt-body').textContent = d.description || d.type || '';
    tooltip.style.left = (e.pageX + 12) + 'px';
    tooltip.style.top  = (e.pageY - 20) + 'px';
  }).on('mousemove', e => {
    tooltip.style.left = (e.pageX + 12) + 'px';
    tooltip.style.top  = (e.pageY - 20) + 'px';
  }).on('mouseout', () => tooltip.classList.remove('visible'));

  nodeG.on('click', (e, d) => {
    if (d.type === 'tech') openTechDrawer(d.label);
  });

  const sim = d3.forceSimulation(nodes)
    .force('link',   d3.forceLink(edges).id(d => d.id).distance(90))
    .force('charge', d3.forceManyBody().strength(-250))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(20));

  kgSim = sim;

  sim.on('tick', () => {
    link
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    edgeLabel
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2);
    nodeG.attr('transform', d => `translate(${d.x},${d.y})`);
  });

  // Legend
  const legendTypes = [...new Set(nodes.map(n => n.type))];
  document.getElementById('kg-legend').innerHTML = legendTypes.map(t => `
    <span class="kg-leg-item">
      <span class="kg-leg-dot" style="background:${NODE_COLORS[t] || NODE_COLORS.default}"></span>
      <span style="font-size:11px;color:var(--fg-2)">${t}</span>
    </span>
  `).join('') + `<span style="margin-left:8px;color:var(--fg-dim);font-size:11px">${nodes.length} nodes · ${edges.length} edges</span>`;
}

// ── Timeline ──────────────────────────────────────────────────────────────────
function renderTimeline() {
  const el = document.getElementById('timeline-content');
  const allEvents = [];

  for (const [techName, analysis] of Object.entries(state.analysisCache)) {
    const tl = analysis.timeline_json || analysis.timeline;
    if (!tl) continue;
    const events = typeof tl === 'string' ? JSON.parse(tl).events : (tl.events || []);
    for (const ev of events) {
      allEvents.push({ ...ev, tech: techName });
    }
  }

  if (!allEvents.length) {
    el.innerHTML = '<div class="timeline-empty">Generate tech analyses to populate the timeline.</div>';
    return;
  }

  allEvents.sort((a, b) => (a.year || 0) - (b.year || 0));

  const html = allEvents.map(ev => `
    <div class="tl-event">
      <div class="tl-event-header">
        <span class="tl-event-year">${ev.year || '?'}</span>
        <span class="tl-event-type">${ev.type || 'event'}</span>
        <span class="tl-tech-label">${ev.tech}</span>
      </div>
      <div class="tl-event-title">${ev.title || ''}</div>
      ${ev.description ? `<div class="tl-event-desc">${ev.description}</div>` : ''}
    </div>
  `).join('');

  el.innerHTML = `<div class="timeline-track">${html}</div>`;
}

// ── Cheatsheet ────────────────────────────────────────────────────────────────
function renderCheatsheetNav() {
  const nav = document.getElementById('cheatsheet-nav');
  const analyzed = Object.keys(state.analysisCache);
  if (!analyzed.length) {
    nav.innerHTML = '<div style="padding:10px 14px;font-size:12px;color:var(--fg-dim)">No analyses yet.</div>';
    return;
  }
  nav.innerHTML = analyzed.map(name => `
    <div class="cs-nav-item ${state.selectedTech === name ? 'active' : ''}" data-cs="${name}">${name}</div>
  `).join('');
  nav.querySelectorAll('[data-cs]').forEach(item => {
    item.addEventListener('click', () => renderCheatsheetFor(item.dataset.cs));
  });
}

function renderCheatsheetFor(techName) {
  state.selectedTech = techName;
  renderCheatsheetNav();
  switchToTab('cheatsheet');

  const analysis = state.analysisCache[techName];
  const el = document.getElementById('cheatsheet-content');
  if (!analysis) {
    el.innerHTML = '<div class="cs-empty">No analysis for this tech.</div>';
    return;
  }

  const cheatsheet = analysis.cheatsheet || '';
  const tech = state.techs.find(t => t.name === techName);

  el.innerHTML = `
    <div class="cs-header">
      <div class="cs-title">${techName}</div>
      ${tech ? `<div class="cs-category">${tech.category}</div>` : ''}
    </div>
    ${analysis.overview ? `<div class="cs-overview">${analysis.overview}</div>` : ''}
    <div class="cs-body">${marked.parse(cheatsheet || '*No cheatsheet generated.*')}</div>
  `;
}

// ── Comparison ────────────────────────────────────────────────────────────────
function refreshCmpSelect() {
  const sel = document.getElementById('cmp-select');
  const cur = sel.value;
  sel.innerHTML = '<option value="">— pick a technology —</option>';

  // Analysed techs first
  const analysed = new Set(Object.keys(state.analysisCache));
  for (const name of analysed) {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    if (name === cur) opt.selected = true;
    sel.appendChild(opt);
  }
  // Remaining techs (no analysis yet — will need generation)
  for (const t of state.techs) {
    if (!analysed.has(t.name)) {
      const opt = document.createElement('option');
      opt.value = t.name; opt.textContent = `${t.name} (generate first)`;
      if (t.name === cur) opt.selected = true;
      sel.appendChild(opt);
    }
  }
}

document.getElementById('cmp-load-btn').addEventListener('click', async () => {
  const sel = document.getElementById('cmp-select');
  const name = sel.value;
  if (!name) return;

  const el = document.getElementById('cmp-content');
  let analysis = state.analysisCache[name];

  if (!analysis) {
    // Not in cache — try DB via API (will generate if needed)
    el.innerHTML = `<div style="display:flex;align-items:center;gap:10px;padding:20px"><span class="spinner"></span> Generating analysis for <strong style="color:var(--gold)">${name}</strong>… (~20s)</div>`;
    try {
      analysis = await GET(`/api/techs/${encodeURIComponent(name)}/analysis`);
      state.analysisCache[name] = analysis;
    } catch (e) {
      el.innerHTML = `<div style="color:var(--danger);padding:20px">
        <strong>Error:</strong> ${e.message}<br>
        <span style="font-size:12px;color:var(--fg-dim)">Try scanning a repo that uses ${name} first, then generate analysis from the tech drawer.</span>
      </div>`;
      return;
    }
  }

  const comparison = analysis.comparison || analysis.comparison_json || [];
  const cmpArr = typeof comparison === 'string' ? JSON.parse(comparison) : comparison;

  if (!cmpArr.length) {
    el.innerHTML = '<div style="color:var(--fg-dim);text-align:center;margin-top:40px">No comparison data in this analysis. Try regenerating.</div>';
    return;
  }

  const rows = cmpArr.map(alt => `
    <tr>
      <td class="cmp-subject">${name}</td>
      <td>${alt.name}</td>
      <td><ul class="bullet-list">${(alt.pros_over_subject || []).map(p => `<li class="cmp-pro">${p}</li>`).join('')}</ul></td>
      <td><ul class="bullet-list">${(alt.cons_over_subject || []).map(c => `<li class="cmp-con">${c}</li>`).join('')}</ul></td>
      <td style="color:var(--fg-2);font-size:12px">${alt.best_for || ''}</td>
    </tr>
  `).join('');

  document.getElementById('cmp-content').innerHTML = `
    <table class="comparison-table">
      <thead><tr>
        <th>Subject</th><th>Alternative</th>
        <th>Pros of alt</th><th>Cons of alt</th><th>Best for alt</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
});

// ── Metrics ───────────────────────────────────────────────────────────────────
let chartCats = null;
let chartCommits = null;

function renderMetrics() {
  const d = state.dashboard;
  document.getElementById('kpi-repos').textContent = d.repo_count || 0;
  document.getElementById('kpi-techs').textContent = d.tech_count || 0;
  document.getElementById('kpi-commits').textContent = fmt(d.total_commits || 0);
  document.getElementById('kpi-prs').textContent = fmt(d.total_prs || 0);
  document.getElementById('kpi-contributors').textContent = fmt(d.total_contributors || 0);
  document.getElementById('kpi-stars').textContent = fmt(d.total_stars || 0);

  renderCategoryChart(d.category_breakdown || []);
  renderCommitChart();
  renderSOAGrid();
}

function renderCategoryChart(cats) {
  const ctx = document.getElementById('chart-cats').getContext('2d');
  const labels = cats.map(c => c.category);
  const values = cats.map(c => c.count);
  const colors = [
    'rgba(212,175,55,0.8)', 'rgba(205,127,50,0.8)', 'rgba(176,141,87,0.8)',
    'rgba(232,209,149,0.8)', 'rgba(245,165,36,0.8)', 'rgba(224,164,88,0.8)',
    'rgba(140,150,165,0.6)', 'rgba(100,90,60,0.8)',
  ];

  if (chartCats) chartCats.destroy();
  chartCats = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors.slice(0, labels.length), borderWidth: 0 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#c9b88a', font: { size: 11 } } },
      },
    },
  });
}

function renderCommitChart() {
  const ctx = document.getElementById('chart-commits').getContext('2d');
  const labels = state.repos.map(r => r.name);
  const values = state.repos.map(r => (r.metrics || {}).commits_total || 0);

  if (chartCommits) chartCommits.destroy();
  chartCommits = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Commits',
        data: values,
        backgroundColor: 'rgba(212,175,55,0.6)',
        borderColor: '#d4af37',
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#8a7a5a' }, grid: { color: 'rgba(140,150,165,0.05)' } },
        y: { ticks: { color: '#c9b88a' }, grid: { display: false } },
      },
    },
  });
}

function renderSOAGrid() {
  const grid = document.getElementById('soa-grid');
  const entries = Object.entries(state.analysisCache);
  if (!entries.length) {
    grid.innerHTML = '<div style="color:var(--fg-dim);font-size:13px">Generate tech analysis to see state-of-art cards.</div>';
    return;
  }
  grid.innerHTML = entries.map(([name, a]) => {
    const soa = a.state_of_art || {};
    const statusClass = (a.ecosystem_status || 'stable').toLowerCase();
    const features = (soa.latest_features || []).slice(0, 3);
    return `
      <div class="soa-card">
        <div>
          <span class="soa-name">${name}</span>
          <span class="soa-status ${statusClass}">${a.ecosystem_status || 'stable'}</span>
        </div>
        ${a.current_version ? `<div class="soa-version">v${a.current_version}</div>` : ''}
        <div class="soa-features">
          ${features.map(f => `<div class="soa-feature">${f}</div>`).join('')}
        </div>
      </div>
    `;
  }).join('');
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  // Resolve logged-in gh user → show badge + auto-import all owner repos
  try {
    const me = await GET('/api/me');
    if (me.login) {
      const badge = document.getElementById('gh-user-badge');
      if (badge) badge.textContent = `@${me.login}`;
      const input = document.getElementById('repo-url-input');
      if (input) input.placeholder = `repo-name 或 ${me.login}/repo`;

      // Auto-import all repos for this owner (metadata only, no scan)
      const result = await POST(`/api/import-owner/${me.login}`);
      if (result.imported > 0) {
        toast(`匯入 ${result.imported} 個 ${me.login} 的 repo，點擊 ▷ 開始掃描`, 'info');
      }
    }
  } catch (_) {}

  await refreshAll();
  // Resume polling for any repos already scanning from a previous session
  for (const r of state.repos) {
    if (r.scan_status === 'running') pollScanStatus(r.id);
  }
})();
