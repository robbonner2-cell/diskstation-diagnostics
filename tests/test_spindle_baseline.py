"""The spindle baseline must track what is published, not a hardcoded number.

Regression guard for 2026-10-27: a disk was legitimately added to ds2 (95 -> 96
spindles) and refresh.py's `totals["disks"] == 95` check then failed on every
run, so the published page froze at 2026-10-27 14:01 for four days while all
four boxes were answering. A disk appearing must publish (and be named as a
finding); a disk vanishing must still block.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_refresh():
    spec = importlib.util.spec_from_file_location("refresh_under_test", ROOT / "refresh.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["refresh_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def vol(status="normal", pct=40.0, tb=10.0, free_tb=6.0, scrub="normal", last_done="2026-01-01"):
    return {"status": status, "pct": pct, "tb": tb, "free_tb": free_tb,
            "scrub": scrub, "last_done": last_done}


def boxes_with(ds2_disks):
    """Four boxes shaped like ds_chart_live.build_model's output."""
    spec = {"ds1": 24, "ds2": ds2_disks, "ds3": 24, "ds4": 24}
    out = []
    for bid, n in spec.items():
        out.append({
            "id": bid, "n_disks": n, "raw_tb": 150.0, "up_h": 10.0, "temp": 38,
            "vols": {"volume_1": vol()}, "arrays": [{"raid": "md2", "have": 12, "need": 12}],
            "bad_disks": [], "backups": [{"name": "task", "state": "backupable"}],
        })
    return out


class FakeChart:
    def __init__(self, boxes):
        self._boxes = boxes

    def pull_one(self, bid, ip, port):
        return None, {"st": {"disks": [{"id": "sda", "slot_id": 1}]}}

    def build_model(self, live, prev_snapshot):
        return json.loads(json.dumps(self._boxes)), None


class SpindleBaselineTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_refresh()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.published = Path(self.tmp.name) / "data.json"
        shutil.copy2(ROOT / "data" / "data.json", self.published)
        self.mod.DATA = str(self.published)
        self.logged = []
        self.mod.log = lambda m: self.logged.append(m)
        self.mod.ensure_tunnels = lambda: {b[0]: "127.0.0.1" for b in self.mod.BOXES}
        self.mod.prev_snapshot = lambda: None
        # published baseline is 95 spindles / ds2 23, read from the real file
        self.assertEqual(self.mod.prev_published()["totals"]["disks"], 95)
        self.assertEqual(self.mod.prev_published()["per_box"]["ds2"], 23)

    def wire(self, boxes):
        self.mod.load_chart_module = lambda: FakeChart(boxes)

    def check(self, ck, name):
        return next(c for c in ck if c[0] == name)

    # ACCEPTED case: dad's added disk (95 -> 96) publishes instead of freezing.
    def test_added_disk_publishes_and_is_named(self):
        self.wire(boxes_with(24))
        model = self.mod.build_model()
        self.assertEqual(model["checks"], {"passed": 13, "total": 13})
        self.assertEqual(model["totals"]["disks"], 96)
        ds2 = next(b for b in model["boxes"] if b["id"] == "ds2")
        msgs = [f["msg"] for f in ds2["findings"]]
        self.assertTrue(any("spindle count changed" in m and "23 -> 24" in m for m in msgs),
                        msgs)
        self.assertFalse(any(f["sev"] == "critical" for f in ds2["findings"]), msgs)

    # REJECTED case: a disk vanishing still blocks the publish.
    def test_lost_disk_blocks(self):
        self.wire(boxes_with(22))
        with self.assertRaises(RuntimeError) as ctx:
            self.mod.build_model()
        self.assertIn("self-checks", str(ctx.exception))
        self.assertTrue(any("no box lost a spindle" in m for m in self.logged), self.logged)

    # No published baseline at all -> the plausibility floor applies.
    def test_no_baseline_uses_plausibility_floor(self):
        self.published.unlink()
        self.assertIsNone(self.mod.prev_published())
        self.wire(boxes_with(24))
        model = self.mod.build_model()
        self.assertEqual(model["checks"], {"passed": 13, "total": 13})

    # The old check must be gone: 96 with 96 published is stable, and 95 is a drop.
    def test_published_96_stays_green(self):
        data = json.loads(self.published.read_text())
        data["totals"]["disks"] = 96
        for b in data["boxes"]:
            if b["id"] == "ds2":
                b["n_disks"] = 24
        self.published.write_text(json.dumps(data))
        self.wire(boxes_with(24))
        self.assertEqual(self.mod.build_model()["checks"]["passed"], 13)
        self.wire(boxes_with(23))
        with self.assertRaises(RuntimeError):
            self.mod.build_model()
        self.assertTrue(any("no box lost a spindle" in m for m in self.logged), self.logged)


if __name__ == "__main__":
    unittest.main()