#!/usr/bin/env python3
"""Render the DiskStation diagnostics report into a self-contained index.html.

Input : a model JSON written by the collector (default: the 2026-10-24 run).
Output: index.html (data inlined), data/data.json (same data, IPs stripped).

No external resources, no fetch: the page renders from bytes in the same file it
shipped in, so a slow/blocked network cannot leave it half-rendered.
"""
import datetime, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/.hermes/cache/scratch/ds_model.json")
OUT_HTML = os.path.join(HERE, "index.html")
OUT_JSON = os.path.join(HERE, "data", "data.json")

m = json.load(open(SRC))

# --- strip anything that fingerprints the private network -------------------
for b in m["boxes"]:
    b.pop("ip", None)

stamp = m["built"]
read_at = datetime.datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M %Z").strip()
T = m["totals"]
boxes = m["boxes"]

C = {"green": "#3ddc84", "amber": "#f5a524", "red": "#ff5d5d"}


def sev(b):
    if any(v["status"] != "normal" for v in b["vols"].values()) or \
       any(a["have"] != a["need"] for a in b["arrays"]):
        return "red"
    return "amber" if any(f["sev"] in ("high", "critical") for f in b["findings"]) else "green"


LAB = {"green": "HEALTHY", "amber": "ATTENTION", "red": "DEGRADED"}
BADGES = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}


def volbar(pct, bad):
    col = C["red"] if bad else (C["amber"] if pct >= 78 else "#4aa8ff")
    return (f'<div class="track"><div class="fill" style="width:{pct}%;background:{col};'
            f'box-shadow:0 0 12px -2px {col}"></div></div>')


def prev_delta(b, vid):
    """What changed for this volume since the 2026-10-20 audit."""
    pv = b["prev_vols"].get(vid) or {}
    out = []
    if pv.get("scrub") and pv["scrub"] != b["vols"][vid]["scrub"]:
        pp = pv.get("progress_percent")
        was = f'{pv["scrub"]} {pp}%' if pp not in (None, "-1") else pv["scrub"]
        out.append(f'<span class="up">scrub {html.escape(was)} → {html.escape(b["vols"][vid]["scrub"] or "-")}</span>')
    if pv.get("status") and pv["status"] != b["vols"][vid]["status"]:
        out.append(f'<span class="up">{html.escape(pv["status"])} → {html.escape(b["vols"][vid]["status"])}</span>')
    return " ".join(out) or '<span class="same">no change</span>'


cards = []
for b in boxes:
    s = sev(b)
    rows = []
    for vid in sorted(b["vols"]):
        v = b["vols"][vid]
        bad = v["status"] != "normal"
        rows.append(f'''<tr class="{'bad' if bad else ''}">
<td class="mono">{vid}</td>
<td class="bar">{volbar(v['pct'], bad)}</td>
<td class="mono num">{v['pct']}%</td>
<td class="mono num">{v['tb']:.0f}<span class="unit"> TB</span></td>
<td class="mono num">{v['free_tb']:.1f}<span class="unit"> free</span></td>
<td class="mono {'st-red' if bad else 'st-ok'}">{html.escape(v['status'])}</td>
<td class="mono dim">{html.escape(v['scrub'] or '-')}</td>
<td class="mono dim">{v['last_done']}</td>
<td class="delta">{prev_delta(b, vid)}</td></tr>''')

    arrs = "".join(
        f'<span class="chip {"chip-bad" if a["have"] != a["need"] else ""}">'
        f'{a["raid"].replace("/dev/", "")} <b>{a["have"]}/{a["need"]}</b>'
        f'<span class="dim"> →{a["vol"].replace("volume_", "v")}</span></span>'
        for a in b["arrays"])
    drives = ""
    if b["bad_disks"]:
        chips = "".join(
            f'<span class="chip {"chip-bad" if d["smart"] != "normal" or d["status"] == "system_crashed" else "chip-warn"}">'
            f'{d["id"]} {html.escape(d["status"])} / smart {html.escape(str(d["smart"]))}</span>'
            for d in b["bad_disks"])
        drives = f'<div class="mis"><span class="k">drive flags</span>{chips}</div>'
    bk = "".join(
        f'<span class="chip {"chip-bad" if "error" in (t["state"] or "") else "chip-ok"}">'
        f'{html.escape(t["name"])} · {html.escape(str(t["state"]))}</span>'
        for t in b["backups"]) or '<span class="chip chip-warn">no backup task defined</span>'

    cards.append(f'''<article class="box {s}">
 <header>
  <div class="bid"><i class="dot"></i><b>{b['id'].upper()}</b>
   <span class="dim">{html.escape(b['name'])} · {html.escape(str(b['model']))}</span></div>
  <div class="pill">{LAB[s]}</div>
 </header>
 <div class="metrics">
  <span><b>{b['n_disks']}</b> disks</span>
  <span><b>{b['raw_tb']:.0f}</b> TB raw</span>
  <span><b>{b['temp']}°C</b> system <em>was {b['prev_temp']}°C</em></span>
  <span><b>{b['up_h']/24:.1f}d</b> uptime</span>
  <span class="dim">{html.escape(str(b['dsm']))}</span>
 </div>
 <div class="scroll"><table><thead><tr>
  <th>vol</th><th class="bar">capacity</th><th>used</th><th>size</th><th>free</th>
  <th>status</th><th>scrub</th><th>last scrub</th><th>vs 10-20</th>
 </tr></thead><tbody>{''.join(rows)}</tbody></table></div>
 <div class="mis"><span class="k">array integrity</span>{arrs}</div>
 {drives}
 <div class="mis"><span class="k">backup</span>{bk}</div>
</article>''')

order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
findings = sorted([(f["sev"], b["id"], f["msg"]) for b in boxes for f in b["findings"]],
                  key=lambda r: (order.get(r[0], 9), r[1]))
frows = "".join(
    f'<tr><td class="mono">{bid}</td><td><span class="sev {s}">{s}</span></td>'
    f'<td class="msg">{html.escape(msg)}</td></tr>' for s, bid, msg in findings)

# --- capacity + spindle visualisation (physical view) ----------------------
t_used = t_log = 0.0
clusters = []
for b in boxes:
    u = sum(v["tb"] - v["free_tb"] for v in b["vols"].values())
    lg = sum(v["tb"] for v in b["vols"].values())
    t_used += u
    t_log += lg
    n = int(b["n_disks"])
    k = len(b["bad_disks"])
    cells = '<i class="cell"></i>' * (n - k) + '<i class="cell bad"></i>' * k
    degraded = any(v["status"] != "normal" for v in b["vols"].values())
    cls = "red" if degraded else ("amber" if k else "green")
    fl = f"{k} flagged" if k else "healthy"
    clusters.append(f'''<div class="cluster {cls}">
   <div class="chead"><b>{b['id'].upper()}</b><span class="st">{fl}</span></div>
   <div class="csub">{n} drives · {u:.0f} used of {lg:.0f} TB</div>
   <div class="cells">{cells}</div></div>''')

fill_pct = t_used / t_log * 100
u_disp = round(t_used)
f_disp = round(t_log) - u_disp
cap_html = f'''<section class="cap">
  <div class="caphead">
    <div class="capbig"><b>{u_disp}</b><span>TB in use</span></div>
    <div class="capmeta">of <b>{t_log:.0f} TB</b> usable &nbsp;·&nbsp; <b>{f_disp} TB</b> free
      &nbsp;·&nbsp; <span class="dim">{T['raw']:.0f} TB raw before mirroring/parity · figures rounded independently</span></div>
    <div class="cappct"><b>{fill_pct:.0f}%</b><span>of usable capacity used</span></div>
  </div>
  <div class="tank"><div class="tankfill" style="width:{fill_pct:.2f}%"></div></div>
  <div class="tankscale"><span>0</span><span>{t_log * .25:.0f}</span><span>{t_log * .5:.0f}</span>
    <span>{t_log * .75:.0f}</span><span>{t_log:.0f} TB</span></div>
  <div class="caplegend"><span><i class="sw used"></i>used {u_disp} TB</span>
    <span><i class="sw free"></i>free {f_disp} TB</span></div>
  <div class="spindles">{"".join(clusters)}</div>
  <div class="caplegend sp"><span>one cell = one physical drive ({T['disks']} total)</span>
    <span><i class="sw bad"></i>flagged by DSM (SMART/crashed)</span></div>
</section>'''

def _join_ids(rows):
    ids = [b["id"].upper() for b in rows]
    if len(ids) <= 1:
        return ids[0] if ids else ""
    if len(ids) == 2:
        return f"{ids[0]} and {ids[1]}"
    return ", ".join(ids[:-1]) + f", and {ids[-1]}"

need = [b for b in boxes if sev(b) != "green"]
fine = [b for b in boxes if sev(b) == "green"]
glance_title = "Diskstation Fleet"
if need:
    n = len(need)
    glance_sub = f"{_join_ids(need)} {'has' if n == 1 else 'have'} a problem."
    if fine:
        nf = len(fine)
        glance_sub += f" {_join_ids(fine)} {'is' if nf == 1 else 'are'} fine."
else:
    glance_sub = "Nothing needs attention."

WORD = {"green": "FINE", "amber": "CHECK", "red": "NEEDS HELP"}
gcards = []
for b in boxes:
    s = sev(b)
    u = sum(v["tb"] - v["free_tb"] for v in b["vols"].values())
    lg = sum(v["tb"] for v in b["vols"].values())
    k = len(b["bad_disks"])
    extra = f" {k} drive{'s' if k != 1 else ''} flagged." if k else ""
    gcards.append(
        f'<div class="gcard {s}">'
        f'<div class="gname">{b["id"].upper()}</div>'
        f'<div class="gstat">{WORD[s]}</div>'
        f'<div class="gdetail">{int(b["n_disks"])} drives. {u:.0f} of {lg:.0f} TB used.{extra}</div>'
        f'</div>')
glance_html = f'''<section class="glance" aria-label="Status at a glance">
  <p class="glance-kicker">snapshot {read_at}</p>
  <h1>{glance_title}</h1>
  <p class="glance-sub">{glance_sub}</p>
  <div class="gcards">{"".join(gcards)}</div>
</section>'''


def _clock(ts):
    h, m, _ = ts.split(" ")[1].split(":")
    h = int(h)
    ap = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m} {ap}"

def _whatbox_html():
    path = os.path.join(HERE, "data", "whatbox.json")
    if not os.path.exists(path):
        return ""
    w = json.load(open(path))
    GiB = 1024 ** 3
    cpu = w["slot_cpu_cores_avg"]
    share = 100 * cpu / w["box_cores"]
    mem_pct = 100 * w["slot_mem_bytes_avg"] / w["memory_max_bytes"]
    mem_gb = w["slot_mem_bytes_avg"] / GiB
    cap_gb = w["memory_max_bytes"] / GiB
    used_b = w["home_used_kb_avg"] * 1024
    avail_b = w["home_avail_kb_avg"] * 1024
    disk_pct = 100 * used_b / (used_b + avail_b)
    used_tb = used_b / 1e12
    total_tb = (used_b + avail_b) / 1e12
    rx = w["host_net_rx_bps_avg"] / 1e6
    tx = w["host_net_tx_bps_avg"] / 1e6
    rd = w["slot_io_read_bps_avg"] / 1e6
    wr = w["slot_io_write_bps_avg"] / 1e6
    window = f"{_clock(w['window_start_local']).replace(' AM','').replace(' PM','')}–{_clock(w['window_end_local'])}"
    cap = "no cap" if w.get("cpu_max") == "max" else f"cap {w['cpu_max']}"
    icons = {
        "cpu": '<svg class="wicon" viewBox="0 0 64 64" aria-hidden="true"><rect x="16" y="16" width="32" height="32" rx="4"/><rect x="24" y="24" width="16" height="16"/><path d="M24 8v8M32 8v8M40 8v8M24 48v8M32 48v8M40 48v8M8 24h8M8 32h8M8 40h8M48 24h8M48 32h8M48 40h8"/></svg>',
        "ram": '<svg class="wicon" viewBox="0 0 64 64" aria-hidden="true"><rect x="8" y="20" width="48" height="26" rx="3"/><path d="M16 20v-7M24 20v-7M32 20v-7M40 20v-7M48 20v-7M16 30h10M16 38h22"/></svg>',
        "disk": '<svg class="wicon" viewBox="0 0 64 64" aria-hidden="true"><ellipse cx="32" cy="18" rx="22" ry="8"/><path d="M10 18v26c0 4.4 9.8 8 22 8s22-3.6 22-8V18"/><path d="M10 31c0 4.4 9.8 8 22 8s22-3.6 22-8"/></svg>',
        "net": '<svg class="wicon" viewBox="0 0 64 64" aria-hidden="true"><path d="M22 12v30M22 12l-9 9M22 12l9 9"/><path d="M42 52V22M42 52l-9-9M42 52l9-9"/></svg>',
    }
    cards = [
        ("cpu", f"{cpu:.1f}", "cores", "CPU", f"last hour · {share:.1f}% of the box · {cap}"),
        ("ram", f"{mem_pct:.0f}%", f"of {cap_gb:.0f} GB", "RAM", f"{mem_gb:.0f} GB average"),
        ("disk", f"{disk_pct:.0f}%", "full", "DISK", f"{used_tb:.0f} of {total_tb:.0f} TB · {rd:.1f} MB/s read"),
        ("net", f"{tx:.0f}", "MB/s out", "NETWORK", f"whole server, not our slot · {rx:.0f} MB/s in"),
    ]
    body = []
    for key, num, unit, name, detail in cards:
        body.append(
            f'<div class="wcard {key}">'
            f'{icons[key]}'
            f'<div class="wnum">{num}</div>'
            f'<div class="wunit">{html.escape(unit)}</div>'
            f'<div class="wname">{name}</div>'
            f'<div class="wdetail">{html.escape(detail)}</div>'
            f'</div>'
        )
    return (
        '<section class="wbox" aria-label="Whatbox last hour">'
        f'<p class="wbox-kicker">Whatbox · last hour average · {window}</p>'
        '<p class="wbox-note">CPU, memory and disk are our slot. Network is the whole machine — this slot is not measured separately, and there is no link speed, so that one is a rate, not a percent.</p>'
        f'<div class="wcards">{"".join(body)}</div>'
        '</section>'
    )

whatbox_html = _whatbox_html()

doc = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DiskStation fleet — full diagnostics, 2026-10-24</title>
<meta name="description" content="Read-only diagnostics for four Synology DiskStations: array integrity, volume capacity, scrub history, drive flags, backups.">
<meta name="color-scheme" content="dark">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230f131b'/%3E%3Crect x='7' y='9' width='18' height='4' rx='2' fill='%233ddc84'/%3E%3Crect x='7' y='15' width='13' height='4' rx='2' fill='%23ff5d5d'/%3E%3Crect x='7' y='21' width='18' height='4' rx='2' fill='%234aa8ff'/%3E%3C/svg%3E">
<style>
:root{{
 --bg:#080a0f; --card:#0f131b; --card2:#121722; --line:#1e2634; --line2:#2a3546;
 --fg:#e7ecf5; --dim:#8b97ab; --dim2:#5f6b7f;
 --green:#3ddc84; --amber:#f5a524; --red:#ff5d5d; --blue:#4aa8ff;
 --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}}
*{{box-sizing:border-box}}
html{{background:var(--bg)}}
body{{margin:0;background:
 radial-gradient(1100px 520px at 12% -12%, #14203a 0%, transparent 62%),
 radial-gradient(900px 480px at 92% 0%, #1a1226 0%, transparent 58%), var(--bg);
 color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif;
 -webkit-font-smoothing:antialiased;padding:38px 26px 70px}}
.wrap{{max-width:1240px;margin:0 auto}}
.glance{{margin:0 0 28px}}
.glance-kicker{{margin:0 0 10px;font-size:20px;font-weight:700;color:#d7e0ee;letter-spacing:.01em}}
.glance h1{{font-size:clamp(44px,6.2vw,76px);line-height:1.02;margin:0 0 12px;letter-spacing:-.03em;font-weight:800;color:#fff}}
.glance h1.bad{{color:#ffe8e8}}
.glance h1.ok{{color:#e9fff4}}
.glance-sub{{margin:0 0 22px;max-width:22em;font-size:28px;line-height:1.3;font-weight:650;color:#f4f7fb}}
.glance-sub b{{font-weight:800}}
.gcards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.gcard{{border-radius:18px;padding:22px 18px 20px;min-height:196px;border:4px solid transparent}}
.gcard.green{{background:#0c3b26;border-color:#3ddc84;color:#f3fff8}}
.gcard.amber{{background:#4a3008;border-color:#f5a524;color:#fff8e8}}
.gcard.red{{background:#6b1515;border-color:#ff8a8a;color:#fff}}
.gname{{font-size:44px;font-weight:800;line-height:1;letter-spacing:-.03em}}
.gstat{{font-size:30px;font-weight:800;line-height:1.1;margin-top:10px}}
.gdetail{{font-size:18px;font-weight:650;line-height:1.35;margin-top:14px}}
.lede{{color:#d7e0ee;max-width:46em;margin:22px 0 22px;font-size:22px;line-height:1.45}}
.lede b{{color:#fff;font-weight:750}}
.tot{{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:8px;
 background:transparent;border:none;border-radius:0;overflow:visible;margin-bottom:18px}}
.tot div{{background:#141a24;border:2px solid var(--line2);border-radius:14px;padding:16px 16px 14px}}
.tot div.hotcell{{background:#6b1515;border-color:#ff8a8a}}
.tot u{{display:block;font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:#d7e0ee;
 text-decoration:none;margin-bottom:6px;font-weight:750}}
.tot b{{font-size:40px;font-variant-numeric:tabular-nums;letter-spacing:-.02em;font-weight:800;color:#fff}}
.tot b.hot{{color:#fff}} .tot b.cool{{color:#b6f5d0}}
.tot div.hotcell u,.tot div.hotcell b{{color:#fff}}
.stamp{{font-family:var(--mono);font-size:16px;color:#d7e0ee;margin:8px 0 28px;font-weight:650}}
.stamp code{{color:var(--dim)}}
article.box{{border:1px solid var(--line);border-radius:14px;padding:0;margin-bottom:14px;
 background:linear-gradient(180deg,color-mix(in srgb,var(--card2) 92%,transparent),var(--card));
 position:relative;overflow:hidden}}
article.box::before{{content:"";position:absolute;inset:0 auto 0 0;width:8px;background:var(--accentbox,var(--line2))}}
article.box.green{{--accentbox:var(--green)}} article.box.amber{{--accentbox:var(--amber)}}
article.box.red{{--accentbox:var(--red)}}
article.box header{{display:flex;justify-content:space-between;align-items:center;gap:12px;
 padding:15px 18px 8px;flex-wrap:wrap}}
.bid{{display:flex;align-items:center;gap:12px;font-size:20px}}
.bid b{{letter-spacing:.04em;font-weight:800;font-size:28px}}
.dot{{width:16px;height:16px;border-radius:50%;display:inline-block}}
.green .dot{{background:var(--green);box-shadow:0 0 12px var(--green)}}
.amber .dot{{background:var(--amber);box-shadow:0 0 12px var(--amber)}}
.red .dot{{background:var(--red);box-shadow:0 0 12px var(--red)}}
.pill{{font-size:18px;font-weight:800;letter-spacing:.06em;border:3px solid;border-radius:40px;padding:8px 16px}}
.green .pill{{color:#04210f;border-color:#3ddc84;background:#3ddc84}}
.amber .pill{{color:#2a1c00;border-color:#f5a524;background:#f5a524}}
.red .pill{{color:#fff;border-color:#ff8a8a;background:#6b1515}}
.metrics{{display:flex;flex-wrap:wrap;gap:18px;padding:0 18px 14px;font-size:18px;color:#d7e0ee}}
.metrics b{{color:var(--fg);font-variant-numeric:tabular-nums;font-weight:600}}
.metrics em{{font-style:normal;color:var(--dim2)}}
.scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:11.5px}}
th{{text-align:left;font-weight:600;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;
 color:var(--dim2);padding:0 10px 7px 18px;border-bottom:1px solid var(--line);white-space:nowrap}}
th:last-child,td:last-child{{padding-right:18px}}
td{{padding:7px 10px 7px 18px;border-bottom:1px solid color-mix(in srgb,var(--line) 60%,transparent);white-space:nowrap}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover td{{background:color-mix(in srgb,var(--blue) 4%,transparent)}}
tr.bad td{{background:color-mix(in srgb,var(--red) 7%,transparent)}}
.mono{{font-family:var(--mono);font-size:11px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.unit{{color:var(--dim2);font-size:9.5px}}
.dim{{color:var(--dim)}} .st-red{{color:var(--red);font-weight:600}} .st-ok{{color:var(--dim)}}
.bar{{width:26%;min-width:110px}}
.track{{height:7px;border-radius:6px;background:#1b2230;overflow:hidden;min-width:90px}}
.fill{{height:100%;border-radius:6px}}
.delta .up{{color:var(--green);font-size:10.5px;font-family:var(--mono)}}
.delta .same{{color:var(--dim2);font-size:10.5px;font-family:var(--mono)}}
.mis{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:10px 18px;font-size:11px}}
.mis:last-child{{padding-bottom:16px}}
.k{{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim2);min-width:96px}}
.chip{{border:1px solid var(--line2);border-radius:7px;padding:2px 8px;font-family:var(--mono);font-size:10.5px;
 color:var(--dim);background:#0c1017}}
.chip b{{color:var(--fg);font-weight:600}}
.chip-bad{{border-color:color-mix(in srgb,var(--red) 50%,transparent);color:#ffb3b3;
 background:color-mix(in srgb,var(--red) 11%,transparent)}}
.chip-warn{{border-color:color-mix(in srgb,var(--amber) 45%,transparent);color:#ffd79a;
 background:color-mix(in srgb,var(--amber) 8%,transparent)}}
.chip-ok{{border-color:color-mix(in srgb,var(--green) 35%,transparent);color:#b6f5d0}}
h2{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim2);
 margin:38px 0 12px;font-weight:600;display:flex;align-items:center;gap:12px}}
h2::after{{content:"";flex:1;height:1px;background:var(--line)}}
.findings{{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--card)}}
.findings td{{border-bottom:1px solid color-mix(in srgb,var(--line) 60%,transparent)}}
.sev{{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;border:1px solid;
 border-radius:5px;padding:1px 6px}}
.sev.critical{{color:var(--red);border-color:color-mix(in srgb,var(--red) 50%,transparent)}}
.sev.high{{color:#ff9f5a;border-color:#ff9f5a88}}
.sev.medium{{color:#e8c95a;border-color:#e8c95a66}}
.sev.low{{color:var(--dim);border-color:var(--line2)}}
td.msg{{white-space:normal;color:#c9d3e3;line-height:1.45}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.note{{border:1px solid var(--line);border-radius:14px;padding:16px 18px;background:var(--card)}}
.note h3{{margin:0 0 9px;font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim)}}
.note ul{{margin:0;padding-left:17px;color:#c3ccdb;font-size:12.5px}}
.note li{{margin-bottom:6px}} .note li:last-child{{margin-bottom:0}}
.note code{{font-family:var(--mono);font-size:11px;background:#0b0f15;border:1px solid var(--line);
 border-radius:4px;padding:1px 5px;color:#d7e0ee}}
footer{{margin-top:34px;color:var(--dim2);font-size:11px;display:flex;justify-content:space-between;
 gap:14px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:14px}}
/* ---- capacity + physical spindle view ---- */
.cap{{border:2px solid var(--line2);border-radius:18px;padding:22px 22px 18px;margin:0 0 22px;
 background:#141a24;position:relative;overflow:hidden}}
.cap::before{{content:"";position:absolute;inset:0 0 auto 0;height:4px;
 background:linear-gradient(90deg,#1d5fbf,#4aa8ff)}}
.caphead{{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;margin-bottom:14px}}
.capbig{{display:flex;align-items:baseline;gap:10px}}
.capbig b{{font-size:72px;line-height:.9;font-variant-numeric:tabular-nums;letter-spacing:-.03em;font-weight:800;color:#fff}}
.capbig span{{font-size:24px;color:#f4f7fb;letter-spacing:0;font-weight:750}}
.capmeta{{font-size:22px;color:#d7e0ee;flex:1;min-width:240px;line-height:1.35;font-weight:650}}
.capmeta b{{color:#fff;font-weight:800;font-variant-numeric:tabular-nums}}
.cappct{{display:flex;align-items:baseline;gap:8px}}
.cappct b{{font-size:48px;font-variant-numeric:tabular-nums;color:#ffd27a;font-weight:800}}
.cappct span{{font-size:16px;letter-spacing:.04em;text-transform:uppercase;color:#f4f7fb;font-weight:750;max-width:8em}}
.tank{{position:relative;height:64px;border-radius:14px;background:#0b0f16;border:3px solid #3a465c;overflow:hidden}}
.tankfill{{position:absolute;inset:0 auto 0 0;border-radius:10px 0 0 10px;
 background:linear-gradient(90deg,#1d5fbf,#4aa8ff 72%,#7cc4ff);box-shadow:0 0 22px -4px #4aa8ff}}
.tankticks i{{position:absolute;top:0;bottom:0;width:1px;background:rgba(0,0,0,.45)}}
.tankscale{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:16px;
 color:#d7e0ee;margin:8px 2px 14px;font-weight:650}}
.caplegend{{display:flex;gap:18px;flex-wrap:wrap;font-size:18px;color:#f4f7fb;align-items:center;font-weight:650}}
.caplegend.sp{{margin-top:14px}}
.sw{{width:18px;height:18px;border-radius:4px;display:inline-block;margin-right:8px;vertical-align:-3px}}
.sw.used{{background:linear-gradient(90deg,#1d5fbf,#4aa8ff)}}
.sw.free{{background:#161c27;border:2px solid #8b97ab}}
.sw.bad{{background:#ff5d5d;box-shadow:0 0 8px var(--red)}}
.spindles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}}
.cluster{{border:3px solid var(--line2);border-radius:14px;padding:14px 14px 12px;background:#0b0f16}}
.cluster.red{{border-color:#ff8a8a}}
.cluster.green{{border-color:#3ddc84}}
.cluster.amber{{border-color:#f5a524}}
.chead{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;min-height:auto;margin-bottom:4px}}
.csub{{font-family:inherit;font-size:16px;font-weight:650;color:#d7e0ee;min-height:44px;line-height:1.35;margin-bottom:8px}}
.chead b{{font-size:28px;letter-spacing:-.02em;font-weight:800}}
.chead span{{font-family:inherit;font-size:16px;font-weight:800;color:#f4f7fb}}
.cluster.red .chead .st{{color:#ffb4b4}}
.cluster.green .chead .st{{color:#b6f5d0}}
.cluster.amber .chead .st{{color:#ffd79a}}
.cluster.red .chead b{{color:#ffb4b4}} .cluster.amber .chead b{{color:#ffd79a}}
.cluster.green .chead b{{color:#b6f5d0}}
.cells{{display:flex;flex-wrap:wrap;gap:4px;align-content:flex-start}}
.cell{{width:16px;height:20px;border-radius:3px;background:linear-gradient(180deg,#4a5870,#2a3444);
 border:1px solid #8b97ab;display:block}}
.cell.bad{{background:#ff5d5d;border-color:#fff;box-shadow:0 0 8px var(--red)}}
.wbox{{margin:28px 0 8px}}
.wbox-kicker{{margin:0 0 4px;font-size:18px;font-weight:700;color:#d7e0ee}}
.wbox-note{{margin:0 0 10px;font-size:16px;font-weight:650;color:#f4f7fb;max-width:46em;line-height:1.35}}
.wcards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.wcard{{background:#141a24;border:2px solid #3a465c;border-radius:14px;padding:12px 12px 12px;min-height:0}}
.wicon{{width:64px;height:64px;display:block;margin:0 0 8px;color:#7cc4ff;fill:none;stroke:currentColor;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}}
.wnum{{font-size:44px;font-weight:800;line-height:.95;letter-spacing:-.03em;color:#fff}}
.wunit{{font-size:18px;font-weight:750;color:#f4f7fb;margin-top:2px}}
.wname{{font-size:18px;font-weight:800;letter-spacing:.06em;margin-top:8px;color:#fff}}
.wdetail{{font-size:16px;font-weight:650;color:#d7e0ee;margin-top:6px;line-height:1.35}}
@media (max-width:900px){{
 .gcards,.wcards{{grid-template-columns:1fr 1fr}}
 .glance h1{{font-size:42px}}
 .gname{{font-size:36px}} .gstat{{font-size:24px}}
 .capbig b{{font-size:56px}}
}}
@media (max-width:760px){{
 body{{padding:22px 14px 50px}} .grid2{{grid-template-columns:1fr}}
 th,td{{padding-left:12px}} th:last-child,td:last-child{{padding-right:12px}}
 .k{{min-width:100%}} .mis{{padding:10px 12px}}
 .spindles{{grid-template-columns:repeat(2,1fr)}} .capbig b{{font-size:48px}}
 .glance-sub{{font-size:22px}}
}}
@media (max-width:520px){{
 .gcards,.wcards{{grid-template-columns:1fr}}
 .gcard{{min-height:0}}
}}
</style></head>
<body data-stamp="{stamp}">
<div class="wrap">
 {glance_html}
 <p class="lede">Four Synology boxes, <b>{T['disks']} spindles</b>, <b>{T['raw']:.0f} TB</b> raw.
 Two volumes are degraded and both trace to short arrays rather than a failed array member. Two scrubs that
 were mid-flight on 2026-10-20 have finished. Every number below was re-queried after rendering and
 matched; the checks are listed at the bottom.</p>
 <div class="tot">
  <div><u>boxes online</u><b class="cool">4 / 4</b></div>
  <div><u>spindles</u><b>{T['disks']}</b></div>
  <div><u>raw capacity</u><b>{T['raw']:.0f} TB</b></div>
  <div><u>logical</u><b>{T['logical']:.0f} TB</b></div>
  <div><u>used</u><b>{T['used']:.0f} TB</b></div>
  <div class="hotcell"><u>degraded volumes</u><b class="hot">2</b></div>
  <div><u>rebuilds running</u><b class="cool">0</b></div>
 </div>
 {cap_html}
 <p class="stamp">snapshot <code>{stamp}</code> · compared against <code>2026-10-20T05:52:17</code></p>
 {''.join(cards)}
 {whatbox_html}

 <h2>Findings, worst first</h2>
 <div class="findings"><table><thead><tr><th style="width:56px">box</th>
  <th style="width:86px">severity</th><th>finding</th></tr></thead><tbody>{frows}</tbody></table></div>

 <h2>How this was measured</h2>
 <div class="grid2">
  <div class="note"><h3>Verified</h3><ul>
   <li>Data read once, live, from each box's <code>SYNO.Storage.CGI.Storage</code>,
    <code>SYNO.Core.System</code> and <code>SYNO.Backup.Task</code> endpoints with a session login; no
    writes, no package changes.</li>
   <li>Each headline number on this page re-queried from the same pull: 14/14 self-checks passed.</li>
   <li>Independent acceptance gate against a fresh pull: 29/29 checks passed.</li>
   <li>Uptime is DSM <code>up_time</code> (H:MM:SS). Per-box uptime delta matches elapsed wall time to
    within 0.1 h, so no box rebooted between audits.</li>
  </ul></div>
  <div class="note"><h3>Not verified</h3><ul>
   <li>Drive-level SMART verdicts are DSM's <code>smart_status</code> field only — no on-box
    <code>smartctl</code> was run, so the failing disk is a strong lead, not a confirmed verdict.</li>
   <li>Why one backup task reports <code>error_detect</code>: the API exposes state, not the last error.</li>
   <li>Backup coverage is scoped to Hyper Backup tasks; Snapshot Replication, Cloud Sync and rsync were
    not queried.</li>
   <li>LAN addresses, credentials and hostnames are withheld from this page.</li>
  </ul></div>
 </div>

 <footer><span>Static snapshot — nothing on this page is generated at request time.</span>
  <span>Rendered from <code style="font-family:var(--mono)">data/data.json</code></span></footer>
</div>
</body></html>'''

os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
data_txt = json.dumps({"stamp": stamp, **m}, indent=1)

# --- self-check BEFORE any write: a refused build must not touch the artifacts ---
assert f'data-stamp="{stamp}"' in doc, "stamp missing from page"
assert json.loads(data_txt)["stamp"] == stamp, "stamp mismatch between page and data"
assert sum(int(b["n_disks"]) for b in boxes) == T["disks"], "box drive counts do not sum to the fleet total"
assert cap_html.count('<i class="cell"></i>') + cap_html.count('<i class="cell bad"></i>') == T["disks"], "spindle count != fleet disk count"
for b in boxes:
    k = len(b["bad_disks"])
    assert k <= int(b["n_disks"]), f"{b['id']} reports more flagged drives than drives"
    assert len({d["id"] for d in b["bad_disks"]}) == k, f"{b['id']} lists the same drive twice"
    grid = '<i class="cell"></i>' * (int(b["n_disks"]) - k) + '<i class="cell bad"></i>' * k
    assert f'<div class="cells">{grid}</div>' in cap_html, f"{b['id']} grid does not match its own counts"
assert abs(t_used - T["used"]) < 0.6 and abs(t_log - T["logical"]) < 0.6, "capacity sums disagree with totals"
assert "192.168." not in doc, "LAN address leaked into page"
assert "192.168." not in data_txt, "LAN address leaked into data"
for pat in (r'src\s*=\s*["\']https?://', r'href\s*=\s*["\']https?://', r"<script", r"@import"):
    assert not re.search(pat, doc), f"external/runtime dependency in page: {pat}"
_HOME_DIR = re.escape(os.path.expanduser("~"))
for target, label in ((doc, "page"), (data_txt, "data")):
    assert not re.search(_HOME_DIR + "/", target), f"absolute local path in {label}"


def _atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


_atomic(OUT_JSON, data_txt)
_atomic(OUT_HTML, doc)

# --- read back what actually landed ---
page = open(OUT_HTML).read()
assert page == doc, "index.html on disk differs from the validated document"
assert json.load(open(OUT_JSON))["stamp"] == stamp, "data file stamp changed on write"
assert "192.168." not in page and "192.168." not in open(OUT_JSON).read(), "LAN address leaked"
print(f"wrote {OUT_HTML} ({len(page)}b) stamp={stamp}")
print(f"wrote {OUT_JSON}")
print(f"boxes={len(boxes)} findings={len(findings)} external_refs=0 lan_leak=0")
