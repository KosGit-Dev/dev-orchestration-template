/* 苦手分析ダッシュボード: 進捗・カテゴリ別正答率・苦手タグ */
(function () {
  'use strict';
  const U = window.WCQ;

  function totals() {
    const st = U.Store.get();
    const qs = window.WCQ_QUESTIONS || [];
    let c = 0;
    let w = 0;
    Object.values(st.answers).forEach((a) => { c += a.c; w += a.w; });
    const answeredIds = Object.keys(st.answers).length;
    return { st, qs, c, w, tries: c + w, answeredIds };
  }

  function ring(rate, size, label) {
    const r = 54;
    const cl = 2 * Math.PI * r;
    return `
<svg viewBox="0 0 140 140" class="ring" style="width:${size}px">
  <circle cx="70" cy="70" r="${r}" fill="none" stroke="rgba(255,255,255,0.09)" stroke-width="11"/>
  <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--accent)" stroke-width="11"
    stroke-linecap="round" stroke-dasharray="${(cl * rate) / 100} ${cl}" transform="rotate(-90 70 70)"/>
  <text x="70" y="66" text-anchor="middle" class="ring-num">${rate}%</text>
  <text x="70" y="88" text-anchor="middle" class="ring-sub">${U.esc(label)}</text>
</svg>`;
  }

  function render(view, actions) {
    const { st, qs, c, tries, answeredIds } = totals();
    const rate = U.pct(c, tries);
    const wrongN = st.wrongSet.length;

    /* レベル別: 到達度（回答済み問題数/総数）と正答率 */
    const levelRows = Object.keys(U.LEVELS).map((lv) => {
      const total = qs.filter((q) => q.level === lv).length;
      const seen = qs.filter((q) => q.level === lv && st.answers[q.id]).length;
      const s = st.levelStats[lv] || { c: 0, w: 0 };
      return { lv, total, seen, rate: U.pct(s.c, s.c + s.w), tries: s.c + s.w };
    });

    /* カテゴリ別正答率（試行があるもののみ、正答率昇順 = 苦手が上） */
    const catRows = Object.entries(st.catStats)
      .map(([cat, s]) => ({ cat, tries: s.c + s.w, rate: U.pct(s.c, s.c + s.w) }))
      .filter((x) => x.tries >= 1)
      .sort((a, b) => a.rate - b.rate || b.tries - a.tries);

    const weakTags = U.Store.weakTags(2).slice(0, 8);

    view.innerHTML = `
<div class="stats-mode">
  <h2 class="mode-title">苦手分析</h2>
  ${tries === 0 ? `
  <div class="card empty"><p>まだ回答履歴がありません。演習モードで問題を解くと、ここに分析が表示されます。</p></div>` : `
  <div class="card stats-hero">
    ${ring(rate, 130, '総合正答率')}
    <div class="stats-hero-nums">
      <div class="stat-tile"><span class="stat-num">${tries}</span><span class="stat-label">総回答数</span></div>
      <div class="stat-tile"><span class="stat-num">${answeredIds}<span class="stat-den">/${qs.length}</span></span><span class="stat-label">挑戦済み問題</span></div>
      <div class="stat-tile"><span class="stat-num">${wrongN}</span><span class="stat-label">要復習</span></div>
    </div>
  </div>

  <div class="card">
    <h3 class="card-title">級別の進み具合</h3>
    ${levelRows.map((r) => `
    <div class="lv-row">
      <span class="lv-name">${U.esc(U.levelLabel(r.lv))}</span>
      <div class="mini-bar dual">
        <div class="cover" style="width:${U.pct(r.seen, r.total)}%"></div>
      </div>
      <span class="lv-val">${r.seen}/${r.total}問 ・ 正答率${r.tries ? `${r.rate}%` : '—'}</span>
    </div>`).join('')}
  </div>

  <div class="card">
    <h3 class="card-title">カテゴリ別正答率 <span class="card-note">低い順（＝苦手が上）</span></h3>
    ${catRows.map((r) => `
    <div class="mini-bar-row">
      <span class="mini-bar-label">${U.esc(U.catLabel(r.cat))}</span>
      <div class="mini-bar"><div style="width:${r.rate}%"></div></div>
      <span class="mini-bar-val">${r.rate}%<span class="mini-bar-n">(${r.tries})</span></span>
    </div>`).join('') || '<p class="empty">データ不足</p>'}
  </div>

  <div class="card">
    <h3 class="card-title">苦手キーワード <span class="card-note">誤答率の高いタグ</span></h3>
    ${weakTags.length ? `<div class="weak-tags">
      ${weakTags.map((t) => `<span class="tag warn">#${U.esc(t.tag)} <b>${Math.round(t.rate * 100)}%誤答</b></span>`).join('')}
    </div>` : '<p class="empty">同じタグの問題を2回以上解くと表示されます。</p>'}
  </div>

  <div class="stats-actions">
    <button class="btn primary wide" data-act="weak" ${tries < 5 ? 'disabled' : ''}>苦手克服モードで出題（10問）</button>
    <button class="btn wide" data-act="review" ${wrongN === 0 ? 'disabled' : ''}>間違えた問題を復習（${wrongN}問）</button>
  </div>`}
  <button class="btn danger-line wide" data-act="reset">学習履歴をリセット</button>
</div>`;

    const weakBtn = view.querySelector('[data-act=weak]');
    if (weakBtn) weakBtn.onclick = actions.weak;
    const revBtn = view.querySelector('[data-act=review]');
    if (revBtn) revBtn.onclick = actions.review;
    view.querySelector('[data-act=reset]').onclick = () => {
      if (confirm('学習履歴（回答・復習リスト・論文下書き）をすべて消去します。よろしいですか？')) {
        U.Store.resetAll();
        render(view, actions);
      }
    };
  }

  window.WCQ.Stats = { render };
})();
