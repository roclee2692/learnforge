"""工具层：MCP 服务和本地网页共用的同一组工具。

每个工具接收参数 dict，返回 {"text": 给模型/纯文字宿主看的文字, "data": 给界面用的结构化数据}。
规则写在这里而不是提示词里：答案只在提交后才返回，判分只由引擎做，错因只能选固定词表。
"""
from __future__ import annotations

import json

from . import book, grade as grading, model, verifiers
from .store import Data, LFError, append_jsonl, stamp

UI_URI = "ui://learnforge/app.html"


def _public(q: dict) -> dict:
    """出给作答者的题目：不含答案、解析、评分要点、验算配置。"""
    out = {k: q[k] for k in ("id", "type", "score", "stem", "options", "concept") if k in q}
    if q["type"] == "calc" and isinstance(q.get("answer"), dict):
        out["answer_keys"] = list(q["answer"])
    if q["type"] == "fill":
        out["blanks"] = len(q["answer"]) if isinstance(q.get("answer"), list) else 1
    out["hint_levels"] = len(q.get("hints") or [])
    return out


def _quiz_text(title: str, qs: list) -> str:
    lines = [f"{title}（{len(qs)} 题，共 {sum(q.get('score', 0) for q in qs)} 分）"]
    for i, q in enumerate(qs, 1):
        lines.append(f"{i}. [{q['id']} · {q['type']} · {q.get('score', '?')} 分] {q['stem']}")
        for k, v in (q.get("options") or {}).items():
            lines.append(f"   {k}. {v}")
        if q.get("answer_keys"):
            lines.append(f"   （依次给出：{'、'.join(q['answer_keys'])}）")
    lines.append("作答后用 lf_submit 提交；不要把答案告诉用户。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 出题

def quiz(data: Data, pack: str = "os", paper: str | None = "diag", concept: str | None = None,
         count: int = 10, only_new: bool = True, ids: list | None = None) -> dict:
    bank = data.bank()
    done = {a["q"] for a in data.attempts()}
    if ids:
        qs = [bank[i] for i in ids if i in bank]
    else:
        qs = [q for q in bank.values() if data.pack_of(q) == pack]
        if paper:
            qs = [q for q in qs if paper in q.get("papers", [])]
        if concept:
            qs = [q for q in qs if any(c.startswith(concept) for c in q.get("concept", []))]
        if only_new:
            qs = [q for q in qs if q["id"] not in done]
        qs.sort(key=lambda q: q["id"])
        qs = qs[:count]
    pub = [_public(q) for q in qs]
    title = f"{data.pack(pack).get('name', pack)} · {paper or concept or '练习'}" if not ids else "练习"
    if not pub:
        return {"text": "没有符合条件的未做题目。可以换知识点，或者用 lf_add_question 现场出题。",
                "data": {"view": "quiz", "title": title, "questions": []}}
    return {"text": _quiz_text(title, pub),
            "data": {"view": "quiz", "title": title, "pack": pack, "questions": pub,
                     "causes": model.CAUSE_NAMES}}


def practice(data: Data, pack: str | None = None, minutes: int = 30) -> dict:
    """按今日建议挑题：未订正的错题和推荐的新题。"""
    r = model.today(data, minutes, pack)
    ids = []
    for it in r["plan"]:
        ids += [q for q in it["questions"] if q not in ids]
    out = quiz(data, ids=ids[:10]) if ids else quiz(data, pack or "os")
    out["data"]["title"] = "按今日建议练习"
    return out


def hint(data: Data, q: str, level: int = 1) -> dict:
    qq = data.question(q)
    hints = qq.get("hints") or []
    if not hints:
        return {"text": "这道题没有预设提示，请按“方向 → 关键步骤 → 差一步”自己给三级提示。",
                "data": {"q": q, "level": 0, "of": 0, "hint": None}}
    lvl = max(1, min(level, len(hints)))
    return {"text": f"提示 {lvl}/{len(hints)}：{hints[lvl - 1]}",
            "data": {"q": q, "level": lvl, "of": len(hints), "hint": hints[lvl - 1]}}


# ---------------------------------------------------------------- 提交与记录

def submit(data: Data, answers: list) -> dict:
    """批量提交：客观题当场判分并记账；主观题记为待批改，返回评分要点给模型。"""
    results, pending = [], []
    open_err = data.open_errors()
    for a in answers:
        q = data.question(a["q"])
        given = a.get("given")
        item = {"q": q["id"], "type": q["type"], "score_max": q.get("score", 0)}
        try:
            if given in (None, "", {}, []):  # “不会，跳过”：记为 0 分，不进入待批改
                res = {"auto": True, "correct": False, "score": 0.0, "feedback": "未作答"}
            else:
                res = grading.grade(data, q, given)
        except LFError as e:  # 格式不对的单题不影响整组提交
            item.update({"status": "invalid", "feedback": str(e)})
            results.append(item)
            continue
        if not res["auto"]:
            pending.append({"q": q["id"], "given": given, "rubric": q.get("rubric", []),
                            "reference": q.get("answer"), "hints_used": a.get("hints", 0)})
            item.update({"status": "pending", "reference": q.get("answer"), "explain": q.get("explain"),
                         "rubric": q.get("rubric", [])})
            results.append(item)
            continue
        rec = {"t": stamp(), "q": q["id"], "mode": a.get("mode", "quiz"), "correct": bool(res["correct"]),
               "score": res["score"], "given": given, "hints_used": a.get("hints", 0),
               "seconds": a.get("seconds"), "confidence": a.get("confidence")}
        append_jsonl(data.attempts_path, rec)
        if res["correct"] and q["id"] in open_err:
            append_jsonl(data.errors_path, {"t": rec["t"], "q": q["id"], "event": "fix"})
        item.update({"status": "correct" if res["correct"] else "wrong", "score": res["score"],
                     "feedback": res.get("feedback", ""), "answer": q.get("answer"), "explain": q.get("explain")})
        results.append(item)
    got = sum(r["score"] * r["score_max"] for r in results if r.get("score") is not None)
    tot = sum(r["score_max"] for r in results if r["status"] in ("correct", "wrong"))
    wrong = [r["q"] for r in results if r["status"] == "wrong"]
    lines = [f"已判分并记入账本：客观题 {round(got, 1)}/{tot} 分。"]
    for r in results:
        mark = {"correct": "✓", "wrong": "✗", "pending": "待批改", "invalid": "格式不对，未记录"}[r["status"]]
        lines.append(f"- {r['q']} {mark} {r.get('feedback', '')}")
    if wrong:
        lines.append("答错的题需要标错因（lf_tag_error，固定词表：" + "、".join(model.CAUSES) + "），"
                     "拿不准时先问用户一句。")
    if pending:
        lines.append("主观题请按 rubric 逐条打分后调用 lf_grade_subjective：" +
                     json.dumps(pending, ensure_ascii=False))
    return {"text": "\n".join(lines),
            "data": {"view": "result", "results": results, "got": round(got, 1), "total": tot,
                     "causes": model.CAUSE_NAMES}}


def grade_subjective(data: Data, q: str, score: float, given: str = "", cause: str | None = None,
                     detail: str = "", feedback: str = "") -> dict:
    qq = data.question(q)
    if not 0 <= score <= 1:
        raise LFError("score 是 0~1 的得分率")
    rec = {"t": stamp(), "q": q, "mode": "quiz", "correct": score >= 0.999, "score": score, "given": given,
           "hints_used": 0, "grader": "model", "feedback": feedback}
    append_jsonl(data.attempts_path, rec)
    if cause:
        tag_error(data, q, cause, detail)
    return {"text": f"{q} 记为得分率 {score:.0%}" + (f"，错因 {model.CAUSE_NAMES[cause]}" if cause else ""),
            "data": {"q": q, "score": score, "score_max": qq.get("score")}}


def tag_error(data: Data, q: str, cause: str, detail: str = "") -> dict:
    if cause not in model.CAUSES:
        raise LFError(f"错因只能用固定词表：{', '.join(model.CAUSES)}")
    qq = data.question(q)
    e = {"t": stamp(), "q": q, "concept": qq["concept"], "cause": cause, "detail": detail, "event": "open"}
    append_jsonl(data.errors_path, e)
    return {"text": f"{q} 已记错因：{model.CAUSE_NAMES[cause]} {detail}", "data": e}


def explain_context(data: Data, q: str) -> dict:
    """讲题素材：题目、参考答案、解析、用户最近一次作答、验算器逐步过程。模型据此讲解。"""
    qq = data.question(q)
    last = next((a for a in reversed(data.attempts()) if a["q"] == q), None)
    traces = []
    specs = qq.get("verify") or []
    for sp in specs if isinstance(specs, list) else [specs]:
        try:
            r = verifiers.get(sp["fn"])(**sp.get("args", {}))
            traces.append({"fn": sp["fn"], "args": sp.get("args"), "result": r})
        except Exception as e:  # 讲题时验算失败不阻断
            traces.append({"fn": sp["fn"], "error": str(e)})
    ctx = {"question": {k: qq.get(k) for k in ("id", "type", "stem", "options", "answer", "explain", "rubric")},
           "last_attempt": last, "open_error": data.open_errors().get(q), "verifier_traces": traces}
    return {"text": "讲题规则：先说错在哪一步，再讲为什么，最后给一道同类题；计算过程以 verifier_traces 为准，"
                    "不要自己心算。\n" + json.dumps(ctx, ensure_ascii=False, default=str), "data": ctx}


# ---------------------------------------------------------------- 复习与统计

def dashboard(data: Data, pack: str | None = None, minutes: int | None = None) -> dict:
    t = model.today(data, minutes, pack)
    s = model.stats(data, pack)
    lines = [f"今天 {t['minutes']} 分钟的建议："]
    for i, it in enumerate(t["plan"], 1):
        lines.append(f"{i}. [{it['kind']}] {it['name']}：" + "；".join(it["reasons"]) +
                     (f"（题目 {' '.join(it['questions'])}）" if it["questions"] else ""))
    for p, st in s.items():
        lines.append(f"{p}：预测分（粗估）{st['predicted_score']}，" +
                     "，".join(f"{model.STATUS_NAMES[k]} {v}" for k, v in st["status_count"].items()))
    return {"text": "\n".join(lines),
            "data": {"view": "dashboard", "today": t, "stats": s, "status_names": model.STATUS_NAMES,
                     "cause_names": model.CAUSE_NAMES}}


def calc(data: Data, name: str, args: dict | None = None) -> dict:
    r = verifiers.get(name)(**(args or {}))
    return {"text": json.dumps(r, ensure_ascii=False), "data": r}


def add_question(data: Data, question: dict) -> dict:
    q = data.add_question(dict(question))
    v = grading.verify(data, q) if (q.get("verify") or q["type"] == "sql") else {"ok": None}
    return {"text": f"已入库 {q['id']}；验算：{v['reason'] if v['ok'] is not None else '无'}",
            "data": {"id": q["id"], "verify": v}}


def book_find(data: Data, pack: str, query: str, k: int = 5) -> dict:
    hits = book.find(data, pack, query, k)
    return {"text": "\n".join(f"[{h['book']} p.{h['page']}] {h['snippet']}" for h in hits), "data": {"hits": hits}}


# ---------------------------------------------------------------- 工具清单

S = lambda **p: {"type": "object", "properties": p}  # noqa: E731
STR, INT, NUM = {"type": "string"}, {"type": "integer"}, {"type": "number"}

TOOLS = [
    {"name": "lf_quiz", "fn": quiz, "ui": True,
     "description": "出一组题（默认是诊断卷里还没做的前 10 题），在界面里显示为可作答的题卡。答案不会下发，提交后由引擎判分。"
                    "pack：os（操作系统）或 db（数据库）；paper：试卷名，默认 diag；concept：只出某个知识点前缀的题。",
     "schema": S(pack=STR, paper=STR, concept=STR, count=INT, only_new={"type": "boolean"},
                 ids={"type": "array", "items": STR})},
    {"name": "lf_practice", "fn": practice, "ui": True,
     "description": "按今日复习建议挑一组题（未订正的错题优先），显示为题卡。",
     "schema": S(pack=STR, minutes=INT)},
    {"name": "lf_dashboard", "fn": dashboard, "ui": True,
     "description": "今日复习建议 + 各章掌握度 + 错因分布，显示为面板。用户问“今天学什么”“我准备得怎么样”时调用。"
                    "不催促、不设提醒。",
     "schema": S(pack=STR, minutes=INT)},
    {"name": "lf_submit", "fn": submit, "visibility": ["model", "app"],
     "description": "提交作答并判分、记账。answers：[{q: 题号, given: 作答, hints: 用了几级提示, seconds, confidence}]。"
                    "计算题的 given 用对象，键名照题目的 answer_keys；多空填空用 | 分隔。主观题会返回 rubric 待你批改。",
     "schema": {"type": "object", "required": ["answers"], "properties": {"answers": {"type": "array", "items": {
         "type": "object", "required": ["q"], "properties": {"q": STR, "given": {}, "hints": INT,
                                                              "seconds": INT, "confidence": NUM}}}}}},
    {"name": "lf_hint", "fn": hint, "visibility": ["model", "app"],
     "description": "取某题的第 level 级提示（1~3）。三级提示用完才给答案。",
     "schema": {"type": "object", "required": ["q"], "properties": {"q": STR, "level": INT}}},
    {"name": "lf_tag_error", "fn": tag_error, "visibility": ["model", "app"],
     "description": "给答错的题记错因。cause 只能是 concept / confusion / reading / calc / procedure / time / format；"
                    "detail 写一句具体到步骤的话。",
     "schema": {"type": "object", "required": ["q", "cause"], "properties": {"q": STR, "cause": STR, "detail": STR}}},
    {"name": "lf_grade_subjective", "fn": grade_subjective,
     "description": "记录你按 rubric 批改主观题的结果。score 是 0~1 的得分率；没满分时给 cause 和 detail。",
     "schema": {"type": "object", "required": ["q", "score"],
                "properties": {"q": STR, "score": NUM, "given": STR, "cause": STR, "detail": STR, "feedback": STR}}},
    {"name": "lf_explain_context", "fn": explain_context,
     "description": "讲题前调用：返回题目、参考答案、解析、用户的作答和验算器的逐步过程。讲解以它为准，不要心算。",
     "schema": {"type": "object", "required": ["q"], "properties": {"q": STR}}},
    {"name": "lf_calc", "fn": calc,
     "description": "调用确定性验算器（页面置换、调度、银行家、磁盘、闭包、候选码、范式、分解、可串行化、日志恢复等），"
                    "返回结果和逐步过程。name 例如 os.page_replace、db.keys。",
     "schema": {"type": "object", "required": ["name"], "properties": {"name": STR, "args": {"type": "object"}}}},
    {"name": "lf_add_question", "fn": add_question,
     "description": "把一道新题入库（现场出题、从试卷照片切出来的真题）。真题入库前必须先让用户确认切分结果。"
                    "计算题带 verify 字段会自动验算。",
     "schema": {"type": "object", "required": ["question"], "properties": {"question": {"type": "object"}}}},
    {"name": "lf_book_find", "fn": book_find,
     "description": "在已导入的教材里按关键词检索，返回页码和片段。",
     "schema": {"type": "object", "required": ["pack", "query"], "properties": {"pack": STR, "query": STR, "k": INT}}},
]


def call(name: str, args: dict, data: Data | None = None) -> dict:
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if not tool:
        raise LFError(f"没有工具 {name}")
    return tool["fn"](data or Data(), **(args or {}))
