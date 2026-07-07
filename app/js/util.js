/* 共通ユーティリティ・定数・ラベル定義 */
(function () {
  'use strict';

  const LEVELS = {
    expert: { label: 'エキスパート', short: 'EX', order: 1 },
    professional: { label: 'プロフェッショナル', short: 'PR', order: 2 },
    master: { label: 'マスター・オブ・ウイスキー', short: 'MW', order: 3 },
  };

  const CATEGORIES = {
    'region-knowledge': '産地・地理',
    distillery: '蒸留所',
    production: '製造工程',
    ingredients: '原料',
    maturation: '熟成・樽',
    blending: 'ブレンド',
    regulation: '法規・定義',
    history: '歴史',
    people: '人物',
    brand: 'ブランド・製品',
    tasting: 'テイスティング',
    chemistry: '香味成分',
    culture: '文化・カクテル',
    business: '業界・市場',
  };

  const REGIONS = {
    'scotland-speyside': 'スペイサイド',
    'scotland-islay': 'アイラ',
    'scotland-highland': 'ハイランド',
    'scotland-lowland': 'ローランド',
    'scotland-campbeltown': 'キャンベルタウン',
    'scotland-islands': 'アイランズ',
    ireland: 'アイルランド',
    'usa-kentucky': 'ケンタッキー',
    'usa-tennessee': 'テネシー',
    'usa-other': 'アメリカその他',
    canada: 'カナダ',
    japan: '日本',
    taiwan: '台湾',
    india: 'インド',
    australia: 'オーストラリア',
    'england-wales': 'イングランド・ウェールズ',
    'europe-other': '欧州その他',
    'world-other': '世界その他',
  };

  const ESSAY_CATS = {
    history: '歴史',
    production: '製造',
    region: '産地',
    regulation: '法規・定義',
    business: 'ビジネス',
    culture: '文化',
    tasting: 'テイスティング',
    japan: '日本',
  };

  /* Miller 図法（scripts/whisky_map_convert.py と同じ定数） */
  const MAP_W = 1000;
  const LAT_TOP = 78;
  const LAT_BOTTOM = -56;
  function millerY(latDeg) {
    const lat = (latDeg * Math.PI) / 180;
    return 1.25 * Math.log(Math.tan(Math.PI / 4 + 0.4 * lat));
  }
  const Y_TOP = millerY(LAT_TOP);
  const Y_BOTTOM = millerY(LAT_BOTTOM);
  const MAP_H = (MAP_W * (Y_TOP - Y_BOTTOM)) / (2 * Math.PI);
  function project(lon, lat) {
    return {
      x: ((lon + 180) / 360) * MAP_W,
      y: ((Y_TOP - millerY(lat)) / (Y_TOP - Y_BOTTOM)) * MAP_H,
    };
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function sample(arr, n) {
    return shuffle(arr).slice(0, n);
  }

  function pct(c, t) {
    return t > 0 ? Math.round((c / t) * 100) : 0;
  }

  function fmtTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  window.WCQ = window.WCQ || {};
  Object.assign(window.WCQ, {
    LEVELS, CATEGORIES, REGIONS, ESSAY_CATS,
    MAP_W, MAP_H, project,
    esc, shuffle, sample, pct, fmtTime, el,
    levelLabel: (l) => (LEVELS[l] ? LEVELS[l].label : l),
    catLabel: (c) => CATEGORIES[c] || c,
    regionLabel: (r) => REGIONS[r] || r,
  });
})();
