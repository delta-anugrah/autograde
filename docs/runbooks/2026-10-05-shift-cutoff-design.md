# Shift cutoff for the working day: design (batch 5.11, not built)

Status: **design only, waiting for the user's answers**. No code changes until the open
questions in §6 are answered. Master plan: the runbook "Rencana Perbaikan AutoGrade" of
2026-09-28 in the `sawit` workspace, Batch 5 item 5.11.

## 1. The problem

The mill runs about 20 hours a day and across midnight. `work_date` flips at 00:00 in
`FACTORY_TZ` (`domain/working_day.py`, `work_date_for`). A night shift that runs 18:00 to 04:00
is split into two working days:

- "Hari ini" on the console drops to zero at midnight while the same shift keeps grading.
- The Rekap tab shows one shift's trucks on two dates.
- A truck graded 23:40 to 00:20 has its bunches on two dates; the per-truck recap counts the
  same visit twice, once per day, each with part of the bunches.

## 2. What the plan asks for

"Cutoff jam kerja bisa disetel (layar support) + ringkasan akhir shift; angka Hari ini
mengikuti shift."

## 3. What `work_date` feeds today

| Reader | Rule | What a cutoff changes |
|---|---|---|
| Ingest (`ConsoleService._ingest`) | rule 10: computed from the event's own timestamp, then stored | the date a bunch is stored under |
| Weighing (`record_weighing`) | from `entered_at` (weigh-in) | the date a ticket is stored under |
| Gate scans (`gate_service`, `gerbang_konsol`) | from the scan time | which day an arrival belongs to |
| "Hari ini" strip, Grading tab, Timbangan tab | `ConsoleService.today()` = the calendar date now | what "today" means on screen |
| Rekap / History (`riwayat_service`) | filters on stored `work_date` | which rows a day holds |
| CSV export | same | file content per day |
| Visit manifest to R2 (`domain/visit_manifest.py`) | carries `work_date` | the folder a manifest is filed under |
| **AutoERP** | **does not read `work_date`**. The visit carries `weighing.time_in`; AutoERP dates the ticket from the local date of `time_in` (`autoerp/docs/autograde-integration.md`, "`ticket_date`") | nothing on its side, which is exactly the risk in §5 |

Rule 17 (grading and weighing are two sources, placed side by side) and rule 18 (a visit is one
message rebuilt whole) are not touched by any option below: neither depends on the date column.

## 4. Options

### A. Shift the stored `work_date` by the cutoff (recommended if §6 Q1 says "yes")

`work_date_for(ts, tz, cutoff)` = the local date of `ts - cutoff`. With a 05:00 cutoff, a bunch
at 02:30 on 6 October belongs to the working day of 5 October.

- One pure function changes (`domain/working_day.py`), plus `today()`. Every reader in §3
  follows, because they all read the stored column.
- The cutoff is a console setting (support screen), stored like the other settings
  (`sync_state`, `setelan_` prefix so the Danger Zone keeps it). Default `00:00` = today's
  behaviour exactly, so nothing changes on a PC until support sets it.
- **Rows already stored keep their date** (rule 10: computed at ingest, never recomputed). A
  change of cutoff applies from the next bunch on. The day the cutoff is first set has one
  ragged boundary; that is stated on the support screen.
- No schema change, no new env var.

### B. Keep `work_date` on the calendar; add a separate `shift_date` column

- Two dates on every row; every reader must choose one. More code, more ways to disagree.
- Only worth it if some readers must stay on the calendar date (for example to match AutoERP).

### C. Screen only: "Hari ini" means "since the last cutoff", nothing stored changes

- Smallest change: the strip and the Grading tab ask for "since HH:MM" instead of "today".
- The Rekap tab and the CSV still split the shift at midnight, which is half of the problem.

## 5. Risk shared by A and B

A truck weighed in at 00:30 with a 05:00 cutoff lands on the console's previous working day,
while AutoERP dates the same ticket on the new calendar day (local date of `time_in`). The
console's daily recap and AutoERP's daily totals would then disagree for every truck weighed
between midnight and the cutoff. Nothing is lost or double counted, but two screens show two
different "days" for the same ticket, and the office reconciles by day.

Ways out, each a decision, not a code detail:

1. Accept it and say so on the recap ("hari kerja konsol, dipotong jam 05:00").
2. Ask AutoERP to date the ticket by a working date AutoGrade sends (contract change; AutoERP is
   Mas Samuel's design, `autoerp/docs/autograde-integration.md` is the contract).
3. Use option C, which never moves a stored date.

## 6. Open questions for the user

1. **AutoERP dating** (§5): is it acceptable that the console's working day and AutoERP's ticket
   date differ for trucks weighed between midnight and the cutoff? If not: option C, or a
   contract change in AutoERP first?
2. **Cutoff time at Lampung**: what time does the last shift really end? (The plan says about
   20 hours of operation; 05:00 is a guess.)
3. **One cutoff or several shifts?** "Ringkasan akhir shift" could mean one summary per working
   day, or one per shift (for example 06:00 to 14:00, 14:00 to 22:00). Several shifts per day is a
   second concept (shift id per bunch) and a bigger change.
4. **End-of-shift summary**: printed (like the grading slip, batch 5.9), shown on screen, sent somewhere
   (Discord, AutoERP), or all of these? Who reads it?
5. **Who may change the cutoff**: support only (proposed, like every setting that decides which
   day a number belongs to), or also an operator?
6. **Past rows**: confirm that changing the cutoff never recomputes rows already stored
   (rule 10). Recomputing would move tonnage between days that may already be reconciled.

## 7. If option A is chosen: the work, in order

1. `domain/working_day.py`: `work_date_for(ts, tz, cutoff=time(0, 0))` and a pure
   `hari_kerja_kini(now, tz, cutoff)`; unit tests for 23:59, 00:00, cutoff minus one second,
   cutoff, DST-free zones only.
2. A console setting `setelan_cutoff_shift` (`HH:MM`, default `00:00`), support route
   `GET/POST /api/console/dev/shift`, domain parser that refuses anything that is not `HH:MM`.
3. `ConsoleService.today()`, ingest, weighing and the gate services read the cutoff through one
   provider, so a change applies to the next row without a restart.
4. Support screen: the cutoff field with the sentence about past rows; the Rekap header names
   the cutoff when it is not midnight.
5. End-of-shift summary: per §6 Q3 and Q4.
6. Tests: unit, integration (route to SQLite), e2e (a night shift across midnight lands on one
   working day; a change of cutoff leaves old rows alone), browser (the setting and the Rekap
   header).
7. Docs: rule 10 in `docs/rules.md` and its `CLAUDE.md` line, `docs/MANUAL.md`.
