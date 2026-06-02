#!/bin/bash
# Hugo → 微信公众号 转换管道 — 一键安装
set -e

echo "=== Hugo → WeChat 转换管道 依赖安装 ==="

# 1. Python deps
echo ""
echo "[1/3] Python 依赖..."
pip3 install -r "$(dirname "$0")/requirements.txt" --break-system-packages

# 2. Node deps (mmdc — 可选，离线 mermaid 渲染)
echo ""
echo "[2/3] mermaid-cli (可选，需要 ~500MB)..."
if command -v mmdc &>/dev/null; then
    echo "  ✓ mmdc 已安装"
else
    echo "  安装中 (下载 Chromium，可能较慢)..."
    npm install -g @mermaid-js/mermaid-cli && echo "  ✓ mmdc 安装完成" || echo "  ⚠ mmdc 安装失败，将使用 mermaid.ink API 作为备选"
fi

# 3. asciicast2gif (可选)
echo ""
echo "[3/3] asciicast2gif (可选)..."
if command -v asciicast2gif &>/dev/null; then
    echo "  ✓ asciicast2gif 已安装"
elif command -v pip3 &>/dev/null; then
    pip3 install asciicast2gif 2>/dev/null && echo "  ✓ asciicast2gif 安装完成" || echo "  ⚠ asciicast2gif 安装失败，将使用占位符"
fi

echo ""
echo "=== 完成 ==="
echo ""
echo "使用:"
echo "  python3 convert.py <blog-post.md>           # 本地渲染"
echo "  python3 convert.py <blog-post.md> --api     # markdown2wechat API 渲染"
echo ""
echo "API 模式需先启动 markdown2wechat:"
echo "  cd ~/Desktop/Devspace/markdown2wechat/next && npx next dev -p 3456"
