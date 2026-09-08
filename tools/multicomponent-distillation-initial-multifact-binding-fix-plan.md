# Initial Multifact Binding Regression Fix

## Problem

On an initial message containing component identities, flows, units, pressure,
and temperature, Qwen may set `target_field="component_names"` while still
extracting all facts correctly. The current binder treats that target as an
exclusive scope even though no question is pending, discarding the flows and
other grounded facts and leaving the conversation stuck at feed quantity.

## Fix

1. Keep deterministic direct-answer binding first when a request is pending.
2. When no request is pending, do not use Qwen's singular `target_field` to
   discard other proposed facts. Pass every proposed fact to the existing
   literal grounding boundary.
3. Continue using field scoping for replies to an active pending request so a
   short answer cannot populate unrelated fields.
4. Let grounding reject derived or fabricated totals, compositions, units, or
   measurements that are not supported by the current message.
   In particular, numbers stated as flow rates must not ground a model-proposed
   composition unless composition is explicitly worded or is the active
   pending request.
5. Commit the valid logical groups atomically through the existing feed-state
   path.

## Tests

- A complete initial message using `component=value` syntax commits identities,
  flows, units, pressure, and temperature even when Qwen targets only
  `component_names`.
- An initial ordered list using "respectively" commits the named component
  flows instead of stopping at identity collection.
- Unsupported model-derived total flow and composition do not become
  authoritative user facts.
- A model proposal that copies explicitly stated flow values into composition
  cannot invalidate the otherwise valid quantity group.
- Existing pending short-answer isolation and grounding tests continue to
  pass.

## Completion criterion

The first message advances to the genuinely next missing input—or directly to
the boiling-point result when complete—without weakening pending-answer
isolation or the grounding boundary.
