"""验算器注册表：名字 → 函数。题目里的 verify / check 字段按名字引用这里的函数。"""
from __future__ import annotations

import inspect

from . import db_algos, db_sql, os_algos

REGISTRY: dict = {**os_algos.REGISTRY, **db_algos.REGISTRY, **db_sql.REGISTRY}


def get(name: str):
    if name not in REGISTRY:
        raise KeyError(f"没有名为 {name} 的验算器；可用：{', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]


def describe() -> list:
    out = []
    for name, fn in sorted(REGISTRY.items()):
        doc = (inspect.getdoc(fn) or "").splitlines()
        out.append({"name": name, "signature": str(inspect.signature(fn)), "doc": doc[0] if doc else ""})
    return out
