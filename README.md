# hugo2wechat

Hugo 博客 Markdown → 微信公众号 HTML 转换管道。

## 安装

```bash
bash setup.sh
```

## 用法

```bash
# 本地渲染（快速预览）
python3 convert.py post.md

# API 渲染（正式发布，微信兼容内联样式）
python3 convert.py post.md --api

# 自定义 API 地址
python3 convert.py post.md --api --api-url http://192.168.1.100:3456/api/convert

# 远程 URL
python3 convert.py https://blog.example.com/posts/xxx/ --api

# 指定主题
python3 convert.py post.md --api --theme orangeheart

# 批量转换（配置文件）
python3 convert.py -c wechat.yml
```

## 依赖服务

使用 `--api` 模式需先启动 [markdown2wechat](https://github.com/markdown2wechat/markdown2wechat)：

```bash
cd markdown2wechat/next && npx next dev -p 3456
```

## 转换支持

| Hugo 元素 | 处理方式 | 状态 |
|-----------|----------|:----:|
| Frontmatter | 剥离，title 用作标题 | ✅ |
| `{{< mermaid >}}` | mmdc + Chromium → PNG | ✅ |
| `{{< asciinema >}}` | agg / asciicast2gif → GIF | ✅ |
| `{{< image >}}` | 提取 src → markdown 图片 | ✅ |
| `{{< raw >}}` `{{< tab >}}` 等 | 移除标签，保留内容 | ✅ |
| 系列导航 | 删除导航块 | ✅ |
| 相对链接 | `/posts/x/` → 补全 `base_url` | ✅ |
| 内联 `<svg>` | resvg → PNG (2.5x zoom) | ✅ |
| 外部 `./file.svg` | Chromium + Pillow 裁边 → PNG | ✅ |
| markdown2wechat 主题 | `--api` 调用排版引擎 | ✅ |
| 代码高亮 | highlight.js Atom One Dark | ✅ |
| mdnice 残留属性 | 清理 `data-website` 等 | ✅ |
| 文末署名 | 追加 `— author` | ✅ |

### 关键依赖

| 功能 | 工具 | 安装 |
|------|------|------|
| SVG → PNG (内联) | `resvg` | `sudo apt install resvg` |
| SVG → PNG (外部) | Chromium + Pillow | 系统 Chromium, `pip install Pillow` |
| Mermaid → PNG | `mmdc` + Chromium | `npm i -g @mermaid-js/mermaid-cli` |
| Asciinema → GIF | `agg` (并行) | GitHub Release 下载 |
| 排版引擎 | markdown2wechat | `npx next dev -p 3456` |
| 预览服务器 | FastAPI + uvicorn + httpx + Pillow | `pip install -r requirements.txt` |

## 管道流程

详见 [DESIGN.md](DESIGN.md)

```
Hugo .md
  ↓ 剥 frontmatter
  ↓ mermaid → 图片
  ↓ asciinema → GIF
  ↓ 系列导航删除
  ↓ Hugo shortcode 清理
  ↓ 相对链接补全
  ↓ SVG → image (可选)
  ↓
干净 Markdown
  ↓ markdown2wechat API / markdown-it-py 本地
  ↓
微信公众号兼容 HTML
  ↓ 复制粘贴到公众号编辑器
```

## 文件

```
hugo2wechat/
├── convert.py          # 转换主脚本
├── preview.py          # 预览服务器 (FastAPI + SSE)
├── setup.sh            # 一键依赖安装
├── requirements.txt    # Python 依赖
├── wechat.example.yml  # 批量配置示例
├── DESIGN.md           # 架构设计
├── fonts/              # 项目字体 (Noto Sans CJK SC)
├── .gitignore
└── README.md
```

## License

MIT
