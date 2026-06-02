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

def _mermaid_ink(mermaid_code: str) -> str:
    encoded = base64.urlsafe_b64encode(mermaid_code.encode()).decode()
    url = f"https://mermaid.ink/img/{encoded}"
    return f'<p style="text-align:center"><img src="{url}" alt="mermaid diagram"/></p>'


def _mermaid_mmdc(mermaid_code: str) -> str | None:
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.mmd', mode='w', delete=False) as f:
            f.write(mermaid_code)
            mmd_path = f.name
        png_path = mmd_path + '.png'
        subprocess.run(
            ['mmdc', '-i', mmd_path, '-o', png_path, '-b', 'transparent'],
            capture_output=True, timeout=30, check=True
        )
        b64 = base64.b64encode(Path(png_path).read_bytes()).decode()
        Path(mmd_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)
        return f'<p style="text-align:center"><img src="data:image/png;base64,{b64}" alt="mermaid diagram"/></p>'
    except Exception:
        return None


def _mermaid_to_img(match: re.Match) -> str:
    code = match.group(1).strip()
    if subprocess.run(['which', 'mmdc'], capture_output=True).returncode == 0:
        result = _mermaid_mmdc(code)
        if result:
            return result
    return _mermaid_ink(code)


# ── Asciinema ─────────────────────────────────────────────────

def _asciinema_placeholder(match: re.Match) -> str:
    src = match.group(1).strip()
    return (
        f'<div style="background:#f5f5f5;border:1px dashed #ccc;'
        f'padding:20px;text-align:center;color:#888;margin:1em 0;border-radius:4px">'
        f'[终端录屏: <a href="{html.escape(src)}" style="color:#4a90d9">{html.escape(src)}</a>]<br>'
        f'<small>安装 asciicast2gif 后自动转 GIF，或手动转换</small></div>'
    )


# ── Cleanup ───────────────────────────────────────────────────

def clean_hugo(content: str) -> str:
    content = re.sub(
        r'{{<\s*mermaid\s*>}}\s*(.*?)\s*{{<\s*/mermaid\s*>}}',
        _mermaid_to_img, content, flags=re.DOTALL
    )
    content = re.sub(
        r'{{<\s*asciinema\s+src="([^"]+)"\s*>}}',
        _asciinema_placeholder, content
    )
    content = re.sub(
        r'<div class="post-series-nav">.*?</div>',
        '', content, flags=re.DOTALL
    )
    content = re.sub(
        r'\*本文是「[^」]+」系列之[一|二|三|四|五|六|七|八|九|十].*?\*',
        '', content
    )
    content = re.sub(r'{{<\s*image\s+[^>]*>}}', '', content)
    content = re.sub(r'{{<\s*\w+[^>]*>}}', '', content)
    content = re.sub(r'{{<\s*/\w+\s*>}}', '', content)
    content = re.sub(r'\]\(/posts/', '](https://whitefirer.org/posts/', content)
    content = re.sub(r'\]\(/(?!/)', '](https://whitefirer.org/', content)
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
) -> Path:
    text, local_dir = fetch_text(source)
    meta, body = strip_frontmatter(text)

    title = meta.get('title', Path(source).stem if not source.startswith('http') else 'article')
    if not author:
        author = meta.get('author', 'whitefirer')

    print(f"📄 {title}")
    print(f"   预处理...")
    body = clean_hugo(body)

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
            convert_one(inp, use_api, api_url, theme, out, author)
        print(f"\n🏁 全部完成")
    elif args.source:
        convert_one(args.source, args.api, args.api_url, args.theme, args.output, args.author)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
