# -*- coding: utf-8 -*-
"""
將各來源嘅原始數據整合成網站用嘅精簡 JSON。

輸入（raw/ 資料夾，由 fetch_sources.py 下載）：
  routeFareList.min.json      全港路線、車站、分段車費（hkbus 開源數據）
  kmb_bbi_f1.json / b1.json   九巴/龍運轉乘（官方原始格式）  或
  kmb_bbi_f1.processed.json   （後備：loohpjames 已處理格式）
  ctb/*.json                  城巴每個轉乘計劃（官方 API 原始格式）
  ctb_bbi_loohp.json          （後備：loohpjames 收錄嘅城巴數據）
  kmb_gmb_interchange.json    九巴 ⇄ 專線小巴轉乘（只有路線對，冇金額）

輸出（site/data/）：
  routes.json  路線（含車站次序同分段車費）
  stops.json   車站名同座標
  bbi.json     轉乘優惠：首程路線 → [次程路線, 優惠類型, 金額, 時限, ...]
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "site", "data")

# 優惠類型代碼（網站 app.js 用同一套）
FREE, MINUS, TOTAL, PAY, REBATE, DIFF = 0, 1, 2, 3, 4, 5

KEEP_CO = {"kmb", "ctb", "nlb", "gmb", "lrtfeeder"}
CO_PRIORITY = ["kmb", "ctb", "nlb", "lrtfeeder", "gmb"]
PROVIDER_MAP = {"KMB": "kmb", "LWB": "kmb", "CTB": "ctb", "NWFB": "ctb", "NLB": "nlb"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    """統一地名寫法方便配對方向。"""
    if not s:
        return ""
    s = s.replace("（", "(").replace("）", ")").replace(" ", "").replace("　", "")
    s = s.replace("邨", "村") if False else s
    return s.strip()


def strip_brackets(s):
    return re.sub(r"\(.*?\)", "", s)


# ---------------------------------------------------------------- routes
class RouteIndex:
    def __init__(self, hk):
        self.stop_ids = {}      # hkbus stop id -> our index
        self.stops = []         # [zh, en, lat, lng]
        self.routes = []        # 精簡路線
        self.by_co_route = {}   # (co, route) -> [route idx]
        stop_list = hk["stopList"]

        def stop_idx(sid):
            if sid not in self.stop_ids:
                s = stop_list.get(sid)
                if s is None:
                    return -1
                self.stop_ids[sid] = len(self.stops)
                self.stops.append([s["name"]["zh"], s["name"]["en"],
                                   round(s["location"]["lat"], 5), round(s["location"]["lng"], 5)])
            return self.stop_ids[sid]

        items = sorted(hk["routeList"].values(),
                       key=lambda v: (route_sort_key(v["route"]), str(v["serviceType"])))
        for v in items:
            cos = [c for c in v["co"] if c in KEEP_CO]
            if not cos:
                continue
            main = next(c for c in CO_PRIORITY if c in v["stops"] and c in cos)
            stops = [stop_idx(s) for s in v["stops"][main]]
            if any(s < 0 for s in stops) or len(stops) < 2:
                continue
            fares = []
            for x in (v.get("fares") or []):
                try:
                    fares.append(round(float(x), 1))
                except (TypeError, ValueError):
                    fares.append(None)
            idx = len(self.routes)
            self.routes.append({
                "r": v["route"], "co": cos, "st": int(v["serviceType"]),
                "o": v["orig"]["zh"], "d": v["dest"]["zh"],
                "oe": v["orig"]["en"], "de": v["dest"]["en"],
                "s": stops, "f": fares,
                "gmbId": v.get("gtfsId") if "gmb" in cos else None,
                "bound": v["bound"],
            })
            for c in cos:
                self.by_co_route.setdefault((c, v["route"]), []).append(idx)
        self.fill_missing_fares()
        self.find_twins()

    def find_twins(self):
        """同一條線、起點同總站都喺 400 米內嘅版本（數據重複），當係同一方向，共用轉乘優惠。"""
        self.twins = {}
        for lst in self.by_co_route.values():
            for i in lst:
                ri = self.routes[i]
                for j in lst:
                    if i == j:
                        continue
                    rj = self.routes[j]
                    if haversine(self.stops[ri["s"][0]], self.stops[rj["s"][0]]) < 400 and \
                            haversine(self.stops[ri["s"][-1]], self.stops[rj["s"][-1]]) < 400:
                        self.twins.setdefault(i, set()).add(j)
        print("重複版本組合:", sum(len(v) for v in self.twins.values()) // 2)

    def expand(self, lst):
        out = set(lst)
        for i in lst:
            out |= self.twins.get(i, set())
        return sorted(out)

    def fill_missing_fares(self):
        """部分路線版本冇車費（數據來源重複）→ 向同線同方向、有車費嘅版本按車站位置借。"""
        fixed = 0
        for key, lst in self.by_co_route.items():
            for i in lst:
                r = self.routes[i]
                if r["f"] and any(x is not None for x in r["f"]):
                    continue
                best, best_hits = None, 0
                for j in lst:
                    s = self.routes[j]
                    if j == i or not s["f"] or s["r"] != r["r"]:
                        continue
                    # 同方向：總站相近
                    if haversine(self.stops[r["s"][-1]], self.stops[s["s"][-1]]) > 1500:
                        continue
                    hits = sum(1 for a in r["s"][:-1]
                               if min(haversine(self.stops[a], self.stops[b]) for b in s["s"][:-1]) < 150)
                    if hits > best_hits:
                        best, best_hits = j, hits
                if best is None or best_hits < max(2, (len(r["s"]) - 1) * 0.5):
                    continue
                s = self.routes[best]
                fares = []
                for a in r["s"][:-1]:
                    k = min(range(len(s["s"]) - 1), key=lambda k: haversine(self.stops[a], self.stops[s["s"][k]]))
                    d = haversine(self.stops[a], self.stops[s["s"][k]])
                    fares.append(s["f"][k] if d < 150 and k < len(s["f"]) else None)
                # 中間未配對到嘅站：用前一個站嘅車費（分段收費只會越坐越平）
                for k in range(1, len(fares)):
                    if fares[k] is None and fares[k - 1] is not None:
                        fares[k] = fares[k - 1]
                r["f"] = fares
                r["fare_from"] = best
                fixed += 1
        print("借用車費嘅路線版本:", fixed)

    def resolve(self, co, route, dest, bound=None):
        """搵 (公司, 路線, 目的地) 對應嘅路線變體。回傳 route idx list。"""
        cands = self.by_co_route.get((co, route), [])
        if not cands:
            return []
        nd = norm(dest)
        best, best_score = [], 0
        for i in cands:
            route = self.routes[i]
            names = [norm(route["d"])]
            if "循環線" in route["d"]:
                # 循環線：九巴/城巴用另一端（起點）命名方向
                names = [norm(route["d"]).replace("(循環線)", ""), norm(route["o"])]
            sc = max(self.name_score(nd, rd) for rd in names)
            if sc > best_score:
                best, best_score = [i], sc
            elif sc == best_score and sc > 0:
                best.append(i)
        if best_score == 0:
            circ = [i for i in cands if "循環線" in self.routes[i]["d"]]
            if circ and len(circ) == len(cands):
                # 單向循環線：名唔夾都只得一個方向
                return circ
            best = self.opposite_of_origin(cands, nd) or self.nearest_terminus(cands, dest)
        return best

    def opposite_of_origin(self, cands, nd):
        """地名同某方向嘅『起點』一樣 → 應該係相反方向。"""
        from_here = [i for i in cands if self.name_score(nd, norm(self.routes[i]["o"])) >= 2]
        if not from_here:
            return []
        origin_names = {norm(self.routes[i]["o"]) for i in from_here}
        other = [i for i in cands if i not in from_here
                 and max(self.name_score(norm(self.routes[i]["o"]), o) for o in origin_names) < 2]
        return other

    def place_stops(self, name):
        """搵名入面包含呢個地名嘅車站（用嚟估地名位置）。"""
        if not hasattr(self, "_place_cache"):
            self._place_cache = {}
        if name in self._place_cache:
            return self._place_cache[name]
        n = norm(name)
        parts = [n, strip_brackets(n)] + re.findall(r"\((.*?)\)", n)
        toks = []
        for p in parts:
            p = re.sub(r"(總站|巴士站|站)$", "", p)
            if len(p) >= 2 and p not in toks:
                toks.append(p)
        found = []
        for t in toks:  # 由最完整嘅名開始搵，搵到就停
            found = [i for i, s in enumerate(self.stops) if t in norm(s[0])]
            if found:
                break
        self._place_cache[name] = found[:300]
        return self._place_cache[name]

    def nearest_terminus(self, cands, dest):
        """邊個方向嘅總站最接近呢個地名，就係嗰個方向。"""
        places = self.place_stops(dest)
        if not places:
            return []

        def d_to_place(i):
            last = self.stops[self.routes[i]["s"][-1]]
            return min(haversine(last, self.stops[p]) for p in places)
        dists = {i: d_to_place(i) for i in cands}
        best_d = min(dists.values())
        if best_d > 1500:
            return []
        chosen = [i for i, d in dists.items() if d <= best_d + 500]
        others = [d for i, d in dists.items() if i not in chosen]
        if others and min(others) < 2 * best_d + 300:
            return []  # 兩個方向都差唔多近，唔估
        return chosen

    @staticmethod
    def name_score(nd, rd):
        if not nd or not rd:
            return 0
        if rd == nd:
            return 4
        if strip_brackets(rd) == strip_brackets(nd):
            return 3
        if nd in rd or rd in nd:
            return 2
        if strip_brackets(nd)[:2] == strip_brackets(rd)[:2]:
            return 1
        return 0


def haversine(a, b):
    """a、b = [名, 英文名, lat, lng]，回傳米。"""
    import math
    dy = (a[2] - b[2]) * 111320
    dx = (a[3] - b[3]) * 111320 * math.cos(math.radians(a[2]))
    return math.hypot(dx, dy)


def route_sort_key(r):
    m = re.match(r"([A-Z]*)(\d*)(.*)", r)
    p, n, s = m.groups()
    return (p, int(n) if n else 0, s)


# ---------------------------------------------------------------- KMB
KMB_VALIDITY = {"^": 30, "#": 60, "*": 90, "@": 120, "": 150}


def parse_kmb_discount(raw):
    raw = raw.strip()
    if "免費" in raw:
        return FREE, 0.0
    for pat, t in (("減 \\$([0-9.]+)", MINUS), ("兩程合共 \\$([0-9.]+)", TOTAL),
                   ("付 \\$([0-9.]+)", PAY), ("回贈 \\$([0-9.]+)", REBATE)):
        m = re.match(pat, raw)
        if m:
            return t, float(m.group(1))
    return None, None


def kmb_records():
    """回傳統一格式記錄 list。優先用官方原始檔，冇就用 loohpjames 處理過嘅。"""
    out = []
    for fb in ("f1", "b1"):
        raw_path = os.path.join(RAW, f"kmb_bbi_{fb}.json")
        proc_path = os.path.join(RAW, f"kmb_bbi_{fb}.processed.json")
        if os.path.exists(raw_path):
            data = load(raw_path)
            for route, rd in data.items():
                direction = rd["bus_arr"][0]["dest"]
                for x in rd["Records"]:
                    t, amt = parse_kmb_discount(x["discount_max"])
                    if t is None:
                        continue
                    out.append(dict(a=("kmb", route, direction), b=x["sec_routeno"], bd=x["sec_dest"],
                                    t=t, amt=amt, lim=KMB_VALIDITY.get(x["validity"], 150),
                                    maxc=int(x["success_cnt"] or 1), at=x["xchange"], sch="九巴/龍運轉乘計劃",
                                    rm="", src="kmb"))
        elif os.path.exists(proc_path):
            data = load(proc_path)
            for route, lst in data.items():
                for x in lst:
                    t, amt = parse_kmb_discount(x["discount_raw"])
                    if t is None:
                        continue
                    out.append(dict(a=("kmb", route, x["bbi_direction"]), b=x["bbi_route_number"],
                                    bd=x["destination"], t=t, amt=amt, lim=x["time_limit"] or 150,
                                    maxc=x["max_change"], at=x["recommended_bbi"], sch="九巴/龍運轉乘計劃",
                                    rm="", src="kmb"))
    # 次程公司：九巴網站用「(城巴)」等後綴標示其他公司
    for r in out:
        b = r["b"]
        m = re.match(r"^(.*?)\((.*?)\)$", b)
        if m:
            name, co = m.group(1), m.group(2)
            r["b"] = ("ctb" if co == "城巴" else "nlb" if co in ("嶼巴", "新大嶼山") else "other:" + co, name, r["bd"])
        else:
            r["b"] = ("kmb", b, r["bd"])
    return out


# ---------------------------------------------------------------- CTB
def ctb_records():
    files = sorted(p for p in glob.glob(os.path.join(RAW, "ctb", "*.json"))
                   if not os.path.basename(p).startswith("_"))
    rows = []
    if files:
        for p in files:
            d = load(p)
            if isinstance(d, list):
                rows.extend(d)
    else:
        p = os.path.join(RAW, "ctb_bbi_loohp.json")
        if os.path.exists(p):
            rows = load(p)
    out = []
    for x in rows:
        code = x.get("discount", "").strip()
        amt_adult = (x.get("discountAmount") or {}).get("adult")
        total_adult = (x.get("totalFare") or {}).get("adult")
        if code == "L2":
            t, amt = FREE, 0.0
        elif code in ("FR", "FF"):
            if amt_adult is None:
                continue
            t, amt = MINUS, float(amt_adult)
        elif code == "TF":
            if total_adult is None:
                continue
            t, amt = TOTAL, float(total_adult)
        elif code == "L1":
            t, amt = DIFF, 0.0
        else:
            continue
        a_co = PROVIDER_MAP.get(x["firstProvider"].strip(), "other:" + x["firstProvider"].strip())
        b_co = PROVIDER_MAP.get(x["secondProvider"].strip(), "other:" + x["secondProvider"].strip())
        out.append(dict(a=(a_co, x["firstRoute"].strip(), x["firstDirection"]),
                        b=(b_co, x["secondRoute"].strip(), x["secondDirection"]),
                        t=t, amt=amt, lim=int(x.get("timeLimit") or 150), maxc=1,
                        at=x.get("stopName") or "", sch=x.get("packageDesc") or "城巴轉乘計劃",
                        rm=(x.get("remark") or "").strip(), src="ctb"))
    return out


# ---------------------------------------------------------------- GMB
def gmb_pairs(idx):
    """九巴 ⇄ 小巴：只知道有優惠，金額要睇小巴營辦商公佈。"""
    p = os.path.join(RAW, "kmb_gmb_interchange.json")
    if not os.path.exists(p):
        return []
    d = load(p)
    gmb_by_id = {}
    for i, r in enumerate(idx.routes):
        if r["gmbId"]:
            gmb_by_id.setdefault(str(r["gmbId"]), []).append(i)
    pairs = []
    for key, lst in d.get("gmb", {}).items():
        gid, bound = key.rsplit("_", 1)
        g_routes = [i for i in gmb_by_id.get(gid, []) if idx.routes[i]["bound"].get("gmb") == bound]
        for k in lst:
            for kr in idx.by_co_route.get(("kmb", k["route"]), []):
                if idx.routes[kr]["bound"].get("kmb") != k["bound"]:
                    continue
                for g in g_routes:
                    pairs.append((g, kr))
                    pairs.append((kr, g))
    return pairs


# ---------------------------------------------------------------- 人手規則
TYPE_CODE = {"free": FREE, "minus": MINUS, "total": TOTAL, "pay": PAY, "rebate": REBATE, "diff": DIFF}


def is_hki(stop):
    """粗略判斷車站喺咪港島（唔包離島）。"""
    lat, lng = stop[2], stop[3]
    return 22.19 < lat < 22.2925 and 114.12 < lng < 114.26


def manual_records(idx):
    p = os.path.join(ROOT, "crawler", "manual_rules.json")
    if not os.path.exists(p):
        return [], [], []
    m = load(p)
    out = []
    # 車站通用規則：途經同一個車站（同一方向 = 同一個站位）嘅路線之間互轉
    for rule in m.get("station_rules", []):
        names = set(rule["stop_names"])
        stop_ids = {i for i, s in enumerate(idx.stops) if s[0] in names}
        inc = re.compile(rule["include_route_regex"]) if rule.get("include_route_regex") else None
        exc = re.compile(rule["exclude_route_regex"]) if rule.get("exclude_route_regex") else None
        by_stop = {}
        for ri, r in enumerate(idx.routes):
            if not set(r["co"]) & set(rule["co"]):
                continue
            if inc and not inc.search(r["r"]):
                continue
            if exc and exc.search(r["r"]):
                continue
            for s in r["s"][:-1]:
                if s in stop_ids:
                    by_stop.setdefault(s, []).append(ri)
        for s, lst in by_stop.items():
            for a in lst:
                for b in lst:
                    ra, rb = idx.routes[a], idx.routes[b]
                    if ra["r"] == rb["r"]:
                        continue
                    lim = rule["limit"]
                    for pat, v in (rule.get("limit_if_route_regex") or {}).items():
                        if re.search(pat, ra["r"]) or re.search(pat, rb["r"]):
                            lim = v
                    out.append(dict(A=[a], B=[b], t=TYPE_CODE[rule["type"]], amt=float(rule.get("amount", 0)),
                                    lim=lim, maxc=1, at=idx.stops[s][0], sch=rule["name"],
                                    rm=rule.get("remark", ""), src="manual"))
    # 路線清單規則
    for rule in m.get("list_rules", []):
        def pick(side):
            res = []
            for rt in side["routes"]:
                for ri in idx.by_co_route.get((side["co"], rt), []):
                    r = idx.routes[ri]
                    first, last = idx.stops[r["s"][0]], idx.stops[r["s"][-1]]
                    if side.get("region") == "HKI" and not is_hki(first):
                        continue
                    if side.get("to_region") == "HKI" and not is_hki(last):
                        continue
                    if side.get("to_region") == "KLN_NT" and is_hki(last):
                        continue
                    res.append(ri)
            return res
        A, B = pick(rule["from"]), pick(rule["to"])
        if A and B:
            out.append(dict(A=A, B=B, t=TYPE_CODE[rule["type"]], amt=float(rule.get("amount", 0)),
                            lim=rule["limit"], maxc=1, at="任何能接駁第二程路線的車站", sch=rule["name"],
                            rm=rule.get("remark", ""), src="manual"))
    return out, m.get("info_schemes", []), m.get("general_notes", [])


# ---------------------------------------------------------------- main
def main():
    hk = load(os.path.join(RAW, "routeFareList.min.json"))
    idx = RouteIndex(hk)
    print(f"routes {len(idx.routes)}  stops {len(idx.stops)}")

    strings, str_idx = [], {}

    def S(s):
        if s not in str_idx:
            str_idx[s] = len(strings)
            strings.append(s)
        return str_idx[s]

    bbi = {}
    seen = set()
    stats = {"kmb": [0, 0], "ctb": [0, 0], "manual": [0, 0]}
    unresolved = {}
    diag = {}
    manual, info_schemes, notes = manual_records(idx)
    for recs in (kmb_records(), ctb_records(), manual):
        for r in recs:
            src = r["src"]
            stats[src][0] += 1
            if "A" in r:
                A, B = r["A"], r["B"]
            else:
                if r["a"][0].startswith("other") or r["b"][0].startswith("other"):
                    continue
                A = idx.resolve(*r["a"])
                B = idx.resolve(*r["b"])
            if not A or not B:
                key = r["a"][:2] if not A else r["b"][:2]
                unresolved[key] = unresolved.get(key, 0) + 1
                side = r["a"] if not A else r["b"]
                dkey = (src,) + tuple(side)
                diag[dkey] = diag.get(dkey, 0) + 1
                continue
            stats[src][1] += 1
            if src != "manual":  # 車站通用規則本身已經逐個版本計
                A, B = idx.expand(A), idx.expand(B)
            for a in A:
                for b in B:
                    if a == b:
                        continue
                    k = (a, b, r["t"], r["amt"], r["at"])
                    if k in seen:
                        continue
                    seen.add(k)
                    amt = r["amt"]
                    amt = int(amt) if amt == int(amt) else amt
                    bbi.setdefault(a, []).append([b, r["t"], amt, r["lim"], r["maxc"],
                                                  S(r["at"]), S(r["sch"]), S(r["rm"])])
    gp = gmb_pairs(idx)
    for a, b in gp:
        k = (a, b, "gmb")
        if k in seen:
            continue
        seen.add(k)
        bbi.setdefault(a, []).append([b, -1, 0, 0, 1, S(""), S("九巴⇄專線小巴轉乘（優惠以小巴公佈為準）"), S("")])

    for src, (n, ok) in stats.items():
        print(f"{src}: {ok}/{n} records resolved")
    print("gmb pairs", len(gp))
    top = sorted(unresolved.items(), key=lambda x: -x[1])[:25]
    print("unresolved (top):", top)
    print("DIAG 未對到（來源, 公司, 路線, 數據寫嘅目的地 → 路線數據有嘅目的地）:")
    for (src, co, rt, dest), n in sorted(diag.items(), key=lambda x: -x[1])[:60]:
        have = sorted({f'{idx.routes[i]["o"]}→{idx.routes[i]["d"]}' for i in idx.by_co_route.get((co, rt), [])})
        print(f"DIAG {n:4d} {src} {co} {rt} 『{dest}』 have={have[:4]}")

    os.makedirs(OUT, exist_ok=True)
    hkt = timezone(timedelta(hours=8))
    updated = datetime.now(hkt).strftime("%Y-%m-%d %H:%M")
    routes_out = [[r["r"], "+".join(r["co"]), r["st"], r["o"], r["d"], r["oe"], r["de"], r["s"], r["f"]]
                  for r in idx.routes]
    dump(os.path.join(OUT, "routes.json"), {"updated": updated, "routes": routes_out})
    dump(os.path.join(OUT, "stops.json"), idx.stops)
    ctb_files = len([p for p in glob.glob(os.path.join(RAW, "ctb", "*.json"))
                     if not os.path.basename(p).startswith("_")])
    dump(os.path.join(OUT, "bbi.json"), {"updated": updated, "strings": strings,
                                         "bbi": {str(k): v for k, v in bbi.items()},
                                         "info": info_schemes, "notes": notes,
                                         "sources": {"kmb": stats["kmb"][1], "ctb": stats["ctb"][1],
                                                     "ctb_schemes": ctb_files, "manual": stats["manual"][1],
                                                     "gmb": len(gp), "pairs": len(seen)}})
    # 香港巴士大典：作參考資料（唔直接計入優惠，因為部分內容未更新）
    wiki_files = sorted(glob.glob(os.path.join(RAW, "wiki", "*.wikitext")))
    if wiki_files:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wiki_parse
        regions = {}
        for p in wiki_files:
            with open(p, encoding="utf-8") as f:
                regions[os.path.basename(p).split(".")[0]] = wiki_parse.to_output(wiki_parse.parse(f.read()))
        fetched = datetime.fromtimestamp(max(os.path.getmtime(p) for p in wiki_files), hkt).strftime("%Y-%m-%d")
        dump(os.path.join(OUT, "wiki.json"), {"fetched": fetched, "regions": regions})
        print("wiki rows:", {k: len(v) for k, v in regions.items()})
    for f in ("routes.json", "stops.json", "bbi.json", "wiki.json"):
        p = os.path.join(OUT, f)
        if os.path.exists(p):
            print(f, round(os.path.getsize(p) / 1e6, 2), "MB")


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
