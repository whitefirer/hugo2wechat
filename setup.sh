#!/bin/bash
# Hugo → 微信公众号 转换管道 — 一键安装
set -e

echo "=== Hugo → WeChat 转换管道 依赖安装 ==="

# 1. Python deps
echo ""
echo "[1/5] Python 依赖..."
pip3 install -r "$(dirname "$0")/requirements.txt" --break-system-packages

# 2. Node deps (mmdc — 可选，离线 mermaid 渲染)
echo ""
echo "[2/5] mermaid-cli (可选，需要 ~500MB)..."
if command -v mmdc &>/dev/null; then
    echo "  ✓ mmdc 已安装"
else
    echo "  安装中 (下载 Chromium，可能较慢)..."
    npm install -g @mermaid-js/mermaid-cli && echo "  ✓ mmdc 安装完成" || echo "  ⚠ mmdc 安装失败，将使用 mermaid.ink API 作为备选"
fi

# 3. agg — asciinema → GIF (推荐)
echo ""
echo "[3/5] agg (asciinema → GIF)..."
if command -v agg &>/dev/null; then
    echo "  ✓ agg 已安装"
else
    AGG_VER=$(curl -s https://api.github.com/repos/asciinema/agg/releases/latest | python3 -c "import sys,json;print(json.load(sys.stdin)['tag_name'])")
    AGG_URL="https://github.com/asciinema/agg/releases/download/${AGG_VER}/agg-x86_64-unknown-linux-gnu"
    echo "  下载 ${AGG_URL}..."
    curl -sL -o /tmp/agg "$AGG_URL" && chmod +x /tmp/agg && cp /tmp/agg ~/.local/bin/agg && rm /tmp/agg
    echo "  ✓ agg ${AGG_VER} 安装完成" || echo "  ⚠ agg 安装失败"
fi

# 4. resvg — SVG → PNG (快速、高保真)
echo ""
echo "[4/5] resvg (SVG → PNG)..."
if command -v resvg &>/dev/null; then
    echo "  ✓ resvg 已安装"
else
    sudo apt-get install -y resvg -qq 2>/dev/null && echo "  ✓ resvg 安装完成" || echo "  ⚠ resvg 安装失败，将使用 base64 SVG"
fi

# 5. asciicast2gif — 备选方案 (需要 PhantomJS + ImageMagick)
echo ""
echo "[5/5] asciicast2gif (备选，需要 PhantomJS)..."
if command -v asciicast2gif &>/dev/null; then
    echo "  ✓ asciicast2gif 已安装"
else
    npm install -g asciicast2gif --ignore-scripts 2>/dev/null && echo "  ✓ asciicast2gif 安装完成" || echo "  ⚠ asciicast2gif 安装失败 (非必需，agg 替代)"
fi

echo ""
echo "=== 完成 ==="
echo ""
echo "使用:"
echo "  python3 convert.py <blog-post.md>           # 本地渲染"
echo "  python3 convert.py <blog-post.md> --api     # markdown2wechat API 渲染"
echo "  python3 convert.py -c wechat.yml            # 批量转换"
echo "  python3 preview.py                          # 预览服务器"
echo ""
echo "API 模式需先启动 markdown2wechat:"
echo "  cd ~/Desktop/Devspace/markdown2wechat/next && npx next dev -p 3456"
