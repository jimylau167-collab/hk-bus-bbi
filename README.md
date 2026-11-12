# 全港巴士轉乘車費計算機

計算香港巴士轉乘車費：九巴、龍運、城巴、過海隧道線、跨公司轉乘，同埋部分小巴轉乘。
參考咗 [loohpjames 九巴轉乘車費計算機](https://loohpjames.com/hkkmbcal/)，擴展到全港所有公司。

## 功能

- **車費計算**：輸入幾程路線，揀方向同上落車站，自動揀轉乘站，計每程車費、轉乘優惠同總車費
- **轉乘查詢**：輸入一條線，列出佢可以「轉出」或者「轉入」嘅所有優惠組合
- **數據說明**：收錄範圍、規則、來源

## 資料夾

```
crawler/
  fetch_sources.py   下載原始數據到 raw/
  build_data.py      整合成網站用嘅 site/data/*.json
  wiki_parse.py      解析香港巴士大典表格
  manual_rules.json  人手維護規則（車站通用優惠、九巴⇄進智小巴、電車說明）
site/
  index.html, app.js 網站（純 HTML/JS，冇框架）
  data/              自動產生，唔使放入 git
.github/workflows/update-data.yml   每日自動更新同發佈
```

## 放上網（GitHub Pages，免費）

1. 喺 GitHub 開一個新 repo，將成個資料夾 push 上去（main branch）
2. repo → **Settings → Pages → Build and deployment → Source** 揀 **GitHub Actions**
3. repo → **Actions** → 「每日更新轉乘數據」→ **Run workflow**
4. 跑完（城巴 90 幾個計劃逐個攞，大約 10 分鐘）網址會喺 Settings → Pages 顯示

之後每日香港時間 05:17 自動更新。

## 喺自己部機跑（Windows + Anaconda）

```bat
cd 你放呢個資料夾嘅位置
pip install requests
python crawler\fetch_sources.py
python crawler\build_data.py
cd site
python -m http.server 8000
```

然後瀏覽器開 http://localhost:8000

只更新城巴：`python crawler\fetch_sources.py --only ctb`

## 數據來源

| 數據 | 來源 | 備註 |
|---|---|---|
| 路線、車站、分段車費 | [HK Bus Crawling@2021](https://github.com/hkbus/hk-bus-crawling)（DATA.GOV.HK） | |
| 九巴/龍運轉乘（含轉城巴） | 九巴網站 `BBI_routeF1/B1` | 失敗時用 [LOOHP/HK-KMB-Calculator](https://github.com/LOOHP/HK-KMB-Calculator) data branch |
| 城巴轉乘（90 幾個計劃） | 城巴車費優惠 API | 逐個計劃攞，每個之間等 4 秒；失敗保留上次版本 |
| 九巴⇄小巴 | LOOHP 整理 | 只有配對，冇金額 |
| 車站通用規則、進智小巴、電車 | [香港巴士大典](https://hkbus.fandom.com/wiki/%E5%85%AB%E9%81%94%E9%80%9A%E8%BD%89%E4%B9%98%E5%84%AA%E6%83%A0%E5%88%97%E8%A1%A8)（CC-BY-SA） | 寫入 `manual_rules.json` |
| 香港巴士大典全表 | 同上 | 只作「參考」顯示，因為頁面註明部分資料未更新 |

### 城巴 API 被拒點算？

城巴 API 對程式請求有防護。爬蟲用誠實嘅 User-Agent、慢速逐個攞，如果連續被拒會停止、保留上次數據，唔會硬闖。如果長期攞唔到，可以考慮去信城巴索取數據，或者向 DATA.GOV.HK 要求開放轉乘數據。

### 香港巴士大典被 Cloudflare 擋點算？

手動下載：用瀏覽器開以下網址，將成頁內容另存做 `raw/wiki/港島.json`（九龍、新界同樣），
再用 `python -c "import json;open('raw/wiki/港島.wikitext','w',encoding='utf-8').write(json.load(open('raw/wiki/港島.json',encoding='utf-8'))['parse']['wikitext'])"` 轉做 wikitext。

```
https://hkbus.fandom.com/api.php?action=parse&prop=wikitext&formatversion=2&format=json&page=八達通轉乘優惠列表/港島
```

## 計算規則同限制

- 車費以成人八達通、上車站分段收費計；雙向分段、假日收費、半價未計
- 轉乘站：九巴/龍運獨營之間任何可接駁站都得；涉及城巴或聯營線，要喺建議轉乘站（或同收費車站）轉
- 連續轉乘：按每個組合「可連續轉乘次數」檢查
- 時限只顯示，唔檢查
- 未收錄：新大嶼山巴士轉乘、九巴⇄小巴金額

本網站非任何巴士公司官方網站，車費及優惠以營辦商公佈為準。
