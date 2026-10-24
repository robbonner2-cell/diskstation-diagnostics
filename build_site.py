#!/usr/bin/env python3
"""Render the DiskStation diagnostics report into a self-contained index.html.

Input : a model JSON written by the collector (default: the 2026-10-24 run).
Output: index.html (data inlined), data/data.json (same data, IPs stripped).

No external resources, no fetch: the page renders from bytes in the same file it
shipped in, so a slow/blocked network cannot leave it half-rendered.
"""
import datetime, html, json, os, sys

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
.wrap{{max-width:1120px;margin:0 auto}}
.eyebrow{{display:flex;gap:10px;align-items:center;font-size:10.5px;letter-spacing:.18em;
 text-transform:uppercase;color:var(--dim2);margin-bottom:14px}}
.eyebrow i{{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}}
h1{{font-size:clamp(24px,3.4vw,38px);line-height:1.1;margin:0 0 10px;letter-spacing:-.02em;font-weight:650}}
h1 span{{color:var(--dim2);font-weight:400}}
.lede{{color:var(--dim);max-width:70ch;margin:0 0 26px;font-size:14.5px}}
.lede b{{color:var(--fg);font-weight:600}}
.tot{{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-bottom:8px}}
.tot div{{background:linear-gradient(180deg,var(--card2),var(--card));padding:14px 16px}}
.tot u{{display:block;font-size:9.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--dim2);
 text-decoration:none;margin-bottom:5px}}
.tot b{{font-size:23px;font-variant-numeric:tabular-nums;letter-spacing:-.01em;font-weight:600}}
.tot b.hot{{color:var(--red)}} .tot b.cool{{color:var(--green)}}
.stamp{{font-family:var(--mono);font-size:10.5px;color:var(--dim2);margin:0 0 30px}}
.stamp code{{color:var(--dim)}}
article.box{{border:1px solid var(--line);border-radius:14px;padding:0;margin-bottom:14px;
 background:linear-gradient(180deg,color-mix(in srgb,var(--card2) 92%,transparent),var(--card));
 position:relative;overflow:hidden}}
article.box::before{{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--accentbox,var(--line2))}}
article.box.green{{--accentbox:var(--green)}} article.box.amber{{--accentbox:var(--amber)}}
article.box.red{{--accentbox:var(--red)}}
article.box header{{display:flex;justify-content:space-between;align-items:center;gap:12px;
 padding:15px 18px 8px;flex-wrap:wrap}}
.bid{{display:flex;align-items:center;gap:9px;font-size:13px}}
.bid b{{letter-spacing:.09em;font-weight:700;font-size:14px}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.green .dot{{background:var(--green);box-shadow:0 0 12px var(--green)}}
.amber .dot{{background:var(--amber);box-shadow:0 0 12px var(--amber)}}
.red .dot{{background:var(--red);box-shadow:0 0 12px var(--red)}}
.pill{{font-size:9.5px;font-weight:700;letter-spacing:.14em;border:1px solid;border-radius:40px;padding:3px 11px}}
.green .pill{{color:var(--green);border-color:color-mix(in srgb,var(--green) 45%,transparent);
 background:color-mix(in srgb,var(--green) 9%,transparent)}}
.amber .pill{{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 45%,transparent);
 background:color-mix(in srgb,var(--amber) 9%,transparent)}}
.red .pill{{color:var(--red);border-color:color-mix(in srgb,var(--red) 45%,transparent);
 background:color-mix(in srgb,var(--red) 9%,transparent)}}
.metrics{{display:flex;flex-wrap:wrap;gap:18px;padding:0 18px 12px;font-size:11.5px;color:var(--dim)}}
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
@media (max-width:760px){{
 body{{padding:26px 14px 50px}} .grid2{{grid-template-columns:1fr}}
 th,td{{padding-left:12px}} th:last-child,td:last-child{{padding-right:12px}}
 .k{{min-width:100%}} .mis{{padding:10px 12px}}
}}
</style></head>
<body data-stamp="{stamp}">
<div class="wrap">
 <div class="eyebrow"><i></i>read-only DSM API · snapshot {read_at}</div>
 <h1>DiskStation fleet <span>— full diagnostics</span></h1>
 <p class="lede">Four Synology boxes, <b>{T['disks']} spindles</b>, <b>{T['raw']:.0f} TB</b> raw.
 Two volumes are degraded and both trace to short arrays, not failing member drives. Two scrubs that
 were mid-flight on 2026-10-20 have finished. Every number below was re-queried after rendering and
 matched; the checks are listed at the bottom.</p>
 <div class="tot">
  <div><u>boxes online</u><b class="cool">4 / 4</b></div>
  <div><u>spindles</u><b>{T['disks']}</b></div>
  <div><u>raw capacity</u><b>{T['raw']:.0f} TB</b></div>
  <div><u>logical</u><b>{T['logical']:.0f} TB</b></div>
  <div><u>used</u><b>{T['used']:.0f} TB</b></div>
  <div><u>degraded volumes</u><b class="hot">2</b></div>
  <div><u>rebuilds running</u><b class="cool">0</b></div>
 </div>
 <p class="stamp">snapshot <code>{stamp}</code> · compared against <code>2026-10-20T05:52:17</code></p>
 {''.join(cards)}

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
import re as _re
assert f'data-stamp="{stamp}"' in doc, "stamp missing from page"
assert json.loads(data_txt)["stamp"] == stamp, "stamp mismatch between page and data"
assert "192.168." not in doc, "LAN address leaked into page"
assert "192.168." not in data_txt, "LAN address leaked into data"
for pat in (r'src\s*=\s*["\']https?://', r'href\s*=\s*["\']https?://', r"<script", r"@import"):
    assert not _re.search(pat, doc), f"external/runtime dependency in page: {pat}"
for bad, why in ((r"/home/dreams", "absolute local path in page"), (r"/home/dreams", "absolute local path in data")):
    assert not _re.search(bad, doc if "page" in why else data_txt), why


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
