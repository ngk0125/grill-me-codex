# Plan: Cisco Inventory Fulfillment & Optimization — Maple AI
_Locked via grill — by Claude + Nabeel Kahwash_

## Goal
Build an internal decision-support tool for TD SYNNEX sales and quoting teams that ingests Cisco CTO quote spreadsheets, maps CTO SKUs to Cisco-vendor-management-approved spare equivalents, queries the live ERP/WMS API for inventory availability, applies configurable percentage-based fulfillment rules, and presents a clear Stock / Hybrid / Drop-ship / Manual Review recommendation to the sales rep before order conversion. The MVP covers U.S. data only. No order is automatically converted — the tool advises, humans decide.

## Approach
1. **Phase 1 — Business Requirements (Jun 8–12):** Document the current quote-to-order workflow, identify all decision points, confirm data sources, and define user output needs (what a sales rep needs to see to make a decision).
2. **Phase 2 — Design & Logic Mapping (Jun 15–19):** Build mapping table v1 (all entries approved by Cisco vendor management, tracked with approver name + date + Cisco confirmation reference). Verify live ERP/WMS API access and confirm canonical ATS semantics with ERP/WMS owners: which fields represent true available-to-sell (excluding serial/lot constraints, open picks, damaged/hold stock, channel reservations, future receipts). Finalize admin-configurable threshold values. **Exit criteria: mapping table v1 complete AND API access verified AND ATS field definitions confirmed in writing. Backend dev does not start without all three.**
3. **Phase 3 — Backend Development (Jun 22–26):** Build ingestion layer (AI parser + human confirmation step for every parsed quote, low-confidence lines flagged and held; non-standard BOM detection rule forces Manual Review before inventory scoring). Build deconstruction & mapping engine (CTO-to-spare lookup against approved table). Build inventory interrogation layer (live ERP/WMS API call with timeout budget, retry/backoff, and circuit breaker; timestamp attached to every result; degraded recommendation state shown to user if API is unavailable rather than silent failure). Build rules engine (configurable thresholds: ≥100% stock → Stock; 50–99% → Hybrid; <50% → Drop-ship; any Strict Match line missing from inventory → Manual Review regardless of percentage). Build recommendation output with fulfillment options A/B/C and real-time percentage adjustment UI.
4. **Phase 4 — QA, UAT & Pilot (Jun 29–Jul 24):** Test matrix covering: parser accuracy (standard + edge-case spreadsheet formats), mapping conflict detection, rule boundary conditions, stale/degraded inventory API responses, concurrent quote submissions, and permission boundaries. Select Sales/Ops pilot, measure recommendation acceptance rate and manual touch reduction. Tagged order cohort tracking begins (followed vs. overridden vs. ignored).
5. **Phase 5 — Deployment (Jul 27–Aug 14):** RAMP submission, LLM approval, go-live. Background monitoring agent fires UI flag alerts to sales rep + manager when a drop-ship conversion is detected with available inventory, before ERP order cut-off. Logs only if cut-off window has passed.
6. **Phase 6 (Post-MVP) — Canada:** Treated as a fully separate workstream. Different SPA file formats, potentially different SKU naming conventions, dedicated mapping table, separate Cisco vendor management approval process. Not a configuration switch on the U.S. system.

## Key decisions & tradeoffs
- **Mapping table is a prerequisite, not an assumption.** It does not exist yet as a structured artifact — Phase 2 must build it from scratch with Cisco vendor management sign-off on every entry. This was the single biggest hidden risk in the original plan.
- **AI parser is not trusted alone.** Every AI-parsed quote gets human confirmation before entering the rules engine. Low-confidence lines are held. This adds friction but prevents hallucinated SKUs from generating wrong recommendations.
- **Live ERP/WMS API over cached feed.** Chosen for accuracy. Trade-off: latency and availability risk under high-velocity quoting windows. Mitigation: caching for the recommendation UI display, but the final order-conversion step always does a live reserve/lock call to prevent double-allocation.
- **Thresholds are admin-configurable, not hardcoded.** Business owns the percentage cutoffs. Strict Match flag is a hard override — forces Manual Review regardless of overall stock percentage.
- **MCP is MVP-scoped as read-only.** Agents can query recommendations, not trigger conversions. API-key auth per approved agent, all calls logged. Autonomous conversion is post-MVP.
- **Canada is not a config switch.** Different data structures, different SPA formats, different approval chain. Treated as a separate build in Phase 6.
- **Tool owns recommendation quality, not delivery outcomes.** Success is measured via tagged order cohorts (followed vs. overridden vs. ignored) compared against the 90% drop-ship baseline. Ops owns delivery and lead time metrics independently.

## Risks / open questions
- **Mapping table build time:** Cisco vendor management approval is a dependency outside the team's control. If approvals are slow, Phase 2 slips and Phase 3 is delayed.
- **ERP/WMS API SLA:** No confirmed SLA on the live API under peak quoting load. Needs a load/latency test in Phase 2 before backend is built against it. Degraded state behavior (circuit breaker, user-visible failure message) must be designed before Phase 3 build starts.
- **ATS field semantics:** ERP/WMS "available" quantity may include stock that is not truly available (serial/lot constraints, open picks, damaged/hold, channel reservations). Must confirm canonical ATS definition with ERP/WMS owners in Phase 2 — wrong semantics here produce confident-looking but wrong recommendations.
- **Strict Match flag ownership:** Who sets the Strict Match flag on a mapping — the team, Cisco vendor management, or engineering? Process needs to be defined in Phase 1.
- **Intervention window timing:** Background agent alert must fire before ERP cut-off. The exact cut-off time and how the agent knows it need to be confirmed with ERP/ops team.
- **Sales adoption:** 90% drop-ship habit is entrenched. The recommendation UI must show margin impact clearly enough to change behavior — adoption risk is real even with a technically correct tool.

## Out of scope
- Automated order conversion (tool advises only, humans convert)
- Customer-facing portal changes
- Complex / non-standard BOM handling
- Canada rollout (Phase 6, separate workstream)
- Full MCP autonomous quoting (read-only in MVP)
- Any LLM model pinning to specific codex/GPT variants on ChatGPT-account auth
