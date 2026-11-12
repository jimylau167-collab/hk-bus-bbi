# -*- coding: utf-8 -*-
"""
下載所有原始數據到 raw/ 資料夾。之後跑 build_data.py 整合。

用法（Anaconda Prompt 或 GitHub Actions）：
    pip install requests
    python crawler/fetch_sources.py            # 全部
    python crawler/fetch_sources.py --only ctb # 只更新城巴

設計原則：
  * 每個來源獨立，一個失敗唔會影響其他。
  * 城巴計劃逐個慢慢攞（每個之間等幾秒），失敗就保留上次成功嘅檔案。
  * 用誠實嘅 User-Agent，唔扮瀏覽器；如果營辦商唔俾攞，就記錄低，唔會硬闖。
"""
import argparse
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
UA = os.environ.get("BBI_USER_AGENT",
                    "HK-BBI-Calculator/1.0 (open-source fare calculator; +https://github.com/)")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})

LOOHP_DATA = "https://raw.githubusercontent.com/LOOHP/HK-KMB-Calculator/data/data/"
CTB_API = "https://www.citybus.com.hk/concessionApi/public/bbi/api/v1/scheme/tc"
WIKI_API = "https://hkbus.fandom.com/api.php"
WIKI_PAGES = ["八達通轉乘優惠列表/港島", "八達通轉乘優惠列表/九龍", "八達通轉乘優惠列表/新界"]


def log(*a):
    print(*a, flush=True)


def get(url, **kw):
    r = S.get(url, timeout=60, **kw)
    r.raise_for_status()
    return r


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def fetch_hkbus():
    for url in ("https://data.hkbus.app/routeFareList.min.json",
                "https://hkbus.github.io/hk-bus-crawling/routeFareList.min.json"):
        try:
            d = get(url).json()
            assert d["routeList"] and d["stopList"]
            save_json(os.path.join(RAW, "routeFareList.min.json"), d)
            log("hkbus: OK", url, len(d["routeList"]), "routes")
            return True
        except Exception as e:
            log("hkbus: FAIL", url, e)
    return False


def fetch_kmb():
    ok = True
    for fb in ("f1", "b1"):
        url = f"https://www.kmb.hk/storage/BBI_route{fb.upper()}.js"
        try:
            d = get(url).json()
            assert isinstance(d, dict) and d
            save_json(os.path.join(RAW, f"kmb_bbi_{fb}.json"), d)
            log("kmb:", fb, "OK", len(d), "routes")
            continue
        except Exception as e:
            log("kmb:", fb, "官方 FAIL", e, "→ 改用 loohpjames 整理版")
        try:
            d = get(LOOHP_DATA + f"bbi_{fb}.json").json()
            save_json(os.path.join(RAW, f"kmb_bbi_{fb}.processed.json"), d)
            # 官方檔失敗就刪走舊官方檔，避免用到過期數據
            p = os.path.join(RAW, f"kmb_bbi_{fb}.json")
            if os.path.exists(p):
                os.remove(p)
            log("kmb:", fb, "fallback OK")
        except Exception as e:
            log("kmb:", fb, "fallback FAIL", e)
            ok = False
    try:
        d = get(LOOHP_DATA + "kmb_gmb_interchange.json").json()
        save_json(os.path.join(RAW, "kmb_gmb_interchange.json"), d)
        log("kmb-gmb: OK")
    except Exception as e:
        log("kmb-gmb: FAIL", e)
    return ok


KEEP_CTB = ["packageDesc", "firstProvider", "firstRoute", "firstBound", "firstDirection",
            "secondProvider", "secondRoute", "secondBound", "secondDirection", "stopName",
            "discount", "discountAmount", "totalFare", "timeLimit", "remark"]


def fetch_ctb(delay=4.0):
    folder = os.path.join(RAW, "ctb")
    os.makedirs(folder, exist_ok=True)
    list_path = os.path.join(folder, "_schemes.json")
    try:
        schemes = get(CTB_API).json()
        assert isinstance(schemes, list) and schemes
        save_json(list_path, schemes)
        log("ctb: 計劃清單 OK", len(schemes))
    except Exception as e:
        log("ctb: 計劃清單 FAIL", e)
        if not os.path.exists(list_path):
            return False
        schemes = json.load(open(list_path, encoding="utf-8"))
        log("ctb: 用返上次清單", len(schemes))
    ids = sorted({str(s["packageId"]) for s in schemes}, key=int)
    ok = fail = 0
    for n, pid in enumerate(ids):
        path = os.path.join(folder, f"{pid}.json")
        try:
            r = get(f"{CTB_API}/{pid}")
            d = r.json()
            assert isinstance(d, list)
            slim = [{k: x.get(k) for k in KEEP_CTB} for x in d]
            for x in slim:
                for k in ("firstProvider", "firstRoute", "secondProvider", "secondRoute"):
                    if isinstance(x.get(k), str):
                        x[k] = x[k].strip()
            save_json(path, slim)
            ok += 1
            log(f"ctb: {pid} OK ({len(slim)})")
        except Exception as e:
            fail += 1
            status = getattr(getattr(e, "response", None), "status_code", "")
            log(f"ctb: {pid} FAIL {status} {e.__class__.__name__}" +
                ("（保留上次檔案）" if os.path.exists(path) else ""))
            if status in (403, 429) and fail >= 3 and ok == 0:
                log("ctb: 連續被拒，今次停止，聽日再試")
                break
        time.sleep(delay)
    # 清走已取消嘅計劃
    for f in os.listdir(folder):
        m = re.match(r"^(\d+)\.json$", f)
        if m and m.group(1) not in ids:
            os.remove(os.path.join(folder, f))
    log(f"ctb: 完成 {ok} 成功 / {fail} 失敗 / {len(ids)} 個計劃")
    return ok > 0


def fetch_wiki():
    """香港巴士大典：只作補充同對照，失敗唔緊要。"""
    folder = os.path.join(RAW, "wiki")
    os.makedirs(folder, exist_ok=True)
    got = 0
    for page in WIKI_PAGES:
        try:
            r = get(WIKI_API, params={"action": "parse", "prop": "wikitext", "formatversion": "2",
                                      "format": "json", "page": page})
            wt = r.json()["parse"]["wikitext"]
            region = page.split("/")[-1]
            with open(os.path.join(folder, f"{region}.wikitext"), "w", encoding="utf-8") as f:
                f.write(wt)
            got += 1
            log("wiki:", page, "OK", len(wt))
        except Exception as e:
            log("wiki:", page, "FAIL", e.__class__.__name__, "（可能被 Cloudflare 擋，可以手動下載，見 README）")
        time.sleep(2)
    return got > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["hkbus", "kmb", "ctb", "wiki"])
    ap.add_argument("--ctb-delay", type=float, default=4.0)
    ap.add_argument("--skip", default=os.environ.get("BBI_SKIP", ""),
                    help="逗號分隔，跳過嘅來源（用返快取），例如 ctb,wiki")
    a = ap.parse_args()
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    jobs = {"hkbus": fetch_hkbus, "kmb": fetch_kmb, "ctb": lambda: fetch_ctb(a.ctb_delay), "wiki": fetch_wiki}
    results = {}
    for name, fn in jobs.items():
        if (a.only and a.only != name) or name in skip:
            continue
        try:
            results[name] = fn()
        except Exception as e:
            log(name, "ERROR", e)
            results[name] = False
    log("結果:", results)
    # hkbus 係必需，冇就唔好繼續
    if results.get("hkbus") is False and not os.path.exists(os.path.join(RAW, "routeFareList.min.json")):
        sys.exit(1)


if __name__ == "__main__":
    main()
