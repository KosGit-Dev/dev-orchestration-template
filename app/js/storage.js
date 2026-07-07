/* 学習状態の永続化（localStorage、使用不可なら揮発メモリへフォールバック） */
(function () {
  'use strict';

  const KEY = 'wcq-state-v1';
  let memoryFallback = null;

  const DEFAULT = () => ({
    answers: {},   // qid -> {c, w, last}
    wrongSet: [],  // 復習対象の qid
    tagStats: {},  // tag -> {c, w}
    catStats: {},  // category -> {c, w}
    levelStats: {},// level -> {c, w}
    essays: {},    // essId -> {draft, ts, points:{}, rubric:{}, done}
    sessions: [],  // {mode, level, total, correct, ts}
    seenTrivia: [],// 地図で閲覧済みポイント id
  });

  function load() {
    if (memoryFallback) return memoryFallback;
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return DEFAULT();
      const st = JSON.parse(raw);
      return Object.assign(DEFAULT(), st);
    } catch (e) {
      memoryFallback = memoryFallback || DEFAULT();
      return memoryFallback;
    }
  }

  function save(st) {
    try {
      localStorage.setItem(KEY, JSON.stringify(st));
    } catch (e) {
      memoryFallback = st; // プライベートモード等では揮発保存で継続する
    }
  }

  function bump(map, key, correct) {
    if (!map[key]) map[key] = { c: 0, w: 0 };
    if (correct) map[key].c += 1; else map[key].w += 1;
  }

  const Store = {
    get: load,

    recordAnswer(q, correct) {
      const st = load();
      if (!st.answers[q.id]) st.answers[q.id] = { c: 0, w: 0, last: 0 };
      const a = st.answers[q.id];
      if (correct) a.c += 1; else a.w += 1;
      a.last = Date.now();
      const inWrong = st.wrongSet.indexOf(q.id);
      if (correct && inWrong >= 0) st.wrongSet.splice(inWrong, 1);
      if (!correct && inWrong < 0) st.wrongSet.push(q.id);
      (q.tags || []).forEach((t) => bump(st.tagStats, t, correct));
      if (q.category) bump(st.catStats, q.category, correct);
      if (q.level) bump(st.levelStats, q.level, correct);
      save(st);
      return st;
    },

    pushSession(rec) {
      const st = load();
      st.sessions.push(rec);
      if (st.sessions.length > 200) st.sessions = st.sessions.slice(-200);
      save(st);
    },

    markTrivia(id) {
      const st = load();
      if (st.seenTrivia.indexOf(id) < 0) {
        st.seenTrivia.push(id);
        save(st);
      }
    },

    essay(id) {
      const st = load();
      return st.essays[id] || null;
    },

    saveEssay(id, patch) {
      const st = load();
      st.essays[id] = Object.assign(st.essays[id] || { draft: '', points: {}, rubric: {} }, patch, { ts: Date.now() });
      save(st);
    },

    /* タグごとの誤答率（試行2回以上のみ対象） */
    weakTags(minTries) {
      const st = load();
      const min = minTries == null ? 2 : minTries;
      return Object.entries(st.tagStats)
        .map(([tag, s]) => ({ tag, tries: s.c + s.w, rate: s.w / (s.c + s.w) }))
        .filter((x) => x.tries >= min && x.rate > 0)
        .sort((a, b) => b.rate - a.rate || b.tries - a.tries);
    },

    /* 問題ごとの「苦手スコア」: 自身の誤答履歴 + 苦手タグとの一致度 */
    weaknessScore(q) {
      const st = load();
      let score = 0;
      const a = st.answers[q.id];
      if (a && a.c + a.w > 0) score += (a.w / (a.c + a.w)) * 2;
      let tagSum = 0;
      let tagN = 0;
      (q.tags || []).forEach((t) => {
        const s = st.tagStats[t];
        if (s && s.c + s.w >= 2) {
          tagSum += s.w / (s.c + s.w);
          tagN += 1;
        }
      });
      if (tagN > 0) score += tagSum / tagN;
      const cs = st.catStats[q.category];
      if (cs && cs.c + cs.w >= 3) score += (cs.w / (cs.c + cs.w)) * 0.5;
      return score;
    },

    resetAll() {
      memoryFallback = null;
      try { localStorage.removeItem(KEY); } catch (e) { /* noop */ }
    },
  };

  window.WCQ.Store = Store;
})();
