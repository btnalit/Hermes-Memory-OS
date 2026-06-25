# Hermes Memory-OS

Hermes Memory-OS is a file-first memory and governance runtime for long-running
Hermes agents.

It gives a Hermes profile durable memory, bounded cognition modules, owner
review, right-brain expression feedback, and operational monitor evidence
without making Memory-OS the owner of conversation, transport, or scheduling.
Hermes remains the host agent. Memory-OS provides bounded state, stable action
tokens, helper scripts, audit, and monitor evidence.

## What This Project Is

Memory-OS is for operators who want an inspectable memory substrate for Hermes:

- profile-local canonical files instead of opaque hosted storage;
- rebuildable SQLite indexes for search and prefetch;
- hybrid retrieval: FTS5 full-text search, vector similarity via local embeddings,
  and graph-layer edge traversal — composable, knob-gated, and degradable to
  pure FTS5;
- working memory separated from owner-approved crystallized memory;
- attribution and feedback ledgers for memory-source quality;
- owner-visible approval and feedback loops through Hermes;
- module cadence, proposal follow-up, and right-brain expression evidence;
- safe bounded apply paths for explicitly supported proposal kinds.

It is not a standalone chat server, a SaaS memory service, or a generic
executor. External sends, user conversation, cron delivery, channel selection,
origin/local routing, and natural-language interaction belong to Hermes.

## Quick Start

Install into an existing Hermes profile:

```bash
git clone <this-repo-url>
cd Hermes-Memory-OS
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational \
  --hindsight auto
```

`--operational` is the normal open-source install path. It installs and enables:

- the `memory_os` Hermes memory provider;
- the `memory-os-agent-os` Hermes shell plugin;
- portable Memory-OS runtime modules (including `deep_reflection` and `speak_gate`, both default-enabled);
- heartbeat runtime;
- the cognitive-loop integration harness (default-enabled per D1);
- active-closure Hermes cron onboarding (9 jobs: owner review digest, proposal
  follow-up, index sync, working cleanup, L3 probe, candidate aggregation,
  fact judge, expression feedback, memory sources feedback).

The installer auto-detects the owner-facing Hermes channel from
`$HERMES_HOME/channel_directory.json`. Telegram is used only when Telegram is
the configured owner channel. Other installs can resolve to Discord, Signal,
Slack, Matrix, or another configured platform. Background jobs use
`deliver=local` with no agent where appropriate; right-brain expression uses
Hermes `deliver=origin`.

Hindsight is optional and governed by Memory-OS, not by selecting Hermes'
direct `memory.provider=hindsight` path. `--hindsight auto` adopts a new
Hermes Hindsight config into Memory-OS shadow mode, preserves an already-active
Memory-OS Hindsight adoption for the same provider bank, and stays disabled on
a fresh profile with no Hindsight config. Use `--hindsight active` only for a
controlled live cutover where retain, advisory active recall, and reflect
candidate generation should all be enabled.

Interactive install is also available:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh
```

Conservative install with the same core defaults but non-interactive:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe \
  --hindsight off
```

`--production-safe` uses the same core defaults as `--operational` (all three
core components enabled: heartbeat, cognitive_loop, index-sync onboarding) but
is non-interactive. Use `--no-enable-*` flags to selectively disable components.

Install helpers but do not enable recurring cron jobs:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational \
  --no-enable-owner-cron-onboarding
```

The installer does not restart `hermes-gateway.service`.

For automated host rollout, use the deployment wrapper in phases. `plan`,
`preflight`, and `dry-run` are safe gates; `apply` writes installer changes and
still does not restart Hermes unless `--allow-restart` and an explicit restart
command are provided. Automated installs default `--llm-judge-preset` to
`active`, which reuses the current Hermes provider/model in bounded-vote mode
and is checked by a post-install low-clue judge probe. Use
`--llm-judge-preset report-only` for report-only probes, or
`--llm-judge-preset none` to keep the LLM judge disabled.

```bash
# Fresh open-source profile, local execution on the target.
python scripts/deploy_memory_os.py \
  --hermes-home /root/.hermes \
  --profile fresh \
  --phase apply \
  --mode production-safe \
  --hindsight off

# Existing Hermes + Hindsight profile, remote dry-run before apply.
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

## What Gets Scheduled

The installer defaults to the `active-closure` Hermes cron profile (9 jobs).
These are the jobs required for the full automatic governance closure loop:

| Job | Deliver | Agent | Purpose |
| --- | --- | --- | --- |
| `memory-os-owner-review-digest` | owner channel | yes | sends approval items and real alerts to the owner |
| `memory-os-proposal-followups-opsgate` | `local` | no | routes approved proposals through OpsGate/report-only follow-up |
| `memory-os-index-sync` | `local` | no | keeps the SQLite search index in sync with canonical files |
| `memory-os-working-cleanup` | `local` | no | expires aged working-memory items |
| `memory-os-l3-probe-verification` | `local` | no | verifies L3 code provenance and module integrity |
| `memory-os-candidate-aggregation` | `local` | no | clusters related working-memory events into reviewable candidates |
| `memory-os-fact-judge` | `local` | no | durable-fact LLM judge for candidate quality screening |
| `memory-os-expression-feedback-request` | owner channel | yes | asks owner for tokenized right-brain expression quality ratings |
| `memory-os-memory-sources-feedback-request` | owner channel | yes | asks owner for tokenized memory recall quality ratings |

The `full` cron profile adds 3 optional expression/cadence jobs on top of
active-closure:

| Job | Deliver | Agent | Purpose |
| --- | --- | --- | --- |
| `memory-os-right-brain-expression` | `origin` | yes | low-frequency right-brain expression through Hermes |
| `memory-os-module-cadence-report` | `local` | no | records module generated/skipped/error/duplicate counters |
| `memory-os-right-brain-expression-outcome` | `local` | no | records expression outcomes for feedback linkage |

Switch to the full profile:

```bash
HERMES_HOME=/root/.hermes python scripts/install_memory_os_plugin.py \
  --run-owner-cron-onboarding \
  --owner-cron-owner-approved \
  --owner-cron-profile full
```

Hermes owns the scheduler, transport, retry behavior, origin/local routing, and
agent wording. Memory-OS owns the helper outputs, tokens, state transitions,
audit, and monitor fields.

On upgraded hosts, active-closure onboarding pauses legacy optional Memory-OS
cron jobs that are known in the registry but no longer part of the active
profile. They are not deleted, and they can be restored by explicitly running
the `full` cron profile. The monitor classifies paused optional jobs as known
optional rather than unregistered drift.

## Read-Only Monitor Dashboard

The repository includes a static monitor dashboard on the open-source frontend
contract `0.0.0.0:3693`. It is a presentation surface only: it reads bounded
snapshot evidence and has no approve/apply/send controls.

Generate and serve a live snapshot:

```bash
python scripts/memory_os_monitor_dashboard_snapshot.py \
  --hermes-home /root/.hermes \
  --profile main \
  --output monitor_dashboard/snapshot.generated.js

python scripts/serve_memory_os_monitor_dashboard.py \
  --host 0.0.0.0 \
  --port 3693 \
  --snapshot-hermes-home /root/.hermes \
  --snapshot-profile main \
  --snapshot-interval-seconds 60
```

Install it as a system service:

```bash
sudo python scripts/install_memory_os_monitor_dashboard_service.py \
  --repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile main \
  --host 0.0.0.0 \
  --port 3693 \
  --python-bin /usr/bin/python3 \
  --enable
```

## Verify

After install:

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status
```

Expected relationship:

```text
memory.provider = memory_os
plugins.enabled includes memory-os-agent-os
plugins.enabled does not include memory_os
```

`memory_os` is selected through `memory.provider`. It should not be enabled as a
general Hermes plugin.

Useful operator checks:

```bash
HERMES_HOME=/root/.hermes hermes memory-os-agent-os memory-sources stats --hours 24
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules validate-no-send
python scripts/memory_os_cron_adapter_probe.py --host hermes-media --output json
python scripts/memory_os_boundary_runtime_probe.py --host hermes-media --output json
python scripts/memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
```

## Owner Interaction

Owner review and feedback happen in the normal Hermes conversation channel. The
owner should not need a root shell to approve Memory-OS items.

Digest labels such as `A1`, `R1`, and `F1` are display-only list numbers. The
durable identity is the printed `oa_` action token.

Examples of owner utterances:

```text
memory approve oa_<token>
memory reject oa_<token>
memory apply oa_<token>
memory feedback oa_<token> too_mechanistic
memory feedback oa_<token> like_expression
```

Hermes interprets the owner utterance, asks follow-up questions when ambiguous,
and calls the structured Memory-OS review tool. Memory-OS applies only stable
tokens through the owner action state machine.

Approving a proposal does not execute work. It moves the proposal into
human-controlled follow-up. Only proposal kinds with a bounded runtime target,
rollback, monitor fields, and an explicit apply token can be applied.

## Safety Model

Memory-OS keeps these boundaries by default:

- no direct platform sends from Memory-OS;
- no external execution;
- no identity writes without explicit owner-approved path;
- no unapproved crystallized memory writes;
- no ungoverned Hindsight export or raw-turn retain;
- no cleanup or shadow-journal apply without a separate gate;
- source gate (deterministic fragment detection) at the candidate-entry boundary:
  process fragments blocked, user knowledge preserved — fail-safe by default
  (ambiguous cases pass through to downstream gates).

Canonical data lives under the Hermes profile. SQLite indexes are rebuildable.
Review, feedback, and apply operations are audited.

Optional Hindsight support is a derived projection from governed canonical
memory. It can retain only crystallized, owner-approved, or explicitly distilled
records, tracks retain/retract in an append-only projection ledger, and returns
recall facts as advisory `derived_projection` evidence. Local canonical
artifacts remain the primary authority.

## Install-Time Environment Checks

The installer automatically detects and adapts to the host environment:

**LLM package auto-install.** When `--install-system-modules` is used, the
installer checks whether `openai` and `anthropic` Python packages are
importable. If either is missing, it auto-installs it via `pip`. On dry-run
mode the installer reports `would_install` without making changes. If
auto-install fails (network, permissions), a warning is printed to stderr and
the install report records `install_failed` per package so the operator can
follow up.

**Embedder package auto-install.** The installer checks whether
`sentence-transformers` is importable. If missing, it attempts `pip install
sentence-transformers` (~420MB download, `paraphrase-multilingual-MiniLM-L12-v2`
model). The model is downloaded once on first use. If the install or model
download fails, the installer prints a clear warning and records
`embedder_package: install_failed` in the report — the vector retrieval lane
stays at pure FTS5 (the deterministic floor). Vector retrieval and vector edge
proposer are both knob-gated (default off) and are safe to leave disabled on
disk-constrained or air-gapped hosts.

**systemctl availability guard.** When `--enable-runtime` or
`--enable-cognitive-loop` is requested, the installer probes `systemctl --user`
before attempting `daemon-reload` or `enable --now`. If systemctl is
unreachable, the systemd steps are skipped gracefully (files are still copied),
a notice is printed to stderr, and the install report records
`start_method: systemctl_unavailable_skipped`. On such hosts Hermes agent
falls back to cron-based heartbeat scheduling.

**Cron registry snapshot.** Every `--install-system-modules` run regenerates
the `memory_os_cron_registry.json` snapshot from the current `cron_registry.py`.
This ensures newly-added cron lanes (such as `fact_judge`) are visible to the
gate runner after an update install, without requiring a full cron onboarding
re-run.

Environment adaptation checks (LLM packages, embedder, systemctl availability)
are non-fatal — the install completes and the report carries enough detail for
follow-up. **Post-install core component verification (D2) is fatal by default:**
if heartbeat or cognitive-loop timers are not active after install, the script
exits non-zero with a boxed failure summary. Use `--skip-verify` to bypass.

## Architecture

```text
Hermes agent
  owns conversation, LLM interaction, cron, delivery, origin/local routing,
  clarification, transport, retry, and channel adapters

Memory-OS provider
  owns profile-local canonical memory, indexes, prefetch, sync_turn,
  working memory, crystallized candidates, and audit

Memory-OS inner drive (source gate)
  deterministic fragment detection at conversation-turn boundary —
  process fragments blocked, user knowledge preserved with user-segment primacy
  → passive trust auto-promotion: surviving provisional records graduate to
    permanent memory after the owner review window

Memory-OS retrieval (prefetch)
  FTS5 full-text search (deterministic floor)
  → vector similarity via local sentence-transformers embedder (optional,
    knob-gated; degrades to FTS5 when unavailable)
  → graph-layer edge traversal from search anchors (optional, knob-gated)
  → Reciprocal Rank Fusion union over all active lanes

Memory-OS edge proposers
  structural (deterministic heuristics), LLM (Hermes runtime), and vector
  (cosine similarity over embeddings) — three independent edge sources
  feeding the graph layer

Memory-OS substrate providers
  optionally expose governed derived projections such as Hindsight, with
  LocalArtifact as primary authority and external facts always advisory

Memory-OS Agent OS shell
  exposes operator status, doctor, module, feedback, and review tools

Portable modules
  produce bounded artifacts: evidence scores, proposals, expression drafts,
  cadence reports, feedback signals, and OpsGate reports
  (deep_reflection and speak_gate are default-enabled)

OwnerActionProcessor
  is the state-changing entry point for approve, reject, feedback, allow,
  and bounded apply actions
```

## Repository Layout

```text
memory_os_agent/               Minimal Hermes compatibility surface
plugins/memory/memory_os/      Memory-OS provider and core services
  ├── inner_drive.py           Source gate: deterministic fragment detection,
  │                            passive trust auto-promotion
  ├── crystallized.py          Owner-approved canonical memory, candidate triage
  ├── embedder.py              Local sentence-transformers embedder (CPU, ~420MB)
  ├── index.py                 SQLite index, FTS5 search, vector search
  ├── prefetch.py              Context assembly: FTS5 + vector + graph lanes,
  │                            deterministic recall floor
  ├── structural_edge_proposer.py  Deterministic edge heuristics
  ├── llm_edge_proposer.py     LLM-class edge proposer (Hermes runtime)
  └── vector_edge_proposer.py  Embedding-similarity edge proposer
plugins/memory-os-agent-os/    Hermes shell plugin and review tools
plugins/system/                Module contracts and coordination primitives
plugins/modules/               Portable cognition/governance/expression modules
scripts/                       Installer, monitor, cron helpers, validation
tests/                         Provider, module, installer, and monitor tests
docs/                          Public operator docs
```

Normal users should start with [docs/quickstart.md](docs/quickstart.md) and
[docs/configuration.md](docs/configuration.md). Internal development notes and
validation history are intentionally excluded from the public upload.

## Development

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the main test suite:

```bash
python -m pytest -q
```

Run a single test:

```bash
python -m pytest -q tests/plugins/memory/test_memory_os_owner_actions.py
python -m pytest -q -k "test_approve_candidate"
```

Installer and closure checks:

```bash
python -m pytest tests/scripts/test_memory_os_plugin_install.py \
  tests/scripts/test_memory_os_owner_cron_onboarding.py -q
python scripts/memory_os_public_checkout_probe.py --source head --strict
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
git diff --check
```

Static analysis (run before committing):

```bash
python scripts/memory_os_import_cycle_check.py --repo-root .
python scripts/memory_os_write_surface_check.py
python scripts/memory_os_static_hygiene_check.py
git diff --check
```

Before changing scheduler, owner review, feedback, installer, module closure,
or live monitor behavior, verify the owning interface and run the relevant
checks. Internal closure-matrix documents are not part of the public upload.
Do not rely on conversation history as the source of truth.

## Current Maturity

The operational baseline has live validation evidence:

- operational installer path completed;
- active-closure Hermes cron profile (9 jobs) present and verified;
- deployment core guarantee (D1/D2): cognitive_loop default-on, post-install
  core component verification fail-loud;
- source gate (F.2): deterministic fragment detection prevents conversation
  noise from entering the candidate queue — process fragments blocked, user
  knowledge preserved with user-segment primacy;
- passive trust auto-promotion (F.3): provisional records that survive the
  owner review window are automatically promoted to permanent memory;
- fast cron and boundary/runtime probes available for lightweight
  deploy/audit checks before the full monitor, wired into
  `deploy_memory_os.py` postcheck/apply sequencing;
- neutral monitor entrypoint `scripts/memory_os_monitor.py` is available, while
  `scripts/memory_os_3_200_monitor.py` remains the compatibility entrypoint;
- deterministic recall floor (v4): when FTS5 and vector return zero hits,
  Unicode-boundary floor matching + permanent baseline keeps core memory
  accessible;
- owner channel auto-detected from `channel_directory.json`;
- current 3.200 full monitor status is PASS with `WARN=[]`, `FAIL=[]`, and
  `evidence_labels=['live_monitor_pass']`; the index catch-up contract now
  enforces `event_backlog <= max_event_backlog` and a hard 900 second age cap
  that remote `max_age_seconds` cannot widen; owner-boundary proposal auto-route
  stops are visible as guard evidence rather than production WARN;
- owner-approved crystallized memory, feedback ledger, proposal follow-up, and
  bounded expression policy apply have live evidence.

Full test suite: 1584 passed, 0 failed, 3 skipped. Static checks (write surface,
import cycle, static hygiene) all pass.

This does not mean Memory-OS is a generic autonomous executor. New proposal
kinds require their own bounded apply contract, rollback, monitor fields, and
owner-visible workflow.

## License

MIT License. See [LICENSE](LICENSE).
