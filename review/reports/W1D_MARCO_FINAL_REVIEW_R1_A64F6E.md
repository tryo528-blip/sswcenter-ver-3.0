# W1D Marco final exact-SHA review R1

## Review identity and boundary

- Candidate: `a64f6eda267274febb50578cbd317081e3771877`.
- Baseline: `266beeaa2d150371ccd1a0f26f69249eca86ba16`.
- AI-operations commit: `69715fdf4bc680a90685926ef56a7abb2a864162`.
- Review task: `019fb7dd-10b1-7471-8426-3fc6b13443cd`.
- Review worktree: `C:\Users\USER\.codex\worktrees\5bf1\2.1`.
- Mode: detached-HEAD, read-only, no agents, no live PostgreSQL rerun, and no
  repository mutation.

Marco observed exact HEAD and branch-ref identity at the requested candidate,
the direct topology `266beeaa -> 69715fdf -> a64f6eda`, and final
tracked/staged/untracked counts `0/0/0`. The five AI-operations paths and the
48 W1D paths were disjoint, with no candidate deletion, unrelated path,
credential hit, generated build residue, or missing W1D contract.

## Blocking product findings

### M1 - transition end-date contract contradicted canonical persistence

The reviewed transition schema and plan accepted nullable certification and
grade end dates (`schemas.py:134`, plan line 116), while W1C migration 0010
persists both columns as `NOT NULL` (migration lines 124 and 187). Apply then
invented independent 364-day ends (`service.py:883`).

That made the accepted open-ended shape observably unsafe: a grade beginning
after the invented certification end violated the grade-containment constraint
and was not mapped by the W1D integrity-error mapper (`service.py:110`), while
same-start input was silently changed from open-ended to finite. Marco
classified this as a HIGH product defect.

### M2 - repeat transition rewrote ended history

The reviewed repository selected certification and grade rows solely by
`invalidated_at_utc IS NULL` (`repository.py:48,63`). Apply then assigned the
new proposed end to every selected row (`service.py:753,852`). Therefore, after
one transition, a second transition selected both the already-ended historical
rows and the newly inserted rows, rewrote them together, and could violate the
period-exclusion constraints instead of preserving history. This contradicted
the canonical history sequence in the business contract (section around line
301) and was the second HIGH product defect.

## Confirmed accompanying gaps

- No live PostgreSQL case exercised open-ended certification/grade input or two
  successful transitions for one recipient. The 54-test non-live validation
  suite instead accepted the unsafe open-ended shape.
- `frontend/src/services/w1dApi.ts` manually repeated W1D request/response
  shapes and returned a generic apply record even though generated schemas were
  available.
- Transition controls did not identify all required fields, the impact panel
  omitted certification and grade IDs, and the component test clicked preview
  without filling the eventual required fields.
- Apply had no synchronous in-flight guard, so rapid duplicate activation
  could submit the same token twice. Async errors and stale state did not have
  an explicit live-region contract.
- The R12 report's claim that the panel used the generated API surface
  contradicted both the reviewed source and R10's earlier manual-type finding.
- Seven historical raw-byte seals matched after LF-to-CRLF reconstruction but
  not as raw bytes in the committed LF checkout. Marco classified that as
  evidence-provenance drift rather than semantic product drift.
- The retained R10 Markdown hard-break whitespace made the cumulative W1D
  commit range `git diff --check` exit `2`; this was evidence hygiene, not a
  product defect.

## Runtime/evidence boundary

Marco reconciled the supplied attempt-2 evidence as internally consistent:
wrapper parent exit `0`; harness `1`; PG00 `1`; PostgreSQL remainder `17`;
Playwright `9` with `workers=1`; cleanup predicates zero; and
`W1D_POSTGRES_GREEN` emitted after the gates. Marco did not rerun the wrapper.
That historical GREEN remained valid only for the finite, single-transition
scenarios actually exercised and did not cover M1 or M2.

Final observer checks found target listeners, matching runtime processes,
user-temp W1D roots, named frontend/test artifacts, and ignored untracked files
all zero. Protected `C:\WINDOWS\TEMP` enumeration was unavailable; the explicit
user temp root was checked instead.

## Operational troubles retained

Spark's supplied troubles were preserved: it initially changed from its
delegated worktree to the main checkout; several PowerShell branch, command,
pytest-output, and cleanup quoting attempts failed; the first supplement used
the wrong relative base; `Remove-Item` was policy-blocked; and an exact-path
artifact cleanup used `cmd /c rmdir`. Corrected checks ended on the exact clean
candidate, so these were process/evidence findings rather than separate product
defects.

Marco's own non-mutating observer troubles included expected no-match searches,
truncated broad output, PowerShell serialization expansion, guessed/stale paths
and variables, Windows wildcard and revision-expression mistakes, expected
detached-upstream exits, a self-matching process query, and protected system
temp enumeration. Each material observation was corrected by bounded exact-path
reads; no repository byte was changed.

## Decision

The exact candidate was not eligible for W1D closeout. Regina was required to
record and repair the findings, add direct regression coverage, create a new
candidate SHA, and obtain fresh exact-SHA regression and independent review.

MARCO_W1D_REVIEW_RESULT=REQUIRED_CHANGES
