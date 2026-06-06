# Plan Review Log: Cisco Inventory Fulfillment & Optimization — Maple AI
Act 1 (grill) complete — plan locked with Nabeel Kahwash. MAX_ROUNDS=5.

## Round 1 — Codex (gpt-5.5, read-only)
VERDICT: REVISE

Findings:
- [PLAN.md:26] API SLA listed as risk but no fallback behavior for ERP/WMS timeout, partial outage, degraded fields, or inconsistent timestamps. Fix: specify timeout budgets, retry/backoff, circuit breaker, degraded recommendation states, and user-facing failure messages.
- [PLAN.md:11] QA/UAT says "internal testing plan" but does not name test classes for parser accuracy, mapping conflicts, rule boundaries, stale inventory, concurrency, or permissions. Fix: add a test matrix covering unit, integration, contract, load, security, audit, and UAT acceptance cases.
- [PLAN.md:22] Success metrics compare recommendation behavior to a 90% drop-ship baseline but do not define measurement windows, confounders, or false-positive/false-negative recommendation quality. Fix: define baseline period, cohort selection, acceptance criteria, override reasons, and precision/recall targets.
- [PLAN.md:9] ERP/WMS fields omit critical inventory semantics like serial/lot constraints, reservations by channel, open picks, future receipts, damaged/hold stock, and warehouse transfer availability. Fix: confirm canonical ATS semantics and required exclusion/inclusion fields with ERP/WMS owners before rules design.
- [PLAN.md:31] "Complex / non-standard BOM handling" is out of scope, but the ingestion plan does not define how to detect those cases before making recommendations. Fix: add explicit non-standard BOM detection rules that force Manual Review before inventory scoring.
- [implicit] Role-based access controls not defined — who can see customer, margin, inventory, and override details.

### Claude's response — what changed, what was rejected, why

**Accepted:**
1. **ERP/WMS degraded state** — Added timeout budget, retry/backoff, circuit breaker, and user-visible degraded recommendation state to Phase 3 build requirements. Silent API failure producing a confident-wrong recommendation is a real risk.
2. **QA test matrix** — Replaced vague "internal testing plan" with explicit test classes: parser accuracy, mapping conflicts, rule boundary conditions, stale/degraded API responses, concurrent submissions, permission boundaries.
3. **ATS field semantics** — Added canonical ATS field confirmation (serial/lot, open picks, damaged/hold, channel reservations, future receipts) to Phase 2 exit criteria. Wrong ATS semantics = wrong recommendations at high confidence.
4. **Non-standard BOM detection gate** — Added explicit detection rule to ingestion layer: non-standard BOMs force Manual Review before inventory scoring, preventing out-of-scope cases from getting recommendations.

**Rejected:**
- **Role-based access controls** — Valid hardening but this is an internal MVP. RBAC is a post-MVP item; the tool is not customer-facing and operates within existing enterprise auth. Logging this as a post-MVP risk, not a plan blocker.
- **Measurement windows / precision-recall targets** — Premature for a pilot. Tagged cohort tracking (followed/overridden/ignored) vs. 90% baseline is sufficient for MVP validation. Formal precision/recall framework belongs in a post-pilot analytics plan.

## Round 2 — Codex (gpt-5.5, read-only, resumed thread)
Note: Codex read the pre-Round-1 PLAN.md (local clone not pulled). Some findings repeat Round 1; assessed on merit regardless.

VERDICT: REVISE

Findings:
- Parser edge cases remain: human confirmation does not define fail-closed handling for malformed files, non-U.S. inputs, duplicate lines, zero/negative quantities, unknown SKUs, or unsupported BOMs. Fix: add explicit parser validation rules and rejection states before rules execution.
- Prior observability gap remains: after cut-off, the plan "logs only" but does not require reason codes, inventory snapshot, missed-window classification, or alert outcome tracking. Fix: emit structured audit events for every detected mismatch, including cut-off status and inventory state.
- Prior QA gap remains: UAT does not explicitly cover stale cache, ERP outage, API latency, concurrent reps competing for the same inventory, or recommendation-to-order drift. Fix: add these as named Phase 4 acceptance tests.
- Prior metrics gap remains: acceptance rate and manual touch reduction do not measure bad recommendations, false positives, override reasons, or margin/inventory outcomes. Fix: track recommendation accuracy, override reason, financial impact, and avoidable drop-ship rate.

### Claude's response — what changed, what was rejected, why

**Accepted:**
1. **Parser fail-closed rules** — Added explicit rejection states for malformed files, non-U.S. inputs, duplicate lines, zero/negative quantities, unknown SKUs, and unsupported BOMs. Each rejected before rules execution with a user-visible reason. No silent pass-through.
2. **Structured audit events** — Replaced vague "logs only" with structured audit events on every mismatch: order ID, SKUs, inventory snapshot, cut-off status, alert outcome. Both fired and suppressed alerts produce a structured record.
3. **QA: concurrent inventory and drift** — Added concurrent rep competition (double-allocation), recommendation-to-order drift, and ERP outage/circuit-breaker behavior as named Phase 4 acceptance tests.

**Rejected:**
- **Metrics: precision/recall, override reason, financial impact** — Re-raised from Round 1 without new evidence. Holding position: tagged cohort tracking is sufficient for MVP pilot. Full metrics framework is post-pilot. Not a build blocker.
