"""合并 B站 / YouTube / 社区文稿库 / Wayback → data/status.json, data/episodes.json, data/events.json

规则（用户定）：没有官方声明可依据，只能靠前后对比。
- confirmed：两个快照（我们自己的或 Wayback）直接显示视频消失或 silence 变化；证据里必须有 before。
- inferred：从更新空档、社区标注推出来的。
- pending：正在发生、还没法判断的。
日期只取自抓到的上传时间。
"""
import json, pathlib, re, statistics
import datetime as dt
from dates import estimate, skipped

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / 'data'
BJ = dt.timezone(dt.timedelta(hours=8))
MID = 316568752
EP = re.compile(r'【睡前消息\s*(\d{1,4}(?:\.\d)?)】')
VOLUNTARY_BREAKS = False  # 文稿库说是编辑部自己放的“暑假”要不要单独算（不算进宫）


def load(name, default):
    p = D / name
    return json.loads(p.read_text()) if p.exists() else default


def bj_date(iso):
    return dt.datetime.fromisoformat(iso).astimezone(BJ).date().isoformat()


def ts_date(ts):  # Wayback 14 位时间戳
    return f'{ts[:4]}-{ts[4:6]}-{ts[6:8]}'


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def num(x):
    return int(x) if float(x).is_integer() else float(x)


def gaps(dates, factor=3, min_days=10, window=20):
    """相邻上传间隔 > factor×前 window 个间隔的中位数 且 > min_days → (前一次, 后一次, 天数)"""
    out, iv = [], []
    for a, b in zip(dates, dates[1:]):
        g = days(a, b)
        med = statistics.median(iv[-window:]) if len(iv) >= 5 else None
        if med is not None and g > max(factor * med, min_days):
            out.append((a, b, g))
        iv.append(g)
    return out


def flip(states):
    """Wayback 视频页按时间排列 → (最后一次在线, 之后第一次消失)，没有就 None"""
    alive = None
    for c in states:
        if c['state'] == 'alive':
            alive = c
        elif c['state'] == 'gone' and alive:
            return alive, c
    return None


def pick_date(b, xg, ps, ys, vd=None, md=None, sp=None, n=0):
    """(日期, 来源)。优先级：B站列表 > B站 view 接口 > 手工核实（Wayback 里的 pubdate / B站动态）> 西瓜视频 ID 时间戳
    > 蜻蜓FM 标题原播出日期 > YouTube 上传日 / 文稿口播日期 > 蜻蜓FM update_time。
    900 期以后官方 YouTube 比 B站晚 0–12 天，只当上限：口播日期排在它前面。"""
    if b:
        return bj_date(b['pubdate']), 'bilibili'
    if vd:
        return vd, 'bilibili_view'
    if md:
        return md['date'], md['source']
    if xg:
        return dt.datetime.fromtimestamp(int(xg) >> 32, BJ).date().isoformat(), 'xigua_id'
    yt = (min((y['date'] for y in ys if y['date'] and y.get('channel_name') == '睡前消息'), default=None), 'youtube_upload')
    fan = (min((y['date'] for y in ys if y['date'] and y.get('channel_name') != '睡前消息'), default=None), 'youtube_upload')
    spk = (sp, 'transcript_spoken')
    for d, src in ((min((v['date'] for v in ps if v['date_from'] == 'title'), default=None), 'podcast_title'),
                   *((spk, yt) if n > 900 else (yt, spk)), fan,  # 粉丝/引用的上传日期最不可信
                   (min((v['date'] for v in ps), default=None), 'podcast_update')):
        if d:
            return d, src
    return None, None


def build(now=None):
    now = now or dt.datetime.now(BJ)
    now_s = now.isoformat(timespec='seconds')
    videos = load('videos.json', None)           # 完整列表；None = 从没抓全过
    yt = load('youtube.json', [])
    pod = load('podcast.json', [])
    tf = D / 'raw' / 'youtube_archive_dates.tsv'  # 文稿里嵌的、标题不像节目的 = 引用的新闻片段，不算补档
    cited = {l.split('\t')[0] for l in tf.read_text().splitlines()
             if l.count('\t') >= 3 and not re.search(r'睡前消息|Bedtime|马督工|马前卒', l.split('\t')[3])} if tf.exists() else set()
    up_f = D / 'raw' / 'youtube_uploaders.tsv'  # 视频 id → (频道名, 频道 id)，用于致谢
    upl = {l.split('\t')[0]: l.split('\t')[1:3] for l in up_f.read_text().splitlines()} if up_f.exists() else {}
    manual = load('manual_dates.json', {})  # 人工核实的日期（附证据链接），优先于推算
    vraw = load('raw/bili_view_dates.json', {})  # dates.py 一次性抓的 view 接口结果
    view = {bv: v['date'] for bv, v in vraw.items() if v.get('date')}
    ar = load('archive.json', {})
    removals = load('removals.json', {})        # check.py：bvid → {at, before, after}
    state = load('state.json', {})
    snaps = sorted((D / 'snapshots').glob('*.json'))
    snap = json.loads(snaps[-1].read_text()) if snaps else {}
    checked = state.get('last_check') or now_s
    # 没有完整列表时，用最近一次有数据的快照（按时间倒序的第一页是连续的，可以用来算近期空档）
    partial = next((json.loads(p.read_text())['vlist'] for p in reversed(snaps) if json.loads(p.read_text())['vlist']), [])
    blist = videos if videos is not None else [{'bvid': v['bvid'], 'title': v['title'],
                                                'pubdate': dt.datetime.fromtimestamp(v['created'], dt.timezone.utc).isoformat()}
                                               for v in partial]
    complete = videos is not None

    bili = {}
    for v in blist:
        m = EP.search(v['title'])
        if m:
            bili.setdefault(float(m.group(1)), v)
    live_bv = {v['bvid'] for v in blist} | {bv for bv, v in vraw.items() if v['code'] == 0}  # view 返回 0 = 抓取时还在
    ytm = {}
    for v in yt:
        if v['episode'] is not None and v['channel_name'] in ('睡前消息', '文稿库引用'):
            ytm.setdefault(v['episode'], []).append(v)
    for k, vs in load('raw/yt_search_mirrors.json', {}).items():  # 粉丝补档（YouTube 搜到、标题期号对得上）
        ytm.setdefault(float(k), []).extend({'url': v['url'], 'title': v['title'], 'date': None, 'alive': True,
                                              'channel_name': f"粉丝补档·{v['channel']}"} for v in vs)
    podm = {}
    for v in pod:
        if v['episode'] is not None:
            podm.setdefault(v['episode'], []).append(v)
    arc = {float(e['no']): e for e in ar.get('episodes', [])}
    banned = {float(b['no']): b for b in ar.get('banned', [])}
    vstates = {bv: flip(v['captures']) for bv, v in ar.get('video_states', {}).items()}
    wb_gone = {bv for bv, v in ar.get('video_states', {}).items() if v['captures'] and v['captures'][-1]['state'] == 'gone'}
    wb_gone |= {bv for bv, v in vraw.items() if v['code'] in (-404, 62002)}  # 稿件不存在 / 不可见（和下架合集逐一对得上）

    # ---------- episodes ----------
    nums = set(bili) | set(ytm) | set(arc) | set(podm)
    top = max((n for n in nums if n.is_integer()), default=0)
    nums |= {float(i) for i in range(1, int(top) + 1)}
    eps = {}
    for n in sorted(nums):
        b, ys, a, ps = bili.get(n), ytm.get(n, []), arc.get(n), podm.get(n, [])
        xg = (a or {}).get('xigua_id')
        bvid = (b or {}).get('bvid') or (a or {}).get('bvid')
        alive = True if bvid in live_bv else False if (complete and bvid) or bvid in wb_gone or bvid in removals else None
        srcs = []
        if bvid:
            srcs.append({'kind': 'bilibili', 'url': f'https://www.bilibili.com/video/{bvid}', 'official': True,
                         'alive': alive, 'verified': alive is not None, 'checked_at': checked})
        for y in ys:
            cname, cid = (y['channel_name'], y['channel']) if y.get('channel') else upl.get(y['url'][-11:], [None, None])
            srcs.append({'kind': 'youtube', 'url': y['url'], 'alive': y.get('alive', True), 'verified': True, 'checked_at': checked,
                         'uploader': cname, 'uploader_url': cid and f'https://www.youtube.com/channel/{cid}'})
        a_yt = (a or {}).get('youtube_id')
        if a_yt and a_yt not in cited and not any(a_yt in y['url'] for y in ys):  # 文稿里嵌的 YouTube，还没抓到确认
            srcs.append({'kind': 'youtube', 'url': f'https://www.youtube.com/watch?v={a_yt}', 'alive': None,
                         'verified': False, 'checked_at': None})
        xg = (a or {}).get('xigua_id')
        if xg:  # 西瓜视频（字节系 ID 高 32 位是上传时间戳）；文稿库说该账号被禁言，存活未核实
            srcs.append({'kind': 'other', 'url': f'https://www.ixigua.com/{xg}', 'alive': None,
                         'verified': False, 'checked_at': None})
        for pv in ps:
            srcs.append({'kind': 'podcast', 'url': pv['url'], 'alive': True, 'verified': True, 'checked_at': checked})
        if a:
            srcs.append({'kind': 'transcript', 'url': a['url'], 'alive': True, 'verified': True, 'checked_at': checked})
        if bvid and vstates.get(bvid):
            srcs.append({'kind': 'wayback', 'url': vstates[bvid][0]['url'], 'alive': True, 'verified': True, 'checked_at': checked})
        if alive:
            status = 'live'
        elif alive is None and not (complete and not bvid):
            status = 'unknown'  # B站列表没抓全，无法判断是否还在
        elif any(y.get('alive', True) for y in ys) or ps:
            status = 'mirrored'
        elif a:
            status = 'transcript_only'
        else:
            status = 'lost'
        rm = removals.get(bvid) if bvid else None
        eps[n] = {'no': num(n), 'kind': 'main' if n.is_integer() else 'special',
                  'title': (b or {}).get('title') or (a or {}).get('title') or (ys[0]['title'] if ys else None)
                           or (ps[0]['title'] if ps else None),
                  **dict(zip(('date', 'date_source'), pick_date(b, xg, ps, ys, view.get(bvid), manual.get(str(num(n))),
                                                                 (a or {}).get('spoken_date'), n))),
                  'status': status, 'bvid': bvid,
                  'removed_at': (rm['at'] if isinstance(rm, dict) else rm) if rm else
                                (ts_date(vstates[bvid][1]['ts']) if bvid and vstates.get(bvid) else None),
                  'event_id': None, 'sources': srcs}

    # 口播日期有笔误（日子或星期几写错）：用前后期的非口播日期夹一下；夹不住就按说的星期几在 ±6 天里找唯一合适的
    RELIABLE = ('bilibili', 'bilibili_view', 'wayback_pubdate', 'bilibili_dynamic', 'xigua_id', 'podcast_title')
    fixed = sorted((k, v['date']) for k, v in eps.items() if v['date'] and v['date_source'] in RELIABLE)
    for n, e in eps.items():
        if e['date_source'] != 'transcript_spoken':
            continue
        lo = next((d for k, d in reversed(fixed) if k < n), '0000')  # 最近的前一期
        hi = next((d for k, d in fixed if k > n), '9999')            # 最近的后一期
        if lo <= e['date'] <= hi:
            continue
        wd = (arc.get(n) or {}).get('spoken_wd')
        base = dt.date.fromisoformat(e['date'])
        if '0000' < lo and hi < '9999' and days(lo, hi) <= 14:  # 前后期很近：直接在两期之间找那个星期几
            days_in = (dt.date.fromisoformat(lo) + dt.timedelta(days=k) for k in range(days(lo, hi) + 1))
        else:
            days_in = (base + dt.timedelta(days=k) for k in range(-6, 7))
        cand = [c.isoformat() for c in days_in if wd is not None and c.weekday() == wd and lo <= c.isoformat() <= hi]
        if len(cand) == 1:
            e['date'], e['date_fix'] = cand[0], f"口播写的是 {base.isoformat()}，按星期几和前后期校正"
        else:
            e['date'] = e['date_source'] = None

    # YouTube 日期可能是补传：比后面任何一期还晚的，丢掉（B站日期不动）
    run_min = '9999'
    for n in sorted(eps, reverse=True):
        d = eps[n]['date']
        if d and n not in bili and eps[n]['date_source'] not in ('bilibili_view', 'wayback_pubdate', 'bilibili_dynamic', 'transcript_spoken') and d > run_min:  # 补传日期
            eps[n]['date'] = None
        elif d:
            run_min = min(run_min, d)

    # date_source 跟着日期一起清掉；口播日期没有别的来源佐证时标“口播日期”（不算精确）
    for n, e in eps.items():
        if not e['date']:
            e['date_source'] = None
        others = {y['date'] for y in ytm.get(n, []) if y['date']} | {v['date'] for v in podm.get(n, [])}
        e['date_note'] = '口播日期' if e['date_source'] == 'transcript_spoken' and e['date'] not in others else None

    # 跳号区间里、任何来源都没有的期 = 从没播出；其余没日期的按 aid / 期号推算（标 date_estimated）
    for n, e in eps.items():
        e['aired'] = not (skipped(n) and not e['sources'])
        e['date_estimated'] = False
        if not e['aired']:
            e['status'] = 'skipped'
            if not skipped(n, inferred=False):
                e['skip_note'] = '推断：无任何平台发布记录'
    for n, (d, src) in estimate(eps).items():
        eps[n].update(date=d, date_source=src, date_estimated=True)

    def ep_date(n, step):
        """从第 n 期向 step 方向找最近一个有日期的期（补传造成的乱序日期已在上面剔除）"""
        while 0 < n <= top:
            if n in eps and eps[n]['date'] and not eps[n]['date_estimated']:  # 事件起止只用确切日期
                return eps[n]['date'], n
            n += step
        return None, None

    bili_dates = sorted({bj_date(v['pubdate']) for v in blist})

    def yt_between(a, b):
        return [v for v in yt if v['date'] and v['episode'] and v['channel_name'] == '睡前消息' and a < v['date'] < b]

    def yt_ev(ys):
        return [{'kind': 'other', 'url': y['url'], 'label': f"YouTube 同期更新：{y['title'][:40]}", 'date': y['date']} for y in ys[:5]]

    events = []

    def add(ev):
        base, k = ev['id'], 2
        while any(e['id'] == ev['id'] for e in events):
            ev['id'] = f'{base}-{k}'
            k += 1
        ev.setdefault('updated_at', now_s)
        events.append(ev)
        return ev

    # 1) 社区文稿库目录页的停更/禁言提示（按期号，inferred）
    for nt in ar.get('notes', []):
        start, before = ep_date(float(nt['lo'] - 1), -1)
        end, after = ep_date(float(nt['hi'] + 1), +1)
        # 日期对不上，或者最近的有日期的期离区间太远（>3 期），宁可不出
        if not start or (end and end < start) or nt['lo'] - 1 - before > 3 or (after and after - nt['hi'] - 1 > 3):
            continue
        ys = yt_between(start, end or '9999')
        ev = add({'id': f'ev-{start[:7]}', 'type': nt['kind'], 'confidence': 'inferred', 'start': start, 'end': end,
                  'title': f"第{nt['lo']}–{nt['hi']}期 " + ('B站停更（社区标注）' if nt['kind'] == 'ban' else '暑假停更'),
                  'reason': nt['text'],
                  'summary': f"社区文稿库标注：{nt['text']} 起止按第{num(before)}期与第{num(after) if after else '?'}期的发布日期计。"
                             + (f" 同期 YouTube「睡前消息」频道仍发布 {len(ys)} 期睡前消息。" if ys else ''),
                  'affected_episodes': [num(n) for n in eps if nt['lo'] <= n <= nt['hi']],
                  'evidence': [{'kind': 'community', 'url': nt['url'], 'label': '睡前消息文稿库目录页提示', 'date': None}] + yt_ev(ys),
                  'detected_by': 'auto'})
        ev['_range'] = (start, end or now.date().isoformat())

    # 2) B站投稿空档（inferred），与已有事件重叠就只追加证据
    for a, b, g in gaps(bili_dates):
        hit = next((e for e in events if '_range' in e and e['_range'][0] <= b and a <= e['_range'][1]), None)
        evid = {'kind': 'other', 'url': f'https://space.bilibili.com/{MID}/video',
                'label': f'B站投稿间隔 {g} 天（{a} → {b}），超过近期中位间隔 3 倍', 'date': b}
        if hit:
            hit['evidence'].append(evid)
            continue
        ys = yt_between(a, b)
        ev = add({'id': f'ev-{a[:7]}', 'type': 'ban' if ys else 'hiatus', 'confidence': 'inferred',
                  'start': a, 'end': b, 'title': f'B站疑似停更 {g} 天', 'reason': None,
                  'summary': f'B站投稿出现 {g} 天空档。' + (f'同期 YouTube 仍发布 {len(ys)} 条，疑似B站单方面限制。' if ys
                                                     else '同期 YouTube 也没更新，可能是主动休息。'),
                  'affected_episodes': [], 'evidence': [evid] + yt_ev(ys), 'detected_by': 'auto'})
        ev['_range'] = (a, b)

    # 3) 下架：Wayback 在线→消失 / 自己快照前后对比 → confirmed；只有社区“下架合集” → inferred
    for n, e in eps.items():
        bv = e['bvid']
        fl = vstates.get(bv) if bv else None
        rm = removals.get(bv) if bv else None
        vgone = bv and vraw.get(bv, {}).get('code') in (-404, 62002)
        if n not in banned and not fl and not rm and not vgone and not (complete and bv and bv not in live_bv):
            continue
        note = banned.get(n, {}).get('note')
        evid = []
        if isinstance(rm, dict) and rm.get('before'):
            evid.append({'kind': 'snapshot', 'before': rm['before'], 'url': rm['after'],
                         'label': '本工具前后两次抓取：前一次在列表里，后一次不在', 'date': rm['at'][:10]})
        if fl:
            evid.append({'kind': 'wayback', 'before': fl[0]['url'], 'url': fl[1]['url'],
                         'label': f"Wayback：{ts_date(fl[0]['ts'])} 页面在线 → {ts_date(fl[1]['ts'])} 显示“视频去哪了”",
                         'date': ts_date(fl[1]['ts'])})
        if n in banned:
            evid.append({'kind': 'community', 'url': 'https://archive.bedtime.news/banned', 'label': '文稿库·下架合集', 'date': None})
        if vgone:  # 只有“之后”没有“之前”，不够 confirmed
            v = vraw[bv]
            evid.append({'kind': 'other', 'url': f'https://api.bilibili.com/x/web-interface/view?bvid={bv}',
                         'label': f"B站 view 接口返回 {v['code']}（{'稿件不存在' if v['code'] == -404 else '稿件不可见'}）",
                         'date': (v.get('checked_at') or '')[:10] or None})
        if fl:
            start, end = ts_date(fl[0]['ts']), ts_date(fl[1]['ts'])
            when = f'下架发生在 {start}（最后一次存档在线）到 {end}（第一次存档显示已删）之间。'
        elif isinstance(rm, dict):
            start, end = rm['at'][:10], rm['at'][:10]
            when = f'本工具 {start} 首次发现消失。'
        else:
            start, end = e['date'], None
            when = ('没有找到在线→消失的存档对，下架时间未知，start 用的是'
                    + ('按期号/aid 推算的发布日期。' if e['date_estimated'] else '原发布日期。'))
        if not start:
            continue  # 没有任何日期，不硬编
        ev = add({'id': f"ev-takedown-{e['no']}", 'type': 'takedown',
                  'confidence': 'confirmed' if any('before' in x for x in evid) else 'inferred',
                  'start': start, 'end': end,
                  'title': f"第{e['no']}期下架" + ('（社区备注：UP主自删）' if note and '自己删除' in note else ''),
                  'reason': note, 'summary': when + (' 列在社区“下架合集”。' if n in banned else ''),
                  'affected_episodes': [e['no']], 'evidence': evid, 'detected_by': 'auto'})
        e['event_id'] = ev['id']

    # 4) silence 变化：Wayback 存档的 acc/info + 本工具记录（都是前后对比 → confirmed）
    hist = [(ts, v) for ts, v in sorted(ar.get('accinfo_history', {}).items()) if v['code'] == 0]
    hist += [(t, {'silence': s, 'url': u}) for t, s, u in state.get('silence_log', [])]  # 自己的快照
    hist.sort(key=lambda x: x[0].replace('-', '').replace(':', '').replace('T', ''))
    i = 0
    while i < len(hist):
        if hist[i][1]['silence'] != 1:
            i += 1
            continue
        j = i
        while j + 1 < len(hist) and hist[j + 1][1]['silence'] == 1:
            j += 1
        dd = lambda k: ts_date(hist[k][0].replace('-', ''))
        evid = []
        if i:
            evid.append({'kind': 'wayback' if 'web.archive.org' in hist[i][1]['url'] else 'snapshot',
                         'before': hist[i - 1][1]['url'], 'url': hist[i][1]['url'],
                         'label': f'silence 0 → 1（{dd(i - 1)} → {dd(i)}）', 'date': dd(i)})
        if j + 1 < len(hist):
            evid.append({'kind': 'wayback' if 'web.archive.org' in hist[j + 1][1]['url'] else 'snapshot',
                         'before': hist[j][1]['url'], 'url': hist[j + 1][1]['url'],
                         'label': f'silence 1 → 0（{dd(j)} → {dd(j + 1)}）', 'date': dd(j + 1)})
        add({'id': f'ev-silence-{dd(i)}', 'type': 'ban', 'confidence': 'confirmed' if evid else 'pending',
             'start': dd(i), 'end': dd(j + 1) if j + 1 < len(hist) else None,
             'title': 'B站账号禁言（接口 silence=1）', 'reason': None,
             'summary': f'acc/info 接口在 {dd(i)} 至 {dd(j)} 的 {j - i + 1} 个快照里返回 silence=1。'
                        f"真实开始时间在 {dd(i - 1) if i else '?'} 与 {dd(i)} 之间，"
                        + (f'结束时间在 {dd(j)} 与 {dd(j + 1)} 之间。' if j + 1 < len(hist) else '目前还没看到解除。'),
             'affected_episodes': [], 'evidence': evid, 'detected_by': 'auto'})
        i = j + 1

    # 5) 逾期未更新 → pending
    if bili_dates:
        last = bili_dates[-1]
        iv = [days(a, b) for a, b in zip(bili_dates[-21:], bili_dates[-20:])]
        overdue = days(last, now.date().isoformat())
        if iv and overdue > max(3 * statistics.median(iv), 10) and not any(e['end'] is None and e['type'] != 'takedown' for e in events):
            add({'id': f'ev-{last[:7]}-open', 'type': 'hiatus', 'confidence': 'pending', 'start': last, 'end': None,
                 'title': f'B站已 {overdue} 天未更新', 'reason': None,
                 'summary': '超过近期中位间隔 3 倍且超过 10 天，原因未知。', 'affected_episodes': [],
                 'evidence': [], 'detected_by': 'auto'})

    # 5b) 粉丝文稿库刚改了下架合集 / 停更提示 → pending，等人看一眼
    # shortcut: 只看最近 14 天的改动，不做“已处理”标记；要长期留着就写进 manual_events.json
    for ch in load('archive_changes.json', []):
        if not (ch['banned_added'] or ch['banned_removed'] or ch['notes_added'] or ch['notes_removed']):
            continue
        if days(ch['at'][:10], now.date().isoformat()) > 14:
            continue
        what = ([f"下架合集新增第{'、'.join(str(b['no']) for b in ch['banned_added'])}期"] if ch['banned_added'] else []) + \
               ([f"下架合集移除第{'、'.join(str(b['no']) for b in ch['banned_removed'])}期"] if ch['banned_removed'] else []) + \
               [f"新停更提示：{n['text']}" for n in ch['notes_added']] + \
               [f"停更提示被删：{n['text']}" for n in ch['notes_removed']]
        add({'id': f"ev-archive-{ch['at'][:10]}", 'type': 'takedown' if ch['banned_added'] and not ch['notes_added'] else 'ban',
             # end=start：只是“粉丝写了新东西”，不让首页因此显示“进去了”
             'confidence': 'pending', 'start': ch['at'][:10], 'end': ch['at'][:10],
             'title': '文稿库有新记录，待核实', 'reason': None, 'summary': '；'.join(what),
             'affected_episodes': [b['no'] for b in ch['banned_added']] + [n for x in ch['notes_added'] for n in range(x['lo'], x['hi'] + 1) if float(n) in eps],
             'evidence': [{'kind': 'community', 'url': f"{ar.get('repo', '')}/compare/{ch['old']}...{ch['new']}",
                           'label': f"文稿库改动 {ch['old'][:8]}…{ch['new'][:8]}（{len(ch['files'])} 个文件）", 'date': ch['at'][:10]}],
             'detected_by': 'auto'})

    # 5c) 确认事件和重叠的推断/待定事件是同一件事 → 合并成一条，保留确认事件的 id、置信度和结束日期
    for c in [e for e in events if e['confidence'] == 'confirmed' and e['type'] != 'takedown']:
        c_end = c['end'] or '9999'
        for o in [e for e in events if e is not c and e['type'] != 'takedown' and e['confidence'] != 'confirmed'
                  and e['start'] <= c_end and c['start'] <= (e['end'] or '9999')]:
            observed = c['start']
            c['start'] = min(c['start'], o['start'])
            c['title'] = f"{o['title'].split(' ')[0]} {c['title']}" if o['title'].startswith('第') else c['title']
            c['reason'] = c['reason'] or o['reason']
            c['summary'] = (f"{o['summary']} 接口 silence=1 从 {observed} 起被观测到，起点取停更前最后一次投稿 {c['start']}。"
                            f" {c['summary']}")
            c['affected_episodes'] = sorted(set(c['affected_episodes']) | set(o['affected_episodes']))
            seen = {(x['url'], x.get('before')) for x in c['evidence']}
            c['evidence'] += [x for x in o['evidence'] if (x['url'], x.get('before')) not in seen]
            c['voluntary'] = False
            events.remove(o)

    # 5d) 编号跳过 = 粉丝黑话“放假” = 被封。文稿库写的“暑假/放假”默认也按放假（进宫）算；
    #     VOLUNTARY_BREAKS 改成 True 就恢复成“编辑部主动放假，不算进宫”
    for e in events:
        r = e.get('reason') or ''
        own = e['type'] == 'hiatus' and ('暑假' in r or ('放假' in r and '被放假' not in r))
        if own and not VOLUNTARY_BREAKS:
            e['type'] = 'ban'
            e['title'] = e['title'].replace('暑假停更', '放假（粉丝称暑假）')
            e['summary'] += ' 粉丝称暑假/放假；期间编号直接跳过，按放假（被封）计。'
        e.setdefault('voluntary', bool(own and VOLUNTARY_BREAKS))

    # 6) 手工事件：同 id 覆盖自动事件；只有带 before 的证据才算 confirmed
    for m in load('manual_events.json', []):
        events[:] = [e for e in events if e['id'] != m['id']]
        conf = 'confirmed' if any('before' in x for x in m.get('evidence', [])) else m.get('confidence', 'inferred')
        events.append({'detected_by': 'manual', 'updated_at': now_s, **m,
                       'confidence': 'inferred' if conf == 'confirmed' and not any('before' in x for x in m.get('evidence', [])) else conf})

    # 下架事件涉及的期：B站视频视为已没，状态按其他来源重算（协调方定的规则）
    gone = {float(n): ev for ev in events if ev['type'] == 'takedown' for n in ev['affected_episodes']}
    gone.update({n: None for n in banned if n in eps and n not in gone})  # 下架合集里没日期、出不了事件的
    for n, ev in gone.items():
        e = eps[n]
        for s in e['sources']:
            if s['kind'] == 'bilibili':
                s['alive'] = False
        alive = {s['kind'] for s in e['sources'] if s['alive'] and s['kind'] != 'bilibili'}
        e['status'] = ('mirrored' if alive & {'youtube', 'wayback', 'podcast', 'other'} else
                       'transcript_only' if 'transcript' in alive else 'lost')
        e['event_id'] = ev and ev['id']
        e['removed_at'] = ev and (ev['end'] or ev['start'])

    for ev in events:
        ev.pop('_range', None)
        assert ev['confidence'] != 'confirmed' or any('before' in x for x in ev['evidence']), ev['id']
        if ev['type'] != 'takedown':
            for n in ev['affected_episodes']:
                if eps[float(n)]['event_id'] is None:
                    eps[float(n)]['event_id'] = ev['id']
    events.sort(key=lambda e: (e['start'], e['id']))

    acc = (snap.get('acc_info') or {}).get('data') or {}
    stat = (snap.get('relation_stat') or {}).get('data') or {}
    lastv = max(blist, key=lambda v: v['pubdate'], default=None)
    m = lastv and EP.search(lastv['title'])
    status = {'schema': 1, 'last_check': checked, 'check_interval_hours': 6,
              'account': {'mid': MID, 'name': acc.get('name'), 'silence': acc.get('silence'), 'sign': acc.get('sign'),
                          'follower': stat.get('follower')},
              'last_upload': lastv and {'bvid': lastv['bvid'], 'date': bj_date(lastv['pubdate']),
                                        'episode_no': num(float(m.group(1))) if m else None},
              'open_event_id': next((e['id'] for e in reversed(events) if e['end'] is None and e['type'] != 'takedown'), None)}
    return status, [eps[n] for n in sorted(eps)], events


def write(status, episodes, events):
    for name, obj in (('status.json', status), ('episodes.json', episodes), ('events.json', events)):
        (D / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    assert gaps(['2024-01-0%d' % i for i in range(1, 8)] + ['2024-02-01']) == [('2024-01-07', '2024-02-01', 25)]
    assert flip([{'state': 'alive'}, {'state': None}, {'state': 'gone'}]) == ({'state': 'alive'}, {'state': 'gone'})
    assert pick_date(None, '7242671803528086073', [], []) == ('2023-06-09', 'xigua_id')
    _yt = [{'date': '2025-11-10'}]
    assert pick_date(None, None, [], _yt, sp='2025-11-04', n=974) == ('2025-11-04', 'transcript_spoken')
    _yt = [{'date': '2025-11-10', 'channel_name': '睡前消息'}]
    assert pick_date(None, None, [], _yt, sp='2025-11-04', n=500) == ('2025-11-10', 'youtube_upload')
    assert pick_date(None, None, [], [{'date': '2021-11-15', 'channel_name': '文稿库引用'}], sp='2021-11-14', n=353) == ('2021-11-14', 'transcript_spoken')
    s, eps, evs = build()
    write(s, eps, evs)
    from collections import Counter
    print('期号状态:', dict(Counter(e['status'] for e in eps)))
    for e in evs:
        print(f"  {e['id']:<22} {e['type']:<8} {e['confidence']:<9} {e['start']} → {e['end']}  {e['title']}")
