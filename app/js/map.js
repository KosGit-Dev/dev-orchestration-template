/* 世界地図モード v2: 塗りエリア → 産地ドリルダウン → 蒸留所詳細・スクロール年表 */
(function () {
  'use strict';
  const U = window.WCQ;
  const M = () => window.WCQ.MapMeta;

  function areasData() {
    const d = window.WCQ_AREAS;
    const map = {};
    ((d && d.areas) || []).forEach((a) => { map[a.id] = a; });
    return map;
  }

  function questionsIn(regions) {
    const set = new Set(regions);
    return (window.WCQ_QUESTIONS || []).filter((q) => set.has(q.region));
  }

  /* ---- 座標ユーティリティ ---- */

  function polyPath(poly) {
    const pts = poly.map(([lon, lat]) => U.project(lon, lat));
    return `M${pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('L')}Z`;
  }

  function pointInPoly(x, y, poly) {
    let inside = false;
    const pts = poly.map(([lon, lat]) => U.project(lon, lat));
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const xi = pts[i].x; const yi = pts[i].y; const xj = pts[j].x; const yj = pts[j].y;
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  /* ---- パン・ズーム・タップ入力（pointer capture に依存しない） ---- */

  function attachInput(frame, svg, vb, onTap, redraw) {
    const pointers = new Map();
    let lastPinch = 0;
    let moved = false;
    let downAt = null;

    function toSvgXY(cx, cy) {
      // preserveAspectRatio による余白・切り抜きも含めて正確に変換する
      const m = svg.getScreenCTM();
      if (!m) {
        const r = svg.getBoundingClientRect();
        return { x: vb.x + ((cx - r.left) / r.width) * vb.w, y: vb.y + ((cy - r.top) / r.height) * vb.h };
      }
      const p = new DOMPoint(cx, cy).matrixTransform(m.inverse());
      return { x: p.x, y: p.y };
    }
    function svgScale() {
      const m = svg.getScreenCTM();
      return m ? m.a : svg.getBoundingClientRect().width / vb.w;
    }
    function zoomAt(cx, cy, factor, minW, maxW) {
      const nw = Math.min(maxW, Math.max(minW, vb.w / factor));
      const k = nw / vb.w;
      vb.x = cx - (cx - vb.x) * k;
      vb.y = cy - (cy - vb.y) * k;
      vb.w = nw; vb.h = vb.h * k;
      redraw();
    }

    frame.addEventListener('pointerdown', (ev) => {
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pointers.size === 1) { moved = false; downAt = { x: ev.clientX, y: ev.clientY, t: Date.now() }; }
    });
    frame.addEventListener('pointermove', (ev) => {
      if (!pointers.has(ev.pointerId)) return;
      const prev = pointers.get(ev.pointerId);
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pointers.size === 1) {
        if (downAt && Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > 7) moved = true;
        if (moved) {
          const k = svgScale();
          vb.x -= (ev.clientX - prev.x) / k;
          vb.y -= (ev.clientY - prev.y) / k;
          redraw();
        }
      } else if (pointers.size === 2) {
        moved = true;
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (lastPinch > 0) {
          const mid = toSvgXY((a.x + b.x) / 2, (a.y + b.y) / 2);
          zoomAt(mid.x, mid.y, dist / lastPinch, vb.minW, vb.maxW);
        }
        lastPinch = dist;
      }
    });
    function up(ev) {
      if (pointers.has(ev.pointerId) && pointers.size === 1 && !moved && downAt) {
        const p = toSvgXY(ev.clientX, ev.clientY);
        onTap(p.x, p.y);
      }
      pointers.delete(ev.pointerId);
      if (pointers.size < 2) lastPinch = 0;
    }
    frame.addEventListener('pointerup', up);
    frame.addEventListener('pointercancel', (ev) => pointers.delete(ev.pointerId));
    frame.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const p = toSvgXY(ev.clientX, ev.clientY);
      zoomAt(p.x, p.y, ev.deltaY < 0 ? 1.25 : 0.8, vb.minW, vb.maxW);
    }, { passive: false });
    return { toSvgXY, zoomAt };
  }

  function zoomButtons(ctrl, vb) {
    return `
<div class="map-zoom">
  <button class="icon-btn" data-z="in" aria-label="拡大">＋</button>
  <button class="icon-btn" data-z="out" aria-label="縮小">−</button>
</div>`;
  }

  /* ================= 世界ビュー ================= */

  function renderWorld(view, nav) {
    const world = window.WCQ_WORLD;
    // ウイスキーベルト（欧州中心）を大きく見せる初期表示
    const yTop = U.project(0, 74).y;
    const yBottom = U.project(0, -14).y;

    view.innerHTML = `
<div class="map-mode">
  <h2 class="mode-title">世界のウイスキー産地 <span class="mode-sub">エリアをタップして探検</span></h2>
  <div class="map-frame" id="map-frame">
    <svg id="map-svg" preserveAspectRatio="xMidYMid slice">
      <defs>
        <filter id="blob-blur" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3.2"/>
        </filter>
      </defs>
      <rect x="-2000" y="-2000" width="6000" height="6000" class="map-sea"/>
      <path d="${world.path}" class="map-land"/>
      <g id="w-blobs"></g>
      <g id="w-labels"></g>
    </svg>
    ${zoomButtons()}
    <div class="map-hint">色のついた産地をタップ ／ ドラッグで移動・ピンチで拡大</div>
  </div>
  <div class="area-chips">
    ${M().AREAS.map((a) => `<button class="chip area-chip" data-area="${a.id}" style="--ac:${a.color}">${U.esc(a.name)}</button>`).join('')}
  </div>
</div>`;

    const svg = view.querySelector('#map-svg');
    const frame = view.querySelector('#map-frame');
    const vb = { x: 0, y: yTop, w: world.w, h: yBottom - yTop, minW: world.w / 8, maxW: world.w * 1.1 };
    // 横長画面では幅基準、縦長では slice によりウイスキーベルト中心が保たれる

    function redraw() {
      svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      drawBlobs();
    }

    function drawBlobs() {
      // 実描画倍率（CSSピクセル/SVG単位）。slice 切り抜き時も正確
      const m = svg.getScreenCTM();
      const k = m ? m.a : svg.getBoundingClientRect().width / vb.w;
      const scale = 1 / Math.max(k, 0.001);
      const blobs = view.querySelector('#w-blobs');
      const labels = view.querySelector('#w-labels');
      blobs.innerHTML = M().AREAS.map((a) => {
        const p = U.project(a.c[0], a.c[1]);
        return `
<g class="w-blob" data-area="${a.id}">
  <ellipse cx="${p.x}" cy="${p.y}" rx="${a.rx}" ry="${a.ry}" fill="${a.color}" opacity="0.3" filter="url(#blob-blur)"/>
  <ellipse cx="${p.x}" cy="${p.y}" rx="${a.rx * 0.55}" ry="${a.ry * 0.55}" fill="${a.color}" opacity="0.35" filter="url(#blob-blur)"/>
  <ellipse cx="${p.x}" cy="${p.y}" rx="${a.rx}" ry="${a.ry}" fill="none" stroke="${a.color}" stroke-opacity="0.5" stroke-width="${0.8 * scale + 0.3}" stroke-dasharray="2.5 2"/>
</g>`;
      }).join('');
      const fs = Math.min(16, Math.max(4, 12.5 * scale));
      labels.innerHTML = M().AREAS.map((a) => {
        const p = U.project(a.c[0], a.c[1]);
        // side 指定で欧州圏のラベル衝突を回避する
        let x = p.x; let y = p.y - a.ry - fs * 0.45; let anchor = 'middle';
        if (a.side === 'below') { y = p.y + a.ry + fs * 1.1; }
        else if (a.side === 'left') { x = p.x - a.rx - fs * 0.4; y = p.y + fs * 0.35; anchor = 'end'; }
        else if (a.side === 'right') { x = p.x + a.rx + fs * 0.4; y = p.y + fs * 0.35; anchor = 'start'; }
        const nm = (fs > 6 && a.short) ? a.short : a.name;
        return `<text x="${x}" y="${y}" text-anchor="${anchor}" class="w-label" font-size="${fs}" fill="${a.color}">${U.esc(nm)}</text>`;
      }).join('');
    }

    attachInput(frame, svg, vb, (x, y) => {
      // ブロブ楕円のヒットテスト（少し余裕を持たせる）
      for (const a of M().AREAS) {
        const p = U.project(a.c[0], a.c[1]);
        const dx = (x - p.x) / (a.rx * 1.25);
        const dy = (y - p.y) / (a.ry * 1.25);
        if (dx * dx + dy * dy <= 1) { nav.openArea(a.id); return; }
      }
    }, redraw);

    view.querySelectorAll('[data-z]').forEach((b) => {
      b.onclick = () => {
        const f = b.dataset.z === 'in' ? 1.5 : 0.66;
        const cx = vb.x + vb.w / 2; const cy = vb.y + vb.h / 2;
        const nw = Math.min(vb.maxW, Math.max(vb.minW, vb.w / f));
        const k = nw / vb.w;
        vb.x = cx - (cx - vb.x) * k; vb.y = cy - (cy - vb.y) * k; vb.w = nw; vb.h *= k;
        redraw();
      };
    });
    view.querySelectorAll('.area-chip').forEach((b) => { b.onclick = () => nav.openArea(b.dataset.area); });
    redraw();
  }

  /* ================= エリア詳細ビュー ================= */

  function renderArea(view, areaId, nav) {
    const meta = M().AREAS.find((a) => a.id === areaId) || M().AREAS[0];
    const pack = areasData()[areaId];
    const amap = (window.WCQ_AREAMAPS || {})[areaId];
    const subs = M().SUBREGIONS[areaId] || [];
    const dists = (pack && pack.distilleries) || [];
    const qCount = questionsIn(meta.regions).length;
    const st = U.Store.get();

    if (!amap) { nav.openWorld(); return; }
    const pad = Math.max(amap.vb[2], amap.vb[3]) * 0.04;

    view.innerHTML = `
<div class="map-mode area-mode" style="--ac:${meta.color}">
  <div class="q-head">
    <button class="icon-btn" data-act="back" aria-label="世界地図へ戻る">←</button>
    <div class="area-title">
      <h2>${U.esc(meta.name)}</h2>
      ${pack ? `<p class="area-tagline">${U.esc(pack.tagline || '')}</p>` : ''}
    </div>
  </div>
  <div class="map-frame area-frame" id="map-frame">
    <svg id="map-svg" preserveAspectRatio="xMidYMid meet">
      <rect x="-9000" y="-9000" width="20000" height="20000" class="map-sea"/>
      <path d="${amap.path}" class="map-land area-land"/>
      <g id="a-subs"></g>
      <g id="a-pins"></g>
    </svg>
    ${zoomButtons()}
    <div class="map-hint">蒸留所ピンをタップ ／ ピンチで拡大</div>
  </div>

  <div class="area-actions">
    <button class="btn primary" data-act="timeline">📜 歴史年表をたどる</button>
    <button class="btn" data-act="quiz" ${qCount ? '' : 'disabled'}>この産地の問題（全${qCount}問から10問）</button>
  </div>
  ${subs.length ? `<div class="chips sub-chips">${subs.map((s) => `<button class="chip" data-sub="${s.id}" style="--ac:${s.color}">${U.esc(s.name)}</button>`).join('')}</div>` : ''}

  ${pack ? `
  <div class="card area-bg-card">
    <h3 class="card-title">この土地とウイスキー</h3>
    <div class="area-bg" id="area-bg">${U.esc(pack.background || '').split('\n').filter(Boolean).map((p) => `<p>${p}</p>`).join('')}</div>
    <button class="read-more" data-act="more">続きを読む</button>
  </div>
  <div class="dist-list card">
    <h3 class="card-title">蒸留所をめぐる <span class="card-note">${dists.length}箇所</span></h3>
    ${dists.map((d) => `
    <button class="dist-row" data-dist="${U.esc(d.id)}">
      <span class="dist-dot" style="background:${meta.color}"></span>
      <span class="dist-name">${U.esc(d.name)}<small>${U.esc(d.en || '')}</small></span>
      <span class="dist-founded">${d.founded ? `${d.founded}年` : ''}</span>
      <span class="dist-seen">${st.seenTrivia.indexOf(`dist-${d.id}`) >= 0 ? '✓' : ''}</span>
    </button>`).join('')}
  </div>` : '<div class="card empty"><p>この産地の詳細データは準備中です。</p></div>'}
  <div class="sheet" id="dist-sheet" hidden></div>
</div>`;

    const svg = view.querySelector('#map-svg');
    const frame = view.querySelector('#map-frame');
    const vb = {
      x: amap.vb[0] - pad, y: amap.vb[1] - pad, w: amap.vb[2] + pad * 2, h: amap.vb[3] + pad * 2,
      minW: amap.vb[2] / 12, maxW: (amap.vb[2] + pad * 2) * 1.3,
    };

    function redraw() {
      svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      drawOverlays();
    }

    function drawOverlays() {
      const scale = vb.w / (amap.vb[2] + pad * 2);
      const subsG = view.querySelector('#a-subs');
      const pinsG = view.querySelector('#a-pins');
      const base = amap.vb[2] / 100; // エリアサイズに応じた基準単位

      subsG.innerHTML = subs.map((s) => {
        if (s.circles) {
          return s.circles.map((c) => {
            const p = U.project(c.c[0], c.c[1]);
            const r = c.r * base * 1.2;
            return `<circle cx="${p.x}" cy="${p.y}" r="${r}" class="sub-zone" style="--sc:${s.color}"/>
                    <text x="${p.x}" y="${p.y - r - base}" text-anchor="middle" class="sub-label" font-size="${base * 3.2}" fill="${s.color}" style="stroke-width:${(base * 0.55).toFixed(2)}px">${U.esc(c.label)}</text>`;
          }).join('');
        }
        const p0 = U.project(s.poly[0][0], s.poly[0][1]);
        return `<path d="${polyPath(s.poly)}" class="sub-zone" style="--sc:${s.color}"/>
                <text x="${p0.x}" y="${p0.y - base}" class="sub-label" font-size="${base * 3.4}" fill="${s.color}" style="stroke-width:${(base * 0.55).toFixed(2)}px">${U.esc(s.name)}</text>`;
      }).join('');

      const r = Math.max(base * 1.6, base * 4.5 * scale);
      const fs = Math.max(base * 2.6, base * 5.5 * scale);
      // ラベルの衝突間引き: 近接ピンはドットのみ表示（拡大すると順次ラベルが現れる）
      const placed = [];
      const cx = vb.x + vb.w / 2;
      pinsG.innerHTML = dists.map((d) => {
        const p = U.project(d.lon, d.lat);
        const flip = p.x > cx; // 右半分のピンはラベルを左側へ
        let label = '';
        const collides = placed.some((q) => Math.abs(p.y - q.y) < fs * 1.3 && Math.abs(p.x - q.x) < fs * 9);
        if (!collides) {
          placed.push(p);
          label = `<text x="${flip ? p.x - r * 1.5 : p.x + r * 1.5}" y="${p.y + fs * 0.35}" text-anchor="${flip ? 'end' : 'start'}" class="map-label" font-size="${fs}" style="stroke-width:${(fs * 0.18).toFixed(2)}px">${U.esc(d.name)}</text>`;
        }
        return `
<g class="a-pin" data-dist="${U.esc(d.id)}">
  <circle cx="${p.x}" cy="${p.y}" r="${r}" class="pin-dot" fill="${meta.color}"/>
  <circle cx="${p.x}" cy="${p.y}" r="${r * 0.4}" fill="#140f08"/>
  ${label}
</g>`;
      }).join('');
    }

    attachInput(frame, svg, vb, (x, y) => {
      // ピン優先ヒットテスト → サブリージョン
      const scale = vb.w / (amap.vb[2] + pad * 2);
      const base = amap.vb[2] / 100;
      const hitR = Math.max(base * 3, base * 7 * scale);
      let best = null;
      for (const d of dists) {
        const p = U.project(d.lon, d.lat);
        const dd = Math.hypot(x - p.x, y - p.y);
        if (dd < hitR && (!best || dd < best.dd)) best = { d, dd };
      }
      if (best) { openDist(best.d); return; }
      for (const s of subs) {
        if (s.poly && pointInPoly(x, y, s.poly)) { subQuiz(s); return; }
        if (s.circles) {
          for (const c of s.circles) {
            const p = U.project(c.c[0], c.c[1]);
            if (Math.hypot(x - p.x, y - p.y) < c.r * base * 1.3) { subQuiz(s); return; }
          }
        }
      }
    }, redraw);

    function subQuiz(s) {
      nav.goQuiz([s.id], s.name);
    }

    function openDist(d) {
      U.Store.markTrivia(`dist-${d.id}`);
      const sheet = view.querySelector('#dist-sheet');
      const regionQs = questionsIn([d.region]);
      sheet.hidden = false;
      sheet.innerHTML = `
<div class="sheet-grip"></div>
<div class="sheet-head">
  <div>
    <h3>${U.esc(d.name)} <span class="dist-en">${U.esc(d.en || '')}</span></h3>
    <p class="sheet-sub">${d.founded ? `${d.founded}年創業 ・ ` : ''}${U.esc(U.regionLabel(d.region))}</p>
  </div>
  <button class="icon-btn" data-act="close" aria-label="閉じる">✕</button>
</div>
<p class="sheet-trivia">${U.esc(d.history || '')}</p>
${(d.bottles || []).length ? `
<p class="sheet-label">代表銘柄</p>
<div class="bottle-list">${d.bottles.map((b) => `<span class="bottle">🥃 ${U.esc(b)}</span>`).join('')}</div>` : ''}
${d.trivia ? `<div class="trivia-box"><span class="trivia-mark">豆知識</span>${U.esc(d.trivia)}</div>` : ''}
${regionQs.length ? `<button class="btn primary wide" data-act="dq">${U.esc(U.regionLabel(d.region))}の問題に挑戦</button>` : ''}`;
      sheet.querySelector('[data-act=close]').onclick = () => { sheet.hidden = true; };
      const dq = sheet.querySelector('[data-act=dq]');
      if (dq) dq.onclick = () => nav.goQuiz([d.region], U.regionLabel(d.region));
      sheet.scrollTop = 0;
    }

    view.querySelector('[data-act=back]').onclick = nav.openWorld;
    view.querySelector('[data-act=timeline]').onclick = () => renderTimeline(view, meta, pack);
    const qb = view.querySelector('[data-act=quiz]');
    if (qb && !qb.disabled) qb.onclick = () => nav.goQuiz(meta.regions, meta.name);
    view.querySelectorAll('[data-sub]').forEach((b) => {
      b.onclick = () => {
        const s = subs.find((x) => x.id === b.dataset.sub);
        if (s) nav.goQuiz([s.id], s.name);
      };
    });
    view.querySelectorAll('.dist-row').forEach((b) => {
      b.onclick = () => {
        const d = dists.find((x) => x.id === b.dataset.dist);
        if (d) openDist(d);
      };
    });
    const moreBtn = view.querySelector('[data-act=more]');
    if (moreBtn) {
      moreBtn.onclick = () => {
        view.querySelector('#area-bg').classList.toggle('expanded');
        moreBtn.textContent = view.querySelector('#area-bg').classList.contains('expanded') ? '閉じる' : '続きを読む';
      };
    }
    view.querySelectorAll('[data-z]').forEach((b) => {
      b.onclick = () => {
        const f = b.dataset.z === 'in' ? 1.5 : 0.66;
        const cx = vb.x + vb.w / 2; const cy = vb.y + vb.h / 2;
        const nw = Math.min(vb.maxW, Math.max(vb.minW, vb.w / f));
        const k = nw / vb.w;
        vb.x = cx - (cx - vb.x) * k; vb.y = cy - (cy - vb.y) * k; vb.w = nw; vb.h *= k;
        redraw();
      };
    });
    redraw();
  }

  /* ================= スクロール年表 ================= */

  function renderTimeline(view, meta, pack) {
    const events = ((pack && pack.timeline) || []).slice().sort((a, b) => a.year - b.year);
    if (!events.length) return;
    const eras = M().ERAS;
    const overlay = U.el(`
<div class="tl-overlay" style="--ac:${meta.color}">
  <div class="tl-head">
    <div>
      <p class="tl-kicker">HISTORY OF</p>
      <h2>${U.esc(meta.name)}のウイスキー史</h2>
    </div>
    <button class="icon-btn" data-act="close" aria-label="閉じる">✕</button>
  </div>
  <div class="tl-era-banner" id="tl-era"><span class="tl-era-name"></span><span class="tl-era-desc"></span></div>
  <div class="tl-scroll" id="tl-scroll">
    <div class="tl-spine"></div>
    ${events.map((e, i) => {
    const era = eras[e.era] || eras.origins;
    return `
    <section class="tl-event ${i % 2 ? 'alt' : ''}" data-era="${U.esc(e.era)}" style="--ec:${era.color}">
      <div class="tl-node">${M().iconSVG(e.icon, 26)}</div>
      <div class="tl-card">
        <div class="tl-year">${e.year}<span class="tl-era-tag">${U.esc(era.name)}</span></div>
        <h4>${U.esc(e.title)}</h4>
        <p>${U.esc(e.text)}</p>
      </div>
    </section>`;
  }).join('')}
    <div class="tl-end">
      <p>物語は現在も続いている——</p>
      <button class="btn primary" data-act="tl-quiz">この産地の問題に挑戦</button>
    </div>
  </div>
</div>`);
    document.body.appendChild(overlay);
    document.body.classList.add('no-scroll');

    function close() {
      overlay.remove();
      document.body.classList.remove('no-scroll');
    }
    overlay.querySelector('[data-act=close]').onclick = close;
    const tq = overlay.querySelector('[data-act=tl-quiz]');
    if (tq) {
      tq.onclick = () => {
        close();
        const backBtn = view.querySelector('[data-act=quiz]');
        if (backBtn && !backBtn.disabled) backBtn.click();
      };
    }

    // スクロール連動: 表示中イベントの時代をバナーに反映 + カードのフェードイン
    const banner = overlay.querySelector('#tl-era');
    const nameEl = banner.querySelector('.tl-era-name');
    const descEl = banner.querySelector('.tl-era-desc');
    function setEra(eraId) {
      const era = eras[eraId] || eras.origins;
      banner.style.setProperty('--ec', era.color);
      nameEl.textContent = `${era.name}（${era.range}）`;
      descEl.textContent = era.desc;
    }
    setEra(events[0].era);
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) {
          en.target.classList.add('shown');
          setEra(en.target.dataset.era);
        }
      });
    }, { root: overlay.querySelector('#tl-scroll'), threshold: 0.55 });
    overlay.querySelectorAll('.tl-event').forEach((el) => io.observe(el));
  }

  /* ================= エントリポイント ================= */

  function render(view, opts, goQuizRegions) {
    const nav = {
      openWorld: () => { location.hash = '#map'; },
      openArea: (id) => { location.hash = `#map/${id}`; },
      goQuiz: goQuizRegions,
    };
    if (opts && opts.area && (window.WCQ_AREAMAPS || {})[opts.area]) {
      renderArea(view, opts.area, nav);
    } else {
      renderWorld(view, nav);
    }
  }

  window.WCQ.MapMode = { render };
})();
