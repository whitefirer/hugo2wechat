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
| `{{< mermaid >}}` | mermaid.ink API / mmdc → PNG | ✅ |
| `{{< asciinema >}}` | agg / asciicast2gif → GIF | ✅ |
| `{{< image >}}` | 移除 shortcode 标签 | ✅ |
| `{{< raw >}}` `{{< tab >}}` 等 | 移除标签，保留内容 | ✅ |
| 系列导航 | 删除导航块 | ✅ |
| 相对链接 | `/posts/x/` → `https://whitefirer.org/posts/x/` | ✅ |
| 内联 `<svg>` | → `<img src='data:image/svg+xml;base64,...'>` | ✅ |
| markdown2wechat 主题 | `--api` 调用排版引擎 | ✅ |
| mdnice 残留属性 | 清理 `data-website` 等 | ✅ |
| 文末署名 | 追加 `— author` | ✅ |

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
├── convert.py          # 主脚本
├── setup.sh            # 依赖安装
├── requirements.txt    # Python 依赖
├── wechat.example.yml  # 批量配置示例
├── DESIGN.md           # 架构设计
└── README.md
```

## License

MIT
