# Memory-OS Quickstart

This is the shortest path for installing and verifying Memory-OS on an existing
Hermes profile.

## 1. Choose A Hermes Home

Use the Hermes profile you want Memory-OS to manage:

```bash
export HERMES_HOME=/root/.hermes
```

The installer can discover common homes, but setting `HERMES_HOME` keeps the
target explicit.

## 2. Install

One-command operational install for an existing Hermes profile:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --operational \
  --hindsight auto
```

This installs and enables the Memory-OS provider, the Hermes Agent OS shell,
the portable runtime, heartbeat, the current cognitive loop harness, and the
active-closure Hermes cron operational set. Owner-facing cron jobs use Hermes
`channel_directory.json` autodiscovery, so Telegram is selected only when it is
the configured owner channel. The default active-closure cron set contains
the owner review digest, proposal follow-up OpsGate, index sync, working
cleanup, L3 probe verification, candidate aggregation, fact judge, event
stats refresh, expression feedback, and memory sources feedback jobs.
Runtime heartbeat and the cognitive-loop timer own the main
sensing/projection/advisor loop.

Interactive install:

```bash
bash scripts/install_memory_os.sh
```

Use `--no-enable-owner-cron-onboarding` if you want helper scripts installed
but no recurring jobs. Hermes owns scheduled delivery, platform transport, and
final owner-facing wording in agent mode; Memory-OS only renders bounded briefs,
tokens, state transitions, audit, and monitor evidence.

Production-safe install:

```bash
HERMES_HOME=/root/.hermes bash scripts/install_memory_os.sh --yes --production-safe \
  --hindsight off
```

Hindsight adoption is explicit. Use `--hindsight off` for a fresh open-source
install. Use `--hindsight auto` when an existing Hermes profile already has a
Hindsight config and you want Memory-OS to adopt it into governed shadow mode,
or to preserve an already-active adoption for the same provider bank during
later upgrades. Use `--hindsight active` only for a controlled live cutover.
The direct Hermes `memory.provider=hindsight` path is not used by Memory-OS.
Hindsight, when enabled, is a Memory-OS governed substrate with raw-turn retain
disabled and recall kept advisory.

Automated deployment wrapper examples:

The wrapper defaults `--llm-judge-preset` to `active`, reusing the current
Hermes provider/model in bounded-vote mode and running a post-install judge
probe. Pass `--llm-judge-preset report-only` for report-only probes, or
`--llm-judge-preset none` when the target should keep the judge disabled.

```bash
# Fresh host, local execution on the target:
python scripts/deploy_memory_os.py \
  --hermes-home /root/.hermes \
  --profile fresh \
  --phase apply \
  --mode production-safe \
  --hindsight off

# Existing Hermes + Hindsight host, remote orchestration:
python scripts/deploy_memory_os.py \
  --host hermes-media \
  --remote-repo-root /opt/Hermes-Memory-OS \
  --hermes-home /root/.hermes \
  --profile upgrade \
  --phase dry-run \
  --mode operational \
  --hindsight auto
```

The installer does not restart `hermes-gateway.service`.

## 3. Optional Read-Only Monitor Dashboard

Memory-OS includes a read-only monitor dashboard on the open-source frontend
contract `0.0.0.0:3693`. The dashboard reads bounded snapshot evidence and has
no approve/apply/send controls.

Run locally:

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

Install as a system service:

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

## 4. Verify

```bash
HERMES_HOME=/root/.hermes hermes memory
HERMES_HOME=/root/.hermes hermes plugins list
HERMES_HOME=/root/.hermes hermes memory-os-agent-os status
HERMES_HOME=/root/.hermes hermes memory-os-agent-os doctor
HERMES_HOME=/root/.hermes hermes memory-os-agent-os modules status
```

Expected state:

```text
memory.provider = memory_os
memory-os-agent-os = enabled general plugin
memory_os = not enabled as a general plugin
doctor.status = ok
```

Current Hermes builds select Memory-OS through `memory.provider=memory_os`.
They do not need to expose `hermes memory_os ...` as a top-level command.

Optional repo/operator validation:

```bash
python scripts/memory_os_public_checkout_probe.py --source head --strict
python scripts/memory_os_public_checkout_probe.py --source working-tree --strict
python scripts/memory_os_cron_adapter_probe.py --host hermes-media --output json
python scripts/memory_os_boundary_runtime_probe.py --host hermes-media --output json
python scripts/memory_os_3_200_monitor.py --host hermes-media --monitor-profile live --output summary
```

Treat these as separate evidence levels. Fast probe PASS is not a substitute
for a full live monitor PASS.

## 5. What Gets Installed

- `memory_os` provider under `$HERMES_HOME/plugins/memory_os/`
- optional `memory-os-agent-os` shell plugin under
  `$HERMES_HOME/plugins/memory-os-agent-os/`
- optional portable module runtime under
  `$HERMES_HOME/memory-os/runtime/python/`
- optional heartbeat and cognitive-loop systemd user units under
  `$HERMES_HOME/memory-os/systemd/`
- optional Memory-OS Hermes cron onboarding under `$HERMES_HOME/scripts/`; the
  operational preset creates the active-closure cron set unless explicitly
  disabled

Backups belong under `$HERMES_HOME/plugin-backups/`, not under
`$HERMES_HOME/plugins/`.

### Cron Profile

The default cron profile is `active-closure` (10 jobs):

| Job | Purpose |
| --- | --- |
| `memory-os-owner-review-digest` | sends approval items and real alerts through the owner channel |
| `memory-os-proposal-followups-opsgate` | moves safe proposal follow-ups through OpsGate/report-only review |
| `memory-os-index-sync` | keeps SQLite FTS5 index in sync with canonical files |
| `memory-os-working-cleanup` | prunes expired working memory items |
| `memory-os-l3-probe-verification` | verifies L3 boundary probe integrity |
| `memory-os-candidate-aggregation` | aggregates candidate clusters |
| `memory-os-fact-judge` | reversible fact-judge lane for crystallized records |
| `memory-os-event-stats-refresh` | rebuilds O(1) event stats cache every 15 min |
| `memory-os-expression-feedback-request` | requests owner feedback on right-brain expressions |
| `memory-os-memory-sources-feedback-request` | requests owner feedback on memory source recall quality |

The full registry also contains optional jobs for right-brain expression,
module cadence reports, expression outcome capture, and owner feedback prompts.
They are intentionally not part of the default install. Enable them only when
that user-facing product surface is desired:

```bash
HERMES_HOME=/root/.hermes python scripts/install_memory_os_plugin.py \
  --run-owner-cron-onboarding \
  --owner-cron-owner-approved \
  --owner-cron-profile full
```

On upgraded hosts, active-closure onboarding pauses known optional Memory-OS
cron jobs instead of deleting them. Running the `full` profile restores the
optional cron surface when it is intentionally needed.

## 6. Safety Defaults

Memory-OS does not automatically send messages, execute external actions, write
identity, approve crystallized memory, export to Hindsight, apply cleanup, or
apply shadow journals.

The operational preset enables runtime loops and Hermes cron jobs, but it does
not enable direct Memory-OS sends, external execution, identity writes, or
unapproved crystallized approvals.

## 6. Owner Review Via Hermes Agent

Owner review digests use short display anchors such as `A1`, `R1`, and `F1` to
make the list readable. Those anchors are not durable approval identities.

The normal path is conversational: reply in the same Hermes channel where the
digest appears. Hermes interprets your intent, asks when ambiguous, and calls
Memory-OS with structured `memory_os_review_reply` arguments. Memory-OS does
not require a root shell command for owner approval.

Stable-token owner utterance examples:

```text
memory approve oa_<token>
memory reject oa_<token>
memory allow oa_<token>
memory feedback oa_<token> too_mechanistic
```

The corresponding agent tool call is structured, for example:

```yaml
tool: memory_os_review_reply
arguments:
  action: feedback
  action_token: oa_<token>
  rating: too_mechanistic
```

Hermes is the interactive agent. If you reply with natural phrasing such as
`approve A1`, Hermes may resolve `A1` from the current visible digest and call
the Memory-OS review tool with the matching stable `oa_` token. If the target
is not unambiguous, Hermes should ask you to clarify instead of guessing.

Memory-OS itself does not execute display anchors. `A1/R1/F1` are UI labels
only; the plugin/state-machine layer applies only stable `oa_` action tokens.

Owner approval is reserved for trust-boundary actions, not every workflow step.
Proposal follow-up routing is report-only process motion: it may move a proposal
into OpsGate review, but it does not execute work, write policy, mutate routing,
send messages, or write crystallized memory. The actual boundary action
(`apply_proposal`, crystallized write, revoke/demote/delete, route/score
authority, identity/relationship write, external send, or unbounded autonomous
acting) remains owner-gated unless that specific low-risk lane has been
explicitly graduated.

For `proposal_followup_auto_route`, `limited_auto` may be active and idle when
there are no currently eligible proposals. Graduation is based on real prior
bounded routes plus continuing boundary checks; an empty current queue must not
be filled with synthetic proposal samples just to produce activity.

Shell/CLI paths are operator/debug fallbacks only. They are not the owner-facing
approval workflow.

For SessionMirror, the approval is a lane-graduation decision. Once the owner
approves the `approve_session_mirror_apply` item from the owner-home digest,
Memory-OS can let heartbeat auto-import one bounded session per run inside the
approved platform allowlist. This reduces repeat approvals while keeping the
hard boundary intact: the lane does not write crystallized memory, mutate
policy, change route/score authority, write identity/relationships, or send
external messages.
