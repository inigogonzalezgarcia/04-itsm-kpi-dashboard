import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_sample_data import FIELDS, generate_tickets  # noqa: E402
from kpi_report import (Ticket, build_report, load_tickets, parse_priority,  # noqa: E402
                        parse_sla, render_html)

AS_OF = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def ticket(prio=3, hours=None, opened_hours_ago=48, group="Service Desk"):
    opened = AS_OF - timedelta(hours=opened_hours_ago)
    resolved = opened + timedelta(hours=hours) if hours is not None else None
    return Ticket("INC1", opened, resolved, prio, "Hardware", group)


def test_parse_priority_formats():
    assert parse_priority("1 - Critical") == 1
    assert parse_priority("P2") == 2
    assert parse_priority("") == 4


def test_parse_sla_overrides_defaults():
    sla = parse_sla("1=2,4=120")
    assert sla[1] == 2 and sla[2] == 8 and sla[4] == 120


def test_sla_compliance_and_median():
    r = build_report([ticket(prio=1, hours=2), ticket(prio=1, hours=6), ticket(prio=3, hours=10)], as_of=AS_OF)
    assert r.overall.resolved == 3 and r.overall.within_sla == 2
    assert r.by_priority[1].sla_rate == 50.0
    assert r.overall.median_hours == 6


def test_open_ticket_past_target_is_breaching():
    r = build_report([ticket(prio=2, opened_hours_ago=10), ticket(prio=4, opened_hours_ago=10)], as_of=AS_OF)
    assert [t.priority for t, _ in r.breaching] == [2]
    assert r.overall.open == 2


def test_loads_servicenow_style_csv(tmp_path):
    path = tmp_path / "tickets.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({"number": "INC9", "opened_at": "2026-09-30 08:00:00", "resolved_at": "",
                    "priority": "2 - High", "category": "Email", "assignment_group": "Service Desk",
                    "state": "In Progress"})
    tickets = load_tickets(path)
    assert tickets[0].priority == 2 and tickets[0].resolved is None


def test_sample_data_renders_report():
    rows = generate_tickets(days=14, seed=2, as_of=AS_OF)
    tickets = [Ticket(r["number"], datetime.fromisoformat(r["opened_at"]).replace(tzinfo=timezone.utc),
                      datetime.fromisoformat(r["resolved_at"]).replace(tzinfo=timezone.utc) if r["resolved_at"] else None,
                      parse_priority(r["priority"]), r["category"], r["assignment_group"]) for r in rows]
    r = build_report(tickets, as_of=AS_OF)
    assert r.overall.tickets == len(rows)
    assert "Service Desk KPI Report" in render_html(r)
