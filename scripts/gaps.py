"""缺口盘点：播出过的期里，各字段缺多少（按年份/期号段）→ data/gaps.json，并打印表格。"""
import collections, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKS = {
    '播出日期': lambda e: e['date'],
    '精确日期': lambda e: e['date'] and not e.get('date_estimated') and not e.get('date_note'),
    'B站状态': lambda e: e['status'] != 'unknown',
    'YouTube补档': lambda e: any(s['kind'] == 'youtube' and s['alive'] for s in e['sources']),
    '任意补档': lambda e: any(s['kind'] != 'bilibili' and s['alive'] for s in e['sources']),
    '标题': lambda e: e['title'],
    'bvid': lambda e: e['bvid'],
}


def audit(eps):
    aired = [e for e in eps if e.get('aired', True)]
    bucket = lambda e: f"{int(e['no']) // 100 * 100}-{int(e['no']) // 100 * 100 + 99}"
    out = {'aired': len(aired), 'missing': {}}
    for k, ok in CHECKS.items():
        miss = [e for e in aired if not ok(e)]
        out['missing'][k] = {'total': len(miss), 'by_range': dict(sorted(collections.Counter(map(bucket, miss)).items()))}
    return out


if __name__ == '__main__':
    g = audit(json.loads((ROOT / 'data' / 'episodes.json').read_text()))
    (ROOT / 'data' / 'gaps.json').write_text(json.dumps(g, ensure_ascii=False, indent=1))
    print(f"播出过的期：{g['aired']}")
    for k, v in g['missing'].items():
        print(f"  缺{k:<8} {v['total']:>4}   " + ' '.join(f'{r}:{n}' for r, n in v['by_range'].items()))
