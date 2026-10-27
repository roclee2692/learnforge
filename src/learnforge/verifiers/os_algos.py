"""操作系统计算题的确定性求解器。

每个函数返回 dict：关键答案字段 + trace（逐步过程，用于讲解）。
约定写在参数里，不藏在实现里：教材之间口径不同的地方（RR 新到进程排队顺序、
SCAN 是否走到磁道尽头、C-SCAN 回程是否计入寻道距离……）都可以显式指定。
"""
from __future__ import annotations

from fractions import Fraction


def _num(x):
    """把 Fraction 化成便于阅读的数：整数保持整数，否则保留两位小数。"""
    if isinstance(x, Fraction):
        return int(x) if x.denominator == 1 else round(float(x), 2)
    return x


# ---------------------------------------------------------------- 页面置换

def page_replace(frames: int, refs: list, algo: str = "FIFO") -> dict:
    """页面置换：FIFO / LRU / OPT / CLOCK。

    缺页次数包含物理块从空到满的那几次装入；置换次数 = 缺页次数 - 初始装入次数。
    """
    algo = algo.upper()
    if algo not in {"FIFO", "LRU", "OPT", "CLOCK"}:
        raise ValueError(f"未知算法 {algo}")
    mem: list = []            # 物理块里的页，按块号排列
    order: list = []          # FIFO：装入顺序；LRU：最近使用顺序（末尾最新）
    use: list = []            # CLOCK 的访问位
    ptr = 0
    faults = loads = 0
    trace = []
    for i, r in enumerate(refs):
        evicted = None
        hit = r in mem
        if hit:
            if algo == "LRU":
                order.remove(r)
                order.append(r)
            if algo == "CLOCK":
                use[mem.index(r)] = 1
        else:
            faults += 1
            if len(mem) < frames:
                loads += 1
                mem.append(r)
                order.append(r)
                use.append(1)
                if algo == "CLOCK":
                    ptr = len(mem) % frames
            else:
                if algo in ("FIFO", "LRU"):
                    victim = order.pop(0)
                    slot = mem.index(victim)
                    order.append(r)
                elif algo == "OPT":
                    future = refs[i + 1:]

                    def next_use(p):
                        return future.index(p) if p in future else float("inf")
                    # 都不再使用时，取最早装入的那个（不影响缺页次数）
                    slot = max(range(frames), key=lambda k: (next_use(mem[k]), -order.index(mem[k])))
                    victim = mem[slot]
                    order.remove(victim)
                    order.append(r)
                else:  # CLOCK
                    while use[ptr] == 1:
                        use[ptr] = 0
                        ptr = (ptr + 1) % frames
                    slot = ptr
                    victim = mem[slot]
                    use[slot] = 1
                    ptr = (ptr + 1) % frames
                mem[slot] = r
                evicted = victim
        trace.append({"step": i + 1, "ref": r, "frames": list(mem), "fault": not hit, "evicted": evicted})
    return {
        "algo": algo,
        "faults": faults,
        "replacements": faults - loads,
        "fault_rate": _num(Fraction(faults, len(refs))) if refs else 0,
        "trace": trace,
    }


# ---------------------------------------------------------------- 处理机调度

def cpu_sched(procs: list, algo: str = "FCFS", quantum: int | None = None,
              rr_new_first: bool = True, small_priority_first: bool = True) -> dict:
    """处理机调度：FCFS / SJF（非抢占）/ SRTF（抢占式 SJF）/ HRRN / RR / PRIO（非抢占）/ PPRIO（抢占）。

    procs: [{"name":"A","arrive":0,"burst":3,"priority":2}, ...]
    rr_new_first: RR 中某进程时间片用完的同一时刻有新进程到达时，新进程先入队（多数国内教材的口径）。
    small_priority_first: 优先数小的优先级高。
    平局一律按到达时间、再按输入顺序。
    """
    algo = algo.upper()
    ps = [dict(p, idx=i, left=p["burst"]) for i, p in enumerate(procs)]
    sign = 1 if small_priority_first else -1
    t = 0
    gantt: list = []
    done: dict = {}
    first_start: dict = {}

    def run(p, start, end):
        if gantt and gantt[-1][0] == p["name"] and gantt[-1][2] == start:
            gantt[-1] = (p["name"], gantt[-1][1], end)
        else:
            gantt.append((p["name"], start, end))
        first_start.setdefault(p["name"], start)
        p["left"] -= end - start
        if p["left"] == 0:
            done[p["name"]] = end

    def tie(p):
        return (p["arrive"], p["idx"])

    if algo == "RR":
        if not quantum:
            raise ValueError("RR 需要 quantum")
        pending = sorted(ps, key=tie)
        queue: list = []
        while pending or queue:
            if not queue:
                t = max(t, pending[0]["arrive"])
            while pending and pending[0]["arrive"] <= t:
                queue.append(pending.pop(0))
            p = queue.pop(0)
            sl = min(quantum, p["left"])
            run(p, t, t + sl)
            t += sl
            arrived = []
            while pending and pending[0]["arrive"] <= t:
                arrived.append(pending.pop(0))
            if p["left"] > 0:
                queue.extend(arrived + [p] if rr_new_first else [p] + arrived)
            else:
                queue.extend(arrived)
    else:
        preemptive = algo in ("SRTF", "PPRIO")

        def key(p):
            if algo == "FCFS":
                return tie(p)
            if algo in ("SJF", "SRTF"):
                return (p["left"],) + tie(p)
            if algo == "HRRN":
                ratio = Fraction(t - p["arrive"] + p["burst"], p["burst"])
                return (-ratio,) + tie(p)
            if algo in ("PRIO", "PPRIO"):
                return (sign * p["priority"],) + tie(p)
            raise ValueError(f"未知算法 {algo}")

        while len(done) < len(ps):
            ready = [p for p in ps if p["arrive"] <= t and p["left"] > 0]
            if not ready:
                t = min(p["arrive"] for p in ps if p["left"] > 0)
                continue
            p = min(ready, key=key)
            if preemptive:
                future = [q["arrive"] for q in ps if q["arrive"] > t and q["left"] > 0]
                end = min([t + p["left"]] + future)
            else:
                end = t + p["left"]
            run(p, t, end)
            t = end

    rows = []
    for p in ps:
        fin = done[p["name"]]
        ta = fin - p["arrive"]
        rows.append({
            "name": p["name"], "arrive": p["arrive"], "burst": p["burst"],
            "start": first_start[p["name"]], "finish": fin,
            "turnaround": ta, "weighted": _num(Fraction(ta, p["burst"])),
            "wait": ta - p["burst"],
        })
    n = len(rows)
    return {
        "algo": algo,
        "avg_turnaround": _num(Fraction(sum(r["turnaround"] for r in rows), n)),
        "avg_weighted": _num(sum(Fraction(r["turnaround"], r["burst"]) for r in rows) / n),
        "avg_wait": _num(Fraction(sum(r["wait"] for r in rows), n)),
        "order": [g[0] for g in gantt],
        "gantt": [list(g) for g in gantt],
        "trace": rows,
    }


# ---------------------------------------------------------------- 银行家算法

def _le(a, b):
    return all(x <= y for x, y in zip(a, b))


def banker(available: list, max: list, allocation: list, request: dict | None = None,
           names: list | None = None) -> dict:
    """银行家算法。request: {"proc": 1, "vec": [1,0,2]}（proc 是下标）。

    返回 safe、一条安全序列（每轮从下标最小的进程开始找），以及 need 矩阵。
    安全序列通常不唯一，判分请用 check_banker_sequence。
    """
    n = len(allocation)
    names = names or [f"P{i}" for i in range(n)]
    need = [[m - a for m, a in zip(max[i], allocation[i])] for i in range(n)]
    out: dict = {"need": need}
    avail = list(available)
    alloc = [list(r) for r in allocation]
    if request:
        i, req = request["proc"], request["vec"]
        if not _le(req, need[i]):
            return {**out, "granted": False, "reason": f"Request > Need[{names[i]}]，出错", "safe": None}
        if not _le(req, avail):
            return {**out, "granted": False, "reason": f"Request > Available，{names[i]} 等待", "safe": None}
        avail = [a - r for a, r in zip(avail, req)]
        alloc[i] = [a + r for a, r in zip(alloc[i], req)]
        need[i] = [x - r for x, r in zip(need[i], req)]
        out["after_request"] = {"available": avail, "allocation": alloc, "need": need}
    seq, trace = _safety(avail, alloc, need, names)
    safe = len(seq) == n
    out.update({"safe": safe, "sequence": seq if safe else None, "trace": trace})
    if request:
        out["granted"] = safe
        out["reason"] = "试分配后系统安全，可以分配" if safe else "试分配后系统不安全，不分配，进程等待"
    return out


def _safety(avail, alloc, need, names):
    work = list(avail)
    finish = [False] * len(alloc)
    seq, trace = [], []
    progress = True
    while progress:
        progress = False
        for i in range(len(alloc)):
            if not finish[i] and _le(need[i], work):
                before = list(work)
                work = [w + a for w, a in zip(work, alloc[i])]
                finish[i] = True
                seq.append(names[i])
                trace.append({"proc": names[i], "work": before, "need": need[i],
                              "allocation": alloc[i], "work+alloc": list(work)})
                progress = True
                break
    return seq, trace


def check_banker_sequence(given, available, max, allocation, request=None, names=None) -> dict:
    """判分：给出的安全序列是否真的安全。given 可以是 ["P1","P3",...] 或 "P1,P3,..."。"""
    n = len(allocation)
    names = names or [f"P{i}" for i in range(n)]
    if isinstance(given, str):
        given = [g.strip() for g in given.replace("→", ",").replace("->", ",").split(",") if g.strip()]
    base = banker(available, max, allocation, request, names)
    st = base.get("after_request", {"available": available, "allocation": allocation, "need": base["need"]})
    work = list(st["available"])
    if sorted(given) != sorted(names):
        return {"correct": False, "reason": "序列必须恰好包含每个进程一次"}
    for g in given:
        i = names.index(g)
        if not _le(st["need"][i], work):
            return {"correct": False, "reason": f"轮到 {g} 时 Need={st['need'][i]} > Work={work}"}
        work = [w + a for w, a in zip(work, st["allocation"][i])]
    return {"correct": True, "reason": "序列中每一步 Need ≤ Work，是安全序列"}


# ---------------------------------------------------------------- 磁盘调度

def disk_sched(head: int, requests: list, algo: str = "FCFS", direction: str = "up",
               to_end: bool = False, max_cyl: int | None = None, min_cyl: int = 0,
               count_return: bool = True) -> dict:
    """磁盘调度：FCFS / SSTF / SCAN / CSCAN（LOOK、CLOOK 是 to_end=False 的别名）。

    to_end=False：SCAN/CSCAN 只走到最远的请求就掉头（汤小丹《计算机操作系统》的例题口径）。
    to_end=True：走到磁道尽头 max_cyl / min_cyl。
    count_return：C-SCAN 跳回另一端的那段距离是否计入寻道长度（汤小丹的例题计入）。
    """
    algo = algo.upper()
    if algo == "LOOK":
        algo, to_end = "SCAN", False
    if algo == "CLOOK":
        algo, to_end = "CSCAN", False
    reqs = list(requests)
    up_dir = direction == "up"
    # 路径点：(柱面, 是否为“跳回另一端”的那一段)
    path: list = []
    if algo == "FCFS":
        path = [(c, False) for c in reqs]
    elif algo == "SSTF":
        left, pos = list(reqs), head
        while left:
            nxt = min(left, key=lambda c: (abs(c - pos), (c < pos) if up_dir else (c > pos)))
            path.append((nxt, False))
            left.remove(nxt)
            pos = nxt
    elif algo in ("SCAN", "CSCAN"):
        if to_end and max_cyl is None:
            raise ValueError("to_end=True 需要 max_cyl")
        ahead = (lambda c: c >= head) if up_dir else (lambda c: c <= head)
        first = sorted((c for c in reqs if ahead(c)), reverse=not up_dir)
        rest = [c for c in reqs if not ahead(c)]
        far, other = (max_cyl, min_cyl) if up_dir else (min_cyl, max_cyl)
        path = [(c, False) for c in first]
        if rest:
            if algo == "SCAN":
                if to_end:
                    path.append((far, False))
                path += [(c, False) for c in sorted(rest, reverse=up_dir)]
            else:
                tail = sorted(rest, reverse=not up_dir)
                if to_end:
                    path += [(far, False), (other, True)]
                    path += [(c, False) for c in tail]
                else:
                    path += [(tail[0], True)] + [(c, False) for c in tail[1:]]
    else:
        raise ValueError(f"未知算法 {algo}")

    trace, total, pos = [], 0, head
    for c, is_return in path:
        d = abs(c - pos)
        counted = d if (count_return or not is_return) else 0
        total += counted
        trace.append({"to": c, "dist": counted, "note": "回程" if is_return else ""})
        pos = c
    order = [c for c in (t["to"] for t in trace) if c in reqs]
    return {
        "algo": algo,
        "order": order,
        "total": total,
        "avg": _num(Fraction(total, len(reqs))) if reqs else 0,
        "trace": trace,
    }


# ---------------------------------------------------------------- 存储管理

def _int(x):
    if isinstance(x, str):
        x = x.strip().lower()
        if x.endswith("h"):
            return int(x[:-1], 16)
        return int(x, 0)
    return int(x)


def addr_translate(page_size: int, page_table: dict, logical, hex_out: bool = False) -> dict:
    """分页地址变换。page_table: {"0": 5, "1": 10, ...}（页号 → 块号）。logical 支持 2500、"0x0A5C"、"0A5Ch"。"""
    la = _int(logical)
    page, offset = divmod(la, page_size)
    table = {int(k): v for k, v in page_table.items()}
    if page not in table or table[page] is None:
        return {"page": page, "offset": offset, "frame": None, "physical": None,
                "reason": "页号不在页表中（越界或缺页）"}
    pa = table[page] * page_size + offset
    return {"page": page, "offset": offset, "frame": table[page],
            "physical": hex(pa) if hex_out else pa}


def eat(mem_ns: float, hit_rate: float, tlb_ns: float = 0, levels: int = 1,
        parallel: bool = False) -> dict:
    """有快表时的有效访问时间。

    串行（默认）：先查 TLB，未命中再访问 levels 级页表。
      EAT = h·(tlb + mem) + (1-h)·(tlb + levels·mem + mem)
    并行：TLB 与页表同时查，未命中时不额外付 tlb。
    """
    h = Fraction(str(hit_rate))
    m, t = Fraction(str(mem_ns)), Fraction(str(tlb_ns))
    hit = t + m
    miss = levels * m + m + (0 if parallel else t)
    value = h * hit + (1 - h) * miss
    return {"eat": _num(value),
            "formula": f"{_num(h)}×{_num(hit)} + {_num(1 - h)}×{_num(miss)} = {_num(value)}"}


def page_table_levels(va_bits: int, page_size: int, pte_bytes: int) -> dict:
    """多级页表：每页能放多少个页表项，需要几级。"""
    offset_bits = page_size.bit_length() - 1
    per_page = page_size // pte_bytes
    idx_bits = per_page.bit_length() - 1
    page_bits = va_bits - offset_bits
    levels = -(-page_bits // idx_bits)
    return {"offset_bits": offset_bits, "page_number_bits": page_bits,
            "entries_per_page": per_page, "index_bits_per_level": idx_bits, "levels": levels}


# ---------------------------------------------------------------- 文件管理

def inode_max(block_size: int, addr_bytes: int, direct: int, single: int = 0,
              double: int = 0, triple: int = 0) -> dict:
    """混合索引分配的最大文件长度。返回块数与字节数（以及 KB/MB/GB 读法）。"""
    k = block_size // addr_bytes
    blocks = direct + single * k + double * k ** 2 + triple * k ** 3
    size = blocks * block_size

    def human(b):
        for unit, s in (("GB", 2 ** 30), ("MB", 2 ** 20), ("KB", 2 ** 10)):
            if b >= s:
                return f"{_num(Fraction(b, s))} {unit}"
        return f"{b} B"
    return {"addrs_per_block": k, "max_blocks": blocks, "max_bytes": size, "human": human(size),
            "parts": {"direct": direct * block_size, "single": single * k * block_size,
                      "double": double * k ** 2 * block_size, "triple": triple * k ** 3 * block_size}}


def inode_locate(byte_offset: int, block_size: int, addr_bytes: int, direct: int) -> dict:
    """给定文件内字节偏移，判断落在直接 / 一次 / 二次 / 三次间接，以及逻辑块号。"""
    k = block_size // addr_bytes
    lb = byte_offset // block_size
    if lb < direct:
        return {"logical_block": lb, "level": "direct", "index": lb}
    lb2 = lb - direct
    if lb2 < k:
        return {"logical_block": lb, "level": "single", "index": lb2}
    lb2 -= k
    if lb2 < k * k:
        return {"logical_block": lb, "level": "double", "index": [lb2 // k, lb2 % k]}
    lb2 -= k * k
    return {"logical_block": lb, "level": "triple", "index": [lb2 // (k * k), (lb2 // k) % k, lb2 % k]}


def bitmap(word_bits: int, block: int | None = None, row: int | None = None, col: int | None = None,
           base: int = 1) -> dict:
    """位示图换算。base=1 表示行号、列号、盘块号都从 1 开始（汤小丹教材口径）；base=0 从 0 开始。"""
    if block is not None:
        b = block - base
        return {"row": b // word_bits + base, "col": b % word_bits + base}
    return {"block": (row - base) * word_bits + (col - base) + base}


REGISTRY = {
    "os.page_replace": page_replace,
    "os.cpu_sched": cpu_sched,
    "os.banker": banker,
    "os.check_banker_sequence": check_banker_sequence,
    "os.disk_sched": disk_sched,
    "os.addr_translate": addr_translate,
    "os.eat": eat,
    "os.page_table_levels": page_table_levels,
    "os.inode_max": inode_max,
    "os.inode_locate": inode_locate,
    "os.bitmap": bitmap,
}
