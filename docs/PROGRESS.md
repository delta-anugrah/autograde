# Progress log

Newest first. One entry per working session or batch. This is what `git log` cannot tell you:
how far something was validated, decisions and why, events outside the repo (factory PC,
Lampung), what is blocked. Every Claude session prepends its final report here (`CLAUDE.md`
§8). Entries older than 3 months move to `docs/runbooks/progress-archive-<year>.md`.

Entry format:

```
## YYYY-MM-DD · <area> · <title> (PR #n or tag)
Changed:        ...
Validated:      command → result
Not validated:  ...
Decisions:      ... (only when a decision was made)
Next:           ...
```

---

## 2026-10-01 · docs · PLC skill and the PLC team document brought up to v1.20.0 (PR #201)
Changed:        plc-mc-protocol: ERROR = camera lost or AI dead (pointers to rules.md rule 32 and
                plc-integration § Coil ERROR), a licence that stops grading turns M1009 off, all
                three lines hold M1009 and what one crashed line leaves behind, the session plus
                INTERNAL_SECRET path for Uji PLC and the piston. docs/plc-mc-handoff.md 1.8 + PDF.
                Stale lines fixed in spek-pc-pabrik (disk table halved: bbox + clean + thumb),
                mvs-camera (15 fps), model-swap-eval, compose-host-pabrik (Lampung status),
                konsol-autograde and panduan-autograde. Outside the repo: v1.20.0 installed on the
                Lampung PC on 2026-10-01 with the sawit #61 launcher (md5 7d3d7f24...); the
                pre-tag checks passed on 2026-09-30.
Validated:      doc guard tests (em dash, doc links, plc-map vs compose, skill mirror, rejected
                bunch commands, camera feature file) → 59 passed; md_to_pdf → 12 pages, page 7
                checked by eye; git merge-tree against origin/fix/logging-batch-3 → clean;
                rule-reviewer → 1 blocking + 9 warnings, all fixed. Lampung `autograde status`
                (pasted by the operator) → 4 containers up, /health v1.20.0, ai.keadaan=sehat.
Not validated:  the ERROR coil on a real panel (item 0 of the PLC skill); the full test suite
                (no code changed, CI runs it).
Decisions:      the skill points to rule 32 and plc-integration instead of copying the ERROR
                table (standard D1); the PLC team document keeps its own table because its
                readers are outside the repo.
Next:           when #200 lands, update rule 32, plc-integration § Coil ERROR, the handoff (1.9 +
                PDF) and the skill paragraph for "frame berhenti"; hand handoff 1.8 to the PLC team.

## 2026-09-30 · console · Pydantic bodies for the operator routes (PR #199)
Changed:        login, manual truck, scan, scan/keluar and manual weighing take models from
                schemas/console_schema.py (shape only; content rules and their codes stay in the
                domain). pasang_penangan_validasi: a body or query shape error on /api/console/ is
                400 input_tidak_sah (new code, KAMUS id and en plus field labels) instead of 422;
                the machine lane keeps 422. Standard B1 updated and its gap row closed.
Validated:      tests/unit + tests/e2e → 3429 passed, 45 skipped, 1 warning in 160.38s;
                tests/integration → 96 passed; ruff over the ci.yml scope → All checks passed.
                rule-reviewer: 1 blocking (this entry) + 9 warnings, all fixed.
Not validated:  a real browser (the only screen change is the text of an error the screen's own
                requests never trigger).
Decisions:      the four support-setting routes keep a dict (their domain parsers already check
                every field, some read "8" as 8); the two ingest routes keep it for the frozen line
                contract. Weighing figures stay text so "14820,5" from the keypad still passes.
Next:           next known gap in docs/coding-standard.md: schema version for console.db (B5, C3).

## 2026-09-30 · docs · Coding standard loaded into every session (PR #198)
Changed:        new docs/coding-standard.md: 45 one-line rules with ids (L logic, S style,
                B backend, F frontend, T tests, C installed factory PCs, D docs), "not used here"
                and 8 known gaps. CLAUDE.md imports it (@docs/coding-standard.md, 176 lines).
                REVIEW-CHECKLIST section E cites the ids; rule-reviewer reads the standard;
                docs/overview.md §1 table fixed (console without controller, SQLite in
                repositories, schemas/integrations/plc/core rows); skill konsol-autograde points
                at F1 to F10. tests/unit/test_coding_standard.py guards the import, the length,
                the ids and every code path the standard names. .agents/skills gained the missing
                symlinks for model-swap-eval, mvs-camera and spek-pc-pabrik (follow-up 3 of #196),
                guarded by tests/unit/test_skill_mirror.py.
Validated:      tests/unit → 3105 passed, 28 skipped, 1 warning in 82.57s. Guard + test_doc_links +
                test_dokumen_tanpa_em_dash → 51 passed (the 4 first guard tests failed before the
                docs existed); test_skill_mirror failed on the three missing links, then 3 passed.
                ruff over the ci.yml scope → All checks passed. rule-reviewer: 4
                blocking + 9 warnings, all fixed (B1, L4/F3 and F9 had described the code wrongly).
                A subagent started in the worktree had the standard in context: the import loads.
Not validated:  tests/e2e and tests/integration (CI runs them).
Decisions:      names: factory concepts may stay Indonesian in Python, columns and new API paths
                English; REST shape for new endpoints only, existing paths never renamed; no URL
                state on the kiosk; five view states (disconnected added); scrypt and pbkdf2 kept;
                known gaps get their own PRs, a PR is not blocked by a gap it did not add.
Next:           first known gap: Pydantic bodies for the eleven dict routes (B1).

## 2026-09-30 · docs · Fix references left stale by the CLAUDE.md tidy (PR #197)
Changed:        rule references in 2 skills, docs/overview.md, docs/backend-overview.md,
                docs/MANUAL.md and README.md now cite docs/rules.md (full text, sub-points,
                § Critical Rules) or docs/backend-overview.md (HTTP Surface); docs/rules.md rule 21
                and the INTERNAL_SECRET note name docs/backend-overview.md; docs-sync gained check 5
                for references into CLAUDE.md. Rule numbers unchanged. Code and test comments untouched.
Validated:      test_doc_links + test_dokumen_tanpa_em_dash: 44 passed with the local plan file under
                docs/superpowers/ moved aside (only that untracked file fails otherwise);
                test_manual_doc, test_perintah_janjang_ditolak, test_console_copy green. The docs-sync
                grep finds 22 lines on staging, 7 on the branch, all 7 citing sections that exist.
Not validated:  full CI (runs on the PR). docs/MANUAL.pdf not regenerated.
Next:           the ~15 code/test comments citing "CLAUDE.md § Tests" / "Critical Rule N" (item (1) below).

## 2026-09-30 · docs · Tidy the AI-facing docs (PR #196)
Changed:        CLAUDE.md 1392 → 172 lines, English, fixed section order, one-line index of rules 0-32
                plus 1b/1c. Old lines 14-1392 moved verbatim: rules/conventions/git/pointers to
                docs/rules.md, the make table to docs/commands.md, HTTP surface and contracts
                appended to docs/backend-overview.md, system role/stack/structure appended to
                docs/overview.md §12. New: .claude/settings.json (deny list + PreToolUse hook),
                scripts/hooks/guard.sh + guard.py + test_guard.py, subagents rule-reviewer,
                qa-runner, docs-sync, docs/REVIEW-CHECKLIST.md, this log. AGENTS.md symlink and
                the 7 skills unchanged.
Validated:      old-vs-new line diff: 0 lines of CLAUDE.md 14-1392 missing from docs/ (reviewer);
                rule index == docs/rules.md headlines (35 entries); 26-phrase keyword check all
                present; test_doc_links, test_dokumen_tanpa_em_dash, test_manual_doc,
                test_plc_docs_match_compose green; tests/unit 3122 passed, 1 skipped;
                scripts/hooks/test_guard.py 69/69 with the hook on Python 3.9.6 and 3.12.14
                (RED 36/36 against an always-allow hook first). Fresh-session recall test 4/4
                (plus 1 sawit question). Pre-PR run: rule-reviewer no blocking violations; ruff
                clean; tests/unit 3121 passed, 1 failed (test_doc_links, caused by the local
                session plan file excluded via .git/info/exclude, not in the PR); tests/e2e
                311 passed, 17 skipped; tests/integration 96 passed; test_guard 69/69.
Not validated:  full CI (runs on the PR).
Decisions:      rule numbering is frozen (cited by tests, docs, skills); new rules append 33, 34, ...
                in both files. AI-facing files in English; MANUAL.md and runbooks stay Indonesian.
                Hook copied from autoerp (separate .py, command-position matching, py3.9-safe).
Next:           follow-up PR, not this one:
                (1) ~15 code/test comments still cite "CLAUDE.md § Tests" or "§ Critical Rule 1"
                (e.g. src/palmgrade/workers/capture_save_worker.py:30).
                (2) CI does not run scripts/hooks/test_guard.py; the hook fails open on a crash.
                (3) .agents/skills has no symlink for mvs-camera, model-swap-eval, spek-pc-pabrik.
                (4) Rule 31: its 5xx wording may not match
                test_baris_racun_500_mundur_sendiri_tanpa_memutus_sambungan and
                GAGAL_BERUNTUN_PUTUS=3; read the test first.
                Also: moved `##` headings could be demoted to `###`. Run docs-sync monthly.
