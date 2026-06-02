#!/usr/bin/env python3
"""Hugo → 微信公众号 预览服务器

启动: python3 preview.py [--port 8090] [--content-dir /path/to/hugo/content/posts]
"""

import http.server
import json
import urllib.request
import urllib.parse
import sys
import re
import html as html_mod
from pathlib import Path

from convert import strip_frontmatter, clean_hugo

DEFAULT_CONTENT_DIR = Path.cwd() / "content" / "posts"

PHONE_FRAME = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>微信预览 — {title}</title>
<style>
:root{{--bg:#1a1a2e;--panel:#16213e;--ink:#e4e4ee;--muted:#7c7c94;--accent:#0f0}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh}}
.toolbar{{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--panel);border-bottom:1px solid #2a2a4a}}
.toolbar h2{{font-size:15px;font-weight:600;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.toolbar select{{padding:6px 10px;border-radius:6px;border:1px solid #3a3a5a;background:#1a1a2e;color:var(--ink);font-size:13px;cursor:pointer}}
.toolbar select:focus{{outline:none;border-color:var(--accent)}}
.main{{display:flex;justify-content:center;padding:24px 16px 40px}}
.phone{{width:375px;min-height:667px;background:#fff;border-radius:28px;overflow:hidden;box-shadow:0 0 0 3px #333,0 0 0 6px #222,0 0 0 8px #444,0 12px 40px rgba(0,0,0,.5);position:relative}}
.phone-notch{{height:28px;background:#111;display:flex;justify-content:center;align-items:flex-end;padding-bottom:4px}}
.phone-notch::after{{content:'';width:80px;height:4px;background:#333;border-radius:2px}}
.phone-content{{padding:0 14px 24px;min-height:600px;background:#fff;color:#3f3f3f;overflow-y:auto;max-height:calc(100vh - 160px)}}
.phone-content * {{max-width:100%!important;word-break:break-word}}
.loading{{display:flex;align-items:center;justify-content:center;height:400px;color:#999;font-size:14px}}
.error{{color:#e94560;padding:20px;text-align:center}}
.badge{{font-size:11px;padding:3px 8px;border-radius:10px;background:#0f02;color:var(--accent);border:1px solid #0f03}}
.actions{{display:flex;gap:8px;align-items:center}}
.btn{{padding:6px 12px;border-radius:6px;border:1px solid #3a3a5a;background:#1a1a2e;color:var(--ink);font-size:12px;cursor:pointer;text-decoration:none;white-space:nowrap}}
.btn:hover{{border-color:var(--accent)}}
</style>
</head>
<body>
<div class="toolbar">
  <h2>📱 {title}</h2>
  <span class="badge">预览</span>
  <select id="themeSelect" onchange="switchTheme(this.value)">{themeOptions}</select>
  <div class="actions">
    <button class="btn" onclick="copyHTML()">📋 复制 HTML</button>
  </div>
</div>
<div class="main">
  <div class="phone">
    <div class="phone-notch"></div>
    <div class="phone-content" id="phoneContent">
      <div class="loading">加载中...</div>
    </div>
  </div>
</div>
<script>
const SLUG = '{slug}';
let currentHTML = '';
let themes = {themeListJson};

async function render(theme) {{
  document.getElementById('phoneContent').innerHTML = '<div class="loading">渲染中...</div>';
  try {{
    const resp = await fetch('/api/render/' + SLUG + (theme ? '?theme=' + encodeURIComponent(theme) : ''));
    const data = await resp.json();
    if (data.success) {{
      document.getElementById('phoneContent').innerHTML = data.html;
      currentHTML = data.html;
    }} else {{
      document.getElementById('phoneContent').innerHTML = '<div class="error">渲染失败: ' + (data.error || '未知错误') + '</div>';
    }}
  }} catch(e) {{
    document.getElementById('phoneContent').innerHTML = '<div class="error">连接失败，请确认 markdown2wechat 已启动 (port 3456)<br><small>' + e.message + '</small></div>';
  }}
}}

function switchTheme(theme) {{
  render(theme);
}}

function copyHTML() {{
  if (!currentHTML) return;
  navigator.clipboard.write([
    new ClipboardItem({{'text/html': new Blob([currentHTML], {{type: 'text/html'}}),
                        'text/plain': new Blob([document.getElementById('phoneContent').innerText], {{type: 'text/plain'}})}})
  ]).then(() => {{
    const btn = event.target;
    btn.textContent = '✅ 已复制';
    setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
  }}).catch(() => alert('复制失败，请手动选择复制'));
}}

render('{initialTheme}');
</script>
</body>
</html>"""


class PreviewHandler(http.server.BaseHTTPRequestHandler):
    content_dir = DEFAULT_CONTENT_DIR
    api_base = "http://localhost:3456"

    def log_message(self, fmt, *args):
        print(f"  {args[0]}" if args else fmt)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html_str, status=200):
        body = html_str.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def _proxy_api(self, path, method='GET', body=None):
        url = f"{self.api_base}{path}"
        req = urllib.request.Request(url, data=body,
            headers={'Content-Type': 'application/json'} if body else {})
        req.get_method = lambda: method
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), resp.status
        except Exception as e:
            return {'error': str(e)}, 502

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # /preview/{slug} → phone frame page
        m = re.match(r'^/preview/([a-zA-Z0-9_-]+)$', parsed.path)
        if m:
            slug = m.group(1)
            self._serve_preview_page(slug)
            return

        # /api/render/{slug} → rendered HTML body
        m = re.match(r'^/api/render/([a-zA-Z0-9_-]+)$', parsed.path)
        if m:
            slug = m.group(1)
            qs = urllib.parse.parse_qs(parsed.query)
            theme = qs.get('theme', [None])[0]
            self._serve_render(slug, theme)
            return

        # /api/themes → proxy
        if parsed.path == '/api/themes':
            data, code = self._proxy_api('/api/themes')
            self._json(data, code)
            return

        # / → list available posts
        if parsed.path == '/':
            self._serve_index()
            return

        self.send_error(404)

    def _find_post(self, slug: str) -> Path | None:
        for d in self.content_dir.iterdir():
            if d.is_dir() and d.name == slug:
                return d / 'index.md'
            if d.is_file() and d.suffix == '.md' and d.stem == slug:
                return d
        return None

    def _read_post(self, slug: str) -> tuple[str, str, str] | None:
        """Return (title, author, cleaned_markdown) or None"""
        filepath = self._find_post(slug)
        if not filepath or not filepath.exists():
            return None
        text = filepath.read_text(encoding='utf-8')
        meta, body = strip_frontmatter(text)
        title = meta.get('title', slug)
        author = meta.get('author', 'whitefirer')
        body = clean_hugo(body)
        return title, author, body

    def _serve_preview_page(self, slug: str):
        result = self._read_post(slug)
        if not result:
            self._html(f"<h1>404</h1><p>文章不存在: {slug}</p>", 404)
            return
        title, author, _ = result

        # Fetch themes from markdown2wechat
        themes_data, _ = self._proxy_api('/api/themes')
        theme_names = themes_data.get('themes', []) if isinstance(themes_data, dict) else themes_data if isinstance(themes_data, list) else []
        default_theme = themes_data.get('defaultTheme', theme_names[0] if theme_names else '') if isinstance(themes_data, dict) else (theme_names[0] if theme_names else '')

        # Build theme options — the API returns simple name strings
        theme_opts = '\n'.join(
            f'<option value="{html_mod.escape(t)}"{" selected" if t == default_theme else ""}>{html_mod.escape(t)}</option>'
            for t in theme_names
        )

        page = PHONE_FRAME.format(
            title=html_mod.escape(title),
            slug=slug,
            themeOptions=theme_opts,
            initialTheme=default_theme,
            themeListJson=json.dumps(theme_names, ensure_ascii=False),
        )
        self._html(page)

    def _serve_render(self, slug: str, theme: str | None):
        result = self._read_post(slug)
        if not result:
            self._json({'success': False, 'error': '文章不存在'}, 404)
            return

        title, author, body = result
        payload = json.dumps({
            'markdown': body,
            **(dict(theme=theme) if theme else {})
        }).encode()

        data, code = self._proxy_api('/api/convert', method='POST', body=payload)
        if data.get('success'):
            self._json({'success': True, 'html': data['html']})
        else:
            self._json({'success': False, 'error': data.get('error', '渲染失败')}, code)

    def _serve_index(self):
        posts = []
        for d in sorted(self.content_dir.iterdir(), reverse=True):
            if d.is_dir():
                idx = d / 'index.md'
                if idx.exists():
                    meta, _ = strip_frontmatter(idx.read_text(encoding='utf-8'))
                    posts.append({
                        'slug': d.name,
                        'title': meta.get('title', d.name),
                        'date': meta.get('date', ''),
                        'draft': meta.get('draft', 'false').lower() == 'true',
                    })
            elif d.suffix == '.md':
                meta, _ = strip_frontmatter(d.read_text(encoding='utf-8'))
                posts.append({
                    'slug': d.stem,
                    'title': meta.get('title', d.stem),
                    'date': meta.get('date', ''),
                    'draft': meta.get('draft', 'false').lower() == 'true',
                })

        links = '\n'.join(
            f'<li><a href="/preview/{p["slug"]}">{html_mod.escape(p["title"])}</a>'
            f'{" <small style=color:#888>(草稿)</small>" if p["draft"] else ""}</li>'
            for p in posts if not p['draft'] or True  # show all
        )
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>微信预览</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e4e4ee}}
h1{{font-size:20px}} a{{color:#4a90d9;text-decoration:none;line-height:1.8}}
a:hover{{text-decoration:underline}} small{{font-size:12px}}
</style></head>
<body><h1>📱 文章列表</h1><ul>{links}</ul></body></html>"""
        self._html(page)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Hugo → 微信 预览服务器')
    parser.add_argument('-c', '--config', help='配置文件 (YAML/JSON)')
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--content-dir', default=str(DEFAULT_CONTENT_DIR))
    parser.add_argument('--api-base', default="http://localhost:3456")
    parser.add_argument('--theme', help='默认主题')
    args = parser.parse_args()

    # Config file overrides defaults, CLI flags override config
    if args.config:
        from convert import load_config
        cfg = load_config(args.config)
        if not args.port and 'port' in cfg:
            args.port = cfg['port']
        if args.content_dir == str(DEFAULT_CONTENT_DIR) and 'content_dir' in cfg:
            args.content_dir = cfg['content_dir']
        if args.api_base == "http://localhost:3456" and 'api_base' in cfg:
            args.api_base = cfg['api_base']

    PreviewHandler.content_dir = Path(args.content_dir)
    PreviewHandler.api_base = args.api_base

    if not PreviewHandler.content_dir.exists():
        print(f"⚠️  内容目录不存在: {args.content_dir}")

    server = http.server.HTTPServer(('0.0.0.0', args.port), PreviewHandler)
    print(f"📱 微信预览服务器")
    print(f"   地址: http://localhost:{args.port}")
    print(f"   内容: {args.content_dir}")
    print(f"   API:  {args.api_base}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")
        server.shutdown()


if __name__ == '__main__':
    main()
