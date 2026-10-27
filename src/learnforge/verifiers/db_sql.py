"""SQL 题判分：参考答案与作答在同一组数据集上实际执行，比对结果。

用 SQLite 内存库，每个数据集每次都从建表脚本重建，所以作答里写 DELETE/DROP 也不会弄脏数据。
一个数据集可能让错误写法碰巧通过，所以每道题至少配两个数据集：教材样例 + 专门构造的边界数据。
方言：考试和实验用 MySQL，这里用 SQLite 执行。标准 SQL（SELECT/JOIN/子查询/GROUP BY/EXISTS）
两边一致；MySQL 专有函数（YEAR()、IFNULL 以外的函数等）可能需要改写。
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path


def _norm(row):
    return tuple(round(v, 6) if isinstance(v, float) else v for v in row)


def _has_top_order_by(sql: str) -> bool:
    depth = 0
    for m in re.finditer(r"\(|\)|\border\s+by\b", sql, re.I):
        tok = m.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif depth == 0:
            return True
    return False


def _run(setup: str, sql: str, check_tables: list | None):
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(setup)
        cur = con.cursor()
        stmts = [s for s in sql.strip().rstrip(";").split(";") if s.strip()]
        rows = None
        for st in stmts:
            cur.execute(st)
            if cur.description:
                rows = [_norm(r) for r in cur.fetchall()]
                cols = len(cur.description)
        if check_tables:
            state = {}
            for t in check_tables:
                cur.execute(f"SELECT * FROM {t}")
                state[t] = Counter(_norm(r) for r in cur.fetchall())
            return {"state": state}
        if rows is None:
            return {"error": "语句没有返回结果集"}
        return {"rows": rows, "cols": cols}
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        con.close()


def run_sql(sql: str, dataset: str, limit: int = 30) -> dict:
    """在某个数据集上执行一条查询，返回结果（用于讲解时“跑给你看”）。"""
    res = _run(Path(dataset).read_text(encoding="utf-8"), sql, None)
    if "rows" in res:
        res["rows"] = res["rows"][:limit]
    return res


def grade_sql(given: str, reference: str, datasets: list, check_tables: list | None = None) -> dict:
    """在每个数据集上比对作答与参考答案。参考答案有外层 ORDER BY 时比较顺序，否则按多重集合比较。"""
    ordered = _has_top_order_by(reference)
    details = []
    for ds in datasets:
        setup = Path(ds).read_text(encoding="utf-8")
        ref = _run(setup, reference, check_tables)
        got = _run(setup, given, check_tables)
        name = Path(ds).stem
        if "error" in ref:
            raise ValueError(f"参考答案在 {name} 上执行失败：{ref['error']}")
        if "error" in got:
            details.append({"dataset": name, "ok": False, "reason": f"执行出错：{got['error']}"})
            continue
        if check_tables:
            ok = got["state"] == ref["state"]
            details.append({"dataset": name, "ok": ok, "reason": "" if ok else "执行后表中数据与参考答案不同"})
            continue
        if got["cols"] != ref["cols"]:
            details.append({"dataset": name, "ok": False,
                            "reason": f"列数不同：应为 {ref['cols']} 列，实际 {got['cols']} 列"})
            continue
        ok = got["rows"] == ref["rows"] if ordered else Counter(got["rows"]) == Counter(ref["rows"])
        reason = ""
        if not ok:
            missing = list((Counter(ref["rows"]) - Counter(got["rows"])).elements())[:5]
            extra = list((Counter(got["rows"]) - Counter(ref["rows"])).elements())[:5]
            if not missing and not extra:
                reason = "行相同但顺序不对"
            else:
                reason = f"少了 {missing}；多了 {extra}"
        details.append({"dataset": name, "ok": ok, "reason": reason})
    return {"correct": all(d["ok"] for d in details), "details": details}


REGISTRY = {"db.run_sql": run_sql, "db.grade_sql": grade_sql}
