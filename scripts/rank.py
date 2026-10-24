#!/usr/bin/env python3
"""Rank opportunities by how much they move one student toward their dream job.

Cubbie gathers the opportunities (email, Canvas announcements, the web) and the student's commitments
(calendar events, Canvas due dates), writes them to JSON files, and runs this script. The script does the
part Cubbie should not improvise: the same opportunity always gets the same score, with the reasons shown.

    score = value (career fit x kind of leverage + money + selectivity)
          - cost  (hours, dollars against the student's budget, travel time)

Standard library only. State lives under ~/.config/opportunity-radar/ (survives restarts and Skill updates).

Exit codes: 0 ok, 2 bad arguments or unreadable JSON, 3 no profile saved yet, 4 no opportunities to rank.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ASSETS = HERE / "assets"

# How directly each kind of opportunity turns into the dream job. A pipeline (an internship or job at a
# place that hires for it) beats a meeting with people who hire, which beats a credential, and so on.
LEVERAGE = {
    "pipeline": 1.0,     # internship, job, program that feeds straight into the target role
    "access": 0.9,       # time with people who hire or mentor for the role
    "credential": 0.85,  # selective award, publication, fellowship that the field recognizes
    "skill": 0.7,        # builds a skill the role needs
    "money": 0.6,        # pays or funds, little direct career signal
    "exposure": 0.45,    # info sessions, talks, general events
    "other": 0.5,
}
# How costly it is to miss a commitment that overlaps.
CONFLICT_WEIGHT = {"exam": 3, "assignment": 2, "work": 2, "class": 1, "other": 1, "social": 0.5}
DEFAULT_PROFILE = {"max_spend_usd": 200, "max_travel_hours": 6, "hour_value": 1.0}


def fail(message: str, code: int):
    print(message, file=sys.stderr)
    sys.exit(code)


def state_dir() -> Path:
    return Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "opportunity-radar")


def read_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        fail(f"No {what} file at {path}.", 2)
    except ValueError as e:
        fail(f"The {what} file is not valid JSON: {e}", 2)


def parse_day(value) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(n: float) -> str:
    return f"${n:,.0f}"


def score(opp: dict, profile: dict) -> dict:
    fit = max(0.0, min(10.0, num(opp.get("fit"))))
    kind = str(opp.get("leverage") or "other").lower()
    mult = LEVERAGE.get(kind, LEVERAGE["other"])
    award = max(0.0, num(opp.get("award_usd")))
    cost_usd = max(0.0, num(opp.get("cost_usd")))
    hours = max(0.0, num(opp.get("hours")))
    travel = 0.0 if opp.get("remote") else max(0.0, num(opp.get("travel_hours")))
    budget = max(1.0, num(profile.get("max_spend_usd"), DEFAULT_PROFILE["max_spend_usd"]))
    max_travel = num(profile.get("max_travel_hours"), DEFAULT_PROFILE["max_travel_hours"])
    hour_value = max(0.25, num(profile.get("hour_value"), DEFAULT_PROFILE["hour_value"]))

    value = fit * 10 * mult
    value += min(15.0, 5 * math.log10(1 + award / 100))  # $500 ≈ +4, $5,000 ≈ +8.5, capped at +15
    value += 5 if opp.get("selective") else 0

    # Hours on something squarely on the path cost less than hours on a detour.
    cost = min(25.0, hours * 0.6 * hour_value * (1 - 0.5 * fit / 10))
    cost += min(20.0, cost_usd / budget * 10)
    cost += min(15.0, travel * 1.5)
    flags = []
    if cost_usd > budget:
        cost += 10
        flags.append(f"over your {money(budget)} budget")
    if travel > max_travel:
        cost += 10
        flags.append(f"{travel:g}h travel, past your {max_travel:g}h limit")

    return {
        "score": int(max(0, min(100, round(value - cost)))),
        "value": round(value, 1),
        "cost": round(cost, 1),
        "flags": flags,
    }


def overlaps(opp: dict, commitments: list) -> list:
    start = parse_day(opp.get("start"))
    end = parse_day(opp.get("end")) or start
    if not start:
        return []
    hits = []
    for c in commitments:
        cs = parse_day(c.get("start") or c.get("due"))
        ce = parse_day(c.get("end")) or cs
        if cs and cs <= end and ce >= start:
            hits.append(c)
    return hits


def verdict(points: int, conflicts: list) -> tuple[str, list]:
    if points >= 70:
        label = "Top pick"
    elif points >= 50:
        label = "Worth it"
    elif points >= 30:
        label = "Only if you're free"
    else:
        label = "Skip"
    advice = []
    for c in conflicts:
        kind = str(c.get("kind") or "other").lower()
        weight = CONFLICT_WEIGHT.get(kind, 1)
        if kind == "assignment" and num(c.get("weight_pct")) >= 15:
            weight = 3
        title = c.get("title", "something on your calendar")
        if weight >= 3:
            advice.append(f"keep {title}; ask about another date")
        elif points >= 70:
            advice.append(f"worth moving {title}")
        else:
            advice.append(f"not worth missing {title}")
    return label, advice


def rank(profile: dict, opps: list, commitments: list, today: date, seen: set, new_only: bool) -> list:
    out = []
    for o in opps:
        deadline = parse_day(o.get("deadline"))
        if deadline and deadline < today:
            continue
        oid = str(o.get("id") or o.get("title") or "")
        if new_only and oid in seen:
            continue
        s = score(o, profile)
        conflicts = overlaps(o, commitments)
        label, advice = verdict(s["score"], conflicts)
        days_left = (deadline - today).days if deadline else None
        out.append({**o, **s, "id": oid, "verdict": label, "conflicts": advice, "days_left": days_left})
    out.sort(key=lambda r: (-r["score"], r["days_left"] if r["days_left"] is not None else 999))
    return out


def text(rows: list, top: int) -> str:
    lines = []
    for i, r in enumerate(rows[:top], 1):
        head = f"{i}. {r['score']}/100 · {r.get('title', 'Untitled')}"
        if r.get("org"):
            head += f" ({r['org']})"
        lines.append(head)
        lines.append(f"   {r['verdict']}. {r.get('fit_reason') or ''}".rstrip())
        bits = []
        if r["days_left"] is not None:
            bits.append("apply TODAY" if r["days_left"] == 0 else f"deadline in {r['days_left']}d ({r['deadline']})")
        if r.get("start"):
            bits.append(f"on {r['start']}" + (f" to {r['end']}" if r.get("end") and r["end"] != r["start"] else ""))
        bits.append("remote" if r.get("remote") else (r.get("location") or "location unknown"))
        if num(r.get("award_usd")):
            bits.append(f"pays {money(num(r['award_usd']))}")
        if num(r.get("cost_usd")):
            bits.append(f"costs {money(num(r['cost_usd']))}")
        if num(r.get("hours")):
            bits.append(f"{num(r['hours']):g}h")
        lines.append("   " + " · ".join(bits))
        for note in r["flags"] + r["conflicts"]:
            lines.append(f"   ! {note}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
    hidden = len(rows) - min(top, len(rows))
    if hidden > 0:
        lines.append(f"(+{hidden} more ranked lower)")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--opportunities", help="JSON list of opportunities Cubbie gathered")
    p.add_argument("--commitments", help="JSON list of calendar events and Canvas due dates (optional)")
    p.add_argument("--profile", help="JSON profile; with --save-profile it becomes the student's saved profile")
    p.add_argument("--save-profile", action="store_true", help="save --profile for later runs, then exit")
    p.add_argument("--show-profile", action="store_true", help="print the saved profile and exit")
    p.add_argument("--today", help="the student's local date, YYYY-MM-DD (the sandbox clock may be elsewhere)")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--new-only", action="store_true", help="leave out opportunities already sent to the student")
    p.add_argument("--mark-sent", action="store_true", help="remember the shown opportunities as sent")
    p.add_argument("--json", action="store_true")
    p.add_argument("--sample", action="store_true", help="use the bundled sample files; never touches saved state")
    a = p.parse_args()

    sd = state_dir()
    profile_file, seen_file = sd / "profile.json", sd / "sent.json"

    if a.sample:
        profile = read_json(ASSETS / "sample_profile.json", "sample profile")
        opps = read_json(ASSETS / "sample_opportunities.json", "sample opportunities")
        commitments = read_json(ASSETS / "sample_commitments.json", "sample commitments")
        today = date(2026, 10, 24)
        seen = set()
    else:
        if a.save_profile:
            if not a.profile:
                fail("--save-profile needs --profile <file>.", 2)
            prof = read_json(Path(a.profile), "profile")
            if not isinstance(prof, dict) or not prof.get("dream_job"):
                fail("The profile needs at least a dream_job.", 2)
            sd.mkdir(parents=True, exist_ok=True)
            profile_file.write_text(json.dumps({**DEFAULT_PROFILE, **prof}, indent=1))
            print("Profile saved.")
            return
        if a.show_profile:
            if not profile_file.exists():
                fail("No profile saved yet.", 3)
            print(profile_file.read_text())
            return
        if a.profile:
            profile = read_json(Path(a.profile), "profile")
        elif profile_file.exists():
            profile = read_json(profile_file, "saved profile")
        else:
            fail("No profile saved yet. Ask the student for their dream job first.", 3)
        if not a.opportunities:
            fail("--opportunities <file> is required.", 2)
        opps = read_json(Path(a.opportunities), "opportunities")
        commitments = read_json(Path(a.commitments), "commitments") if a.commitments else []
        try:
            today = date.fromisoformat(a.today) if a.today else datetime.now().date()
        except ValueError:
            fail("--today must be YYYY-MM-DD.", 2)
        seen = set(json.loads(seen_file.read_text())) if seen_file.exists() else set()

    if not isinstance(opps, list) or not opps:
        fail("There are no opportunities to rank.", 4)
    rows = rank({**DEFAULT_PROFILE, **profile}, opps, commitments or [], today, seen, a.new_only)
    if not rows:
        fail("Nothing new and still open.", 4)

    if a.mark_sent and not a.sample:
        sd.mkdir(parents=True, exist_ok=True)
        seen_file.write_text(json.dumps(sorted(seen | {r["id"] for r in rows[: a.top]})))

    print(json.dumps(rows[: a.top], indent=1) if a.json else text(rows, a.top))


if __name__ == "__main__":
    main()
