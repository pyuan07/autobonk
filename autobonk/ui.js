// Shared chrome for the PokéBonk pages: top bar nav, live bot control, status polling, toast.
(() => {
  const ICONS = {
    dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 1 18 0"/><path d="m12 12 4-4"/><path d="M3 12h2M19 12h2M12 3v2"/><circle cx="12" cy="12" r="1.5"/><path d="M5 18h14"/></svg>',
    cards: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="3" width="13" height="16" rx="2"/><path d="M4 7v12a2 2 0 0 0 2 2h10"/><path d="M11 9h5M11 13h5"/></svg>',
    targets: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5Z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="5" height="16" rx="1.5"/><rect x="14" y="4" width="5" height="16" rx="1.5"/></svg>',
  };
  const PAGES = [
    ['dashboard', '/', '运行仪表盘'],
    ['cards', '/cards', '卡牌权重'],
    ['targets', '/targets', '地图目标'],
  ];

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  // ---------- Top bar ----------
  const bar = document.querySelector('header.topbar');
  const page = bar?.dataset.page;
  if (bar) {
    const nav = PAGES.map(([key, href, label]) =>
      `<a href="${href}"${key === page ? ' aria-current="page"' : ''} title="${label}">${ICONS[key]}<span>${label}</span></a>`).join('');
    bar.insertAdjacentHTML('afterbegin', `
      <a href="/" class="brand"><span class="brand-mark">B</span><span>PokéBonk</span></a>
      <nav class="nav" aria-label="页面">${nav}</nav>
      <span class="spacer"></span>`);
    bar.insertAdjacentHTML('beforeend', `
      <div class="bot is-offline" id="botControl">
        <span class="bot-state" role="status" aria-live="polite"><span class="dot"></span><span class="label" id="botLabel">未连接</span></span>
        <button class="bot-toggle" id="botToggle" type="button" disabled aria-label="启动机器人" title="启动机器人">${ICONS.play}</button>
      </div>`);
  }

  // ---------- Status polling ----------
  const listeners = [];
  let last = null;
  let busy = false;

  function botMode(s) {
    if (!s || !s.connected) return 'offline';
    return s.paused ? 'paused' : 'running';
  }

  function paintControl(s) {
    const ctl = $('botControl');
    if (!ctl) return;
    const mode = botMode(s);
    ctl.className = `bot is-${mode}`;
    $('botLabel').textContent = { offline: s ? '未连接游戏' : '控制器离线', paused: '已暂停', running: '运行中' }[mode];
    const btn = $('botToggle');
    btn.disabled = mode === 'offline' || busy;
    const label = mode === 'running' ? '暂停机器人' : '启动机器人';
    btn.innerHTML = mode === 'running' ? ICONS.pause : ICONS.play;
    btn.setAttribute('aria-label', label);
    btn.title = label;
  }

  async function poll() {
    try {
      const res = await fetch('/api/status', { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      last = await res.json();
    } catch {
      last = null;
    }
    paintControl(last);
    for (const fn of listeners) fn(last);
    setTimeout(poll, 1000);
  }

  async function toggleBot() {
    if (botMode(last) === 'offline' || busy) return;
    const action = last.paused ? 'start' : 'pause';
    busy = true;
    paintControl(last);
    try {
      const res = await fetch('/api/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      // Show the requested state right away; the next poll confirms it.
      last = { ...last, paused: action === 'pause' };
    } catch (err) {
      toast('操作失败：' + err.message, true);
    } finally {
      busy = false;
      paintControl(last);
      for (const fn of listeners) fn(last);
    }
  }

  $('botToggle')?.addEventListener('click', toggleBot);

  // ---------- Toast ----------
  let toastEl, toastTimer;
  function toast(msg, isError = false) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.toggle('error', isError);
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), isError ? 6000 : 2600);
  }

  // ---------- Save state helper (cards + targets) ----------
  function syncState(dirty, text) {
    const s = $('syncState');
    if (s) {
      s.textContent = text ?? (dirty ? '有未保存的修改' : '已同步');
      s.classList.toggle('dirty', dirty);
    }
    $('saveBtn')?.classList.toggle('dirty', dirty);
  }

  window.Bonk = {
    $, esc, toast, toggleBot, syncState, botMode,
    onStatus(fn) { listeners.push(fn); if (last !== null) fn(last); },
    get status() { return last; },
  };

  poll();
})();
