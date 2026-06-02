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

from convert import strip_frontmatter, clean_hugo, svg_to_img

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
  <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 72 72" style="flex-shrink:0"><g fill="none" fill-rule="evenodd"><path stroke="#000" stroke-opacity=".1" stroke-width=".5" d="M20.3.5h30.3c6.9 0 9.4.7 12 2a14 14 0 0 1 5.8 5.9c1.4 2.5 2.1 5 2.1 12v30.2c0 7-.7 9.5-2.1 12a14 14 0 0 1-5.8 5.8c-2.6 1.4-5.1 2.1-12 2.1H20.2c-6.9 0-9.4-.7-12-2.1a14 14 0 0 1-5.8-5.8C1.1 60.1.4 57.5.4 50.6V20.4c0-7 .7-9.5 2.1-12a14 14 0 0 1 5.8-5.9c2.6-1.3 5.1-2 12-2z"/><path fill="#07C160" d="M51.8 20.5c-2.6-5.4-9.2-9.9-16.6-9.9-3.9 0-9.8 1.3-14.3 6.7-3 3.6-4 7.8-3.3 12 .4 2.9 2 6.7 4.3 9 .9-6 4.1-10.8 8.3-14.3 7.6-5.8 15.7-5.5 21.6-3.5"/><path fill="#07C160" d="M57.7 29.6c-4.7-6-12.7-7.7-20-5 .2 0 .5.1.7.2 10.8 3.7 16.6 15.3 13 26a20.2 20.2 0 0 1-4.4 7.4c2.3-.6 4.7-1.5 6.7-3.1 8.2-6.3 9.8-17.9 4-25.5"/><path fill="#07C160" d="M35.2 48.8c-1.6 0-3.2-.2-4.7-.5a2.3 2.3 0 0 0-.6 0c-.4 0-.8.2-1.2.5l-5 3.2c-.2 0-.3.1-.5.1a.8.8 0 0 1-.8-.7c0-.2 0-.4.1-.6l.9-4c0-.2 0-.3 0-.5a1.6 1.6 0 0 0-.7-1.3C17 41 13.4 35.4 12.6 29.6c-1.4 2.1-2 3.7-2.7 6.2-2.6 9 3 19.8 12.3 22.8 10.6 3.5 20.7-.4 24.2-9.4.4-1.1.9-3 1-4.5-3.7 2.7-7.7 3.9-12.6 3.9"/></g></svg>
  <h2>{title}</h2>
  <span class="badge">预览</span>
  <select id="themeSelect" onchange="switchTheme(this.value)">{themeOptions}</select>
  <div class="actions">
    <a href="https://github.com/whitefirer/hugo2wechat" target="_blank" class="btn" title="GitHub" style="display:inline-flex;align-items:center;gap:4px">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
      hugo2wechat
    </a>
    <button class="btn" onclick="copyHTML(this)">📋 复制 HTML</button>
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
<footer style="text-align:center;padding:20px 16px 40px;color:var(--muted);font-size:13px;line-height:1.8">
  © whitefirer · <a href="https://github.com/whitefirer/hugo2wechat" style="color:var(--accent);text-decoration:none">hugo2wechat</a> on GitHub
</footer>
<script>
const SLUG = '{slug}';
let copyHTMLData = '';
let themes = {themeListJson};

async function render(theme) {{
  document.getElementById('phoneContent').innerHTML = '<div class="loading">渲染中...</div>';
  try {{
    const resp = await fetch('/api/render/' + SLUG + (theme ? '?theme=' + encodeURIComponent(theme) : ''));
    const data = await resp.json();
    if (data.success) {{
      document.getElementById('phoneContent').innerHTML = data.html;
      copyHTMLData = data.copy_html || data.html;
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

function copyHTML(btn) {{
  if (!copyHTMLData) return;
  try {{
    const blob = new Blob([copyHTMLData], {{type: 'text/html'}});
    const item = new ClipboardItem({{'text/html': blob}});
    navigator.clipboard.write([item]).then(() => {{
      btn.textContent = '✅ 已复制';
      setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
    }}).catch(() => fallbackCopy(btn));
  }} catch(e) {{
    fallbackCopy(btn);
  }}
}}

function fallbackCopy(btn) {{
  // Fallback: copy as plain text
  const text = document.getElementById('phoneContent').innerText;
  navigator.clipboard.writeText(text).then(() => {{
    btn.textContent = '✅ 已复制(纯文本)';
    setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
  }}).catch(() => alert('复制失败，请手动 Ctrl+A 全选复制'));
}}

render('{initialTheme}');
</script>
</body>
</html>"""


class PreviewHandler(http.server.BaseHTTPRequestHandler):
    content_dir = DEFAULT_CONTENT_DIR
    api_base = "http://localhost:3456"
    svg_to_image = True

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
        # Render with title for preview display
        markdown_with_title = f'# {title}\n\n{body}'
        payload = json.dumps({
            'markdown': markdown_with_title,
            **(dict(theme=theme) if theme else {})
        }).encode()

        data, code = self._proxy_api('/api/convert', method='POST', body=payload)
        if data.get('success'):
            display_html = data['html']
            # Also render body-only for copy (no title, WeChat editor has its own)
            payload_body = json.dumps({
                'markdown': body,
                **(dict(theme=theme) if theme else {})
            }).encode()
            data_body, _ = self._proxy_api('/api/convert', method='POST', body=payload_body)
            copy_html = data_body.get('html', display_html) if data_body.get('success') else display_html
            # SVG → image for mobile WeChat compat
            if self.svg_to_image:
                display_html = svg_to_img(display_html)
                copy_html = svg_to_img(copy_html)
            self._json({'success': True, 'html': display_html, 'copy_html': copy_html})
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
    parser.add_argument('--port', type=int, default=3333)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--content-dir', default=str(DEFAULT_CONTENT_DIR))
    parser.add_argument('--api-base', default="http://localhost:3456")
    parser.add_argument('--theme', help='默认主题')
    parser.add_argument('--no-svg-to-image', action='store_true', help='禁用 SVG→图片 转换')
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
    PreviewHandler.svg_to_image = not args.no_svg_to_image

    # Config file can also override
    if args.config:
        if 'no_svg_to_image' in cfg:
            PreviewHandler.svg_to_image = not cfg['no_svg_to_image']

    if not PreviewHandler.content_dir.exists():
        print(f"⚠️  内容目录不存在: {args.content_dir}")

    server = http.server.HTTPServer((args.host, args.port), PreviewHandler)
    print(f"📱 微信预览服务器")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   内容: {args.content_dir}")
    print(f"   API:  {args.api_base}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 关闭")
        server.shutdown()


if __name__ == '__main__':
    main()
