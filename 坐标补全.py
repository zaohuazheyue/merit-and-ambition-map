#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
志远行共学地图 · 地名 → 经纬度 补全器
================================================
把「地点名」解析成经纬度，并直接写进数据 / 页面。

为什么单独一个脚本：
  · 内置地名表只覆盖常去的地方，换个场地就漏；
  · 天地图地理编码接口对非浏览器客户端常返回 418（WAF 拦截），所以默认先走高德；
  · 高德返回 GCJ-02，而页面用天地图底图是 WGS84，必须换算，否则点位偏 300–500 米。

用法：
    python 坐标补全.py "北京大兴安定镇后辛房村"         查一个地名
    python 坐标补全.py --text 活动文本_示例.txt         批量查文本里的地点 → 写入 地名坐标.txt
    python 坐标补全.py --html 生成页.html               直接改写页面里每条活动的 lat/lng
    python 坐标补全.py --text 活动.txt --html 页面.html  先补表、再把页面坐标一起刷新

参数：
    --amap-key KEY        高德 Web 服务 key（推荐；也可设环境变量 AMAP_KEY）
    --tdt-key  KEY        天地图 key（不填则自动从页面里读 TDT_KEY）
    --coord wgs84|gcj02   写入哪个坐标系，默认 wgs84（配合天地图底图）
    --no-net              不联网，只用内置表 + 区中心
    --force               表里已有也重新解析
    --dry                 只打印，不写文件
"""
import argparse
import importlib.util
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACE_FILE = HERE / "地名坐标.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PI = math.pi
A_AXIS = 6378245.0
EE = 0.00669342162296594323


# ---------------------------------------------------------------- 坐标系
def _out_of_china(lat, lng):
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _tlat(x, y):
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    r += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    r += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return r


def _tlng(x, y):
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    r += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    r += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return r


def wgs2gcj(lat, lng):
    if _out_of_china(lat, lng):
        return lat, lng
    dlat = _tlat(lng - 105.0, lat - 35.0)
    dlng = _tlng(lng - 105.0, lat - 35.0)
    rad = lat / 180.0 * PI
    magic = 1 - EE * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A_AXIS * (1 - EE)) / (magic * sq) * PI)
    dlng = (dlng * 180.0) / (A_AXIS / sq * math.cos(rad) * PI)
    return lat + dlat, lng + dlng


def gcj2wgs(lat, lng):
    wlat, wlng = lat, lng
    for _ in range(3):
        glat, glng = wgs2gcj(wlat, wlng)
        wlat += lat - glat
        wlng += lng - glng
    return wlat, wlng


def to_coord(lat, lng, native, target):
    if native == target:
        return lat, lng
    if native == "gcj02" and target == "wgs84":
        return gcj2wgs(lat, lng)
    if native == "wgs84" and target == "gcj02":
        return wgs2gcj(lat, lng)
    return lat, lng


# ---------------------------------------------------------------- 网络
def http_json(url, headers=None, timeout=8):
    hdr = {"User-Agent": UA}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body)


def amap_geocode(place, key, city="北京"):
    """高德 Web 服务地理编码。返回 (lat, lng, 级别)，坐标系 GCJ-02。"""
    q = urllib.parse.urlencode({"address": place, "city": city, "key": key, "output": "JSON"})
    j = http_json("https://restapi.amap.com/v3/geocode/geo?" + q)
    if j.get("status") == "1" and j.get("geocodes"):
        g = j["geocodes"][0]
        lng, lat = g["location"].split(",")
        return float(lat), float(lng), g.get("level", "") or "高德"
    info = j.get("info", "高德无结果")
    raise RuntimeError(info)


def tdt_geocode(place, tk):
    """天地图地理编码。返回 (lat, lng)，坐标系 CGCS2000≈WGS84。"""
    ds = json.dumps({"keyWord": place}, ensure_ascii=False)
    url = "https://api.tianditu.gov.cn/geocoder?ds=%s&tk=%s" % (urllib.parse.quote(ds), tk)
    j = http_json(url, {"Referer": "https://www.tianditu.gov.cn/"})
    loc = j.get("location") or {}
    if loc.get("lat") and loc.get("lon"):
        return float(loc["lat"]), float(loc["lon"])
    raise RuntimeError(j.get("msg") or "天地图无结果")


def osm_geocode(place):
    """OpenStreetMap Nominatim，免费但国内经常慢/被墙。WGS84。"""
    q = urllib.parse.urlencode({"format": "json", "limit": 1,
                                "accept-language": "zh-CN", "q": place})
    arr = http_json("https://nominatim.openstreetmap.org/search?" + q,
                    {"User-Agent": "zhiyuanxing-map/1.0"})
    if arr:
        return float(arr[0]["lat"]), float(arr[0]["lon"])
    raise RuntimeError("OSM 无结果")


# ---------------------------------------------------------------- 内置表
def load_generator():
    """复用 活动生成器.py 里的解析和地名表。"""
    for name in ("活动生成器.py", "活动生成器.txt"):
        f = HERE / name
        if f.exists():
            try:
                spec = importlib.util.spec_from_file_location("actgen", f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            except Exception as e:
                print("（载入 %s 失败：%s）" % (name, e))
    return None


def load_place_file():
    data = {}
    if PLACE_FILE.exists():
        for ln in PLACE_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = re.split(r"[|,，\t]+", ln)
            if len(parts) >= 3:
                try:
                    data[parts[0].strip()] = (float(parts[1]), float(parts[2]))
                except ValueError:
                    pass
    return data


def save_place_file(data):
    lines = ["# 地名坐标表：地名|纬度|经度   （坐标补全.py 自动维护，也可手改）"]
    for k in sorted(data):
        lines.append("%s|%.6f|%.6f" % (k, data[k][0], data[k][1]))
    PLACE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 解析主流程
class Resolver:
    def __init__(self, amap_key="", tdt_key="", target="wgs84", no_net=False, force=False, verbose=False):
        self.amap_key = amap_key
        self.tdt_key = tdt_key
        self.target = target
        self.no_net = no_net
        self.force = force
        self.verbose = verbose
        self.gen = load_generator()
        self.places = load_place_file()
        self.dirty = False
        self.cache = {}

    def say(self, *a):
        if self.verbose:
            print("   ", *a)

    def resolve(self, place):
        """返回 (lat, lng, 来源, native坐标系)。"""
        key = place.strip()
        if key in self.cache:
            return self.cache[key]
        res = self._resolve(key)
        self.cache[key] = res
        return res

    def _resolve(self, place):
        # 1) 已有表
        if not self.force and place in self.places:
            self.say("命中 地名坐标.txt")
            return self.places[place][0], self.places[place][1], "地名坐标.txt", self.target
        # 2) 内置表（关键词包含即算命中）
        if self.gen:
            for table, label in ((getattr(self.gen, "PLACES", {}), "内置地名表"),):
                for k, v in table.items():
                    if k and k in place:
                        self.say("命中" + label, "→", k)
                        return v[0], v[1], label + ":" + k, self.target
        # 3) 在线
        if not self.no_net:
            if self.amap_key:
                try:
                    lat, lng, lvl = amap_geocode(place, self.amap_key)
                    self.say("高德", lvl)
                    return lat, lng, "高德:" + lvl, "gcj02"
                except Exception as e:
                    self.say("高德失败:", e)
            if self.tdt_key:
                try:
                    lat, lng = tdt_geocode(place, self.tdt_key)
                    self.say("天地图")
                    return lat, lng, "天地图", "wgs84"
                except Exception as e:
                    self.say("天地图失败:", e)
            try:
                lat, lng = osm_geocode(place)
                self.say("OSM")
                return lat, lng, "OpenStreetMap", "wgs84"
            except Exception as e:
                self.say("OSM 失败:", e)
        # 4) 区中心
        if self.gen:
            for k, v in getattr(self.gen, "DISTRICTS", {}).items():
                if k in place:
                    return v[0], v[1], "区中心:" + k, self.target
        return None


def fmt(lat, lng):
    return "%.6f, %.6f" % (lat, lng)


# ---------------------------------------------------------------- 三种模式
def mode_single(args, rv):
    for place in args.places:
        r = rv.resolve(place)
        if not r:
            print("✗ %-30s 没解析出来" % place)
            continue
        lat, lng, src, native = r
        la, lo = to_coord(lat, lng, native, args.coord)
        print("%-30s → %s   [%s → %s]" % (place, fmt(la, lo), src, args.coord))
        if not args.dry and place not in rv.places:
            rv.places[place] = (la, lo)
            rv.dirty = True


def mode_text(args, rv):
    src = Path(args.text)
    if not src.is_absolute() and not src.exists():
        src = HERE / src
    if not src.exists():
        sys.exit("找不到文本：%s" % args.text)

    raw = src.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = raw.decode("utf-8", "replace")

    if not rv.gen:
        sys.exit("需要同目录的 活动生成器.py 来解析文本格式")
    blocks = rv.gen.split_blocks(text)
    if not blocks:
        sys.exit("没解析出活动，检查「标题/时间/地点/费用」格式")

    places = []
    for b in blocks:
        f = b["fields"]
        p = (f.get("地点") or f.get("地址") or "").strip()
        if p and p not in places:
            places.append(p)

    print("从 %s 读到 %d 场活动 / %d 个地点" % (src.name, len(blocks), len(places)))
    print("-" * 76)
    ok = 0
    for p in places:
        r = rv.resolve(p)
        if not r:
            print("✗ %-28s 定位失败，请手动加进 地名坐标.txt" % p[:28])
            continue
        lat, lng, src_name, native = r
        la, lo = to_coord(lat, lng, native, args.coord)
        print("✓ %-28s %s   [%s]" % (p[:28], fmt(la, lo), src_name))
        if not args.dry:
            rv.places[p] = (la, lo)
            rv.dirty = True
        ok += 1
    print("-" * 76)
    print("成功 %d / %d" % (ok, len(places)))


def mode_html(args, rv):
    f = Path(args.html)
    if not f.is_absolute() and not f.exists():
        f = HERE / f
    if not f.exists():
        sys.exit("找不到页面：%s" % args.html)
    html = f.read_text(encoding="utf-8")

    m = re.search(r"const activities = (\[[\s\S]*?\n\]);", html)
    if not m:
        sys.exit("页面里没找到 activities 数据块")
    try:
        acts = json.loads(m.group(1))
    except json.JSONDecodeError:
        sys.exit("这个页面的数据是 JS 对象写法（模板），请用 --text 补表后重新生成，而不是直接改模板")

    print("%s 里 %d 场活动" % (f.name, len(acts)))
    print("-" * 76)
    changed = 0
    for a in acts:
        place = a.get("place", "")
        if not place or place in ("地点待定", ""):
            continue
        r = rv.resolve(place)
        if not r:
            print("✗ %-28s 定位失败" % place[:28])
            continue
        lat, lng, src_name, native = r
        la, lo = to_coord(lat, lng, native, args.coord)
        old = (a.get("lat"), a.get("lng"))
        new = (round(la, 5), round(lo, 5))
        moved = abs(old[0] - new[0]) > 1e-5 or abs(old[1] - new[1]) > 1e-5
        print("%s %-26s %s → %s  [%s]" % ("~" if moved else "=", place[:26],
                                          fmt(old[0], old[1]), fmt(new[0], new[1]), src_name))
        a["lat"], a["lng"] = new
        if moved:
            changed += 1
        if not args.dry and place not in rv.places:
            rv.places[place] = (la, lo)
            rv.dirty = True

    print("-" * 76)
    if args.dry:
        print("（--dry：没有写入）")
        return
    block = "const activities = " + json.dumps(acts, ensure_ascii=False, indent=2) + ";"
    html = html[:m.start()] + block + html[m.end():]
    f.write_text(html, encoding="utf-8")
    print("已写回 %s（坐标变动 %d 处）" % (f.name, changed))


def main():
    ap = argparse.ArgumentParser(description="地名 → 经纬度 补全器")
    ap.add_argument("places", nargs="*", help="要查的地名")
    ap.add_argument("--text", help="按活动文本批量补全")
    ap.add_argument("--html", help="改写页面里的 lat/lng")
    ap.add_argument("--amap-key", default=os.environ.get("AMAP_KEY", ""))
    ap.add_argument("--tdt-key", default="")
    ap.add_argument("--coord", default="wgs84", choices=["wgs84", "gcj02"])
    ap.add_argument("--no-net", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tk = args.tdt_key
    if not tk:
        for p in [Path(args.html)] if args.html else []:
            pass
        for p in HERE.glob("*.html"):
            t = p.read_text(encoding="utf-8", errors="replace")
            mm = re.search(r'const TDT_KEY = "([0-9a-fA-F]{16,})"', t)
            if mm:
                tk = mm.group(1)
                break

    if not args.places and not args.text and not args.html:
        print(__doc__)
        return

    rv = Resolver(args.amap_key, tk, args.coord, args.no_net, args.force, args.verbose)
    print("坐标系统：%s ｜ 在线：%s ｜ 高德 key：%s ｜ 天地图 key：%s" % (
        args.coord, "否" if args.no_net else "是",
        "有" if args.amap_key else "无", "有" if tk else "无"))

    if args.places:
        mode_single(args, rv)
    if args.text:
        mode_text(args, rv)
    if args.html:
        mode_html(args, rv)

    if rv.dirty and not args.dry:
        save_place_file(rv.places)
        print("已更新 %s（%d 条）" % (PLACE_FILE.name, len(rv.places)))


if __name__ == "__main__":
    main()
