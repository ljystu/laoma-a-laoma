"""本地预览：python3 scripts/serve.py [端口]，从项目根目录提供文件，禁止浏览器缓存（数据更新后刷新即见）。"""
import functools, http.server, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    print(f'http://localhost:{port}/site/')
    http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(NoCache, directory=str(ROOT))).serve_forever()
