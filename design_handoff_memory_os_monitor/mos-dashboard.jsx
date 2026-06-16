/* Hermes Memory-OS — comprehensive monitoring dashboard.
   Reads window.MOS. Colors resolve from CSS vars on the themed root,
   so the same component renders in any theme. Exported to window. */

const M = () => window.MOS;

// ── primitives ──────────────────────────────────────────────
function Panel({ title, sub, right, kicker, children, className }) {
  return (
    <section className={"panel " + (className || "")}>
      <header className="panel-h">
        <div className="panel-h-l">
          {kicker && <span className="kicker">{kicker}</span>}
          <h3>{title}</h3>
          {sub && <span className="panel-sub">{sub}</span>}
        </div>
        {right && <div className="panel-h-r">{right}</div>}
      </header>
      <div className="panel-b">{children}</div>
    </section>
  );
}

function Pill({ children, tone = "muted", solid }) {
  return <span className={"pill pill-" + tone + (solid ? " pill-solid" : "")}>{children}</span>;
}

function Dot({ tone }) { return <span className={"dot dot-" + tone} />; }

const toneVar = (t) => ({ good: "var(--pass)", pass: "var(--pass)", warn: "var(--warn)", fail: "var(--fail)", accent: "var(--accent)", muted: "var(--muted)" }[t] || "var(--muted)");

// ── header bar ──────────────────────────────────────────────
function HeaderBar({ themeName }) {
  const d = M().meta, mon = M().monitor;
  const tone = mon.status === "PASS" ? "good" : mon.status === "WARN" ? "warn" : "fail";
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" />
        <div className="brand-txt">
          <div className="brand-name">{d.product}</div>
          <div className="brand-meta">{d.provider} · {d.shell_plugin} · {d.install_mode}</div>
        </div>
      </div>
      <div className="topbar-mid">
        <span className="kv"><i>profile</i>{d.profile}</span>
        <span className="kv"><i>host</i>{d.host} · {d.environment}</span>
        <span className="kv"><i>hindsight</i>{d.hindsight_mode}</span>
        <span className="kv"><i>uptime</i>{d.uptime}</span>
      </div>
      <div className="topbar-right">
        <div className="status-block">
          <div className={"status-pill status-" + tone}>
            <span className="status-led" /> monitor {mon.status}
          </div>
          <div className="status-sub">{mon.pass}/{mon.checks_total} checks · {mon.warn} warn · {mon.fail} fail</div>
        </div>
        <div className="run-block">
          <div className="run-line"><i>run</i>{mon.run_id}</div>
          <div className="run-line"><i>last</i>{mon.last_run_ago} · next {mon.next_run_in}</div>
        </div>
      </div>
      <div className="theme-chip">{themeName}</div>
    </header>
  );
}

// ── monitor health hero ─────────────────────────────────────
function MonitorHero() {
  const mon = M().monitor;
  const tone = mon.status === "PASS" ? "good" : mon.status === "WARN" ? "warn" : "fail";
  return (
    <Panel kicker="overall health" title="Monitor 健康总览" sub={mon.schema}
      className="span-8"
      right={<Pill tone={tone} solid>{mon.status}</Pill>}>
      <div className="hero-grid">
        <div className="hero-gauge">
          <Gauge pass={mon.pass} warn={mon.warn} fail={mon.fail} />
          <div className="gauge-center">
            <div className={"gauge-status gauge-" + tone}>{mon.status}</div>
            <div className="gauge-num">{Math.round((mon.pass / mon.checks_total) * 100)}%</div>
            <div className="gauge-lbl">{mon.checks_total} checks · {mon.duration_ms / 1000}s</div>
          </div>
          <div className="hero-legend">
            <span><Dot tone="good" /> pass {mon.pass}</span>
            <span><Dot tone="warn" /> warn {mon.warn}</span>
            <span><Dot tone="fail" /> fail {mon.fail}</span>
          </div>
        </div>
        <div className="hero-sections">
          {mon.sections.map((s) => {
            const st = s.fail ? "fail" : s.warn ? "warn" : "good";
            return (
              <div className="secrow" key={s.key}>
                <Dot tone={st} />
                <span className="secrow-lbl">{s.label}</span>
                <span className="secrow-key">{s.key}</span>
                <span className="secrow-checks">{s.checks}</span>
                <span className={"secrow-flag flag-" + st}>{s.fail ? s.fail + " F" : s.warn ? s.warn + " W" : "ok"}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="hero-history">
        <div className="hist-lbl">21-day status</div>
        <div className="hist-strip">
          {mon.history.map((h, i) => (
            <span key={i} className={"hist-cell hist-" + (h === 0 ? "good" : h === 1 ? "warn" : "fail")} title={"day " + (i + 1)} />
          ))}
        </div>
      </div>
    </Panel>
  );
}

// ── KPI strip ───────────────────────────────────────────────
function KpiStrip() {
  return (
    <div className="kpi-strip span-12">
      {M().kpis.map((k) => {
        const dirTone = k.dir === "flat" ? "muted" : (k.good === "down" ? (k.dir === "down" ? "good" : "warn") : (k.dir === "up" ? "good" : "warn"));
        return (
          <div className="kpi" key={k.key}>
            <div className="kpi-top">
              <span className="kpi-label">{k.label}</span>
              <span className={"kpi-delta delta-" + dirTone}>{k.delta}</span>
            </div>
            <div className="kpi-val">{k.value.toLocaleString()}<span className="kpi-unit">{k.unit}</span></div>
            <div className="kpi-spark"><Sparkline data={k.spark} color="var(--accent)" fill="var(--accent-soft)" w={150} h={30} /></div>
          </div>
        );
      })}
    </div>
  );
}

// ── cron jobs ───────────────────────────────────────────────
function CronPanel() {
  const c = M().cron;
  return (
    <Panel kicker="hermes cron" title="Cron 作业" sub={`${c.enabled}/${c.total} enabled`}
      className="span-8" right={<Pill tone="good">all ok</Pill>}>
      <table className="tbl">
        <thead><tr><th>job</th><th>deliver</th><th>agent</th><th>schedule</th><th>last</th><th>next</th><th className="ta-r">ms</th><th>status</th></tr></thead>
        <tbody>
          {c.jobs.map((j) => (
            <tr key={j.name}>
              <td className="mono strong">{j.name.replace("memory-os-", "")}</td>
              <td className="mono dim">{j.deliver}</td>
              <td>{j.agent ? <Pill tone="accent">agent</Pill> : <Pill tone="muted">local</Pill>}</td>
              <td className="mono dim">{j.schedule}</td>
              <td className="mono">{j.last}</td>
              <td className="mono dim">{j.next}</td>
              <td className="mono ta-r">{j.last_ms}</td>
              <td><span className="cell-status"><Dot tone="good" />{j.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

// ── owner review queue ──────────────────────────────────────
function OwnerReviewPanel() {
  const o = M().ownerReview;
  const stateSegs = [
    { label: "pending", value: o.states.pending, color: "var(--warn)" },
    { label: "approved", value: o.states.approved, color: "var(--accent)" },
    { label: "applied", value: o.states.applied, color: "var(--pass)" },
    { label: "rejected", value: o.states.rejected, color: "var(--fail)" },
    { label: "allowed", value: o.states.allowed, color: "var(--muted)" },
  ];
  return (
    <Panel kicker="owner action processor" title="Owner 审批队列" sub="oa_ action tokens"
      className="span-4">
      <div className="oreview-counts">
        <div className="ocount oc-action"><b>{o.counts.action_required_shown}</b><span>action_required</span></div>
        <div className="ocount oc-review"><b>{o.counts.review_suggested_shown}</b><span>review_suggested</span></div>
        <div className="ocount oc-fyi"><b>{o.counts.fyi_shown}</b><span>fyi</span></div>
      </div>
      <div className="oreview-donut">
        <Donut segments={stateSegs} size={104} thickness={13} center={{ value: o.states.pending, label: "pending" }} />
        <div className="donut-legend">
          {stateSegs.map((s) => (
            <span key={s.label}><i style={{ background: s.color }} />{s.label} <b>{s.value}</b></span>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function OwnerQueueList() {
  const o = M().ownerReview;
  const sevTone = { action_required: "fail", review_suggested: "warn", fyi: "muted" };
  return (
    <Panel kicker="review surface" title="待办明细" sub="display anchors A/R/F · 稳定 token = oa_"
      className="span-8">
      <table className="tbl">
        <thead><tr><th>#</th><th>oa_ token</th><th>kind</th><th>surface</th><th>age</th><th>severity</th><th>note</th></tr></thead>
        <tbody>
          {o.queue.map((q) => (
            <tr key={q.token}>
              <td className="anchor">{q.anchor}</td>
              <td className="mono strong">{q.token}</td>
              <td className="mono dim">{q.kind}</td>
              <td className="mono dim">{q.surface}</td>
              <td className="mono">{q.age}</td>
              <td><Pill tone={sevTone[q.sev]}>{q.sev}</Pill></td>
              <td className="note">{q.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

// ── memory layers ───────────────────────────────────────────
function MemoryPanel() {
  const m = M().memory;
  const classSegs = m.classes.map((c, i) => ({ ...c, color: `var(--accent-${i})` }));
  return (
    <Panel kicker="canonical memory" title="记忆分层" sub="working ↔ crystallized"
      className="span-7"
      right={<Pill tone={m.index_fresh ? "good" : "warn"}>index {m.index_fresh ? "fresh" : "stale"}</Pill>}>
      <div className="mem-stats">
        <div className="mem-stat"><b>{m.working.toLocaleString()}</b><span>working</span></div>
        <div className="mem-stat"><b>{m.crystallized}</b><span>crystallized</span></div>
        <div className="mem-stat"><b>{m.candidates}</b><span>candidates</span></div>
        <div className="mem-stat"><b>{m.canonical_files.toLocaleString()}</b><span>canonical files</span></div>
        <div className="mem-stat"><b>{m.index_mb}<i>MB</i></b><span>sqlite index</span></div>
        <div className="mem-stat"><b>{m.fts_rows.toLocaleString()}</b><span>fts rows</span></div>
      </div>
      <div className="mem-charts">
        <div className="mem-chart">
          <div className="chart-cap"><span>working memory · 21d</span><span className="mono dim">+{m.working - m.working_trend[0]}</span></div>
          <AreaLine data={m.working_trend} color="var(--accent)" fill="var(--accent-soft)" h={92} />
        </div>
        <div className="mem-chart">
          <div className="chart-cap"><span>crystallized by class</span></div>
          <div className="classbars">
            {m.classes.map((c, i) => {
              const mx = Math.max(...m.classes.map((x) => x.value));
              return (
                <div className="classbar" key={c.label}>
                  <span className="cb-lbl">{c.label}</span>
                  <span className="cb-track"><span className="cb-fill" style={{ width: (c.value / mx * 100) + "%", background: `var(--accent-${i})` }} /></span>
                  <span className="cb-val mono">{c.value}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ── module cadence ──────────────────────────────────────────
function ModulesPanel() {
  const mo = M().modules;
  const t = mo.totals;
  const totalSegs = [
    { label: "generated", value: t.generated_count, color: "var(--accent)" },
    { label: "skipped", value: t.skipped_count, color: "var(--track-2)" },
    { label: "error", value: t.error_count, color: "var(--fail)" },
    { label: "duplicate", value: t.duplicate_count, color: "var(--warn)" },
  ];
  const stTone = { ok: "good", skipped: "muted", error: "fail", missing: "warn", observed: "accent" };
  return (
    <Panel kicker="module_cadence_report.v0" title="模块 cadence" sub={`${mo.module_count} modules · status=${mo.status}`}
      className="span-12"
      right={<><Pill tone="warn">{mo.finding_count} findings</Pill><Pill tone="muted">{mo.split_recommended_count} split-pending</Pill></>}>
      <div className="mod-summary">
        <div className="mod-tot">
          <div className="chart-cap"><span>aggregate counters</span></div>
          <StackBar segments={totalSegs} h={14} />
          <div className="mod-tot-legend">
            {totalSegs.map((s) => <span key={s.label}><i style={{ background: s.color }} />{s.label} <b>{s.value.toLocaleString()}</b></span>)}
          </div>
          <div className="mod-meta">
            <span><i>harness members</i>{mo.integration_harness_member_count}</span>
            <span><i>cron missing</i>{mo.expected_hermes_cron_missing_count}</span>
            <span><i>coverage</i>{t.counter_coverage_count}/{mo.module_count}</span>
          </div>
        </div>
        <table className="tbl tbl-compact">
          <thead><tr><th>module</th><th>runner</th><th>cadence class</th><th className="ta-r">run</th><th className="ta-r">gen</th><th className="ta-r">skip</th><th className="ta-r">err</th><th className="ta-r">dup</th><th>last</th><th>split</th></tr></thead>
          <tbody>
            {mo.rows.map((r) => (
              <tr key={r.module} className={r.err > 0 ? "row-err" : ""}>
                <td className="mono strong">{r.module}</td>
                <td className="mono dim">{r.runner}</td>
                <td className="mono dim">{r.cadence}</td>
                <td className="mono ta-r">{r.run.toLocaleString()}</td>
                <td className="mono ta-r">{r.gen}</td>
                <td className="mono ta-r dim">{r.skip}</td>
                <td className={"mono ta-r " + (r.err ? "v-err" : "dim")}>{r.err}</td>
                <td className={"mono ta-r " + (r.dup ? "v-warn" : "dim")}>{r.dup}</td>
                <td><span className="cell-status"><Dot tone={stTone[r.last] || "muted"} />{r.last}</span></td>
                <td>{r.split ? <Pill tone="warn">pending</Pill> : <span className="dim mono">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// ── right-brain expression ──────────────────────────────────
function ExpressionPanel() {
  const e = M().expression;
  const mx = Math.max(...e.feedback.map((f) => f.value));
  return (
    <Panel kicker="right-brain · speak-gate" title="表达表现" sub="draft → gate → outcome"
      className="span-4">
      <div className="expr-stats">
        <div className="estat"><b>{e.drafts}</b><span>drafts</span></div>
        <div className="estat"><b>{e.would_send}</b><span>would_send</span></div>
        <div className="estat"><b>{e.silent}</b><span>[SILENT]</span></div>
        <div className="estat"><b>{e.sent}</b><span>sent</span></div>
      </div>
      <div className="expr-cad">
        <div className="chart-cap"><span>expression cadence · 21d</span></div>
        <BarSeries data={e.cadence_trend} color="var(--accent)" h={56} gap={3} />
      </div>
      <div className="expr-fb">
        <div className="chart-cap"><span>owner feedback tags</span></div>
        {e.feedback.map((f) => (
          <div className="fbrow" key={f.tag}>
            <span className="fb-lbl mono">{f.tag}</span>
            <span className="fb-track"><span className="fb-fill" style={{ width: (f.value / mx * 100) + "%", background: toneVar(f.tone) }} /></span>
            <span className="fb-val mono">{f.value}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── proposals / opsgate ─────────────────────────────────────
function ProposalsPanel() {
  const p = M().proposals;
  const total = p.states.reduce((s, x) => s + x.value, 0);
  return (
    <Panel kicker="self-evolution · opsgate" title="Proposal 跟进" sub={`${total} proposals tracked`}
      className="span-5">
      <div className="prop-states">
        {p.states.map((s) => (
          <div className="pstate" key={s.label}>
            <span className="ps-bar" style={{ background: toneVar(s.tone) }} />
            <b>{s.value}</b>
            <span className="ps-lbl mono">{s.label}</span>
          </div>
        ))}
      </div>
      <div className="prop-lanes">
        <div className="chart-cap"><span>apply lanes</span><span className="mono dim">approve ≠ execute</span></div>
        {p.lanes.map((l) => (
          <div className="lane" key={l.lane}>
            <span className="lane-name mono strong">{l.lane}</span>
            <span className="lane-desc">{l.desc}</span>
            <span className="lane-count mono">{l.count}</span>
            {l.graduated ? <Pill tone="good">graduated</Pill> : <Pill tone="muted">gated</Pill>}
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── hindsight projection ────────────────────────────────────
function HindsightPanel() {
  const h = M().hindsight;
  return (
    <Panel kicker="derived projection" title="Hindsight 投影账本" sub={h.recall}
      className="span-7"
      right={<Pill tone="accent">{h.mode}</Pill>}>
      <div className="hs-stats">
        <div className="hstat"><b>{h.retained}</b><span>retained</span></div>
        <div className="hstat"><b>{h.retracted}</b><span>retracted</span></div>
        <div className="hstat"><b>{h.ledger_entries.toLocaleString()}</b><span>ledger entries</span></div>
        <div className="hstat"><b>{h.advisory_recall_hits.toLocaleString()}</b><span>recall hits</span></div>
      </div>
      <div className="hs-flags">
        <span className={"hflag " + (h.raw_turn_retain ? "hf-warn" : "hf-ok")}><Dot tone={h.raw_turn_retain ? "warn" : "good"} />raw_turn_retain {String(h.raw_turn_retain)}</span>
        <span className="hflag hf-ok"><Dot tone="good" />source: {h.retain_source}</span>
      </div>
      <div className="hs-charts">
        <div className="hs-chart">
          <div className="chart-cap"><span>retained · 21d</span></div>
          <AreaLine data={h.retained_trend} color="var(--accent)" fill="var(--accent-soft)" h={70} />
        </div>
        <div className="hs-chart">
          <div className="chart-cap"><span>advisory recall hits</span></div>
          <BarSeries data={h.recall_trend} color="var(--accent-2)" h={70} gap={3} />
        </div>
      </div>
    </Panel>
  );
}

// ── feedback ledgers ────────────────────────────────────────
function FeedbackPanel() {
  const f = M().feedback;
  return (
    <Panel kicker="attribution & feedback" title="反馈账本" sub="memory-sources · expression"
      className="span-4">
      <div className="fb-ledgers">
        <div className="ledger">
          <div className="ledger-h">MemorySources</div>
          <div className="ledger-row"><span>prompts</span><b className="mono">{f.memory_sources.prompts}</b></div>
          <div className="ledger-row"><span>responses</span><b className="mono">{f.memory_sources.responses}</b></div>
          <div className="ledger-row"><span>attribution quality</span><b className="mono v-good">{(f.memory_sources.attribution_quality * 100).toFixed(0)}%</b></div>
        </div>
        <div className="ledger">
          <div className="ledger-h">Expression</div>
          <div className="ledger-row"><span>prompts</span><b className="mono">{f.expression.prompts}</b></div>
          <div className="ledger-row"><span>responses</span><b className="mono">{f.expression.responses}</b></div>
          <div className="ledger-row"><span>satisfaction</span><b className="mono v-good">{(f.expression.satisfaction * 100).toFixed(0)}%</b></div>
        </div>
      </div>
      <div className="fb-trend">
        <div className="chart-cap"><span>feedback quality · 21d</span></div>
        <AreaLine data={f.quality_trend} color="var(--accent-2)" fill="var(--accent-soft)" h={66} baseline={0.5} />
      </div>
    </Panel>
  );
}

// ── safety boundaries ───────────────────────────────────────
function BoundaryPanel() {
  const b = M().boundary;
  const stTone = { blocked: "good", disabled: "good", gated: "accent", false: "good" };
  return (
    <Panel kicker="safety model" title="边界守卫" sub="default boundaries enforced"
      className="span-5" right={<Pill tone="good">enforced</Pill>}>
      <div className="bnd-grid">
        {b.map((g) => (
          <div className="bnd" key={g.key}>
            <Dot tone={stTone[g.state] || "good"} />
            <span className="bnd-lbl">{g.label}</span>
            <span className={"bnd-state bs-" + (stTone[g.state] || "good")}>{g.state}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── audit tail ──────────────────────────────────────────────
function AuditPanel() {
  return (
    <Panel kicker="append-only" title="审计流" sub="recent state transitions"
      className="span-12">
      <div className="audit">
        {M().audit.map((a, i) => (
          <div className="audit-row" key={i}>
            <span className="au-t mono dim">{a.t}</span>
            <Dot tone={a.tone} />
            <span className="au-actor mono">{a.actor}</span>
            <span className="au-action mono strong">{a.action}</span>
            <span className="au-detail">{a.detail}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ── full dashboard ──────────────────────────────────────────
function Dashboard({ themeName }) {
  return (
    <div className="mos">
      <HeaderBar themeName={themeName} />
      <div className="grid">
        <MonitorHero />
        <OwnerReviewPanel />
        <KpiStrip />
        <CronPanel />
        <FeedbackPanel />
        <OwnerQueueList />
        <ExpressionPanel />
        <MemoryPanel />
        <ProposalsPanel />
        <ModulesPanel />
        <HindsightPanel />
        <BoundaryPanel />
        <AuditPanel />
      </div>
      <footer className="mos-foot">
        <span>{M().meta.product} · {M().meta.version} · {M().meta.monitor_build}</span>
        <span className="mono dim">generated {M().meta.generated_at} · {M().meta.hermes_home}</span>
      </footer>
    </div>
  );
}

Object.assign(window, { Dashboard });
