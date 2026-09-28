---
name: tag-release
description: Cut a release tag for palmgrade-api, palmgrade-frontend, or autograde from a merged staging→main PR. Use when the user asks to tag a release, cut a version, or says "buatin tag untuk PR #N" / "tag release" / "rilis PR #N".
---

# Tag a palmgrade production release

Pushing a `vX.Y.Z` tag **is** the production deploy, there is no staging
environment in palmgrade. `staging` is a branch, nothing more. Treat every tag
push as "this goes live now".

Two independently versioned repos:

| Repo | What a tag does | Verify with |
|---|---|---|
| `delta-anugrah/palmgrade-api` | build + deploy to prod | `https://api.smagri.id/health` |
| `delta-anugrah/palmgrade-frontend` | build + deploy to prod | `https://app.smagri.id/api/health` |
| `delta-anugrah/autograde` | **build only**: pushes to GHCR, deploys nowhere | GHCR tags (below) |

All three trigger on `push: tags: v*.*.*` (`.github/workflows/deploy.yml`), but
vision's workflow has no SSH job: there is no cloud vision, it runs on the
factory PC. Its tag matters anyway, because it publishes `:latest`, the marker
`palmgrade.sh` pulls in the background on the factory PC. Confirm both tags
landed:

```bash
gh api /orgs/delta-anugrah/packages/container/palmgrade-vision/versions \
  --jq '.[0].metadata.container.tags | join(", ")'    # want: v1.5.0, latest
```

A missing `:latest` means the factory never picks the release up. That has
happened (2026-08-14): the commit adding the `latest` marker landed four hours
*after* the tag was pushed, so `v1.7.0` shipped without it.

## Never decide these alone

- **The version number.** Propose it, show the reasoning, wait for a yes.
- **The push.** Everything before `git push origin vX.Y.Z` is read-only and
  safe to do unprompted. The push itself needs an explicit go-ahead.

## Steps

### 1. Resolve the repo

A bare PR number is ambiguous, all three repos number from 1. Probe them:

```bash
for r in palmgrade-api palmgrade-frontend autograde; do
  echo "=== $r ==="
  gh pr view N --repo delta-anugrah/$r \
    --json number,title,state,baseRefName,headRefName,mergeCommit 2>/dev/null || echo "not found"
done
```

Exists in more than one → ask which. Never guess from the title.

### 2. Validate the PR

Hard requirements: any miss is a **stop**, not a warning:

- `state == "MERGED"` (an open PR has no merge commit to tag)
- `baseRefName == "main"`
- `headRefName == "staging"`

A feature-branch→`staging` PR is never a release. Tagging one ships whatever
else is sitting on `staging`.

### 3. Confirm the commit is on main

```bash
gh api repos/delta-anugrah/<repo>/pulls/N --jq .merge_commit_sha
gh api repos/delta-anugrah/<repo>/commits/main --jq .sha
```

Take the SHA from `gh api`, **never** from local `git log`. A stale local
checkout is exactly how `v1.3.0` got burned (2026-07-20): the tag landed on an
old commit, the run was cancelled, but the GHCR image had already been pushed,
so the immutable guard rejected every retry and the number was lost for good,
the release had to jump to `v1.3.1`.

The workflow re-checks ancestry itself (`git merge-base --is-ancestor`), but
catching it locally is free and saves burning a version number.

### 4. Propose the version

```bash
git ls-remote --tags --refs git@github.com:delta-anugrah/<repo>.git 'v*' \
  | awk -F/ '{print $NF}' | sort -V | tail -1
```

Read the PR body and file list, then propose:

- new feature / new endpoint / new UI surface → **minor**
- fix or docs only → **patch**
- breaking API contract → **major**

Show the current tag, the proposed tag, and one line of why. Wait for the
user's answer. If the number they pick already exists on the remote, refuse,
tags are immutable and the GHCR image blocks reuse anyway.

### 5. Migration gate (API only)

```bash
gh pr diff N --repo delta-anugrah/palmgrade-api --name-only | grep '^init-db/' || true
```

New SQL files apply **themselves**. `config/database/migrator.ts` runs
`init-db/*.sql` on every boot, before the port opens, from a copy baked into
the image (`Dockerfile`: `COPY init-db ./init-db`). No `scp`, no `psql`, no
droplet trip. The compose mount into Postgres is only for a genuinely empty
volume.

Baselining will not silently skip them: it fires only when the ledger is
empty (`applied.size === 0`), and prod's `schema_migrations` has been populated
since `v1.8.0`.

You do not need a database check to know they applied. A failing migration
aborts the boot on purpose, so the deploy health gate rolls back and `/health`
keeps echoing the old tag. `/health` echoing the new tag **is** the proof.

**What still needs your eyes** is the SQL's meaning, because nothing else will
catch it: not CI, not the health gate, not the tests:

- A migration that touches `users` rows can lock people out while succeeding
  perfectly. Before tagging, check who actually uses the rows you are about to
  rewrite (the operator runs this, you read the output):

  ```bash
  docker exec -i palmgrade_postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
  SELECT email, last_login FROM users WHERE email IN ('a@x.com','b@x.com') ORDER BY last_login DESC NULLS LAST;
  SQL
  ```

  This is not hypothetical. On 2026-08-19 `028_rename_seed_users.sql` would
  have renamed three accounts that were in active use, `superadmin@`,
  `office@`, `site@`, two of them logged in ten days earlier. Its `NOT EXISTS`
  guard looked protective but held nothing back: the destination emails did not
  exist in prod, so every rename would have fired. All 317 tests passed, because
  no test or source file referenced those emails. Only the `last_login` query
  found it. The file shipped cut down to the one account with a blank
  `last_login`.

  Note the invocation: it reads the container's own `$POSTGRES_USER` /
  `$POSTGRES_DB`, so nobody needs to know the password. Enumerate the emails
  explicitly: a `LIKE '%@gmail.com'` both misses seed accounts on other domains
  and sweeps in real users.

- An **edit to an already-applied file** is not a migration. The ledger keys on
  the filename, so the edit is ignored everywhere the file already ran, and
  takes effect only on a fresh volume, a new factory PC. That divergence is
  intended sometimes (`005`/`019` in `v1.9.0`), but say it out loud in the
  release notes, because the seeded accounts on the next factory install will
  not match the ones documented for the existing sites.

### 6. Order gate: API before frontend

When both repos have an unreleased `staging`→`main` merge, **API ships first**.
The frontend's `PermissionGuard` reads `GET /permissions/me`; against an older
API that endpoint 404s, the matrix stays `null`, and `null` means deny, every
`/dashboard/*` page bounces to `/unauthorized`, including the operator's own.

Before tagging the frontend, confirm the API is actually live:

```bash
curl -s https://api.smagri.id/health
```

It must already echo the new API version. Not "the tag was pushed", echoed.

### 7. Tag and push

Only after an explicit go-ahead:

```bash
cd /home/nexio/Desktop/Projects/sawit/<repo>
git switch main
git fetch origin main
git pull --ff-only origin main

git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

`--ff-only` is load-bearing, not a stylistic choice. It turns a failed or
diverged pull into a hard error instead of silently leaving local `main` on an
old commit: which is precisely how `v1.3.0` got tagged onto stale history.

Then cross-check before pushing, since the tag lands on `HEAD`:

```bash
git rev-parse HEAD                                          # must equal
gh api repos/delta-anugrah/<repo>/commits/main --jq .sha    # this
```

Mismatch → **stop**, do not push. Re-pull and re-check.

This cross-check is the only one that counts, do not substitute `git status`
for it. In `autograde`, local `main` tracks `origin/init`, so
`git status -sb` reports `## main...origin/init [ahead 155]` on a checkout that
is in fact exactly level with `origin/main`. Trust `rev-parse` against the API,
not the branch summary.

Pushes on this machine OOM with git's defaults; if the push dies with signal
137, retry as:

```bash
git -c pack.threads=1 -c pack.windowMemory=64m -c pack.compression=0 push origin vX.Y.Z
```

### 8. Publish the GitHub release

The tag deploys; the release is what a human reads six months later. Always
both.

```bash
gh release create vX.Y.Z \
  --target main \
  --title "vX.Y.Z" \
  --latest \
  --generate-notes \
  --notes "$(cat <<'EOF'
## Changes

- <what changed AND why it matters, one sentence, naming the concrete
  identifier — file, constant, endpoint, vendor id — not a vague area>

## Validation

- <command run> — <actual result, e.g. "76 tests, 0 failures">

## Related

- <cross-repo release or PR this stays in sync with, and why>
EOF
)"
```

`--generate-notes` appends GitHub's auto commit list **below** the hand-written
notes, so both survive. Write the notes from the PR diff and the test output
you actually saw: never from the PR title alone.

House style for `## Changes`, taken from prior releases: each bullet is a full
sentence carrying the reasoning, not a changelog fragment. "Both ship with
churn support: Revealera reports `track_churn: true` for Linear (id 1109)",
not "added churn support". Name the trap when there is one (a paraphrased
vendor name returns zero rows instead of erroring, so the bug looks like a dead
feature, not a failure).

`## Validation` lists commands and their real numbers. If a check was skipped,
say it was skipped.

### 9. Watch and verify

```bash
gh run watch --repo delta-anugrah/<repo> $(gh run list --repo delta-anugrah/<repo> \
  --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Then confirm the deployed version, which is the only evidence that counts:

```bash
curl -s https://api.smagri.id/health        # or app.smagri.id/api/health
```

Report the actual `version` string. If it still shows the old tag, the deploy
did not land: say so plainly, do not call it done.

### 10. If it fails

Rollback is **redeploy the previous tag**, never a schema drop. For the
role-permissions release specifically: dropping `role_permissions` makes the
fail-closed middleware 403 every request. Rolling back the image is safe;
rolling back the table is not.

## Guardrails

- Never `git push --force`, never `git tag -f`, never delete a remote tag.
- Never touch the droplet directly. Hand the operator the exact command and
  read the output they paste back.
- Never tag both repos in the same breath, API, verify live, then frontend.
