/* 世界地図モード: パン・ズーム・ポイント選択・豆知識シート */
(function () {
  'use strict';
  const U = window.WCQ;

  const JUMPS = [
    { label: '世界', box: null },
    { label: 'スコットランド', c: [-4.2, 57.0], z: 22 },
    { label: 'アイルランド', c: [-7.5, 53.3], z: 18 },
    { label: '日本', c: [137.5, 38.0], z: 9 },
    { label: '北米', c: [-88, 38], z: 4.2 },
    { label: 'アジア・豪', c: [110, 10], z: 2.6 },
    { label: '欧州', c: [5, 50], z: 7 },
  ];

  const KIND = { region: '産地', distillery: '蒸留所', landmark: '歴史地点' };

  function render(view, goQuiz) {
    const world = window.WCQ_WORLD;
    const points = (window.WCQ_MAP && window.WCQ_MAP.points) || [];
    const st = U.Store.get();
    const seen = new Set(st.seenTrivia);

    view.innerHTML = `
<div class="map-mode">
  <div class="map-jumps">
    ${JUMPS.map((j, i) => `<button class="chip" data-jump="${i}">${j.label}</button>`).join('')}
  </div>
  <div class="map-frame" id="map-frame">
    <svg id="map-svg" viewBox="0 0 ${world.w} ${world.h}" preserveAspectRatio="xMidYMid meet">
      <rect x="-2000" y="-2000" width="5000" height="5000" class="map-sea"/>
      <path d="${world.path}" class="map-land"/>
      <g id="map-pts"></g>
    </svg>
    <div class="map-hint">ドラッグで移動 / ピンチ・ホイールで拡大。琥珀の点をタップ。</div>
  </div>
  <p class="map-progress">豆知識 閲覧済み ${seen.size}/${points.length} 地点</p>
  <div class="sheet" id="map-sheet" hidden></div>
</div>`;

    const svg = view.querySelector('#map-svg');
    const ptsG = view.querySelector('#map-pts');
    const sheet = view.querySelector('#map-sheet');

    /* ビュー状態（viewBox 操作でパン・ズーム） */
    const vb = { x: 0, y: 0, w: world.w, h: world.h };
    function applyVB() {
      svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      drawPoints();
    }
    function zoomAt(cx, cy, factor) {
      const nw = Math.min(world.w * 1.2, Math.max(world.w / 60, vb.w / factor));
      const k = nw / vb.w;
      vb.x = cx - (cx - vb.x) * k;
      vb.y = cy - (cy - vb.y) * k;
      vb.w = nw;
      vb.h = vb.h * k;
      applyVB();
    }

    function drawPoints() {
      const scale = vb.w / world.w; // 1=全体表示
      const r = Math.max(2.2, 7 * Math.sqrt(scale));
      const showLabels = scale < 0.34;
      ptsG.innerHTML = points.map((p) => {
        const xy = U.project(p.lon, p.lat);
        const cls = `map-pt kind-${p.kind}${seen.has(p.id) ? ' seen' : ''}`;
        const label = showLabels
          ? `<text x="${xy.x + r * 1.6}" y="${xy.y + r * 0.6}" class="map-label" font-size="${Math.max(3.4, 11 * scale * 2.2)}">${U.esc(p.name)}</text>` : '';
        return `<g class="${cls}" data-id="${U.esc(p.id)}">
          <circle cx="${xy.x}" cy="${xy.y}" r="${r * 1.7}" class="map-hit"/>
          <circle cx="${xy.x}" cy="${xy.y}" r="${r}" class="map-dot"/>
          ${label}</g>`;
      }).join('');
      ptsG.querySelectorAll('.map-pt').forEach((g) => {
        g.addEventListener('click', (ev) => {
          ev.stopPropagation();
          openSheet(points.find((p) => p.id === g.dataset.id));
        });
      });
    }

    function openSheet(p) {
      if (!p) return;
      U.Store.markTrivia(p.id);
      seen.add(p.id);
      const regionQs = (window.WCQ_QUESTIONS || []).filter((q) => q.region === p.region);
      const label = U.regionLabel(p.region);
      sheet.hidden = false;
      sheet.innerHTML = `
<div class="sheet-grip"></div>
<div class="sheet-head">
  <div>
    <h3>${U.esc(p.name)}</h3>
    <p class="sheet-sub">${U.esc(p.country)} ・ ${KIND[p.kind] || ''}</p>
  </div>
  <button class="icon-btn" data-act="close" aria-label="閉じる">✕</button>
</div>
<p class="sheet-trivia">${U.esc(p.trivia)}</p>
${regionQs.length ? `
<button class="btn primary wide" data-act="quiz">
  ${U.esc(label)}の問題に挑戦（全${regionQs.length}問から10問）
</button>` : '<p class="sheet-sub">この地域の問題は準備中です。</p>'}`;
      sheet.querySelector('[data-act=close]').onclick = () => { sheet.hidden = true; };
      const qb = sheet.querySelector('[data-act=quiz]');
      if (qb) qb.onclick = () => goQuiz(p.region, label);
      const seenEl = view.querySelector('.map-progress');
      if (seenEl) seenEl.textContent = `豆知識 閲覧済み ${seen.size}/${points.length} 地点`;
    }

    /* パン（ドラッグ）とピンチズーム */
    const frame = view.querySelector('#map-frame');
    const pointers = new Map();
    let lastPinch = 0;
    function toSvgXY(ev) {
      const rect = svg.getBoundingClientRect();
      return {
        x: vb.x + ((ev.clientX - rect.left) / rect.width) * vb.w,
        y: vb.y + ((ev.clientY - rect.top) / rect.height) * vb.h,
      };
    }
    frame.addEventListener('pointerdown', (ev) => {
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      frame.setPointerCapture(ev.pointerId);
    });
    frame.addEventListener('pointermove', (ev) => {
      if (!pointers.has(ev.pointerId)) return;
      const prev = pointers.get(ev.pointerId);
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pointers.size === 1) {
        const rect = svg.getBoundingClientRect();
        vb.x -= ((ev.clientX - prev.x) / rect.width) * vb.w;
        vb.y -= ((ev.clientY - prev.y) / rect.height) * vb.h;
        applyVB();
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (lastPinch > 0) {
          const mid = toSvgXY({ clientX: (a.x + b.x) / 2, clientY: (a.y + b.y) / 2 });
          zoomAt(mid.x, mid.y, dist / lastPinch);
        }
        lastPinch = dist;
      }
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach((t) => {
      frame.addEventListener(t, (ev) => {
        pointers.delete(ev.pointerId);
        if (pointers.size < 2) lastPinch = 0;
      });
    });
    frame.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const p = toSvgXY(ev);
      zoomAt(p.x, p.y, ev.deltaY < 0 ? 1.25 : 0.8);
    }, { passive: false });

    view.querySelectorAll('[data-jump]').forEach((b) => {
      b.onclick = () => {
        const j = JUMPS[Number(b.dataset.jump)];
        if (!j.c) { vb.x = 0; vb.y = 0; vb.w = world.w; vb.h = world.h; }
        else {
          const xy = U.project(j.c[0], j.c[1]);
          const w = world.w / j.z;
          const h = (world.h / world.w) * w;
          vb.x = xy.x - w / 2; vb.y = xy.y - h / 2; vb.w = w; vb.h = h;
        }
        applyVB();
      };
    });

    applyVB();
  }

  window.WCQ.MapMode = { render };
})();
