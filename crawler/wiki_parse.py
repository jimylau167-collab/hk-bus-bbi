# -*- coding: utf-8 -*-
"""
解析香港巴士大典《八達通轉乘優惠列表》分頁嘅 wikitext 表格（處理 rowspan）。
輸出每行：[分區, 第一程, 轉乘地點, 第二程, 優惠車資, 時限, 備註]
路線會寫成 [CTB:970X]、[CHT:608]（CHT = 聯營）、[NWFB:..] 等標記，方便前端搜尋。
"""
import re

ROUTE_TPL = r"CTB|NWFB|KMB|LWB|NLB|MTRB|MTR|GMB|LRT|TRAM|PB|DB|CHT|HKGMB|KLNGMB|NTGMB"


def clean(s):
    s = re.sub(r"<ref[^>]*>[\s\S]*?</ref>", "", s)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"\[https?:[^\]\s]+(?:\s([^\]]*))?\]", lambda m: m.group(1) or "", s)
    while True:
        prev = s
        s = re.sub(r"\{\{(" + ROUTE_TPL + r")\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"[\1:\2]", s)
        s = re.sub(r"\{\{bs\|([^{}|]*)\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1(\2)", s)
        s = re.sub(r"\{\{FC\|[^{}|]*\|([^{}]*)\}\}", r"\1", s)
        s = re.sub(r"\{\{[a-zA-Z]+\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1", s)
        s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
        if s == prev:
            break
    s = re.sub(r"<br\s*/?>", " / ", s)
    s = re.sub(r"</?[a-z]+[^>]*>", "", s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def parse(wt):
    rows = []
    section = ""
    in_table = False
    grid, pending, cur, col, row_no = [], [], None, 0, -1

    def end_row():
        if cur is None:
            return
        for i in range(col, len(pending)):
            p = pending[i]
            if p and p["left"] > 0 and p["row"] < row_no:
                while len(cur) <= i:
                    cur.append(None)
                cur[i] = p["val"]
                p["left"] -= 1

    def put(i, v):
        while len(cur) <= i:
            cur.append(None)
        cur[i] = v

    for raw in wt.split("\n"):
        line = raw.strip()
        h = re.match(r"^={2,4}\s*(.+?)\s*={2,4}$", line)
        if h:
            section = clean(h.group(1))
            continue
        if line.startswith("{|"):
            in_table, grid, pending, cur, col, row_no = True, [], [], None, 0, -1
            continue
        if not in_table:
            continue
        if line.startswith("|}"):
            end_row()
            in_table = False
            for r in grid:
                if sum(1 for x in r if x is not None) >= 5:
                    rows.append([section] + [x or "" for x in r])
            continue
        if line.startswith("!"):
            continue
        if line.startswith("|-"):
            end_row()
            row_no += 1
            cur = []
            grid.append(cur)
            col = 0
            continue
        if line.startswith("|"):
            if cur is None:
                row_no += 1
                cur = []
                grid.append(cur)
                col = 0
            body, span = line[1:], 1
            m = re.match(r'^[^|]*?rowspan\s*=\s*"?(\d+)"?[^|]*\|(.*)$', body)
            if m:
                span, body = int(m.group(1)), m.group(2)
            else:
                m2 = re.match(r"^\s*(?:style|width|colspan|align)\s*=[^|]*\|(.*)$", body)
                if m2:
                    body = m2.group(1)
            guard = 0
            while guard < 20 and col < len(pending) and pending[col] and pending[col]["left"] > 0 \
                    and pending[col]["row"] < row_no:
                put(col, pending[col]["val"])
                pending[col]["left"] -= 1
                col += 1
                guard += 1
            v = clean(body)
            put(col, v)
            while len(pending) <= col:
                pending.append(None)
            pending[col] = {"val": v, "left": span - 1, "row": row_no} if span > 1 else None
            col += 1
            continue
        if cur is not None and col > 0 and line:
            cur[col - 1] = ((cur[col - 1] or "") + " " + clean(line)).strip()
    return rows


def to_output(rows):
    """[分區, 主要對象, 第一程, 轉乘地點, 第二程, 優惠, 時限, 備註] → 去走「主要對象」。"""
    out = []
    for r in rows:
        r = (r + [""] * 8)[:8]
        out.append([r[0], r[2], r[3], r[4], r[5], r[6], r[7]])
    return out


if __name__ == "__main__":
    import sys
    wt = open(sys.argv[1], encoding="utf-8").read()
    for r in to_output(parse(wt))[:20]:
        print(" | ".join(r))
