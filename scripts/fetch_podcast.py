"""蜻蜓FM「睡前消息」频道 378005（音频版，约到第 504 期 / 2022-11）→ data/podcast.json

是否官方未能核实（文稿库引用过这个频道）。日期优先取标题里的【YYYY.MM.DD】原播出日期，否则用 update_time。
没写期号的，按标题（去标点后完全相同）对文稿库配期号。
"""
import json, pathlib, re, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CH = 378005
EP = re.compile(r'【睡前消息\s*(\d{1,4}(?:\.\d)?)】')
AIR = re.compile(r'^【(20\d\d)\.(\d\d)\.(\d\d)\s*】')  # 标题里的原播出日期


def core(t):
    t = re.sub(r'^【[^】]*】', '', t or '')
    return re.sub(r'[^\w]', '', t)


def archive_index():
    """文稿库标题 → 期号，用来给没写期号的音频配期号（标题去掉标点后完全相同才算）"""
    f = ROOT / 'data' / 'archive.json'
    if not f.exists():
        return {}
    idx = {}
    for e in json.loads(f.read_text())['episodes']:
        idx.setdefault(core(e['title']), e['no'])
    return idx


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read())


def fetch():
    v = get(f'https://i.qtfm.cn/capi/channel/{CH}')['data']['v']
    idx = archive_index()
    out, page = [], 1
    while True:
        d = get(f'https://i.qtfm.cn/capi/channel/{CH}/programs/{v}?curpage={page}&pagesize=100')['data']
        for p in d['programs']:
            m, a = EP.search(p['title']), AIR.search(p['title'])
            no = float(m.group(1)) if m else idx.get(core(p['title']))
            out.append({'id': p['id'], 'title': p['title'], 'episode': float(no) if no is not None else None,
                        'matched_by': 'title_no' if m else 'archive_title' if no is not None else None,
                        'date': '-'.join(a.groups()) if a else p['update_time'][:10], 'date_from': 'title' if a else 'update_time',
                        'url': f"https://www.qtfm.cn/channels/{CH}/programs/{p['id']}/"})
        if page * 100 >= d['total']:
            break
        page += 1
        time.sleep(1)
    (ROOT / 'data' / 'podcast.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    assert core('【2020.10.09】政府 企业 农民都没错，但是教师的工资去哪了？') == core('【睡前消息178】政府/企业/农民都没错，但是教师的工资去哪了？')
    ps = fetch()
    eps = sorted(p['episode'] for p in ps if p['episode'])
    print(f'蜻蜓FM {len(ps)} 条，带期号 {len(eps)}，期号 {eps[0]:g}–{eps[-1]:g}，日期 {min(p["date"] for p in ps)} – {max(p["date"] for p in ps)}')
