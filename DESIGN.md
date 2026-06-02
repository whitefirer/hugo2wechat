# Hugo → 微信公众号 转换管道

公众号：赛博闲谭
作者：whitefirer

## 用法

```
"把这篇文章转公众号" → Claude Code 读 Hugo MD → 预处理 → 微信 HTML → 手动粘贴
```

## 架构

```
Hugo .md
    ↓
Python 预处理管道 (convert.py)
    ├── 剥 frontmatter
    ├── mermaid → mermaid.ink API / mmdc 本地 (自动降级)
    ├── asciinema → 占位符 (待 asciicast2gif)
    ├── 相对链接补全
    ├── Hugo shortcode 清理
    ├── 系列导航删除
    └── mdnice 属性清理 + 署名追加
    ↓
干净 Markdown
    ↓
── 本地模式: markdown-it-py 渲染 (快速预览)
── API 模式:  markdown2wechat API 渲染 (正式发布，内联样式)
    ↓
微信兼容 HTML
    ↓
手动粘贴到公众号后台
```

自己写预处理管道，排版引擎调 markdown2wechat API。
不自己写排版——微信 CSS 兼容是体力活，mdnice 主题已验证。

## 预处理清单

| 操作 | 工具 | 状态 | 说明 |
|------|------|------|------|
| 剥 frontmatter | Python | ✅ | title → 公众号标题 |
| `{{< mermaid >}}` | mermaid.ink API / mmdc | ✅ | 优先本地 mmdc，不可用则 mermaid.ink |
| `{{< asciinema >}}` | — | ⏳ | 当前占位符，待 asciicast2gif |
| 相对链接 | regex | ✅ | `/posts/xxx/` → `https://whitefirer.org/posts/xxx/` |
| Hugo shortcode | regex | ✅ | 移除 `{{< raw >}}` `{{< tab >}}` 等标签 |
| 系列导航删除 | regex | ✅ | 删 `*本文是「...」系列...*` 和 `<div class="post-series-nav">...</div>` |
| 署名追加 | 文本 | ✅ | 末尾加 `— whitefirer` |
| mdnice 属性清理 | regex | ✅ | 删 `data-website` 等冗余属性 |
| 排版引擎 | api/local | ✅ | `--api` 调 markdown2wechat，默认本地 markdown-it |

## 不做的事

- 不发 API（个人号无权限）
- 不自动发布（需手动粘贴）
- 不管理图片 CDN（以后再说）

## 核心依赖

- markdown2wechat (MIT, Next.js) — 排版引擎，爬 mdnice 主题
- mermaid-cli (`@mermaid-js/mermaid-cli`) — `mmdc` 命令
- asciicast2gif — asciinema → GIF
- Python 标准库 — frontmatter 解析、正则、HTTP 调 API

## 文件

```
scripts/wechat/
├── DESIGN.md       # 本文件
├── convert.py      # 主转换脚本（Hugo MD → 预处理 → 渲染 → HTML）
├── setup.sh        # 一键依赖安装
├── requirements.txt # Python 依赖
└── themes/         # 自定义主题（markdown2wechat 导入）
```
