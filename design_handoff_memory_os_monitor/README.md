# Handoff: Hermes Memory-OS — 全方位监测前端 (Monitoring Dashboard)

## Overview
这是一个面向运维/SRE 的 **只读监测仪表盘**,用于观测 Hermes Memory-OS 运行时的全方位健康信号:整体 monitor PASS/WARN/FAIL 状态、7 个 Hermes cron 作业、owner 审批队列、记忆分层、18 个模块的 cadence 计数、right-brain 表达反馈、proposal/OpsGate 跟进、Hindsight 投影账本、反馈账本与安全边界。

设计是 **non-interactive(纯数据呈现)**:没有业务操作交互,只有信息展示 + 自动刷新。定稿采用深色 NOC 大屏风格(代号 **Control Room / theme B**)。

## About the Design Files
本包内的 HTML/CSS/JSX 是 **设计参考稿(用 HTML 做的高保真原型)**,不是要直接照搬上线的生产代码。任务是:**在目标代码库的既有技术栈里(React / Vue / Svelte 等)按既有工程规范重建这套设计**;若项目尚无前端,可自行选择最合适的框架实现。

原型用 React 18 + Babel(浏览器内转译)+ 内联 SVG 图表 + CSS 变量主题化。生产实现应:
- 用项目既有的图表库(如 visx / Recharts / ECharts / D3)替换手写 SVG,或保留轻量 SVG 方案;
- 用项目既有的设计令牌系统承载下方 Design Tokens;
- 把示意数据(`mos-data.js` 里的 `window.MOS`)替换为真实数据源(见每个面板的 **数据来源** 映射)。

## Fidelity
**High-fidelity(高保真)**。颜色、排版、间距、栅格、图表样式均为最终值,请按下方 Design Tokens 与各面板规格 **像素级重建**。深色主题为定稿;浅色(Clarity)与暖白(Paper Terminal)两套主题在 `Hermes Memory-OS — 3-Style Explorations.html` 中,可作为可选主题令牌参考,非必须实现。

---

## 技术上下文:这是在监测什么
Memory-OS 是 Hermes agent 的 file-first 记忆与治理运行时。仪表盘消费的是它产出的 **bounded 证据文件 / CLI 输出**,关键产物:

| 信号 | 真实来源(仓库) |
| --- | --- |
| 整体 monitor 状态 | `scripts/memory_os_3_200_monitor.py` 输出;`status ∈ {PASS,WARN,FAIL}` |
| 模块 cadence | `scripts/memory_os_module_cadence_report.py` → `system-modules/module_cadence/reports.jsonl`,schema `memory-os.module_cadence_report.v0` |
| 7 个 cron 作业 | `$HERMES_HOME/cron/jobs.json`(name/schedule/deliver/enabled) |
| owner 审批 | `hermes memory-os-agent-os review preview-digest --owner <o> --mode agenda`(counts: action_required_shown / review_suggested_shown / fyi_shown);稳定 token = `oa_…` |
| 记忆分层 | provider 状态 + 可重建的 SQLite FTS 索引 |
| right-brain 表达 | `system-modules/{wandering_mind,expression_draft,speak_gate,right_brain_expression_adapter}/*.jsonl` |
| proposal / OpsGate | `system-modules/{self_evolution,ops_gate}/reports.jsonl` |
| Hindsight | governed derived projection,append-only ledger,recall = advisory |
| 安全边界 | cadence report 的 `boundary{}` 对象 + README 安全模型 |

> 重要语义(必须在 UI 文案里保留):approve ≠ execute;`A1/R1/F1` 只是显示锚点,稳定身份是 `oa_` token;Hindsight recall 始终是 advisory/derived_projection。

---

## Screens / Views
单屏(single scrollable view),12 列栅格,自上而下堆叠。容器 `max-width: 1820px` 居中,深色背景填满视口。

布局顺序与列宽(12 列):
1. **Top bar**(整宽)
2. **Monitor 健康总览** `span-8` + **Owner 审批队列** `span-4`
3. **KPI 条** `span-12`(6 个 tile)
4. **Cron 作业表** `span-8` + **反馈账本** `span-4`
5. **待办明细表** `span-8` + **表达表现** `span-4`
6. **记忆分层** `span-7` + **Proposal 跟进** `span-5`
7. **模块 cadence** `span-12`
8. **Hindsight 投影账本** `span-7` + **边界守卫** `span-5`
9. **审计流** `span-12`
10. **Footer**(整宽)

### 通用面板(Panel)结构
卡片:`background var(--surface)` · `1px solid var(--border)` · `border-radius var(--radius)` · `box-shadow var(--shadow)` · `overflow hidden`。
- Header:`padding 13px 18px`,底部 `1px solid var(--border)`,`background var(--surface-2)`。含 **kicker**(9.5px mono 大写 letter-spacing .13em,色 `var(--accent)`)、**标题 h3**(IBM Plex Sans 14.5px/600,色 `var(--text-strong)`)、可选 **sub**(10.5px mono,色 `var(--muted)`),右侧放 Pill。
- Body:`padding 18px`。

### 1. Top bar
三栏 grid(`auto 1fr auto`)。左:品牌方块(30px,圆角 radius-sm,`linear-gradient(135deg, var(--accent), var(--accent-2))`,内嵌 8px inset 的白色圆环 2px)+ 产品名 `Hermes · Memory-OS`(Sans 15/700)+ 子行 `memory_os · memory-os-agent-os · operational`(mono 10.5 muted)。中:`profile / host·env / hindsight / uptime` 键值对(mono 11,标签 9.5 muted 大写)。右:**状态块** = 大状态 Pill(`monitor PASS`,圆角 999,字 13/700 大写,色 = 状态色,底 = 状态色 14% 混入)+ 发光 LED 圆点(8px,`box-shadow var(--led-glow) currentColor`)+ 子行 `304/312 checks · 8 warn · 0 fail`;再右 **run 块**(左边框分隔)`run_id` 与 `last/next`。左上角浮一个 **theme-chip**(`Control Room`,绝对定位 top:-9px)。

### 2. Monitor 健康总览(核心信号)
两栏(`minmax(220,280px) 1fr`)。
- 左:**半环 Gauge**(见 Charts),圆心叠 `gauge-center`:状态字(mono 13/700)、大百分比 `97%`(mono 34/700,`var(--text-strong)`)、`312 checks · 18.4s`(mono 10 muted);下方图例三点 pass/warn/fail。
- 右:**子系统 roll-up** 列表(8 行),每行 = 点 + 中文标签 + key(mono dim)+ checks 数 + flag(`ok` / `n W` / `n F`,色随状态)。奇数行 `var(--surface-2)` 斑马纹。
- 底部:**21 天状态条** —— 21 个等宽格子,`hist-good`=pass 色 55% 混 surface、`hist-warn`、`hist-fail`,高 22px。

### 3. KPI 条
6 个 tile(`repeat(6,1fr)`)。每个:标签(11 muted)+ delta(mono 10.5,涨绿跌红、`good:"down"` 的指标反向判定)、大数值(mono 26/700 tabular-nums)+ 单位(11 muted)、底部 **Sparkline**(150×30,描边 `var(--accent)`,填充 `var(--accent-soft)`)。
KPI:working memory / crystallized / 待 owner 审批 / cron 健康(/7)/ 活跃模块(/18)/ Hindsight 记录。

### 4. Cron 作业表
表格列:`job(去 memory-os- 前缀,mono strong)| deliver | agent(agent→accent pill / local→muted pill)| schedule | last | next | ms(右对齐)| status(点+文字)`。7 行,全 ok。

### 5. 待办明细(owner 队列)
表格列:`#(锚点 A1/R1/F1,mono 700 accent)| oa_ token(mono strong)| kind | surface | age | severity(pill:action_required→fail / review_suggested→warn / fyi→muted)| note(muted)`。

### 6. 记忆分层
顶部 6 个 stat(左边框 2px accent:working / crystallized / candidates / canonical files / sqlite index MB / fts rows)。下方两栏:左 = working memory 21天 **AreaLine**;右 = crystallized 分类水平条(track + accent-N 填充)。

### 7. 模块 cadence(整宽,18 行)
左栏(280px):**聚合 StackBar**(generated=accent / skipped=track-2 / error=fail / duplicate=warn)+ 图例(带数值)+ meta(harness members / cron missing / coverage)。
右栏:紧凑表 `module | runner | cadence class | run | gen | skip | err | dup | last | split`,数值右对齐 tabular,err>0 行整行 `var(--fail) 7%` 底色,err/dup 非零时着色,`split` 列 pending→warn pill。

### 8. right-brain 表达表现
4 个 stat(drafts / would_send / [SILENT] / sent)+ **表达 cadence 21天 BarSeries** + **owner feedback tags** 水平条(like_expression/resonant→good,neutral→muted,too_mechanistic/off_tone→warn)。

### 9. Proposal 跟进
5 个状态卡(左色条 + 数值 + label:pending_followup→warn,in_opsgate_review→accent,report_only→muted,applied→good,rejected→fail)+ **apply lanes** 列表(lane 名 / 描述 / count / graduated→good 或 gated→muted pill),旁注 `approve ≠ execute`。

### 10. Hindsight 投影账本
右上 mode pill(`shadow`)。4 个 stat(左边框 accent-2:retained/retracted/ledger entries/recall hits)+ 两条 flag(`raw_turn_retain false`、retain source)+ 两图(retained 21天 AreaLine、recall hits BarSeries 用 accent-2)。

### 11. 反馈账本
两个 ledger 卡(MemorySources / Expression,各 prompts/responses/质量百分比,质量值绿色)+ **feedback quality 21天 AreaLine**(accent-2,baseline 0.5)。

### 12. 边界守卫
9 行边界(点 + 标签 + 状态 chip)。状态:blocked/disabled/false→good 绿,gated→accent。奇数行斑马纹。

### 13. 审计流(整宽)
等宽行:`时间 | 点 | actor(accent)| action(mono strong)| detail(muted)`,8 条,底部分隔线。tone 决定点色。

### Footer
两端对齐:左产品+版本,右 `generated <ts> · <hermes_home>`(mono muted)。

---

## Interactions & Behavior
设计本体 **非交互**。生产环境唯一需要的"行为"是 **数据刷新**:
- 轮询/订阅各数据源(monitor 每 ~30min、cadence `*/30`、cron 状态实时、owner 队列按需);建议前端定时拉取或 SSE/websocket。
- 状态色与 LED 发光随 `status` 变化(PASS 绿 / WARN 琥珀 / FAIL 红)。
- 数值用 `toLocaleString()` 千分位 + `font-variant-numeric: tabular-nums`。
- 表格行 hover → `var(--surface-2)`(纯视觉,可保留)。
- 无动画硬需求;若加,仅做进入淡入,避免装饰性循环动画。
- 响应式断点(已在定稿 HTML 内联):`≤1280px` KPI 转 3 列、span-7/8→12、span-4/5→6;`≤760px` 全部单列、KPI 2 列。

## State Management
只读视图,状态 = 后端数据快照。建议:
- 一个顶层 `monitorSnapshot` 对象(形状见下方 Data Schema),由 data-fetching 层填充;
- 每个面板是纯函数组件,`props` 取快照切片;
- `lastUpdated` / `loading` / `error` 三态用于刷新指示与降级(数据缺失时面板显示空态而非崩溃)。

## Design Tokens(定稿 = Control Room 深色)
颜色用 **oklch**;状态色独立于品牌强调色。

```
/* 背景 / 表面 */
--bg:            oklch(0.165 0.012 252)   /* 页面底,近黑冷调 */
--bg-2:          oklch(0.195 0.013 252)
--surface:       oklch(0.208 0.014 252)   /* 卡片 */
--surface-2:     oklch(0.245 0.015 252)   /* 表头/斑马 */
--border:        oklch(0.315 0.016 252)
--border-strong: oklch(0.40  0.02  252)

/* 文本 */
--text:          oklch(0.92 0.012 220)
--text-strong:   oklch(0.97 0.01  220)
--muted:         oklch(0.66 0.018 230)
--dim:           oklch(0.55 0.016 240)

/* 品牌强调(绿)+ 次强调(蓝)*/
--accent:        oklch(0.82 0.16 162)
--accent-2:      oklch(0.80 0.12 218)
--accent-soft:   oklch(0.82 0.16 162 / 0.16)
/* 分类调色板 accent-0..4: 162 / 140 / 188 / 212 / 120 hue,L≈0.82 C≈0.15 */

/* 状态色(语义,独立保留)*/
--pass:          oklch(0.80 0.16 162)   /* 绿 */
--warn:          oklch(0.82 0.14 82)    /* 琥珀 */
--fail:          oklch(0.68 0.18 25)    /* 红 */

/* 图表轨道/网格 */
--track:   oklch(0.285 0.015 252)
--track-2: oklch(0.34  0.016 252)
--grid:    oklch(0.30  0.014 252)

/* 排版 */
--sans: "IBM Plex Sans"  → 标题/品牌名
--mono: "IBM Plex Mono"  → 数据/标签/表格(主字体,终端感)
权重: 400/500/600/700

/* 形状 / 间距 / 阴影 */
--radius: 6px   --radius-sm: 4px
--gap: 13px   --pad: 14px(面板内)/ 卡 padding 18px
--fs: 12px(基准)
--shadow: 0 0 0 1px rgba(0,0,0,.25), 0 10px 28px rgba(0,0,0,.38)
--led-glow: 0 0 8px(状态点/LED 的辉光,深色专属)
```

排版尺度(px):大数值 26–34/700 mono;面板标题 14.5/600 sans;正文/表格 11–12;kicker/标签 9.5–10 mono 大写 letter-spacing .06–.13em;tabular-nums 全程开启。

间距尺度:4 / 6 / 8 / 10 / 13(gap)/ 14(pad)/ 16 / 18 / 22。

圆角:pill = 999px;卡 = 6px;小元素 = 4px。

## Data Schema(把 `window.MOS` 换成真实数据)
原型数据见 `mos-data.js`,顶层 `window.MOS` 形状(键名对齐真实字段):
```
meta{ product, profile, hermes_home, provider, shell_plugin, install_mode,
      hindsight_mode, host, environment, version, monitor_build, owner_channel,
      generated_at, uptime }
monitor{ status:'PASS'|'WARN'|'FAIL', run_id, schema, checks_total, pass, warn, fail,
         duration_ms, last_run_ago, next_run_in,
         sections:[{key,label,checks,warn,fail}],   // 8 个子系统
         history:[0|1|2 ×21], checks_trend:[…] }
kpis:[{ key,label,unit,value,delta,dir:'up'|'down'|'flat', good?, spark:[…] }]
cron{ enabled, total, jobs:[{name,deliver,agent,schedule,last,last_ms,next,status,out}] }  // 7
ownerReview{ mode, counts{action_required_shown,review_suggested_shown,fyi_shown},
             states{pending,approved,applied,rejected,allowed},
             queue:[{anchor,token,kind,surface,age,sev,state,note}], throughput:[…] }
memory{ working,crystallized,candidates,canonical_files,index_mb,index_fresh,
        index_rebuilt,fts_rows, working_trend:[…], crystallized_trend:[…],
        classes:[{label,value}] }
modules{ status, module_count, integration_harness_member_count,
         split_recommended_count, expected_hermes_cron_missing_count, finding_count,
         totals{generated_count,skipped_count,error_count,duplicate_count,counter_coverage_count},
         rows:[{module,runner,cadence,run,gen,skip,err,dup,last,split}],  // 18
         findings:[{code,module,severity}] }
expression{ drafts,would_send,silent,sent,outcomes_recorded, cadence_trend:[…],
            feedback:[{tag,value,tone}] }
proposals{ states:[{label,value,tone}], lanes:[{lane,desc,count,graduated}] }
hindsight{ mode,retain_source,raw_turn_retain,recall,retained,retracted,
           ledger_entries,advisory_recall_hits, retained_trend:[…], recall_trend:[…] }
feedback{ memory_sources{prompts,responses,attribution_quality},
          expression{prompts,responses,satisfaction}, quality_trend:[…] }
boundary:[{key,label,state:'blocked'|'disabled'|'gated'|'false'}]   // 9
audit:[{t,actor,action,detail,tone}]
```

## Charts(规格,见 `mos-charts.jsx`)
全部纯 SVG、由数据确定、用 CSS 变量取色(stroke/fill 可直接写 `var(--accent)`,因 SVG 在主题作用域内)。生产可保留或换库,但需复刻外观:
- **Sparkline** — 极简折线 + 可选面积填充;KPI 用。
- **AreaLine** — 折线 + 面积 + 3 条虚线网格(`var(--grid)` dash 2 4);趋势用。
- **BarSeries** — 等宽柱,圆角 1.5,gap 可调。
- **StackBar** — 单行水平堆叠分段(模块聚合计数)。
- **Donut** — 环形,可选圆心数值/标签(owner 状态分布)。
- **Gauge** — 上半圆三段弧(pass/warn/fail),轨道 `var(--track)`;monitor 核心。

## Assets
无外部图片。品牌方块为 CSS 渐变 + 内嵌圆环(纯 CSS,可换成真实 logo)。字体经 Google Fonts 加载 IBM Plex Sans / IBM Plex Mono(生产请自托管)。图标极少,均可用现成图标库替代;占位图一律不需要。

## Files(本包内)
- `Hermes Memory-OS Monitor.html` — **定稿**:单屏 Control Room 深色大屏(直接挂载、响应式)。入口。
- `mos.css` — 全部样式 + 三套主题令牌(`.theme-control` 为定稿;`.theme-clarity`/`.theme-paper` 可选)。
- `mos-data.js` — `window.MOS` 示意数据(**替换为真实数据源**)。
- `mos-charts.jsx` — 6 个 SVG 图表组件。
- `mos-dashboard.jsx` — 13 个面板 + 组合 `Dashboard`。
- `Hermes Memory-OS — 3-Style Explorations.html` — 三风格并排对比(浅色/深色/暖白),作为可选主题参考。
- `design-canvas.jsx` — 仅对比版用到的画布脚手架(生产不需要)。

> 实现建议:先按 Data Schema 定义类型 → 搭 13 个纯组件(对照各面板规格)→ 接真实数据源 → 用项目图表库复刻 6 类图表 → 套用 Design Tokens 主题。文案中英混排请保留(标签中文、术语英文)。
