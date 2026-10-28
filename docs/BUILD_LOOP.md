# FinSight — Phase Build Loop

> Paste this alongside `PROGRESS_TRACKER.md` at the start of a session.
> Say "run the loop for Phase N" (or just "next phase") to trigger one
> pass. This is a protocol I follow, not an unattended background job —
> it still stops for your input at the points marked ⏸ below, per our
> standing convention that real trade-offs get surfaced to you, not
> silently decided.

---

## The 5 steps

### 1. Research
- Web-search anything in this phase involving: library/package choice,
  version currency, a tool that might have changed since training data
  (deprecated, discontinued, superseded, security-patched), or a
  technical claim I'd otherwise be recalling from memory instead of
  verifying (e.g. "does Postgres allow X inside a transaction").
- Do **not** search settled, timeless facts (e.g. "what is Numeric type
  for"). Search recency- or currency-dependent facts only — same rule as
  everywhere else in this project.
- If research surfaces a genuine trade-off (competing libraries, a
  deprecated dependency, an architecture fork in the road) → ⏸ **stop and
  present the options with real trade-offs**, same format as the
  MinIO→SeaweedFS decision. Don't proceed until you choose.
- If research just confirms "yes, this is still the right/current
  choice" → note it briefly and continue without stopping.

### 2. Implement
- Follow the established schema/architecture conventions already in the
  repo (layered `core/db/schemas/api/pipeline` separation, `Numeric` for
  money, `uuidv7()` PKs, provenance/audit fields, generic error messages
  on auth-adjacent endpoints, ownership checks before cross-resource
  access, etc.) — don't reinvent a pattern this project has already
  settled.
- Build in dependency order within the phase itself, same as the
  cross-phase ordering principle.
- Inline comments explain *non-obvious* decisions only (why, not what) —
  same density as the code already written this project.

### 3. Test
- **Real infrastructure only.** No mocks counted as "done." If the
  sandbox lacks a needed service (e.g. no Docker for a real Postgres 18
  or a real SeaweedFS container), download/run the actual binary or an
  apt-installable close substitute, test against it for real, and if any
  substitution was made (version downgrade, flag swap), explicitly
  revert it afterward and re-verify the restored file's syntax and that
  no test-only substitutions leaked into the shipped version.
- Exercise the real path end-to-end (actual HTTP requests / actual ORM
  calls / actual task execution), not just "it imports" or "it compiles."
- Write out explicit assertions for the phase's edge cases where
  feasible (auth timing, cross-user isolation, malformed input, etc.),
  not just the happy path.
- If a test result contradicts my assumption, say so and fix the
  assumption — don't retrofit the test to match what I expected (see
  Session 1's async-status test-methodology correction as the template
  for how to handle this).

### 4. Update Progress Tracker
Following the exact structure already established in
`PROGRESS_TRACKER.md`:
- Flip the relevant Phase Roadmap checkboxes (⬜ → ✅ or 🔶 for partial).
- Add any new rows to the **Decisions Log** (decision / chosen / rejected
  / why) for anything decided in step 1.
- Add any new items to **Known Gaps** for anything deliberately deferred
  or left unhardened in this phase.
- Append a new `### Session N — YYYY-MM-DD` block under Session Log with
  the same level of specificity as Session 1: what was built, what was
  tested and how, what was verified for real vs. assumed, what edge
  cases were identified, what's deliberately not done yet, and what's
  next.

### 5. Deliver
- Zip the full current repo state (not just the new files — the whole
  working tree, same as every delivery so far).
- Present the zip **and** the updated `PROGRESS_TRACKER.md` together via
  `present_files` in the same turn.
- In chat: list this phase's edge cases (same depth as prior phases),
  flag anything genuinely unverified or deferred, state the next phase.

---

## Definition of Done (a phase isn't ✅ until all of these are true)

- [ ] Every new library/tool choice was searched for currency, not assumed
- [ ] Every non-trivial trade-off was surfaced and decided by Dhruv, not auto-picked
- [ ] Code follows established repo conventions (layering, money-as-Numeric, UUID scheme, etc.)
- [ ] Tested against real infrastructure, end-to-end, not mocked
- [ ] Any sandbox-only test substitutions were reverted and the reverted file re-verified
- [ ] Edge cases identified and stated, not just the happy path
- [ ] `PROGRESS_TRACKER.md` updated: roadmap checkboxes, decisions log, known gaps, session log entry
- [ ] Full repo zip + updated tracker delivered together
- [ ] Next phase stated

---

<!-- This file doesn't need per-session edits — it's the constant
     procedure. PROGRESS_TRACKER.md is the one that accumulates state. -->
