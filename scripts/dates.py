"""日期补全：BV→aid 换算、按 aid / 期号插值推算、跳号区间，以及一次性用 B站 view 接口补精确日期。

python3 scripts/dates.py   → 对所有有 bvid 的期调 view 接口（已缓存的跳过），结果缓存到 data/raw/bili_view_dates.json
"""
import datetime as dt, json, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / 'data' / 'raw' / 'bili_view_dates.json'
BJ = dt.timezone(dt.timedelta(hours=8))
ALPHA = 'FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf'
# 编号跳过、从没播出的区间（研究结论：暑假 / 冷静期 / 1073-1074 后被放假）
SKIPPED = [(597, 645), (687, 841), (1076, 1121)]
# 封禁/禁言期间“暂无更新”的期号：没有任何平台发布记录，推断同样跳过
SKIPPED_INFERRED = [(590, 591), (674, 676), (948, 953)]


def bv2aid(bv):
    b = list(bv)
    b[3], b[9] = b[9], b[3]
    b[4], b[7] = b[7], b[4]
    t = 0
    for c in b[3:]:
        t = t * 58 + ALPHA.index(c)
    return (t & ((1 << 51) - 1)) ^ 23442827791579


def skipped(n, inferred=True):
    return any(lo <= n <= hi for lo, hi in SKIPPED + (SKIPPED_INFERRED if inferred else []))


def _od(s):
    return dt.date.fromisoformat(s).toordinal()


def _interp(x, x0, d0, x1, d1):
    return dt.date.fromordinal(round(_od(d0) + (_od(d1) - _od(d0)) * (x - x0) / (x1 - x0))).isoformat()


def estimate(eps):
    """eps: {期号: episode dict}，只改没日期、播出过的期；返回 {期号: (日期, 来源)}"""
    out = {}
    exact = [(bv2aid(e['bvid']), e['date']) for e in eps.values()
             if e['date'] and not e.get('date_estimated') and e['bvid']]
    anchors = sorted((a, d) for a, d in exact if a > 1e13)  # 2024-12 以后的 aid 随时间单调
    for n, e in eps.items():
        if e['date'] or not e.get('aired', True) or not e['bvid']:
            continue
        a = bv2aid(e['bvid'])
        if a <= 1e13 or len(anchors) < 2:
            continue
        lo = [x for x in anchors if x[0] <= a]
        hi = [x for x in anchors if x[0] >= a]
        if lo and hi:
            (a0, d0), (a1, d1) = lo[-1], hi[0]
            out[n] = (d0 if a1 == a0 else _interp(a, a0, d0, a1, d1), 'bv_aid_interp')
        elif lo:  # 比所有锚点都新：用最后 10 个锚点外推
            (a0, d0), (a1, d1) = anchors[-10], anchors[-1]
            out[n] = (_interp(a, a0, d0, a1, d1), 'bv_aid_interp')
    dated = sorted((n, e['date']) for n, e in eps.items() if e['date'] and not e.get('date_estimated'))
    for n, e in eps.items():
        if e['date'] or n in out or not e.get('aired', True) or not float(n).is_integer():
            continue
        prev = [x for x in dated if x[0] < n]
        nxt = [x for x in dated if x[0] > n]
        if not prev or not nxt:
            continue
        (n0, d0), (n1, d1) = prev[-1], nxt[0]
        if n1 - n0 > 12 or any(n0 < lo and hi < n1 for lo, hi in SKIPPED) or d1 < d0:
            continue
        out[n] = (_interp(n, n0, d0, n1, d1), 'epno_interp')
    return out


def fill_view(bvids, recheck=0):
    """view 接口拿 pubdate / 是否还在。先查没缓存的，再复查 recheck 个最久没查的。遇到风控就停，已拿到的保存。"""
    import bili
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [b for b in bvids if b not in cache]
    todo += sorted((b for b in bvids if b in cache), key=lambda b: cache[b].get('checked_at') or '')[:recheck]
    c = bili.Client()
    ok = 0
    for i, bv in enumerate(todo):
        d = c.get('https://api.bilibili.com/x/web-interface/view', {'bvid': bv}, tries=1)
        code = d.get('code')
        if code in bili.RISK_CODES:
            print(f'  第 {i + 1} 个遇到风控 code={code}，停止；已保存 {ok} 个')
            break
        pub = (d.get('data') or {}).get('pubdate')
        cache[bv] = {'code': code, 'pubdate': pub, 'title': (d.get('data') or {}).get('title'),
                     'checked_at': dt.datetime.now(BJ).isoformat(timespec='seconds'),
                     'date': dt.datetime.fromtimestamp(pub, BJ).date().isoformat() if pub else None}
        ok += bool(pub)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        time.sleep(3)
    return ok, len(todo), cache


SEARCH = ROOT / 'data' / 'raw' / 'bili_search_bvids.json'


def search_bvids(nos, mid=316568752):
    """没有 bvid 的期：B站视频搜索“睡前消息N”，只认马督工本人上传、标题含【睡前消息N】的。缓存到 bili_search_bvids.json。"""
    import re, bili
    cache = json.loads(SEARCH.read_text()) if SEARCH.exists() else {}
    c = bili.Client()
    for n in [n for n in nos if str(n) not in cache]:
        d = c.get('https://api.bilibili.com/x/web-interface/wbi/search/type',
                  {'search_type': 'video', 'keyword': f'睡前消息{n:g}'}, wbi=True, tries=1)
        if d.get('code') in bili.RISK_CODES:
            print(f'  搜索第 {n:g} 期遇到风控，停止')
            break
        hit = next((r for r in (d.get('data') or {}).get('result') or []
                    if r.get('mid') == mid and re.search(rf'【睡前消息{n:g}】', re.sub('<[^>]+>', '', r.get('title', '')))), None)
        cache[str(n)] = hit and {'bvid': hit['bvid'], 'title': re.sub('<[^>]+>', '', hit['title']), 'pubdate': hit.get('pubdate')}
        SEARCH.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        time.sleep(3)
    return cache


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['search']:
        eps = json.loads((ROOT / 'data' / 'episodes.json').read_text())
        res = search_bvids([float(e['no']) for e in eps if e.get('aired', True) and not e['bvid']])
        print(f"搜索 {len(res)} 期，找到 bvid {sum(1 for v in res.values() if v)} 个：",
              {k: v['bvid'] for k, v in res.items() if v})
        raise SystemExit
    assert bv2aid('BV17x411w7KC') == 170001, bv2aid('BV17x411w7KC')
    assert bv2aid('BV1L9Uoa9EUx') == 111298867365120, bv2aid('BV1L9Uoa9EUx')
    assert skipped(700) and not skipped(686) and not skipped(1122) and skipped(950) and not skipped(950, inferred=False)
    eps = {float(e['no']): e for e in json.loads((ROOT / 'data' / 'episodes.json').read_text())}
    want = [e['bvid'] for e in eps.values() if e['bvid'] and e.get('aired', True)]  # 全部查一遍：拿精确日期 + 是否还在
    ok, n, cache = fill_view(want)
    print(f'view 接口：本次要查 {n} 个，拿到日期 {ok} 个；缓存共 {len(cache)} 条')
