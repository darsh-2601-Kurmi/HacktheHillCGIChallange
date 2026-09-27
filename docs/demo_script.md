# OneCase: 90-second demo script

## Before you go on (2 minutes, at the venue)

1. Turn Wi-Fi **off**. Run `python run.py` in the project folder. The app must load with no network.
2. Open `http://localhost:8000/desk` (the agent desk), press **F11** (full screen), and set browser zoom to **100%** (Ctrl+0).
   The screen is built for 1366×768 and up; at 1366×768 everything in this script is visible without scrolling.
3. Click **Reset demo** (top right). The centre panel says "No case open".
4. Open the Power BI report (`powerbi/Northwind.pbip`, refreshed, or your saved .pbix) for the diagnosis pages,
   and `/impact` in a second browser tab as the live-scenario backup.
5. Optional opener: `http://localhost:8000/` (the landing page) in a third tab.
   If the laptop has no WebGL, the desk switches to its flat view by itself, and the script below still works.

## The 90 seconds (account A, then D)

| Time | Click | Say |
|---|---|---|
| 0:00 | Tile **A** | "A customer in Ashford calls. They have a smart meter. On the right is their last complaint from the data pack: it took **95 days**, was transferred and reopened." |
| 0:12 | **Create case** | "One case, **OC-10001**. It's routed once to Billing resolution by a rule, not a transfer. The bill check has already run: three bills on **estimates** while their smart meter was sending actual reads. **$171.08** over-billed. The agent reads that paragraph out." |
| 0:30 | **Correct and re-issue · $34** | "One click. Bills re-issued on the smart reads, re-checked, resolved **at first contact**, in under a minute. The chart on the right now shows the corrected bills. No $92 field visit." |
| 0:42 | Toggle **Legacy path** (a 6-second animation plays; **Replay** reruns it) | "Here's the same complaint today. Watch the trail: it's wiped every time the case changes system. Phone system, re-keyed into CaseTrack (that's where history is lost, it's in their own system notes), then Helix, then SmartRead, where the read was all along. **46%** chance of a transfer from this intake. Transferred complaints take **38.2 days**, **89%** miss SLA, **27%** reopen, and cost **$121**." |
| 1:00 | Toggle **OneCase**, tile **D**, **Create case** | "Second customer, Fenwick, calls about an outage and a payment reminder. OneCase knows there's an active outage, routes to Network, and…" |
| 1:10 | **Hold billing reminders** | "…holds the reminders. GridWatch never told billing that before." |
| 1:15 | Pick **Billing resolution** → **Reassign, keep this case** | "They also want the reminder cancelled. Reassign: still **OC-10002**, same timeline, full history. That's the whole point: the case moves, the customer never repeats themselves." |
| 1:25 | (point at the wire) | "One line, one case, from first contact to close." |

Hand over to the value and roadmap section.

## If something breaks (30-second fallback)

- **Button does nothing or error:** click **Reset demo** and redo from tile A. Every step takes under a second.
- **App won't start:** open `docs/value_case.html` and the screenshots in the slide deck. Say: "Here's what the agent sees."
  Then walk through A's numbers: estimates on 3 bills, $171.08, one click, and the legacy 46% / 38.2 days / 89% / $121.
- **Report won't open:** switch to the `/impact` tab. Click **Recommended**, then say the two headline numbers
  (plan method 3.23; backlog-aware 4.0 in month 5).

## Likely judge questions

**"How do you know transfers are caused by the intake system?"**
Transfer rate is 33 to 37% across every category, channel, priority, region and quarter, but by intake system it is
**0% for CaseTrack** (6,281 cases) and **46 to 47%** for Billing, Web/App and Telephony. CaseTrack's own note:
"Cases transferred in from other channels lose their history." (`python run.py test`, test_data.py, proves every number.)

**"Why not just use AI?"**
The 2025 pilot got worse every month: containment 16% → 10%, repeat contact 31% → 45%, CSAT 2.6 → 2.0. It couldn't
show a bill breakdown or case history. We fix the plumbing first with rules that are explainable and testable. AI can
come in phase 2, on top of one case with full history.

**"Is 4.0 reachable?"**
Honestly: not by per-case fixes alone. Our recommended package gets to **3.23** on the plan method. Removing every
transfer alone gets to ~3.0. But days to close has tracked the open backlog almost exactly for 24 months (r = 0.99).
If removing transfers frees the capacity our model says it does (a transferred case costs 1.78× the effort),
the backlog clears and **4.0 arrives around month 5**. Status quo keeps falling toward 1.9.

**"What's your biggest risk?"**
Moving intake into one case store on top of nightly-batch legacy systems. Mitigation: start with the three
high-transfer intake points (Billing, Web/App, Telephony) and the case store only. Leave the 1998 billing system of
record untouched in phase 1; OneCase reads from it.

**"Is this real customer data?"**
No. Complaint history and all statistics are from the data pack. Meter reads, bills and the outage flag are
synthetic, seeded and labelled on every screen.

**"Why Calderfield isn't the answer?"**
It lost half its agents (73 → 37), yet its days to close and breach rate match the other regions.
