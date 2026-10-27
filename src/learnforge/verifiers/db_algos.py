"""数据库计算题的确定性求解器：函数依赖、范式、分解、可串行化、日志恢复。

属性写法：全是大写单字母时可以连写（"ABC"、"A->BC"）；多字母属性用逗号分隔（"Sno,Cno->Grade"），
单个多字母属性直接写（"Sno->Sname"）。
最小依赖集、分解、安全序列这类“答案不唯一”的题，判分用 check_* 函数验性质，不比字面。
"""
from __future__ import annotations

import re
from itertools import combinations


# ---------------------------------------------------------------- 解析

def _attrs(s) -> frozenset:
    if isinstance(s, (set, frozenset, list, tuple)):
        return frozenset(s)
    s = s.strip()
    if any(ch in s for ch in ", ，、"):
        return frozenset(a.strip() for a in re.split(r"[,\s，、]+", s) if a.strip())
    if re.fullmatch(r"[A-Z]*", s):
        return frozenset(s)
    return frozenset({s})


def _fds(fds) -> list:
    """接受 "A->BC; CD->E"、["A->BC", ...]、[["A","BC"], ...]，返回 [(X, Y)]。"""
    if isinstance(fds, str):
        fds = [f for f in re.split(r"[;；\n]+", fds) if f.strip()]
    out = []
    for f in fds:
        if isinstance(f, str):
            lhs, rhs = re.split(r"\s*(?:->|→|=>)\s*", f.strip())
            out.append((_attrs(lhs), _attrs(rhs)))
        else:
            out.append((_attrs(f[0]), _attrs(f[1])))
    return out


def _fmt(a) -> str:
    items = sorted(a)
    return ("" if all(len(x) == 1 for x in items) else ",").join(items)


def _fmt_fd(fd) -> str:
    return f"{_fmt(fd[0])}->{_fmt(fd[1])}"


# ---------------------------------------------------------------- 闭包与码

def _closure(x, fds) -> frozenset:
    res = set(x)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in fds:
            if lhs <= res and not rhs <= res:
                res |= rhs
                changed = True
    return frozenset(res)


def closure(attrs, fds) -> dict:
    """属性集闭包 X+，trace 记录每一步用了哪条依赖。"""
    F = _fds(fds)
    res = set(_attrs(attrs))
    trace = [{"step": 0, "closure": _fmt(res)}]
    changed = True
    while changed:
        changed = False
        for fd in F:
            if fd[0] <= res and not fd[1] <= res:
                res |= fd[1]
                trace.append({"step": len(trace), "use": _fmt_fd(fd), "closure": _fmt(res)})
                changed = True
    return {"closure": _fmt(res), "trace": trace}


def _keys(R, F) -> list:
    R = frozenset(R)
    only_left = {a for a in R if any(a in l for l, _ in F) and not any(a in r for _, r in F)}
    neither = {a for a in R if not any(a in l or a in r for l, r in F)}
    must = frozenset(only_left | neither)
    optional = sorted(R - must)
    keys: list = []
    for k in range(len(optional) + 1):
        for extra in combinations(optional, k):
            cand = must | frozenset(extra)
            if any(key <= cand for key in keys):
                continue
            if _closure(cand, F) >= R:
                keys.append(cand)
    return keys


def keys(R, fds) -> dict:
    """候选码与主属性。先找只在左边出现或两边都不出现的属性（必在每个码里），再逐层扩展。"""
    R, F = _attrs(R), _fds(fds)
    ks = _keys(R, F)
    prime = frozenset().union(*ks) if ks else frozenset()
    return {"keys": sorted(_fmt(k) for k in ks), "prime": _fmt(prime), "nonprime": _fmt(R - prime)}


# ---------------------------------------------------------------- 最小依赖集

def _split(F):
    return [(l, frozenset({a})) for l, r in F for a in sorted(r)]


def _min_cover(F) -> list:
    G = []
    for fd in _split(F):
        if fd not in G and not fd[1] <= fd[0]:
            G.append(fd)
    # 去掉左部多余属性
    for i, (l, r) in enumerate(G):
        lhs = set(l)
        for a in sorted(l):
            if len(lhs) > 1 and r <= _closure(frozenset(lhs - {a}), G):
                lhs.discard(a)
        G[i] = (frozenset(lhs), r)
    dedup = []
    for fd in G:
        if fd not in dedup:
            dedup.append(fd)
    G = dedup
    # 去掉冗余依赖
    i = 0
    while i < len(G):
        rest = G[:i] + G[i + 1:]
        if G[i][1] <= _closure(G[i][0], rest):
            G = rest
        else:
            i += 1
    return G


def min_cover(fds) -> dict:
    G = _min_cover(_fds(fds))
    return {"cover": [_fmt_fd(f) for f in G]}


def _equiv(F, G) -> bool:
    return all(r <= _closure(l, G) for l, r in F) and all(r <= _closure(l, F) for l, r in G)


def equiv(F, G) -> dict:
    return {"equivalent": _equiv(_fds(F), _fds(G))}


def check_min_cover(given, fds) -> dict:
    """判分：given 是否为 F 的一个最小依赖集（等价 + 右部单属性 + 左部无多余 + 无冗余依赖）。"""
    F, G = _fds(fds), _fds(given)
    if not _equiv(F, G):
        return {"correct": False, "reason": "与原依赖集不等价"}
    for l, r in G:
        if len(r) != 1:
            return {"correct": False, "reason": f"{_fmt_fd((l, r))} 的右部不是单属性"}
    for i, (l, r) in enumerate(G):
        rest = G[:i] + G[i + 1:]
        if r <= _closure(l, rest):
            return {"correct": False, "reason": f"{_fmt_fd((l, r))} 是冗余依赖"}
        for a in l:
            if len(l) > 1 and r <= _closure(l - {a}, G):
                return {"correct": False, "reason": f"{_fmt_fd((l, r))} 左部的 {a} 是多余属性"}
    return {"correct": True, "reason": "等价且满足最小依赖集的三个条件"}


# ---------------------------------------------------------------- 范式

def _project(F, S) -> list:
    """F 在属性子集 S 上的投影（穷举子集求闭包，适合教学规模）。"""
    S = frozenset(S)
    out = []
    items = sorted(S)
    for k in range(1, len(items) + 1):
        for X in combinations(items, k):
            X = frozenset(X)
            rhs = (_closure(X, F) & S) - X
            if rhs:
                out.append((X, rhs))
    return _min_cover(out) if out else []


def _nf(R, F) -> tuple:
    ks = _keys(R, F)
    prime = frozenset().union(*ks) if ks else frozenset()
    nonprime = R - prime
    # 2NF：非主属性不部分依赖于码
    for k in ks:
        for n in range(1, len(k)):
            for sub in combinations(sorted(k), n):
                part = (_closure(frozenset(sub), F) & nonprime) - frozenset(sub)
                if part:
                    return "1NF", f"非主属性 {_fmt(part)} 部分依赖于码 {_fmt(k)}（{_fmt(sub)}->{_fmt(part)}）"
    viol3 = None
    viol_bc = None
    for l, r in _split(F):
        if r <= l:
            continue
        superkey = _closure(l, F) >= R
        if not superkey:
            viol_bc = viol_bc or f"{_fmt_fd((l, r))} 的决定因素不含码"
            if not r <= prime:
                viol3 = viol3 or f"非主属性 {_fmt(r)} 传递依赖于码（{_fmt_fd((l, r))}，{_fmt(l)} 不是超码）"
    if viol3:
        return "2NF", viol3
    if viol_bc:
        return "3NF", viol_bc
    return "BCNF", "每个非平凡依赖的决定因素都含码"


def normal_form(R, fds) -> dict:
    """最高范式（假定已满足 1NF），并给出不满足下一级的那条依赖。"""
    R, F = _attrs(R), _fds(fds)
    nf, why = _nf(R, F)
    return {"nf": nf, "reason": why, "keys": sorted(_fmt(k) for k in _keys(R, F))}


# ---------------------------------------------------------------- 分解

def _lossless(R, F, schemas) -> bool:
    """Chase 表法判无损连接。"""
    R = sorted(R)
    rows = [{a: ("a", a) if a in s else ("b", i, a) for a in R} for i, s in enumerate(schemas)]
    changed = True
    while changed:
        changed = False
        for l, r in F:
            groups: dict = {}
            for row in rows:
                groups.setdefault(tuple(row[a] for a in sorted(l)), []).append(row)
            for grp in groups.values():
                if len(grp) < 2:
                    continue
                for a in r:
                    vals = {row[a] for row in grp}
                    if len(vals) > 1:
                        target = ("a", a) if ("a", a) in vals else min(vals)
                        for row in grp:
                            if row[a] != target:
                                row[a] = target
                                changed = True
    return any(all(row[a] == ("a", a) for a in R) for row in rows)


def _preserves(F, schemas) -> list:
    """返回没有被保持的依赖（空列表表示保持函数依赖）。"""
    lost = []
    for l, r in _split(F):
        z = set(l)
        changed = True
        while changed:
            changed = False
            for s in schemas:
                t = _closure(frozenset(z) & s, F) & s
                if not t <= z:
                    z |= t
                    changed = True
        if not r <= z:
            lost.append(_fmt_fd((l, r)))
    return lost


def decompose_3nf(R, fds) -> dict:
    """3NF 合成算法：最小依赖集 → 按左部分组 → 补一个码 → 去掉被包含的模式。保持依赖且无损。"""
    R, F = _attrs(R), _fds(fds)
    G = _min_cover(F)
    groups: dict = {}
    for l, r in G:
        groups.setdefault(l, set(l)).update(r)
    schemas = [frozenset(s) for s in groups.values()]
    used = frozenset().union(*schemas) if schemas else frozenset()
    if R - used:
        schemas.append(frozenset(R - used))
    ks = _keys(R, F)
    if not any(any(k <= s for k in ks) for s in schemas):
        schemas.append(ks[0])
    schemas = [s for s in schemas if not any(s < t for t in schemas)]
    uniq = []
    for s in schemas:
        if s not in uniq:
            uniq.append(s)
    return {"schemas": [_fmt(s) for s in uniq], "lossless": _lossless(R, F, uniq),
            "lost_fds": _preserves(F, uniq)}


def decompose_bcnf(R, fds) -> dict:
    """BCNF 分解：反复找违反 BCNF 的 X->Y，拆成 XY 和 R-Y。无损，但不一定保持依赖。"""
    R, F = _attrs(R), _fds(fds)
    todo, result, steps = [R], [], []
    while todo:
        S = todo.pop(0)
        FS = _project(F, S)
        bad = next(((l, r) for l, r in _split(FS) if not r <= l and not _closure(l, FS) >= S), None)
        if not bad:
            result.append(S)
            continue
        l = bad[0]
        xp = _closure(l, FS) & S
        s1, s2 = frozenset(xp), frozenset(S - (xp - l))
        steps.append({"split": _fmt(S), "by": _fmt_fd(bad), "into": [_fmt(s1), _fmt(s2)]})
        todo += [s1, s2]
    return {"schemas": [_fmt(s) for s in result], "steps": steps,
            "lossless": _lossless(R, F, result), "lost_fds": _preserves(F, result)}


def lossless(R, fds, schemas) -> dict:
    R, F = _attrs(R), _fds(fds)
    S = [_attrs(s) for s in schemas]
    return {"lossless": _lossless(R, F, S), "lost_fds": _preserves(F, S)}


def check_decomposition(given, R, fds, target: str = "3NF", need_preserve: bool | None = None) -> dict:
    """判分：给出的分解是否覆盖 R、无损、（3NF 时）保持依赖，且每个模式都达到 target。"""
    R, F = _attrs(R), _fds(fds)
    S = [_attrs(s) for s in (given if isinstance(given, list) else re.split(r"[;；]", given))]
    if frozenset().union(*S) != R:
        return {"correct": False, "reason": "各子模式的属性并起来不等于 R"}
    if not _lossless(R, F, S):
        return {"correct": False, "reason": "不是无损连接分解"}
    need_preserve = (target == "3NF") if need_preserve is None else need_preserve
    lost = _preserves(F, S)
    if need_preserve and lost:
        return {"correct": False, "reason": f"没有保持函数依赖：{', '.join(lost)}"}
    rank = ["1NF", "2NF", "3NF", "BCNF"]
    for s in S:
        nf, why = _nf(s, _project(F, s))
        if rank.index(nf) < rank.index(target):
            return {"correct": False, "reason": f"子模式 {_fmt(s)} 只达到 {nf}：{why}"}
    return {"correct": True, "reason": f"无损{'、保持依赖' if not lost else ''}，且每个子模式都达到 {target}"}


# ---------------------------------------------------------------- 事务：可串行化

_OP = re.compile(r"([rwRW])\s*_?\s*(\d+)\s*\(\s*(\w+)\s*\)")


def serializable(schedule) -> dict:
    """冲突可串行化判定。schedule: "r1(A) w2(A) r1(B) w1(B)" 或 R1(A)、w_1(A) 等写法。

    两个操作冲突 = 不同事务、同一数据、至少一个是写。按冲突先后画前驱图，无环即冲突可串行化。
    """
    ops = [(m.group(1).lower(), int(m.group(2)), m.group(3)) for m in _OP.finditer(schedule)]
    txns = sorted({t for _, t, _ in ops})
    edges = set()
    reasons = []
    for i, (a1, t1, x1) in enumerate(ops):
        for a2, t2, x2 in ops[i + 1:]:
            if t1 != t2 and x1 == x2 and "w" in (a1, a2) and (t1, t2) not in edges:
                edges.add((t1, t2))
                reasons.append(f"T{t1}->T{t2}：{a1}{t1}({x1}) 在 {a2}{t2}({x2}) 之前")
    indeg = {t: 0 for t in txns}
    for _, b in edges:
        indeg[b] += 1
    order, ready = [], sorted(t for t in txns if indeg[t] == 0)
    while ready:
        t = ready.pop(0)
        order.append(t)
        for a, b in sorted(edges):
            if a == t:
                indeg[b] -= 1
                if indeg[b] == 0:
                    ready.append(b)
                    ready.sort()
    ok = len(order) == len(txns)
    return {"serializable": ok, "edges": [f"T{a}->T{b}" for a, b in sorted(edges)], "reasons": reasons,
            "serial_order": [f"T{t}" for t in order] if ok else None}


# ---------------------------------------------------------------- 事务：日志恢复

def recovery(log: list) -> dict:
    """根据日志判断故障恢复时哪些事务 REDO、哪些 UNDO（王珊《数据库系统概论》的检查点口径）。

    log 每行一条：<T1 start>、<T1,A,10,20>（旧值,新值）、<T1 commit>、<T1 abort>、<checkpoint>
    或 <checkpoint T1,T2>（记录检查点时活跃的事务）。最后一条之后发生故障。
    检查点之前已提交的事务：不用处理；检查点之后提交的：REDO；故障时未提交的：UNDO。
    """
    if isinstance(log, str):
        log = [l for l in log.splitlines() if l.strip()]
    committed_at: dict = {}
    seen: list = []
    last_cp = -1
    for i, raw in enumerate(log):
        s = raw.strip().strip("<>").strip()
        low = s.lower()
        if low.startswith("checkpoint"):
            last_cp = i
            continue
        m = re.match(r"(T\d+)", s, re.I)
        if not m:
            continue
        t = m.group(1).upper()
        if t not in seen:
            seen.append(t)
        if re.search(r"\bcommit\b", low):
            committed_at[t] = i
    redo = [t for t in seen if t in committed_at and committed_at[t] > last_cp]
    done = [t for t in seen if t in committed_at and committed_at[t] <= last_cp]
    undo = [t for t in seen if t not in committed_at]
    return {"redo": redo, "undo": undo, "ignore": done,
            "note": "先反向扫描执行 UNDO，再正向扫描执行 REDO"}


# ---------------------------------------------------------------- 判分：写法无关的比较

_NF_ALIAS = {"第一范式": "1NF", "第二范式": "2NF", "第三范式": "3NF", "bc范式": "BCNF", "bcnf": "BCNF",
             "1nf": "1NF", "2nf": "2NF", "3nf": "3NF"}


def _key_list(given, single: bool) -> set:
    """single：R 的属性全是单字母，此时 "A, BC, CD" 里每个逗号都分隔码；否则只有 ; 或 ")(" 分隔码。"""
    if isinstance(given, str):
        sep = r"[;；,，、\s]+" if single else r"[;；]|\)\s*[,，、]?\s*\(|（|）"
        given = [g for g in re.split(sep, given) if g.strip(" ()（）{}")]
    return {_attrs(g.strip(" ()（）{}")) if isinstance(g, str) else _attrs(g) for g in given}


def check_keys(given, R, fds) -> dict:
    """判分：候选码集合是否正确（与顺序、写法无关）。given：["A","BC"]、"A, BC" 或 "(Sno,Cno); (X)"。"""
    R = _attrs(R)
    want = set(_keys(R, _fds(fds)))
    got = _key_list(given, all(len(x) == 1 for x in R))
    if got == want:
        return {"correct": True, "reason": "候选码正确"}
    return {"correct": False, "reason": f"应为 {sorted(_fmt(k) for k in want)}"}


def check_closure(given, attrs, fds) -> dict:
    want = _closure(_attrs(attrs), _fds(fds))
    got = _attrs(str(given).strip(" (){}（）"))
    return {"correct": got == want, "reason": "" if got == want else f"应为 {_fmt(want)}"}


def check_nf(given, R, fds) -> dict:
    want = _nf(_attrs(R), _fds(fds))[0]
    g = re.sub(r"\s", "", str(given)).lower()
    got = _NF_ALIAS.get(g, g.upper())
    return {"correct": got == want, "reason": "" if got == want else f"应为 {want}"}


def check_set(given, expected) -> dict:
    """判分：集合相等（事务列表、进程列表等）。"""
    if isinstance(given, str):
        given = [g for g in re.split(r"[,，、;\s]+", given) if g]
    norm = lambda xs: {str(x).strip().upper() for x in xs}
    ok = norm(given) == norm(expected)
    return {"correct": ok, "reason": "" if ok else f"应为 {sorted(expected)}"}


REGISTRY = {
    "db.check_keys": check_keys,
    "db.check_closure": check_closure,
    "db.check_nf": check_nf,
    "db.check_set": check_set,
    "db.closure": closure,
    "db.keys": keys,
    "db.min_cover": min_cover,
    "db.check_min_cover": check_min_cover,
    "db.equiv": equiv,
    "db.normal_form": normal_form,
    "db.decompose_3nf": decompose_3nf,
    "db.decompose_bcnf": decompose_bcnf,
    "db.lossless": lossless,
    "db.check_decomposition": check_decomposition,
    "db.serializable": serializable,
    "db.recovery": recovery,
}
