"""判分。客观题直接比对；计算题逐项比对，答案不唯一的项交给 check 函数；SQL 题实际执行；
简答、设计、代码题返回 auto=False，由模型按 rubric 打分后用 lf record --score 记录。
"""
from __future__ import annotations

import re
import unicodedata

from . import verifiers
from .store import Data, LFError

OBJECTIVE = {"choice", "judge", "fill", "calc", "sql"}


def _n(s) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"[\s，,;；]+", "", s).rstrip("。.")


def _num_eq(a, b) -> bool:
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(fa - fb) <= max(0.01, 0.005 * abs(fb))


def _eq(given, ans) -> bool:
    if isinstance(ans, list):
        if isinstance(given, str):
            given = [g for g in re.split(r"[,，、\s→]+|->", given) if g]
        return isinstance(given, list) and len(given) == len(ans) and all(_eq(g, a) for g, a in zip(given, ans))
    if isinstance(ans, bool):
        return _judge(given) == ans
    if isinstance(ans, (int, float)) and not isinstance(ans, bool):
        return _num_eq(given, ans)
    return _n(given) == _n(ans) or _num_eq(given, ans)


def _judge(x):
    t = _n(x)
    if t in ("对", "正确", "是", "能", "可以", "安全", "t", "true", "√", "✓", "yes", "y", "1"):
        return True
    if t in ("错", "错误", "否", "不能", "不可以", "不安全", "f", "false", "×", "✗", "no", "n", "0"):
        return False
    return None


def grade(data: Data, q: dict, given) -> dict:
    t = q["type"]
    ans = q.get("answer")
    if t == "choice":
        g = "".join(sorted(ch for ch in _n(given).upper() if ch.isalpha()))
        a = "".join(sorted(str(ans).upper()))
        ok = g == a
        return {"auto": True, "correct": ok, "score": 1.0 if ok else 0.0,
                "feedback": "" if ok else f"正确答案 {ans}"}
    if t == "judge":
        ok = _judge(given) == bool(ans)
        return {"auto": True, "correct": ok, "score": 1.0 if ok else 0.0,
                "feedback": "" if ok else f"正确答案：{'对' if ans else '错'}"}
    if t == "fill":
        blanks = ans if isinstance(ans, list) else [ans]
        if isinstance(given, str):
            given = [g.strip() for g in re.split(r"[|｜]", given)] if len(blanks) > 1 else [given]
        if not isinstance(given, list):
            given = [given]
        hits = []
        for i, b in enumerate(blanks):
            alts = b if isinstance(b, list) else [b]
            hits.append(i < len(given) and any(_eq(given[i], a) for a in alts))
        score = sum(hits) / len(blanks)
        return {"auto": True, "correct": score == 1.0, "score": score,
                "feedback": "" if score == 1 else "错的空：" + "、".join(str(i + 1) for i, h in enumerate(hits) if not h)}
    if t == "calc":
        return _grade_calc(q, given)
    if t == "sql":
        ds = [str(data.resolve(q, d)) for d in q.get("datasets", [])]
        if not ds:
            raise LFError(f"{q['id']} 没有配置 datasets")
        ref = ans["sql"] if isinstance(ans, dict) else ans
        r = verifiers.get("db.grade_sql")(given, ref, ds, q.get("check_tables"))
        bad = [f"{d['dataset']}：{d['reason']}" for d in r["details"] if not d["ok"]]
        return {"auto": True, "correct": r["correct"], "score": 1.0 if r["correct"] else 0.0,
                "feedback": "；".join(bad)}
    return {"auto": False, "correct": None, "score": None,
            "feedback": "主观题：请按 rubric 打分，再用 lf record <qid> --score 记录",
            "rubric": q.get("rubric", []), "reference": ans}


def _grade_calc(q: dict, given) -> dict:
    ans = q.get("answer")
    checks = q.get("check", {})  # 字段 → {"fn":..., "args":...}，用于答案不唯一的字段
    if not isinstance(ans, dict):
        ok = _eq(given, ans)
        return {"auto": True, "correct": ok, "score": 1.0 if ok else 0.0, "feedback": "" if ok else f"答案 {ans}"}
    if not isinstance(given, dict):
        if len(ans) == 1:
            given = {next(iter(ans)): given}
        else:
            raise LFError(f"这道题要逐项作答，请按 JSON 给出这些键：{list(ans)}")
    wrong, notes = [], []
    for k, a in ans.items():
        if k not in given:
            wrong.append(k)
            continue
        if k in checks:
            spec = checks[k]
            r = verifiers.get(spec["fn"])(given[k], **spec.get("args", {}))
            if not r.get("correct"):
                wrong.append(k)
                notes.append(f"{k}：{r.get('reason', '')}")
        elif not _eq(given[k], a):
            wrong.append(k)
            notes.append(f"{k}：应为 {a}")
    score = 1 - len(wrong) / len(ans)
    return {"auto": True, "correct": not wrong, "score": round(score, 3), "wrong": wrong,
            "feedback": "；".join(notes)}


def verify(data: Data, q: dict) -> dict:
    """出题质检：用验算器重算答案，与题目里存的答案核对。"""
    if q["type"] == "sql":
        ref = q["answer"]["sql"] if isinstance(q["answer"], dict) else q["answer"]
        ds = [str(data.resolve(q, d)) for d in q.get("datasets", [])]
        if len(ds) < 2:
            return {"ok": False, "reason": "SQL 题至少要两个数据集"}
        try:
            r = verifiers.get("db.grade_sql")(ref, ref, ds, q.get("check_tables"))
        except ValueError as e:
            return {"ok": False, "reason": str(e)}
        return {"ok": r["correct"], "reason": "参考答案在所有数据集上可执行"}
    spec = q.get("verify")
    if not spec:
        return {"ok": None, "reason": "没有验算配置（非计算题，或需要人工/双次作答核对）"}
    ans = q["answer"] if isinstance(q["answer"], dict) else {"_": q["answer"]}
    checked, mism = set(), []
    for sp in spec if isinstance(spec, list) else [spec]:
        res = verifiers.get(sp["fn"])(**sp.get("args", {}))
        pick = sp.get("pick") or {k: k for k in ans if k in res}  # 答案字段 → 验算结果字段
        for k, field in pick.items():
            checked.add(k)
            if not _eq(ans[k], res.get(field)):
                mism.append(f"{k}: 题目答案 {ans[k]}，验算结果 {res.get(field)}")
    for k, sp in q.get("check", {}).items():
        checked.add(k)
        r = verifiers.get(sp["fn"])(ans[k], **sp.get("args", {}))
        if not r.get("correct"):
            mism.append(f"{k}: 参考答案没通过检查（{r.get('reason')}）")
    missing = [k for k in ans if k not in checked]
    if missing:
        mism.append(f"这些答案字段没有被验算覆盖：{missing}")
    return {"ok": not mism, "reason": "；".join(mism) or "答案与验算结果一致"}
