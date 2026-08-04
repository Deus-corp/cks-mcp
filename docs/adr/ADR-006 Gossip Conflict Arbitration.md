# ADR-006

# Gossip Conflict Arbitration: LLM-Assisted Merge Resolution

**Status:** Proposed

**Date:** 2026-08-04

**Category:** Architecture Decision Record

---

# Context

`arbitrate_inference_conflict` (ADR-001) provides three paths to resolve
an `InferenceConfidenceConflict`: interactive (caller picks `winner_id`),
unattended (`auto_resolve=True`), and bypass (`resolve_inference_conflict`
operation directly). Gossip conflicts (`GossipConflictDetected`, ADR-008)
have no equivalent: `merge_branch` reports structural conflicts as a list
of `object_id`s with `target_diff`/`source_diff`, and the caller must
hand-roll a `resolutions` dict without any LLM assistance. This asymmetry
forces the Critic Agent to dead-letter every structural gossip conflict
as unresolvable, even when an LLM could propose sensible resolutions.

# Decision

Add `resolve_gossip_conflict` as a new MCP tool, mirroring
`arbitrate_inference_conflict`'s three-path shape:

1. **Interactive:** returns `conflicts` (object_id + target_diff/source_diff)
   and a `policy` describing resolution criteria; caller picks per-object
   resolutions and calls again with a `resolutions` dict.
2. **Unattended** (`auto_resolve=True`): the tool calls an LLM via the
   same provider dispatch as `construct_knowledge`/`arbitrate_inference_conflict`,
   asks it to pick `branch_a`/`branch_b`/`custom` per conflicting object,
   and returns a ready-to-use `resolutions` dict for `merge_branch`.
3. **Bypass:** caller always retains the option to hand-craft resolutions
   and call `merge_branch` directly.

## Consequences

- Closes the asymmetry between gossip and inference conflict resolution.
- The Critic Agent can now auto-resolve structural gossip conflicts
  instead of dead-lettering them.
- LLM provider dependency: same `CKS_LLM_PROVIDER` env vars as all other
  LLM-facing tools; no new configuration surface.