"""验算器回归测试：每个用例都对得上教材例题的标准答案。运行：python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from learnforge.verifiers import db_algos as db  # noqa: E402
from learnforge.verifiers import os_algos as os_  # noqa: E402

REFS = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
DISK = [55, 58, 39, 18, 90, 160, 150, 38, 184]
BK = {"available": [3, 3, 2], "max": [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]],
      "allocation": [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]]}
PROCS = [{"name": "A", "arrive": 0, "burst": 4}, {"name": "B", "arrive": 1, "burst": 3},
         {"name": "C", "arrive": 2, "burst": 5}, {"name": "D", "arrive": 3, "burst": 2},
         {"name": "E", "arrive": 4, "burst": 4}]


class OS(unittest.TestCase):
    def test_page_replace(self):
        self.assertEqual([os_.page_replace(3, REFS, a)["faults"] for a in ("FIFO", "LRU", "OPT")], [15, 12, 9])

    def test_belady(self):
        seq = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
        self.assertEqual((os_.page_replace(3, seq)["faults"], os_.page_replace(4, seq)["faults"]), (9, 10))

    def test_disk(self):  # 汤小丹例题
        got = {a: os_.disk_sched(100, DISK, a)["total"] for a in ("FCFS", "SSTF", "SCAN", "CSCAN")}
        self.assertEqual(got, {"FCFS": 498, "SSTF": 248, "SCAN": 250, "CSCAN": 322})

    def test_disk_to_end(self):  # Silberschatz 例题
        req = [98, 183, 37, 122, 14, 124, 65, 67]
        self.assertEqual(os_.disk_sched(53, req, "SCAN", direction="down", to_end=True, max_cyl=199)["total"], 236)
        self.assertEqual(os_.disk_sched(53, req, "CSCAN", to_end=True, max_cyl=199)["total"], 382)

    def test_banker(self):
        self.assertTrue(os_.banker(**BK)["safe"])
        self.assertTrue(os_.banker(**BK, request={"proc": 1, "vec": [1, 0, 2]})["granted"])
        self.assertTrue(os_.check_banker_sequence("P1,P3,P4,P2,P0", **BK)["correct"])
        self.assertFalse(os_.check_banker_sequence("P0,P1,P2,P3,P4", **BK)["correct"])

    def test_sched(self):
        self.assertEqual(os_.cpu_sched(PROCS, "FCFS")["avg_turnaround"], 9)
        self.assertEqual(os_.cpu_sched(PROCS, "SJF")["avg_turnaround"], 8)
        self.assertEqual(os_.cpu_sched(PROCS, "RR", quantum=2)["avg_turnaround"], 11.2)

    def test_memory(self):
        self.assertEqual(os_.addr_translate(1024, {"0": 2, "1": 3, "2": 1, "3": 6}, 2500)["physical"], 1476)
        self.assertEqual(os_.addr_translate(1024, {"0": 2, "1": 3, "2": 1, "3": 6}, "0x0A5C")["physical"], 0x65C)
        self.assertEqual(os_.eat(100, 0.8, 20)["eat"], 140)
        self.assertEqual(os_.page_table_levels(32, 4096, 4)["levels"], 2)

    def test_files(self):
        self.assertEqual(os_.inode_max(1024, 4, 10, 1, 1)["max_blocks"], 65802)
        self.assertEqual(os_.bitmap(16, block=100), {"row": 7, "col": 4})
        self.assertEqual(os_.bitmap(16, row=7, col=4), {"block": 100})


class DB(unittest.TestCase):
    F = "A->BC; CD->E; B->D; E->A"
    SLC = "Sno->Sdept; Sdept->Mname; Sno,Cno->Grade"

    def test_keys_closure(self):
        self.assertEqual(db.closure("B", self.F)["closure"], "BD")
        self.assertEqual(db.keys("ABCDE", self.F)["keys"], ["A", "BC", "CD", "E"])
        self.assertTrue(db.check_keys("E, A, DC, CB", "ABCDE", self.F)["correct"])
        self.assertTrue(db.check_keys("(Sno,Cno)", "Sno,Sdept,Mname,Cno,Grade", self.SLC)["correct"])

    def test_nf(self):
        self.assertEqual(db.normal_form("ABCDE", self.F)["nf"], "3NF")
        self.assertEqual(db.normal_form("Sno,Sdept,Mname,Cno,Grade", self.SLC)["nf"], "1NF")
        self.assertEqual(db.normal_form("ABC", "AB->C; C->B")["nf"], "3NF")
        self.assertEqual(db.normal_form("AB", "A->B")["nf"], "BCNF")

    def test_cover(self):
        self.assertEqual(db.min_cover("A->BC; B->C; A->B; AB->C")["cover"], ["A->B", "B->C"])
        self.assertFalse(db.check_min_cover(["A->B", "B->C", "A->C"], "A->BC; B->C; A->B; AB->C")["correct"])

    def test_decomp(self):
        r = db.decompose_3nf("Sno,Sdept,Mname,Cno,Grade", self.SLC)
        self.assertTrue(r["lossless"])
        self.assertEqual(r["lost_fds"], [])
        b = db.decompose_bcnf("ABC", "AB->C; C->B")
        self.assertTrue(b["lossless"])
        self.assertEqual(b["lost_fds"], ["AB->C"])
        self.assertFalse(db.check_decomposition("AB;AC", "ABC", "A->B; B->C")["correct"])

    def test_txn(self):
        self.assertFalse(db.serializable("r1(A) w1(A) r2(A) w2(A) r2(B) w2(B) r1(B) w1(B)")["serializable"])
        self.assertEqual(db.serializable("r1(A) w1(A) r2(A) w2(A)")["serial_order"], ["T1", "T2"])
        r = db.recovery(["<T1 start>", "<T1 commit>", "<T2 start>", "<checkpoint>", "<T2 commit>", "<T3 start>"])
        self.assertEqual((r["redo"], r["undo"], r["ignore"]), (["T2"], ["T3"], ["T1"]))


if __name__ == "__main__":
    unittest.main()


class Packs(unittest.TestCase):
    def test_bundled_packs_install_and_verify(self):
        import os
        import tempfile
        from learnforge import cli
        from learnforge.grade import verify
        from learnforge.store import Data
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for sub in ("packs", "bank"):
                (root / sub).mkdir()
            (root / "learnforge.yaml").write_text("review_every_days: 7\n", encoding="utf-8")
            self.assertEqual(cli.install_packs(root), ["db", "os"])
            data = Data(root)
            bank = data.bank()
            self.assertEqual(len(bank), 40)
            bad = [q for q in bank.values() if (q.get("verify") or q["type"] == "sql") and not verify(data, q)["ok"]]
            self.assertEqual(bad, [])
