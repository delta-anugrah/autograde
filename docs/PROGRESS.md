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

## 2026-10-01 · console · A visit's grading is summed over every line that unloaded it (PR pending)
Changed:        A truck unloaded on three lines has three line assignments, but `weighings.assignment_id`
                holds one, so AutoERP, the detail page and the Log tab counted only the line released
                last. New table `visit_assignments` (one row per assignment, written when a line lets
                the truck go, back-filled at start-up; the old column is still written so an older
                image works after a rollback). `ConsoleStore.grading_counts_for_visit` and
                `bunches_for_visit` sum every linked assignment; `ErpQueue`, `VisitManifestWorker` and
                the Log tab context (`erp_link._konteks`) read them. Every assignment now finds its
                ticket, so a late bunch on the first released line re-queues the visit. Cross-midnight
                fix: `_queue_grading` finds the ticket by a 12 hour window on the console clock
                (`JENDELA_KUNJUNGAN_DETIK`, `latest_weighing_for_truck_since`), not by work date, so a
                truck weighed in at 23:30 and released at 00:30 is no longer linked to nothing. Demo
                seeder: `wipe()` also deletes the link rows of the visits it deleted, and the seed
                writes the line code. Rule 18 and `docs/overview.md` name the new link.
Validated:      RED first: `test_kunjungan_banyak_line_kirim.py` 7 failed before the change (total 2 of
                5, link rows without a line code, nothing linked across midnight); the new integration
                test failed against the previous commit with 4 of 9 bunches sent. After:
                `pytest tests/unit tests/e2e tests/integration` → 4313 passed, 45 skipped;
                `WAJIB_BROWSER=1 pytest tests/browser/ --browser chromium --browser firefox` →
                58 passed; `ruff check` on every touched file clean. New tests:
                `tests/unit/test_kunjungan_banyak_line_kirim.py` (send, detail page, Log line, window),
                `tests/unit/test_kunjungan_banyak_line.py` (an unlinked assignment never leaks into a
                visit's recap, window query), `tests/unit/test_demo_wipe.py` (link rows),
                `tests/integration/test_kunjungan_banyak_line_integrasi.py` (three lines, real
                `LineClient`, real queues and workers).
Not validated:  A real factory PC and a real AutoERP; the fake AutoERP is `tests/autoerp_palsu.py`.
Decisions:      The key AutoERP stores (`autograde_assignment_id`, unique) is the FIRST assignment
                linked, so it stays the same across resends. `line_code` in the message now names every
                line ("line-1, line-2"); AutoERP does not read it. The window query filters on
                `truck_id` and `received_at`, so it gets its own index (`idx_weighings_truck`, added
                at start-up like the others, nothing dropped) instead of scanning `weighings`.
Next:           Part 2 of the plan, automatic line assignment (stacked on this PR).

## 2026-10-01 · console, tests · Follow-ups from the browser suite (PR #206)
Changed:        Console: the Setelan line that did not receive a change is a KAMUS sentence
                (`setelanBelumSampai`, id + en), guarded by `test_kalimat_layar_hanya_dari_kamus`;
                the weigh-out hint names the row button "Timbang keluar" (it said "Keluar").
                Browser tests: exit scan (tare box, no ticket, two tickets refused), unregistered
                plate names the plate and leaves the form empty; the guard also fails a console
                /api/ 404 without a code and a 405; `jalankan_terbatas` stops a hung seeder or probe
                with its process group and keeps its output; fixtures typed. MANUAL 2.1 + PDF
                (hidden scan fields, plate picker, Timbang keluar), rule 20, skills konsol-autograde
                (how to write browser tests) and panduan-autograde (manual version).
Validated:      on 4b72c97: unit 3823 passed / 37 skipped; e2e 271 passed / 27 skipped;
                integration 124 passed / 1 skipped; `make test-browser` 72 passed (Chromium +
                Firefox); CI ruff scope + F821 clean; cek_skrip_konsol OK; test_manual_pdf 3 passed.
                New tests each made to fail once on purpose; the copy guard fails on the old HTML.
Not validated:  None beyond CI on the PR.
Decisions:      Holding the offline line-3 port was dropped: a bound, non-listening socket is
                refused on Linux but times out on macOS, unlike a stopped line.
Next:           None from #203's list.

## 2026-10-01 · ci · CI checks required by a repo ruleset (PR #205)
Changed:        Repo ruleset `ci-wajib-lolos` (id 24315701, active) on `refs/heads/staging` and
                `refs/heads/main` requires `lint-and-test`, `browser (chromium)` and
                `browser (firefox)`; branches need not be up to date. Before it, the org ruleset
                `protected-branch` required one approval and no check, so a red PR could merge.
                CLAUDE.md §3 Git names it. `tests/unit/test_ci_gerbang_rilis.py` pins the job name
                and matrix the ruleset matches on.
Validated:      `gh api repos/delta-anugrah/autograde/rulesets/24315701` → enforcement active,
                include staging + main, the three checks, strict false.
Not validated:  See this PR's merge state below once its checks run.
Next:           None.

## 2026-10-01 · console, tests · Browser tests with Playwright (PR #203)
Changed:        `tests/browser/`: Playwright drives the real console (copy of `src/palmgrade` in a
                temp folder, free ports, two fake lines and a dead one, 10 seeded days) through
                sign-in, line cards, manual truck, gate scan, weigh-in and weigh-out, assignment,
                Rekap + CSV, every tab in id and en and at 1024 px, roles, settings, accounts.
                A page guard fails the test call on a script error, a console 5xx or a request
                beyond 127.0.0.1. CI job `browser` (chromium, firefox), `requirements-browser.txt`,
                `make browser-siap` / `make test-browser`, qa-runner step 5, T3, CLAUDE.md §2.
                Console fix found by the suite: `kirimScan` reloads the truck list when the scanned
                plate is not an option yet, never toasts "scanned" over an empty plate field
                (`scanDaftarBelumMuat`), and names a deactivated truck (`scanTrukNonaktif`); rule 20.
                Second fix, found in CI: `.tabel` is `position:relative`, so the `.sr-only` header
                label no longer widens the Rekap page past a 1024 px screen (Linux Chromium 1079 px).
Validated:      on 149f3c0: unit 3817 passed / 37 skipped; e2e 271 passed / 27 skipped; integration
                124 passed / 1 skipped; CI ruff scope + F821 clean; cek_skrip_konsol OK. On cd54aed:
                `make test-browser` 58 passed in 135.97s (Chromium + Firefox). Each browser test
                was made to fail once on purpose. On c192970: unit 3818 passed / 37 skipped,
                `make test-browser` 58 passed; GitHub CI: lint-and-test pass, browser (chromium)
                33 passed, browser (firefox) 33 passed.
Not validated:  The ruleset (separate step).
Decisions:      The QR fields ship hidden, so scan tests un-hide `#scan-plat` and the weighing test
                uses the plate picker and the row's Keluar button (today's operator path). The
                ruleset that makes the three checks required is a separate step after merge, with
                the user's go-ahead (needs repo admin).
Next:           Merge by the user; then the ruleset `ci-wajib-lolos`. Open: `Belum sampai ke:` in
                Setelan is a literal, not KAMUS; no browser test for the weigh-out scan.

## 2026-10-01 · release · v1.21.0 released and installed in Lampung, PLC docs follow (PR #204)
Changed:        Release PR #202 (staging to main, merge commit 1adadec, tag v1.21.0) shipped #196,
                #197, the coding standard, the Codex skill mirror guard, #199, #201 and #200
                (Batch 3 logging plus the 4.1 and 4.3 gates). This PR: the "after #200, not yet
                installed in Lampung" wording becomes v1.21.0, installed 2026-10-01, in
                docs/plc-mc-handoff.md 1.9 (summary, table 4.2, field test paragraph and table,
                PDF reprinted) and skill plc-mc-protocol (address map note, Coil ERROR heading and
                summary, waiting list item 0).
Validated:      Deploy run 36821091663: ci / lint-and-test 3m44s first (the 4.1 gate holds), then
                the factory image 8m06s and the demo -cpu image 1m00s, all success; its log pushes
                v1.21.0, latest and v1.21.0-cpu. GitHub Release v1.21.0 = Latest. Lampung, by the
                user: `autograde use v1.21.0`, everything checked as expected. Check before the
                install (12:40 WIB): 3 lines healthy, cameras 20 fps, 201 GB free; the E-STOP
                ribbon was on (a PLC reading, not a blocker). This PR: unit 3824 passed /
                28 skipped; doc guard tests 62 passed; md_to_pdf → 12 pages, pages 3, 7 and 9
                checked by eye; rule-reviewer → 0 blocking, 4 warnings, all fixed.
Not validated:  The ERROR coil on a real panel, for AI dead and for frames stopped alike. Last Sync
                Cloud Photo in Lampung still read 25 Sep 14:00 before the install (normal if
                nothing was graded since; the user checks it).
Decisions:      The handoff stays at version 1.9: only the install status changed, and the PLC
                team has not received 1.9 yet.
Next:           Hand the 1.9 PDF to the PLC team once this is merged. Demo console to
                v1.21.0-cpu (the user runs it). Batch 4: 4.4, 4.2, 4.5, 4.6.

## 2026-10-01 · console, logging · Fixes from the manual browser test (PR #200)
Changed:        Unreachable-line sentence ends at "mati atau sedang restart." (no technician tail).
                Disk strip: as wide as the cards (`--pad`, also `#pita-alarm`), one line with an
                inline SVG warning icon, title, divider, time + lines + free GB only (diskSaran*
                keys removed, steps stay in MANUAL and the line log), slow pulse on the warning,
                × on the warning hides it for 24 h per browser (`pitaDiskDitutupPada`), critical
                cannot be dismissed. uvicorn's "timeout graceful shutdown exceeded" (every line
                restart while the console holds the video feed) is INFO, not an ERROR in the Log
                tab and Discord (`core/log_akses.TurunkanTenggangTutup`). MANUAL + rules + PDF.
                After #201 was merged: staging merged in, and the PLC skill + `plc-mc-handoff.md`
                1.9 (+ PDF) name frame berhenti as a third ERROR-coil state (the four-places rule).
Validated:      unit 3824 passed / 28 skipped; integration + e2e 459 passed / 17 skipped; CI ruff
                scope and F821 main.py clean; cek_skrip_konsol OK (detached worktree at 354ec4e).
                Browser by the user: Diagnostik sentence, Versi width, disk strip (width, pulse,
                one line, icon, ×, 24 h), Log tab WARNING line-1/line-3, recording stop 132 frames
                written = 132 readable, 0 dropped.
Not validated:  The uvicorn downgrade in a live restart (no feed was open on the restart after the
                fix); covered by a unit test that replays uvicorn 0.34's exact call.
Next:           Review, merge to staging by the user.

## 2026-10-01 · console · Plain-language screen text outside the Log tab (PR #200)
Changed:        User decision after the manual test of PR #200: no screen except the Log tab
                shows system error text. KAMUS id/en rewritten (no HTTP codes, env or file
                names, error codes; ribbons keep line, since-time, action); alasan() returns
                a generic sentence for an unknown code and its own sentence when the console
                does not answer, never e.message; the backend classifies an unreadable line
                (domain/line_tak_terbaca.py, sebab_kode) and a waiting AutoERP/R2 message
                (erp_outbox.error_kind, added in place), the screen words both; the raw
                reason goes to the Log tab (LineStatusWorker: one WARNING per episode after
                three failed polls, one on a cause change, one on recovery; uncoded operator
                refusals logged). Setelan errors go through alasan(); rekam refusal codes got
                their err_ keys; the Versi box lines up with the other Status sections; 60
                em dashes in log messages became commas (guarded). Docs: rules 21, F6, skill
                konsol-autograde, backend-overview, MANUAL ribbon lines.
Validated:      unit, integration, e2e, ruff CI scope, F821 on main.py, cek_skrip_konsol
                (counts in .superpowers/sdd/batch3-induk/teks-ramah-report.md).
                Fix wave after review: one episode rule for all three console readers of a
                line (first cause only, duration from the first failed poll, 120 s start-up
                grace), model reasons as codes, 4xx refusals worded as refused values, R2 and
                odd AutoERP failures classified precisely, unknown PLC alarm worded, no paths
                or commands in error sentences (guarded), MANUAL PDF regenerated.
Not validated:  real browser pass (the user's manual test).
Next:           user re-tests the Status tab and a line restart in the browser.

## 2026-09-30 · logging, health, CI · Batch 3 on fix/logging-batch-3 (PR #200)
Changed:        Integration branch from 849c30d: streams D, A, C merged, origin/staging (#196/#197)
                merged in, then stream B merged.
                D (batch 4.1, 4.3): deploy.yml calls ci.yml, release and demo images build only
                after CI passes on the tagged commit; CI parses every console.html script block;
                unit step uses -rs. Two flaky tests fixed: outbox sender stopped before its store
                closes in the shutdown test; Rekam Video Stop now writes the frames already queued
                (real bug: recordings lost their tail).
                A (batch 3.1, 3.3, 3.4, rule 33): one configure_logging for lines and console
                (console now reaches docker logs and uvicorn 500s reach tab Log), zone-marked
                lines with line code, LOG_LEVEL, httpx/httpcore capped at WARNING, successful
                polling silenced in the access log, tab Log merge key normalises volatile ids,
                PLC/camera/master data faults logged once at start and once at recovery.
                B (batch 3.2, 3.5, rule 34): each line keeps its WARNING/ERROR in a capped
                log_line.db written from a queue (detection never waits); the console pulls it
                every 10 s with a (generasi, seq) cursor into tab Log (line tag, first seen,
                traceback); ERRORs go to Discord as a digest queued on disk (off while
                DISCORD_WEBHOOK_URL is empty); a restarted line drains its log before os._exit,
                so the exit budget is 1 + 8 + 1 = 10 s (Danger Zone still waits 12 s).
                C (batch 3.6, 3.7, rule 35): connected camera that stops sending frames =
                FRAME_BERHENTI (ERROR coil, /health 503), finished test video = sumber_selesai,
                disk monitor on every line (15 GB / 5 GB, with or without R2, deletes nothing),
                honest Diagnostik card; console mirrors of line facts log at INFO only.
                Integration: CI step `ruff check --select F821 src/palmgrade/main.py`; rules 33,
                34, 35 full text plus the A/B/C/D edits to rules 21, 23, 25, 27, 29, 31, 32 and
                Git Workflow / Pointers moved into docs/rules.md, HTTP rows into
                docs/backend-overview.md, the Tooling line into docs/overview.md; CLAUDE.md index
                lines 33 to 35. Cross-stream tests: tests/e2e/test_transisi_line_sekali_di_tab_log_lane.py
                (one line transition = one line-tagged Log row) and
                tests/integration/test_discord_tanpa_alamat_di_log.py (webhook address never in
                stderr, tab Log or the Discord queue). The create_app route test no longer leaves
                the line log writer on root writing into the repo's state/. MANUAL 2.0 + PDF.
                Final fix wave (both final reviews + queued items): the last traceback line joins
                the merge key in tab Log, line log and digest (two different 500s stay two rows,
                Discord shows the exception class only); a line answering 5xx or a malformed log
                page gets one WARNING; a failing absorption no longer re-forwards the same ERROR
                counts to Discord; the start of a PLC outage and a coil write failure are ERROR
                (reach Discord); frame stop judged from any reconnect success since the last
                frame (no flapping, grace stamped once per episode, no false ERROR at the end of
                an outage, boot connect recorded); Discord 400 sets the message aside after three
                refusals, one WARNING per failure kind, unusable https URLs are url_salah; the
                line log writer backs off on a refusing disk; the state-not-mounted error reaches
                tab Log; Rekam Video stop runs in the threadpool; reconnect cycles are quiet;
                drifted /health and comment text fixed; the test suites no longer write into the
                checkout's state/ and artifacts/.
                Fix waves 2 to 5 (each re-reviewed): an undecodable webhook host is url_salah instead
                of stopping the console boot; only content refusals count before a Discord message
                is set aside; the merge key is the exception class plus our own last frame (never the
                message text), class shown only when the traceback was not cut, frame taken from the
                whole detail, one linear pass, truncated details still keyed. origin/staging #198
                (coding standard) and #199 (Pydantic bodies) merged in; nine batch-touched files
                joined the ruff list (standard S5).
Validated:      after the #199 merge: tests/unit 3677 passed, 28 skipped; tests/integration 125
                passed; tests/e2e 331 passed, 17 skipped (torch venv). After fix wave 1: tests/unit
                3633 passed, 28 skipped; tests/integration 124 passed; tests/e2e 331 passed, 17 skipped; ruff on the ci.yml scope
                and the F821 step clean; tests/cek_skrip_konsol.py OK; scripts/hooks/test_guard.py
                69/69 (venv and /usr/bin/python3); state/ and artifacts/ empty after all three
                suites. Earlier: the two cross-stream tests turn red when the console mirror goes
                back to WARNING or the httpx cap is removed (mutations reverted). Every line the
                branches added to the old CLAUDE.md (A/C/D 109, B 48) found verbatim in the new
                layout.
Not validated:  full CI (runs on the PR); nothing on the Lampung PC yet; Discord against the real
                webhook.
Decisions:      rule numbers A = 33, B = 34, C = 35; the line is the single WARNING/ERROR source
                for facts it owns, console mirrors are INFO. Fix wave: PLC outage start is ERROR
                (Discord), recovery WARNING; one full disk stays one row per line (rule 35).
Next:           PR to staging (PR body: reusable ci.yml call only provable on the first tag).
                Lampung: optional DISCORD_WEBHOOK_URL in the host compose console block and .env;
                tell the PLC team the ERROR coil also rises for a camera that stops sending
                frames.

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
