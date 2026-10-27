"""lf 命令行。所有命令都支持 --json，给宿主（Claude Code、Codex、Hermes……）解析用。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import book, grade as grading, model, verifiers
from .store import MARKER, Data, LFError, append_jsonl, read_jsonl, register, set_yaml_key, stamp

JSON = False


def emit(obj, human=None):
    if JSON or human is None:
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        human(obj)


def parse_given(s):
    if s == "-":
        s = sys.stdin.read()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


# ---------------------------------------------------------------- 初始化

DATA_FILES = {
    MARKER: "# LearnForge 数据仓库配置\nreview_every_days: 7      # 复习节奏由你定，系统只决定复习什么\n"
            "default_minutes: 60\n",
    "learner/profile.md": "# 学习偏好\n\n- 先给结论，再讲为什么\n",
    "learner/teaching-notes.md": "# 什么讲法对我有效\n\n（由 lf-teach 和进化模块追加，人写的条目标 [human]）\n",
    "ledger/attempts.jsonl": "",
    "ledger/errors.jsonl": "",
    "holdout/README.md": "# 盲测卷（锁定）\n\n每门课留一套不练的真题放这里，只能通过 `lf holdout` 使用。\n"
                         "出题、讲解、进化模块都不能读写这个目录。\n",
    "sessions/.keep": "",
    ".gitignore": "learner/mastery.json\n.DS_Store\n",
    ".claude/settings.json": json.dumps({"permissions": {"deny": [
        "Read(./holdout/**)", "Edit(./holdout/**)", "Write(./holdout/**)",
        "Bash(cat holdout/*)", "Bash(cat ./holdout/*)"]}}, indent=2) + "\n",
}

PACK_FILES = {
    "pack.yaml": "name: {name}\nmode: exam            # exam：以盲测分为验收；growth：以项目和面试为验收\n"
                 "exam_date: null\ntextbook: null\nscope: null\n",
    "map.yaml": "# 能力地图：章节 → 知识点 → 前置依赖\nchapters: []\n",
    "blueprint.yaml": "# 考点权重（从真题统计；没有真题时按教材估）\nweights: {{}}\ntypes: {{}}\n",
    "sources.md": "# 资料卡\n",
}


def cmd_init_data(a):
    root = Path(a.dir).expanduser().resolve()
    for rel, content in DATA_FILES.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text(content, encoding="utf-8")
    for d in ("packs", "bank"):
        (root / d).mkdir(exist_ok=True)
    installed = [] if a.no_packs else install_packs(root, a.packs.split(",") if a.packs else None)
    register(root)
    emit({"data": str(root), "registered": True, "packs_installed": installed},
         lambda o: print(f"数据仓库就绪：{o['data']}" + (f"；装入学科包 {', '.join(installed)}" if installed else "")))


def install_packs(root: Path, names: list | None = None) -> list:
    """把软件自带的学科包（能力地图、权重、资料卡、SQL 数据集、诊断卷）装进数据仓库。已存在的文件不覆盖。"""
    import shutil
    from importlib import resources
    src = resources.files("learnforge").joinpath("packs")
    done = []
    for pack in sorted(p.name for p in src.iterdir() if p.is_dir()):
        if names and pack not in names:
            continue
        dst = root / "packs" / pack
        for f in src.joinpath(pack).iterdir():
            if f.name == "seed.jsonl":
                target = root / "bank" / f"{pack}.seed.jsonl"
            elif f.is_dir():
                target = dst / f.name
                if not target.exists():
                    shutil.copytree(str(f), str(target))
                continue
            else:
                target = dst / f.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(f.read_bytes())
        done.append(pack)
    return done


def cmd_init(a):
    data = Data()
    d = data.p("packs", a.pack)
    d.mkdir(parents=True, exist_ok=True)
    for rel, content in PACK_FILES.items():
        if not (d / rel).exists():
            (d / rel).write_text(content.format(name=a.name or a.pack), encoding="utf-8")
    emit({"pack": a.pack, "path": str(d)}, lambda o: print(f"学科包骨架：{o['path']}"))


def cmd_pack(a):
    data = Data()
    if a.action == "set":
        val = parse_given(a.value)
        set_yaml_key(data.p("packs", a.pack, "pack.yaml"), a.key, val)
    emit(data.pack(a.pack))


def cmd_map(a):
    data = Data()
    cmap = data.concept_map(a.pack)

    def human(cs):
        ch = None
        for c in cs:
            if c["chapter_name"] != ch:
                ch = c["chapter_name"]
                print(f"\n## {ch}")
            pre = f"  ← {', '.join(c['prereq'])}" if c["prereq"] else ""
            print(f"  {c['id']:<34} {c['name']}  [{c['weight']:.0%}]{pre}")
    emit(cmap, human)


# ---------------------------------------------------------------- 今日建议 / 统计

KIND = {"new": "新学", "review": "复习", "fix": "订正"}


def cmd_today(a):
    data = Data()
    r = model.today(data, a.minutes, a.pack)

    def human(r):
        for p, e in r["exams"].items():
            if e["days_left"] is None:
                print(f"[{p}] 还没设考试日期：lf pack {p} set exam_date 2027-01-10")
            else:
                print(f"[{p}] 距离考试 {e['days_left']} 天（{e['exam_date']}）")
        print(f"\n今天 {r['minutes']} 分钟，建议这样用（约 {r['planned_minutes']} 分钟）：")
        for i, it in enumerate(r["plan"], 1):
            print(f"\n{i}. [{KIND[it['kind']]}] {it['name']}  ({it['concept']}, 约 {it['minutes']} 分钟)")
            for why in it["reasons"]:
                print(f"   · {why}")
            if it["questions"]:
                print(f"   题目：{' '.join(it['questions'])}")
        if r["drills"]:
            print("\n专项练习：")
            for d in r["drills"]:
                print(f"   · {d['suggest']}")
        if r["coverage_gaps"]:
            print("\n覆盖缺口（考前两周）：")
            for g in r["coverage_gaps"]:
                print(f"   · {g['name']}（{model.STATUS_NAMES[g['status']]}，权重 {g['weight']:.0%}）")
    emit(r, human)


def cmd_stats(a):
    data = Data()
    r = model.stats(data, a.pack)

    def human(r):
        for p, s in r.items():
            sc = s["status_count"]
            print(f"=== {p}：{s['concepts']} 个知识点 · " +
                  " ".join(f"{model.STATUS_NAMES[k]} {sc.get(k, 0)}" for k in model.STATUS_NAMES) +
                  f" · 预测分（粗估）{s['predicted_score']}")
            for ch, cs in s["chapters"].items():
                print(f"\n  {ch}")
                for c in cs:
                    if c["status"] == "unseen":
                        print(f"    {'·':<2} {c['name']:<18} 未学")
                        continue
                    errs = " ".join(f"{model.CAUSE_NAMES.get(k, k)}×{n}" for k, n in c["open_errors"].items())
                    print(f"    {'●' if c['status'] == 'solid' else '○':<2} {c['name']:<18} "
                          f"{model.STATUS_NAMES[c['status']]}  对 {c['correct']}/{c['attempts']}  "
                          f"R={c['r_now']:.2f} S={c['stability_days']}d  {errs}")
            if s["error_causes"]:
                print("\n  错因分布：" + "  ".join(f"{model.CAUSE_NAMES.get(k, k)} {n}"
                                               for k, n in sorted(s["error_causes"].items(), key=lambda x: -x[1])))
            print()
    emit(r, human)


# ---------------------------------------------------------------- 题库

def _public(q: dict, with_answer: bool) -> dict:
    hidden = set() if with_answer else {"answer", "explain", "rubric", "verify", "check", "hints"}
    out = {k: v for k, v in q.items() if k not in hidden and not k.startswith("_")}
    if not with_answer and q["type"] == "calc" and isinstance(q.get("answer"), dict):
        out["answer_keys"] = list(q["answer"])
    if not with_answer and q.get("hints"):
        out["hint_levels"] = len(q["hints"])
    return out


def _render_q(q: dict, n: int | None = None, with_answer: bool = False):
    head = f"{n}. " if n else ""
    print(f"{head}[{q['id']} · {q['type']} · {q.get('score', '?')} 分] {q['stem']}")
    for k, v in (q.get("options") or {}).items():
        print(f"   {k}. {v}")
    if q["type"] == "calc" and isinstance(q.get("answer"), dict):
        print(f"   （作答时依次给出：{'、'.join(q['answer'])}）")
    if with_answer:
        print(f"   答案：{json.dumps(q.get('answer'), ensure_ascii=False)}")
        if q.get("explain"):
            print(f"   解析：{q['explain']}")
    print()


def cmd_q(a):
    data = Data()
    if a.action == "add":
        raw = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
        recs = [json.loads(l) for l in raw.splitlines() if l.strip()] if a.jsonl else [json.loads(raw)]
        added = []
        for q in recs:
            q = data.add_question(q)
            v = grading.verify(data, q) if (q.get("verify") or q["type"] == "sql") else {"ok": None}
            added.append({"id": q["id"], "verify": v})
        emit(added)
        return
    bank = data.bank()
    if a.action == "show":
        q = bank.get(a.id) or data.question(a.id)
        emit(_public(q, a.answer), lambda q: _render_q(q, with_answer=a.answer))
        return
    if a.action == "hint":
        q = data.question(a.id)
        hints = q.get("hints") or []
        lvl = max(1, min(a.level, len(hints))) if hints else 0
        emit({"id": a.id, "level": lvl, "of": len(hints), "hint": hints[lvl - 1] if hints else None})
        return
    qs = list(bank.values())
    if a.pack:
        qs = [q for q in qs if data.pack_of(q) == a.pack]
    if a.concept:
        qs = [q for q in qs if any(c.startswith(a.concept) for c in q.get("concept", []))]
    if a.type:
        qs = [q for q in qs if q["type"] == a.type]
    if a.paper:
        qs = [q for q in qs if a.paper in q.get("papers", [])]
    if a.unseen:
        done = {x["q"] for x in data.attempts()}
        qs = [q for q in qs if q["id"] not in done]
    rows = [{"id": q["id"], "type": q["type"], "concept": q.get("concept"), "stem": q["stem"][:60]} for q in qs]
    emit(rows, lambda rs: [print(f"{r['id']:<16} {r['type']:<7} {','.join(r['concept'])}  {r['stem']}") for r in rs])


def cmd_paper(a):
    data = Data()
    qs = [q for q in data.bank().values() if data.pack_of(q) == a.pack and a.name in q.get("papers", [])]
    qs.sort(key=lambda q: q["id"])
    if not qs:
        raise LFError(f"{a.pack} 没有名为 {a.name} 的试卷")
    if JSON:
        emit([_public(q, a.answers) for q in qs])
        return
    total = sum(q.get("score", 0) for q in qs)
    print(f"# {data.pack(a.pack).get('name', a.pack)} · {a.name}（共 {len(qs)} 题，{total} 分）\n")
    for i, q in enumerate(qs, 1):
        _render_q(q, i, a.answers)


# ---------------------------------------------------------------- 判分与记录

def cmd_grade(a):
    data = Data()
    q = data.question(a.id)
    emit(grading.grade(data, q, parse_given(a.given)))


def cmd_record(a):
    data = Data()
    q = data.question(a.id)
    given = parse_given(a.given) if a.given is not None else None
    if a.score is not None:
        res = {"auto": False, "correct": a.score >= 0.999 and not a.wrong, "score": a.score, "feedback": ""}
    elif a.correct or a.wrong:
        res = {"auto": False, "correct": a.correct, "score": 1.0 if a.correct else 0.0, "feedback": ""}
    else:
        if given is None:
            raise LFError("需要 --given 作答内容，或者用 --correct/--wrong/--score 直接给判定")
        res = grading.grade(data, q, given)
        if not res["auto"]:
            raise LFError("这道题不能自动判分：请按 rubric 判断后加 --score 0~1 记录")
    if a.cause and a.cause not in model.CAUSES:
        raise LFError(f"错因只能用固定词表：{', '.join(model.CAUSES)}")
    rec = {"t": stamp(), "q": q["id"], "mode": a.mode, "correct": bool(res["correct"]),
           "score": res["score"], "given": given, "hints_used": a.hints, "seconds": a.seconds,
           "confidence": a.confidence}
    append_jsonl(data.attempts_path, rec)
    out = {"recorded": rec, "grade": res}
    open_err = data.open_errors()
    if not res["correct"]:
        if a.cause:
            err = {"t": rec["t"], "q": q["id"], "concept": q["concept"], "cause": a.cause,
                   "detail": a.detail or "", "event": "open"}
            append_jsonl(data.errors_path, err)
            out["error"] = err
        else:
            out["warning"] = f"答错了但没标错因：lf err add {q['id']} --cause <{'|'.join(model.CAUSES)}> --detail ..."
        out["explain"] = q.get("explain")
        out["answer"] = q.get("answer")
    elif q["id"] in open_err:
        append_jsonl(data.errors_path, {"t": rec["t"], "q": q["id"], "event": "fix"})
        out["fixed"] = True

    def human(o):
        g = o["grade"]
        mark = "✓ 正确" if o["recorded"]["correct"] else f"✗ 错误（得分 {g['score']}）"
        print(f"{q['id']}：{mark}  {g.get('feedback', '')}")
        if o.get("fixed"):
            print("  这道错题已订正。")
        if o.get("error"):
            print(f"  已记错因：{model.CAUSE_NAMES[o['error']['cause']]}  {o['error']['detail']}")
        if o.get("warning"):
            print(f"  {o['warning']}")
    emit(out, human)


def cmd_err(a):
    data = Data()
    if a.action == "add":
        q = data.question(a.id)
        if a.cause not in model.CAUSES:
            raise LFError(f"错因只能用固定词表：{', '.join(model.CAUSES)}")
        e = {"t": stamp(), "q": q["id"], "concept": q["concept"], "cause": a.cause,
             "detail": a.detail or "", "event": "open"}
        append_jsonl(data.errors_path, e)
        emit(e)
    elif a.action == "fix":
        append_jsonl(data.errors_path, {"t": stamp(), "q": a.id, "event": "fix"})
        emit({"fixed": a.id})
    else:
        emit(list(data.open_errors().values()),
             lambda es: [print(f"{e['q']:<16} {model.CAUSE_NAMES.get(e['cause'], e['cause']):<10} {e['detail']}")
                         for e in es] or print("没有未订正的错题"))


def cmd_verify(a):
    data = Data()
    bank = data.bank()
    ids = a.ids or [i for i, q in bank.items() if q.get("verify") or q["type"] == "sql"]
    res = []
    for i in ids:
        r = grading.verify(data, bank[i] if i in bank else data.question(i))
        res.append({"id": i, **r})
    bad = [r for r in res if r["ok"] is False]

    def human(rs):
        for r in rs:
            print(f"{'✓' if r['ok'] else '✗' if r['ok'] is False else '-'} {r['id']:<16} {r['reason']}")
        print(f"\n{len(rs)} 题，未通过 {len(bad)} 题")
    emit(res, human)
    if bad:
        sys.exit(1)


def cmd_calc(a):
    if a.list or not a.name:
        emit(verifiers.describe(), lambda ds: [print(f"{d['name']:<26} {d['doc']}\n{'':<26} {d['signature']}")
                                               for d in ds])
        return
    args = parse_given(a.args) if a.args else {}
    res = verifiers.get(a.name)(**args)

    def human(r):
        trace = r.get("trace")
        for k, v in r.items():
            if k != "trace":
                print(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        if isinstance(trace, list) and trace and isinstance(trace[0], dict):
            keys = list(trace[0])
            print("\n" + " | ".join(keys))
            for row in trace:
                print(" | ".join(json.dumps(row.get(k), ensure_ascii=False) for k in keys))
    emit(res, human)


def cmd_sql(a):
    data = Data()
    d = data.p("packs", a.pack, "datasets")
    ds = d / f"{a.dataset}.sql"
    res = verifiers.get("db.run_sql")(a.query, str(ds))
    emit(res, lambda r: print(r.get("error") or "\n".join(" | ".join(map(str, row)) for row in r["rows"])))


def cmd_book(a):
    data = Data()
    if a.action == "add":
        emit(book.add(data, a.pack, a.arg, a.name, a.offset))
    elif a.action == "find":
        emit(book.find(data, a.pack, a.arg, a.k),
             lambda hs: [print(f"[{h['book']} p.{h['page']}] {h['snippet']}\n") for h in hs])
    else:
        emit(book.toc(data, a.pack),
             lambda es: [print(f"{'  ' * e['level']}{e['title']}  p.{e.get('page')}") for e in es])


def cmd_holdout(a):
    data = Data()
    hd = data.root / "holdout"
    files = sorted(hd.glob(f"{a.pack}*.jsonl"))
    if a.action == "add":
        src = Path(a.file)
        dst = hd / f"{a.pack}-{src.stem}.jsonl"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        emit({"locked": str(dst), "questions": len(read_jsonl(dst, allow_holdout=True))})
        return
    qs = [q for f in files for q in read_jsonl(f, allow_holdout=True)]
    if a.action == "count":
        emit({"pack": a.pack, "questions": len(qs), "score": sum(q.get("score", 0) for q in qs)})
        return
    # run：交互式盲测，只在终端里由你本人作答
    print(f"盲测：{len(qs)} 题。只显示题目，作答后不显示答案；主观题记为待人工评分。\n")
    total = got = 0
    run = stamp()
    for i, q in enumerate(qs, 1):
        _render_q({k: v for k, v in q.items() if k not in ("answer", "explain")}, i)
        ans = input("你的答案> ")
        total += q.get("score", 0)
        if q["type"] in grading.OBJECTIVE:
            r = grading.grade(data, q, parse_given(ans))
            got += (r["score"] or 0) * q.get("score", 0)
            status = r["score"]
        else:
            status = "pending"
        append_jsonl(data.root / "ledger" / "holdout.jsonl",
                     {"run": run, "t": stamp(), "q": q["id"], "given": ans, "score": status})
    print(f"\n客观题得分 {got:.1f}/{total}（主观题待评）。结果在 ledger/holdout.jsonl")


def cmd_mcp(a):
    from . import mcp_server
    mcp_server.main()


def cmd_serve(a):
    from . import web
    web.serve(a.port, a.open)


def cmd_where(a):
    data = Data()
    emit({"data": str(data.root), "packs": data.packs()}, lambda o: print(o["data"]))


def cmd_note(a):
    data = Data()
    f = data.p("sessions", f"{stamp()[:10]}.md")
    f.parent.mkdir(exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {stamp()[11:]}\n{a.text}\n")
    emit({"saved": str(f)})


# ---------------------------------------------------------------- 入口

def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lf", description="LearnForge 学习引擎")
    ap.add_argument("--json", action="store_true", help="输出 JSON（放在命令任意位置都行）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-data", help="新建并登记数据仓库（默认装入自带的 os、db 学科包和诊断卷）")
    s.add_argument("dir")
    s.add_argument("--packs", help="只装这些学科包，逗号分隔，例如 os,db")
    s.add_argument("--no-packs", action="store_true", help="只建空仓库")
    s.set_defaults(fn=cmd_init_data)

    s = sub.add_parser("init", help="新建学科包骨架")
    s.add_argument("pack")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("pack", help="查看或修改学科包设置")
    s.add_argument("pack")
    s.add_argument("action", nargs="?", default="show", choices=["show", "set"])
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("map", help="查看能力地图")
    s.add_argument("pack")
    s.set_defaults(fn=cmd_map)

    s = sub.add_parser("today", help="现在最值得复习什么（不推送，只在你打开时给）")
    s.add_argument("--minutes", type=int)
    s.add_argument("--pack")
    s.set_defaults(fn=cmd_today)

    s = sub.add_parser("stats", help="掌握度、错因分布、预测分")
    s.add_argument("--pack")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("q", help="题库：list / show / hint / add")
    s.add_argument("action", choices=["list", "show", "hint", "add"])
    s.add_argument("id", nargs="?")
    s.add_argument("--answer", action="store_true", help="show 时显示答案和解析")
    s.add_argument("--level", type=int, default=1, help="hint 的级别 1~3")
    s.add_argument("--pack")
    s.add_argument("--concept")
    s.add_argument("--type")
    s.add_argument("--paper")
    s.add_argument("--unseen", action="store_true")
    s.add_argument("--file", help="add：从文件读题（默认读 stdin）")
    s.add_argument("--jsonl", action="store_true", help="add：每行一道题")
    s.set_defaults(fn=cmd_q)

    s = sub.add_parser("paper", help="打印一套试卷")
    s.add_argument("pack")
    s.add_argument("--name", default="diag")
    s.add_argument("--answers", action="store_true")
    s.set_defaults(fn=cmd_paper)

    s = sub.add_parser("grade", help="只判分，不记录")
    s.add_argument("id")
    s.add_argument("given")
    s.set_defaults(fn=cmd_grade)

    s = sub.add_parser("record", help="判分并记一次作答（答错可同时记错因）")
    s.add_argument("id")
    s.add_argument("--given")
    s.add_argument("--correct", action="store_true")
    s.add_argument("--wrong", action="store_true")
    s.add_argument("--score", type=float)
    s.add_argument("--hints", type=int, default=0)
    s.add_argument("--seconds", type=int)
    s.add_argument("--confidence", type=float)
    s.add_argument("--cause", help="|".join(model.CAUSES))
    s.add_argument("--detail")
    s.add_argument("--mode", default="quiz")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("err", help="错因账本：list / add / fix")
    s.add_argument("action", choices=["list", "add", "fix"])
    s.add_argument("id", nargs="?")
    s.add_argument("--cause")
    s.add_argument("--detail")
    s.set_defaults(fn=cmd_err)

    s = sub.add_parser("verify", help="用验算脚本核对题目答案")
    s.add_argument("ids", nargs="*")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("calc", help="直接调用验算器：lf calc os.page_replace '{\"frames\":3,...}'")
    s.add_argument("name", nargs="?")
    s.add_argument("args", nargs="?")
    s.add_argument("--list", action="store_true")
    s.set_defaults(fn=cmd_calc)

    s = sub.add_parser("sql", help="在学科包的数据集上跑一条 SQL")
    s.add_argument("pack")
    s.add_argument("query")
    s.add_argument("--dataset", default="school_textbook")
    s.set_defaults(fn=cmd_sql)

    s = sub.add_parser("book", help="教材：add <文件> / find <关键词> / toc")
    s.add_argument("action", choices=["add", "find", "toc"])
    s.add_argument("pack")
    s.add_argument("arg", nargs="?")
    s.add_argument("--name")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(fn=cmd_book)

    s = sub.add_parser("holdout", help="盲测卷：add / count / run（锁定，只有这里能碰）")
    s.add_argument("action", choices=["add", "count", "run"])
    s.add_argument("pack")
    s.add_argument("file", nargs="?")
    s.set_defaults(fn=cmd_holdout)

    s = sub.add_parser("mcp", help="以 MCP 服务（stdio）运行，给 Claude 桌面版、Claude Code、Codex 等宿主加载")
    s.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("serve", help="启动本地网页版")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="启动后打开浏览器")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("where", help="显示数据仓库位置")
    s.set_defaults(fn=cmd_where)

    s = sub.add_parser("note", help="记一条学习摘要到 sessions/")
    s.add_argument("text")
    s.set_defaults(fn=cmd_note)
    return ap


def main(argv=None):
    global JSON
    argv = list(sys.argv[1:] if argv is None else argv)
    JSON = "--json" in argv
    a = build().parse_args([x for x in argv if x != "--json"])
    try:
        a.fn(a)
    except LFError as e:
        if JSON:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"lf: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
