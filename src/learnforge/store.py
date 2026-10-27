"""数据层读写。数据仓库是普通文件：YAML 放配置，JSONL 放只追加的记录。

数据仓库位置按顺序查找：环境变量 LF_DATA → 当前目录向上找 learnforge.yaml → ~/.config/learnforge/config.yaml。
holdout/（盲测卷）只有 holdout 命令能碰，其他代码路径一律经过 _guard 拒绝。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

CONFIG = Path.home() / ".config" / "learnforge" / "config.yaml"
MARKER = "learnforge.yaml"


class LFError(Exception):
    pass


# ---------------------------------------------------------------- 定位

def data_root() -> Path:
    env = os.environ.get("LF_DATA")
    if env:
        return Path(env).expanduser().resolve()
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / MARKER).exists():
            return p
    if CONFIG.exists():
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        if cfg.get("data"):
            return Path(cfg["data"]).expanduser().resolve()
    raise LFError("找不到数据仓库：先运行 lf init-data <目录>，或设置环境变量 LF_DATA")


def register(root: Path) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(yaml.safe_dump({"data": str(root)}, allow_unicode=True), encoding="utf-8")


def _guard(path: Path, allow_holdout: bool = False) -> Path:
    if not allow_holdout and "holdout" in path.parts:
        raise LFError("盲测卷已锁定：只有 lf holdout 命令可以读写 holdout/")
    return path


# ---------------------------------------------------------------- 文件读写

def load_yaml(path: Path, default=None):
    _guard(path)
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def read_jsonl(path: Path, allow_holdout: bool = False) -> list:
    _guard(path, allow_holdout)
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise LFError(f"{path} 第 {n} 行不是合法 JSON：{e}") from e
    return out


def append_jsonl(path: Path, rec: dict, allow_holdout: bool = False) -> None:
    _guard(path, allow_holdout)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def set_yaml_key(path: Path, key: str, value) -> None:
    """改顶层键的值，保留文件里的注释和顺序。"""
    _guard(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    dumped = yaml.safe_dump({key: value}, allow_unicode=True, default_flow_style=True).strip()
    if dumped.startswith("{") and dumped.endswith("}"):
        dumped = dumped[1:-1].strip()
    pat = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    text = pat.sub(dumped, text, count=1) if pat.search(text) else text.rstrip("\n") + f"\n{dumped}\n"
    path.write_text(text, encoding="utf-8")


def now() -> datetime:
    fake = os.environ.get("LF_NOW")  # 测试用：固定“现在”的时间
    return datetime.fromisoformat(fake) if fake else datetime.now()


def stamp() -> str:
    return now().strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------- 数据仓库对象

class Data:
    def __init__(self, root: Path | None = None):
        self.root = root or data_root()
        self.cfg = load_yaml(self.root / MARKER, {}) or {}

    # 路径
    def p(self, *parts) -> Path:
        return _guard(self.root.joinpath(*parts))

    @property
    def attempts_path(self):
        return self.p("ledger", "attempts.jsonl")

    @property
    def errors_path(self):
        return self.p("ledger", "errors.jsonl")

    # 学科包
    def packs(self) -> list:
        d = self.p("packs")
        return sorted(x.name for x in d.iterdir() if (x / "pack.yaml").exists()) if d.exists() else []

    def pack(self, name: str) -> dict:
        info = load_yaml(self.p("packs", name, "pack.yaml"))
        if info is None:
            raise LFError(f"没有学科包 {name}；现有：{', '.join(self.packs()) or '无'}")
        return info

    def concept_map(self, pack: str) -> list:
        """展开 map.yaml：[{id, name, chapter, chapter_name, prereq, weight}]。"""
        m = load_yaml(self.p("packs", pack, "map.yaml"), {}) or {}
        bp = load_yaml(self.p("packs", pack, "blueprint.yaml"), {}) or {}
        weights = bp.get("weights", {}) or {}
        out = []
        for ch in m.get("chapters", []):
            for c in ch.get("concepts", []):
                out.append({"id": c["id"], "name": c["name"], "chapter": ch["id"], "chapter_name": ch["name"],
                            "prereq": c.get("prereq", []), "weight": weights.get(c["id"], 0.0),
                            "pack": pack})
        total = sum(c["weight"] for c in out)
        for c in out:
            c["weight"] = c["weight"] / total if total else 1 / max(len(out), 1)
        return out

    # 题库
    def bank(self) -> dict:
        qs = {}
        d = self.p("bank")
        if d.exists():
            for f in sorted(d.glob("*.jsonl")):
                for q in read_jsonl(f):
                    q["_file"] = f.name
                    qs[q["id"]] = q
        return qs

    def question(self, qid: str) -> dict:
        q = self.bank().get(qid)
        if not q:
            raise LFError(f"题库里没有 {qid}")
        return q

    def pack_of(self, q: dict) -> str:
        return q.get("pack") or q["id"].split("-")[0]

    def resolve(self, q: dict, rel: str) -> Path:
        return self.p("packs", self.pack_of(q), rel)

    def add_question(self, q: dict) -> dict:
        pack = q.get("pack") or (q.get("concept") or ["?"])[0].split(".")[0]
        if pack not in self.packs():
            raise LFError(f"题目的学科包 {pack} 不存在（由 pack 字段或第一个 concept 的前缀决定）")
        source = q.get("source", "gen")
        if source not in ("real", "gen", "seed"):
            raise LFError("source 只能是 real / gen / seed")
        for k in ("concept", "type", "stem"):
            if not q.get(k):
                raise LFError(f"题目缺少字段 {k}")
        known = {c["id"] for c in self.concept_map(pack)}
        unknown = [c for c in q["concept"] if c not in known]
        if unknown:
            raise LFError(f"知识点不在能力地图里：{unknown}（先在 packs/{pack}/map.yaml 里加上）")
        bank = self.bank()
        if not q.get("id"):
            prefix = f"{pack}-{source}-"
            nums = [int(i[len(prefix):]) for i in bank if i.startswith(prefix) and i[len(prefix):].isdigit()]
            q["id"] = f"{prefix}{max(nums, default=0) + 1:04d}"
        elif q["id"] in bank:
            raise LFError(f"题号 {q['id']} 已存在")
        q.setdefault("source", source)
        q.setdefault("created", now().strftime("%Y-%m-%d"))
        q.pop("_file", None)
        append_jsonl(self.p("bank", f"{pack}.{source}.jsonl"), q)
        return q

    # 记录
    def attempts(self) -> list:
        return read_jsonl(self.attempts_path)

    def errors(self) -> list:
        return read_jsonl(self.errors_path)

    def open_errors(self) -> dict:
        """当前未订正的错题：qid → 最近一次错因记录。errors.jsonl 是事件流，fix 事件关闭之前的 open。"""
        state: dict = {}
        for e in self.errors():
            if e.get("event") == "fix" or e.get("fixed") is True:
                state.pop(e["q"], None)
            else:
                state[e["q"]] = e
        return state
