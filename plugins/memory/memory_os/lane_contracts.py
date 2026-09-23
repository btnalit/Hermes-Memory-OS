"""Lane / cognitive-loop-step IO contract table -- the W1-B freeze gate.

Background (verified in production 2026-09-22/23, see the stabilization
checklist section DJ "另立项"): four real lifecycle failures went unnoticed
for months because nothing checked them -- ``memory_projection.
compact_memory_projection_records`` was implemented but never wired to any
lane, the monitor still required retired ``wandering_mind_*`` sources,
sannai's ``full_monitor_refresh`` produced no artifact for six weeks, and
``session_fact_extraction`` reads ``sessions/session_*.json``, a file Hermes
stopped writing months ago. An advisor ruled that a prose ``contract`` field
on every table would drift silently; this module is the alternative: a small
declarative table plus a census test, not prose.

Every entry in :data:`LANE_CONTRACTS` answers three questions for one cron
lane (keyed by :attr:`cron_registry.MemoryOSCronLaneDef.key`) or one
cognitive-loop step (keyed by the step name in
``CognitiveLoopRunner._step_functions``):

``reads``
    Input sources, named through an existing path accessor or module
    reference where one exists (``event_stats.event_stats_path``,
    ``roots.crystallized_root``) rather than a re-typed path literal --
    CLAUDE.md's "path literal repeated at each call site" class of bug is
    exactly what naming the accessor instead of the path avoids.

``produces``
    Output artifacts, named the same way.

``consumers``
    Dotted module paths that read this lane's/step's output for further
    processing, downstream of the lane itself. When nothing consumes the
    output as an *input* to more processing -- the lane exists to inform an
    owner, a monitor, or only itself -- ``disposition`` names why instead of
    a consumer. At least one of ``consumers``/``disposition`` must be set;
    :class:`LaneContract` enforces this at construction time so the table
    cannot silently regress to neither.

``disposition``
    One of the closed set in :data:`DISPOSITIONS` when there is no forward
    consumer:

    - ``report_only`` -- output is for owner/operator reading, not further
      automated processing (e.g. an owner digest render).
    - ``watchdog`` -- the lane's job is to alert on its own failure; success
      is silence. ``l3_probe_verification`` is the owner-ruled example: a
      6-hourly self-test that only speaks when something is wrong.
    - ``monitor_only`` -- output exists to be read by the monitor's health
      classification and nothing else.

``monitor_codes``
    Monitor status codes/fields this lane's completion or output feeds.
    Every cron lane rides the generic ExecutionGate helper-completion
    classifier (:data:`GENERIC_CRON_LANE_MONITOR_CODES`) whether or not it
    also has a dedicated code; cognitive-loop steps do not ride that cron
    classifier and list only what actually reads them, confirmed by grep
    against ``scripts/memory_os_3_200_monitor.py``.

Any field this module's author could not confirm by reading the producer or
grepping the monitor is the literal string :data:`UNVERIFIED` inside the
tuple -- never a guessed path or a guessed consumer. A guessed value that
happens to be wrong is worse than an honest gap: it gates on vocabulary that
does not exist (see CLAUDE.md's "A gate whose vocabulary drifts from its
producer's checks nothing, silently").

The freeze gate itself is
``tests/plugins/memory/test_memory_os_lane_contracts.py``: it enumerates
every lane key in ``cron_registry.MEMORY_OS_CRON_LANES`` and every step name
``CognitiveLoopRunner`` can produce (including the three legacy-right-brain
conditional steps), and fails if any real lane/step lacks an entry here, if
any entry here names a lane/step that does not exist, or if a declared
consumer module does not import. A new lane or loop step cannot land without
an entry -- that is the freeze.
"""

from __future__ import annotations

from dataclasses import dataclass


CRON_LANE = "cron_lane"
COGNITIVE_LOOP_STEP = "cognitive_loop_step"
KINDS = frozenset({CRON_LANE, COGNITIVE_LOOP_STEP})

DISPOSITIONS = frozenset({"report_only", "watchdog", "monitor_only"})

# Closed-vocabulary marker for a field the author could not confirm. Never a
# guessed path/module -- see the module docstring's "honest gap" note.
UNVERIFIED = "unverified"

# Every cron lane completes (or fails to) through the same ExecutionGate
# helper-completion classifier in scripts/memory_os_3_200_monitor.py
# (missing / stale / error / boundary_true / boundary_unobserved), confirmed
# by reading _classify_execution_gate_cron_helpers's warn/fail append sites.
# Lane-specific codes are listed in addition to this baseline, not instead
# of it.
GENERIC_CRON_LANE_MONITOR_CODES: tuple[str, ...] = (
    "execution_gate_memory_os_cron_helper_completion_missing",
    "execution_gate_memory_os_cron_helper_completion_stale",
    "execution_gate_memory_os_cron_helper_completion_error",
    "execution_gate_memory_os_cron_helper_boundary_true",
    "execution_gate_memory_os_cron_helper_boundary_unobserved",
)


@dataclass(frozen=True)
class LaneContract:
    """One lane's/step's IO contract. See the module docstring for fields."""

    kind: str
    reads: tuple[str, ...]
    produces: tuple[str, ...]
    consumers: tuple[str, ...] = ()
    disposition: str = ""
    monitor_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"lane_contracts: unknown kind {self.kind!r}, want one of {sorted(KINDS)}")
        if not self.reads:
            raise ValueError("lane_contracts: reads must be non-empty (use (UNVERIFIED,) if unknown)")
        if not self.produces:
            raise ValueError("lane_contracts: produces must be non-empty (use (UNVERIFIED,) if unknown)")
        if self.disposition and self.disposition not in DISPOSITIONS:
            raise ValueError(f"lane_contracts: unknown disposition {self.disposition!r}")
        if not self.consumers and self.disposition not in DISPOSITIONS:
            raise ValueError(
                "lane_contracts: entry needs consumers or a disposition in "
                f"{sorted(DISPOSITIONS)}; got consumers={self.consumers!r} disposition={self.disposition!r}"
            )


# ── Cron lanes (plugins/memory/memory_os/cron_registry.py::MEMORY_OS_CRON_LANES) ──
# Grouped in the same order as the registry's own G1-G4 + single-member
# groups, so the two files can be read side by side.
_CRON_LANE_CONTRACTS: dict[str, LaneContract] = {
    # G1 -- derived views, rebuildable projections
    "event_stats_refresh": LaneContract(
        kind=CRON_LANE,
        reads=("store.read_events() (events/*.jsonl canonical event ledger)",),
        produces=("event_stats.event_stats_path (event_stats.json cache)",),
        consumers=(
            "plugins.memory.memory_os.cli",
            "plugins.memory.memory_os.prefetch",
        ),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "index_sync": LaneContract(
        kind=CRON_LANE,
        reads=("roots.crystallized_root", "roots.working_root", "roots.events_root"),
        produces=("roots.index_path (SQLite FTS5 index, non-authoritative cache)",),
        consumers=("plugins.memory.memory_os.prefetch",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "state_overlay_refresh": LaneContract(
        kind=CRON_LANE,
        reads=(
            "roots.last_session_anchor_path",
            "task_anchor (active task anchor)",
            "event_stats.event_stats_path",
            "crystallized preferences",
        ),
        produces=("system/state_overlay/current.json", "system/state_overlay/current.md"),
        consumers=("plugins.memory.memory_os.prefetch",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "entity_index_refresh": LaneContract(
        kind=CRON_LANE,
        reads=("roots.crystallized_root",),
        produces=("entity_index SQLite table (roots.index_path)",),
        consumers=("plugins.memory.memory_os.prefetch",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    # G2 -- governance queues
    "proposal_followups_opsgate": LaneContract(
        kind=CRON_LANE,
        reads=("plugins.modules.governance.proposal_queue (proposal_queue_only items)",),
        produces=("plugins.modules.governance.ops_gate report-only follow-up records",),
        consumers=("plugins.memory.memory_os.owner_actions",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "clearance_cycle": LaneContract(
        kind=CRON_LANE,
        reads=("candidate queue", "permanent crystallized corpus"),
        produces=("clearance verdicts (receipt invalidation, provisional enqueue)",),
        consumers=("plugins.memory.memory_os.crystallized",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    # G3 -- judgement + probe lanes
    "hindsight_health_probe": LaneContract(
        kind=CRON_LANE,
        reads=("Hindsight substrate config + endpoint reachability",),
        produces=("Hindsight health status (disabled/unconfigured/timeout/unhealthy/healthy)",),
        disposition="monitor_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "fact_judge": LaneContract(
        kind=CRON_LANE,
        reads=("candidate queue (inner_drive_candidate items)",),
        produces=("fact_judge verdict sidecar JSONL (durable_fact judgements)",),
        consumers=("plugins.memory.memory_os.crystallized",),
        # DW: monitor part 2 reads the ExecutionGate completion ledger's
        # result_summary for this lane_id (judge_backend / fallback / L1
        # transport diagnostics) -- see lane_backend_transport_summary().
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES + (
            "llm_lane_consecutive_failure_streak",
            "fact_judge_backend_state",
            "fact_judge_backend_no_sample",
            "fact_judge_backend_fallback_all",
        ),
    ),
    "candidate_aggregation": LaneContract(
        kind=CRON_LANE,
        reads=("candidate queue",),
        produces=("crystallized/candidate_triage.jsonl (cluster/promote/demote/fleeting actions)",),
        consumers=("plugins.memory.memory_os.crystallized",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "l3_probe_verification": LaneContract(
        kind=CRON_LANE,
        reads=("live governance write/read/revoke path (self-exercised, not external state)",),
        produces=("watchdog alert on failure only; silent (exit 0, empty stdout) on success",),
        disposition="watchdog",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "v3_wandering": LaneContract(
        kind=CRON_LANE,
        reads=(UNVERIFIED,),
        produces=("system/v3_wandering_runs.jsonl",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "session_fact_extraction": LaneContract(
        kind=CRON_LANE,
        reads=(
            "roots.state_db_path (Hermes state.db: sessions + messages tables, read-only) -- "
            "replaces the dead <hermes_home>/sessions/session_*.json input (SFE, 2026-09-23); "
            "sessions are filtered through principal.resolve_principal before extraction",
        ),
        produces=("candidate queue entries (unapproved candidates)",),
        consumers=("plugins.memory.memory_os.crystallized",),
        # DW: monitor part 2 reads system-modules/session_fact_extraction/
        # runs.jsonl's latest record for input_source / sessions_skipped_by_
        # principal / group_sessions_* / L1 transport diagnostics -- see
        # lane_backend_transport_summary().
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES + (
            "lane_input_stale",
            "llm_lane_consecutive_failure_streak",
            "session_fact_extraction_backend_state",
            "session_fact_extraction_backend_no_sample",
        ),
    ),
    # G4 -- day-boundary + maintenance
    "exposure_rollup": LaneContract(
        kind=CRON_LANE,
        reads=("system/memory_sources.jsonl (attribution ledger, cursor-tracked)",),
        produces=("system/exposure_rollup.jsonl", "system/exposure_rollup_snapshot.json"),
        disposition="monitor_only",
        monitor_codes=("exposure_rollup_lag_hours", "exposure_rollup_records_total"),
    ),
    "v3_seed_evidence": LaneContract(
        kind=CRON_LANE,
        reads=(UNVERIFIED,),
        produces=("v3_seed_evidence.v3_seed_edges_daily_path", "per-natural_date daily seed-evidence snapshot"),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES + ("append_only_ledger_oversized",),
    ),
    "v3_journal_sweep": LaneContract(
        kind=CRON_LANE,
        reads=(UNVERIFIED,),
        produces=("private V3 journal, TTL-swept",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "working_cleanup": LaneContract(
        kind=CRON_LANE,
        reads=("plugins.memory.memory_os.working (working memory documents)",),
        produces=("system/lane_last_run/working_cleanup.json (removal count + reason)",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "state_source_mirror": LaneContract(
        kind=CRON_LANE,
        reads=("config-declared external state roots (allowlisted patterns)",),
        produces=("summary-only Memory-OS events (hash/size/mtime metadata, never content)",),
        consumers=("plugins.memory.memory_os.prefetch",),
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "hindsight_advisory_digest": LaneContract(
        kind=CRON_LANE,
        reads=("Hindsight reflect() output",),
        produces=("advisory-only owner finding (advisory_only=True, non-actionable)",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "memory_projection_compaction": LaneContract(
        kind=CRON_LANE,
        reads=("plugins.memory.memory_os.memory_projection.memory_projection_records_path (system/memory_projections.jsonl)",),
        produces=(
            "compacted system/memory_projections.jsonl",
            "plugins.memory.memory_os.memory_projection.memory_projection_compactions_path (per-run closed-outcome report)",
        ),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES + (
            "memory_projection_retention_compaction_missing",
            "memory_projection_retention_compaction_failed",
            "memory_projection_retention_compaction_stale",
        ),
    ),
    # Single-member groups
    "owner_review_digest": LaneContract(
        kind=CRON_LANE,
        reads=("proposal queue", "candidate queue", "owner review surfaces"),
        produces=("owner-facing digest text (stdout; empty means Hermes cron stays silent)",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "memory_sources_feedback_request": LaneContract(
        kind=CRON_LANE,
        reads=("system/memory_sources.jsonl",),
        produces=("owner-facing feedback prompt text (stdout)",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "expression_feedback_request": LaneContract(
        kind=CRON_LANE,
        reads=("right-brain expression outcomes",),
        produces=("owner-facing feedback prompt text (stdout)",),
        disposition="report_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "full_monitor_refresh": LaneContract(
        kind=CRON_LANE,
        reads=("the full production monitor snapshot (scripts.memory_os_3_200_monitor)",),
        produces=("canonical full-monitor artifact, atomically published",),
        disposition="watchdog",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
    "module_cadence_report": LaneContract(
        kind=CRON_LANE,
        reads=("per-module cadence/heartbeat evidence across registered modules",),
        produces=("system-modules/module_cadence/reports.jsonl",),
        disposition="monitor_only",
        monitor_codes=GENERIC_CRON_LANE_MONITOR_CODES,
    ),
}


# ── Cognitive-loop steps (plugins/memory/memory_os/cognitive_loop.py::CognitiveLoopRunner._step_functions) ──
# Listed in the same order _step_functions returns them. wandering_mind /
# grounded_expression_judge / spontaneous_expression only run when the
# legacy right-brain path is enabled and not retired
# (CognitiveLoopRunner._legacy_right_brain_step_names) -- they still need an
# entry because the census enumerates the full closed vocabulary, not just
# what runs on a given profile today.
_COGNITIVE_LOOP_STEP_CONTRACTS: dict[str, LaneContract] = {
    "heartbeat_pre": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("event queue",),
        produces=("MemoryOSRuntime.heartbeat() result (candidate generation, decay, index sync)",),
        consumers=("plugins.memory.memory_os.runtime",),
    ),
    "working_decay": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("plugins.memory.memory_os.working (all ALLOWED_WORKING_KINDS documents)",),
        produces=("decayed/pruned working-memory documents",),
        consumers=("plugins.memory.memory_os.working",),
    ),
    "household_digest": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store.read_events()",),
        produces=("household digest artifact",),
        consumers=("plugins.modules.context.household_digest",),
    ),
    "digest_consolidation": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store events", "plugins.modules.governance.proposal_queue"),
        produces=("daily + weekly digest consolidation artifacts",),
        consumers=("plugins.modules.context.digest_consolidation",),
    ),
    "wandering_mind": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(UNVERIFIED,),
        produces=("would-send expression draft (legacy right-brain, conditional step)",),
        consumers=(
            "plugins.modules.expression.grounded_expression_judge",
            "plugins.memory.memory_os.cognitive_loop",
        ),
    ),
    "ops_gate": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("proposed_actions=[] (this step call site passes none)",),
        produces=("plugins.modules.governance.ops_gate report-only records",),
        disposition="report_only",
    ),
    "evidence_scoring": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store", "plugins.modules.governance.proposal_queue"),
        produces=("scored evidence, shared via context['evidence_scoring_instance']",),
        consumers=(
            "plugins.modules.governance.confidence_router",
            "plugins.modules.evidence.confabulation",
            "plugins.modules.governance.self_evolution",
        ),
    ),
    "confidence_router": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['evidence_scoring_instance']",),
        produces=("routed confidence bands, shared via context['confidence_router_result']",),
        consumers=(
            "plugins.modules.governance.candidate_review",
            "plugins.modules.governance.cascade_routing_policy",
        ),
    ),
    "candidate_review": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("plugins.modules.governance.confidence_router routes",),
        produces=("review decisions, shared via context['candidate_review_result']",),
        consumers=(
            "plugins.modules.governance.judge_calibration",
            "plugins.modules.governance.shadow_recall",
            "plugins.modules.governance.provisional",
        ),
    ),
    "judge_calibration": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['candidate_review_result'] decisions",),
        produces=("judge calibration/canary evidence",),
        disposition="report_only",
    ),
    "shadow_recall": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['candidate_review_result'] downgrade decisions",),
        produces=("discard fingerprints (plugins.modules.governance.shadow_recall)",),
        disposition="report_only",
    ),
    "provisional": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(
            "context['candidate_review_result'] keep decisions",
            "plugins.memory.memory_os.crystallized (promotion eligibility, dry_run=True)",
        ),
        produces=("provisional records; promotion eligibility report (no auto-promote)",),
        disposition="report_only",
    ),
    "cascade_routing_policy": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['confidence_router_result'] band distribution",),
        produces=("proposed route policy (guarded, does not self-apply)",),
        disposition="report_only",
    ),
    "imagination_loop": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(UNVERIFIED,),
        produces=("simulated scenario artifacts, shared via context['imagination_loop_result']",),
        consumers=("plugins.modules.governance.migration_controller",),
    ),
    "confabulation_detector": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['evidence_scoring_instance']",),
        produces=("confabulation flags, shared via context['confabulation_detector_result']",),
        consumers=("plugins.modules.expression.grounded_expression_judge",),
    ),
    "ground_truth_miner": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store (reversible-labels scope)",),
        produces=("reversible owner-truth labels, shared via context['ground_truth_miner_result']",),
        consumers=("plugins.modules.governance.migration_controller",),
    ),
    "crystallized_revalidator": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store crystallized records",),
        produces=("would-demote flags (report-only)",),
        disposition="report_only",
    ),
    "provisional_sweep": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store provisional records",),
        produces=("TTL/cap sweep result",),
        disposition="report_only",
    ),
    "knob_ab_eval": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("plugins.memory.memory_os.knob_overrides (active overrides with ab_metric set)",),
        produces=("A/B confirm/revert decisions on knob overrides",),
        consumers=("plugins.modules.governance.override_sweep",),
    ),
    "override_sweep": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("plugins.memory.memory_os.knob_overrides", "plugins.modules.governance.live_guard kill switch"),
        produces=("expired/evicted/kill-reverted override counts",),
        disposition="report_only",
    ),
    "migration_controller": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(
            "context['ground_truth_miner_result']",
            "context['evidence_scoring_result']",
            "context['imagination_loop_result']",
        ),
        produces=("migration regime evaluation",),
        disposition="report_only",
    ),
    "abstraction_distillation": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("store.read_events() (latest event only)",),
        produces=("candidate-only distilled summary",),
        disposition="report_only",
    ),
    "grounded_expression_judge": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(
            "context['wandering_mind']",
            "context['confabulation_detector_result']",
            "context['evidence_scoring']",
        ),
        produces=("advisory_ok/blocked verdict, shared via context['grounded_expression_judge_result']",),
        consumers=("plugins.memory.memory_os.cognitive_loop",),
    ),
    "spontaneous_expression": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['wandering_mind']", "context['grounded_expression_judge_result']"),
        produces=("owner-send via plugins.modules.expression.speak_gate (rate-limited, gated)",),
        disposition="report_only",
    ),
    "self_evolution": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(
            "plugins.modules.governance.ops_gate",
            "plugins.modules.governance.proposal_queue",
            "context['evidence_scoring_instance']",
        ),
        produces=("self-evolution proposals, shared via context['self_evolution_instance']",),
        consumers=("plugins.modules.governance.feedback_bridge",),
    ),
    "structural_edge_proposer": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (structural co-occurrence over the index)",),
        produces=("active graph edges (structural proposer; see CLAUDE.md graph-layer notes)",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "crystallization_gate": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (candidate crystallization eligibility)",),
        produces=("flagged candidate list",),
        disposition="report_only",
    ),
    "llm_edge_proposer": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path", "low_clue_recall._call_hermes_runtime_model_result (LLM edge judging via Hermes call_llm)"),
        produces=("active graph edges; born at 0.45 + 0.30 x confidence per CLAUDE.md",),
        consumers=("plugins.memory.memory_os.prefetch",),
        monitor_codes=("llm_lane_consecutive_failure_streak",),
    ),
    "vector_edge_proposer": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (precomputed embeddings)",),
        produces=("active graph edges; born at raw cosine similarity, no upper clamp (documented exception)",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "contradiction_lane": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path", "embedder (build_embedder)"),
        produces=("candidate graph edges (only proposer emitting candidate, not active)",),
        consumers=("plugins.memory.memory_os.edge_promotion",),
    ),
    "edge_provenance": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (source_event_ids on crystallized records)",),
        produces=("event -> crystallized evidence_for provenance edges",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "edge_promotion": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (candidate graph edges, weight-ordered)",),
        produces=("promoted active edges (<=25/run) + invalidated (30-day TTL)",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "edge_weight_feedback": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path (edge hit/injection history)",),
        produces=("reinforced/forgotten edge weights (w += 0.12 x (1-w); 60-day idle -> invalidated)",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "entity_index": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.crystallized_root",),
        produces=("entity_index SQLite table rows",),
        consumers=("plugins.memory.memory_os.prefetch",),
    ),
    "left_brain_pipeline_check": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("proposal/duplicate/quality signals across left-brain modules",),
        produces=("pipeline health findings",),
        disposition="report_only",
    ),
    "host_capability_probe": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots (path-based capability checks)",),
        produces=("host capability map, shared via context['host_capability_probe_result']",),
        consumers=(
            "plugins.memory.memory_os.signal_collectors",
            "plugins.memory.memory_os.memory_projection",
        ),
    ),
    "signal_collection": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['host_capability_probe_result']",),
        produces=(
            "bare signal-source collection result (monitor-required step evidence only; "
            "deliberately not consumed by memory_projection's own re-collection)",
        ),
        disposition="monitor_only",
    ),
    "memory_projection": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['host_capability_probe_result']", "signal_source_registry.signal_source_specs()"),
        produces=("system/memory_projections.jsonl (compacted)",),
        consumers=("plugins.memory.memory_os.left_brain_advisor",),
        monitor_codes=(
            "memory_projection_freshness_missing",
            "memory_projection_stale_after_deploy",
            "memory_projection_retention_compaction_missing",
        ),
    ),
    "left_brain_advisor": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['memory_projection_result']",),
        produces=("owner-visible findings (report-only, not auto-apply)",),
        disposition="report_only",
        monitor_codes=("left_brain_advisor",),
    ),
    "governance_feedback": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=(
            "context['evidence_scoring_instance']",
            "context['ops_gate_instance']",
            "context['proposal_queue_instance']",
            "context['self_evolution_instance']",
        ),
        produces=("governance feedback bridge result (dry_run unless apply=True)",),
        disposition="report_only",
    ),
    "deep_reflection": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("context['proposal_queue_instance']",),
        produces=("reflection analysis artifact",),
        disposition="report_only",
    ),
    "heartbeat_post": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("event queue (post-cycle)",),
        produces=("MemoryOSRuntime.heartbeat() result (second pass within the same cycle)",),
        consumers=("plugins.memory.memory_os.runtime",),
    ),
    "doctor_boundary_report": LaneContract(
        kind=COGNITIVE_LOOP_STEP,
        reads=("roots.index_path counts", "store.read_events()", "candidate queue"),
        produces=("cycle boundary report (event/candidate/crystallized counts + boundary flags)",),
        disposition="report_only",
    ),
}


LANE_CONTRACTS: dict[str, LaneContract] = {**_CRON_LANE_CONTRACTS, **_COGNITIVE_LOOP_STEP_CONTRACTS}


def cron_lane_contract_keys() -> frozenset[str]:
    return frozenset(_CRON_LANE_CONTRACTS)


def cognitive_loop_step_contract_keys() -> frozenset[str]:
    return frozenset(_COGNITIVE_LOOP_STEP_CONTRACTS)
