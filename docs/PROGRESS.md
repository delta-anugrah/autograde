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

## 2026-09-30 · logging, health, CI · Batch 3 on fix/logging-batch-3 (PR not open yet, in progress)
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
Validated:      after the fix wave: tests/unit 3633 passed, 28 skipped; tests/integration 124
                passed; tests/e2e 331 passed, 17 skipped (torch venv); ruff on the ci.yml scope
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
