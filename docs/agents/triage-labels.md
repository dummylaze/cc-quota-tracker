# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Completion state (local convention)

The five roles above have no "done" state, and `/implement` does not mark tickets finished
(upstream: mattpocock/skills#508, #795). This repo adds one lifecycle value:

| Value      | Meaning                                                           | Set by / when                                                                                |
| ---------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `resolved` | Implemented, tests pass, committed; unblocks tickets that list it | The agent that ran `/implement`, after the full test suite passes and the work is committed |

Tick the acceptance criteria that were verified in the same edit.
Revisit this section if upstream settles on a different vocabulary (#795 proposes `resolved`, #508 proposes `done`).

### `resolved` is terminal

A local markdown tracker has no native "reopen", so `resolved` is one-way here:

- **Never move a `resolved` ticket back** to another status.
- **Never change its scope.** Its body (What to build, Blocked by, acceptance criteria) stays as it was when it was resolved. Only append to `## Comments`.
- **A change of scope is always a new ticket.** Each ticket's Comments point to the other by path. Don't list the old ticket in `Blocked by`: a resolved ticket blocks nothing, and the new ticket may live in another feature directory where a bare number would point at the wrong file.
- **A resolved spec gets no new tickets.** New scope after a spec is `resolved` goes into a new feature directory `.scratch/<new-feature-slug>/`.
- An acceptance criterion deferred to another ticket is ticked on the original ticket, with a Comment pointing to where it was verified, when that other ticket resolves.
