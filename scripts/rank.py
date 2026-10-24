#!/usr/bin/env python3
"""Rank opportunities by how much they move one student toward their dream job.

Cubbie gathers the opportunities (email, Canvas announcements, the school's site, job boards) and the student's
commitments (calendar events, Canvas due dates), writes them to JSON files, and runs this script. The script does
the part Cubbie should not improvise: the same opportunity always gets the same score, with the reasons shown.

Six criteria, each scored 0-100, averaged with the student's own 1-5 importance ratings:
  fit       how well it matches the dream job
  career    how directly it leads there (pipeline > access > credential > skill > money > exposure),
            plus selectivity and a documented track record of past participants
  effort    hours to apply and take part (hours squarely on the path cost less)
  funding   pay, stipend or expected prize value, minus costs not covered by a sponsor, against the budget
  schedule  collisions with exams, graded work, shifts and classes
  travel    remote or close is best; past the student's limit is worst
Fit also scales the total (x0.5 at fit 0, x1 at fit 10), and fit 3 or less is capped at 35:
a cheap, easy detour is still a detour.

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

ASSETS = Path(__file__).resolve().parent.parent / "assets"

LEVERAGE = {"pipeline": 1.0, "access": 0.9, "credential": 0.85, "skill": 0.7, "money": 0.6, "exposure": 0.45,
            "other": 0.5}
CONFLICT_WEIGHT = {"exam": 3, "assignment": 2, "work": 2, "class": 1, "other": 1, "social": 0.5}
CRITERIA = ("fit", "career", "effort", "funding", "schedule", "travel")
DEFAULT_WEIGHTS = {"fit": 5, "career": 4, "effort": 3, "funding": 3, "schedule": 3, "travel": 2}
DEFAULT_PROFILE = {"max_spend_usd": 200, "max_travel_hours": 6, "hour_value": 1.0, "weights": DEFAULT_WEIGHTS}
PRIZE_ODDS = 0.1  # a competition's top prize counts at a tenth of its value: it's a chance, not a paycheck


def fail(message: str, code: int):
    print(message, file=sys.stderr)
    sys.exit(code)


def state_dir() -> Path:
    return Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "opportunity-radar")


def read_json(path, what: str):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        fail(f"No {what} file at {path}.", 2)
    except ValueError as e:
        fail(f"The {what} file is not valid JSON: {e}", 2)


def parse_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(n: float) -> str:
    return f"${n:,.0f}"


def clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def weights_of(profile: dict) -> dict:
    w = {**DEFAULT_WEIGHTS, **(profile.get("weights") or {})}
    return {k: max(1.0, min(5.0, num(w.get(k), 3))) for k in CRITERIA}


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


def conflict_weight(c: dict) -> float:
    kind = str(c.get("kind") or "other").lower()
    if kind == "assignment" and num(c.get("weight_pct")) >= 15:
        return 3
    return CONFLICT_WEIGHT.get(kind, 1)


def score(opp: dict, profile: dict, conflicts: list) -> dict:
    fit = max(0.0, min(10.0, num(opp.get("fit"))))
    budget = max(1.0, num(profile.get("max_spend_usd"), DEFAULT_PROFILE["max_spend_usd"]))
    max_travel = max(0.5, num(profile.get("max_travel_hours"), DEFAULT_PROFILE["max_travel_hours"]))
    hour_value = max(0.25, num(profile.get("hour_value"), 1.0))
    hours = max(0.0, num(opp.get("hours")))
    travel = 0.0 if opp.get("remote") else max(0.0, num(opp.get("travel_hours")))
    award = max(0.0, num(opp.get("award_usd"))) * (PRIZE_ODDS if opp.get("competitive") else 1)
    cost = max(0.0, num(opp.get("cost_usd")) - num(opp.get("sponsored_usd")))
    flags = []

    s = {"fit": fit * 10}
    s["career"] = clamp(LEVERAGE.get(str(opp.get("leverage") or "other").lower(), 0.5) * 85
                        + (8 if opp.get("selective") else 0)
                        + 4 * max(0.0, min(3.0, num(opp.get("track_record")))))
    s["effort"] = clamp(100 - hours * 2.5 * hour_value * (1 - 0.5 * fit / 10))
    net = award - cost
    if net >= 0:
        s["funding"] = clamp(50 + 12 * math.log10(1 + net / 100))
    else:
        s["funding"] = clamp(50 - (-net) / budget * 40)
    if cost > budget:
        s["funding"] = min(s["funding"], 10)
        flags.append(f"costs {money(cost)}, over your {money(budget)} budget")
    s["schedule"] = clamp(100 - 25 * sum(conflict_weight(c) for c in conflicts))
    if any(conflict_weight(c) >= 3 for c in conflicts):
        s["schedule"] = min(s["schedule"], 10)
    if travel > max_travel:
        s["travel"] = 10
        flags.append(f"{travel:g}h of travel, past your {max_travel:g}h limit")
    else:
        s["travel"] = clamp(100 - travel / max_travel * 60)

    w = weights_of(profile)
    total = sum(w[k] * s[k] for k in CRITERIA) / sum(w.values())
    # Fit scales everything: a perfect schedule and zero travel don't make a detour worth taking.
    total *= 0.5 + 0.5 * fit / 10
    if fit <= 3:
        total = min(total, 35)
    if str(opp.get("verified") or "").lower() == "unverified":
        flags.append("couldn't verify this listing yet; apply only through the official site")
    return {"score": int(round(total)), "parts": {k: int(round(v)) for k, v in s.items()}, "flags": flags}


def verdict(points: int, conflicts: list, hours: float) -> tuple[str, list]:
    if hours <= 1 and points >= 30:
        label = "Quick win: under an hour, do it now"
    elif points >= 70:
        label = "Top pick"
    elif points >= 55:
        label = "Worth it"
    elif points >= 40:
        label = "Only if you're free"
    else:
        label = "Skip"
    advice = []
    for c in conflicts:
        title = c.get("title", "something on your calendar")
        if conflict_weight(c) >= 3:
            advice.append(f"keep {title}; ask about another date")
        elif points >= 70:
            advice.append(f"worth moving {title}")
        else:
            advice.append(f"not worth missing {title}")
    return label, advice


SORTS = {
    "score": lambda r: (not r["verdict"].startswith("Quick win"), -r["score"]),
    "deadline": lambda r: (r["days_left"] if r["days_left"] is not None else 999, -r["score"]),
    "travel": lambda r: (0 if r.get("remote") else num(r.get("travel_hours")), -r["score"]),
    "pay": lambda r: (-num(r.get("award_usd")) * (PRIZE_ODDS if r.get("competitive") else 1), -r["score"]),
    "effort": lambda r: (num(r.get("hours")), -r["score"]),
}


def rank(profile: dict, opps: list, commitments: list, today: date, seen: set, new_only: bool):
    out, dropped = [], []
    for o in opps:
        title = o.get("title", "Untitled")
        if str(o.get("verified") or "").lower() == "suspicious":
            dropped.append(f"{title}: looks like a scam ({o.get('warning') or 'failed the legitimacy check'})")
            continue
        if o.get("eligible") is False:
            dropped.append(f"{title}: you're not eligible ({o.get('warning') or 'per the listing'})")
            continue
        deadline = parse_day(o.get("deadline"))
        if deadline and deadline < today:
            continue
        oid = str(o.get("id") or title)
        if new_only and oid in seen:
            continue
        conflicts = overlaps(o, commitments)
        s = score(o, profile, conflicts)
        label, advice = verdict(s["score"], conflicts, num(o.get("hours"), 99))
        out.append({**o, **s, "id": oid, "verdict": label, "conflicts": advice,
                    "days_left": (deadline - today).days if deadline else None})
    return out, dropped


def text(rows: list, dropped: list, top: int) -> str:
    lines = []
    for i, r in enumerate(rows[:top], 1):
        lines.append(f"{i}. {r['score']}/100 · {r.get('title', 'Untitled')}" + (f" ({r['org']})" if r.get("org") else ""))
        lines.append(f"   {r['verdict']}. {r.get('fit_reason') or ''}".rstrip())
        bits = []
        if r["days_left"] is not None:
            bits.append("apply TODAY" if r["days_left"] == 0 else f"deadline in {r['days_left']}d ({r['deadline']})")
        if r.get("start"):
            bits.append(f"on {r['start']}" + (f" to {r['end']}" if r.get("end") and r["end"] != r["start"] else ""))
        if r.get("remote") or r.get("location"):
            bits.append("remote" if r.get("remote") else r["location"])
        if num(r.get("award_usd")):
            bits.append(("top prize " if r.get("competitive") else "pays ") + money(num(r["award_usd"])))
        if num(r.get("cost_usd")):
            covered = num(r.get("sponsored_usd"))
            bits.append(f"costs {money(num(r['cost_usd']))}" + (f" ({money(covered)} covered)" if covered else ""))
        if num(r.get("hours")):
            bits.append(f"{num(r['hours']):g}h")
        lines.append("   " + " · ".join(bits))
        lines.append("   fit {fit} · career {career} · effort {effort} · funding {funding} · schedule {schedule} · travel {travel}".format(**r["parts"]))
        if r.get("track_record_note"):
            lines.append(f"   track record: {r['track_record_note']}")
        for note in r["flags"] + r["conflicts"]:
            lines.append(f"   ! {note}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
    hidden = len(rows) - min(top, len(rows))
    if hidden > 0:
        lines.append(f"(+{hidden} more ranked lower)")
    for d in dropped:
        lines.append(f"Left out: {d}")
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
    p.add_argument("--sort", choices=sorted(SORTS), default="score")
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
        today, seen = date(2026, 10, 24), set()
    else:
        if a.save_profile:
            if not a.profile:
                fail("--save-profile needs --profile <file>.", 2)
            prof = read_json(a.profile, "profile")
            if not isinstance(prof, dict) or not prof.get("dream_job"):
                fail("The profile needs at least a dream_job.", 2)
            old = read_json(profile_file, "saved profile") if profile_file.exists() else {}
            merged = {**DEFAULT_PROFILE, **old, **prof}
            merged["weights"] = {**DEFAULT_WEIGHTS, **(old.get("weights") or {}), **(prof.get("weights") or {})}
            sd.mkdir(parents=True, exist_ok=True)
            profile_file.write_text(json.dumps(merged, indent=1))
            print("Profile saved.")
            return
        if a.show_profile:
            if not profile_file.exists():
                fail("No profile saved yet.", 3)
            print(profile_file.read_text())
            return
        if a.profile:
            profile = read_json(a.profile, "profile")
        elif profile_file.exists():
            profile = read_json(profile_file, "saved profile")
        else:
            fail("No profile saved yet. Ask the student for their dream job first.", 3)
        if not a.opportunities:
            fail("--opportunities <file> is required.", 2)
        opps = read_json(a.opportunities, "opportunities")
        commitments = read_json(a.commitments, "commitments") if a.commitments else []
        try:
            today = date.fromisoformat(a.today) if a.today else datetime.now().date()
        except ValueError:
            fail("--today must be YYYY-MM-DD.", 2)
        seen = set(json.loads(seen_file.read_text())) if seen_file.exists() else set()

    if not isinstance(opps, list) or not opps:
        fail("There are no opportunities to rank.", 4)
    rows, dropped = rank({**DEFAULT_PROFILE, **profile}, opps, commitments or [], today, seen, a.new_only)
    if not rows:
        fail("Nothing new and still open." + "".join(f"\nLeft out: {d}" for d in dropped), 4)
    rows.sort(key=SORTS[a.sort])

    if a.mark_sent and not a.sample:
        sd.mkdir(parents=True, exist_ok=True)
        seen_file.write_text(json.dumps(sorted(seen | {r["id"] for r in rows[: a.top]})))

    print(json.dumps({"ranked": rows[: a.top], "left_out": dropped}, indent=1) if a.json else text(rows, dropped, a.top))


if __name__ == "__main__":
    main()
