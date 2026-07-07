/* ルーター・ホーム画面・演習設定画面 */
(function () {
  'use strict';
  const U = window.WCQ;
  const view = () => document.getElementById('view');

  const NAV = [
    { id: 'home', label: 'ホーム', icon: '🏠' },
    { id: 'map', label: '地図', icon: '🗺️' },
    { id: 'quiz', label: '演習', icon: '✍️' },
    { id: 'sensory', label: '官能', icon: '🥃' },
    { id: 'essay', label: '論文', icon: '📜' },
  ];

  function routeName() {
    return (location.hash || '#home').slice(1);
  }

  function setNav(active) {
    document.querySelectorAll('.nav-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.route === active.split('/')[0]);
    });
  }

  /* ---- クイズ起動ヘルパ ---- */

  function startQuiz(cfg) {
    document.querySelector('.bottom-nav').classList.add('hidden');
    U.Quiz.run(view(), cfg, () => {
      document.querySelector('.bottom-nav').classList.remove('hidden');
      route(routeName());
    });
  }

  const Launch = {
    level(level, opts) {
      startQuiz({
        mode: 'quiz', title: U.levelLabel(level),
        questions: U.Quiz.Builders.level(level, opts),
      });
    },
    region(region, label) {
      startQuiz({
        mode: 'region', title: label,
        questions: U.Quiz.Builders.region(region, 10),
      });
    },
    regions(regionList, label) {
      startQuiz({
        mode: 'region', title: label,
        questions: U.Quiz.Builders.regions(regionList, 10),
      });
    },
    review() {
      startQuiz({ mode: 'review', title: '復習', questions: U.Quiz.Builders.review() });
    },
    weak() {
      startQuiz({ mode: 'weak', title: '苦手克服', questions: U.Quiz.Builders.weak(10) });
    },
    mock(level) {
      const m = U.Quiz.Builders.mock(level);
      startQuiz({
        mode: 'mock', title: `${U.levelLabel(level)} 模試`,
        questions: m.questions, timerSec: m.timerSec, instant: false,
      });
    },
    sensory(kind) {
      startQuiz({
        mode: 'sensory', title: kind === 'color' ? '色判定' : '香味',
        questions: U.Quiz.Builders.sensory(kind, 10),
      });
    },
  };

  /* ---- 画面 ---- */

  function renderHome() {
    const st = U.Store.get();
    const qs = window.WCQ_QUESTIONS || [];
    let c = 0;
    let t = 0;
    Object.values(st.answers).forEach((a) => { c += a.c; t += a.c + a.w; });
    const wrongN = st.wrongSet.length;
    const seenN = Object.keys(st.answers).length;
    const last = st.sessions[st.sessions.length - 1];

    view().innerHTML = `
<div class="home">
  <div class="hero card">
    <svg class="hero-still" viewBox="0 0 100 100" aria-hidden="true">
      <g fill="none" stroke="var(--accent)" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round">
        <path d="M33 12 h34 c0 23 -4 35 -17 41 c-13 -6 -17 -18 -17 -41 Z"/>
        <path d="M50 53 v25 M36 80 h28"/>
        <path d="M36.5 33 h27" opacity="0.65"/>
      </g>
    </svg>
    <h2>ウイスキーコニサー道場</h2>
    <p class="hero-sub">エキスパート / プロフェッショナル / マスター・オブ・ウイスキー 対策</p>
    <div class="hero-stats">
      <div class="stat-tile"><span class="stat-num">${qs.length}</span><span class="stat-label">収録問題</span></div>
      <div class="stat-tile"><span class="stat-num">${seenN}</span><span class="stat-label">挑戦済み</span></div>
      <div class="stat-tile"><span class="stat-num">${t ? U.pct(c, t) : 0}<span class="stat-den">%</span></span><span class="stat-label">正答率</span></div>
    </div>
    ${last ? `<p class="hero-last">前回: ${U.esc(last.title || last.mode)} ${last.correct}/${last.total}問正解</p>` : ''}
  </div>

  ${wrongN ? `
  <button class="banner card" data-act="review">
    <span class="banner-icon">🔁</span>
    <span><b>${wrongN}問</b>の復習が待っています — 間違えた問題だけ解き直す</span>
  </button>` : ''}

  <div class="mode-grid">
    <button class="mode-card card" data-route="quiz"><span class="mode-icon">✍️</span><h3>級別演習</h3><p>級・分野・問題数を選んで演習/模試</p></button>
    <button class="mode-card card" data-route="map"><span class="mode-icon">🗺️</span><h3>世界地図</h3><p>産地をめぐり豆知識と地域問題へ</p></button>
    <button class="mode-card card" data-route="sensory"><span class="mode-icon">🥃</span><h3>官能トレーニング</h3><p>色判定・色見本帳・香味知識</p></button>
    <button class="mode-card card" data-route="essay"><span class="mode-icon">📜</span><h3>論文対策</h3><p>${(window.WCQ_ESSAYS || []).length}テーマ・タイマー・模範解答</p></button>
    <button class="mode-card card" data-route="stats"><span class="mode-icon">📈</span><h3>苦手分析</h3><p>正答率と苦手傾向、苦手克服出題</p></button>
    <button class="mode-card card" data-act="weak" ${t < 5 ? 'disabled' : ''}><span class="mode-icon">🎯</span><h3>苦手克服</h3><p>あなたの誤答傾向から自動出題</p></button>
  </div>
</div>`;
    view().querySelectorAll('[data-route]').forEach((b) => {
      b.onclick = () => { location.hash = `#${b.dataset.route}`; };
    });
    const rv = view().querySelector('[data-act=review]');
    if (rv) rv.onclick = Launch.review;
    const wk = view().querySelector('[data-act=weak]');
    if (wk && !wk.disabled) wk.onclick = Launch.weak;
  }

  function renderQuizSetup() {
    const qs = window.WCQ_QUESTIONS || [];
    const counts = { expert: 0, professional: 0, master: 0 };
    qs.forEach((q) => { if (counts[q.level] != null) counts[q.level] += 1; });
    let level = 'expert';
    let cat = '';
    let num = 10;

    function catOptions() {
      const inLv = qs.filter((q) => level === 'all' || q.level === level);
      const cats = [...new Set(inLv.map((q) => q.category))].sort();
      return `<option value="">すべての分野</option>` +
        cats.map((cN) => `<option value="${cN}" ${cN === cat ? 'selected' : ''}>${U.esc(U.catLabel(cN))}</option>`).join('');
    }

    view().innerHTML = `
<div class="quiz-setup">
  <h2 class="mode-title">級別演習</h2>
  <div class="card">
    <p class="exam-label">受験級</p>
    <div class="lv-select">
      ${Object.keys(U.LEVELS).map((lv) => `
      <button class="lv-btn ${lv === level ? 'active' : ''}" data-lv="${lv}">
        <span class="lv-btn-name">${U.esc(U.levelLabel(lv))}</span>
        <span class="lv-btn-n">${counts[lv]}問収録</span>
      </button>`).join('')}
      <button class="lv-btn ${level === 'all' ? 'active' : ''}" data-lv="all">
        <span class="lv-btn-name">全級ミックス</span><span class="lv-btn-n">${qs.length}問収録</span>
      </button>
    </div>
    <p class="exam-label">分野</p>
    <select id="qs-cat" class="select">${catOptions()}</select>
    <p class="exam-label">問題数</p>
    <div class="chips" id="qs-num">
      ${[10, 25, 50].map((n) => `<button class="chip ${n === num ? 'active' : ''}" data-n="${n}">${n}問</button>`).join('')}
    </div>
    <button class="btn primary wide" data-act="start">演習をはじめる</button>
  </div>
  <div class="card">
    <h3 class="card-title">模擬試験 <span class="card-note">時間制限つき・解説は最後にまとめて</span></h3>
    <div class="mock-row">
      <button class="btn" data-mock="expert">エキスパート模試<br><small>60問 / 60分</small></button>
      <button class="btn" data-mock="professional">プロフェッショナル模試<br><small>60問 / 70分</small></button>
      <button class="btn" data-mock="master">マスター模試<br><small>40問 / 60分</small></button>
    </div>
  </div>
</div>`;
    view().querySelectorAll('[data-lv]').forEach((b) => {
      b.onclick = () => {
        level = b.dataset.lv;
        view().querySelectorAll('[data-lv]').forEach((x) => x.classList.toggle('active', x === b));
        document.getElementById('qs-cat').innerHTML = catOptions();
      };
    });
    view().querySelector('#qs-cat').onchange = (e) => { cat = e.target.value; };
    view().querySelectorAll('#qs-num .chip').forEach((b) => {
      b.onclick = () => {
        num = Number(b.dataset.n);
        view().querySelectorAll('#qs-num .chip').forEach((x) => x.classList.toggle('active', x === b));
      };
    });
    view().querySelector('[data-act=start]').onclick = () => {
      Launch.level(level, { category: cat || null, count: num, unseenFirst: true });
    };
    view().querySelectorAll('[data-mock]').forEach((b) => {
      b.onclick = () => Launch.mock(b.dataset.mock);
    });
  }

  /* ---- ルーティング ---- */

  function route(name) {
    document.querySelector('.bottom-nav').classList.remove('hidden');
    setNav(name);
    const v = view();
    v.scrollTop = 0;
    window.scrollTo(0, 0);
    if (name === 'home' || name === '') renderHome();
    else if (name === 'map') U.MapMode.render(v, {}, (regions, label) => Launch.regions(regions, label));
    else if (name.startsWith('map/')) U.MapMode.render(v, { area: name.slice(4) }, (regions, label) => Launch.regions(regions, label));
    else if (name === 'quiz') renderQuizSetup();
    else if (name === 'sensory') U.Sensory.renderHome(v, (kind) => Launch.sensory(kind));
    else if (name === 'essay') U.Essay.renderList(v, (id) => { location.hash = `#essay/${id}`; });
    else if (name.startsWith('essay/')) U.Essay.renderDetail(v, name.slice(6), () => { location.hash = '#essay'; });
    else if (name === 'stats') U.Stats.render(v, { weak: Launch.weak, review: Launch.review });
    else renderHome();
  }

  function init() {
    const nav = document.querySelector('.bottom-nav');
    nav.innerHTML = NAV.map((n) => `
      <button class="nav-btn" data-route="${n.id}"><span class="nav-icon">${n.icon}</span><span>${n.label}</span></button>`).join('');
    nav.querySelectorAll('.nav-btn').forEach((b) => {
      b.onclick = () => { location.hash = `#${b.dataset.route}`; route(b.dataset.route); };
    });
    window.addEventListener('hashchange', () => route(routeName()));
    route(routeName());
  }

  document.addEventListener('DOMContentLoaded', init);
})();
