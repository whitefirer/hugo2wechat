#!/usr/bin/env python3
"""Hugo → 微信公众号 预览服务器 (FastAPI)

启动: python3 preview.py [--port 3333] [--content-dir /path/to/hugo/content/posts]
"""

import asyncio
import json
import os
import re
import base64
import mimetypes
import subprocess
import html as html_mod
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from convert import strip_frontmatter, clean_hugo, svg_to_img

app = FastAPI(title="hugo2wechat preview")
app.state.content_dir = Path.cwd() / "content" / "posts"
app.state.api_base = "http://localhost:3456"
app.state.svg_to_image = True
app.state.base_url = 'https://whitefirer.org'

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30))
    return _client


async def proxy_api(path: str, method: str = "GET", body: dict | None = None):
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


def _get_ai_client():
    """Lazy-init AI client from available API keys.
    Priority: OPENAI_API_KEY > DEEPSEEK_API_KEY > ANTHROPIC_API_KEY
    """
    try:
        from openai import AsyncOpenAI
        if os.environ.get("OPENAI_API_KEY"):
            return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]), "openai"
        if os.environ.get("DEEPSEEK_API_KEY"):
            return AsyncOpenAI(
                api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url="https://api.deepseek.com"
            ), "deepseek"
    except ImportError:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from anthropic import AsyncAnthropic
            return AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]), "anthropic"
        except ImportError:
            pass
    return None, None


# ── Routes ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
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
    return templates.TemplateResponse("index.html", {"request": request, "posts": posts})


@app.get("/preview/{slug}", response_class=HTMLResponse)
async def serve_preview(request: Request, slug: str):
    post = read_post(slug)
    if not post:
        raise HTTPException(404, "文章不存在")
    title, _, _ = post

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

    return templates.TemplateResponse("preview.html", {
        "request": request,
        "title": html_mod.escape(title),
        "slug": slug,
        "theme_options": theme_opts,
        "theme_names": theme_names,
        "default_theme": default_theme,
    })


@app.get("/api/render/{slug}")
async def serve_render(slug: str, theme: str | None = Query(None)):
    post = read_post(slug)
    if not post:
        return JSONResponse({"success": False, "error": "文章不存在"}, 404)

    title, _, body = post

    # Resolve ./relative.svg paths → PNG (Chromium headless)
    post_dir = find_post(slug).parent if find_post(slug) else None
    if post_dir:
        def _resolve_rel_svg(m):
            rel = m.group(1)
            fpath = post_dir / rel
            if fpath.suffix.lower() == '.svg' and fpath.exists():
                import tempfile
                try:
                    svg_text = fpath.read_text(encoding='utf-8')
                    html_fd, html_path = tempfile.mkstemp(suffix='.html')
                    png_fp = html_path + '.png'
                    svg_text = fpath.read_text(encoding='utf-8')
                    wm = re.search(r'<svg\b[^>]*\swidth="(\d+(?:\.\d+)?)(?:px)?"', svg_text)
                    hm = re.search(r'<svg\b[^>]*\sheight="(\d+(?:\.\d+)?)(?:px)?"', svg_text)
                    vw = int(float(wm.group(1))) * 2 if wm else 1800
                    vh = int(float(hm.group(1))) * 2 if hm else 1400
                    page = '<!DOCTYPE html><html><body style="margin:0">' + svg_text + '</body></html>'
                    Path(html_path).write_text(page, encoding='utf-8')
                    subprocess.run([
                        'chromium', '--headless=new', f'--screenshot={png_fp}',
                        f'--window-size={vw},{vh}', '--hide-scrollbars', html_path
                    ], capture_output=True, timeout=20, check=True)
                    from PIL import Image, ImageChops
                    img = Image.open(png_fp).convert('RGB')
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    diff = ImageChops.difference(img, bg)
                    bbox = diff.getbbox()
                    if bbox: img = img.crop(bbox)
                    img.save(png_fp)
                    b64 = base64.b64encode(Path(png_fp).read_bytes()).decode()
                    Path(html_path).unlink(missing_ok=True)
                    Path(png_fp).unlink(missing_ok=True)
                    return f'src="data:image/png;base64,{b64}"'
                except Exception:
                    return m.group(0)
            return m.group(0)
        body = re.sub(r'src="\.\/([^"]+)"', _resolve_rel_svg, body)

    import time
    loop = asyncio.get_running_loop()

    async def event_stream(input_body, input_title):
        steps = {}
        md_body = input_body
        progress_q = asyncio.Queue()

        def sse(event, data):
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def on_progress(step, status):
            loop.call_soon_threadsafe(progress_q.put_nowait, (step, status))

        async def drain_progress():
            while True:
                try:
                    step, status = await asyncio.wait_for(progress_q.get(), timeout=0.1)
                    yield sse("progress", {"step": step, "status": status})
                except asyncio.TimeoutError:
                    return

        # Step 1: 预处理
        yield sse("progress", {"step": "预处理", "status": "running"})
        t0 = time.time()
        clean_task = loop.run_in_executor(None, clean_hugo, md_body, app.state.base_url, on_progress)

        while not clean_task.done():
            async for evt in drain_progress():
                yield evt
            await asyncio.sleep(0.1)
        try:
            md_body = await clean_task
        except Exception as e:
            yield sse("error", {"error": f"预处理失败: {e}"})
            return
        async for evt in drain_progress():
            yield evt
        steps["预处理"] = f"{time.time()-t0:.1f}s"
        yield sse("progress", {"step": "预处理", "status": "done", "elapsed": steps["预处理"]})

        # Step 2: SVG→PNG
        if app.state.svg_to_image and '<svg' in md_body:
            yield sse("progress", {"step": "SVG→PNG", "status": "running"})
            t0 = time.time()
            md_body = await loop.run_in_executor(None, svg_to_img, md_body)
            steps["SVG→PNG"] = f"{time.time()-t0:.1f}s"
            yield sse("progress", {"step": "SVG→PNG", "status": "done", "elapsed": steps["SVG→PNG"]})

        # Step 3: 排版
        yield sse("progress", {"step": "排版", "status": "running"})
        t0 = time.time()
        try:
            display_html = await render_markdown(f"# {input_title}\n\n{md_body}", theme)
            copy_html = await render_markdown(md_body, theme)
            # Rewrite relative image paths → /article-assets/{slug}/{filename}
            def _fix_img_paths(html):
                return re.sub(
                    r'src="((?!(?:https?:|/|data:))[^"]+)"',
                    rf'src="/article-assets/{slug}/\1"',
                    html
                )
            display_html = _fix_img_paths(display_html)
            # Copy HTML embeds images as base64 for WeChat paste
            def _embed_images(html):
                def _replace(m):
                    fname = m.group(1)
                    fpath = post_dir / fname if post_dir else None
                    if fpath and fpath.exists():
                        from PIL import Image
                        from io import BytesIO
                        img = Image.open(fpath)
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        w, h = img.size
                        if w > 800:
                            img = img.resize((800, int(h * 800 / w)), Image.LANCZOS)
                        buf = BytesIO()
                        img.save(buf, format='JPEG', quality=100, optimize=True)
                        data = buf.getvalue()
                        mime = 'image/jpeg'
                        return f'src="data:{mime};base64,{base64.b64encode(data).decode()}"'
                    return m.group(0)
                return re.sub(
                    r'src="((?!(?:https?:|/|data:))[^"]+)"',
                    _replace,
                    html
                )
            copy_html = _embed_images(copy_html)
            steps["排版"] = f"{time.time()-t0:.1f}s"
            yield sse("progress", {"step": "排版", "status": "done", "elapsed": steps["排版"]})
        except RuntimeError as e:
            yield sse("error", {"error": str(e)})
            return

        yield sse("result", {"success": True, "html": display_html, "copy_html": copy_html, "steps": steps})

    return StreamingResponse(event_stream(body, title), media_type="text/event-stream")


@app.get("/api/themes")
async def serve_themes():
    data, code = await proxy_api("/api/themes")
    return JSONResponse(data, code)


# ── New: Cover Editor APIs ────────────────────────────────────

@app.get("/api/article-images/{slug}")
async def serve_article_images(slug: str):
    """Extract all images from a rendered article."""
    post = read_post(slug)
    if not post:
        return JSONResponse({"images": []})
    title, _, body = post

    import tempfile
    loop = asyncio.get_running_loop()
    try:
        md_body = await loop.run_in_executor(None, clean_hugo, body, app.state.base_url)
        if app.state.svg_to_image and '<svg' in md_body:
            md_body = await loop.run_in_executor(None, svg_to_img, md_body)
        html_content = await render_markdown(md_body)
    except Exception:
        html_content = ""

    # Parse all <img> src attributes
    images = []
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', html_content):
        src = m.group(1)
        if src and not src.startswith('data:image/svg+xml'):
            # Resolve relative paths → /article-assets/{slug}/...
            if not src.startswith(('http', '/', 'data:')):
                src = f'/article-assets/{slug}/{src}'
            images.append(src)

    return JSONResponse({"images": images})


@app.post("/api/cover/ai-text")
async def serve_cover_ai_text(request: Request):
    """Generate cover text suggestions using AI."""
    body = await request.json()
    title = body.get("title", "")
    count = body.get("count", 3)

    client, provider = _get_ai_client()
    if not client:
        return JSONResponse({
            "texts": [
                f"🔥 {title}",
                f"{title}｜深度解析",
                f"关于「{title}」你想知道的一切",
            ],
            "note": "AI 服务未配置，返回占位文案。请设置 DEEPSEEK_API_KEY、OPENAI_API_KEY 或 ANTHROPIC_API_KEY。"
        })

    prompt = (
        f"你是一个微信公众号运营专家。请为以下文章标题生成{count}个封面宣传文案，"
        f"每个文案不超过20字，简洁有力，吸引读者点击。\n\n文章标题：{title}\n\n"
        f"请直接返回{count}个文案，每行一个，不要编号。"
    )

    try:
        if provider in ("openai", "deepseek"):
            model = "gpt-4o-mini" if provider == "openai" else "deepseek-chat"
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            texts = [t.strip() for t in resp.choices[0].message.content.strip().split("\n") if t.strip()]
        else:  # anthropic
            resp = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            texts = [t.strip() for t in resp.content[0].text.strip().split("\n") if t.strip()]
        return JSONResponse({"texts": texts[:count]})
    except Exception as e:
        return JSONResponse({"texts": [], "error": str(e)})


@app.post("/api/cover/ai-image")
async def serve_cover_ai_image(request: Request):
    """Generate cover image using DALL-E."""
    body = await request.json()
    prompt = body.get("prompt", "")

    client, provider = _get_ai_client()
    if not client or provider != "openai":
        return JSONResponse({
            "images": [],
            "error": "AI 生图需要配置 OPENAI_API_KEY。当前仅支持 DALL-E。"
        })

    try:
        resp = await client.images.generate(
            model="dall-e-3",
            prompt=f"微信公众号文章封面图，2.35:1 宽高比，适合科技博客：{prompt}",
            n=1,
            size="1792x1024",
            quality="standard",
        )
        return JSONResponse({"images": [resp.data[0].url]})
    except Exception as e:
        return JSONResponse({"images": [], "error": str(e)})


# ── New: AI Chat API ──────────────────────────────────────────

@app.post("/api/chat")
async def serve_chat(request: Request):
    """AI chat with article context, SSE streaming."""
    body = await request.json()
    message = body.get("message", "")
    slug = body.get("slug", "")
    title = body.get("title", "")

    # Get article content for context
    article_body = ""
    if slug:
        post = read_post(slug)
        if post:
            article_body = post[2][:4000]  # First 4000 chars for context

    client, provider = _get_ai_client()
    if not client:
        async def no_api_stream():
            yield f"data: {json.dumps({'text': 'AI 服务未配置。请设置 DEEPSEEK_API_KEY、OPENAI_API_KEY 或 ANTHROPIC_API_KEY 环境变量后重启。'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(no_api_stream(), media_type="text/event-stream")

    system_prompt = (
        "你是一个微信公众号排版和内容优化助手。你可以帮助用户优化文章标题、调整排版、"
        "改写段落、生成摘要等。回答应简洁实用，直接给出可操作的建议。"
    )
    if article_body:
        system_prompt += f"\n\n当前文章标题：{title}\n当前文章内容（部分）：{article_body[:2000]}"

    async def stream():
        try:
            if provider in ("openai", "deepseek"):
                model = "gpt-4o-mini" if provider == "openai" else "deepseek-chat"
                stream_resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    stream=True,
                )
                async for chunk in stream_resp:
                    if chunk.choices[0].delta.content:
                        yield f"data: {json.dumps({'text': chunk.choices[0].delta.content})}\n\n"
            else:  # anthropic
                async with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": message}],
                ) as stream_resp:
                    async for text in stream_resp.text_stream:
                        yield f"data: {json.dumps({'text': text})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


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
    parser.add_argument("--base-url", default="https://whitefirer.org", help="相对链接补全域名")
    args = parser.parse_args()

    app.state.content_dir = Path(args.content_dir)
    app.state.api_base = args.api_base
    app.state.svg_to_image = not args.no_svg_to_image
    app.state.base_url = args.base_url

    if args.config:
        from convert import load_config
        cfg = load_config(args.config)
        if "content_dir" in cfg:
            app.state.content_dir = Path(cfg["content_dir"])
        if "api_base" in cfg:
            app.state.api_base = cfg["api_base"]
        if "no_svg_to_image" in cfg:
            app.state.svg_to_image = not cfg["no_svg_to_image"]
        if "base_url" in cfg:
            app.state.base_url = cfg["base_url"]

    # Mount article static files after content_dir is resolved
    from starlette.staticfiles import StaticFiles
    app.mount("/article-assets", StaticFiles(directory=str(app.state.content_dir)), name="article_assets")

    print(f"📱 微信预览服务器 (FastAPI)")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   内容: {app.state.content_dir}")
    print(f"   API:  {app.state.api_base}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
