---
name: opportunity-radar
description: Finds the opportunities that move a student toward their dream job, from professors' emails, Canvas and the web, and ranks them against time, money, distance and their calendar. Use when the student asks what's worth applying to, what they're missing, whether an event or program is worth it, whether to skip class or work for something, or forwards an opportunity email; also for "find me internships, research, fellowships, scholarships, conferences or hackathons in my field", even if they don't say "opportunity".
---

# Opportunity Radar

The most expensive thing a driven student loses is the opportunity they never saw: the research spot a professor
mentioned in one email, the fellowship that closed Friday. This Skill finds those opportunities, scores each one
for this student's dream job, and says plainly whether it's worth their time, money, travel, and anything it
collides with.

## When to use

- "anything worth applying to this week?"
- "my professor sent something about a research position, is it worth it?"
- "is this conference worth skipping class for?"
- "find me internships for UX design"
- "what am I missing?"
- The student forwards or pastes an opportunity email.

Not for: writing the application itself (offer a draft only if asked), or general job-search advice.

## First time: the student's profile

If `python3 scripts/rank.py --show-profile` exits with 3, there is no profile yet. Ask these one at a time, each
with a default the student can accept with "yes", and remember the answers:

1. Their dream job, as specific as they can make it ("product designer at a consumer AI startup", not "tech").
2. Their campus city (to estimate travel).
3. The most they'd spend out of pocket on one opportunity (default $150).
4. The longest trip they'd make, one way, in hours (default 6).
5. How tight their time is right now: light, normal or packed (sets `hour_value` to 0.8, 1.0 or 1.4).

Write the answers to a file and save them:

```bash
python3 scripts/rank.py --profile /tmp/radar-profile.json --save-profile
```

The file holds `dream_job`, `field` (a few words for the field around it), `home`, `max_spend_usd`,
`max_travel_hours` and `hour_value`. When the student changes any of these later, save the profile again.

## Steps

1. **Gather opportunities.** Look in all three places, newest first:
   - The student's email from the last 30 days: search for opportunities from professors, departments, the
     career center and programs (words like research, assistant, fellowship, internship, scholarship, award,
     conference, hackathon, competition, workshop, apply, deadline, nominate). Professors' emails come first.
   - The student's Canvas announcements from the last 30 days, for the same kinds of things.
   - The web: two or three searches built from the dream job and field, for opportunities open now that a
     student can join (from anywhere in the country, or remote). Prefer official pages.
   If the student forwarded or pasted one opportunity, rank just that one (plus anything clearly better you find).
2. **Describe each one** as an object in a JSON list (`/tmp/radar-opps.json`). Read the actual email or page; never
   invent a date, amount or requirement. Leave a field out when the source doesn't say.
   - `id` a short slug, `title`, `org`, `source` (email, canvas or web), `url`
   - `fit` 0 to 10 for this dream job: 9-10 is the job itself or its direct pipeline, 6-8 builds what that role
     hires for, 3-5 is general career value, 0-2 is unrelated. `fit_reason`: one short line in plain words.
   - `leverage`, the main way it helps: `pipeline` (internship, job, program that hires into the role), `access`
     (time with people who hire or mentor, including a professor who could write a letter), `credential`
     (selective award, fellowship, publication), `skill`, `money`, or `exposure` (talks, info sessions)
   - `award_usd` (pay, prize, stipend or scholarship), `cost_usd` (fees plus travel and lodging; estimate travel
     from the student's city with a quick search), `hours` (application plus the commitment), `travel_hours`
     (round trip), `remote` (true or false), `location`
   - `deadline`, `start`, `end` as YYYY-MM-DD; `selective` true when it admits a small share of applicants
3. **Gather commitments** for the weeks the opportunities fall in: the student's Google Calendar events and
   Canvas due dates and exams, as a JSON list (`/tmp/radar-commitments.json`) of `title`, `kind` (exam,
   assignment, class, work, social or other), `start` or `due`, optional `end`, and `weight_pct` for graded work
   when Canvas shows it.
4. **Rank.** Run from this Skill's folder, with the student's local date:

   ```bash
   python3 scripts/rank.py --opportunities /tmp/radar-opps.json --commitments /tmp/radar-commitments.json --today <YYYY-MM-DD> --top 3 --mark-sent
   ```

   Add `--new-only` for scheduled check-ins, so the student only hears about what's new. Use `--json` when you
   need the fields; the plain output is already close to a reply.
5. **Reply** (below), then offer the next step for the top pick, one at a time:
   - "Add the deadline to your calendar?" Add it only after a yes.
   - For a professor's opportunity: "Want me to draft a reply to Prof. ___ saying you're interested?" Draft it in
     the student's Gmail; never send it. They send it.
6. **Offer the weekly radar** the first time: "Want me to check every Sunday at 6 pm and text you only what's new
   and worth it?" Create it only after a yes, at the time and day they pick. Word the check-in so it makes sense
   on its own later: "Opportunity Radar weekly check: gather new opportunities from email, Canvas and the web for
   <dream job>, rank them with rank.py using --new-only, and text the top 3 if any score 50 or more; otherwise
   send nothing."

## How the score works (say this if the student asks)

Score out of 100 = value minus cost. Value is how well it fits the dream job, times how directly it leads there
(a pipeline beats meeting the right people, which beats a credential, a skill, money, then exposure), plus pay and
selectivity. Cost is the hours (less for hours spent squarely on the path), the money against their budget, and
the travel. Over budget or past their travel limit costs extra. 70+ is a top pick, 50-69 worth it, 30-49 only if
they're free, under 30 skip. Anything that takes under an hour and scores 30+ is a quick win and goes first. Exams and heavily weighted work always win a conflict: the Skill never tells a
student to skip an exam; it says to ask about another date.

## Replies

- Short, plain text, no Markdown. Lead with the single best opportunity.
- At most three, each as: score and title, the one-line reason, deadline, cost, time and place, any conflict
  advice, then the link on its own line.
- Put "apply today" or "closes in N days" first when a deadline is within three days.
- More than five worth showing: make a one-page PDF of the full ranked list, send it, and text the top three.
- Never pad. If nothing scores 50 or more, say so in one line and name the closest one.

Example:

```text
Best this week: 70/100 HCI research assistant with Prof. Lee.
Designing AI interfaces with a professor who can write your letter.
Closes in 4 days. 40h, on campus.
https://example.edu/hci-lab/apply

Want me to draft a reply to Prof. Lee?
```

## When something fails

| What happened | What to do |
| --- | --- |
| `rank.py` exits 3 (no profile) | Ask the profile questions above, save, then rank |
| `rank.py` exits 4 (nothing open or new) | One line: nothing new worth their time this week |
| `rank.py` exits 2 (bad file) | Fix the JSON you wrote and run it again once |
| Email or Google not connected | Ask them to connect Google, or to forward the opportunity email; rank what they send |
| Canvas not connected | Skip Canvas and say so in one line |
| A source doesn't give a date or cost | Leave it out of the JSON; mention "deadline not listed" in the reply |

Never invent an opportunity, a deadline or an amount, and never apply, register, pay or send anything for the
student. Every one of those waits for their yes.
