/* 官能トレーニングモード: 色判定・色見本帳・香味知識 */
(function () {
  'use strict';
  const U = window.WCQ;

  function scale() {
    return (window.WCQ_SENSORY && window.WCQ_SENSORY.color_scale) || [];
  }

  function renderHome(view, startQuiz) {
    const colorN = (window.WCQ_QUESTIONS || []).filter((q) => q.type === 'color').length;
    const aromaN = (window.WCQ_QUESTIONS || []).filter((q) => q.type === 'aroma' || q.type === 'offflavor').length;
    view.innerHTML = `
<div class="sen-mode">
  <h2 class="mode-title">官能トレーニング</h2>
  <p class="mode-desc">テイスティング試験の第一歩は色調の見極めです。色見本帳で基準を頭に入れ、判定訓練で反復しましょう。</p>
  <div class="mode-grid">
    <button class="mode-card card" data-act="color">
      <span class="mode-icon">🥃</span>
      <h3>色判定トレーニング</h3>
      <p>グラスの色調から色名・樽・熟成を見極める（${colorN}問）</p>
    </button>
    <button class="mode-card card" data-act="chart">
      <span class="mode-icon">🎨</span>
      <h3>色見本帳</h3>
      <p>${scale().length}段階の色調スケールと典型例</p>
    </button>
    <button class="mode-card card" data-act="aroma">
      <span class="mode-icon">👃</span>
      <h3>香味・オフフレーバー</h3>
      <p>フレーバーホイールと香味成分の知識（${aromaN}問）</p>
    </button>
  </div>
  <div id="sen-body"></div>
</div>`;
    view.querySelector('[data-act=color]').onclick = () => startQuiz('color');
    view.querySelector('[data-act=aroma]').onclick = () => startQuiz('aroma');
    view.querySelector('[data-act=chart]').onclick = () => renderChart(view.querySelector('#sen-body'));
  }

  function renderChart(body) {
    body.innerHTML = `
<div class="color-chart">
  <h3 class="chart-title">ウイスキー色調スケール</h3>
  <p class="mode-desc">上から熟成の浅い順。照明は自然光か白色灯で、白い背景に傾けて見るのが基本です。</p>
  ${scale().map((c) => `
  <div class="color-row card">
    <div class="color-glass">${window.WCQ.Quiz.glassSVG(c.hex)}</div>
    <div class="color-info">
      <h4>${U.esc(c.name_ja)} <span class="color-en">${U.esc(c.name_en || '')}</span></h4>
      <p>${U.esc(c.description || '')}</p>
      ${c.typical ? `<p class="color-typical">典型例: ${U.esc(c.typical)}</p>` : ''}
    </div>
  </div>`).join('')}
</div>`;
    body.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  window.WCQ.Sensory = { renderHome };
})();
