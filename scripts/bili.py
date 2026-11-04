"""B站 API 小客户端：buvid3 cookie + WBI 签名 + 风控退避。仅用标准库。"""
import hashlib, http.cookiejar, json, time, urllib.error, urllib.parse, urllib.request

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')
MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
         33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
         61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
         36, 20, 34, 44, 52]
RISK_CODES = (-352, -412, -799)
risk_log = []  # 每次遇到风控记一条，供调用方报告


def mixin_key(img_key, sub_key):
    s = img_key + sub_key
    return ''.join(s[i] for i in MIXIN)[:32]


def sign(params, mkey, wts=None):
    p = dict(params, wts=int(wts if wts is not None else time.time()))
    p = {k: ''.join(c for c in str(v) if c not in "!'()*") for k, v in sorted(p.items())}
    q = urllib.parse.urlencode(p)
    p['w_rid'] = hashlib.md5((q + mkey).encode()).hexdigest()
    return p


class Client:
    def __init__(self, referer='https://www.bilibili.com'):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.h = {'User-Agent': UA, 'Referer': referer, 'Origin': 'https://www.bilibili.com'}
        self.raw('https://www.bilibili.com')  # 拿 buvid3
        self.mkey = None

    def raw(self, url, timeout=20):
        return self.op.open(urllib.request.Request(url, headers=self.h), timeout=timeout).read()

    def get(self, url, params=None, wbi=False, tries=5):
        for i in range(tries):
            p = params or {}
            if wbi:
                p = sign(p, self.wbi_key())
            try:
                d = json.loads(self.raw(url + ('?' + urllib.parse.urlencode(p) if p else '')))
            except urllib.error.HTTPError as e:
                d = {'code': -e.code, 'message': f'HTTP {e.code}'}
            except ValueError:  # 风控时会返回 HTML 页
                d = {'code': -412, 'message': 'non-json (risk page)'}
            if d.get('code') not in RISK_CODES:
                return d
            wait = 30 * 2 ** i
            risk_log.append(f"{url} code={d.get('code')} {d.get('message')} → 等 {wait}s 重试")
            print('  [风控]', risk_log[-1])
            time.sleep(wait)
        return d

    def wbi_key(self):
        if not self.mkey:
            d = json.loads(self.raw('https://api.bilibili.com/x/web-interface/nav'))
            w = d['data']['wbi_img']
            k = lambda u: u.rsplit('/', 1)[1].split('.')[0]
            self.mkey = mixin_key(k(w['img_url']), k(w['sub_url']))
        return self.mkey


if __name__ == '__main__':
    # 自检：B站文档公开的示例（bilibili-API-collect）
    mk = mixin_key('7cd084941338484aae1ad9425b84077c', '4932caff0ff746eab6f01bf08b70ac45')
    assert mk == 'ea1db124af3c7062474693fa704f4ff8', mk
    s = sign({'foo': '114', 'bar': '514', 'zab': 1919810}, mk, wts=1702204169)
    assert s['w_rid'] == '8f6f2b5b3d485fe1886cec6a0be8c5d4', s['w_rid']
    print('WBI 签名自检通过')
