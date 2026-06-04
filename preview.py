#!/usr/bin/env python3
"""Hugo → 微信公众号 预览服务器 (FastAPI)

启动: python3 preview.py [--port 3333] [--content-dir /path/to/hugo/content/posts]
"""

import asyncio
import json
import re
import base64
import subprocess
import html as html_mod
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from convert import strip_frontmatter, clean_hugo, svg_to_img

app = FastAPI(title="hugo2wechat preview")
app.state.content_dir = Path.cwd() / "content" / "posts"
app.state.api_base = "http://localhost:3456"
app.state.svg_to_image = True
app.state.base_url = 'https://whitefirer.org'

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
.main{{display:flex;justify-content:center;align-items:flex-start;gap:12px;padding:24px 16px 40px}}
.phone-dock{{display:flex;justify-content:center;gap:20px;padding:10px 0 14px;background:inherit;border-top:1px solid rgba(0,0,0,.06);border-radius:0 0 28px 28px}}
.dock-icon{{width:36px;height:36px;border-radius:8px;border:none;background:rgba(0,0,0,.04);color:#666;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s}}
.dock-icon:hover{{background:rgba(0,0,0,.1);color:#333}}
/* 投影面板 (手机外) */
.proj-panel{{position:absolute;top:10px;width:280px;max-height:400px;background:rgba(255,255,255,.9);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.3);z-index:15;overflow-y:auto;padding:16px;opacity:0;pointer-events:none;transition:all .3s cubic-bezier(.4,0,.2,1);border:1px solid rgba(255,255,255,.3)}}
.proj-panel.open{{opacity:1;pointer-events:auto}}
.proj-left{{right:calc(100% + 8px);transform:translateX(20px)}}
.proj-left.open{{transform:translateX(0)}}
.proj-right{{left:calc(100% + 8px);transform:translateX(-20px)}}
.proj-right.open{{transform:translateX(0)}}

/* Sheet 面板 (手机内) */
.sheet-backdrop{{position:absolute;inset:0;background:rgba(0,0,0,.4);z-index:14;opacity:0;pointer-events:none;transition:opacity .3s}}
.sheet-backdrop.show{{opacity:1;pointer-events:auto}}
.sheet-panel{{position:absolute;left:0;right:0;max-height:60%;background:rgba(255,255,255,.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-radius:16px 16px 0 0;z-index:15;overflow-y:auto;padding:20px 16px;opacity:0;pointer-events:none;transition:opacity .2s,transform .35s cubic-bezier(.4,0,.2,1);border:1px solid rgba(255,255,255,.3)}}
.sheet-panel.open{{opacity:1;pointer-events:auto}}
.sheet-bottom{{bottom:60px;transform:translateY(120%)}}
.sheet-bottom.open{{transform:translateY(0)}}
.log-area{{max-height:50vh;overflow-y:auto;font-size:12px;color:var(--muted);font-family:SF Mono,monospace;line-height:1.7}}
.sheet-top{{top:0;border-radius:0 0 16px 16px;transform:translateY(-130%)}}
.sheet-top.open{{transform:translateY(0)}}
.sheet-panel *{{color:#3f3f3f}}
.phone.dark .sheet-panel{{background:rgba(28,28,30,.94);border-color:rgba(255,255,255,.08)}}
.phone.dark .sheet-panel *{{color:#f5f5f7!important}}
.phone.dark .sheet-backdrop{{background:rgba(0,0,0,.6)}}
.panel-external{{display:none}}
.panel-external.show{{display:block}}
.panel-internal{{display:block}}
.panel-internal.hide{{display:none}}
.phone.dark{{background:#000;color:#f5f5f7}}
.phone.dark .phone-content{{background:#000;color:#f5f5f7}}
.phone.dark .phone-content *{{color:#f5f5f7!important}}
.phone.dark .dock-icon{{background:rgba(255,255,255,.06);color:#999}}
.phone.dark .dock-icon:hover{{background:rgba(255,255,255,.12);color:#eee}}
.proj-panel *{{color:#3f3f3f}}
.phone.dark .proj-panel{{background:rgba(28,28,30,.95);border-color:rgba(255,255,255,.08)}}
.phone.dark .proj-panel *{{color:#f5f5f7!important}}
.phone.dark .phone-dock{{border-color:rgba(255,255,255,.06)}}
::-webkit-scrollbar{{width:4px;height:4px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:rgba(0,0,0,.15);border-radius:2px}}
::-webkit-scrollbar-thumb:hover{{background:rgba(0,0,0,.3)}}
.hljs-keyword{{color:#c678dd!important}}.hljs-string{{color:#98c379!important}}.hljs-number{{color:#d19a66!important}}.hljs-comment{{color:#5c6370!important;font-style:italic!important}}.hljs-function{{color:#61afef!important}}.hljs-attr{{color:#d19a66!important}}.hljs-built_in{{color:#e6c07b!important}}.hljs-type{{color:#e6c07b!important}}.hljs-literal{{color:#d19a66!important}}.hljs-params{{color:#abb2bf!important}}.hljs-selector-class{{color:#e6c07b!important}}.hljs-meta{{color:#61afef!important}}.hljs-title{{color:#61afef!important}}.hljs-punctuation{{color:#abb2bf!important}}
.log-entry{{font-size:12px;color:var(--muted);font-family:SF Mono,monospace;line-height:1.7;padding:2px 0;border-bottom:1px solid #2a2a4a}}
.log-entry.ok{{color:#3ecf8e}}
.log-entry.fail{{color:#e94560}}
.toggle-switch{{position:relative;display:inline-block;width:44px;height:24px}}
.toggle-switch input{{opacity:0;width:0;height:0}}
.toggle-slider{{position:absolute;cursor:pointer;inset:0;background:#3a3a5a;border-radius:24px;transition:.3s}}
.toggle-slider::before{{content:'';position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s}}
input:checked+.toggle-slider{{background:var(--accent)}}
input:checked+.toggle-slider::before{{transform:translateX(20px)}}
.phone-wrapper{{position:relative;display:inline-block;flex-shrink:0}}
.phone{{width:375px;background:#fff;border-radius:28px;overflow:hidden;box-shadow:0 0 0 3px #333,0 0 0 6px #222,0 0 0 8px #444,0 12px 40px rgba(0,0,0,.5);position:relative}}
.phone-notch{{height:28px;background:#111;display:flex;justify-content:center;align-items:flex-end;padding-bottom:4px;border-radius:28px 28px 0 0}}
.phone-notch::after{{content:'';width:80px;height:4px;background:#333;border-radius:2px}}
.phone-screen{{position:relative;overflow:hidden}}
.phone-content{{padding:0 14px 24px;min-height:calc(100vh - 160px);background:#fff;color:#3f3f3f;overflow-y:auto;overflow-x:hidden;max-height:calc(100vh - 160px);position:relative;border-radius:0 0 28px 28px}}
.phone-content * {{max-width:100%!important;word-break:break-word}}
.phone-content pre,.phone-content pre * {{max-width:none!important;white-space:pre!important;word-break:normal!important}}
.loading{{display:flex;align-items:center;justify-content:center;height:400px;color:#999;font-size:14px}}
.error{{color:#e94560;padding:20px;text-align:center}}
.badge{{font-size:11px;padding:3px 8px;border-radius:10px;background:#0f02;color:var(--accent);border:1px solid #0f03}}
.actions{{display:flex;gap:8px;align-items:center}}
.btn{{padding:6px 12px;border-radius:6px;border:1px solid #3a3a5a;background:#1a1a2e;color:var(--ink);font-size:12px;cursor:pointer;text-decoration:none;white-space:nowrap}}
.btn:hover{{border-color:var(--accent)}}
.spinner{{display:inline-block;width:16px;height:16px;border:2px solid #3a3a5a;border-top-color:#07C160;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.progress-log{{position:absolute;bottom:0;left:0;right:0;max-height:200px;overflow-y:auto;padding:12px 14px;font-size:12px;color:#7c7c94;font-family:SF Mono,monospace;pointer-events:none}}
.progress-log div{{line-height:1.6;white-space:nowrap}}
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
  <div class="phone-wrapper">
  <div class="phone">
    <div class="phone-notch"></div>
    <div class="phone-screen">
    <div class="phone-content" id="phoneContent">
      <div class="loading">加载中...</div>
    </div>
    <div class="phone-dock">
      <button class="dock-icon" onclick="toggleLog()" title="渲染日志">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      </button>
      <button class="dock-icon" onclick="toggleSettings()" title="设置">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      </button>
    </div>
    <!-- Sheet panels (手机内) -->
    <div class="sheet-backdrop" id="sheetBackdrop" onclick="closePanels()"></div>
    <div class="sheet-panel sheet-bottom" id="logSheet">
      <div style="width:40px;height:4px;background:#ddd;border-radius:2px;margin:0 auto 12px"></div>
      <div id="logContentSheet" class="log-area"></div>
    </div>
    <div class="sheet-panel sheet-top" id="settingsSheet">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <h3 style="margin:0;font-size:15px">⚙️ 设置</h3>
        <button onclick="closePanels()" style="background:none;border:none;color:#999;cursor:pointer;font-size:18px">✕</button>
      </div>
      <div id="settingsInner"></div>
      <div style="width:40px;height:4px;background:#ddd;border-radius:2px;margin:8px auto 0"></div>
    </div>
    </div>
  </div>
  <!-- Proj panels (手机外, inside phone-wrapper) -->
    <div class="proj-panel proj-left panel-external" id="logPanel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:14px;color:var(--ink)">📋 渲染日志</h3>
        <button onclick="closePanels()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px">✕</button>
      </div>
      <div id="logContentProj" class="log-area"></div>
    </div>
    <div class="proj-panel proj-right panel-external" id="settingsPanel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:14px;color:var(--ink)">⚙️ 设置</h3>
        <button onclick="closePanels()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px">✕</button>
      </div>
      <div id="settingsInnerExt"></div>
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
  let log = [];
  let startTime = Date.now();
  const elapsed = () => Math.floor((Date.now() - startTime) / 1000);

  const updateLoading = (step, done) => {{
    const ts = '[' + elapsed() + 's]';
    if (!done) {{
      log.push(ts + ' ' + step + '...');
      addLogEntry(ts + ' ' + step + '...', '');
    }} else {{
      log.push('<span style=\"color:#3ecf8e\">' + ts + ' ✓ ' + step + '</span>');
      addLogEntry(ts + ' ✓ ' + step, 'ok');
    }}
    const entries = log.slice(-12).map(e => '<div>' + e + '</div>').join('');
    const current = log[log.length-1];
    const isDone = current && current.includes('✓');
    const html = '<div class=\"loading\">'
      + (isDone ? '✅ 完成' : '<span class=\"spinner\"></span>' + (step + '...'))
      + '</div>'
      + '<div class=\"progress-log\">' + entries + '</div>';
    document.getElementById('phoneContent').innerHTML = html;
  }};

  updateLoading('预处理', false);

  const url = '/api/render/' + SLUG + (theme ? '?theme=' + encodeURIComponent(theme) : '');
  const es = new EventSource(url);
  es.addEventListener('progress', (e) => {{
    const data = JSON.parse(e.data);
    if (data.status === 'running') updateLoading(data.step, false);
    else if (data.status === 'done') updateLoading(data.step, true);
  }});
  es.addEventListener('result', (e) => {{
    es.close();
    const data = JSON.parse(e.data);
    document.getElementById('phoneContent').innerHTML = data.html + '<div class=\"progress-log\" style=\"background:none;color:#3ecf8e\">✅ 完成 (预处理:' + (data.steps['预处理']||'') + ' 排版:' + (data.steps['排版']||'') + ')</div>';
    setTimeout(() => {{ const log = document.querySelector('.progress-log'); if (log) log.style.display = 'none'; }}, 3000);
    addLogEntry('✅ 完成', 'ok');
    renderLog = [];
    copyHTMLData = data.copy_html || data.html;
    if (data.steps) {{
      let info = [];
      for (const [k,v] of Object.entries(data.steps)) info.push(k + ': ' + v);
      const badge = document.querySelector('.badge');
      if (badge) badge.title = info.join(', ');
    }}
  }});
  es.addEventListener('error', (e) => {{
    es.close();
    let msg = '渲染失败';
    try {{ const d = JSON.parse(e.data); msg = d.error || msg; }} catch(_) {{}}
    document.getElementById('phoneContent').innerHTML = '<div class=\"error\">' + msg + '</div>';
  }});
  es.onerror = (e) => {{ if (es.readyState === EventSource.CLOSED) {{ es.close(); }} }};
}}

let isExternalMode = false;

// Shared settings content
(function initSettings() {{
  const html = '<label style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;font-size:14px;color:inherit">深色模式<label class="toggle-switch"><input type="checkbox" id="darkToggle" onchange="togglePhoneTheme(this.checked)"><span class="toggle-slider"></span></label></label><label style="padding:12px 0;font-size:14px;color:inherit"><div style="display:flex;justify-content:space-between;margin-bottom:6px"><span>字体大小</span><span id="fontSizeLabel" style="opacity:.7">16px</span></div><input type="range" min="12" max="22" value="16" oninput="setFontSize(this.value)" style="width:100%;accent-color:#07C160"></label><label style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;font-size:14px;color:inherit">手机外投影<label class="toggle-switch"><input type="checkbox" id="projToggle" onchange="toggleProjectionMode(this.checked)"><span class="toggle-slider"></span></label></label>';
  document.getElementById('settingsInner').innerHTML = html;
  document.getElementById('settingsInnerExt').innerHTML = html;
}})();

function setFontSize(px) {{
  document.getElementById('fontSizeLabel').textContent = px + 'px';
  document.querySelector('.phone-content').style.zoom = (px / 16);
}}

function addLogEntry(msg, type) {{
  const cls = type === 'ok' ? 'ok' : (type === 'fail' ? 'fail' : '');
  const entry = '<div class="log-entry ' + cls + '">' + msg + '</div>';
  document.querySelectorAll('.log-area').forEach(el => {{
    el.innerHTML += entry; el.scrollTop = el.scrollHeight;
  }});
}}

let activePanel = null;

function toggleLog() {{
  const logId = isExternalMode ? 'logPanel' : 'logSheet';
  const el = document.getElementById(logId);
  const wasOpen = el.classList.contains('open');
  closePanels();
  if (!wasOpen) {{
    el.classList.add('open');
    activePanel = logId;
    if (!isExternalMode) document.getElementById('sheetBackdrop').classList.add('show');
  }}
}}

function toggleSettings() {{
  const setId = isExternalMode ? 'settingsPanel' : 'settingsSheet';
  const el = document.getElementById(setId);
  const wasOpen = el.classList.contains('open');
  closePanels();
  if (!wasOpen) {{
    el.classList.add('open');
    activePanel = setId;
    if (!isExternalMode) document.getElementById('sheetBackdrop').classList.add('show');
  }}
}}

function closePanels() {{
  document.querySelectorAll('.proj-panel,.sheet-panel').forEach(p => p.classList.remove('open'));
  document.getElementById('sheetBackdrop').classList.remove('show');
  activePanel = null;
}}

function togglePhoneTheme(dark) {{
  document.querySelector('.phone').classList.toggle('dark', dark);
}}

function toggleProjectionMode(external) {{
  isExternalMode = external;
  closePanels();
  document.querySelectorAll('.panel-external').forEach(p => p.classList.toggle('show', external));
  document.querySelectorAll('.panel-internal').forEach(p => p.classList.toggle('hide', external));
}}

function switchTheme(theme) {{ render(theme); }}

function fallbackCopy(btn) {{
  navigator.clipboard.writeText(document.getElementById('phoneContent').innerText).then(() => {{
    btn.textContent = '✅ 已复制(纯文本)';
    setTimeout(() => btn.textContent = '📋 复制 HTML', 1500);
  }}).catch(() => alert('复制失败，请手动全选复制'));
}}

async function copyHTML(btn) {{
  if (!copyHTMLData) return;
  try {{
    let html = copyHTMLData;
    const container = document.createElement('div');
    container.innerHTML = html;
    // Inject highlight.js colors as inline styles (WeChat-safe)
    const hljsMap = {{
      keyword:'#c678dd', string:'#98c379', number:'#d19a66', comment:'#5c6370',
      function:'#61afef', attr:'#d19a66', built_in:'#e6c07b', type:'#e6c07b',
      literal:'#d19a66', title:'#61afef', meta:'#61afef', punctuation:'#abb2bf',
      params:'#abb2bf', 'selector-class':'#e6c07b'
    }};
    container.querySelectorAll('[class*=\"hljs-\"]').forEach(el => {{
      for (const cls of el.classList) {{
        if (hljsMap[cls.replace('hljs-','')]) {{
          el.style.color = hljsMap[cls.replace('hljs-','')];
        }}
      }}
    }});
    // Fallback: Canvas convert any remaining inline SVGs
    const svgs = container.querySelectorAll('svg');
    if (svgs.length > 0) {{
      btn.textContent = '⏳ 转换中...';
      for (const svg of svgs) {{
        try {{
          const svgData = new XMLSerializer().serializeToString(svg);
          const b64 = btoa(unescape(encodeURIComponent(svgData)));
          svg.outerHTML = '<img src=\"data:image/svg+xml;base64,' + b64 + '\" style=\"max-width:100%;height:auto;display:block;margin:1.2em auto\" width=\"100%\" alt=\"diagram\"/>';
        }} catch(e) {{}}
      }}
    }}
    html = container.innerHTML;
    const blob = new Blob([html], {{type: 'text/html'}});
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
                    # Chromium headless: full browser engine, perfect foreignObject/text
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

        # Step 1: 预处理 (with sub-step progress)
        yield sse("progress", {"step": "预处理", "status": "running"})
        t0 = time.time()
        clean_task = loop.run_in_executor(None, clean_hugo, md_body, app.state.base_url, on_progress)

        # Drain progress events while clean_hugo runs
        while not clean_task.done():
            async for evt in drain_progress():
                yield evt
            await asyncio.sleep(0.1)
        try:
            md_body = await clean_task
        except Exception as e:
            yield sse("error", {"error": f"预处理失败: {e}"})
            return
        # Drain any remaining progress
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

    print(f"📱 微信预览服务器 (FastAPI)")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   内容: {app.state.content_dir}")
    print(f"   API:  {app.state.api_base}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
