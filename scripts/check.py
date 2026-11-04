"""定时任务入口：抓取 → 与上一个快照对比 → 重算事件 → 输出中文摘要。

用法：python3 scripts/check.py [--skip-youtube] [--skip-archive]
站点是纯静态的（site/ 直接读 data/*.json），所以“重建站点”就是重写这几个 JSON。
"""
import json, pathlib, subprocess, sys
import datetime as dt
import analyze, fetch_archive, fetch_bilibili, fetch_podcast, fetch_youtube, bili

D = analyze.D
BJ = analyze.BJ


def main(argv):
    now = dt.datetime.now(BJ)
    olds = [json.loads(f.read_text()) | {'_path': f'data/snapshots/{f.name}'} for f in sorted((D / 'snapshots').glob('*.json'))]
    prev = next((o for o in reversed(olds) if o.get('complete')), None)  # 和上一个“完整”快照比
    lines = [f'【老马封禁追踪】{now:%Y-%m-%d %H:%M} 检查']

    # 第一步：粉丝文稿库（主数据源：期号/标题/bvid/YouTube/西瓜链接、下架合集、停更提示）
    if '--skip-archive' not in argv:
        r = subprocess.run([sys.executable, str(pathlib.Path(fetch_archive.__file__))], capture_output=True, text=True)
        lines += [l.strip() for l in r.stdout.splitlines() if '[文稿库]' in l] or ['文稿库没有新改动']
        if r.returncode:
            lines.append(f"⚠️ 文稿库更新失败：{(r.stderr.strip().splitlines() or ['?'])[-1]}")

    snap, norm = fetch_bilibili.fetch()
    acc = (snap['acc_info'].get('data') or {})
    if bili.risk_log:
        lines.append(f'⚠️ B站风控 {len(bili.risk_log)} 次：{bili.risk_log[-1]}')
    if not snap['complete']:
        lines.append(f"⚠️ B站列表不完整（{len(snap['vlist'])}/{snap['expected_count']}），本次不判定下架")

    state = analyze.load('state.json', {})
    removals = analyze.load('removals.json', {})
    cur_path = f"data/snapshots/{snap['fetched_at']}.json"
    if prev and snap['complete']:
        old = {v['bvid']: v['title'] for v in prev['vlist']}
        new = {v['bvid'] for v in snap['vlist']}
        gone = [b for b in old if b not in new]
        for b in gone:
            removals.setdefault(b, {'at': now.isoformat(timespec='seconds'), 'before': prev['_path'], 'after': cur_path})
        lines += [f'🗑 消失：{b} {old[b]}' for b in gone] or ['没有视频消失']
        added = [v['title'] for v in snap['vlist'] if v['bvid'] not in old]
        lines += [f'🆕 新视频：{t}' for t in added]
    elif not prev:
        lines.append('还没有完整的旧快照可对比')
    if 'silence' in acc:
        state.setdefault('silence_log', []).append([snap['fetched_at'], acc['silence'], cur_path])
        if acc['silence'] and not state.get('silence_since'):
            state['silence_since'] = now.isoformat(timespec='seconds')
            state.pop('silence_until', None)
            lines.append('🚫 账号变为禁言状态（silence=1）')
        elif not acc['silence'] and state.get('silence_since') and not state.get('silence_until'):
            state['silence_until'] = now.date().isoformat()
            lines.append('✅ 账号禁言解除')
    else:
        lines.append(f"⚠️ 账号信息没拿到：code={snap['acc_info'].get('code')} {snap['acc_info'].get('message')}")
    state['last_check'] = now.isoformat(timespec='seconds')
    (D / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=1))
    (D / 'removals.json').write_text(json.dumps(removals, ensure_ascii=False, indent=1))

    if '--skip-youtube' not in argv:
        yt, ok = fetch_youtube.fetch(limit=100)
        lines.append(f'YouTube {len(yt)} 条' + ('' if ok else '（抓取失败，沿用旧数据）'))
    try:
        lines.append(f'蜻蜓FM {len(fetch_podcast.fetch())} 条')
    except Exception as e:
        lines.append(f'⚠️ 蜻蜓FM 抓取失败：{e}')

    status, eps, evs = analyze.build(now)
    analyze.write(status, eps, evs)
    lu = status['last_upload']
    lines.append(f"账号 silence={status['account']['silence']}，最近投稿 {lu and lu['date']}（第{lu and lu['episode_no']}期）")
    if status['open_event_id']:
        ev = next(e for e in evs if e['id'] == status['open_event_id'])
        lines.append(f"⏳ 进行中事件：{ev['title']}（{ev['confidence']}）")
    from collections import Counter
    lines.append('期号状态：' + '，'.join(f'{k} {v}' for k, v in Counter(e['status'] for e in eps).items()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1:])
