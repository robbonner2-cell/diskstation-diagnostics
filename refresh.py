#!/usr/bin/env python3
"""Refresh the DiskStation diagnostics page and publish it to GitHub Pages.

One run:
  1. makes sure four SSH tunnels to the boxes are up (through dad's desktop when
     the laptop is not on the 192.168.0.x LAN),
  2. pulls all four boxes live (DSM API, read-only GETs),
  3. derives findings, totals and self-checks from THAT pull,
  4. pulls the Whatbox last-hour figures from the VPS,
  5. rebuilds index.html, commits and pushes (local -> vps -> origin).

Nothing is committed unless the pull and the generator's own asserts both pass,
so a bad pull leaves the published page untouched.

Usage: python3 refresh.py [--no-push] [--keep-tunnel]
Exit: 0 published or unchanged, 1 failed before publishing.
"""
import datetime
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.expanduser("~/.hermes/skills/devops/diskstation-easymode/scripts")
DS_CHART = os.path.join(SKILL, "ds_chart_live.py")
DS_SNAPS = os.path.expanduser("~/.hermes/cache/dsaudit")
LOG = os.path.expanduser("~/.hermes/logs/ds-refresh.log")
DATA = os.path.join(HERE, "data", "data.json")
WHATBOX = os.path.join(HERE, "data", "whatbox.json")
VPS = "vps"
VPS_REPO = "/home/rwbonner/repos/diskstation-diagnostics"
JUMP = "dads-desktop"

# box id, display name, LAN address, tunnel port
BOXES = [("ds1", "Diskstation1", "192.168.0.134", 15001),
         ("ds2", "Diskstation2", "192.168.0.106", 15002),
         ("ds3", "Diskstation3", "192.168.0.124", 15003),
         ("ds4", "Diskstation4", "192.168.0.47", 15004)]


def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def tcp_open(host, port, t=2.0):
    try:
        with socket.create_connection((host, port), timeout=t):
            return True
    except OSError:
        return False


def kill_tunnels():
    """Only our own forwards: ssh -N ... -L 127.0.0.1:1500x."""
    subprocess.run(["pkill", "-f", r"ssh -N .*-L 127\.0\.0\.1:15001"],
                   check=False)
    time.sleep(1)


def ensure_tunnels():
    """Return the ip to hand the collector per box, starting tunnels if needed."""
    if tcp_open(BOXES[0][2], 5001):
        log("lan reachable, pulling direct")
        return {b[0]: b[2] for b in BOXES}

    down = [b for b in BOXES if not tcp_open("127.0.0.1", b[3], 1.0)]
    if down:
        log(f"opening tunnel via {JUMP} for {len(down)} port(s)")
        args = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3"]
        for _, _, ip, port in BOXES:
            args += ["-L", f"127.0.0.1:{port}:{ip}:5001"]
        args.append(JUMP)
        subprocess.Popen(args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 25
        while time.time() < deadline:
            if all(tcp_open("127.0.0.1", b[3], 1.0) for b in BOXES):
                log("tunnel up")
                break
            time.sleep(1)
        else:
            raise RuntimeError("tunnel did not come up; boxes unreachable")

    # 127.0.0.1:5001 refuses instantly, so the collector falls through to the
    # tunnel port without waiting on an unroutable LAN address.
    return {b[0]: "127.0.0.1" for b in BOXES}


def load_chart_module():
    if not os.path.exists(DS_CHART):
        raise RuntimeError(f"collector missing: {DS_CHART}")
    spec = importlib.util.spec_from_file_location("ds_chart_live", DS_CHART)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {DS_CHART}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prev_snapshot():
    if not os.path.isdir(DS_SNAPS):
        return None
    cands = sorted(f for f in os.listdir(DS_SNAPS) if f.endswith("-diag.json"))
    return os.path.join(DS_SNAPS, cands[-1]) if cands else None


def findings_for(b):
    """Every finding is derived from this pull. No carry-over from an old run."""
    out = []
    for vid, v in b["vols"].items():
        if v.get("status") != "normal":
            out.append({"sev": "critical",
                        "msg": f'{vid} is {v.get("status")} ({v.get("pct")}% full)'})
        if v.get("scrub") == "abnormal":
            out.append({"sev": "high", "msg": f'{vid} scrubbingStatus=abnormal'})
        running = v.get("scrub") in ("kernel_running", "mdcheck_running", "running")
        if running:
            out.append({"sev": "low",
                        "msg": f'{vid} scrub running, progress not exposed'})
        elif v.get("last_done") == "never":
            out.append({"sev": "low", "msg": f"{vid} never scrubbed"})
    for a in b["arrays"]:
        if a.get("have") != a.get("need"):
            out.append({"sev": "critical",
                        "msg": f'{a.get("raid")} has {a.get("have")}/{a.get("need")} members '
                               f'(pool {a.get("pool") or a.get("vol")})'})
    for d in b["bad_disks"]:
        smart, status = d.get("smart"), d.get("status")
        base = f'{d.get("id")} {status}, SMART {smart}, {d.get("model")}'
        if smart == "failing":
            out.append({"sev": "high", "msg": base})
        elif status == "system_crashed":
            out.append({"sev": "low", "msg": base})
        else:
            out.append({"sev": "medium", "msg": base})
    if not b["backups"]:
        out.append({"sev": "low", "msg": "no backup task defined"})
    for t in b["backups"]:
        if t.get("state") not in ("backupable", "none", None):
            out.append({"sev": "medium",
                        "msg": f'backup "{t.get("name")}" reports {t.get("state")}'})
    return out


def self_checks(boxes, totals):
    """Real assertions on this pull. The count is published on the page."""
    ck = []

    def add(name, cond, detail=""):
        ck.append((name, bool(cond), str(detail)))

    add("four boxes answered", len(boxes) == 4, len(boxes))
    add("every box reports disks", all(b["n_disks"] > 0 for b in boxes),
        [b["n_disks"] for b in boxes])
    add("spindle total stable (95)", totals["disks"] == 95, totals["disks"])
    add("raw capacity plausible", totals["raw"] > 500, f'{totals["raw"]} TB')
    add("logical <= raw", totals["logical"] <= totals["raw"] + 1,
        f'{totals["logical"]} vs {totals["raw"]}')
    add("used <= logical", totals["used"] <= totals["logical"] + 1,
        f'{totals["used"]} vs {totals["logical"]}')
    add("uptime parsed as hours", all(0 < b["up_h"] < 24 * 400 for b in boxes),
        [f'{b["id"]}={b["up_h"]:.0f}h' for b in boxes])
    add("system temps sane", all(0 < (b["temp"] or 0) < 95 for b in boxes),
        [b["temp"] for b in boxes])
    add("volume pct in range",
        all(0 <= v["pct"] <= 100 for b in boxes for v in b["vols"].values()), "")
    add("flagged drives <= drive count",
        all(len(b["bad_disks"]) <= b["n_disks"] for b in boxes), "")
    add("no duplicate flagged drive",
        all(len({d["id"] for d in b["bad_disks"]}) == len(b["bad_disks"]) for b in boxes), "")
    return ck


def build_model():
    mod = load_chart_module()
    ips = ensure_tunnels()
    live = {}
    for bid, name, lan, port in BOXES:
        base, data = mod.pull_one(bid, ips[bid], port)
        if not data:
            raise RuntimeError(f"{bid}: unreachable on {lan}:5001 and tunnel :{port}")
        data["name"], data["ip"] = name, lan
        live[bid] = data
    boxes, prev_taken = mod.build_model(live, prev_snapshot())
    for b in boxes:
        b["findings"] = findings_for(b)
    totals = {
        "disks": sum(int(b["n_disks"]) for b in boxes),
        "raw": round(sum(float(b["raw_tb"]) for b in boxes), 1),
        "logical": round(sum(v["tb"] for b in boxes for v in b["vols"].values()), 1),
        "used": round(sum(v["tb"] - v["free_tb"] for b in boxes
                          for v in b["vols"].values()), 1),
    }
    ck = self_checks(boxes, totals)
    passed = sum(1 for _, ok, _ in ck if ok)
    for name, ok, detail in ck:
        if not ok:
            log(f"CHECK FAIL {name} [{detail}]")
    if passed != len(ck):
        raise RuntimeError(f"self-checks {passed}/{len(ck)}")
    now = datetime.datetime.now().isoformat()
    return {"stamp": now, "built": now, "totals": totals, "boxes": boxes,
            "prev_taken": prev_taken, "checks": {"passed": passed, "total": len(ck)}}


def refresh_whatbox():
    """Last completed hour of slot metrics, straight from the VPS sampler."""
    remote = r'''
import json, os, sqlite3
con = sqlite3.connect("file:" + os.path.expanduser("~/.hermes/state/host_metrics.db") + "?mode=ro", uri=True)
con.row_factory = sqlite3.Row
r = dict(con.execute("""
SELECT COUNT(*) n, AVG(slot_cpu_cores) slot_cpu_cores_avg,
       AVG(slot_mem_bytes) slot_mem_bytes_avg,
       AVG(slot_io_read_bps) slot_io_read_bps_avg, AVG(slot_io_write_bps) slot_io_write_bps_avg,
       AVG(home_used_kb) home_used_kb_avg, AVG(home_avail_kb) home_avail_kb_avg,
       AVG(net_rx_bps) host_net_rx_bps_avg, AVG(net_tx_bps) host_net_tx_bps_avg,
       MIN(ts_local) window_start_local, MAX(ts_local) window_end_local
FROM samples WHERE ts > strftime('%s','now') - 3600
""").fetchone())
if r["n"] < 10:
    raise SystemExit("too few samples")
r["cpu_max"] = open("/sys/fs/cgroup/rwbonner/cpu.max").read().split()[0]
r["memory_max_bytes"] = int(open("/sys/fs/cgroup/rwbonner/memory.max").read().strip())
r["box_cores"] = os.cpu_count()
r["cpuset"] = open("/sys/fs/cgroup/rwbonner/cpuset.cpus.effective").read().strip()
r["network_scope"] = "host-wide; this slot has no network counter and the link speed is unreadable"
print(json.dumps(r))
'''
    p = subprocess.run(["ssh", "-o", "ConnectTimeout=15", VPS,
                        "python3 -c " + subprocess.list2cmdline([remote])],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError(f"whatbox pull failed: {p.stderr.strip()[:300]}")
    w = json.loads(p.stdout)
    w["measured"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    w["source"] = "host_metrics.db samples, last 3600s, plus cgroup limits read the same minute"
    json.dump(w, open(WHATBOX, "w"), indent=1)
    return w


def git(*args, check=True):
    return subprocess.run(["git", "-C", HERE, *args], capture_output=True,
                          text=True, check=check)


def publish():
    git("add", "index.html", "data/data.json", "data/whatbox.json")
    if subprocess.run(["git", "-C", HERE, "diff", "--cached", "--quiet"]).returncode == 0:
        log("no change, nothing to publish")
        return False
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    git("commit", "-m", f"snapshot: refresh {stamp}")
    git("push", "vps", "main")
    p = subprocess.run(["ssh", "-o", "ConnectTimeout=15", VPS,
                        f"cd {VPS_REPO} && git push origin main"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"origin push failed: {p.stderr.strip()[:300]}")
    log("published")
    return True


def main():
    args = sys.argv[1:]
    if not os.path.isdir(os.path.join(HERE, ".git")):
        log("FATAL not a git checkout")
        return 1
    try:
        try:
            model = build_model()
        except Exception as e:
            log(f"first attempt failed ({e}); clearing tunnels and retrying")
            kill_tunnels()
            model = build_model()
        json.dump(model, open("/tmp/ds_refresh_model.json", "w"), indent=1)
        w = refresh_whatbox()
        gen = subprocess.run([sys.executable, os.path.join(HERE, "build_site.py"),
                              "/tmp/ds_refresh_model.json"],
                             capture_output=True, text=True, cwd=HERE)
        if gen.returncode != 0:
            raise RuntimeError(f"build failed: {gen.stderr.strip()[-400:]}")
        log(f'built stamp={model["stamp"]} whatbox={w["n"]} samples '
            f'checks={model["checks"]["passed"]}/{model["checks"]["total"]}')
        if "--no-push" not in args:
            publish()
    except Exception as e:
        log(f"FAILED {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())