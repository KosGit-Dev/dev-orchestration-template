/* 出題エンジン: 演習・模試・復習・苦手克服・官能クイズを共通で駆動する */
(function () {
  'use strict';
  const U = window.WCQ;

  function pool() {
    return window.WCQ_QUESTIONS || [];
  }

  /* ---- 出題セットの構築 ---- */

  const Builders = {
    level(level, opts) {
      const o = opts || {};
      let qs = pool().filter((q) => (level === 'all' ? true : q.level === level));
      if (o.category) qs = qs.filter((q) => q.category === o.category);
      if (o.unseenFirst) {
        const st = U.Store.get();
        const unseen = qs.filter((q) => !st.answers[q.id]);
        const seen = qs.filter((q) => st.answers[q.id]);
        qs = U.shuffle(unseen).concat(U.shuffle(seen));
        return qs.slice(0, o.count || 10);
      }
      return U.sample(qs, o.count || 10);
    },

    region(region, count) {
      const qs = pool().filter((q) => q.region === region);
      return U.sample(qs, Math.min(count || 10, qs.length));
    },

    regions(regionList, count) {
      const set = new Set(regionList);
      const qs = pool().filter((q) => set.has(q.region));
      return U.sample(qs, Math.min(count || 10, qs.length));
    },

    review(count) {
      const st = U.Store.get();
      const set = new Set(st.wrongSet);
      const qs = pool().filter((q) => set.has(q.id));
      return U.sample(qs, count ? Math.min(count, qs.length) : qs.length);
    },

    weak(count) {
      const scored = pool()
        .map((q) => ({ q, s: U.Store.weaknessScore(q) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s);
      const top = scored.slice(0, Math.max((count || 10) * 3, 30)).map((x) => x.q);
      return U.sample(top, Math.min(count || 10, top.length));
    },

    mock(level) {
      const spec = { expert: [60, 60], professional: [60, 70], master: [40, 60] }[level] || [60, 60];
      const qs = pool().filter((q) => q.level === level && q.type !== 'color');
      return { questions: U.sample(qs, spec[0]), timerSec: spec[1] * 60 };
    },

    sensory(kind, count) {
      let qs;
      if (kind === 'color') qs = pool().filter((q) => q.type === 'color');
      else qs = pool().filter((q) => q.type === 'aroma' || q.type === 'offflavor');
      return U.sample(qs, Math.min(count || 10, qs.length));
    },
  };

  /* ---- グラス描画（官能・色判定用） ---- */

  function glassSVG(hex) {
    const c = U.esc(hex || '#C88A2E');
    return `
<svg class="glass" viewBox="0 0 120 140" role="img" aria-label="ウイスキーの色見本">
  <defs>
    <linearGradient id="liq-${c.replace('#', '')}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${c}" stop-opacity="0.72"/>
      <stop offset="1" stop-color="${c}"/>
    </linearGradient>
  </defs>
  <path d="M28 14 h64 v96 q0 16 -32 16 q-32 0 -32 -16 Z" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.35)" stroke-width="2.5"/>
  <path d="M33 58 h54 v50 q0 12 -27 12 q-27 0 -27 -12 Z" fill="url(#liq-${c.replace('#', '')})"/>
  <ellipse cx="60" cy="58" rx="27" ry="5" fill="${c}" opacity="0.9"/>
  <path d="M36 20 q2 44 1 86" stroke="rgba(255,255,255,0.28)" stroke-width="3" fill="none" stroke-linecap="round"/>
</svg>`;
  }

  /* ---- セッション実行 ---- */

  function run(view, cfg, onExit) {
    const questions = cfg.questions.filter(Boolean);
    if (!questions.length) {
      view.innerHTML = `<div class="empty card"><p>出題できる問題がありません。</p>
        <button class="btn" data-act="exit">戻る</button></div>`;
      view.querySelector('[data-act=exit]').onclick = onExit;
      return;
    }
    const state = {
      i: 0,
      correct: 0,
      results: [],           // {q, pickedText, correct}
      remain: cfg.timerSec || 0,
      timerId: null,
      instant: cfg.instant !== false, // 即時解説（模試は false）
    };

    function stopTimer() {
      if (state.timerId) { clearInterval(state.timerId); state.timerId = null; }
    }

    function header() {
      const timer = cfg.timerSec
        ? `<span class="q-timer ${state.remain <= 60 ? 'danger' : ''}" id="q-timer">${U.fmtTime(state.remain)}</span>` : '';
      return `
<div class="q-head">
  <button class="icon-btn" data-act="exit" aria-label="中断">✕</button>
  <div class="q-progress"><div class="q-progress-bar" style="width:${(state.i / questions.length) * 100}%"></div></div>
  <span class="q-count">${state.i + 1}/${questions.length}</span>${timer}
</div>`;
    }

    function renderQuestion() {
      const q = questions[state.i];
      const order = U.shuffle(q.choices.map((_, idx) => idx));
      const color = q.color_hex ? `<div class="glass-wrap">${glassSVG(q.color_hex)}</div>` : '';
      view.innerHTML = `
${header()}
<div class="q-card card">
  <div class="q-meta">
    <span class="badge lv-${U.esc(q.level)}">${U.esc(U.levelLabel(q.level))}</span>
    <span class="badge cat">${U.esc(U.catLabel(q.category))}</span>
  </div>
  ${color}
  <p class="q-text">${U.esc(q.question)}</p>
  <div class="choices">
    ${order.map((ci, pos) => `
      <button class="choice" data-ci="${ci}">
        <span class="choice-key">${'ABCD'[pos]}</span>${U.esc(q.choices[ci])}
      </button>`).join('')}
  </div>
</div>`;
      view.querySelector('[data-act=exit]').onclick = () => { stopTimer(); onExit(); };
      view.querySelectorAll('.choice').forEach((btn) => {
        btn.onclick = () => answer(q, Number(btn.dataset.ci), btn);
      });
      tickTimer();
    }

    function tickTimer() {
      if (!cfg.timerSec || state.timerId) return;
      state.timerId = setInterval(() => {
        state.remain -= 1;
        const t = document.getElementById('q-timer');
        if (t) {
          t.textContent = U.fmtTime(Math.max(0, state.remain));
          if (state.remain <= 60) t.classList.add('danger');
        }
        if (state.remain <= 0) { stopTimer(); finish(true); }
      }, 1000);
    }

    function answer(q, ci, btn) {
      const ok = ci === q.answer;
      if (ok) state.correct += 1;
      state.results.push({ q, picked: q.choices[ci], correct: ok });
      U.Store.recordAnswer(q, ok);
      view.querySelectorAll('.choice').forEach((b) => {
        b.disabled = true;
        if (Number(b.dataset.ci) === q.answer) b.classList.add('is-correct');
      });
      if (!ok) btn.classList.add('is-wrong');

      if (state.instant) {
        const card = view.querySelector('.q-card');
        card.appendChild(U.el(`
<div class="explain ${ok ? 'ok' : 'ng'}">
  <div class="explain-title">${ok ? '◯ 正解' : '✕ 不正解'}</div>
  <p>${U.esc(q.explanation || '')}</p>
  <div class="explain-tags">${(q.tags || []).map((t) => `<span class="tag">#${U.esc(t)}</span>`).join('')}</div>
  <button class="btn primary" data-act="next">${state.i + 1 >= questions.length ? '結果を見る' : '次の問題'}</button>
</div>`));
        const nx = card.querySelector('[data-act=next]');
        nx.onclick = next;
        nx.scrollIntoView({ behavior: 'smooth', block: 'end' });
      } else {
        setTimeout(next, 350);
      }
    }

    function next() {
      state.i += 1;
      if (state.i >= questions.length) finish(false);
      else renderQuestion();
    }

    function finish(timeUp) {
      stopTimer();
      const total = state.results.length;
      const rate = U.pct(state.correct, total);
      U.Store.pushSession({ mode: cfg.mode || 'quiz', title: cfg.title || '', total, correct: state.correct, ts: Date.now() });

      const byCat = {};
      state.results.forEach((r) => {
        const c = r.q.category || 'other';
        if (!byCat[c]) byCat[c] = { c: 0, t: 0 };
        byCat[c].t += 1;
        if (r.correct) byCat[c].c += 1;
      });
      const wrongs = state.results.filter((r) => !r.correct);
      const grade = rate >= 90 ? '素晴らしい。マスター級の仕上がりです。'
        : rate >= 70 ? '合格圏です。取りこぼしを復習で潰しましょう。'
          : rate >= 50 ? 'あと一歩。解説を読み込んで再挑戦を。'
            : '基礎から積み直しましょう。復習モードが近道です。';

      view.innerHTML = `
<div class="result card">
  ${timeUp ? '<p class="time-up">⏰ 時間切れ</p>' : ''}
  <div class="ring-wrap">${ringSVG(rate)}</div>
  <p class="result-score">${state.correct} / ${total} 問正解</p>
  <p class="result-grade">${grade}</p>
  <div class="result-cats">
    ${Object.entries(byCat).sort((a, b) => (a[1].c / a[1].t) - (b[1].c / b[1].t)).map(([c, s]) => `
      <div class="mini-bar-row">
        <span class="mini-bar-label">${U.esc(U.catLabel(c))}</span>
        <div class="mini-bar"><div style="width:${U.pct(s.c, s.t)}%"></div></div>
        <span class="mini-bar-val">${s.c}/${s.t}</span>
      </div>`).join('')}
  </div>
  ${wrongs.length ? `
  <details class="wrong-list">
    <summary>間違えた問題（${wrongs.length}問）</summary>
    ${wrongs.map((r) => `
      <div class="wrong-item">
        <p class="wrong-q">${U.esc(r.q.question)}</p>
        <p class="wrong-a">正解: ${U.esc(r.q.choices[r.q.answer])}</p>
        <p class="wrong-e">${U.esc(r.q.explanation || '')}</p>
      </div>`).join('')}
  </details>` : ''}
  <div class="result-actions">
    ${wrongs.length ? '<button class="btn" data-act="retry-wrong">間違いだけ再挑戦</button>' : ''}
    <button class="btn" data-act="again">もう一度</button>
    <button class="btn primary" data-act="exit">終了</button>
  </div>
</div>`;
      view.querySelector('[data-act=exit]').onclick = onExit;
      view.querySelector('[data-act=again]').onclick = () => run(view, cfg, onExit);
      const rw = view.querySelector('[data-act=retry-wrong]');
      if (rw) {
        rw.onclick = () => run(view, {
          mode: 'review', title: '間違い再挑戦', instant: true,
          questions: U.shuffle(wrongs.map((r) => r.q)),
        }, onExit);
      }
    }

    function ringSVG(rate) {
      const r = 54;
      const cLen = 2 * Math.PI * r;
      return `
<svg viewBox="0 0 140 140" class="ring">
  <circle cx="70" cy="70" r="${r}" fill="none" stroke="rgba(255,255,255,0.09)" stroke-width="11"/>
  <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--accent)" stroke-width="11"
    stroke-linecap="round" stroke-dasharray="${(cLen * rate) / 100} ${cLen}"
    transform="rotate(-90 70 70)"/>
  <text x="70" y="66" text-anchor="middle" class="ring-num">${rate}%</text>
  <text x="70" y="88" text-anchor="middle" class="ring-sub">正答率</text>
</svg>`;
    }

    renderQuestion();
  }

  window.WCQ.Quiz = { Builders, run, glassSVG };
})();
