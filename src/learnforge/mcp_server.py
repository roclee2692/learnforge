"""MCP 服务（stdio）。宿主（Claude 桌面版、Claude Code、Codex、DeepSeek Harness……）启动 `lf mcp` 拉起它。

只用标准库实现 JSON-RPC：initialize / tools/list / tools/call / resources/list / resources/read / ping。
支持 MCP Apps 扩展（io.modelcontextprotocol/ui，规范 2026-01-26）的宿主会把带 _meta.ui.resourceUri 的
工具结果渲染成交互界面；不支持的宿主只看到 content 里的文字，功能不受影响。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from importlib import resources
from pathlib import Path

from . import __version__, service
from .store import Data, LFError

MIME = "text/html;profile=mcp-app"
UI_EXT = "io.modelcontextprotocol/ui"
INSTRUCTIONS = (
    "LearnForge 学习引擎。出题用 lf_quiz / lf_practice（界面里作答），复习建议和进度用 lf_dashboard。"
    "判分只能用 lf_submit，不要自己判；答错要用 lf_tag_error 记错因（固定词表）。讲题前先调 lf_explain_context，"
    "计算过程以验算器为准。提示分三级（lf_hint），三级用完才给答案。不要读取 holdout/ 目录。"
)


LOG = Path(os.environ.get("LF_MCP_LOG", Path.home() / ".config" / "learnforge" / "mcp.log"))


def log(event: str, **kw):
    """排查宿主行为用：记录宿主发来的每个请求（方法名、工具名、客户端能力），不记录作答内容。"""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid(), "event": event, **kw},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def ui_html() -> str:
    return resources.files("learnforge").joinpath("ui/app.html").read_text(encoding="utf-8")


def ui_uri() -> str:
    """题卡地址带内容版本号：界面一改，地址就变，宿主不会继续用缓存里的旧界面。"""
    import hashlib
    return f"ui://learnforge/app-{hashlib.sha1(ui_html().encode()).hexdigest()[:8]}.html"


WEB_PORT = int(os.environ.get("LF_WEB_PORT", "8765"))


def ensure_web() -> str | None:
    """看不到题卡的通道（只回传文字）也要能做题：确保本机网页版在跑，返回它的地址。"""
    import socket
    import subprocess
    try:
        with socket.create_connection(("127.0.0.1", WEB_PORT), timeout=0.3):
            return f"http://127.0.0.1:{WEB_PORT}"
    except OSError:
        pass
    try:
        subprocess.Popen([sys.executable, "-m", "learnforge.cli", "serve", "--port", str(WEB_PORT)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(20):
            time.sleep(0.1)
            try:
                with socket.create_connection(("127.0.0.1", WEB_PORT), timeout=0.2):
                    log("web_started", port=WEB_PORT)
                    return f"http://127.0.0.1:{WEB_PORT}"
            except OSError:
                continue
    except OSError as e:
        log("web_failed", error=str(e))
    return None


def web_link(name: str, data: dict) -> str | None:
    base = ensure_web()
    if not base:
        return None
    if data.get("view") == "quiz" and data.get("questions"):
        return f"{base}/?view=quiz&ids={','.join(q['id'] for q in data['questions'])}"
    return f"{base}/?view=dashboard"


class Server:
    def __init__(self):
        self.client_ui = False

    def tools(self) -> list:
        out = []
        for t in service.TOOLS:
            meta = {}
            if t.get("ui"):
                meta = {"ui": {"resourceUri": ui_uri()}, "ui/resourceUri": ui_uri()}
            if t.get("visibility"):
                meta.setdefault("ui", {})["visibility"] = t["visibility"]
            item = {"name": t["name"], "description": t["description"], "inputSchema": t["schema"]}
            if meta:
                item["_meta"] = meta
            out.append(item)
        return out

    def handle(self, msg: dict):
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            log("initialize", client=params.get("clientInfo"), protocol=params.get("protocolVersion"),
                capabilities=params.get("capabilities"))
        elif method == "tools/call":
            log("tools/call", tool=params.get("name"))
        elif method != "ping":
            log(method, uri=params.get("uri"))
        if method == "initialize":
            caps = params.get("capabilities") or {}
            self.client_ui = UI_EXT in (caps.get("extensions") or {})
            return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}, "resources": {}, "extensions": {UI_EXT: {}}},
                    "serverInfo": {"name": "learnforge", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools()}
        if method == "resources/list":
            return {"resources": [{"uri": ui_uri(), "name": "LearnForge 界面",
                                   "description": "题卡、判分结果、复习面板", "mimeType": MIME}]}
        if method == "resources/read":
            uri = params.get("uri") or ""
            if not uri.startswith("ui://learnforge/app"):
                raise LFError(f"没有资源 {uri}")
            return {"contents": [{"uri": uri, "mimeType": MIME, "text": ui_html(),
                                  "_meta": {"ui": {"prefersBorder": True}}}]}
        if method == "tools/call":
            try:
                r = service.call(params["name"], params.get("arguments") or {}, Data())
            except (LFError, KeyError, TypeError, ValueError) as e:
                return {"content": [{"type": "text", "text": f"出错：{e}"}], "isError": True}
            text = r["text"]
            if params["name"] in ("lf_quiz", "lf_practice", "lf_dashboard"):
                link = web_link(params["name"], r["data"])
                if link:
                    text += (f"\n\n如果用户的对话里没有出现可点的题卡，把这个链接原样发给用户，在浏览器里作答，"
                             f"交卷后同样自动判分记账：{link}")
            return {"content": [{"type": "text", "text": text}],
                    "structuredContent": json.loads(json.dumps(r["data"], ensure_ascii=False, default=str))}
        raise NotImplementedError(method)


def main():
    srv = Server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:  # 通知（notifications/initialized 等）不用回复
            log("notification", method=msg.get("method"))
            continue
        try:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": srv.handle(msg)}
        except NotImplementedError as e:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"未实现：{e}"}}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
