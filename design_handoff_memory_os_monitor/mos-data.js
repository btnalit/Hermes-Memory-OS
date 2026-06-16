/* Hermes Memory-OS — shared sample monitoring data.
   Field names mirror the real repo (module_cadence_report.v0, cron set,
   owner_review counts, boundary flags). Values are realistic示意 data. */
(function () {
  // deterministic seeded RNG so trends are stable across reloads
  function rng(seed) {
    let s = seed >>> 0;
    return function () {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }
  // build a wandering series around `base` with given amplitude
  function series(n, base, amp, seed, opts) {
    const r = rng(seed);
    const o = opts || {};
    const out = [];
    let v = base;
    for (let i = 0; i < n; i++) {
      v += (r() - 0.5) * amp;
      if (o.drift) v += o.drift;
      if (o.min != null && v < o.min) v = o.min;
      if (o.max != null && v > o.max) v = o.max;
      out.push(o.int ? Math.round(v) : Math.round(v * 100) / 100);
    }
    return out;
  }

  const DAYS = 21;

  const MOS = {
    meta: {
      product: "Hermes · Memory-OS",
      profile: "main",
      hermes_home: "/root/.hermes",
      provider: "memory_os",
      shell_plugin: "memory-os-agent-os",
      install_mode: "operational",
      hindsight_mode: "shadow",
      host: "hermes-media",
      environment: "prod",
      version: "memory-os 0.9.4",
      monitor_build: "monitor v3.200",
      owner_channel: "telegram",
      generated_at: "2026-06-03 08:42:17 UTC",
      uptime: "37d 04h",
    },

    // ── overall monitor health ──────────────────────────────
    monitor: {
      status: "PASS", // PASS | WARN | FAIL
      run_id: "mon_3200_9f2a17c4",
      schema: "memory-os.module_cadence_report.v0",
      checks_total: 312,
      pass: 304,
      warn: 8,
      fail: 0,
      duration_ms: 18432,
      last_run_at: "08:42:17",
      last_run_ago: "6m ago",
      next_run_in: "24m",
      // per-section health roll-up (the monitor's subsystems)
      sections: [
        { key: "provider", label: "Provider 核心", checks: 41, warn: 0, fail: 0 },
        { key: "indexes", label: "SQLite 索引", checks: 28, warn: 0, fail: 0 },
        { key: "cron", label: "Cron 作业", checks: 35, warn: 0, fail: 0 },
        { key: "owner_review", label: "Owner 审批", checks: 33, warn: 1, fail: 0 },
        { key: "modules", label: "模块 cadence", checks: 88, warn: 4, fail: 0 },
        { key: "expression", label: "Right-brain 表达", checks: 31, warn: 1, fail: 0 },
        { key: "hindsight", label: "Hindsight 投影", checks: 27, warn: 2, fail: 0 },
        { key: "boundary", label: "Safety 边界", checks: 29, warn: 0, fail: 0 },
      ],
      // 21-day status history (0=pass,1=warn,2=fail) for the strip
      history: [0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0],
      checks_trend: series(DAYS, 300, 8, 7, { int: true, min: 290, max: 312 }),
    },

    // ── KPI strip ───────────────────────────────────────────
    kpis: [
      { key: "working", label: "Working memory", unit: "items", value: 1284, delta: "+38", dir: "up", spark: series(DAYS, 1180, 40, 11, { int: true, drift: 5 }) },
      { key: "crystallized", label: "Crystallized", unit: "approved", value: 412, delta: "+6", dir: "up", spark: series(DAYS, 380, 8, 13, { int: true, drift: 1.5 }) },
      { key: "pending", label: "待 owner 审批", unit: "oa_ tokens", value: 3, delta: "−2", dir: "down", good: "down", spark: series(DAYS, 5, 3, 17, { int: true, min: 0, max: 11 }) },
      { key: "cron_ok", label: "Cron 健康", unit: "/ 7 jobs", value: 7, delta: "0", dir: "flat", spark: series(DAYS, 7, 0.2, 19, { int: true, min: 6, max: 7 }) },
      { key: "modules", label: "活跃模块", unit: "/ 18", value: 18, delta: "0", dir: "flat", spark: series(DAYS, 18, 0.1, 23, { int: true, min: 17, max: 18 }) },
      { key: "hindsight", label: "Hindsight 记录", unit: "retained", value: 318, delta: "+4", dir: "up", spark: series(DAYS, 270, 6, 29, { int: true, drift: 2.3 }) },
    ],

    // ── 7 Hermes cron jobs ──────────────────────────────────
    cron: {
      enabled: 7,
      total: 7,
      jobs: [
        { name: "memory-os-owner-review-digest", deliver: "owner · telegram", agent: true, schedule: "0 8 * * *", last: "08:00:04", last_ms: 1240, next: "明日 08:00", status: "ok", out: "9 items shown" },
        { name: "memory-os-right-brain-expression", deliver: "origin", agent: true, schedule: "0 18 * * 1,4", last: "06-02 18:00", last_ms: 2870, next: "06-05 18:00", status: "ok", out: "1 expression" },
        { name: "memory-os-module-cadence-report", deliver: "local", agent: false, schedule: "*/30 * * * *", last: "08:30:11", last_ms: 940, next: "09:00", status: "ok", out: "status=warning" },
        { name: "memory-os-right-brain-expression-outcome", deliver: "local", agent: false, schedule: "15 * * * *", last: "08:15:02", last_ms: 410, next: "09:15", status: "ok", out: "2 outcomes" },
        { name: "memory-os-proposal-followups-opsgate", deliver: "local", agent: false, schedule: "*/20 * * * *", last: "08:40:08", last_ms: 1120, next: "09:00", status: "ok", out: "3 routed" },
        { name: "memory-os-expression-feedback-request", deliver: "owner · telegram", agent: true, schedule: "0 9 * * 2", last: "06-02 09:00", last_ms: 880, next: "06-09 09:00", status: "ok", out: "1 prompt" },
        { name: "memory-os-memory-sources-feedback-request", deliver: "owner · telegram", agent: true, schedule: "0 9 * * 5", last: "05-30 09:00", last_ms: 760, next: "06-06 09:00", status: "ok", out: "1 prompt" },
      ],
    },

    // ── owner review queue ──────────────────────────────────
    ownerReview: {
      mode: "agenda",
      counts: { action_required_shown: 3, review_suggested_shown: 7, fyi_shown: 5 },
      states: { pending: 3, approved: 18, applied: 11, rejected: 4, allowed: 2 },
      queue: [
        { anchor: "A1", token: "oa_7f3c9d", kind: "crystallized_candidate", surface: "owner-home", age: "4h", sev: "action_required", state: "pending", note: "consolidate 3 working notes → identity preference" },
        { anchor: "A2", token: "oa_9b21e4", kind: "approve_session_mirror_apply", surface: "owner-home", age: "1d", sev: "action_required", state: "pending", note: "graduate SessionMirror bounded apply lane" },
        { anchor: "A3", token: "oa_2d84af", kind: "proposal_followup", surface: "owner-home", age: "6h", sev: "action_required", state: "pending", note: "route-tuning proposal → OpsGate review" },
        { anchor: "R1", token: "oa_5e10b7", kind: "expression_feedback", surface: "review-pull", age: "9h", sev: "review_suggested", state: "pending", note: "rate right-brain expression rb_8841" },
        { anchor: "R2", token: "oa_c6f0a1", kind: "memory_sources_feedback", surface: "review-pull", age: "2d", sev: "review_suggested", state: "pending", note: "MemorySources attribution quality" },
        { anchor: "F1", token: "oa_a1d722", kind: "cadence_advisory", surface: "fyi", age: "30m", sev: "fyi", state: "pending", note: "4 modules: production_cadence_split_pending" },
      ],
      throughput: series(DAYS, 4, 3, 31, { int: true, min: 0, max: 12 }),
    },

    // ── memory layers ───────────────────────────────────────
    memory: {
      working: 1284,
      crystallized: 412,
      candidates: 23,
      canonical_files: 1938,
      index_mb: 84.2,
      index_fresh: true,
      index_rebuilt: "07:55:30",
      fts_rows: 9421,
      working_trend: series(DAYS, 1180, 40, 41, { int: true, drift: 5 }),
      crystallized_trend: series(DAYS, 380, 8, 43, { int: true, drift: 1.5 }),
      // distribution of crystallized by class
      classes: [
        { label: "identity", value: 96 },
        { label: "preference", value: 134 },
        { label: "relationship", value: 71 },
        { label: "procedure", value: 58 },
        { label: "fact", value: 53 },
      ],
    },

    // ── module cadence (18 modules) ─────────────────────────
    modules: {
      status: "warning",
      module_count: 18,
      integration_harness_member_count: 11,
      split_recommended_count: 11,
      expected_hermes_cron_missing_count: 0,
      finding_count: 4,
      totals: { generated_count: 4938, skipped_count: 21947, error_count: 9, duplicate_count: 8, counter_coverage_count: 18 },
      rows: [
        { module: "heartbeat_inner_drive", runner: "systemd_timer", cadence: "event_driven_fast", run: 2880, gen: 2864, skip: 14, err: 2, dup: 0, last: "ok", split: false },
        { module: "cognitive_loop", runner: "systemd_timer", cadence: "test_host_harness", run: 1440, gen: 1402, skip: 32, err: 6, dup: 0, last: "ok", split: false },
        { module: "owner_review_digest", runner: "hermes_cron", cadence: "owner_daily", run: 14, gen: 9, skip: 5, err: 0, dup: 0, last: "ok", split: false },
        { module: "right_brain_expression_adapter", runner: "hermes_cron", cadence: "owner_low_frequency", run: 14, gen: 11, skip: 3, err: 0, dup: 0, last: "ok", split: false },
        { module: "digest_consolidation", runner: "cognitive_loop", cadence: "daily_weekly", run: 1440, gen: 38, skip: 1402, err: 0, dup: 0, last: "skipped", split: true },
        { module: "household_digest", runner: "cognitive_loop", cadence: "daily_or_on_signal", run: 1440, gen: 14, skip: 1426, err: 0, dup: 0, last: "skipped", split: true },
        { module: "wandering_mind", runner: "cognitive_loop", cadence: "low_freq_or_signal", run: 1440, gen: 64, skip: 1376, err: 0, dup: 0, last: "skipped", split: true },
        { module: "expression_draft", runner: "cognitive_loop", cadence: "on_signal", run: 1440, gen: 64, skip: 1374, err: 0, dup: 2, last: "ok", split: true },
        { module: "speak_gate", runner: "cognitive_loop", cadence: "on_signal", run: 1440, gen: 41, skip: 1399, err: 0, dup: 0, last: "ok", split: true },
        { module: "evidence_scoring", runner: "cognitive_loop", cadence: "daily_or_on_new_signal", run: 1440, gen: 372, skip: 1067, err: 1, dup: 0, last: "ok", split: true },
        { module: "self_evolution", runner: "cognitive_loop", cadence: "daily_weekly_or_signal", run: 1440, gen: 27, skip: 1408, err: 0, dup: 5, last: "skipped", split: true },
        { module: "governance_feedback", runner: "cognitive_loop", cadence: "daily_or_on_new_signal", run: 1440, gen: 48, skip: 1392, err: 0, dup: 0, last: "ok", split: true },
        { module: "deep_reflection", runner: "cognitive_loop", cadence: "daily_weekly_or_min", run: 1440, gen: 12, skip: 1428, err: 0, dup: 0, last: "skipped", split: true },
        { module: "ops_gate", runner: "cognitive_loop", cadence: "on_approved_proposal", run: 1440, gen: 9, skip: 1430, err: 0, dup: 1, last: "ok", split: true },
        { module: "left_brain_pipeline_check", runner: "cognitive_loop", cadence: "monitor_poll_or_daily", run: 1440, gen: 1, skip: 1439, err: 0, dup: 0, last: "ok", split: true },
        { module: "session_mirror", runner: "manual_or_monitor", cadence: "on_demand_or_approved_apply", run: 6, gen: 6, skip: 0, err: 0, dup: 0, last: "ok", split: false },
        { module: "rh31_eval", runner: "manual_or_monitor", cadence: "on_demand_or_monitor_poll", run: 3, gen: 3, skip: 0, err: 0, dup: 0, last: "ok", split: false },
        { module: "metadata_retention", runner: "manual_or_monitor", cadence: "on_demand_dry_run", run: 2, gen: 2, skip: 0, err: 0, dup: 0, last: "ok", split: false },
      ],
      findings: [
        { code: "production_cadence_split_pending", module: "digest_consolidation", severity: "warning" },
        { code: "production_cadence_split_pending", module: "household_digest", severity: "warning" },
        { code: "production_cadence_split_pending", module: "deep_reflection", severity: "warning" },
        { code: "production_cadence_split_pending", module: "left_brain_pipeline_check", severity: "warning" },
      ],
    },

    // ── right-brain expression ──────────────────────────────
    expression: {
      drafts: 64,
      would_send: 41,
      silent: 23,
      sent: 38,
      outcomes_recorded: 36,
      cadence_trend: series(DAYS, 3, 2, 47, { int: true, min: 0, max: 7 }),
      feedback: [
        { tag: "like_expression", value: 22, tone: "good" },
        { tag: "resonant", value: 9, tone: "good" },
        { tag: "neutral", value: 7, tone: "muted" },
        { tag: "too_mechanistic", value: 6, tone: "warn" },
        { tag: "off_tone", value: 2, tone: "warn" },
      ],
    },

    // ── proposals / OpsGate follow-up ───────────────────────
    proposals: {
      states: [
        { label: "pending_followup", value: 5, tone: "warn" },
        { label: "in_opsgate_review", value: 3, tone: "accent" },
        { label: "report_only", value: 7, tone: "muted" },
        { label: "applied", value: 2, tone: "good" },
        { label: "rejected", value: 1, tone: "fail" },
      ],
      lanes: [
        { lane: "report_only", desc: "process motion · no execution", count: 7, graduated: false },
        { lane: "opsgate_review", desc: "approved → bounded review", count: 3, graduated: false },
        { lane: "session_mirror_apply", desc: "bounded apply · owner-graduated", count: 1, graduated: true },
        { lane: "bounded_apply", desc: "rollback + monitor + apply token", count: 2, graduated: true },
      ],
    },

    // ── Hindsight derived projection ────────────────────────
    hindsight: {
      mode: "shadow", // off | shadow | active
      retain_source: "crystallized · owner-approved · distilled",
      raw_turn_retain: false,
      recall: "advisory · derived_projection",
      retained: 318,
      retracted: 12,
      ledger_entries: 1706,
      advisory_recall_hits: 1442,
      retained_trend: series(DAYS, 270, 6, 53, { int: true, drift: 2.3 }),
      recall_trend: series(DAYS, 55, 18, 59, { int: true, min: 10, max: 110 }),
    },

    // ── feedback ledgers ────────────────────────────────────
    feedback: {
      memory_sources: { prompts: 14, responses: 11, attribution_quality: 0.86 },
      expression: { prompts: 14, responses: 12, satisfaction: 0.78 },
      quality_trend: series(DAYS, 0.78, 0.06, 61, { min: 0.6, max: 0.95 }),
    },

    // ── safety boundaries ───────────────────────────────────
    boundary: [
      { key: "actual_send", label: "Direct platform send", state: "blocked" },
      { key: "actual_execute", label: "External execution", state: "blocked" },
      { key: "actual_identity_write", label: "Identity write", state: "gated" },
      { key: "actual_unapproved_crystallized_approval", label: "Unapproved crystallize", state: "blocked" },
      { key: "ungoverned_hindsight_export", label: "Ungoverned Hindsight export", state: "blocked" },
      { key: "raw_turn_retain", label: "Raw-turn retain", state: "disabled" },
      { key: "cleanup_apply", label: "Cleanup apply", state: "gated" },
      { key: "shadow_journal_apply", label: "Shadow-journal apply", state: "gated" },
      { key: "cron_modified", label: "Cron mutation by MOS", state: "false" },
    ],

    // ── audit tail ──────────────────────────────────────────
    audit: [
      { t: "08:42:17", actor: "monitor", action: "monitor.run", detail: "status=PASS · 312 checks · 8 warn", tone: "good" },
      { t: "08:40:08", actor: "ops_gate", action: "proposal.route", detail: "3 proposals → report_only follow-up", tone: "muted" },
      { t: "08:30:11", actor: "cadence", action: "report.append", detail: "module_cadence_report.v0 · status=warning", tone: "warn" },
      { t: "07:55:30", actor: "index", action: "fts.rebuild", detail: "9,421 rows · 84.2 MB", tone: "muted" },
      { t: "07:12:44", actor: "owner", action: "review.approve", detail: "oa_b330e1 crystallized_candidate", tone: "good" },
      { t: "06-02 18:00", actor: "owner", action: "review.feedback", detail: "oa_5e10b7 like_expression", tone: "good" },
      { t: "06-02 14:21", actor: "hindsight", action: "projection.retain", detail: "4 records · append-only ledger", tone: "muted" },
      { t: "06-02 09:03", actor: "owner", action: "review.feedback", detail: "oa_77c0a2 too_mechanistic", tone: "warn" },
    ],
  };

  window.MOS = MOS;
})();
