(function () {
  "use strict";

  const toneVar = {
    good: "var(--pass)",
    pass: "var(--pass)",
    warn: "var(--warn)",
    fail: "var(--fail)",
    accent: "var(--accent)",
    muted: "var(--muted)",
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function num(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n : 0;
  }

  function fmt(value) {
    return num(value).toLocaleString();
  }

  function pct(value) {
    return `${Math.round(num(value) * 100)}%`;
  }

  function cssTone(tone) {
    return toneVar[tone] || "var(--muted)";
  }

  function dot(tone) {
    return `<span class="dot dot-${esc(tone || "muted")}"></span>`;
  }

  function pill(text, tone = "muted", solid = false) {
    return `<span class="pill pill-${esc(tone)}${solid ? " pill-solid" : ""}">${esc(text)}</span>`;
  }

  function panel({ kicker, title, sub, right, className, body }) {
    return `
      <section class="panel ${esc(className || "")}">
        <header class="panel-h">
          <div class="panel-h-l">
            ${kicker ? `<span class="kicker">${esc(kicker)}</span>` : ""}
            <h3>${esc(title)}</h3>
            ${sub ? `<span class="panel-sub">${esc(sub)}</span>` : ""}
          </div>
          ${right ? `<div class="panel-h-r">${right}</div>` : ""}
        </header>
        <div class="panel-b">${body || ""}</div>
      </section>`;
  }

  function series(data) {
    return Array.isArray(data) && data.length ? data.map(num) : [0];
  }

  function pointPath(data, w, h, pad = 3, baseline) {
    const values = series(data);
    const min = Math.min(baseline == null ? Math.min(...values) : baseline, ...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const iw = w - pad * 2;
    const ih = h - pad * 2;
    const denom = Math.max(values.length - 1, 1);
    const pts = values.map((v, i) => {
      const x = pad + (i / denom) * iw;
      const y = pad + ih - ((v - min) / span) * ih;
      return [x, y];
    });
    return {
      d: pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" "),
      pts,
      pad,
      iw,
      ih,
    };
  }

  function sparkline(data, color = "var(--accent)", fill = "var(--accent-soft)", w = 150, h = 30) {
    const path = pointPath(data, w, h);
    const area = `${path.d} L ${w} ${h} L 0 ${h} Z`;
    return `
      <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" preserveAspectRatio="none" style="display:block">
        ${fill ? `<path d="${esc(area)}" fill="${esc(fill)}"></path>` : ""}
        <path d="${esc(path.d)}" fill="none" stroke="${esc(color)}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>`;
  }

  function areaLine(data, color = "var(--accent)", fill = "var(--accent-soft)", h = 150, baseline = 0) {
    const w = 520;
    const pad = 8;
    const path = pointPath(data, w, h, pad, baseline);
    const area = `${path.d} L ${pad + path.iw} ${pad + path.ih} L ${pad} ${pad + path.ih} Z`;
    return `
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" style="display:block">
        <line x1="${pad}" x2="${pad + path.iw}" y1="${pad + path.ih * 0.25}" y2="${pad + path.ih * 0.25}" stroke="var(--grid)" stroke-width="1" stroke-dasharray="2 4"></line>
        <line x1="${pad}" x2="${pad + path.iw}" y1="${pad + path.ih * 0.5}" y2="${pad + path.ih * 0.5}" stroke="var(--grid)" stroke-width="1" stroke-dasharray="2 4"></line>
        <line x1="${pad}" x2="${pad + path.iw}" y1="${pad + path.ih * 0.75}" y2="${pad + path.ih * 0.75}" stroke="var(--grid)" stroke-width="1" stroke-dasharray="2 4"></line>
        ${fill ? `<path d="${esc(area)}" fill="${esc(fill)}"></path>` : ""}
        <path d="${esc(path.d)}" fill="none" stroke="${esc(color)}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>`;
  }

  function barSeries(data, color = "var(--accent)", h = 120, gap = 2) {
    const values = series(data);
    const w = 520;
    const max = Math.max(...values) || 1;
    const bw = (w - gap * (values.length - 1)) / values.length;
    const bars = values.map((v, i) => {
      const bh = (v / max) * (h - 4);
      return `<rect x="${(i * (bw + gap)).toFixed(2)}" y="${(h - bh).toFixed(2)}" width="${bw.toFixed(2)}" height="${bh.toFixed(2)}" rx="1.5" fill="${esc(color)}"></rect>`;
    }).join("");
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" style="display:block">${bars}</svg>`;
  }

  function stackBar(segments, h = 12) {
    const safe = Array.isArray(segments) ? segments : [];
    const total = safe.reduce((sum, item) => sum + num(item.value), 0) || 1;
    let x = 0;
    const rects = safe.map((item) => {
      const w = (num(item.value) / total) * 100;
      const rect = `<rect x="${x.toFixed(2)}" y="0" width="${(w + 0.4).toFixed(2)}" height="${h}" fill="${esc(item.color)}"></rect>`;
      x += w;
      return rect;
    }).join("");
    return `<svg viewBox="0 0 100 ${h}" width="100%" height="${h}" preserveAspectRatio="none" style="display:block;border-radius:6px;overflow:hidden">${rects}</svg>`;
  }

  function donut(segments, size = 104, thickness = 13, center) {
    const safe = Array.isArray(segments) ? segments : [];
    const total = safe.reduce((sum, item) => sum + num(item.value), 0) || 1;
    const r = (size - thickness) / 2;
    const c = size / 2;
    const circ = 2 * Math.PI * r;
    let offset = 0;
    const arcs = safe.map((item) => {
      const frac = num(item.value) / total;
      const len = Math.max(0, frac * circ - 2);
      const arc = `
        <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${esc(item.color)}" stroke-width="${thickness}"
          stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-offset}"
          transform="rotate(-90 ${c} ${c})"></circle>`;
      offset += frac * circ;
      return arc;
    }).join("");
    const centerSvg = center ? `
      <text x="${c}" y="${c - 2}" text-anchor="middle" font-size="${size * 0.2}" font-weight="700" fill="var(--text)" style="font-family:var(--mono)">${esc(center.value)}</text>
      <text x="${c}" y="${c + size * 0.13}" text-anchor="middle" font-size="${size * 0.085}" fill="var(--muted)" style="font-family:var(--mono);letter-spacing:.05em">${esc(center.label)}</text>` : "";
    return `
      <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
        <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="var(--track)" stroke-width="${thickness}"></circle>
        ${arcs}
        ${centerSvg}
      </svg>`;
  }

  function gauge(pass, warn, fail, size = 220) {
    const total = pass + warn + fail || 1;
    const r = size * 0.4;
    const c = size / 2;
    const stroke = size * 0.075;
    const arcLen = Math.PI * r;
    const cy = c + size * 0.13;
    let offset = 0;
    const segs = [
      { v: pass, col: "var(--pass)" },
      { v: warn, col: "var(--warn)" },
      { v: fail, col: "var(--fail)" },
    ];
    const arcs = segs.map((item) => {
      const len = (item.v / total) * arcLen;
      const arc = `
        <path d="M ${c - r} ${cy} A ${r} ${r} 0 0 1 ${c + r} ${cy}" fill="none"
          stroke="${item.col}" stroke-width="${stroke}" stroke-dasharray="${Math.max(0, len - 1.5)} ${arcLen}"
          stroke-dashoffset="${-offset}" stroke-linecap="butt"></path>`;
      offset += len;
      return arc;
    }).join("");
    return `
      <svg viewBox="0 0 ${size} ${size * 0.62}" width="100%" height="${size * 0.62}">
        <path d="M ${c - r} ${cy} A ${r} ${r} 0 0 1 ${c + r} ${cy}" fill="none" stroke="var(--track)" stroke-width="${stroke}" stroke-linecap="round"></path>
        ${arcs}
      </svg>`;
  }

  function headerBar(data) {
    const d = data.meta || {};
    const mon = data.monitor || {};
    const tone = mon.status === "PASS" ? "good" : mon.status === "WARN" ? "warn" : "fail";
    return `
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark"></span>
          <div class="brand-txt">
            <div class="brand-name">${esc(d.product)}</div>
            <div class="brand-meta">${esc(d.provider)} · ${esc(d.shell_plugin)} · ${esc(d.install_mode)}</div>
          </div>
        </div>
        <div class="topbar-mid">
          <span class="kv"><i>profile</i>${esc(d.profile)}</span>
          <span class="kv"><i>host</i>${esc(d.host)} · ${esc(d.environment)}</span>
          <span class="kv"><i>hindsight</i>${esc(d.hindsight_mode)}</span>
          <span class="kv"><i>uptime</i>${esc(d.uptime)}</span>
        </div>
        <div class="topbar-right">
          <div class="status-block">
            <div class="status-pill status-${tone}"><span class="status-led"></span> monitor ${esc(mon.status)}</div>
            <div class="status-sub">${fmt(mon.pass)}/${fmt(mon.checks_total)} checks · ${fmt(mon.warn)} warn · ${fmt(mon.fail)} fail</div>
          </div>
          <div class="run-block">
            <div class="run-line"><i>run</i>${esc(mon.run_id)}</div>
            <div class="run-line"><i>last</i>${esc(mon.last_run_ago)} · next ${esc(mon.next_run_in)}</div>
          </div>
        </div>
        <div class="theme-chip">Control Room</div>
      </header>`;
  }

  function monitorHero(data) {
    const mon = data.monitor || {};
    const tone = mon.status === "PASS" ? "good" : mon.status === "WARN" ? "warn" : "fail";
    const sections = (mon.sections || []).map((s) => {
      const st = num(s.fail) ? "fail" : num(s.warn) ? "warn" : "good";
      return `
        <div class="secrow">
          ${dot(st)}
          <span class="secrow-lbl">${esc(s.label)}</span>
          <span class="secrow-key">${esc(s.key)}</span>
          <span class="secrow-checks">${fmt(s.checks)}</span>
          <span class="secrow-flag flag-${st}">${num(s.fail) ? `${fmt(s.fail)} F` : num(s.warn) ? `${fmt(s.warn)} W` : "ok"}</span>
        </div>`;
    }).join("");
    const history = (mon.history || []).map((h) => `<span class="hist-cell hist-${h === 0 ? "good" : h === 1 ? "warn" : "fail"}"></span>`).join("");
    const percent = mon.checks_total ? Math.round((num(mon.pass) / num(mon.checks_total)) * 100) : 0;
    return panel({
      kicker: "overall health",
      title: "Monitor 健康总览",
      sub: mon.schema,
      className: "span-8",
      right: pill(mon.status, tone, true),
      body: `
        <div class="hero-grid">
          <div class="hero-gauge">
            ${gauge(num(mon.pass), num(mon.warn), num(mon.fail))}
            <div class="gauge-center">
              <div class="gauge-status gauge-${tone}">${esc(mon.status)}</div>
              <div class="gauge-num">${percent}%</div>
              <div class="gauge-lbl">${fmt(mon.checks_total)} checks · ${(num(mon.duration_ms) / 1000).toFixed(1)}s</div>
            </div>
            <div class="hero-legend">
              <span>${dot("good")} pass ${fmt(mon.pass)}</span>
              <span>${dot("warn")} warn ${fmt(mon.warn)}</span>
              <span>${dot("fail")} fail ${fmt(mon.fail)}</span>
            </div>
          </div>
          <div class="hero-sections">${sections}</div>
        </div>
        <div class="hero-history">
          <div class="hist-lbl">21-day status</div>
          <div class="hist-strip">${history}</div>
        </div>`,
    });
  }

  function ownerReviewPanel(data) {
    const o = data.ownerReview || {};
    const states = o.states || {};
    const segments = [
      { label: "pending", value: states.pending, color: "var(--warn)" },
      { label: "approved", value: states.approved, color: "var(--accent)" },
      { label: "applied", value: states.applied, color: "var(--pass)" },
      { label: "rejected", value: states.rejected, color: "var(--fail)" },
      { label: "allowed", value: states.allowed, color: "var(--muted)" },
    ];
    return panel({
      kicker: "owner action processor",
      title: "Owner 审批队列",
      sub: "oa_ action tokens",
      className: "span-4",
      body: `
        <div class="oreview-counts">
          <div class="ocount oc-action"><b>${fmt(o.counts && o.counts.action_required_shown)}</b><span>action_required</span></div>
          <div class="ocount oc-review"><b>${fmt(o.counts && o.counts.review_suggested_shown)}</b><span>review_suggested</span></div>
          <div class="ocount oc-fyi"><b>${fmt(o.counts && o.counts.fyi_shown)}</b><span>fyi</span></div>
        </div>
        <div class="oreview-donut">
          ${donut(segments, 104, 13, { value: fmt(states.pending), label: "pending" })}
          <div class="donut-legend">
            ${segments.map((s) => `<span><i style="background:${esc(s.color)}"></i>${esc(s.label)} <b>${fmt(s.value)}</b></span>`).join("")}
          </div>
        </div>`,
    });
  }

  function kpiStrip(data) {
    return `
      <div class="kpi-strip span-12">
        ${(data.kpis || []).map((k) => {
          const dirTone = k.dir === "flat" ? "muted" : (k.good === "down" ? (k.dir === "down" ? "good" : "warn") : (k.dir === "up" ? "good" : "warn"));
          return `
            <div class="kpi">
              <div class="kpi-top">
                <span class="kpi-label">${esc(k.label)}</span>
                <span class="kpi-delta delta-${dirTone}">${esc(k.delta)}</span>
              </div>
              <div class="kpi-val">${fmt(k.value)}<span class="kpi-unit">${esc(k.unit)}</span></div>
              <div class="kpi-spark">${sparkline(k.spark)}</div>
            </div>`;
        }).join("")}
      </div>`;
  }

  function cronPanel(data) {
    const c = data.cron || {};
    const rows = (c.jobs || []).map((j) => `
      <tr>
        <td class="mono strong">${esc(String(j.name || "").replace("memory-os-", ""))}</td>
        <td class="mono dim">${esc(j.deliver)}</td>
        <td>${j.agent ? pill("agent", "accent") : pill("local", "muted")}</td>
        <td class="mono dim">${esc(j.schedule)}</td>
        <td class="mono">${esc(j.last)}</td>
        <td class="mono dim">${esc(j.next)}</td>
        <td class="mono ta-r">${fmt(j.last_ms)}</td>
        <td><span class="cell-status">${dot(j.status === "ok" ? "good" : "warn")}${esc(j.status)}</span></td>
      </tr>`).join("");
    return panel({
      kicker: "hermes cron",
      title: "Cron 作业",
      sub: `${fmt(c.enabled)}/${fmt(c.total)} enabled`,
      className: "span-12",
      right: pill(c.enabled === c.total ? "all ok" : "partial", c.enabled === c.total ? "good" : "warn"),
      body: `
        <table class="tbl">
          <thead><tr><th>job</th><th>deliver</th><th>agent</th><th>schedule</th><th>last</th><th>next</th><th class="ta-r">ms</th><th>status</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`,
    });
  }

  function feedbackPanel(data) {
    const f = data.feedback || {};
    const ms = f.memory_sources || {};
    const ex = f.expression || {};
    return panel({
      kicker: "attribution & feedback",
      title: "反馈账本",
      sub: "memory-sources · expression",
      className: "span-4",
      body: `
        <div class="fb-ledgers">
          <div class="ledger">
            <div class="ledger-h">MemorySources</div>
            <div class="ledger-row"><span>prompts</span><b class="mono">${fmt(ms.prompts)}</b></div>
            <div class="ledger-row"><span>responses</span><b class="mono">${fmt(ms.responses)}</b></div>
            <div class="ledger-row"><span>attribution quality</span><b class="mono v-good">${pct(ms.attribution_quality)}</b></div>
          </div>
          <div class="ledger">
            <div class="ledger-h">Expression</div>
            <div class="ledger-row"><span>prompts</span><b class="mono">${fmt(ex.prompts)}</b></div>
            <div class="ledger-row"><span>responses</span><b class="mono">${fmt(ex.responses)}</b></div>
            <div class="ledger-row"><span>satisfaction</span><b class="mono v-good">${pct(ex.satisfaction)}</b></div>
          </div>
        </div>
        <div class="fb-trend">
          <div class="chart-cap"><span>feedback quality · 21d</span></div>
          ${areaLine(f.quality_trend, "var(--accent-2)", "var(--accent-soft)", 66, 0.5)}
        </div>`,
    });
  }

  function ownerQueueList(data) {
    const o = data.ownerReview || {};
    const tone = { action_required: "fail", review_suggested: "warn", fyi: "muted" };
    const queue = o.queue || [];
    const rows = queue.length ? queue.map((q) => `
      <tr>
        <td class="anchor">${esc(q.anchor)}</td>
        <td class="mono strong">${esc(q.token)}</td>
        <td class="mono dim">${esc(q.kind)}</td>
        <td class="mono dim">${esc(q.surface)}</td>
        <td class="mono">${esc(q.age)}</td>
        <td>${pill(q.sev, tone[q.sev] || "muted")}</td>
        <td class="note">${esc(q.note)}</td>
      </tr>`).join("") : '<tr class="empty-row"><td colspan="7">当前没有待处理 owner action token</td></tr>';
    return panel({
      kicker: "review surface",
      title: "待办明细",
      sub: "display anchors A/R/F · 稳定 token = oa_",
      className: "span-12",
      body: `
        <table class="tbl">
          <thead><tr><th>#</th><th>oa_ token</th><th>kind</th><th>surface</th><th>age</th><th>severity</th><th>note</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`,
    });
  }

  function expressionPanel(data) {
    const e = data.expression || {};
    const feedback = e.feedback || [];
    const max = Math.max(...feedback.map((f) => num(f.value)), 1);
    return panel({
      kicker: "right-brain · speak-gate",
      title: "表达表现",
      sub: "draft → gate → outcome",
      className: "span-4",
      body: `
        <div class="expr-stats">
          <div class="estat"><b>${fmt(e.drafts)}</b><span>drafts</span></div>
          <div class="estat"><b>${fmt(e.would_send)}</b><span>would_send</span></div>
          <div class="estat"><b>${fmt(e.silent)}</b><span>[SILENT]</span></div>
          <div class="estat"><b>${fmt(e.sent)}</b><span>sent</span></div>
        </div>
        <div class="expr-cad">
          <div class="chart-cap"><span>expression cadence · 21d</span></div>
          ${barSeries(e.cadence_trend, "var(--accent)", 56, 3)}
        </div>
        <div class="expr-fb">
          <div class="chart-cap"><span>owner feedback tags</span></div>
          ${feedback.map((f) => `
            <div class="fbrow">
              <span class="fb-lbl mono">${esc(f.tag)}</span>
              <span class="fb-track"><span class="fb-fill" style="width:${Math.min(100, (num(f.value) / max) * 100)}%;background:${cssTone(f.tone)}"></span></span>
              <span class="fb-val mono">${fmt(f.value)}</span>
            </div>`).join("")}
        </div>`,
    });
  }

  function memoryPanel(data) {
    const m = data.memory || {};
    const classes = m.classes || [];
    const max = Math.max(...classes.map((c) => num(c.value)), 1);
    return panel({
      kicker: "canonical memory",
      title: "记忆分层",
      sub: "working ↔ crystallized",
      className: "span-6",
      right: pill(`index ${m.index_fresh ? "fresh" : "stale"}`, m.index_fresh ? "good" : "warn"),
      body: `
        <div class="mem-stats">
          <div class="mem-stat"><b>${fmt(m.working)}</b><span>working</span></div>
          <div class="mem-stat"><b>${fmt(m.crystallized)}</b><span>crystallized</span></div>
          <div class="mem-stat"><b>${fmt(m.candidates)}</b><span>candidates</span></div>
          <div class="mem-stat"><b>${fmt(m.canonical_files)}</b><span>canonical files</span></div>
          <div class="mem-stat"><b>${num(m.index_mb).toFixed(1)}<i>MB</i></b><span>sqlite index</span></div>
          <div class="mem-stat"><b>${fmt(m.fts_rows)}</b><span>fts rows</span></div>
        </div>
        <div class="mem-charts">
          <div class="mem-chart">
            <div class="chart-cap"><span>working memory · 21d</span><span class="mono dim">${fmt(m.working)}</span></div>
            ${areaLine(m.working_trend, "var(--accent)", "var(--accent-soft)", 92)}
          </div>
          <div class="mem-chart">
            <div class="chart-cap"><span>crystallized by class</span></div>
            <div class="classbars">
              ${classes.map((c, i) => `
                <div class="classbar">
                  <span class="cb-lbl">${esc(c.label)}</span>
                  <span class="cb-track"><span class="cb-fill" style="width:${Math.min(100, (num(c.value) / max) * 100)}%;background:var(--accent-${i})"></span></span>
                  <span class="cb-val mono">${fmt(c.value)}</span>
                </div>`).join("")}
            </div>
          </div>
        </div>`,
    });
  }

  function proposalsPanel(data) {
    const p = data.proposals || {};
    const states = p.states || [];
    const total = states.reduce((sum, item) => sum + num(item.value), 0);
    return panel({
      kicker: "self-evolution · opsgate",
      title: "Proposal 跟进",
      sub: `${fmt(total)} proposals tracked`,
      className: "span-4",
      body: `
        <div class="prop-states">
          ${states.map((s) => `
            <div class="pstate">
              <span class="ps-bar" style="background:${cssTone(s.tone)}"></span>
              <b>${fmt(s.value)}</b>
              <span class="ps-lbl mono">${esc(s.label)}</span>
            </div>`).join("")}
        </div>
        <div class="prop-lanes">
          <div class="chart-cap"><span>apply lanes</span><span class="mono dim">approve ≠ execute</span></div>
          ${(p.lanes || []).map((l) => `
            <div class="lane">
              <span class="lane-name mono strong">${esc(l.lane)}</span>
              <span class="lane-desc">${esc(l.desc)}</span>
              <span class="lane-count mono">${fmt(l.count)}</span>
              ${l.graduated ? pill("graduated", "good") : pill("gated", "muted")}
            </div>`).join("")}
        </div>`,
    });
  }

  function modulesPanel(data) {
    const mo = data.modules || {};
    const t = mo.totals || {};
    const segments = [
      { label: "generated", value: t.generated_count, color: "var(--accent)" },
      { label: "skipped", value: t.skipped_count, color: "var(--track-2)" },
      { label: "error", value: t.error_count, color: "var(--fail)" },
      { label: "duplicate", value: t.duplicate_count, color: "var(--warn)" },
    ];
    const stTone = { ok: "good", skipped: "muted", error: "fail", missing: "warn", observed: "accent" };
    const rows = (mo.rows || []).map((r) => `
      <tr class="${num(r.err) > 0 ? "row-err" : ""}">
        <td class="mono strong">${esc(r.module)}</td>
        <td class="mono dim">${esc(r.runner)}</td>
        <td class="mono dim">${esc(r.cadence)}</td>
        <td class="mono ta-r">${fmt(r.run)}</td>
        <td class="mono ta-r">${fmt(r.gen)}</td>
        <td class="mono ta-r dim">${fmt(r.skip)}</td>
        <td class="mono ta-r ${num(r.err) ? "v-err" : "dim"}">${fmt(r.err)}</td>
        <td class="mono ta-r ${num(r.dup) ? "v-warn" : "dim"}">${fmt(r.dup)}</td>
        <td><span class="cell-status">${dot(stTone[r.last] || "muted")}${esc(r.last)}</span></td>
        <td>${r.split ? pill("pending", "warn") : '<span class="dim mono">-</span>'}</td>
      </tr>`).join("");
    return panel({
      kicker: "module_cadence_report.v0",
      title: "模块 cadence",
      sub: `${fmt(mo.module_count)} modules · status=${esc(mo.status)}`,
      className: "span-12",
      right: `${pill(`${fmt(mo.finding_count)} findings`, num(mo.finding_count) ? "warn" : "muted")}${pill(`${fmt(mo.split_recommended_count)} split-pending`, "muted")}`,
      body: `
        <div class="mod-summary">
          <div class="mod-tot">
            <div class="chart-cap"><span>aggregate counters</span></div>
            ${stackBar(segments, 14)}
            <div class="mod-tot-legend">
              ${segments.map((s) => `<span><i style="background:${esc(s.color)}"></i>${esc(s.label)} <b>${fmt(s.value)}</b></span>`).join("")}
            </div>
            <div class="mod-meta">
              <span><i>harness members</i>${fmt(mo.integration_harness_member_count)}</span>
              <span><i>cron missing</i>${fmt(mo.expected_hermes_cron_missing_count)}</span>
              <span><i>coverage</i>${fmt(t.counter_coverage_count)}/${fmt(mo.module_count)}</span>
            </div>
          </div>
          <table class="tbl tbl-compact">
            <thead><tr><th>module</th><th>runner</th><th>cadence class</th><th class="ta-r">run</th><th class="ta-r">gen</th><th class="ta-r">skip</th><th class="ta-r">err</th><th class="ta-r">dup</th><th>last</th><th>split</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`,
    });
  }

  function hindsightPanel(data) {
    const h = data.hindsight || {};
    return panel({
      kicker: "derived projection",
      title: "Hindsight 投影账本",
      sub: h.recall,
      className: "span-6",
      right: pill(h.mode, "accent"),
      body: `
        <div class="hs-stats">
          <div class="hstat"><b>${fmt(h.retained)}</b><span>retained</span></div>
          <div class="hstat"><b>${fmt(h.retracted)}</b><span>retracted</span></div>
          <div class="hstat"><b>${fmt(h.ledger_entries)}</b><span>ledger entries</span></div>
          <div class="hstat"><b>${fmt(h.advisory_recall_hits)}</b><span>recall hits</span></div>
        </div>
        <div class="hs-flags">
          <span class="hflag ${h.raw_turn_retain ? "hf-warn" : "hf-ok"}">${dot(h.raw_turn_retain ? "warn" : "good")}raw_turn_retain ${esc(String(!!h.raw_turn_retain))}</span>
          <span class="hflag hf-ok">${dot("good")}source: ${esc(h.retain_source)}</span>
        </div>
        <div class="hs-charts">
          <div class="hs-chart">
            <div class="chart-cap"><span>retained · 21d</span></div>
            ${areaLine(h.retained_trend, "var(--accent)", "var(--accent-soft)", 70)}
          </div>
          <div class="hs-chart">
            <div class="chart-cap"><span>advisory recall hits</span></div>
            ${barSeries(h.recall_trend, "var(--accent-2)", 70, 3)}
          </div>
        </div>`,
    });
  }

  function boundaryPanel(data) {
    const stTone = { blocked: "good", disabled: "good", gated: "accent", false: "good", enabled: "warn", true: "warn", warn: "warn" };
    return panel({
      kicker: "safety model",
      title: "边界守卫",
      sub: "default boundaries enforced",
      className: "span-5",
      right: pill("enforced", "good"),
      body: `
        <div class="bnd-grid">
          ${(data.boundary || []).map((g) => {
            const tone = stTone[g.state] || "good";
            return `
              <div class="bnd">
                ${dot(tone)}
                <span class="bnd-lbl">${esc(g.label)}</span>
                <span class="bnd-state bs-${tone}">${esc(g.state)}</span>
              </div>`;
          }).join("")}
        </div>`,
    });
  }

  function auditPanel(data) {
    return panel({
      kicker: "append-only",
      title: "审计流",
      sub: "recent state transitions",
      className: "span-7",
      body: `
        <div class="audit">
          ${(data.audit || []).map((a) => `
            <div class="audit-row">
              <span class="au-t mono dim">${esc(a.t)}</span>
              ${dot(a.tone)}
              <span class="au-actor mono">${esc(a.actor)}</span>
              <span class="au-action mono strong">${esc(a.action)}</span>
              <span class="au-detail">${esc(a.detail)}</span>
            </div>`).join("")}
        </div>`,
    });
  }

  function dashboard(data) {
    return `
      <div class="mos">
        ${headerBar(data)}
        <div class="grid">
          ${monitorHero(data)}
          ${ownerReviewPanel(data)}
          ${kpiStrip(data)}
          ${expressionPanel(data)}
          ${feedbackPanel(data)}
          ${proposalsPanel(data)}
          ${memoryPanel(data)}
          ${hindsightPanel(data)}
          ${boundaryPanel(data)}
          ${auditPanel(data)}
          ${cronPanel(data)}
          ${ownerQueueList(data)}
          ${modulesPanel(data)}
        </div>
        <footer class="mos-foot">
          <span>${esc(data.meta.product)} · ${esc(data.meta.version)} · ${esc(data.meta.monitor_build)}</span>
          <span class="mono dim">generated ${esc(data.meta.generated_at)} · ${esc(data.meta.hermes_home)}</span>
        </footer>
      </div>`;
  }

  function render() {
    const root = document.getElementById("root");
    if (!root) return;
    if (!window.MOS) {
      root.innerHTML = '<div class="dashboard-empty">Memory-OS dashboard snapshot missing.</div>';
      return;
    }
    root.innerHTML = dashboard(window.MOS);
  }

  const ready = window.MOS_DATA_READY || Promise.resolve();
  ready.then(() => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", render);
    } else {
      render();
    }
  });
}());
