#!/usr/bin/env python3
"""Hugo Markdown → 微信公众号 HTML 转换管道

用法:
    # 本地文件
    python3 convert.py post.md                          # 本地渲染
    python3 convert.py post.md --api                    # API 渲染
    python3 convert.py post.md --api --api-url http://x  # 自定义 API 地址

    # 远程 URL
    python3 convert.py https://blog.example/posts/x/    # 抓取 URL 渲染
    python3 convert.py https://blog.example/posts/x/ --api

    # 配置文件批量转换
    python3 convert.py -c wechat.yml

依赖安装: bash setup.sh
"""

import sys
import re
import html
import time
import json
import base64
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_API_URL = "http://localhost:3456/api/convert"


# ── Frontmatter ──────────────────────────────────────────────

def strip_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---\n', 4)
    if end == -1:
        return {}, text
    meta_raw = text[4:end]
    body = text[end + 5:]
    meta = {}
    for line in meta_raw.strip().split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


# ── Source: file or URL ──────────────────────────────────────

def fetch_text(source: str) -> tuple[str, Path | None]:
    """读取输入源，返回 (text, local_dir_or_None)"""
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ('http', 'https'):
        print(f"   抓取: {source}")
        with urllib.request.urlopen(source, timeout=30) as resp:
            text = resp.read().decode('utf-8')
        return text, Path.cwd()
    else:
        p = Path(source)
        return p.read_text(encoding='utf-8'), p.parent


# ── Mermaid ───────────────────────────────────────────────────

def _mermaid_to_img(match: re.Match) -> str:
    """Mermaid → PNG (mmdc + Chromium，纯本地)"""
    import os, tempfile
    code = match.group(1).strip()

    # mmdc + Chromium
    if subprocess.run(['which', 'mmdc'], capture_output=True).returncode == 0:
        try:
            mmd_fd, mmd_path = tempfile.mkstemp(suffix='.mmd')
            with open(mmd_fd, 'w') as f:
                f.write(code)
            png_path = mmd_path + '.png'
            env = {**os.environ, 'PUPPETEER_EXECUTABLE_PATH': '/usr/bin/chromium'}
            subprocess.run(
                ['mmdc', '-i', mmd_path, '-o', png_path, '-b', 'transparent'],
                capture_output=True, timeout=30, check=True, env=env
            )
            b64 = base64.b64encode(Path(png_path).read_bytes()).decode()
            Path(mmd_path).unlink(missing_ok=True)
            Path(png_path).unlink(missing_ok=True)
            return f'\n\n![mermaid](data:image/png;base64,{b64})\n\n'
        except Exception:
            Path(mmd_path).unlink(missing_ok=True)
            Path(png_path).unlink(missing_ok=True)

    return f'\n\n```mermaid\n{code}\n```\n\n'


# ── Asciinema ─────────────────────────────────────────────────

def _convert_asciinema(src: str) -> str:
    """asciinema .cast → GIF (agg 优先, asciicast2gif 备选)"""
    import tempfile
    gif_path = None
    try:
        gif_fd, gif_path = tempfile.mkstemp(suffix='.gif')
        if subprocess.run(['which', 'agg'], capture_output=True).returncode == 0:
            subprocess.run(['agg', '--fps-cap', '15', src, gif_path], capture_output=True, timeout=60, check=True)
        elif subprocess.run(['which', 'asciicast2gif'], capture_output=True).returncode == 0:
            subprocess.run(['asciicast2gif', '-S', '2', src, gif_path], capture_output=True, timeout=120, check=True)
        else:
            raise FileNotFoundError('no converter (install agg: see setup.sh)')

        b64 = base64.b64encode(Path(gif_path).read_bytes()).decode()
        return (
            f'<p style="text-align:center"><img src="data:image/gif;base64,{b64}"'
            f' alt="terminal recording" style="max-width:100%"/></p>'
        )
    except Exception as e:
        return (
            f'<div style="background:#f5f5f5;border:1px dashed #ccc;'
            f'padding:20px;text-align:center;color:#888;margin:1em 0;border-radius:4px">'
            f'[终端录屏: <a href="{html.escape(src)}" style="color:#4a90d9">{html.escape(src)}</a>]'
            f'<br><small>{html.escape(str(e)[:100])}</small></div>'
        )
    finally:
        if gif_path:
            Path(gif_path).unlink(missing_ok=True)


def _asciinema_to_gif(match: re.Match) -> str:
    return _convert_asciinema(match.group(1).strip())


# ── Cleanup ───────────────────────────────────────────────────

def clean_hugo(content: str, base_url: str = 'https://whitefirer.org',
               progress: callable = None) -> str:
    def _report(step, status='done'):
        if progress: progress(step, status)

    # Mermaid — process one by one with progress
    mermaids = list(re.finditer(r'{{<\s*mermaid\s*>}}\s*(.*?)\s*{{<\s*/mermaid\s*>}}', content, re.DOTALL))
    for i, m in enumerate(mermaids):
        code = m.group(1).strip()
        first_line = code.split('\n')[0][:30]
        label = f'Mermaid {i+1}/{len(mermaids)} ({first_line}...)'
        _report(label, 'running')
        t0 = time.time()
        result = _mermaid_to_img(m)
        ok = 'base64' in result
        content = content.replace(m.group(0), result, 1)
        _report(label, f'{"✓" if ok else "✗"} {time.time()-t0:.1f}s')

    # Asciinema — parallel (max 2 workers)
    asciis = list(re.finditer(r'{{<\s*asciinema\s[^>]*src="([^"]+)"[^>]*>}}', content))
    if asciis:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        total = len(asciis)
        futures = {}
        with ThreadPoolExecutor(max_workers=min(total, 2)) as ex:
            for i, m in enumerate(asciis):
                src = m.group(1)
                label = f'Asciinema {i+1}/{total} ({src[:40]}...)'
                _report(label, 'running')
                futures[ex.submit(_asciinema_to_gif, m)] = (i, m, label)
            results = {}
            for f in as_completed(futures):
                i, m, label = futures[f]
                results[i] = f.result()
                ok = 'base64' in results[i]
                _report(label, f'{"✓" if ok else "✗"}')
        # Apply replacements in reverse order
        for i, m in reversed(list(enumerate(asciis))):
            content = content.replace(m.group(0), results[i], 1)

    # Image shortcodes
    img_count = len(re.findall(r'{{<\s*image\s+[^>]*>}}', content))
    if img_count:
        _report(f'图片短代码 ({img_count}个)', 'running')
        def _image_replace(m):
            src = re.search(r'src="([^"]+)"', m.group(0))
            alt = re.search(r'alt="([^"]*)"', m.group(0))
            caption = re.search(r'caption="([^"]*)"', m.group(0))
            if src:
                url = src.group(1)
                if url.startswith('/'):
                    url = base_url + url
                alt_text = alt.group(1) if alt else ''
                if caption:
                    cap_text = caption.group(1)
                    return f'\n\n<figure><img src="{url}" alt="{alt_text}"><figcaption>{cap_text}</figcaption></figure>\n\n'
                return f'\n\n![{alt_text}]({url})\n\n'
            return ''
        content = re.sub(r'{{<\s*image\s+[^>]*>}}', _image_replace, content)
        _report(f'图片短代码 ({img_count}个)')

    # Inline SVGs (will be processed later by svg_to_img)
    svg_count = len(re.findall(r'<svg\b', content))
    if svg_count:
        _report(f'内联SVG ({svg_count}个)')

    # Misc cleanup
    content = re.sub(r'{{<\s*\w+[^>]*>}}', '', content)
    content = re.sub(r'{{<\s*/\w+\s*>}}', '', content)
    content = re.sub(r'<div class="post-series-nav">.*?</div>', '', content, flags=re.DOTALL)
    content = re.sub(r'\*本文是「[^」]+」系列之[一|二|三|四|五|六|七|八|九|十].*?\*', '', content)
    content = re.sub(r'\]\(/posts/', f']({base_url}/posts/', content)
    content = re.sub(r'\]\(/(?!/)', f']({base_url}/', content)
    return content.strip()


# ── Markdown → HTML ────────────────────────────────────────────

def local_render(content: str) -> str:
    from markdown_it import MarkdownIt
    md = MarkdownIt('commonmark', {'html': True, 'linkify': True, 'typographer': True})
    md.enable(['table', 'strikethrough', 'linkify'])
    return md.render(content)


def api_render(content: str, api_url: str, theme: str | None = None) -> str:
    payload = json.dumps({'markdown': content, **(dict(theme=theme) if theme else {})}).encode()
    req = urllib.request.Request(
        api_url, data=payload,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get('success'):
                return data['html']
            print(f"  ⚠️  API 返回错误: {data.get('error')}，回退本地渲染")
            return local_render(content)
    except Exception as e:
        print(f"  ⚠️  API 不可用 ({e})，回退本地渲染")
        return local_render(content)


# ── Post-processing ────────────────────────────────────────────

def post_process(html_content: str, author: str = 'whitefirer') -> str:
    html_content = re.sub(
        r'data-website="https?://www\.mdnice\.com"', '', html_content
    )
    html_content = re.sub(
        r'data-(?!src=|alt=|href=)[\w-]+="[^"]*"', '', html_content
    )
    html_content = re.sub(r'<div[^>]*></div>', '', html_content)
    sig = (
        f'\n<p style="color:#888;font-size:14px;text-align:right;margin-top:2em">'
        f'— {html.escape(author)}</p>\n'
    )
    return html_content + sig


# ── SVG → Image (mobile WeChat compat) ─────────────────────────

def svg_to_img(html_content: str) -> str:
    """内联 <svg> → PNG (resvg 快速渲染, base64 SVG 备选)"""
    import os, tempfile

    _FONT_DIRS = [
        str(Path(__file__).resolve().parent / 'fonts'),
        '/usr/share/fonts',
        '/usr/local/share/fonts',
    ]
    _FONT_ARGS = []
    for d in _FONT_DIRS:
        if Path(d).is_dir():
            _FONT_ARGS += ['--use-fonts-dir', d]

    def _replace(m: re.Match) -> str:
        svg = m.group(0)
        svg_path = png_path = None
        try:
            svg_fd, svg_path = tempfile.mkstemp(suffix='.svg')
            png_fd, png_path = tempfile.mkstemp(suffix='.png')
            svg_rendered = svg.replace('system-ui', 'Noto Sans CJK SC')
            Path(svg_path).write_text(svg_rendered, encoding='utf-8')
            subprocess.run([
                'resvg', '--zoom', '2.5',
                '--sans-serif-family', 'Noto Sans CJK SC',
                '--font-family', 'Noto Sans CJK SC',
                *_FONT_ARGS,
                svg_path, png_path
            ], capture_output=True, timeout=10, check=True)
            b64 = base64.b64encode(Path(png_path).read_bytes()).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;height:auto;display:block;margin:1.2em auto" width="100%" alt="diagram"/>'
        except Exception:
            b64 = base64.b64encode(svg.encode()).decode()
            w = re.search(r'width="([^"]*)"', svg)
            attrs = ''
            if w: attrs += f' width="{w.group(1)}"'
            return f'<img src="data:image/svg+xml;base64,{b64}" style="max-width:100%;height:auto;display:block;margin:1.2em auto"{attrs} alt="diagram"/>'
        finally:
            if svg_path: Path(svg_path).unlink(missing_ok=True)
            if png_path: Path(png_path).unlink(missing_ok=True)
    return re.sub(r'<svg\b[^>]*>.*?</svg>', _replace, html_content, flags=re.DOTALL)


# ── Wrapper ────────────────────────────────────────────────────

def wrap_html(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{html.escape(title)}</title></head>
<body>
<section id="nice">
<h1 style="text-align:center;font-size:1.6em;font-weight:700;margin:1.5em 0 .8em">{html.escape(title)}</h1>
{body_html}
</section>
</body>
</html>"""


# ── Single post pipeline ──────────────────────────────────────

def convert_one(
    source: str,
    use_api: bool = False,
    api_url: str = DEFAULT_API_URL,
    theme: str | None = None,
    output: str | None = None,
    author: str = 'whitefirer',
    base_url: str = 'https://whitefirer.org',
) -> Path:
    text, local_dir = fetch_text(source)
    meta, body = strip_frontmatter(text)

    title = meta.get('title', Path(source).stem if not source.startswith('http') else 'article')
    if not author:
        author = meta.get('author', 'whitefirer')

    print(f"📄 {title}")
    print(f"   预处理...")
    body = clean_hugo(body, base_url)
    body = svg_to_img(body)

    # Fix relative image paths → absolute Hugo URLs
    if local_dir:
        slug = local_dir.name
        date_raw = meta.get('date', '')
        date_part = date_raw[:10].replace('-', '/') if date_raw else ''
        article_path = f"{base_url}/posts/{date_part}/{slug}" if date_part else ''
        if article_path:
            def _fix_rel(m):
                img_path = m.group(2)
                if img_path and not img_path.startswith(('http', '/', 'data:')):
                    return f'![{m.group(1)}]({article_path}/{img_path})'
                return m.group(0)
            body = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _fix_rel, body)

    print(f"   渲染...")
    if use_api:
        body_html = api_render(body, api_url, theme)
    else:
        body_html = local_render(body)

    body_html = post_process(body_html, author)

    if output:
        out = Path(output)
    else:
        out = (local_dir or Path.cwd()) / 'wechat-output.html'

    result = wrap_html(title, body_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding='utf-8')
    print(f"✅ {out} ({len(result)} bytes)")
    return out


# ── Config file ───────────────────────────────────────────────

def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"❌ 配置文件不存在: {path}")
        sys.exit(1)
    text = p.read_text(encoding='utf-8')
    if p.suffix in ('.yml', '.yaml'):
        import yaml
        return yaml.safe_load(text)
    elif p.suffix == '.json':
        return json.loads(text)
    else:
        print(f"❌ 不支持的配置格式: {p.suffix}，请用 .yml / .yaml / .json")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Hugo Markdown → 微信公众号 HTML')
    parser.add_argument('source', nargs='?', help='Markdown 文件路径或 URL')
    parser.add_argument('--api', action='store_true', help='使用 markdown2wechat API 渲染')
    parser.add_argument('--api-url', default=DEFAULT_API_URL, help=f'API 地址 (默认 {DEFAULT_API_URL})')
    parser.add_argument('--theme', help='markdown2wechat 主题名 (需 --api)')
    parser.add_argument('-o', '--output', help='输出文件路径')
    parser.add_argument('-c', '--config', help='配置文件 (YAML/JSON)，批量转换')
    parser.add_argument('--author', default='whitefirer', help='文末署名 (默认 whitefirer)')
    parser.add_argument('--base-url', default='https://whitefirer.org', help='相对链接补全域名')
    args = parser.parse_args()

    if args.config:
        cfg = load_config(args.config)
        api_url = cfg.get('api_url', DEFAULT_API_URL)
        theme = cfg.get('theme')
        output_dir = cfg.get('output_dir', '.')
        author = cfg.get('author', 'whitefirer')
        use_api = cfg.get('api', False)
        posts = cfg.get('posts', [])
        if not posts:
            print("❌ 配置文件中没有 posts 列表")
            sys.exit(1)
        print(f"📋 批量转换 {len(posts)} 篇 (API={'on' if use_api else 'off'})")
        for i, post in enumerate(posts):
            inp = post if isinstance(post, str) else post.get('source')
            out = post.get('output') if isinstance(post, dict) else None
            if output_dir and not out:
                if inp.startswith('http'):
                    stem = 'article'
                else:
                    parts = Path(inp).parts
                    stem = parts[-2] if parts[-1] in ('index.md', '_index.md') and len(parts) >= 2 else Path(inp).stem
                out = str(Path(output_dir) / f'{stem}-wechat.html')
            print(f"\n[{i+1}/{len(posts)}]")
            convert_one(inp, use_api, api_url, theme, out, author, args.base_url)
        print(f"\n🏁 全部完成")
    elif args.source:
        convert_one(args.source, args.api, args.api_url, args.theme, args.output, args.author, args.base_url)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
