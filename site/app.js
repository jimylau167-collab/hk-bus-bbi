/* 全港巴士轉乘車費計算機 — 前端邏輯（純 JavaScript，冇外部套件） */
"use strict";

// 優惠類型（同 crawler/build_data.py 一致）
const T = { GMB: -1, FREE: 0, MINUS: 1, TOTAL: 2, PAY: 3, REBATE: 4, DIFF: 5 };
const CO_NAME = { kmb: "九巴", ctb: "城巴", nlb: "嶼巴", gmb: "小巴", lrtfeeder: "港鐵巴士" };
const KMB_SCHEME = "九巴/龍運轉乘計劃";

let R = [], S = [], BBI = {}, STR = [], META = {};
const byNum = new Map();        // 路線號 → [route idx]
let incoming = null;            // 次程 idx → [[首程 idx, rule]]（轉入查詢先建立）

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v) => (v == null ? "—" : "$" + (Math.round(v * 10) / 10).toFixed(1));
const r1 = (v) => Math.round(v * 10) / 10;

// ---------------------------------------------------------------- 載入數據
async function loadData() {
  const [routes, stops, bbi] = await Promise.all(
    ["data/routes.json", "data/stops.json", "data/bbi.json"].map((u) => fetch(u).then((r) => {
      if (!r.ok) throw new Error(u + " " + r.status);
      return r.json();
    }))
  );
  R = routes.routes.map((x, i) => ({ i, route: x[0], co: x[1], st: x[2], o: x[3], d: x[4], stops: x[7], fares: x[8] }));
  S = stops;
  BBI = bbi.bbi; STR = bbi.strings;
  META = { updated: bbi.updated, sources: bbi.sources, info: bbi.info || [], notes: bbi.notes || [] };
  for (const r of R) {
    if (!byNum.has(r.route)) byNum.set(r.route, []);
    byNum.get(r.route).push(r.i);
  }
  // 香港巴士大典參考資料（可選，冇都照用）
  fetch("data/wiki.json").then((r) => (r.ok ? r.json() : null)).then((w) => { WIKI = w; }).catch(() => {});
}
let WIKI = null;

function wikiRows(route) {
  if (!WIKI) return [];
  const tag = ":" + route + "]";
  const out = [];
  for (const [region, rows] of Object.entries(WIKI.regions || {})) {
    for (const r of rows) if (r[1].includes(tag) || r[3].includes(tag)) out.push([region, ...r]);
  }
  return out;
}
function wikiCell(s) {
  return esc(s).replace(/\[([A-Z]+):([^\]]+)\]/g, (m, co, no) => `<b>${no}</b>`);
}

// ---------------------------------------------------------------- 路線顯示
function isLWB(route) {
  return /^(A3[1-8]|A4[1-7]|E3[1-7]|E4[12]|NA3\d|NA4\d|R33|R42|N30|N31|N36|N42A?|N64|S64)/.test(route);
}
function coLabel(r) {
  const cos = r.co.split("+");
  if (cos.length > 1) return cos.map((c) => CO_NAME[c] || c).join("/");
  if (cos[0] === "kmb" && isLWB(r.route)) return "龍運";
  return CO_NAME[cos[0]] || cos[0];
}
function coClass(r) {
  const cos = r.co.split("+");
  if (cos.length > 1) return "co-joint";
  if (cos[0] === "kmb" && isLWB(r.route)) return "co-lwb";
  return "co-" + cos[0];
}
function chip(r) {
  return `<span class="chip ${coClass(r)}" title="${esc(coLabel(r))}"><span class="chip-co">${esc(coLabel(r))}</span><span class="chip-no">${esc(r.route)}</span></span>`;
}
function variantLabel(r) {
  return `${coLabel(r)} ${r.route} 往 ${r.d}${r.st !== 1 ? "（特別班）" : ""}`;
}
function stopName(id) { return S[id] ? S[id][0] : "?"; }
function fareAt(r, idx) {
  const v = r.fares && r.fares[idx];
  return v == null ? null : v;
}
function routeSortKey(n) {
  const m = n.match(/^([A-Z]*)(\d*)(.*)$/);
  return [m[1], m[2] ? +m[2] : 0, m[3]];
}
function cmpRoute(a, b) {
  const x = routeSortKey(a), y = routeSortKey(b);
  return x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0);
}
function variantsOf(num) {
  const order = { kmb: 0, "kmb+ctb": 1, ctb: 2, nlb: 3, lrtfeeder: 4, gmb: 5 };
  return (byNum.get(num) || []).slice().sort((a, b) =>
    (order[R[a].co] ?? 9) - (order[R[b].co] ?? 9) || R[a].st - R[b].st || R[a].d.localeCompare(R[b].d, "zh-Hant"));
}

// ---------------------------------------------------------------- 優惠規則
function unpack(x) {
  return { b: x[0], t: x[1], amt: x[2], lim: x[3], maxc: x[4], at: STR[x[5]], sch: STR[x[6]], rm: STR[x[7]] };
}
function rulesFrom(a) { return (BBI[a] || []).map(unpack); }
function rulesBetween(a, b) { return rulesFrom(a).filter((r) => r.b === b); }

function ruleText(rule, prevPaid) {
  switch (rule.t) {
    case T.FREE: return "次程免費";
    case T.MINUS: return `次程減 $${rule.amt}`;
    case T.TOTAL: return `兩程合共 $${rule.amt}`;
    case T.PAY: return `次程只付 $${rule.amt}`;
    case T.REBATE: return `回贈 $${rule.amt}`;
    case T.DIFF: return "補次程差額";
    case T.GMB: return "有轉乘優惠（金額未收錄）";
    default: return "優惠";
  }
}
function applyRule(rule, f2, prevPaid) {
  if (f2 == null) return null;
  switch (rule.t) {
    case T.FREE: return 0;
    case T.MINUS: return Math.max(0, r1(f2 - rule.amt));
    case T.TOTAL: return Math.min(f2, Math.max(0, r1(rule.amt - (prevPaid || 0))));
    case T.PAY: return Math.min(f2, rule.amt);
    case T.REBATE: return Math.max(0, r1(f2 - rule.amt));
    case T.DIFF: return Math.max(0, r1(f2 - (prevPaid || 0)));
    default: return f2;
  }
}

// 轉乘站名配對：去除九巴站號 (YT562)，按字詞重疊計分
function cleanAt(at) {
  return (at || "").replace(/\([A-Z]{2}\d{2,4}\)/g, "").replace(/\s*\([A-Z]{0,2}\d*$/, "").replace(/\s+/g, " ").trim();
}
function isAnyStop(at) { return /任何/.test(at || ""); }
function nameScore(at, name) {
  const a = cleanAt(at);
  if (!a || isAnyStop(a)) return 0;
  if (name.includes(a) || a.includes(name)) return 1;
  const toks = a.split(/[\s\-–—\/／、,，()（）]+/).filter((t) => t.length >= 2);
  if (!toks.length) return 0;
  let hit = 0, tot = 0;
  for (const t of toks) {
    tot += t.length;
    if (name.includes(t)) hit += t.length;
    else {
      // 部分字重疊（例如「西區海底隧道」對「西隧轉車站」）
      const core = t.replace(/(巴士)?(轉乘|轉車)站?$/, "");
      if (core.length >= 2 && name.includes(core)) hit += t.length * 0.8;
    }
  }
  return hit / tot;
}
function dist(s1, s2) {
  const a = S[s1], b = S[s2];
  if (!a || !b) return 1e9;
  const dy = (a[2] - b[2]) * 111320, dx = (a[3] - b[3]) * 111320 * Math.cos((a[2] * Math.PI) / 180);
  return Math.sqrt(dx * dx + dy * dy);
}

// 揀轉乘站：首程（上車站之後）同次程之間最近、最似建議站名嘅一對站
function pickTransfer(legA, legB, rules) {
  const A = R[legA.rid], B = R[legB.rid];
  const from = legA.board + 1;
  let best = null;
  for (let i = from; i < A.stops.length; i++) {
    for (let j = 0; j < B.stops.length - 1; j++) {
      const d = A.stops[i] === B.stops[j] ? 0 : dist(A.stops[i], B.stops[j]);
      if (d > 400) continue;
      let ns = 0;
      for (const r of rules) ns = Math.max(ns, nameScore(r.at, stopName(A.stops[i])), nameScore(r.at, stopName(B.stops[j])));
      const score = ns * 1000 - d - (i - from) * 3;
      if (!best || score > best.score) best = { i, j, score };
    }
  }
  return best;
}

// ---------------------------------------------------------------- 計算
function legBaseFare(leg) { return fareAt(R[leg.rid], leg.board); }

function evaluate(legs) {
  const out = [];
  let chain = 0; // 已連續用咗幾多次轉乘優惠
  legs.forEach((leg, k) => {
    const r = R[leg.rid];
    const base = legBaseFare(leg);
    const row = { leg, r, base, paid: base, transfer: null };
    if (k > 0) {
      const prev = out[k - 1];
      const rules = rulesBetween(legs[k - 1].rid, leg.rid);
      const tr = { rules, used: null, alts: [], warn: "", chain };
      if (rules.length) {
        const aName = stopName(R[legs[k - 1].rid].stops[legs[k - 1].alight]);
        const bName = stopName(r.stops[leg.board]);
        const kmbOnly = !R[legs[k - 1].rid].co.includes("+") && !r.co.includes("+") &&
          R[legs[k - 1].rid].co === "kmb" && r.co === "kmb";
        const cands = rules.map((rule) => {
          const ns = Math.max(nameScore(rule.at, aName), nameScore(rule.at, bName));
          const atOK = isAnyStop(rule.at) || ns >= 0.5 || (kmbOnly && rule.sch === KMB_SCHEME) || rule.t === T.GMB;
          const chainOK = (rule.maxc || 1) >= chain + 1;
          const paid = applyRule(rule, base, prev.paid);
          return { rule, atOK, chainOK, paid };
        });
        const ok = cands.filter((c) => c.atOK && c.chainOK);
        ok.sort((x, y) => (x.paid ?? 1e9) - (y.paid ?? 1e9));
        if (ok.length) {
          tr.used = ok[0];
          row.paid = ok[0].paid;
          tr.alts = ok.slice(1);
        } else if (cands.some((c) => c.atOK && !c.chainOK)) {
          tr.warn = "已經連續用咗轉乘優惠，呢程唔可以再減（指定組合除外）。";
        } else {
          const sug = cleanAt(rules[0].at);
          tr.warn = `你揀嘅轉乘站未必有優惠，建議喺「${sug}」轉乘。`;
          tr.suggest = true;
        }
        tr.cands = cands;
      }
      chain = tr.used && tr.used.rule.t !== T.GMB ? chain + 1 : 0;
      row.transfer = tr;
    }
    out.push(row);
  });
  return out;
}

// ---------------------------------------------------------------- 計算機介面
const state = { legs: [] };

function newLeg(rid) {
  const r = R[rid];
  return { rid, board: 0, alight: r.stops.length - 1 };
}
function setLegRoute(k, rid) {
  state.legs[k] = newLeg(rid);
  if (k > 0) autoTransfer(k);
  if (k + 1 < state.legs.length) autoTransfer(k + 1);
}
function autoTransfer(k) {
  const a = state.legs[k - 1], b = state.legs[k];
  if (!a || !b) return;
  const rules = rulesBetween(a.rid, b.rid);
  const p = pickTransfer(a, b, rules);
  if (p) {
    a.alight = p.i;
    b.board = p.j;
    if (b.alight <= b.board) b.alight = R[b.rid].stops.length - 1;
  }
}

function routeOptions(listId) {
  const nums = [...byNum.keys()].sort(cmpRoute);
  return `<datalist id="${listId}">${nums.map((n) => `<option value="${esc(n)}"></option>`).join("")}</datalist>`;
}

function renderCalc() {
  const res = evaluate(state.legs);
  const total = res.reduce((s, x) => s + (x.paid ?? 0), 0);
  const orig = res.reduce((s, x) => s + (x.base ?? 0), 0);
  const missing = res.some((x) => x.base == null);
  const saved = orig - total;

  $("#led-total").textContent = state.legs.length ? money(total) + (missing ? "*" : "") : "$0.0";
  $("#led-sub").innerHTML = state.legs.length
    ? `原價 ${money(orig)}　·　慳 <b>${money(saved)}</b>　·　${state.legs.length} 程`
    : "加入路線開始計算";
  $("#led-note").textContent = missing ? "* 有一程未有車費資料，總數未計嗰程。" : "成人八達通車費；小童、長者約半價。";

  const html = res.map((row, k) => legCard(row, k)).join("");
  $("#legs").innerHTML = html || `<p class="empty">喺下面輸入第一程路線號碼。</p>`;
}

function legCard(row, k) {
  const { leg, r } = row;
  const vars = variantsOf(r.route);
  const nStops = r.stops.length;
  const boardOpts = r.stops.slice(0, nStops - 1).map((s, i) =>
    `<option value="${i}" ${i === leg.board ? "selected" : ""}>${i + 1}. ${esc(stopName(s))}${fareAt(r, i) != null ? "　$" + fareAt(r, i).toFixed(1) : ""}</option>`).join("");
  const alightOpts = r.stops.map((s, i) => i <= leg.board ? "" :
    `<option value="${i}" ${i === leg.alight ? "selected" : ""}>${i + 1}. ${esc(stopName(s))}</option>`).join("");
  let transfer = "";
  if (row.transfer) transfer = transferStrip(row.transfer, k);
  const discounted = row.paid != null && row.base != null && row.paid < row.base;
  return `${transfer}
  <article class="leg" data-k="${k}">
    <header class="leg-head">
      <span class="leg-no">第 ${k + 1} 程</span>
      ${chip(r)}
      <span class="leg-dest">往 ${esc(r.d)}</span>
      <span class="leg-fare">${discounted ? `<s>${money(row.base)}</s> ` : ""}<b>${money(row.paid)}</b></span>
      <button class="icon-btn" data-act="remove" data-k="${k}" aria-label="刪除第 ${k + 1} 程" title="刪除呢程">✕</button>
    </header>
    <div class="leg-grid">
      <label>路線<input id="route-${k}" class="route-in" data-k="${k}" list="route-list" value="${esc(r.route)}" autocomplete="off" inputmode="text"></label>
      <label class="wide">方向／班次<select id="var-${k}" data-act="variant" data-k="${k}">${vars.map((v) =>
        `<option value="${v}" ${v === leg.rid ? "selected" : ""}>${esc(variantLabel(R[v]))}</option>`).join("")}</select></label>
      <label class="wide">上車站<select id="board-${k}" data-act="board" data-k="${k}">${boardOpts}</select></label>
      <label class="wide">落車站<select id="alight-${k}" data-act="alight" data-k="${k}">${alightOpts}</select></label>
    </div>
    ${row.base == null ? `<p class="leg-warn">未有呢個站嘅車費資料。</p>` : ""}
  </article>`;
}

function transferStrip(tr, k) {
  const prevLeg = state.legs[k - 1];
  const hasRules = tr.rules.length > 0;
  let pill, body = "";
  if (tr.used) {
    const u = tr.used.rule;
    pill = `<span class="pill pill-good">${esc(ruleText(u))}</span>`;
    body = `<dl class="tr-meta">
        <div><dt>轉乘站</dt><dd>${esc(cleanAt(u.at) || "—")}</dd></div>
        <div><dt>時限</dt><dd>${u.lim ? u.lim + " 分鐘" : "—"}</dd></div>
        <div><dt>計劃</dt><dd>${esc(u.sch)}</dd></div>
        ${u.rm ? `<div class="full"><dt>備註</dt><dd>${esc(u.rm)}</dd></div>` : ""}
      </dl>`;
    if (tr.alts.length) {
      body += `<details class="alts"><summary>另外 ${tr.alts.length} 個適用組合</summary><ul>${tr.alts.map((c) =>
        `<li>${esc(ruleText(c.rule))}・${esc(cleanAt(c.rule.at))}・${c.rule.lim} 分鐘</li>`).join("")}</ul></details>`;
    }
  } else if (hasRules) {
    pill = `<span class="pill pill-warn">未符合條件</span>`;
    body = `<p class="tr-warn">${esc(tr.warn)}</p>${tr.suggest ? `<button class="text-btn" data-act="suggest" data-k="${k}">用建議轉乘站</button>` : ""}`;
  } else {
    pill = `<span class="pill pill-none">冇轉乘優惠</span>`;
    body = `<p class="tr-none">現有數據入面，呢兩程之間冇八達通轉乘優惠，次程照付全費。</p>`;
  }
  const aStop = stopName(R[prevLeg.rid].stops[prevLeg.alight]);
  const bStop = stopName(R[state.legs[k].rid].stops[state.legs[k].board]);
  const walk = Math.round(dist(R[prevLeg.rid].stops[prevLeg.alight], R[state.legs[k].rid].stops[state.legs[k].board]));
  return `<section class="transfer ${tr.used ? "ok" : hasRules ? "warn" : "none"}">
    <div class="tr-head"><span class="tr-label">轉車</span>${pill}
      <span class="tr-stops">${esc(aStop)} → ${esc(bStop)}${walk > 800 ? `（兩站相距約 ${(walk / 1000).toFixed(1)} 公里，請改落車／上車站）` : walk > 30 ? `（步行約 ${walk} 米）` : ""}</span></div>
    ${body}
  </section>`;
}

function addLegFromInput(value) {
  const num = value.trim().toUpperCase();
  const vars = variantsOf(num);
  if (!vars.length) {
    $("#add-msg").textContent = `搵唔到路線「${value}」。`;
    return false;
  }
  $("#add-msg").textContent = "";
  let rid = vars[0];
  const k = state.legs.length;
  // 有上一程嘅話，優先揀有轉乘優惠嘅方向
  if (k > 0) {
    const prev = state.legs[k - 1].rid;
    const withRule = vars.find((v) => rulesBetween(prev, v).length);
    if (withRule != null) rid = withRule;
  }
  state.legs.push(newLeg(rid));
  if (k > 0) autoTransfer(k);
  renderCalc();
  return true;
}

function bindCalc() {
  $("#add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = $("#add-route");
    if (addLegFromInput(inp.value)) inp.value = "";
  });
  $("#clear-btn").addEventListener("click", () => { state.legs = []; renderCalc(); });
  const legsEl = $("#legs");
  legsEl.addEventListener("change", (e) => {
    const t = e.target, k = +t.dataset.k;
    if (t.classList.contains("route-in")) {
      const vars = variantsOf(t.value.trim().toUpperCase());
      if (vars.length) { setLegRoute(k, vars[0]); }
      renderCalc();
      return;
    }
    const act = t.dataset.act;
    if (act === "variant") setLegRoute(k, +t.value);
    else if (act === "board") {
      const leg = state.legs[k];
      leg.board = +t.value;
      if (leg.alight <= leg.board) leg.alight = R[leg.rid].stops.length - 1;
    } else if (act === "alight") state.legs[k].alight = +t.value;
    renderCalc();
  });
  legsEl.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const k = +b.dataset.k;
    if (b.dataset.act === "remove") {
      state.legs.splice(k, 1);
      if (k > 0 && k < state.legs.length) autoTransfer(k);
    } else if (b.dataset.act === "suggest") autoTransfer(k);
    renderCalc();
  });
}

// ---------------------------------------------------------------- 轉乘查詢
function buildIncoming() {
  incoming = new Map();
  for (const a in BBI) {
    for (const x of BBI[a]) {
      if (!incoming.has(x[0])) incoming.set(x[0], []);
      incoming.get(x[0]).push([+a, x]);
    }
  }
}

function renderQueryVariants() {
  const num = $("#q-route").value.trim().toUpperCase();
  const vars = variantsOf(num);
  $("#q-var").innerHTML = vars.map((v) => `<option value="${v}">${esc(variantLabel(R[v]))}</option>`).join("");
  renderQuery();
}

function renderQuery() {
  const rid = +$("#q-var").value;
  const dir = $("input[name=q-dir]:checked").value;
  const filt = $("#q-filter").value.trim().toUpperCase();
  const out = $("#q-results");
  if (Number.isNaN(rid) || !R[rid]) {
    out.innerHTML = `<p class="empty">輸入路線號碼，例如 968、970X、A11。</p>`;
    $("#q-info").innerHTML = "";
    return;
  }
  let rows;
  if (dir === "out") {
    rows = (BBI[rid] || []).map((x) => ({ other: x[0], rule: unpack(x) }));
  } else {
    if (!incoming) buildIncoming();
    rows = (incoming.get(rid) || []).map(([a, x]) => ({ other: a, rule: unpack(x) }));
  }
  // 合併重複（同一路線號 + 方向 + 優惠 + 轉乘站）
  const seen = new Map();
  for (const x of rows) {
    const o = R[x.other];
    const key = [o.co, o.route, o.d, x.rule.t, x.rule.amt, cleanAt(x.rule.at)].join("|");
    if (!seen.has(key)) seen.set(key, x);
  }
  rows = [...seen.values()];
  if (filt) rows = rows.filter((x) => R[x.other].route.includes(filt) || R[x.other].d.includes(filt) || cleanAt(x.rule.at).includes(filt));
  const coOrder = { "co-kmb": 0, "co-lwb": 1, "co-joint": 2, "co-ctb": 3, "co-nlb": 4, "co-lrtfeeder": 5, "co-gmb": 6 };
  rows.sort((x, y) => (coOrder[coClass(R[x.other])] ?? 9) - (coOrder[coClass(R[y.other])] ?? 9) ||
    cmpRoute(R[x.other].route, R[y.other].route) || R[x.other].st - R[y.other].st);

  const me = R[rid];
  const info = META.info.filter((s) => Object.entries(s.routes || {}).some(([co, list]) => me.co.includes(co) && list.includes(me.route)));
  $("#q-info").innerHTML = info.map((s) => `<aside class="info-box"><b>${esc(s.name)}</b><p>${esc(s.text)}</p><small>來源：${esc(s.source)}</small></aside>`).join("");

  const nCo = new Set(rows.map((x) => coLabel(R[x.other]))).size;
  out.innerHTML = `<p class="q-count">${dir === "out" ? "由" : "轉入"} ${chip(me)} 往 ${esc(me.d)}：共 <b>${rows.length}</b> 個組合，涉及 ${nCo} 個營辦商類別。撳一行可以直接計車費。</p>
  <div class="table-wrap"><table class="q-table">
    <thead><tr><th>${dir === "out" ? "次程" : "首程"}</th><th>方向</th><th>優惠</th><th>轉乘站</th><th class="num">時限</th><th>計劃</th></tr></thead>
    <tbody>${rows.slice(0, 600).map((x) => {
      const o = R[x.other];
      return `<tr data-a="${dir === "out" ? rid : x.other}" data-b="${dir === "out" ? x.other : rid}" tabindex="0">
        <td>${chip(o)}</td><td>往 ${esc(o.d)}${o.st !== 1 ? "<small>（特別班）</small>" : ""}</td>
        <td><span class="pill ${x.rule.t === T.GMB ? "pill-none" : "pill-good"}">${esc(ruleText(x.rule))}</span></td>
        <td>${esc(cleanAt(x.rule.at) || "—")}</td><td class="num">${x.rule.lim ? x.rule.lim + "′" : "—"}</td>
        <td class="sch">${esc(x.rule.sch)}${x.rule.rm ? `<small>${esc(x.rule.rm)}</small>` : ""}</td></tr>`;
    }).join("")}</tbody></table></div>
  ${rows.length > 600 ? `<p class="q-more">只顯示頭 600 個，可以用篩選收窄。</p>` : ""}`;

  const wr = wikiRows(me.route);
  if (wr.length) {
    out.insertAdjacentHTML("beforeend", `<details class="wiki"><summary>香港巴士大典記載 ${me.route} 嘅組合（${wr.length} 行，參考用，部分可能過時）</summary>
      <div class="table-wrap"><table class="q-table wiki-table"><thead><tr><th>分區</th><th>第一程</th><th>轉乘地點</th><th>第二程</th><th>優惠</th><th>時限</th><th>備註</th></tr></thead>
      <tbody>${wr.map((r) => `<tr><td>${esc(r[0])}・${esc(r[1])}</td><td>${wikiCell(r[2])}</td><td>${wikiCell(r[3])}</td><td>${wikiCell(r[4])}</td><td>${esc(r[5])}</td><td>${esc(r[6])}</td><td>${wikiCell(r[7])}</td></tr>`).join("")}</tbody></table></div>
      <p class="hint">來源：香港巴士大典《八達通轉乘優惠列表》（CC-BY-SA），擷取於 ${esc(WIKI.fetched || "")}。</p></details>`);
  }
}

function bindQuery() {
  $("#q-route").addEventListener("input", renderQueryVariants);
  $("#q-var").addEventListener("change", renderQuery);
  $("#q-filter").addEventListener("input", renderQuery);
  document.querySelectorAll("input[name=q-dir]").forEach((el) => el.addEventListener("change", renderQuery));
  $("#q-results").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-a]");
    if (!tr) return;
    useCombo(+tr.dataset.a, +tr.dataset.b);
  });
  $("#q-results").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-a]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); useCombo(+tr.dataset.a, +tr.dataset.b); }
  });
}
function useCombo(a, b) {
  state.legs = [newLeg(a), newLeg(b)];
  autoTransfer(1);
  renderCalc();
  location.hash = "calc";
}

// ---------------------------------------------------------------- 數據說明
function renderAbout() {
  const s = META.sources || {};
  $("#about-stats").innerHTML = `
    <div class="stat"><b>${R.length.toLocaleString()}</b><span>路線（連方向、特別班）</span></div>
    <div class="stat"><b>${S.length.toLocaleString()}</b><span>車站</span></div>
    <div class="stat"><b>${(s.pairs || 0).toLocaleString()}</b><span>轉乘組合</span></div>
    <div class="stat"><b>${(s.ctb_schemes || 0) ? s.ctb_schemes : "2"}</b><span>城巴計劃已收錄</span></div>`;
  $("#about-updated").textContent = META.updated || "";
  $("#about-notes").innerHTML = META.notes.map((n) => `<li>${esc(n)}</li>`).join("");
  $("#footer-updated").textContent = META.updated || "";
  $("#hdr-updated").textContent = META.updated ? "數據更新：" + META.updated : "";
}

// ---------------------------------------------------------------- 分頁
function route() {
  const v = (location.hash || "#calc").slice(1);
  const view = ["calc", "query", "about"].includes(v) ? v : "calc";
  document.querySelectorAll("[data-view]").forEach((el) => { el.hidden = el.dataset.view !== view; });
  document.querySelectorAll(".tabs a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === "#" + view ? "page" : "false"));
}

// ---------------------------------------------------------------- 開始
async function init() {
  try {
    await loadData();
  } catch (err) {
    $("#loading").innerHTML = `數據載入失敗：${esc(err.message)}。請重新整理頁面。`;
    return;
  }
  document.body.insertAdjacentHTML("beforeend", routeOptions("route-list"));
  $("#loading").hidden = true;
  bindCalc();
  bindQuery();
  renderAbout();
  // 預設例子：元朗 968 → 西隧轉 970X 去香港仔
  const ex1 = variantsOf("968").find((i) => R[i].d.includes("銅鑼灣") && R[i].st === 1);
  const ex2 = variantsOf("970X").find((i) => R[i].d.includes("香港仔") && R[i].st === 1);
  if (ex1 != null && ex2 != null) {
    state.legs = [newLeg(ex1), newLeg(ex2)];
    autoTransfer(1);
  }
  renderCalc();
  $("#q-route").value = "968";
  renderQueryVariants();
  window.addEventListener("hashchange", route);
  route();
}
init();
