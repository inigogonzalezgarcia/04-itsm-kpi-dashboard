"""Service desk KPI report from an ITSM ticket export (CSV).

Calculates the numbers a service review needs: volume, mean time to resolve,
SLA compliance by priority and by team, weekly trend and the open tickets that
are already past their SLA target.

Input: CSV with the columns number, opened_at, resolved_at, priority, category,
assignment_group, state (the names used by a typical ServiceNow incident export).
Output: a self-contained HTML report and a CSV of open tickets breaching SLA.

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import html
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

# Resolution targets in hours per priority (1 = critical). Override with --sla.
DEFAULT_SLA_HOURS = {1: 4, 2: 8, 3: 24, 4: 72}
PRIORITY_NAMES = {1: "P1 Critical", 2: "P2 High", 3: "P3 Moderate", 4: "P4 Low"}


@dataclass
class Ticket:
    number: str
    opened: datetime
    resolved: datetime | None
    priority: int
    category: str
    group: str

    def hours_to_resolve(self) -> float | None:
        return (self.resolved - self.opened).total_seconds() / 3600 if self.resolved else None


@dataclass
class Stats:
    tickets: int = 0
    resolved: int = 0
    within_sla: int = 0
    hours: list = field(default_factory=list)
    open: int = 0

    def add(self, t: Ticket, sla: dict) -> None:
        self.tickets += 1
        h = t.hours_to_resolve()
        if h is None:
            self.open += 1
            return
        self.resolved += 1
        self.hours.append(h)
        self.within_sla += h <= sla.get(t.priority, float("inf"))

    @property
    def sla_rate(self) -> float | None:
        return self.within_sla / self.resolved * 100 if self.resolved else None

    @property
    def median_hours(self) -> float | None:
        return median(self.hours) if self.hours else None

    @property
    def mean_hours(self) -> float | None:
        return sum(self.hours) / len(self.hours) if self.hours else None


@dataclass
class Report:
    as_of: datetime
    sla: dict
    overall: Stats
    by_priority: dict
    by_group: dict
    weekly: list
    breaching: list
    aged_backlog: int


def parse_priority(value: str) -> int:
    """'2 - High', 'P2', '2' -> 2. Unknown values count as the lowest priority."""
    digits = [c for c in str(value) if c.isdigit()]
    return int(digits[0]) if digits and 1 <= int(digits[0]) <= 4 else 4


def parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_tickets(path: str | Path) -> list[Ticket]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    missing = {"number", "opened_at", "resolved_at", "priority"} - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
    return [Ticket(r["number"], parse_dt(r["opened_at"]), parse_dt(r["resolved_at"]),
                   parse_priority(r["priority"]), r.get("category") or "(none)",
                   r.get("assignment_group") or "(none)") for r in rows]


def parse_sla(text: str | None) -> dict:
    """'1=4,2=8,3=24,4=72' -> {1: 4.0, ...}"""
    sla = dict(DEFAULT_SLA_HOURS)
    for part in filter(None, (text or "").split(",")):
        prio, hours = part.split("=")
        sla[int(prio)] = float(hours)
    return sla


def build_report(tickets: list[Ticket], as_of: datetime | None = None, sla: dict | None = None) -> Report:
    as_of = as_of or datetime.now(timezone.utc)
    sla = sla or dict(DEFAULT_SLA_HOURS)
    overall, by_prio, by_group = Stats(), defaultdict(Stats), defaultdict(Stats)
    weeks: dict = defaultdict(lambda: {"opened": 0, "stats": Stats()})
    breaching = []

    for t in tickets:
        overall.add(t, sla)
        by_prio[t.priority].add(t, sla)
        by_group[t.group].add(t, sla)
        week = (t.opened - timedelta(days=t.opened.weekday())).date()
        weeks[week]["opened"] += 1
        if t.resolved:
            rweek = (t.resolved - timedelta(days=t.resolved.weekday())).date()
            weeks[rweek]["stats"].add(t, sla)
        else:
            age = (as_of - t.opened).total_seconds() / 3600
            if age > sla.get(t.priority, float("inf")):
                breaching.append((t, age))

    breaching.sort(key=lambda x: (x[0].priority, -x[1]))
    aged = sum(1 for t in tickets if not t.resolved and (as_of - t.opened).days > 7)
    weekly = [(w, v["opened"], v["stats"]) for w, v in sorted(weeks.items())]
    return Report(as_of, sla, overall, dict(sorted(by_prio.items())),
                  dict(sorted(by_group.items(), key=lambda kv: kv[1].sla_rate or 0)),
                  weekly, breaching, aged)


def write_breach_csv(report: Report, path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["number", "priority", "assignment_group", "category", "opened_at",
                    "age_hours", "sla_target_hours"])
        for t, age in report.breaching:
            w.writerow([t.number, PRIORITY_NAMES[t.priority], t.group, t.category,
                        t.opened.strftime("%Y-%m-%d %H:%M"), round(age, 1), report.sla[t.priority]])


# --------------------------------------------------------------------------- HTML

CSS = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--bar:#2a78d6;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px}
.meta{color:var(--ink2);margin:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:24px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .label{color:var(--ink2);font-size:13px}.tile .value{font-size:28px;font-weight:600;font-variant-numeric:tabular-nums}
.tile .note{color:var(--muted);font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:4px 16px;overflow-x:auto}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--grid);white-space:nowrap}
th.num{text-align:right}
th{color:var(--ink2);font-weight:500;font-size:13px}tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--grid);border-radius:4px;min-width:120px}
.bar span{display:block;height:8px;background:var(--bar);border-radius:4px}
.badge{display:inline-flex;align-items:center;gap:4px;margin:0 6px 2px 0;font-size:12px;color:var(--ink)}
.badge i{width:8px;height:8px;border-radius:50%;display:inline-block}
.critical i{background:var(--critical)}.serious i{background:var(--serious)}.warning i{background:var(--warning)}
.badge b{font-weight:600}
footer{color:var(--muted);font-size:12px;margin-top:32px}
"""


def _hours(h: float | None) -> str:
    if h is None:
        return "-"
    return f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} d"


def _pct(p: float | None) -> str:
    return "-" if p is None else f"{p:.1f}%"


def _bar(p: float | None, label: str) -> str:
    width = 0 if p is None else p
    return (f"<td title='{html.escape(label)}: {_pct(p)} within SLA'><div class='bar'>"
            f"<span style='width:{width:.1f}%'></span></div></td>")


def render_html(r: Report, title: str = "Service Desk KPI Report") -> str:
    e = html.escape
    o = r.overall
    tiles = [
        ("Tickets", f"{o.tickets:,}", f"{o.resolved:,} resolved"),
        ("SLA compliance", _pct(o.sla_rate), "resolved within target"),
        ("Median time to resolve", _hours(o.median_hours), f"mean {_hours(o.mean_hours)}"),
        ("Open backlog", f"{o.open:,}", f"{r.aged_backlog} older than 7 days"),
        ("Breaching SLA now", f"{len(r.breaching):,}", "open and past target"),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="label">{e(l)}</div><div class="value">{v}</div>'
        f'<div class="note">{e(n)}</div></div>' for l, v, n in tiles)

    prio_rows = "".join(
        f"<tr><td>{PRIORITY_NAMES[p]}</td><td class='num'>{_hours(r.sla[p])}</td>"
        f"<td class='num'>{s.resolved}</td><td class='num'>{_hours(s.median_hours)}</td>"
        f"<td class='num'>{_pct(s.sla_rate)}</td>{_bar(s.sla_rate, PRIORITY_NAMES[p])}</tr>"
        for p, s in r.by_priority.items())

    group_rows = "".join(
        f"<tr><td>{e(g)}</td><td class='num'>{s.resolved}</td><td class='num'>{_hours(s.median_hours)}</td>"
        f"<td class='num'>{s.open}</td><td class='num'>{_pct(s.sla_rate)}</td>{_bar(s.sla_rate, g)}</tr>"
        for g, s in r.by_group.items())

    week_rows = "".join(
        f"<tr><td>{w:%d %b %Y}</td><td class='num'>{opened}</td><td class='num'>{s.resolved}</td>"
        f"<td class='num'>{opened - s.resolved:+d}</td><td class='num'>{_pct(s.sla_rate)}</td>"
        f"{_bar(s.sla_rate, f'Week of {w:%d %b}')}</tr>"
        for w, opened, s in r.weekly)

    breach_rows = "".join(
        f"<tr><td>{e(t.number)}</td><td>{PRIORITY_NAMES[t.priority]}</td><td>{e(t.group)}</td>"
        f"<td>{e(t.category)}</td><td class='num'>{_hours(age)}</td>"
        f"<td><span class='badge critical'><i></i><b>&#10005;</b>over {_hours(r.sla[t.priority])} target</span></td></tr>"
        for t, age in r.breaching[:50]) or "<tr><td colspan='6'>No open tickets past their SLA target.</td></tr>"
    more = f"<p class='meta'>Showing 50 of {len(r.breaching)}; the full list is in the CSV.</p>" if len(r.breaching) > 50 else ""

    head = "<th class='num'>{}</th>".format
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{e(title)}</h1>
<p class="meta">Data as of {r.as_of:%d %b %Y %H:%M} UTC &middot; SLA targets P1 {_hours(r.sla[1])}, P2 {_hours(r.sla[2])},
P3 {_hours(r.sla[3])}, P4 {_hours(r.sla[4])}</p>
<section class="tiles">{tiles_html}</section>
<h2>By priority</h2>
<div class="card"><table><thead><tr><th>Priority</th>{head("Target")}{head("Resolved")}{head("Median TTR")}
{head("Within SLA")}<th></th></tr></thead><tbody>{prio_rows}</tbody></table></div>
<h2>By team</h2>
<div class="card"><table><thead><tr><th>Assignment group</th>{head("Resolved")}{head("Median TTR")}{head("Open")}
{head("Within SLA")}<th></th></tr></thead><tbody>{group_rows}</tbody></table></div>
<h2>Weekly trend</h2>
<div class="card"><table><thead><tr><th>Week starting</th>{head("Opened")}{head("Resolved")}{head("Net")}
{head("Within SLA")}<th></th></tr></thead><tbody>{week_rows}</tbody></table></div>
<h2>Open tickets past SLA ({len(r.breaching)})</h2>
<div class="card"><table><thead><tr><th>Ticket</th><th>Priority</th><th>Team</th><th>Category</th>{head("Age")}
<th>Status</th></tr></thead><tbody>{breach_rows}</tbody></table></div>{more}
<footer>Generated by itsm-kpi-dashboard. Times are calendar hours.</footer>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Service desk KPI report from an ITSM ticket export.")
    parser.add_argument("input", help="CSV export of tickets")
    parser.add_argument("--out-dir", default="output", help="folder for report.html and sla_breaches.csv")
    parser.add_argument("--sla", help="resolution targets in hours, e.g. 1=4,2=8,3=24,4=72")
    parser.add_argument("--title", default="Service Desk KPI Report", help="report title")
    args = parser.parse_args()

    report = build_report(load_tickets(args.input), sla=parse_sla(args.sla))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(report, args.title), encoding="utf-8")
    write_breach_csv(report, out / "sla_breaches.csv")
    o = report.overall
    print(f"{o.tickets} tickets, SLA {_pct(o.sla_rate)}, median TTR {_hours(o.median_hours)}, "
          f"{len(report.breaching)} open tickets past SLA.")
    print(f"Report: {out / 'report.html'}\nBreaches: {out / 'sla_breaches.csv'}")


if __name__ == "__main__":
    main()
