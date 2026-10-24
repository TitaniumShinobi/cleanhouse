# CleanHouse Agent Contract

## Owner authority

The human owner is the only product-canon authority. Treat direct owner requests as implementation authorization for their stated scope. Do not require ritual phrases, repeated confirmation, or a restatement of an already clear request.

Active listening is operational:

1. Restate the requested outcome in one concise sentence.
2. Begin productive work in the same turn.
3. Report evidence after acting.

## Product preservation gate

Established CleanHouse surfaces are protected product assets. Before deleting, hiding, replacing, consolidating, renaming, or removing navigation to any protected surface:

1. Run `cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py`.
2. Identify the exact protected surface and affected routes.
3. Obtain an explicit owner instruction naming the destructive change.
4. Preserve a recoverable snapshot or commit.
5. Update the baseline only when the owner expressly changes canon.

Broad requests such as clean up, fix, simplify, integrate, redesign, modernize, reconcile, complete, or roll back do not authorize deleting product surfaces.

Protected surfaces currently include Overview, Applications, Network, Files, Zaelith, Identity, Reports, Allowed Threats, Help, Advanced/Settings, and Custom Scan.

Removing a failing surface is not a repair. Preserve it, expose the failure truthfully, and repair its implementation.

## Required task entry

Before implementation:

- Read `CLEANHOUSE.md`.
- Run `cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py`.
- Preserve unrelated dirty and untracked work.
- Check port `3333` before starting another runtime.
- Select the authoritative subordinate contract under `documents/` that owns the requested implementation. Code and that contract change together; reports and final summaries do not satisfy this gate.

`CLEANHOUSE.md` is owner canon and must not be modified without an explicit owner instruction naming that canon change. The subordinate contract must record the full resulting specification, including behavior, boundaries, commands, states, validation criteria, and known limitations as they are implemented.

If the baseline fails before the task, record the pre-existing failure and repair within scope. Do not redefine the baseline to make the failure disappear.

## Required task exit

- Re-run the protected-surface verifier.
- Run focused tests for the changed scope.
- Confirm the canonical runtime source matches the accepted source before claiming live success.
- Verify the implementation and its authoritative subordinate documentation are exact mirrors. Documentation drift blocks completion.
- Record incomplete or blocked work truthfully.
- Never claim completion because a surface was removed, hidden, or excluded from navigation.

## Owner-intent memory and interpretation lock

Do not reinterpret an established CleanHouse behavior while repairing its
placement, styling, reliability, data flow, or implementation. A request to
fix, move, align, match, restore, complete, or optimize a feature preserves the
feature's existing meaning unless the owner explicitly changes that meaning.

When the owner identifies another surface as the reference, treat the reference
surface as an invariant. Match the requested behavior to it; do not remove or
repurpose the reference behavior.

Before changing established UI behavior, write a private working checklist of
the literal owner requirements and verify each one after the change. If two
interpretations would produce materially different product behavior, stop and
ask the owner instead of choosing a new abstraction.

Keep these states distinct in every report:

- repository source changed;
- staged runtime changed;
- canonical live product changed and verified.

Never describe a behavior as restored, fixed, complete, or live until the
applicable state is explicitly identified and proven. Source-only proof is not
live-product proof.

### Permanent Network Graph/Chart meaning

The Network `Graph / Chart` control is intentional duplicate navigation:

- `Graph` selects **Trend**.
- `Chart` selects **Distribution**.
- The control remains visible on both Trend and Distribution.
- Distribution is the placement reference when aligning the Trend control.
- Trend remains the observed connection-count graph.
- Distribution remains the activity distribution visualization.
- Findings owns explanatory security text.
- `ctrl` owns selected-evidence context and controls.

Do not reinterpret Graph/Chart as two Trend render modes. Do not replace the
Trend graph with prose, findings, rationalization, or a table. Any change to
these meanings requires an explicit owner instruction naming the change.

