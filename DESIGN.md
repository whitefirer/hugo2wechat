# Hugo → 微信公众号 转换管道

## 架构

```
Hugo .md
    ↓
Python 预处理管道 (clean_hugo)
    ├── 剥 frontmatter
    ├── mermaid → mmdc + Chromium → PNG base64
    ├── asciinema → agg → GIF base64 (并行)
    ├── image shortcode → markdown 图片
    ├── 系列导航删除 + shortcode 清理
    └── 相对链接补全 (base_url)
    ↓
SVG 转换
    ├── 内联 <svg> → resvg 2.5x → PNG base64
    └── 外部 ./file.svg → Chromium + Pillow 裁边 → PNG base64
    ↓
干净 Markdown (含 PNG img)
    ↓
markdown2wechat API 排版 (内联样式 + 代码高亮)
    ↓
微信兼容 HTML
    ↓
预览 / 复制粘贴到公众号
```

## 预处理清单

| 操作 | 工具 | 说明 |
|------|------|------|
| 剥 frontmatter | Python | title → 公众号标题 |
| `{{< mermaid >}}` | mmdc + Chromium → PNG | clean_hugo 阶段 |
| `{{< asciinema >}}` | agg → GIF (并行) | ThreadPoolExecutor, --fps-cap 15 |
| `{{< image >}}` | 提取 src → markdown | 相对路径补全 base_url |
| 内联 `<svg>` | resvg 2.5x → PNG | svg_to_img 阶段 |
| 外部 `./file.svg` | Chromium + Pillow 裁边 | serve_render 阶段 |
| 代码块高亮 | highlight.js Atom One Dark | JS 注入 inline style (公众号兼容) |
| 系列导航/短代码清理 | regex | clean_hugo 阶段 |
| 相对链接补全 | regex | `/posts/x/` → base_url |
| 署名/mdnice 清理 | 后处理 | post_process 阶段 |

## 服务

| 服务 | 端口 | 技术 |
|------|------|------|
| 预览服务器 | 3333 | FastAPI + SSE 实时进度 |
| 排版引擎 | 3456 | markdown2wechat (Next.js) |
| Hugo 预览 | 1313 | hugo server -D |

## 核心依赖

- resvg — 内联 SVG 渲染 (apt)
- Chromium — 外部 SVG + mermaid 渲染 (系统)
- mmdc — mermaid CLI (npm)
- agg — asciinema → GIF (GitHub Release)
- Pillow — PNG 自动裁边 (pip)
- markdown2wechat — 排版引擎 (Next.js)
- FastAPI + uvicorn + httpx — 预览服务器

## 文件

```
hugo2wechat/
├── convert.py          # 转换主脚本
├── preview.py          # 预览服务器 (FastAPI + SSE)
├── setup.sh            # 一键依赖安装
├── requirements.txt    # Python 依赖
├── wechat.example.yml  # 批量配置示例
├── DESIGN.md           # 本文件
├── fonts/              # 项目字体
└── README.md
```
