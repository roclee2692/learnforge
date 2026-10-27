"""掌握度、复习建议、统计。全部从 ledger/ 重新计算；mastery.json 只是缓存，删了可以重建。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime

from . import fsrs
from .store import Data, now

CAUSES = {  # 错因词表（固定，进化模块无权修改）→ 严重度
    "concept": 1.0, "confusion": 0.9, "procedure": 0.7, "reading": 0.5,
    "calc": 0.5, "time": 0.3, "format": 0.3,
}
CAUSE_NAMES = {"concept": "概念不懂", "confusion": "概念记混", "reading": "审题错", "calc": "计算错",
               "procedure": "步骤遗漏/顺序错", "time": "超时", "format": "格式不规范"}
HINT_PENALTY = 0.25   # 每用一级提示，这次作答的得分打 75 折
STATUS_NAMES = {"unseen": "未学", "weak": "薄弱", "shaky": "不稳", "ok": "还行", "solid": "牢固"}


def credit(a: dict) -> float:
    base = a["score"] if a.get("score") is not None else (1.0 if a.get("correct") else 0.0)
    return max(base * (1 - HINT_PENALTY * a.get("hints_used", 0)), 0.0)


def _day(t: str) -> date:
    return datetime.fromisoformat(t).date()


def mastery(data: Data) -> dict:
    bank = data.bank()
    concepts = {c["id"]: c for p in data.packs() for c in data.concept_map(p)}
    by_concept: dict = defaultdict(list)
    for a in data.attempts():
        cs = a.get("concept") or bank.get(a["q"], {}).get("concept", [])
        for c in ([cs] if isinstance(cs, str) else cs):
            by_concept[c].append(a)
    open_err = data.open_errors()
    today = now().date()
    out = {}
    for cid, c in concepts.items():
        atts = sorted(by_concept.get(cid, []), key=lambda a: a["t"])
        errs = Counter(e["cause"] for e in open_err.values()
                       if cid in ([e["concept"]] if isinstance(e.get("concept"), str) else e.get("concept", [])))
        rec = {"name": c["name"], "chapter": c["chapter_name"], "pack": c["pack"],
               "exam_weight": round(c["weight"], 4), "attempts": len(atts),
               "open_errors": dict(errs)}
        if not atts:
            out[cid] = {**rec, "status": "unseen"}
            continue
        days: dict = defaultdict(list)
        for a in atts:
            days[_day(a["t"])].append(a)
        s = d = None
        last_day, last_g = None, None
        for day in sorted(days):
            g = fsrs.rating([credit(a) for a in days[day]],
                            [a["confidence"] for a in days[day] if a.get("confidence") is not None])
            if s is None:
                s, d = fsrs.init(g)
            else:
                s, d = fsrs.review(s, d, (day - last_day).days, g)
            last_day, last_g = day, g
        r_now = fsrs.retrievability((today - last_day).days, s)
        total = sum(credit(a) for a in atts)
        acc = total / len(atts)
        if last_g == fsrs.AGAIN or acc < 0.5:
            status = "weak"
        elif r_now < 0.8 or errs:
            status = "shaky"
        elif r_now >= 0.9 and s >= 14:
            status = "solid"
        else:
            status = "ok"
        out[cid] = {**rec, "correct": round(total, 2), "acc": round(acc, 3),
                    "stability_days": round(s, 1), "difficulty": round(d, 2),
                    "last_seen": last_day.isoformat(), "r_now": round(r_now, 3), "status": status}
    data.p("learner").mkdir(exist_ok=True)
    data.p("learner", "mastery.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------------------------------------------------------------- 复习建议

def _days_to_exam(info: dict):
    ed = info.get("exam_date")
    if not ed:
        return None
    return (date.fromisoformat(str(ed)) - now().date()).days


def today(data: Data, minutes: int | None = None, pack: str | None = None) -> dict:
    cfg = data.cfg
    minutes = minutes or cfg.get("default_minutes", 60)
    every = cfg.get("review_every_days", 7)
    packs = [pack] if pack else data.packs()
    m = mastery(data)
    bank = data.bank()
    attempted = {a["q"] for a in data.attempts()}
    open_err = data.open_errors()

    items = []
    exam_info = {}
    for p in packs:
        info = data.pack(p)
        dte = _days_to_exam(info)
        exam_info[p] = {"exam_date": info.get("exam_date"), "days_left": dte}
        urgency = 1.5 if dte is not None and dte <= 14 else 1.2 if dte is not None and dte <= 30 else 1.0
        cmap = data.concept_map(p)
        for c in cmap:
            st = m[c["id"]]
            reasons = []
            if st["status"] == "unseen":
                blocked = [x for x in c["prereq"] if m.get(x, {}).get("status") in ("unseen", "weak")]
                if blocked:
                    continue
                gap = 1.0 if dte is not None and dte <= 14 else 0.5
                pri = c["weight"] * gap * urgency
                kind, cost = "new", 25
                reasons.append(f"还没学过，考试权重 {c['weight']:.0%}")
            else:
                r_next = fsrs.retrievability((now().date() - date.fromisoformat(st["last_seen"])).days + every,
                                             st["stability_days"])
                sev = min(sum(CAUSES.get(k, 0.5) * n for k, n in st["open_errors"].items()), 2.0)
                pri = c["weight"] * ((1 - r_next) + 0.15 * sev + (0.3 if st["status"] == "weak" else 0)) * urgency
                kind = "fix" if st["open_errors"] else "review"
                cost = min(10 + 5 * sum(st["open_errors"].values()), 25)
                reasons.append(f"{every} 天后记忆保持率约 {r_next:.0%}（上次 {st['last_seen']}，"
                               f"稳定度 {st['stability_days']} 天）")
                if st["status"] == "weak":
                    reasons.append(f"得分率 {st['acc']:.0%}，薄弱")
                if st["open_errors"]:
                    reasons.append("未订正错题：" + "、".join(f"{CAUSE_NAMES.get(k, k)}×{n}"
                                                       for k, n in st["open_errors"].items()))
                reasons.append(f"考试权重 {c['weight']:.0%}")
            qs = _pick_questions(c["id"], bank, attempted, open_err)
            items.append({"concept": c["id"], "name": c["name"], "pack": p, "kind": kind,
                          "priority": round(pri, 4), "minutes": cost, "reasons": reasons, "questions": qs})

    items.sort(key=lambda x: -x["priority"])
    plan, used = [], 0
    for it in items:
        if used + it["minutes"] <= minutes or not plan:
            plan.append(it)
            used += it["minutes"]
    drills = _drills(open_err)
    gaps = []
    for p in packs:
        dte = exam_info[p]["days_left"]
        if dte is not None and dte <= 14:
            cmap = data.concept_map(p)
            weak = [c for c in cmap if m[c["id"]]["status"] in ("unseen", "weak")]
            gaps += [{"concept": c["id"], "name": c["name"], "status": m[c["id"]]["status"],
                      "weight": round(c["weight"], 3)} for c in sorted(weak, key=lambda c: -c["weight"])[:8]]
    return {"minutes": minutes, "planned_minutes": used, "review_every_days": every, "exams": exam_info,
            "plan": plan, "drills": drills, "coverage_gaps": gaps}


def _pick_questions(cid: str, bank: dict, attempted: set, open_err: dict, k: int = 3) -> list:
    on = [q for q in bank.values() if cid in q.get("concept", []) and q.get("source") != "holdout"]
    redo = [q["id"] for q in on if q["id"] in open_err]
    fresh = sorted((q for q in on if q["id"] not in attempted),
                   key=lambda q: (q.get("source") != "real", q.get("difficulty", {}).get("est", 0.5)))
    return (redo + [q["id"] for q in fresh])[:k]


def _drills(open_err: dict) -> list:
    """同一知识点上同一错因累计 3 次 → 生成专项练习建议。"""
    cnt: Counter = Counter()
    for e in open_err.values():
        cs = [e["concept"]] if isinstance(e.get("concept"), str) else e.get("concept", [])
        for c in cs:
            cnt[(c, e["cause"])] += 1
    return [{"concept": c, "cause": cause, "count": n,
             "suggest": f"{c} 上「{CAUSE_NAMES.get(cause, cause)}」已出现 {n} 次，做一组专项练习"}
            for (c, cause), n in cnt.most_common() if n >= 3]


# ---------------------------------------------------------------- 统计

def stats(data: Data, pack: str | None = None) -> dict:
    m = mastery(data)
    packs = [pack] if pack else data.packs()
    all_err = data.errors()
    out = {}
    for p in packs:
        cmap = data.concept_map(p)
        chapters: dict = {}
        predicted = 0.0
        for c in cmap:
            st = m[c["id"]]
            chapters.setdefault(c["chapter_name"], []).append({"id": c["id"], **st})
            if st["status"] == "unseen":
                prob = 0.25
            else:
                smoothed = (st["correct"] + 1) / (st["attempts"] + 2)
                prob = smoothed * (0.5 + 0.5 * st["r_now"])
            predicted += c["weight"] * prob
        statuses = Counter(m[c["id"]]["status"] for c in cmap)
        causes = Counter(e["cause"] for e in all_err if e.get("event") != "fix"
                         and str(e.get("q", "")).startswith(p + "-"))
        out[p] = {"concepts": len(cmap), "status_count": dict(statuses), "chapters": chapters,
                  "error_causes": dict(causes), "predicted_score": round(predicted * 100, 1)}
    return out
