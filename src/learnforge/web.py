"""本地网页版：`lf serve` 在 127.0.0.1 上起一个小服务，浏览器打开就能刷题、看复习面板。

和 MCP 服务用同一个界面文件（ui/app.html）、同一组工具（service.TOOLS），数据也是同一份。
需要 AI 讲题时：配置了 API key 就直接调（OpenAI 兼容接口，默认 DeepSeek）；没配就给一段提示词，
复制到任何 AI 聊天里（DeepSeek 网页版、豆包、ChatGPT……）都能用。
/host-test 是一个最小的 MCP Apps 宿主模拟器，用来在本机测试“聊天里的界面”那条路径。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

from . import service
from .mcp_server import ui_html
from .store import CONFIG, Data, LFError

HOST_TEST = """<!doctype html><html><head><meta charset="utf-8"><title>MCP Apps 宿主模拟器</title>
<style>body{font:14px -apple-system,sans-serif;margin:0;display:grid;grid-template-columns:1fr 320px;height:100vh}
iframe{width:100%;border:0;border-right:1px solid #ddd}#log{padding:12px;overflow:auto;background:#f6f5f1}
#log div{margin:0 0 8px;white-space:pre-wrap;word-break:break-all}.chat{color:#185fa5}</style></head><body>
<iframe id="f" src="/app.html"></iframe><div id="log"><b>宿主日志</b></div>
<script>
const f=document.getElementById('f'),log=document.getElementById('log');
const tool=new URLSearchParams(location.search).get('tool')||'lf_quiz';
const args=JSON.parse(new URLSearchParams(location.search).get('args')||'{"pack":"os","count":3}');
const theme=new URLSearchParams(location.search).get('theme')||'light';
document.body.style.background=theme==='dark'?'#1f1e1c':'#fff';
const hostVars={'--color-background-primary':'light-dark(#ffffff, #30302e)','--color-text-primary':'light-dark(#141413, #faf9f5)','--color-border-primary':'light-dark(rgba(0,0,0,.15), rgba(255,255,255,.15))'};
function L(t,c){const d=document.createElement('div');if(c)d.className=c;d.textContent=t;log.appendChild(d);log.scrollTop=1e9}
async function call(name,a){const r=await fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,arguments:a})});const j=await r.json();
 if(j.error)return{content:[{type:'text',text:j.error}],isError:true};return{content:[{type:'text',text:j.text}],structuredContent:j.data}}
function send(m){f.contentWindow.postMessage(m,'*')}
window.addEventListener('message',async e=>{const m=e.data;if(!m||m.jsonrpc!=='2.0')return;L('← '+m.method+(m.params&&m.method!=='ui/notifications/size-changed'?' '+JSON.stringify(m.params).slice(0,160):''));
 if(m.method==='ui/initialize')send({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'host-test',version:'1'},hostCapabilities:{},hostContext:{theme,styles:{variables:hostVars}}}});
 else if(m.method==='ui/notifications/initialized'){const r=await call(tool,args);send({jsonrpc:'2.0',method:'ui/notifications/tool-input',params:{arguments:args}});send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:r});L('→ tool-result '+tool)}
 else if(m.method==='tools/call'){const r=await call(m.params.name,m.params.arguments);send({jsonrpc:'2.0',id:m.id,result:r});L('→ result '+m.params.name)}
 else if(m.method==='ui/message'){L('聊天收到：'+m.params.content.map(c=>c.text).join(''),'chat');send({jsonrpc:'2.0',id:m.id,result:{}})}
 else if(m.method==='ui/notifications/size-changed'){f.style.height=m.params.height+'px'}
 else if(m.id!=null)send({jsonrpc:'2.0',id:m.id,result:{}})});
</script></body></html>"""


def llm_config(data: Data) -> dict:
    cfg = {}
    if CONFIG.exists():
        cfg.update((yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("llm") or {})
    cfg.update(data.cfg.get("llm") or {})
    cfg.setdefault("base_url", "https://api.deepseek.com")
    cfg.setdefault("model", "deepseek-chat")
    cfg.setdefault("api_key_env", "DEEPSEEK_API_KEY")
    return cfg


def build_prompt(data: Data, q: str | None, mode: str, text: str) -> str:
    if mode.startswith("teach:"):
        cid = mode.split(":", 1)[1]
        notes = data.p("learner", "teaching-notes.md")
        return (f"你是我的期末复习老师。请讲解知识点「{cid}」：先用一句话说它解决什么问题，再讲机制，"
                f"给一个小例子，最后问我一个“为什么”的问题检查我是否理解。用中文，结论先行。\n"
                f"对我有效的讲法记录：\n{notes.read_text(encoding='utf-8') if notes.exists() else '（无）'}\n\n我的请求：{text}")
    ctx = service.explain_context(data, q)["data"]
    if mode == "grade":
        return ("你是阅卷老师。按下面的 rubric 逐条给我的答案打分，每条说得了几分、差在哪。"
                "最后单独一行写“得分率：0~1 的小数”，再单独一行写“错因：concept/confusion/reading/calc/procedure/time/format 之一”"
                "（满分就写“错因：无”）。\n" + json.dumps(ctx, ensure_ascii=False, default=str) + f"\n\n我的请求：{text}")
    return ("你是我的期末复习老师。我答错了下面这道题。请先用一句话指出我错在哪一步，再讲为什么，"
            "计算过程以 verifier_traces 为准，不要自己重算；最后出一道同类的小题让我练。用中文，简洁。\n"
            + json.dumps(ctx, ensure_ascii=False, default=str) + f"\n\n我的请求：{text}")


def call_llm(cfg: dict, prompt: str) -> str:
    key = os.environ.get(cfg["api_key_env"]) or cfg.get("api_key")
    if not key:
        raise LFError("no-key")
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps({"model": cfg["model"], "messages": [{"role": "user", "content": prompt}],
                                                  "temperature": 0.3}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: str, ctype: str = "application/json; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/app.html"):
            return self._send(200, ui_html(), "text/html; charset=utf-8")
        if path == "/host-test":
            return self._send(200, HOST_TEST, "text/html; charset=utf-8")
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        data = Data()
        try:
            if self.path == "/api/call":
                r = service.call(body["name"], body.get("arguments") or {}, data)
                return self._send(200, json.dumps({"text": r["text"], "data": r["data"]}, ensure_ascii=False, default=str))
            if self.path == "/api/explain":
                mode, q = body.get("mode", "explain"), body.get("q")
                prompt = build_prompt(data, q, mode, body.get("text", ""))
                cfg = llm_config(data)
                try:
                    text = call_llm(cfg, prompt)
                except LFError:
                    return self._send(200, json.dumps({"prompt": prompt, "note": f"没有找到 API key（环境变量 {cfg['api_key_env']}）。"
                                                       "把下面的提示词复制到任意 AI 聊天里（DeepSeek、豆包、ChatGPT 都行）："},
                                                      ensure_ascii=False))
                if mode == "grade" and q:
                    m = re.search(r"得分率[:：]\s*([01](?:\.\d+)?)", text)
                    c = re.search(r"错因[:：]\s*(concept|confusion|reading|calc|procedure|time|format)", text)
                    if m:
                        service.grade_subjective(data, q, float(m.group(1)), cause=c.group(1) if c else None,
                                                 feedback=text[:500])
                        text += "\n\n（已按这个得分率记入账本）"
                return self._send(200, json.dumps({"text": text}, ensure_ascii=False))
            self._send(404, json.dumps({"error": "not found"}))
        except (LFError, KeyError, TypeError, ValueError) as e:
            self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        except Exception as e:  # 讲题接口的网络错误等
            self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


def serve(port: int = 8765, open_browser: bool = False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"LearnForge 网页版：{url}（Ctrl+C 退出）", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
