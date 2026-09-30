"""Generate a synthetic service desk ticket export (CSV) for demos and tests.

Columns follow the names of a typical ITSM incident export (for example ServiceNow):
number, opened_at, resolved_at, priority, category, assignment_group, state.
All tickets are fictional.
"""

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

PRIORITIES = ["1 - Critical", "2 - High", "3 - Moderate", "4 - Low"]
PRIORITY_WEIGHTS = [0.03, 0.12, 0.55, 0.30]
# typical resolution time in hours per priority (mean of an exponential distribution)
MEAN_HOURS = {1: 3, 2: 7, 3: 20, 4: 50}
CATEGORIES = ["Hardware", "Software", "Network", "Access", "Email", "Printing", "Telephony"]
GROUPS = ["Service Desk", "Site Support MAD", "Site Support PAR", "Site Support AMS", "Network Ops"]
FIELDS = ["number", "opened_at", "resolved_at", "priority", "category", "assignment_group", "state"]


def generate_tickets(days: int = 84, per_day: int = 22, seed: int = 5,
                     as_of: datetime | None = None) -> list[dict]:
    """Return fictional tickets opened over the last `days` days."""
    rng = random.Random(seed)
    as_of = (as_of or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    tickets = []
    n = 0
    for d in range(days, 0, -1):
        day = as_of - timedelta(days=d)
        weekend = day.weekday() >= 5
        for _ in range(rng.randint(2, 6) if weekend else rng.randint(per_day - 6, per_day + 6)):
            n += 1
            opened = day.replace(hour=rng.randint(7, 19), minute=rng.randint(0, 59))
            prio = rng.choices([1, 2, 3, 4], weights=PRIORITY_WEIGHTS)[0]
            group = "Network Ops" if rng.random() < 0.1 else rng.choice(GROUPS[:4])
            # one site team is slower, so the report has something to show
            slow = 1.6 if group == "Site Support PAR" else 1.0
            hours = rng.expovariate(1 / (MEAN_HOURS[prio] * slow))
            resolved = opened + timedelta(hours=hours)
            if resolved > as_of:
                resolved = None
            tickets.append({
                "number": f"INC{100000 + n}",
                "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"),
                "resolved_at": resolved.strftime("%Y-%m-%d %H:%M:%S") if resolved else "",
                "priority": PRIORITIES[prio - 1],
                "category": rng.choice(CATEGORIES),
                "assignment_group": group,
                "state": "Resolved" if resolved else rng.choice(["New", "In Progress", "On Hold"]),
            })
    return tickets


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic service desk ticket export.")
    parser.add_argument("--days", type=int, default=84, help="days of history (default: 84)")
    parser.add_argument("--seed", type=int, default=5, help="random seed for repeatable data")
    parser.add_argument("--output", default="sample_data/tickets.csv", help="output CSV path")
    args = parser.parse_args()

    tickets = generate_tickets(days=args.days, seed=args.seed)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(tickets)
    print(f"Wrote {len(tickets)} fictional tickets to {out}")


if __name__ == "__main__":
    main()
