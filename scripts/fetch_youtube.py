"""YouTube 频道列表（yt-dlp，无需 API key）→ data/youtube.json

- 列表用 --flat-playlist（快，但日期只是“N 个月前”的近似值）
- 精确上传日期逐条抓取，缓存在 data/raw/youtube_<channel>_dates.tsv，只补新视频
"""
import json, pathlib, re, subprocess, sys, time
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
YTDLP = str(ROOT / '.venv' / 'bin' / 'yt-dlp')
# 是否官方未能核实：UCR4U 频道名“睡前消息”、13.7 万订阅、按期号更新；@maqianzu 为“马前卒”，只发其他栏目
CHANNELS = {'UCR4U_q_MojVVqYnawAVlryw': '睡前消息', 'UCZERVNjvgTd3Fz7k25fKkXA': '马前卒(@maqianzu)'}
SHOW = r'睡前消息|Bedtime|马督工|马前卒'
EP = re.compile(r'(?:【睡前消息|\[(?:Bedtime|Pre-Sleep|Sleep Before) (?:News|Message)\s*)(\d{1,4}(?:\.\d)?)(?=[】\]\s])')


def flat(cid):
    r = subprocess.run([YTDLP, '--flat-playlist', '-J', '--extractor-args', 'youtubetab:approximate_date',
                        f'https://www.youtube.com/channel/{cid}/videos'], capture_output=True, text=True)
    if r.returncode:
        print('  [yt-dlp]', cid, r.stderr.strip().splitlines()[-1:])
        return None
    return json.loads(r.stdout)['entries']


def exact_dates(cid, ids, limit):
    cache = ROOT / 'data' / 'raw' / f'youtube_{cid}_dates.tsv'
    have = {l.split('\t')[0]: l.split('\t')[1] for l in cache.read_text().splitlines()} if cache.exists() else {}
    todo = [i for i in ids if i not in have][:limit]
    if todo:
        r = subprocess.run([YTDLP, '--skip-download', '--ignore-errors', '--sleep-requests', '1', '--sleep-interval', '3',  # 0.3s 时抓了 ~470 条后被限流一小时
                            '--print',
                            '%(id)s\t%(upload_date)s\t%(timestamp)s\t%(title)s', '--']
                           + todo, capture_output=True, text=True)
        # 永久性错误（已删除/私密/不可用）记成 GONE，下次不再查；限流之类的临时错误不记，下次重试
        gone = [f"{i}\t{'MEMBERS' if 'members' in msg else 'GONE'}\t\t{msg[:80]}\n" for i, msg in re.findall(r'ERROR: \[youtube\] ([\w-]{11}): (.*)', r.stderr)
                if not re.search(r'rate-limit|try again later|timed out|HTTP Error 5|Sign in to confirm', msg)]
        with cache.open('a') as f:
            f.write(r.stdout + ''.join(gone))
        have.update({l.split('\t')[0]: l.split('\t')[1] for l in (r.stdout + ''.join(gone)).splitlines()})
    return have


def fetch(limit=200):
    out, ok = [], True
    for cid, name in CHANNELS.items():
        es = flat(cid)
        if es is None:
            ok = False
            continue
        dates = exact_dates(cid, [e['id'] for e in es], limit)
        for e in es:
            m = EP.search(e.get('title') or '')
            d = dates.get(e['id'])
            approx = e.get('timestamp') and dt.datetime.fromtimestamp(e['timestamp'], dt.timezone.utc).date().isoformat()
            out.append({'id': e['id'], 'channel': cid, 'channel_name': name, 'title': e.get('title'),
                        'episode': float(m.group(1)) if m else None,
                        'date': f'{d[:4]}-{d[4:6]}-{d[6:]}' if d and d[:1].isdigit() else None, 'alive': d != 'GONE',  # MEMBERS = 会员专享，视频还在
                        'approx_date': approx, 'url': f"https://www.youtube.com/watch?v={e['id']}"})
    # 文稿库里嵌的 YouTube 视频（频道列表里没有的）：逐条确认还在 + 拿上传日期
    af = ROOT / 'data' / 'archive.json'
    seen = {v['id'] for v in out}
    ref = {e['youtube_id']: e['no'] for e in json.loads(af.read_text())['episodes']
           if e.get('youtube_id') and e['youtube_id'] not in seen} if af.exists() else {}
    if ref and ok:
        dates = exact_dates('archive', list(ref), limit)  # 抓不到的（已删/私密）不会出现在结果里
        tf = ROOT / 'data' / 'raw' / 'youtube_archive_dates.tsv'
        titles = {l.split('\t')[0]: l.split('\t')[3] for l in tf.read_text().splitlines() if l.count('\t') >= 3}
        # 文稿里有时嵌的是节目引用的新闻片段，不是这一期本身：标题得像节目才算补档
        ref = {i: no for i, no in ref.items() if i not in titles or re.search(SHOW, titles[i])}
        out += [{'id': i, 'channel': None, 'channel_name': '文稿库引用', 'title': titles.get(i), 'episode': float(no),
                 'date': f'{dates[i][:4]}-{dates[i][4:6]}-{dates[i][6:]}' if dates[i][:1].isdigit() else None,
                 'alive': dates[i] != 'GONE',
                 'approx_date': None, 'url': f'https://www.youtube.com/watch?v={i}'}
                for i, no in ref.items() if i in dates]
    if ok:
        (ROOT / 'data' / 'youtube.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out, ok


def uploaders(ids):
    """YouTube 视频的上传者（频道名、频道 id），用于致谢。缓存到 youtube_uploaders.tsv，只补新的。"""
    f = ROOT / 'data' / 'raw' / 'youtube_uploaders.tsv'
    have = {l.split('\t')[0]: l.split('\t')[1:3] for l in f.read_text().splitlines()} if f.exists() else {}
    todo = [i for i in ids if i not in have]
    if todo:
        r = subprocess.run([YTDLP, '--skip-download', '--ignore-errors', '--sleep-requests', '1', '--sleep-interval', '3',
                            '--print', '%(id)s\t%(channel)s\t%(channel_id)s', '--'] + todo, capture_output=True, text=True)
        with f.open('a') as fh:
            fh.write(r.stdout)
        have.update({l.split('\t')[0]: l.split('\t')[1:3] for l in r.stdout.splitlines()})
    return have


def search_mirrors(nos):
    """B站和已知频道都没有的期：YouTube 搜“睡前消息 N”，标题含【睡前消息N】/[... N] 才算补档。缓存到 yt_search_mirrors.json。"""
    f = ROOT / 'data' / 'raw' / 'yt_search_mirrors.json'
    cache = json.loads(f.read_text()) if f.exists() else {}
    for n in [n for n in nos if str(n) not in cache]:
        r = subprocess.run([YTDLP, '--flat-playlist', '-J', f'ytsearch10:睡前消息 {n:g}'], capture_output=True, text=True)
        es = json.loads(r.stdout)['entries'] if r.returncode == 0 else []
        cache[str(n)] = [{'id': e['id'], 'title': e.get('title'), 'channel': e.get('channel'), 'channel_id': e.get('channel_id'),
                          'url': f"https://www.youtube.com/watch?v={e['id']}"}
                         for e in es if (m := EP.search(e.get('title') or '')) and float(m.group(1)) == n]
        f.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        time.sleep(5)
    return cache


if __name__ == '__main__':
    if sys.argv[1:] == ['uploaders']:
        ids = [v['id'] for v in json.loads((ROOT / 'data' / 'youtube.json').read_text()) if v['channel_name'] == '文稿库引用']
        ids += [v['id'] for vs in json.loads((ROOT / 'data' / 'raw' / 'yt_search_mirrors.json').read_text()).values() for v in vs]
        print(f'上传者：{len(uploaders(ids))} 条')
        raise SystemExit
    if sys.argv[1:2] == ['search']:
        res = search_mirrors([float(x) for x in sys.argv[2:]])
        print({k: [(v['channel'], v['title'][:30]) for v in vs] for k, vs in res.items()})
        raise SystemExit
    assert EP.search('[Bedtime News 1123] x').group(1) == '1123' and EP.search('【睡前消息914.5】').group(1) == '914.5'
    assert EP.search('[Bedtime News 10:35] x') is None and EP.search('[Bedtime Message 1063] x').group(1) == '1063'
    vids, ok = fetch(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
    print(f"YouTube {len(vids)} 条，其中带期号 {sum(v['episode'] is not None for v in vids)}，"
          f"有精确日期 {sum(bool(v['date']) for v in vids)}，完整={ok}")
