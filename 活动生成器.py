#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
志远行共学地图 · 活动批量生成器  v2
================================================
把「活动文本」解析成数据，套进地图网页模板，输出一份完整的新网页。

用法（在同一个文件夹里执行）：
    python 活动生成器.py                      # 读 活动更新文本.txt
    python 活动生成器.py 活动.txt              # 指定输入文件
    python 活动生成器.py 活动.txt -o 新.html    # 指定输出
    python 活动生成器.py --demo                # 用内置示例
    python 活动生成器.py --geocode             # 没收录的地名在线编码（建议配合 坐标补全.py）
    python 活动生成器.py --open                # 生成后自动打开

输入格式（每场活动一段，字段用「键：值」）：
    活动二：北京亲子游 棉花采摘周末营
    标题： 北京亲子游 棉花采摘 周末营自然科普/弹棉花/制作小绵羊肖恩灯笼/制作棉花糖
    时间： 11月1日（周日）10:00 ~ 16:00
    地点： 北京大兴安定镇后辛房村后马路
    费用： ¥50 - 198元
    报名： https://xxx            （可选，可多条，空格或逗号分开）
    类型： 公益 / 探索 / 工坊       （可选，不写按关键词猜）
    主办： 某某机构                （可选）
    备注： 想写什么写什么           （可选，显示在点位弹窗里）

支持：多日活动（11月21日 - 11月22日）、复杂票价（单人/双人/多档）会原样保留。
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 地名坐标表
# 关键词 -> (纬度, 经度)。命中即用；想加地点直接补一行，
# 或在本目录建 地名坐标.txt，每行：地名|纬度|经度（坐标补全.py 会自动维护）
PLACES = {
    "人济山庄": (39.9427, 116.3103), "紫竹桥": (39.9430, 116.3070),
    "龙德紫金": (40.0536, 116.4140), "龙德广场": (40.0536, 116.4140),
    "天通苑": (40.0536, 116.4140),
    "亦创": (39.7929, 116.5203), "亦庄": (39.7929, 116.5203),
    "安定镇": (39.6336, 116.4331), "后辛房": (39.6352, 116.4368),
    "798": (39.9843, 116.4956), "79罐": (39.9843, 116.4956), "酒仙桥": (39.9750, 116.4950),
    "中关村": (39.9830, 116.3160), "五道口": (39.9920, 116.3380),
    "国家图书馆": (39.9450, 116.3250), "国图": (39.9450, 116.3250),
    "首都体育馆": (39.9360, 116.3300), "奥森": (40.0000, 116.3900),
    "奥林匹克森林公园": (40.0000, 116.3900), "三里屯": (39.9360, 116.4550),
    "望京": (39.9960, 116.4700), "首钢园": (39.9130, 116.1900),
    "环球影城": (39.8560, 116.6800), "雁栖湖": (40.4000, 116.6600),
    "古北水镇": (40.6500, 117.2700), "大兴机场": (39.5100, 116.4100),
    "天安门": (39.9087, 116.3975), "故宫": (39.9163, 116.3972),
    "什刹海": (39.9400, 116.3830), "南锣鼓巷": (39.9400, 116.4030),
    "隆福寺": (39.9250, 116.4070), "北京坊": (39.8990, 116.3950),
    "国子监": (39.9450, 116.4090), "朝阳公园": (39.9430, 116.4780),
    "温榆河": (40.0500, 116.5500),
    # 昌平兴寿镇西新城村（昌金路旁），据园区官网 www.xinchengyuangp.com
    "鑫城缘": (40.2080, 116.3600), "西新城": (40.2080, 116.3600),
    "兴寿": (40.2150, 116.3700),
    "亮马桥": (39.9490, 116.4660), "罗马桥": (39.9490, 116.4660),   # 「罗马桥」多为「亮马桥」笔误
    "平安国际金融中心": (39.9490, 116.4660), "燕莎": (39.9495, 116.4620),
    "国贸": (39.9088, 116.4590), "金融街": (39.9150, 116.3610),
}

DISTRICTS = {
    "东城": (39.9280, 116.4160), "西城": (39.9120, 116.3660),
    "朝阳": (39.9210, 116.4430), "海淀": (39.9590, 116.2980),
    "丰台": (39.8580, 116.2860), "石景山": (39.9060, 116.2230),
    "门头沟": (39.9400, 116.1020), "房山": (39.7490, 116.1430),
    "通州": (39.9020, 116.6580), "顺义": (40.1300, 116.6540),
    "昌平": (40.2200, 116.2310), "大兴": (39.7280, 116.3410),
    "怀柔": (40.3160, 116.6370), "平谷": (40.1440, 117.1210),
    "密云": (40.3770, 116.8430), "延庆": (40.4570, 115.9750),
}

TYPES = {"公益": "charity", "慈善": "charity", "志愿": "charity", "义卖": "charity",
         "探索": "explore", "展会": "explore", "峰会": "explore",
         "工坊": "workshop", "实践": "workshop", "体验": "workshop", "亲子": "workshop"}

KEYWORDS_CHARITY = ("公益", "志愿", "救助", "捐赠", "义卖", "助残", "助学", "献血", "救灾", "义演")
KEYWORDS_EXPLORE = ("峰会", "论坛", "展会", "展览", "市集", "沙龙", "分享会", "发布会",
                    "开放日", "大会", "音乐节", "艺术节", "戏剧", "演出", "讲座", "创新节", "节")
TAG_NAME = {"charity": "公益", "explore": "探索", "workshop": "工坊"}

DEMO_TEXT = """活动一：世界记忆大师团 体验课
标题： 世界记忆大师团 高效学习法 / 快速记忆 / 快速阅读 / 魔方思维 体验课
时间： 11月14日（周六）13:30 ~ 15:30
地点： 北京昌平区天通苑 龙德紫金商场二层
费用： 免费
报名： #小程序://互动吧/Y33bi3lZpzayIwf

活动二：北京亲子游 棉花采摘周末营
标题： 北京亲子游 棉花采摘 周末营自然科普/弹棉花/制作小绵羊肖恩灯笼/制作棉花糖
时间： 11月1日（周日）10:00 ~ 16:00
地点： 北京大兴安定镇后辛房村后马路
费用： ¥50 - 198元
"""

# ---------------------------------------------------------------- 解析
FIELD = re.compile(
    r"^\s*(标题|名称|活动名称|主题|活动|时间|日期|地点|地址|费用|收费|价格|票价|报名|链接|报名链接|"
    r"类型|分类|主办|主办方|备注|日程|简介|说明|适合人群|人群)\s*[：:]\s*(.*)$")
ACT_HEAD = re.compile(r"^\s*活动\s*[一二三四五六七八九十百\d]*\s*[：:]?\s*(.*)$")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def split_blocks(text: str):
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    blocks, cur = [], []
    for ln in lines:
        if re.match(r"^\s*[-=*]{3,}\s*$", ln):
            continue
        if ACT_HEAD.match(ln) and cur and any(FIELD.match(x) for x in cur):
            blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append(cur)

    out = []
    for b in blocks:
        fields, head = {}, ""
        for ln in b:
            m = FIELD.match(ln)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if k in fields and v:
                    fields[k] = fields[k] + " " + v          # 同名字段拼接
                else:
                    fields.setdefault(k, v)
                continue
            h = ACT_HEAD.match(ln)
            if h and not head:
                head = h.group(1).strip()
        if fields:
            out.append({"head": head, "fields": fields})
    return out


def clean(s: str) -> str:
    """去掉零宽字符、全角空格、多余空白。"""
    if not s:
        return ""
    s = re.sub(r"[\u200b-\u200f\ufeff\u00ad]", "", str(s))
    s = s.replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()


def fmt_duration(minutes: int) -> str:
    if minutes <= 0:
        return "待定"
    if minutes % 60 == 0:
        return "约 %d 小时" % (minutes // 60)
    if minutes % 30 == 0:
        return "约 %.1f 小时" % (minutes / 60.0)
    h, mm = divmod(minutes, 60)
    return "约 %d 小时 %d 分钟" % (h, mm) if h else "约 %d 分钟" % mm


def parse_time(raw: str):
    """返回 (起始日期, 显示时间, 时长, 跨天数)。支持多日与单日时段。"""
    s = clean(raw).replace("（", "(").replace("）", ")")
    dates = []
    m2 = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[-–~～]\s*(\d{1,2})\s*[日号]", s)
    if m2:
        dates = ["%02d-%02d" % (int(m2.group(1)), int(m2.group(2))),
                 "%02d-%02d" % (int(m2.group(1)), int(m2.group(3)))]
    for m in re.finditer(r"(?:(?:\d{4})\s*[-/.年]\s*)?(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*(?:日|号)?", s):
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            d = "%02d-%02d" % (mm, dd)
            if d not in dates:
                dates.append(d)

    times = re.findall(r"(\d{1,2})\s*[:：]\s*(\d{2})", s)
    if len(times) >= 2:
        m1 = int(times[0][0]) * 60 + int(times[0][1])
        m2 = int(times[1][0]) * 60 + int(times[1][1])
        minutes = m2 - m1
        if minutes <= 0:
            minutes += 24 * 60
        t1 = "%02d:%s" % (int(times[0][0]), times[0][1])
        t2 = "%02d:%s" % (int(times[1][0]), times[1][1])
        span = "%s – %s" % (t1, t2)
        return (dates[0] if dates else ""), span, fmt_duration(minutes), 1

    if len(dates) >= 2:
        # 只写了日期：多日 / 全天
        days = 2
        span = "至 %s 全天" % dates[1] if len(dates) == 2 else "至 %s 全天" % dates[-1]
        return dates[0], span, "跨 %d 天" % max(days, len(dates)), len(dates)
    if len(times) == 1:
        return (dates[0] if dates else ""), "约 %02d:%s 开始" % (int(times[0][0]), times[0][1]), "待定", 0
    return (dates[0] if dates else ""), "时间待定", "待定", 0


def norm_fee(raw: str):
    """返回 (显示文本, 是否待定, 完整票价说明)。复杂票价原样保留。"""
    s = clean(raw)
    if not s:
        return "待确认", True, ""
    if "免费" in s:
        return "免费", False, ""
    # ① 明确的价位区间：50 - 198、¥128~176
    m = re.search(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*元?\s*[-–~～至]\s*[¥￥]?\s*(\d+(?:\.\d+)?)", s)
    if m and len(m.group(2)) >= 1:
        return "¥%s – %s" % (m.group(1), m.group(2)), False, (s if len(s) > 10 else "")
    # ② 多档票价（单人/双人/套票等多种）
    prices = re.findall(r"[¥￥]\s*(\d+(?:\.\d+)?)", s) or re.findall(r"(\d+(?:\.\d+)?)\s*元", s)
    if len(prices) >= 2 or any(k in s for k in ("单人", "双人", "套票", "票种", "套餐")):
        short = s if len(s) <= 16 else s[:16].rstrip() + "…"
        return short, False, s
    # ③ 单一价格（后面括号里的说明进弹窗）
    if prices:
        return "¥" + prices[0], False, (s if len(s) > 8 else "")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    return ("¥" + nums[0] if nums else s), False, ""


def guess_type(name: str, explicit: str):
    if explicit:
        for k, v in TYPES.items():
            if k in explicit:
                return v
    for k in KEYWORDS_CHARITY:
        if k in name:
            return "charity"
    for k in KEYWORDS_EXPLORE:
        if k in name:
            return "explore"
    return "workshop"


def parse_links(raw: str):
    if not raw:
        return []
    out, seen = [], set()
    for p in [x for x in re.split(r"[\s,，、;；]+", raw) if x]:
        if p in seen:
            continue
        seen.add(p)
        if p.startswith("#小程序") or "小程序://" in p:
            out.append({"label": "小程序报名", "url": p})
        elif "hudongba" in p:
            out.append({"label": "互动吧报名", "url": p})
        elif "mp.weixin.qq.com" in p:
            out.append({"label": "公众号详情", "url": p})
        elif p.startswith("http"):
            out.append({"label": "报名链接", "url": p})
        else:
            out.append({"label": "报名", "url": p})
    return out


# ---------------------------------------------------------------- 坐标
def load_extra_places() -> dict:
    extra = {}
    for name in ("地名坐标.txt", "地名坐标.csv"):
        f = HERE / name
        if not f.exists():
            continue
        for ln in read_text(f).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = re.split(r"[|,，\t]+", ln)
            if len(parts) >= 3:
                try:
                    extra[parts[0].strip()] = (float(parts[1]), float(parts[2]))
                except ValueError:
                    pass
    return extra


def geocode_tdt(place: str, tk: str):
    if not tk:
        return None
    url = "https://api.tianditu.gov.cn/geocoder?ds=%s&tk=%s" % (
        urllib.parse.quote(json.dumps({"keyWord": place}, ensure_ascii=False)), tk)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://www.tianditu.gov.cn/"})
        with urllib.request.urlopen(req, timeout=8) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        loc = j.get("location") or {}
        if loc.get("lat") and loc.get("lon"):
            return float(loc["lat"]), float(loc["lon"])
    except Exception:
        return None
    return None


def locate(place: str, extra: dict, tk: str, use_geo: bool):
    for table, note in ((extra, "地名坐标.txt"), (PLACES, "内置地名表")):
        for k, v in table.items():
            if k and k in place:
                return v[0], v[1], note
    if use_geo:
        g = geocode_tdt(place, tk)
        if g:
            return g[0], g[1], "在线编码"
    for k, v in DISTRICTS.items():
        if k in place:
            return v[0], v[1], "区中心(粗略)"
    return 39.9042, 116.4074, "未识别→北京市中心"


# ---------------------------------------------------------------- 组装
def build_activities(blocks, extra, tk, use_geo):
    acts, warns = [], []
    for i, b in enumerate(blocks, 1):
        f = b["fields"]
        name = clean(f.get("标题") or f.get("名称") or f.get("活动名称") or b["head"] or "")
        if not name:
            continue
        raw_time = f.get("时间") or f.get("日期") or ""
        d, t, dur, _span = parse_time(raw_time)
        place = clean(f.get("地点") or f.get("地址") or "")
        fee, pending, fee_note = norm_fee(f.get("费用") or f.get("收费") or f.get("价格") or f.get("票价") or "")
        typ = guess_type(name + " " + (f.get("主题") or ""), f.get("类型") or f.get("分类") or "")
        links = parse_links(f.get("报名") or f.get("链接") or f.get("报名链接") or "")
        lat, lng, how = locate(place, extra, tk, use_geo)
        if how in ("区中心(粗略)", "未识别→北京市中心"):
            warns.append("「%s」用的是%s，建议在 地名坐标.txt 里补精确坐标" % (place or name, how))

        note = "；".join(clean(x) for x in [f.get("活动"), f.get("日程"), f.get("备注"),
                                           f.get("简介"), f.get("说明")] if x)
        host = (f.get("主办") or f.get("主办方") or f.get("主题") or "").strip() \
            or ("%s · 志远行整理" % TAG_NAME[typ])

        acts.append({
            "id": "act%d" % i,
            "name": name,
            "type": typ,
            "place": place or "地点待定",
            "date": d or "本月",
            "time": t,
            "duration": dur,
            "fee": fee,
            "feePending": pending,
            "feeNote": fee_note,
            "note": note,
            "host": host,
            "lat": round(lat, 4),
            "lng": round(lng, 4),
            "links": links,
        })
    return acts, warns


def find_template(explicit=None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit("找不到模板：%s" % explicit)
        return p

    def usable(p):
        if "生成" in p.name:
            return False
        if p.name.lower().startswith("index"):
            return False
        if re.search(r"_\d{2}[.\-]\d{2}\.html$", p.name):
            return False
        return "共学地图" in p.name or p.stat().st_size > 30000

    cands = [p for p in HERE.glob("*.html") if usable(p)]
    if not cands:
        cands = [p for p in HERE.glob("*.html") if p.stat().st_size > 30000]
    if not cands:
        sys.exit("没找到网页模板（含「共学地图」的 html），请把本脚本放到网页同目录")
    return max(cands, key=lambda p: p.stat().st_mtime)


def date_range(acts):
    ds = sorted({a["date"] for a in acts if re.match(r"\d{2}-\d{2}$", a["date"])})
    if not ds:
        return "本周"
    fmt = lambda x: "%s.%s" % (x[:2], x[3:])
    return fmt(ds[0]) if len(ds) == 1 else "%s – %s" % (fmt(ds[0]), fmt(ds[-1]))


# 部署地址：分享卡片的 og:url / og:image 用它拼。换域名只改这一行。
SITE_URL = "https://zaohuazheyue.github.io/merit-and-ambition-map/"
COVER_NAME = "weixin_cover.png"    # 分享封面：放仓库根目录，ASCII 小写命名，别用中文


def inject_meta(html, title, desc, site):
    """把模板里的 __META_*__ 占位符换成真实值；模板没有占位符就原样返回。"""
    site = (site or "").rstrip("/") + "/"
    pairs = {
        "__META_TITLE__": title,
        "__META_DESC__": desc.replace('"', "'"),
        "__META_URL__": site,
        "__META_IMG__": site + COVER_NAME,
    }
    for k, v in pairs.items():
        html = html.replace(k, v)
    return html


def render(tpl_html: str, acts) -> str:
    block = "const activities = " + json.dumps(acts, ensure_ascii=False, indent=2) + ";"
    pat = re.compile(r"const activities = \[.*?\n\];", re.S)
    if len(pat.findall(tpl_html)) != 1:
        sys.exit("模板里没找到唯一的 `const activities = [...]`，请确认模板是否被改过")
    html = pat.sub(lambda _m: block, tpl_html, count=1)

    rng = date_range(acts)
    title = "%s · 志远行共学活动地图" % rng
    html = re.sub(r"<title>.*?</title>", "<title>%s</title>" % title, html, count=1)

    # 微信 / QQ 抓取用的分享卡片信息
    names = [a["name"].split("·")[0].strip() for a in acts][:3]
    desc = "%s 北京 %d 场活动：%s%s" % (rng, len(acts), " · ".join(names), " 等" if len(acts) > 3 else "")
    return inject_meta(html, title, desc, SITE_URL)


def main():
    ap = argparse.ArgumentParser(description="志远行共学地图 · 活动批量生成器")
    ap.add_argument("input", nargs="?", help="活动文本文件（默认 活动更新文本.txt）")
    ap.add_argument("-o", "--out", help="输出 html 路径")
    ap.add_argument("-t", "--template", help="模板 html 路径（默认自动找）")
    ap.add_argument("--demo", action="store_true", help="用内置示例文本")
    ap.add_argument("--geocode", action="store_true", help="未收录地名调用天地图在线编码")
    ap.add_argument("--open", action="store_true", help="生成后自动打开浏览器")
    args = ap.parse_args()

    if args.demo:
        text, src_name = DEMO_TEXT, "内置示例"
    else:
        if args.input:
            src = Path(args.input)
            if not src.is_absolute() and not src.exists():
                src = HERE / src
        else:
            src = None
            for cand in (HERE / "活动更新文本.txt",
                         HERE.parent / "活动更新文本.txt",
                         HERE / "活动文本.txt",
                         HERE / "活动.txt"):
                if cand.exists() and cand.stat().st_size > 0:
                    src = cand
                    break
            if src is None:
                src = HERE / "活动更新文本.txt"
        if not src.exists():
            sys.exit("找不到活动文本：%s（可先用 --demo 试试）" % src)
        text = read_text(src)
        src_name = src.name

    blocks = split_blocks(text)
    if not blocks:
        sys.exit("没解析出活动，检查格式：标题/时间/地点/费用 各占一行，用「键：值」")

    tpl = find_template(args.template)
    tpl_html = read_text(tpl)
    tk = ""
    m = re.search(r'const TDT_KEY = "([0-9a-fA-F]{16,})"', tpl_html)
    if m:
        tk = m.group(1)

    acts, warns = build_activities(blocks, load_extra_places(), tk, args.geocode)
    if not acts:
        sys.exit("解析到 0 场活动")

    html = render(tpl_html, acts)
    rng = date_range(acts)
    out = Path(args.out) if args.out else HERE / ("志远行共学地图_生成_%s.html" % rng.replace("–", "-").replace(" ", ""))
    out.write_text(html, encoding="utf-8")

    print("模板：%s" % tpl.name)
    print("来源：%s  →  解析 %d 场" % (src_name, len(acts)))
    print("-" * 74)
    for a in acts:
        print("  [%s] %s" % (TAG_NAME[a["type"]], a["name"][:36]))
        print("        %s %s ｜ %s ｜ %s" % (a["date"], a["time"], a["duration"], a["fee"]))
        print("        %s (%s, %s)  报名:%d 条  %s" % (
            a["place"][:28], a["lat"], a["lng"], len(a["links"]),
            ("备注" + str(len(a["note"])) + "字") if a["note"] else ""))
    print("-" * 74)
    for w in warns:
        print("  提示：" + w)
    print("已生成：%s（%.1f KB）" % (out, out.stat().st_size / 1024))
    if args.open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
