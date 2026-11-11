"""Run folders: outputs/runX_[parameters]/"""
import argparse
import json
import tempfile
import unittest
from pathlib import Path

from ev_charging.run_output import new_run_dir, next_run_number, run_folder, run_parameters


def parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evs", type=int, default=10)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--share", type=float, default=0.1)
    ap.add_argument("--start", default="2025-07-07")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    return ap


class TestRunOutput(unittest.TestCase):
    def test_parameters(self):
        ap = parser()
        a = ap.parse_args(["--share", "0.3", "--sample", "--plot"])
        self.assertEqual(run_parameters(a, ap, always=("evs", "days")),
                         ["evs-10", "days-7", "share-0.3", "sample"])   # --plot is output-only
        self.assertEqual(run_parameters(ap.parse_args([]), ap), [])

    def test_numbering_and_folder_contents(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(next_run_number(root), 1)
            (root / "run7_old").mkdir()
            (root / "notes").mkdir()
            self.assertEqual(new_run_dir(root, "greedy", ["evs-10"]).name, "run8_greedy_evs-10")
            ap = parser()
            a = ap.parse_args(["--out", d, "--evs", "3"])
            with run_folder(a, ap, "test", always=("evs",)) as path:
                print("hello")
            self.assertEqual(path.name, "run9_test_evs-3")
            self.assertEqual(a.run_dir, path)
            self.assertIn("hello", (path / "summary.txt").read_text())
            self.assertEqual(json.loads((path / "params.json").read_text())["options"]["evs"], 3)

    def test_long_names_are_cut(self):
        with tempfile.TemporaryDirectory() as d:
            p = new_run_dir(Path(d), "x", ["k-" + "9" * 300])
            self.assertLessEqual(len(p.name), 150)


if __name__ == "__main__":
    unittest.main()
