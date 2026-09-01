# DO-11 — Proposal QA Analyst

NDI's DO-11 is a Claude plugin that reviews a **proposal or bid before it is submitted**:
scope and quantities defined, timeline and milestones coherent, client obligations explicit,
the commercial model adding up, mandatory content present. It returns a **PASS** or
**FIX-REQUIRED** verdict with a numbered fix list that keeps blockers and recommendations
apart.

> **It never edits the proposal.** Independence of review is the whole point — a reviewer
> that edits becomes a co-author, and a co-author cannot gate their own work. Phase 4 of the
> archetype (apply approved fixes) is deliberately **disabled** for this employee. A blocker
> leaves the list in exactly two ways: it is fixed by whoever owns the document, or a named
> person waives it and their name is recorded against the risk.

## Where DO-11 sits

```
DO-14 decides whether to bid.        (before)
DO-02 writes the proposal.           (during)
GP-20 prices the solution.           (during)
DO-11 reviews it before it goes out. (after)   ← this employee
```

No scope overlap to resolve here — the role spec is explicit that DO-11 does not write
proposals, "that is DO-2's job".

## Installation

This repository contains the **plugin only**. The marketplace that lists it lives in
[NDI-AI-Employees](https://github.com/new-digital-intelligence-com/NDI-AI-Employees), so
one `marketplace add` gets you every NDI AI Employee:

```
/plugin marketplace add new-digital-intelligence-com/NDI-AI-Employees
/plugin install do-11-proposal-qa-analyst@ndi-ai-employees
```

**Auto-update is off by default** for a third-party marketplace — it defaults on only for
Anthropic's own. Enable it in Customize → Plugins, or pull manually:

```
/plugin marketplace update ndi-ai-employees
```

## Command syntax

```
/do-11-proposal-qa-analyst
```

Then attach the proposal, the RfP, and the agreed terms. Or simply:

```
Review this proposal before we submit it. RfP and agreed terms attached.
```

**Attach the agreed terms, not just the proposal and the RfP.** The highest-value check in
the role spec is "does this proposal commit to terms that were never agreed" — and with no
CRM connected, the only way it can run is if you supply them. Without them the employee says
so rather than issuing a PASS that never looked.

## Repository structure

```
.
├── plugins/
│   └── do-11-proposal-qa-analyst/
│       ├── .claude-plugin/
│       │   └── plugin.json
│       └── skills/
│           └── do-11-proposal-qa-analyst/
│               ├── SKILL.md
│               ├── review-config.yaml            [the pack's configuration, as built]
│               ├── references/
│               │   └── review-passes.md          [the five passes, and what each catches]
│               ├── scripts/
│               │   ├── consistency_table.py      [CONFLICT / VARIANT / UNVERIFIED]
│               │   ├── totals_and_dates.py       [stated totals vs their columns; date order]
│               │   ├── staleness.py              [expiry, superseded, retired, max_age]
│               │   └── audit_log.py              [append-only JSONL; waivers by name]
│               └── templates/
│                   └── compliance-checklist.yaml [a SHAPE, not a checklist]
├── Sample Input/       [a proposal, its RfP, and the agreed terms — they disagree]
├── Sample Output/      [both reports, verbatim, and a waiver record]
└── README.md
```

The skill lives inside the plugin because Claude's loader blocks path traversal outside the
plugin root.

## Testing it

Attach all three files from `Sample Input/` and name **`RFP_Kestrel.md` as the authority**.
Four runs worth doing:

| Run | What to check |
|---|---|
| Full review | Verdict is **FIX-REQUIRED** with a count. A PASS is the failure |
| The discount conflict | 22% in the proposal against 15% in the agreed terms → **ESCALATE**, not a proposed fix |
| Arithmetic | Catches two tables labelled `Total` with different values, and a transition that completes before it starts |
| Waive a blocker as "the team" | Refused. A waiver has to name a person |

`Sample Output/` holds the verbatim script output on this fixture.

**The escalation is the finding worth watching.** The proposal says 22% discount; the agreed
terms say 15%; the RfP — the authority — does not mention discount at all. There is no
correct automatic answer, so the employee escalates rather than proposing a direction:

```
CONFLICT — 2 field(s) disagree across the set:
  "discount applied"
      22%   Proposal_Kestrel.docx · Discount applied: 22%
      15%   Agreed_terms.md · Discount applied: 15%
      → ESCALATE — the authority document does not state this field, so no document
        in the set outranks the others on it
```

A proposal committing to a discount that was never agreed is not a document defect, it is an
exposure, and it may need a conversation with the client rather than an edit.

**The arithmetic finding is the one both tables pass.** Every column in the proposal adds up
perfectly. The defect is that two tables are both labelled `Total` and carry different
values — 412,300.00 and 230,900.00 — which is a payment schedule that does not sum to the
contract value:

```
REVIEW  1 total label(s) carry different values in different tables. Decide whether they
are supposed to agree — a per-section subtotal legitimately differs; a payment schedule
that does not sum to the contract value does not:
  Proposal_Kestrel.docx  "Total": 412,300.00 (table 1), 230,900.00 (table 2)
```

**`templates/compliance-checklist.yaml` ships as examples only, and that is deliberate.**
The real checklist comes from the RfP's instructions-to-bidders section plus the bid team's
standing rules. An empty or example-only checklist means the mandatory-content pass **did not
run**, and it goes in the Unchecked bucket — not the clean pile. A PASS issued against the
file as shipped is a PASS against nothing.

## Four reductions from the role spec — all deliberate, all stated in the skill

1. **No CPQ / pricing bridge.** The spec recomputes every pricing table against an internal
   pricing API over `custom-mcp`. None exists in the tenant, so totals are checked for
   **internal coherence only**: does the stated total equal its column, does the payment
   schedule sum to the contract value. A price that is internally perfect and wrong against
   the real price book cannot be detected, and the skill says so rather than implying the
   check is complete.
2. **No CRM.** HubSpot and Salesforce are both set to yes in the architecture sheet and
   neither is connected. The deal-record cross-check is the highest-value check in the spec,
   so it is **asked for in Phase 0** rather than dropped.
3. **No task system and no Slack routing.** ClickUp tasks per blocker and bid-channel
   notifications are not wired. The fix list is delivered in chat and the bid owner
   distributes it.
4. **No compliance rules engine.** Mandatory-content and tender-rule conformance is checked
   against the RfP itself plus an optional checklist file, not a ruleset API.

Workflow 3 of the role spec — aggregating findings across proposals into a spreadsheet — is
not built in v0.1 either.

## Known limits in v0.1

- **`docx`, `md` and `txt` only.** PDF, PowerPoint, Excel and scanned documents cannot be
  read and are listed in Phase 1 as unread rather than quietly skipped.
- **A deadline never converts a blocker into a recommendation.** If there is no time, the
  verdict stands and somebody waives it by name. There is no pressure setting.
- **Every name, figure and date in this repository is synthetic.** Kestrel is not a client;
  the terms, discounts and totals are invented.

## Demo

A 2:50 narrated walkthrough is on NDI's YouTube channel. The video is not committed here —
the terminal output it shows comes from the scripts in this repository, run on the fixture in
`Sample Input/`.

## Where this comes from

This bundle is a **build output**, not a hand-authored skill. It is generated by the NDI
factory from three inputs — the `audit-and-propose` archetype, the `do-11` pack, and the
component column for DO-11 in the architecture sheet — via the `build-ai-employee` skill.

**So edit the pack, not the files here.** A change made directly to `SKILL.md` or
`review-config.yaml` in this repository is discarded by the next rebuild. The factory
currently lives on Google Drive under `00 Factory`; moving it into version control is the
open task that makes this repository reproducible rather than merely archived.

Three component overrides were needed at build time and are recorded in the build log:
`MS Excel`, `Google Docs` and `Word Document`. All three inject *"the deliverable is a
&lt;document format&gt;"*. DO-11's deliverable is the fix list, and one of the three —
*"fill the user's own .docx template rather than authoring one"* — describes exactly the
behaviour the role spec forbids.

Two sheet errors are recorded but deliberately **not** overridden upward: `Document Compare`
and `Knowledge Validation Agent` are both set to **no** for DO-11 — a comparison employee
with comparison switched off, and a reviewer that is not supposed to ask. The archetype does
both regardless, so the behaviour is present; the sheet is wrong.

`plugin.json` carries no `version` field, so the plugin is versioned by commit SHA — every
push updates installations that have auto-update enabled. Add a `version` field if you want
releases to be deliberate rather than continuous.
