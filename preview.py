#!/usr/bin/env python3
"""Hugo → 微信公众号 预览服务器 (FastAPI)

启动: python3 preview.py [--port 3333] [--content-dir /path/to/hugo/content/posts]
"""

import asyncio
import json
import re
import base64
import html as html_mod
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from convert import strip_frontmatter, clean_hugo, svg_to_img

app = FastAPI(title="hugo2wechat preview")
app.state.content_dir = Path.cwd() / "content" / "posts"
app.state.api_base = "http://localhost:3456"
app.state.svg_to_image = True

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30))
    return _client


async def proxy_api(path: str, method: str = "GET", body: dict | None = None):
    """代理请求到 markdown2wechat，连接池复用"""
    c = await get_client()
    try:
        if method == "POST":
            resp = await c.post(f"{app.state.api_base}{path}", json=body or {})
        else:
            resp = await c.get(f"{app.state.api_base}{path}")
        return resp.json(), resp.status_code
    except Exception as e:
        return {"error": str(e)}, 502


def find_post(slug: str) -> Path | None:
    content_dir = app.state.content_dir
    for d in content_dir.iterdir():
        if d.is_dir() and d.name == slug:
            return d / "index.md"
        if d.is_file() and d.suffix == ".md" and d.stem == slug:
            return d
    return None


def read_post(slug: str) -> tuple[str, str, str] | None:
    fp = find_post(slug)
    if not fp or not fp.exists():
        return None
    text = fp.read_text(encoding="utf-8")
    meta, body = strip_frontmatter(text)
    return meta.get("title", slug), meta.get("author", "whitefirer"), body


async def render_markdown(markdown: str, theme: str | None = None) -> str:
    data, code = await proxy_api(
        "/api/convert", "POST",
        {"markdown": markdown, **(dict(theme=theme) if theme else {})}
    )
    if data.get("success"):
        return data["html"]
    raise RuntimeError(data.get("error", "render failed"))


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
footer{{text-align:center;padding:20px 16px 40px;color:var(--muted);font-size:13px;line-height:1.8}}
footer a{{color:var(--accent);text-decoration:none}}
</style>
</head>
<body>
<div class="toolbar">
  <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 72 72" style="flex-shrink:0"><g fill="none" fill-rule="evenodd"><path stroke="#000" stroke-opacity=".1" stroke-width=".5" d="M20.3.5h30.3c6.9 0 9.4.7 12 2a14 14 0 0 1 5.8 5.9c1.4 2.5 2.1 5 2.1 12v30.2c0 7-.7 9.5-2.1 12a14 14 0 0 1-5.8 5.8c-2.6 1.4-5.1 2.1-12 2.1H20.2c-6.9 0-9.4-.7-12-2.1a14 14 0 0 1-5.8-5.8C1.1 60.1.4 57.5.4 50.6V20.4c0-7 .7-9.5 2.1-12a14 14 0 0 1 5.8-5.9c2.6-1.3 5.1-2 12-2z"/><path fill="#07C160" d="M51.8 20.5c-2.6-5.4-9.2-9.9-16.6-9.9-3.9 0-9.8 1.3-14.3 6.7-3 3.6-4 7.8-3.3 12 .4 2.9 2 6.7 4.3 9 .9-6 4.1-10.8 8.3-14.3 7.6-5.8 15.7-5.5 21.6-3.5"/><path fill="#07C160" d="M57.7 29.6c-4.7-6-12.7-7.7-20-5 .2 0 .5.1.7.2 10.8 3.7 16.6 15.3 13 26a20.2 20.2 0 0 1-4.4 7.4c2.3-.6 4.7-1.5 6.7-3.1 8.2-6.3 9.8-17.9 4-25.5"/><path fill="#07C160" d="M35.2 48.8c-1.6 0-3.2-.2-4.7-.5a2.3 2.3 0 0 0-.6 0c-.4 0-.8.2-1.2.5l-5 3.2c-.2 0-.3.1-.5.1a.8.8 0 0 1-.8-.7c0-.2 0-.4.1-.6l.9-4c0-.2 0-.3 0-.5a1.6 1.6 0 0 0-.7-1.3C17 41 13.4 35.4 12.6 29.6c-1.4 2.1-2 3.7-2.7 6.2-2.6 9 3 19.8 12.3 22.8 10.6 3.5 20.7-.4 24.2-9.4.4-1.1.9-3 1-4.5-3.7 2.7-7.7 3.9-12.6 3.9"/></g></svg>
  <h2>{title}</h2>
  <span class="badge">预览</span>
  <select id="themeSelect" onchange="switchTheme(this.value)">{theme_options}</select>
  <div class="actions">
    <a href="https://github.com/whitefirer/hugo2wechat" target="_blank" class="btn" title="GitHub" style="display:inline-flex;align-items:center;gap:4px">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg> hugo2wechat</a>
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
<footer>© whitefirer · <a href="https://github.com/whitefirer/hugo2wechat">hugo2wechat</a> on GitHub</footer>
<script>
const SLUG = '{slug}';
let copyHTMLData = '';
const themeNames = {theme_names};
const defaultTheme = '{default_theme}';

async function render(theme) {{
  document.getElementById('phoneContent').innerHTML = '<div class="loading">渲染中...</div>';
  try {{
    const url = '/api/render/' + SLUG + (theme ? '?theme=' + encodeURIComponent(theme) : '');
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.success) {{
      document.getElementById('phoneContent').innerHTML = data.html;
      copyHTMLData = data.copy_html || data.html;
    }} else {{
      document.getElementById('phoneContent').innerHTML = '<div class="error">渲染失败: ' + (data.error || '未知') + '</div>';
    }}
  }} catch(e) {{
    document.getElementById('phoneContent').innerHTML = '<div class="error">连接失败: ' + e.message + '</div>';
  }}
}}

function switchTheme(theme) {{ render(theme); }}

function fallbackCopy(btn) {{
  navigator.clipboard.writeText(document.getElementById('phoneContent').innerText).then(() => {{
    btn.textContent = '✅ 已复制(纯文本)';
    setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
  }}).catch(() => alert('复制失败，请手动全选复制'));
}}

function copyHTML(btn) {{
  if (!copyHTMLData) return;
  try {{
    const blob = new Blob([copyHTMLData], {{type: 'text/html'}});
    navigator.clipboard.write([new ClipboardItem({{'text/html': blob}})]).then(() => {{
      btn.textContent = '✅ 已复制';
      setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
    }}).catch(() => fallbackCopy(btn));
  }} catch(e) {{ fallbackCopy(btn); }}
}}

render(defaultTheme);
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    posts = []
    cd = app.state.content_dir
    for d in sorted(cd.iterdir(), reverse=True):
        if d.is_dir():
            idx = d / "index.md"
            if idx.exists():
                meta, _ = strip_frontmatter(idx.read_text(encoding="utf-8"))
                posts.append({
                    "slug": d.name,
                    "title": meta.get("title", d.name),
                    "date": meta.get("date", ""),
                })
        elif d.suffix == ".md":
            meta, _ = strip_frontmatter(d.read_text(encoding="utf-8"))
            posts.append({
                "slug": d.stem,
                "title": meta.get("title", d.stem),
                "date": meta.get("date", ""),
            })
    links = "\n".join(
        f'<li><a href="/preview/{p["slug"]}">{html_mod.escape(p["title"])}</a></li>'
        for p in posts
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>微信预览</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e4e4ee}}h1{{font-size:20px}}a{{color:#4a90d9;text-decoration:none;line-height:1.8}}a:hover{{text-decoration:underline}}</style></head>
<body><h1>📱 文章列表</h1><ul>{links}</ul></body></html>"""


@app.get("/preview/{slug}", response_class=HTMLResponse)
async def serve_preview(slug: str):
    post = read_post(slug)
    if not post:
        raise HTTPException(404, "文章不存在")
    title, _, _ = post

    # Fetch themes
    themes_data, _ = await proxy_api("/api/themes")
    theme_names = []
    default_theme = "兰青"
    if isinstance(themes_data, dict):
        theme_names = themes_data.get("themes", [])
        default_theme = themes_data.get("defaultTheme", theme_names[0] if theme_names else "")

    theme_opts = "\n".join(
        f'<option value="{html_mod.escape(t)}"{" selected" if t == default_theme else ""}>{html_mod.escape(t)}</option>'
        for t in theme_names
    )

    return PHONE_FRAME.format(
        title=html_mod.escape(title),
        slug=slug,
        theme_options=theme_opts,
        theme_names=json.dumps(theme_names, ensure_ascii=False),
        default_theme=html_mod.escape(default_theme),
    )


@app.get("/api/render/{slug}")
async def serve_render(slug: str, theme: str | None = Query(None)):
    post = read_post(slug)
    if not post:
        return JSONResponse({"success": False, "error": "文章不存在"}, 404)

    title, _, body = post
    body = clean_hugo(body)

    # Render with title for display
    md_with_title = f"# {title}\n\n{body}"
    try:
        display_html = await render_markdown(md_with_title, theme)
        # Render body-only for copy
        copy_html = await render_markdown(body, theme)
    except RuntimeError as e:
        return JSONResponse({"success": False, "error": str(e)}, 500)

    if app.state.svg_to_image:
        # Run in thread to avoid blocking (svg_to_img is CPU-bound regex)
        loop = asyncio.get_running_loop()
        display_html = await loop.run_in_executor(None, svg_to_img, display_html)
        copy_html = await loop.run_in_executor(None, svg_to_img, copy_html)

    return {"success": True, "html": display_html, "copy_html": copy_html}


@app.get("/api/themes")
async def serve_themes():
    data, code = await proxy_api("/api/themes")
    return JSONResponse(data, code)


# ── Main ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hugo → 微信 预览服务器")
    parser.add_argument("-c", "--config", help="配置文件 (YAML/JSON)")
    parser.add_argument("--port", type=int, default=3333)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--content-dir", default=str(Path.cwd() / "content" / "posts"))
    parser.add_argument("--api-base", default="http://localhost:3456")
    parser.add_argument("--no-svg-to-image", action="store_true", help="禁用 SVG→图片 转换")
    args = parser.parse_args()

    app.state.content_dir = Path(args.content_dir)
    app.state.api_base = args.api_base
    app.state.svg_to_image = not args.no_svg_to_image

    if args.config:
        from convert import load_config
        cfg = load_config(args.config)
        if "content_dir" in cfg:
            app.state.content_dir = Path(cfg["content_dir"])
        if "api_base" in cfg:
            app.state.api_base = cfg["api_base"]
        if "no_svg_to_image" in cfg:
            app.state.svg_to_image = not cfg["no_svg_to_image"]

    print(f"📱 微信预览服务器 (FastAPI)")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   内容: {app.state.content_dir}")
    print(f"   API:  {app.state.api_base}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
