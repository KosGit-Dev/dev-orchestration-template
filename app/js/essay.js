/* 論文対策モード: テーマ一覧・執筆・骨子・模範解答・自己採点 */
(function () {
  'use strict';
  const U = window.WCQ;

  function essays() {
    return window.WCQ_ESSAYS || [];
  }

  function renderList(view, openDetail) {
    const list = essays();
    const cats = ['all'].concat([...new Set(list.map((e) => e.category))]);
    let active = 'all';

    function draw() {
      const items = list.filter((e) => active === 'all' || e.category === active);
      view.querySelector('#ess-list').innerHTML = items.map((e) => {
        const s = U.Store.essay(e.id);
        const status = s && s.done ? '<span class="badge done">自己採点済</span>'
          : s && s.draft ? '<span class="badge draft">下書きあり</span>' : '';
        return `
<button class="ess-card card" data-id="${U.esc(e.id)}">
  <div class="ess-card-top">
    <span class="badge cat">${U.esc(U.ESSAY_CATS[e.category] || e.category)}</span>${status}
  </div>
  <h3>${U.esc(e.title)}</h3>
  <p class="ess-q-preview">${U.esc(e.question)}</p>
</button>`;
      }).join('') || '<p class="empty">テーマがありません。</p>';
      view.querySelectorAll('.ess-card').forEach((c) => {
        c.onclick = () => openDetail(c.dataset.id);
      });
    }

    view.innerHTML = `
<div class="ess-mode">
  <h2 class="mode-title">論文対策 <span class="mode-sub">全${list.length}テーマ</span></h2>
  <p class="mode-desc">マスター・オブ・ウイスキーの筆記は論述が中心です。設問に対して構成を立て、時間内に書き切る訓練をしましょう。</p>
  <div class="chips">
    ${cats.map((c) => `<button class="chip ${c === 'all' ? 'active' : ''}" data-cat="${c}">${c === 'all' ? 'すべて' : U.esc(U.ESSAY_CATS[c] || c)}</button>`).join('')}
  </div>
  <div id="ess-list" class="ess-list"></div>
</div>`;
    view.querySelectorAll('[data-cat]').forEach((b) => {
      b.onclick = () => {
        active = b.dataset.cat;
        view.querySelectorAll('[data-cat]').forEach((x) => x.classList.toggle('active', x === b));
        draw();
      };
    });
    draw();
  }

  function renderDetail(view, id, goBack) {
    const e = essays().find((x) => x.id === id);
    if (!e) { goBack(); return; }
    const saved = U.Store.essay(id) || { draft: '', points: {}, rubric: {} };
    let timerId = null;
    let remain = 0;

    view.innerHTML = `
<div class="ess-detail">
  <div class="q-head">
    <button class="icon-btn" data-act="back" aria-label="戻る">←</button>
    <span class="badge cat">${U.esc(U.ESSAY_CATS[e.category] || e.category)}</span>
    <span class="ess-timer" id="ess-timer"></span>
  </div>
  <div class="card exam-paper">
    <p class="exam-label">設問</p>
    <p class="exam-q">${U.esc(e.question)}</p>
    <p class="exam-chars">目安分量: ${U.esc(e.target_chars || '800〜1200字')}</p>
    <div class="timer-row">
      ${[30, 60, 90].map((m) => `<button class="chip" data-timer="${m}">${m}分で書く</button>`).join('')}
    </div>
  </div>

  <details class="card fold">
    <summary>構成の骨子を見る（まず自力で構成を考えてから）</summary>
    <ol class="outline">${(e.outline || []).map((o) => `<li>${U.esc(o)}</li>`).join('')}</ol>
  </details>

  <details class="card fold">
    <summary>キーポイント チェックリスト（${(e.key_points || []).length}項目）</summary>
    <p class="fold-hint">書き終えてから、盛り込めた論点にチェックを。</p>
    ${(e.key_points || []).map((k, i) => `
      <label class="check-row"><input type="checkbox" data-kp="${i}" ${saved.points[i] ? 'checked' : ''}> ${U.esc(k)}</label>`).join('')}
  </details>

  <div class="card">
    <p class="exam-label">答案（自動保存）</p>
    <textarea id="ess-draft" rows="14" placeholder="ここに論述する。序論→本論→結論の三部構成が基本。">${U.esc(saved.draft)}</textarea>
    <p class="char-count" id="ess-count"></p>
  </div>

  <details class="card fold model-answer">
    <summary>模範解答を見る（自分で書いてから開くこと）</summary>
    <div class="model-body">${U.esc(e.model_answer || '').split('\n').map((p) => `<p>${p}</p>`).join('')}</div>
  </details>

  <div class="card">
    <p class="exam-label">自己採点（採点観点）</p>
    ${(e.rubric || []).map((r, i) => `
      <label class="check-row"><input type="checkbox" data-rb="${i}" ${saved.rubric[i] ? 'checked' : ''}> ${U.esc(r)}</label>`).join('')}
    <button class="btn primary" data-act="done" style="margin-top:12px">採点を保存して完了にする</button>
  </div>
</div>`;

    const ta = view.querySelector('#ess-draft');
    const count = view.querySelector('#ess-count');
    function updateCount() {
      count.textContent = `${ta.value.length} 字`;
    }
    updateCount();
    let deb = null;
    ta.addEventListener('input', () => {
      updateCount();
      clearTimeout(deb);
      deb = setTimeout(() => U.Store.saveEssay(id, { draft: ta.value }), 400);
    });

    view.querySelectorAll('[data-kp]').forEach((cb) => {
      cb.onchange = () => {
        const pts = (U.Store.essay(id) || { points: {} }).points || {};
        pts[cb.dataset.kp] = cb.checked;
        U.Store.saveEssay(id, { points: pts });
      };
    });
    view.querySelectorAll('[data-rb]').forEach((cb) => {
      cb.onchange = () => {
        const rb = (U.Store.essay(id) || { rubric: {} }).rubric || {};
        rb[cb.dataset.rb] = cb.checked;
        U.Store.saveEssay(id, { rubric: rb });
      };
    });
    view.querySelectorAll('[data-timer]').forEach((b) => {
      b.onclick = () => {
        clearInterval(timerId);
        remain = Number(b.dataset.timer) * 60;
        const t = view.querySelector('#ess-timer');
        t.textContent = U.fmtTime(remain);
        timerId = setInterval(() => {
          remain -= 1;
          t.textContent = remain > 0 ? U.fmtTime(remain) : '⏰ 時間切れ';
          t.classList.toggle('danger', remain <= 300);
          if (remain <= 0) clearInterval(timerId);
        }, 1000);
      };
    });
    view.querySelector('[data-act=done]').onclick = () => {
      U.Store.saveEssay(id, { draft: ta.value, done: true });
      goBack();
    };
    view.querySelector('[data-act=back]').onclick = () => {
      clearInterval(timerId);
      U.Store.saveEssay(id, { draft: ta.value });
      goBack();
    };
  }

  window.WCQ.Essay = { renderList, renderDetail };
})();
