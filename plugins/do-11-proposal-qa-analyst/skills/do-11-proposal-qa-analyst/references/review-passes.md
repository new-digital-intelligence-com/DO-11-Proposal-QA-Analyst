# DO-11 · The four review passes

Work them in this order. Scope first, because a scope defect invalidates the timeline
and the price that were built on it — finding it last means re-reviewing both.

Each pass below lists what to look for and, in italics, the wording that reliably hides
a defect. The italic phrases are the highest-yield thing in this file: they are how an
undefined commitment reads when nobody wrote it deliberately.

---

## Pass A · Scope, quality and quantity

**Every deliverable must be countable and every commitment testable.**

- Can you write down how many of each deliverable, and would the client write the same
  number? If not, it is Undefined.
- Is each quality commitment measurable — a figure, a window, a standard named?
- Is anything excluded stated as excluded? Silence on exclusions is read as inclusion by
  every client and every court.
- Does the scope match the RfP's requirement list item by item? Anything required and
  absent is **Missing**, not an oversight.

*Hiding places:* "and related services" · "as required" · "etc." · "including but not
limited to" · "a number of" · "appropriate" · "industry standard" · "best practice" ·
"reasonable endeavours" · "up to" with no floor · "full support"

**"Up to" is the one to watch.** "Up to 500 endpoints" is a ceiling with no commitment
underneath it — the client reads capacity, the delivery team reads a limit.

---

## Pass B · Timeline and milestones

Run `totals_and_dates.py` first, then read for what it cannot see.

- Does every milestone have a date, or an offset from a named event? "Within 4 weeks of
  contract signature" is fine; "in Q3" is not.
- Do the durations sum to the stated overall term? Add them up.
- Does anything start before its dependency finishes?
- Is there a date the *client* has to hit? An unstated client date is a delivery risk
  the proposal has silently absorbed.
- Do the payment milestones align with the delivery milestones, or does the schedule pay
  for a phase before it completes?

*Hiding places:* "in due course" · "promptly" · "subject to resource availability" ·
"target date" with no consequence · a Gantt chart in an annex that disagrees with the
prose

---

## Pass C · Client prerequisites, dependencies and obligations

The pass most often skipped and the one that costs the most in delivery.

- Is every client obligation stated **explicitly**, in one place, as a list?
- Does each carry a **date or an SLA**, and a **consequence** for non-delivery?
- Are third-party dependencies named — a vendor, a licence, an incumbent's cooperation?
- Are assumptions labelled as assumptions, with what happens if one is wrong?

An obligation without a consequence is not an obligation. "The client will provide
timely access to systems" commits the client to nothing and commits us to working around
its absence for free.

*Hiding places:* "the client will provide access as needed" · "with the client's
cooperation" · "assuming timely feedback" · "subject to site readiness" · "standard
assumptions apply"

---

## Pass D · Commercial model and pricing

`totals_and_dates.py` catches the arithmetic. This pass catches the rest.

- Does every price state its **basis** — per what, per how long, in what currency?
- Is the currency stated at all, and the same one throughout?
- Is tax treatment stated? "€412,300" with no VAT position is two different numbers.
- Does indexation exist, and does it name an index and a date?
- Do the payment terms match the milestones from Pass B?
- Are the assumptions the price rests on written down where the client will read them,
  not only in an internal model?
- Does anything in the price contradict the **agreed terms** — a discount, a cap, a
  liability position? That one escalates rather than going in the list.

*Hiding places:* a total with no breakdown · a rate card in an annex nobody
cross-checked · "prices valid for 30 days" with no start date · "excludes travel" with
no estimate · a discount with no expiry

---

## Before issuing the verdict

- Every blocker is genuinely un-submittable, not merely important.
- Every item has all four parts: quote, location, risk, suggested correction.
- No two findings are merged into one item.
- The **Unchecked** list is present, and names each pass that did not run and why.
- Previously waived blockers are re-reported with the waiver named.
- Nothing in the proposal has been edited.
