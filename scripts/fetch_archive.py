"""社区文稿库 bedtimenews/bedtimenews-archive-contents + Wayback CDX → data/archive.json

产出：每期文稿（标题、bvid、YouTube id）、社区“下架合集”、目录页里的停更/禁言提示（按期号范围）。
文稿库是社区维护的，内容当数据看，不当官方结论。
"""
import gzip, json, pathlib, re, shutil, subprocess, time, urllib.parse, urllib.request
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT / 'data' / 'raw' / 'bedtimenews'
URL = 'https://github.com/bedtimenews/bedtimenews-archive-contents'
SITE = 'https://archive.bedtime.news'
MID = 316568752


def git(*a):
    return subprocess.run(['git', '-C', str(REPO), *a], capture_output=True, text=True)


def sync_repo():
    """pull --ff-only；失败就删掉重新浅克隆。返回 (旧 commit, 新 commit, 改动的文件列表)"""
    old = git('rev-parse', 'HEAD').stdout.strip() if (REPO / '.git').exists() else None
    if not old or git('pull', '-q', '--ff-only').returncode:
        print('  [文稿库] pull 失败或没有本地副本，重新浅克隆')
        shutil.rmtree(REPO, ignore_errors=True)
        subprocess.run(['git', 'clone', '-q', '--depth', '1', URL + '.git', str(REPO)], check=True)
    new = git('rev-parse', 'HEAD').stdout.strip()
    files = git('diff', '--name-only', f'{old}..{new}').stdout.split() if old and old != new else []
    return old, new, files


def front(text):
    m = re.match(r'---\n(.*?)\n---', text, re.S)
    return dict(re.findall(r'^(\w+):\s*(.*)$', m.group(1), re.M)) if m else {}


def episodes():
    out = {}
    for p in sorted((REPO / 'main').glob('*-*/*.md')):
        m = re.fullmatch(r'(\d+)(?:-(\d+))?', p.stem)
        if not m:
            continue
        t = p.read_text(errors='ignore')
        fm = front(t)
        no = int(m.group(1)) + (int(m.group(2)) / 10 if m.group(2) else 0)  # 914-1 → 914.1（番外）
        bv = re.search(r'bvid=(BV[0-9A-Za-z]{10})', t)
        yt = re.search(r'(?:embed/|watch\?v=|youtu\.be/)([0-9A-Za-z_-]{11})', t)
        xg = re.search(r'ixigua\.com/iframe/(\d{15,20})', t)
        out[no] = {'no': no, 'kind': 'special' if m.group(2) else 'main', 'title': fm.get('title', ''),
                   'bvid': bv and bv.group(1), 'youtube_id': yt.group(1) if yt and yt.group(1) != 'YouTubeVID' else None,
                   'xigua_id': xg and xg.group(1),
                   'url': f"{SITE}/{p.relative_to(REPO).with_suffix('').as_posix()}",
                   'wiki_created': fm.get('dateCreated')}
    return out


def banned():
    """下架合集里的【睡前消息N】条目，含括号备注（如“督工自己删除”）。"""
    t = (REPO / 'banned.md').read_text()
    sec = t.split('# 睡前消息', 1)[1].split('\n# ', 1)[0]
    return [{'no': int(n), 'title': title, 'note': (re.search(r'（([^）]*)）\s*$', title) or [None, None])[1]}
            for title, n in re.findall(r'\*\*(【睡前消息(\d+)】[^*]*)\*\*', sec)]


def notes():
    """目录页的 {.is-warning}/{.is-info} 提示 → 期号范围 + 关键词。"""
    seen, out = set(), []
    for p in sorted((REPO / 'main').glob('*.md')):
        for line in re.findall(r'^>\s*(.+)$', p.read_text(), re.M):
            if line in seen or not re.search(r'禁言|冷静期|被封|放假|暑假', line):
                continue
            seen.add(line)
            m = re.search(r'(\d+)期后.*?暂缓更新。(\d+)期后', line)  # “596期后…暂缓更新。646期后恢复”
            if m:
                lo, hi = int(m.group(1)) + 1, int(m.group(2)) - 1
            else:
                m = (re.search(r'第?(\d+)\s*(?:至|-|与)\s*(\d+)期', line) or re.search(r'无(\d+)-(\d+)期', line))
                if not m:
                    continue
                lo, hi = int(m.group(1)), int(m.group(2))
            kind = 'hiatus' if '暑假' in line else 'ban'
            out.append({'lo': lo, 'hi': hi, 'kind': kind, 'text': line, 'url': f"{SITE}/{p.relative_to(REPO).with_suffix('').as_posix()}"})
    return out


def cdx(url, limit=200):
    q = urllib.parse.urlencode({'url': url, 'output': 'json', 'fl': 'timestamp,original,statuscode',
                                'collapse': 'timestamp:8', 'limit': limit})
    for i in range(3):
        try:
            rows = json.loads(urllib.request.urlopen('https://web.archive.org/cdx/search/cdx?' + q, timeout=40).read() or '[]')
            return [dict(zip(rows[0], r)) for r in rows[1:]]
        except Exception as e:  # Wayback 经常超时
            print('  [wayback]', url, e)
            time.sleep(5 * (i + 1))
    return None


def wayback_for(bvids):
    res = {}
    for bv in bvids:
        rows = cdx(f'bilibili.com/video/{bv}*', limit=5)
        res[bv] = [f"https://web.archive.org/web/{r['timestamp']}/{r['original']}" for r in rows or []]
        time.sleep(1)
    return res


def wb_get(ts, url):
    b = urllib.request.urlopen(f'https://web.archive.org/web/{ts}id_/{url}', timeout=60).read()
    return gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b


def page_state(html):
    """B站视频页存档 → alive / gone / None(看不出)"""
    s = html.decode('utf-8', 'ignore')
    t = re.search(r'<title[^>]*>(.*?)</title>', s, re.S)
    t = t.group(1).strip() if t else ''
    if '视频去哪了' in t or '出错啦' in t:
        return 'gone', t
    if '_哔哩哔哩_bilibili' in t and t != '哔哩哔哩 (゜-゜)つロ 干杯~-bilibili':
        return 'alive', t
    return None, t


def wayback_video_states(bvids):
    """对每个 bvid：按时间读 Wayback 存档，找“最后一次在线”和“第一次消失”。缓存在 data/raw/wb_video_states.json。"""
    f = ROOT / 'data' / 'raw' / 'wb_video_states.json'
    have = json.loads(f.read_text()) if f.exists() else {}
    fails = 0
    for bv in bvids:
        if bv in have and have[bv].get('done'):
            continue
        rows = cdx(f'www.bilibili.com/video/{bv}*', limit=200)
        if rows is None:
            continue
        rows = sorted((r for r in rows if r['statuscode'] == '200'), key=lambda r: r['timestamp'])
        caps, alive, failed = [], None, False
        for r in rows:
            time.sleep(2)
            try:
                st, title = page_state(wb_get(r['timestamp'], r['original']))
                fails = 0
            except Exception as e:
                print('  [wayback video]', bv, r['timestamp'], e)
                failed = True
                fails += 1
                if fails >= 5:
                    print('  [wayback video] 连续失败，停止，下次运行继续')
                    f.write_text(json.dumps(have, ensure_ascii=False, indent=1))
                    return have
                time.sleep(10 * fails)
                continue
            caps.append({'ts': r['timestamp'], 'state': st, 'title': title[:80],
                         'url': f"https://web.archive.org/web/{r['timestamp']}/{r['original']}"})
            if st == 'alive':
                alive = caps[-1]
            if st == 'gone' and alive:
                break  # 已经找到 在线→消失 这一对
        have[bv] = {'captures': caps, 'done': not failed}  # 有失败就下次重抓
        print(f"  {bv}: {' '.join((c['state'] or '?')[0] for c in caps)}")
    f.write_text(json.dumps(have, ensure_ascii=False, indent=1))
    return have


def wayback_accinfo():
    """Wayback 存过的 B站 acc/info 接口响应 → 历史 silence 值。缓存在 data/raw/wb_accinfo.json。"""
    f = ROOT / 'data' / 'raw' / 'wb_accinfo.json'
    have = json.loads(f.read_text()) if f.exists() else {}
    rows = []
    for u in (f'api.bilibili.com/x/space/wbi/acc/info?mid={MID}*', f'api.bilibili.com/x/space/acc/info?mid={MID}*'):
        rows += [r for r in cdx(u, limit=2000) or [] if r['statuscode'] == '200']
    fails = 0
    for r in rows:
        if r['timestamp'] in have:
            continue
        time.sleep(2)
        try:
            b = urllib.request.urlopen(f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}", timeout=40).read()
            d = json.loads(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b)
            fails = 0
        except Exception as e:
            print('  [wayback acc/info]', r['timestamp'], e)
            fails += 1
            if fails >= 5:  # Wayback 限流了，下次再补
                print('  [wayback acc/info] 连续失败，停止，下次运行继续')
                break
            time.sleep(10 * fails)
            continue
        dd = d.get('data') or {}
        have[r['timestamp']] = {'code': d.get('code'), 'silence': dd.get('silence'), 'sign': dd.get('sign'),
                                'url': f"https://web.archive.org/web/{r['timestamp']}/{r['original']}"}
    f.write_text(json.dumps(dict(sorted(have.items())), ensure_ascii=False, indent=1))
    return have


if __name__ == '__main__':
    f = ROOT / 'data' / 'archive.json'
    prev = json.loads(f.read_text()) if f.exists() else {}
    c_old, c_new, changed = sync_repo()
    c_old = c_old or (prev.get('commit') or [None])[0]  # CI 每次都是新克隆，上次的 commit 记在 archive.json 里
    eps, ban, nt = episodes(), banned(), notes()
    assert any(n['lo'] == 686 and n['hi'] == 841 for n in nt), 'notes 解析失败'
    ban_bv = [eps[b['no']]['bvid'] for b in ban if b['no'] in eps and eps[b['no']]['bvid']]
    # 粉丝改了下架合集或停更提示 → 记一笔，analyze 会出 pending 事件
    if prev and c_old != c_new:
        ch = {'at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'old': c_old, 'new': c_new,
              'files': changed,
              'banned_added': [b for b in ban if b['no'] not in {x['no'] for x in prev.get('banned', [])}],
              'banned_removed': [b for b in prev.get('banned', []) if b['no'] not in {x['no'] for x in ban}],
              'notes_added': [n for n in nt if n['text'] not in {x['text'] for x in prev.get('notes', [])}],
              'notes_removed': [n for n in prev.get('notes', []) if n['text'] not in {x['text'] for x in nt}]}
        log = ROOT / 'data' / 'archive_changes.json'
        hist = json.loads(log.read_text()) if log.exists() else []
        log.write_text(json.dumps(hist + [ch], ensure_ascii=False, indent=1))
        print(f"  [文稿库] {c_old[:8]}→{c_new[:8]} 改了 {len(changed)} 个文件；下架合集 +{len(ch['banned_added'])}/-{len(ch['banned_removed'])}，"
              f"停更提示 +{len(ch['notes_added'])}/-{len(ch['notes_removed'])}")
    commit = [c_new, git('log', '-1', '--format=%cI').stdout.strip()]
    old = prev.get('wayback', {})
    wb = {**old, **wayback_for([b for b in ban_bv if b not in old])}
    space = cdx(f'space.bilibili.com/{MID}*', limit=500)
    acc_hist = wayback_accinfo()
    # 下架合集里的 + B站列表里找不到的 bvid（videos.json 存在时）
    vf = ROOT / 'data' / 'videos.json'
    live = {v['bvid'] for v in json.loads(vf.read_text())} if vf.exists() else None
    check = ban_bv + ([e['bvid'] for e in eps.values() if e['bvid'] and e['bvid'] not in live] if live else [])
    vstates = wayback_video_states(list(dict.fromkeys(check)))
    out = {'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'repo': URL, 'commit': commit,
           'episodes': list(eps.values()), 'banned': ban, 'notes': nt, 'wayback': wb,
           'accinfo_history': acc_hist, 'video_states': vstates,
           'space_snapshots': [f"https://web.archive.org/web/{r['timestamp']}/{r['original']}" for r in space or []]}
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'文稿 {len(eps)} 期，下架合集 {len(ban)} 条，停更提示 {len(nt)} 条，'
          f'Wayback 视频页快照 {sum(map(len, wb.values()))} 个，空间页快照 {len(space or [])} 个，'
          f"acc/info 存档 {len(acc_hist)} 个（其中 silence=1 的 {sum(v['silence'] == 1 for v in acc_hist.values())} 个）")
    for n in nt:
        print(f"  {n['lo']}-{n['hi']} {n['kind']}: {n['text']}")
