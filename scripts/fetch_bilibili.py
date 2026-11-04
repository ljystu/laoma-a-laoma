"""抓取马督工 B站全部投稿 + 账号信息 → data/snapshots/<UTC>.json 与 data/videos.json"""
import datetime as dt, json, pathlib, random, re, sys, time
import bili

MID = 316568752  # 马督工（《睡前消息》主号）；4466168 是自称“假的睡前消息”的转发号
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
EP_RE = [re.compile(p) for p in (r'第\s*(\d{1,4})\s*期', r'【睡前消息\s*(\d{1,4})】',
                                 r'睡前消息\s*(\d{1,4})', r'^\s*【?(\d{3,4})】?')]


def episode(title):
    for r in EP_RE:
        m = r.search(title)
        if m:
            return int(m.group(1))
    return None


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def fetch(mid=MID):
    c = bili.Client(referer=f'https://space.bilibili.com/{mid}')
    info = c.get('https://api.bilibili.com/x/space/wbi/acc/info', {'mid': mid}, wbi=True)
    stat = c.get('https://api.bilibili.com/x/relation/stat', {'vmid': mid})
    pages, pn = [], 1
    while True:
        d = c.get('https://api.bilibili.com/x/space/wbi/arc/search',
                  {'mid': mid, 'ps': 50, 'pn': pn, 'order': 'pubdate'}, wbi=True)
        if d.get('code') != 0:
            print(f'  第 {pn} 页失败: code={d.get("code")} {d.get("message")}')
            break
        vl = d['data']['list']['vlist']
        pages.append(vl)
        total = d['data']['page']['count']
        print(f'  第 {pn} 页 {len(vl)} 条（共 {total}）')
        if not vl or pn * 50 >= total:
            break
        pn += 1
        time.sleep(random.uniform(20, 40))  # 1-2s 时第 2 页起就被 -352/412，放慢
    vids = [v for p in pages for v in p]
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    snap = {'fetched_at': now, 'mid': mid, 'acc_info': info, 'relation_stat': stat, 'expected_count': total if pages else None,
            'complete': bool(pages) and len(vids) >= total, 'vlist': vids, 'risk_log': bili.risk_log}
    (DATA / 'snapshots').mkdir(parents=True, exist_ok=True)
    (DATA / 'snapshots' / f'{now}.json').write_text(json.dumps(snap, ensure_ascii=False))
    norm = sorted(({'bvid': v['bvid'], 'aid': v['aid'], 'title': v['title'], 'pubdate': iso(v['created']),
                    'duration': v['length'], 'episode': episode(v['title'])} for v in vids),
                  key=lambda x: x['pubdate'])
    if snap['complete']:  # 不完整时不覆盖 videos.json，免得误判“下架”
        (DATA / 'videos.json').write_text(json.dumps(norm, ensure_ascii=False, indent=1))
    return snap, norm


if __name__ == '__main__':
    assert episode('【睡前消息812】xxx') == 812 and episode('睡前消息第 55 期') == 55
    snap, norm = fetch(int(sys.argv[1]) if len(sys.argv) > 1 else MID)
    a = (snap['acc_info'].get('data') or {})
    print(f"抓到 {len(norm)} 条 / 预期 {snap['expected_count']}，silence={a.get('silence')}，"
          f"完整={snap['complete']}，风控 {len(bili.risk_log)} 次")
