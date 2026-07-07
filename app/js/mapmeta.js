/* 地図モード v2 の静的メタデータ: エリア定義・塗りブロブ・時代区分・アイコン */
(function () {
  'use strict';

  /* 各エリアの表示順・色・世界ビューの塗り位置（lon/lat 中心 + 地図単位の半径） */
  const AREAS = [
    { id: 'scotland', name: 'スコットランド', color: '#e0a24e', c: [-4.2, 57.1], rx: 13, ry: 10, side: 'above', regions: ['scotland-speyside', 'scotland-islay', 'scotland-highland', 'scotland-lowland', 'scotland-campbeltown', 'scotland-islands'] },
    { id: 'ireland', name: 'アイルランド', color: '#6fbf73', c: [-8.0, 53.3], rx: 10, ry: 8, side: 'left', regions: ['ireland'] },
    { id: 'england-wales', name: 'イングランド＆ウェールズ', short: '英・ウェールズ', color: '#b39ddb', c: [-1.5, 52.3], rx: 10, ry: 9, side: 'below', regions: ['england-wales'] },
    { id: 'europe', name: 'ヨーロッパ大陸・北欧', short: '欧州・北欧', color: '#9db95e', c: [10.0, 56.5], rx: 20, ry: 22, side: 'right', regions: ['europe-other'] },
    { id: 'usa', name: 'アメリカ', color: '#cd8b62', c: [-86.0, 36.5], rx: 18, ry: 9, side: 'below', regions: ['usa-kentucky', 'usa-tennessee', 'usa-other'] },
    { id: 'canada', name: 'カナダ', color: '#8fb7d9', c: [-80.0, 46.5], rx: 26, ry: 9, side: 'above', regions: ['canada'] },
    { id: 'japan', name: '日本', color: '#e2725b', c: [137.5, 38.0], rx: 12, ry: 15, side: 'right', regions: ['japan'] },
    { id: 'taiwan', name: '台湾', color: '#d96fa0', c: [121.0, 23.7], rx: 6, ry: 6, side: 'left', regions: ['taiwan'] },
    { id: 'india', name: 'インド', color: '#d9c84a', c: [77.5, 17.0], rx: 13, ry: 12, side: 'left', regions: ['india'] },
    { id: 'australia', name: 'オーストラリア', color: '#7fd0c9', c: [146.5, -39.5], rx: 11, ry: 9, side: 'above', regions: ['australia'] },
  ];

  /* スコットランド内の産地区分（lon/lat の簡略ポリゴン。厳密な境界ではなく学習用の目安） */
  const SUBREGIONS = {
    scotland: [
      { id: 'scotland-speyside', name: 'スペイサイド', color: '#f0c069',
        poly: [[-3.95, 57.75], [-2.75, 57.75], [-2.75, 57.25], [-3.95, 57.25]] },
      { id: 'scotland-islay', name: 'アイラ', color: '#c47b1e',
        poly: [[-6.6, 55.95], [-5.95, 55.95], [-5.95, 55.5], [-6.6, 55.5]] },
      { id: 'scotland-campbeltown', name: 'キャンベルタウン', color: '#e2725b',
        poly: [[-5.8, 55.55], [-5.35, 55.55], [-5.35, 55.15], [-5.8, 55.15]] },
      { id: 'scotland-lowland', name: 'ローランド', color: '#9db95e',
        poly: [[-4.95, 55.95], [-2.2, 56.9], [-1.95, 55.6], [-3.0, 54.85], [-5.1, 54.8]] },
      { id: 'scotland-highland', name: 'ハイランド', color: '#b8863b',
        poly: [[-5.9, 58.65], [-3.0, 58.7], [-2.05, 57.7], [-2.2, 56.95], [-4.95, 55.98], [-5.6, 56.4], [-6.3, 57.0], [-5.4, 57.9]] },
      { id: 'scotland-islands', name: 'アイランズ', color: '#8fb7d9', circles: [
        { c: [-6.25, 57.4], r: 4.5, label: 'スカイ' },
        { c: [-3.0, 59.0], r: 4, label: 'オークニー' },
        { c: [-6.05, 56.4], r: 3.5, label: 'マル' },
        { c: [-5.6, 55.95], r: 2.8, label: 'ジュラ' },
        { c: [-5.25, 55.58], r: 2.6, label: 'アラン' },
      ] },
    ],
  };

  /* 年表の時代区分 */
  const ERAS = {
    origins: { name: '起源の時代', range: '〜1700', color: '#8a7b5c', desc: '修道士と生命の水' },
    smuggling: { name: '密造の時代', range: '1700-1823', color: '#7d6f9e', desc: '霧の中の蒸留器' },
    industrial: { name: '産業の時代', range: '1823-1900', color: '#c47b1e', desc: '公認・技術革新・ブレンデッド' },
    crisis: { name: '試練の時代', range: '1900-1980', color: '#a05252', desc: '戦争・禁酒法・大閉鎖' },
    renaissance: { name: '復興の時代', range: '1980-', color: '#6fae7d', desc: 'シングルモルトとクラフトの世紀' },
  };

  /* 年表用アイコン（24x24 線画。stroke は currentColor） */
  const ICONS = {
    scroll: '<path d="M7 4h11a2 2 0 0 1 2 2v1h-3M7 4a2 2 0 0 0-2 2v12a2 2 0 0 1-2 2h13a2 2 0 0 0 2-2V7M7 4v13a2 2 0 0 1-2 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 9h6M9 12.5h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
    still: '<path d="M9 3h6M10 3v3.5q0 1 .8 1.6L12 9l1.2-.9q.8-.6.8-1.6V3M12 9c-4 1.4-5.5 4-5.5 7a5.5 5.5 0 0 0 11 0c0-3-1.5-5.6-5.5-7Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 12l3.5 2v3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    barrel: '<ellipse cx="12" cy="5" rx="6.5" ry="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M5.5 5v11.5q0 2.5 6.5 2.5t6.5-2.5V5M4.8 10.5h14.4M4.8 14h14.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    ship: '<path d="M4 15h16l-2 4H6ZM12 15V4M12 5l6 7h-6M12 7L8 12h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 20q1.5 1 3 0t3 0 3 0 3 0 3 0 3 0" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
    factory: '<path d="M4 20V9l5 3V9l5 3V9l6 3v8ZM4 20h16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M6.5 5V3M6.5 5a1.5 1.5 0 1 0 0 .01" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M8 16h2M13 16h2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    law: '<path d="M12 3v18M8 21h8M12 6H6.5M12 6h5.5M6.5 6L4 12a3 3 0 0 0 5 0ZM17.5 6L15 12a3 3 0 0 0 5 0Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    fire: '<path d="M12 21c-3.6 0-6-2.3-6-5.6 0-2.8 2-4.7 3.4-6.4C10.7 7.4 11.5 5.7 11 3c3.5 1.6 4.6 4 4.3 6.2 1.4.4 2.7 2.2 2.7 4.2 0 4-2.4 7.6-6 7.6Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 21c-1.6-.9-2.4-2.2-2.2-3.8.2-1.4 1.2-2.3 2.2-3.4 1 1.1 2 2 2.2 3.4.2 1.6-.6 2.9-2.2 3.8Z" fill="none" stroke="currentColor" stroke-width="1.3"/>',
    trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0ZM8 5H5v1.5A3.5 3.5 0 0 0 8.5 10M16 5h3v1.5A3.5 3.5 0 0 1 15.5 10M12 13v4M9 20h6l-.7-3h-4.6Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    glass: '<path d="M6 4h12l-1 7a5 5 0 0 1-10 0ZM12 16v4M8.5 21h7M7 8.5h10.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    crown: '<path d="M4 17l-1-9 5 3.5L12 5l4 6.5L21 8l-1 9Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M4.5 20h15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    train: '<rect x="5" y="4" width="14" height="12" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M5 10.5h14M9 4v6.5M15 4v6.5" stroke="currentColor" stroke-width="1.4"/><circle cx="8.7" cy="13.4" r="1" fill="currentColor"/><circle cx="15.3" cy="13.4" r="1" fill="currentColor"/><path d="M7.5 16.5L5.5 20M16.5 16.5l2 3.5M6.8 19h10.4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    globe: '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3.5 12h17M12 3.5c-6.5 5.5-6.5 11.5 0 17M12 3.5c6.5 5.5 6.5 11.5 0 17" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  };

  function iconSVG(name, size, cls) {
    const body = ICONS[name] || ICONS.scroll;
    return `<svg viewBox="0 0 24 24" width="${size || 22}" height="${size || 22}" class="${cls || ''}" aria-hidden="true">${body}</svg>`;
  }

  window.WCQ = window.WCQ || {};
  window.WCQ.MapMeta = { AREAS, SUBREGIONS, ERAS, ICONS, iconSVG };
})();
