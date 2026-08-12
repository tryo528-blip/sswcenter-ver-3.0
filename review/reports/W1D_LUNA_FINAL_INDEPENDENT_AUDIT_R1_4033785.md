# W1D Luna Max/Fast final independent audit R1

## Decision boundary

- Product candidate: `403378524994a0566120810f41111cf27463586d`.
- Required branch: `codex/w1d-contract-transition`.
- Repair topology:
  `a64f6eda267274febb50578cbd317081e3771877` →
  `ee905fd2dc9859fa83090bb7fa316b9748cf06f8` →
  `403378524994a0566120810f41111cf27463586d`.
- The final commit changes only the metadata exact-set test and two evidence
  records. Product bytes at `4033785` equal the repaired product bytes at
  `ee905fd`.
- Main and independent-review worktrees began and ended clean with staged,
  unstaged, and untracked counts `0/0/0`.

## Separation of duties

| Stage | Task | Boundary | Result |
|---|---|---|---|
| Live execution | `019fb87b-b1de-7bd3-8200-838704f6feb7` | Luna Max/Fast execution agent | GREEN evidence collected |
| Live independent audit | `019fb885-a827-7e30-a81d-5f1a39244485` | Separate user-visible clean worktree, read-only | APPROVE |
| Non-live execution | `019fb891-a44f-7fe1-8335-e83324ae85f6` | Luna Max/Fast execution agent | PASS evidence collected |
| Final independent audit | `019fb89b-7997-7392-99d9-90b370aeeda9` | Separate user-visible clean worktree, read-only | APPROVE for Regina integration |

The final reviewer was not a subagent of the execution operator, did not edit
the candidate, and did not rerun the live wrapper.

## Product closure

The final independent audit closed both prior HIGH findings in exact candidate
bytes:

1. certification and grade transition ends are required finite dates; the
   invented 364-day fallback and unsafe nullable apply path are absent;
2. repeat transition locks complete non-invalidated sets but hashes, previews,
   and mutates only rows effective at `proposed_end`, leaving ended history
   byte-identical.

Direct regression coverage performs two successful transitions and verifies
predecessor byte equality, exact affected IDs, audit prefix/append behavior,
row-version `+1`, date ranges, and timestamps. Generated OpenAPI types,
required finite fields, affected-ledger IDs, duplicate-apply ownership,
stale-generation isolation, assertive error regions, and
`erp.recipient_contract` metadata membership were also confirmed.

Product findings: **NONE**.

Blocking evidence/process findings: **NONE**.

## Raw execution evidence

### Live

The raw operator record contains exactly one wrapper invocation with
process-local user `TEMP`/`TMP` and ports `55442/18092/14192`.

- harness: `1 passed / 19 deselected`;
- PG00: `1 passed / 19 deselected`;
- remaining PostgreSQL: `18 passed / 2 deselected`;
- Playwright: `9 passed`;
- every stage and parent exit: `0`;
- listener, process, temp-root, and artifact zero markers precede
  `W1D_POSTGRES_GREEN`;
- independent postflight remained clean and exact.

The historical `19` versus candidate `20` count difference is intentional:
the repair appended `test_w1d_pg_18_repeat_transition_preserves_ended_history`.
It is not a product failure.

### Non-live

- focused collection: `89` tests;
- backend: `69 passed / 20 skipped / 1 existing warning`;
- Ruff and format: exit `0`;
- mypy: `53` source files, exit `0`;
- Alembic heads/history/verbose and offline SQL: exit `0`;
- generated OpenAPI: up to date;
- frontend: `111` tests in `18` files;
- TypeScript no-emit/build mode, oxlint, and production build: exit `0`;
- production build: `153` modules;
- Playwright list: `66` tests in `10` files, workers `1`;
- generated artifacts, workspace processes, wrapper processes, and reserved
  listeners: absent at final postflight;
- final Git identity and clean counts: exact and zero.

## Luna pilot measurements

| Stage | Duration | TTFT | Input | Cached input | Output | Reasoning | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Live execution | 6m 21s | 4.984s | 571,511 | 510,464 | 23,765 | 12,486 | 595,276 |
| Live independent audit | 9m 49s | 6.491s | 2,418,484 | 2,291,712 | 24,929 | 9,913 | 2,443,413 |
| Non-live execution | 9m 19s | 9.563s | 3,528,469 | 3,402,240 | 28,010 | 13,363 | 3,556,479 |
| Final independent audit | 15m 15s | 12.283s | 6,390,994 | 6,119,680 | 34,415 | 12,018 | 6,425,409 |
| **Total** | **40m 45s** | — | **12,909,458** | **12,324,096** | **111,119** | **47,780** | **13,020,577** |

Cached input was 95.5% of input and 94.7% of total tokens. The pilot preserved
or improved quality: the live executor conservatively treated the intentional
count delta as blocking, and the separate reviewer resolved it from exact Git
causality without hiding the discrepancy.

The pilot does not yet prove a time win. The separate live audit and final
audit both inspected the same live raw record, and the final audit spent
15 minutes and 6.4M tokens re-reading broad evidence. Future slices should use
one executor plus one separate independent review, carry an approved live gate
forward by exact identity, and provide a bounded evidence index. Actual money
savings remain provisional until provider billing is reconciled; the user's
stated relative price alone is not treated as measured spend.

## Troubles and residual risk

- System temp access was unsuitable for the live wrapper; process-local user
  `TEMP`/`TMP` fixed the environment without persistent configuration changes.
- A no-match CIM listener query initially surfaced as an observer error; a
  query-all-and-filter probe confirmed zero reserved listeners.
- Non-live evidence collection corrected one truncated `rg` pipeline and one
  empty PowerShell range read with narrower bounded searches.
- The Desktop `wait_threads` and later `list_threads` handlers returned
  `No handler registered for tool`; the tasks themselves remained healthy and
  were read from their task records without duplicate dispatch.
- PowerShell 5.1 could not deserialize one very large embedded JSONL payload;
  the reviewer switched to targeted raw marker extraction.
- The final independent audit crossed a context compaction before sealing its
  decision. No scope was added after compaction.
- The user-visible task API did not expose an independently checkable Fast
  field. Luna Max was explicit; Fast was inherited from the app setting and is
  therefore not independently attested in the task metadata.
- Git diff checks emitted existing CRLF-to-LF normalization warnings for the
  README and canonical index. The visible diffs remained limited to the four
  intended version-reference lines; no whole-file normalization was accepted.
- The first staged `git diff --check` found three Markdown hard-break trailing
  spaces. They were removed without changing meaning before commit. The first
  correction patch had an invalid hunk boundary and changed no file; the
  corrected patch then applied normally.
- The first staged-path allowlist script exited without useful output while Git
  used quoted non-ASCII paths. Repeating it with `core.quotePath=false` proved
  the exact six-path allowlist and zero staged product paths.
- One existing Starlette/httpx deprecation warning remains nonblocking.

The live wrapper was not rerun by the independent reviewer because that room
was intentionally read-only. Its exact invocation, exits, cleanup ordering,
and postflight were verified from raw evidence.

## Regina integration

The exact candidate is eligible for W1D final integration. The evidence-only
closeout commit that adds this report and updates AI operations does not change
the reviewed W1D product bytes.

## Remote publication divergence

The first `git push -u origin codex/w1d-contract-transition` was rejected as a
non-fast-forward. No force push, merge, rebase, reset, or remote deletion was
performed.

Read-only recovery established:

- pre-amend local closeout: `7e8b8e7a47792dfcfdd5481ca5e611b101cb916a`;
- remote head: `7bcf902febbaf6133a5db4aff9f3da2b1c19f8ff`;
- merge base: `266beeaa2d150371ccd1a0f26f69249eca86ba16`;
- divergence: local-only `5` commits, remote-only `6` commits.

The explicit fetch populated `FETCH_HEAD` but did not create an
`origin/codex/w1d-contract-transition` tracking ref. The first probe therefore
produced expected unknown-revision errors; a corrected `FETCH_HEAD` plus
`git ls-remote` probe proved the identities above.

The remote-only lineage ends at 17:50 KST and its own
`review/evidence/w1d/WIP_HANDOFF_20260731.md` says real PostgreSQL migration
roundtrip and update-guard validation were not run and the implementation was
not GREEN. The reviewed local lineage starts later, ends in the exact candidate
audited by this report, and cannot be combined file-by-file with that alternative
implementation without invalidating the candidate review.

On 2026-08-01 KST the user explicitly authorized the recommended
history-preserving reconciliation. Commit
`1c27653cffb680d64a738c19764484b94f6b8506` was created with parents
`b068fe59b7c518f689964b2ca18dfe445aafae92` and
`7bcf902febbaf6133a5db4aff9f3da2b1c19f8ff` using Git's `ours` strategy.
The merge tree is byte-identical to `b068fe5`, product paths remain identical
to reviewed candidate `4033785`, and the worktree is clean.

The merge succeeded, but the first tree-identity verification command left
`^{tree}` unquoted and PowerShell misparsed it, so that observer script exited
`1` after the commit already existed. A corrected quoted-revision check proved
identical tree object `7978f1cddae12b587e78d2aeb8743012ab952669`, exact parents,
zero product-path differences, and clean status. No rollback was required.

The same-named branch may now be published by a normal fast-forward push; no
force push or remote rewrite is needed. W1E remains gated only on successful
remote SHA matching and a final clean-tree check.

The normal push advanced the remote branch to the reconciled local history.
The first local/upstream/remote equality probe then found that this checkout's
`remote.origin.fetch` contained only the prior W1C branch. The remote SHA already
matched and the tree was clean, but `@{u}` could not resolve. Fetching the W1D
tracking ref alone still did not satisfy Git because its mapping was absent from
the configured refspec. Regina added the exact W1D fetch mapping to local Git
configuration, fetched again, and proved local, upstream, and remote equality.
This changed no tracked file or remote content.

`LUNA_W1D_FINAL_INDEPENDENT_AUDIT_RESULT=APPROVE`

`REGINA_W1D_RESULT=PASS`
