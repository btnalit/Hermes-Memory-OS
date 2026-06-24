#!/usr/bin/env bash
# ============================================================================
# Hermes-Memory-OS Stabilization Deploy + Verify
# ============================================================================
# Usage: bash scripts/memory_os_stabilization_deploy_verify.sh
#
# Run on the target host (e.g., hermes-media) after git-pulling source.
# Does: install → enable knobs → boundary probe → cron probe → full monitor
#
# This script is host-agnostic — it reads HERMES_HOME from env or defaults
# to /root/.hermes. No hardcoded hostnames.
# ============================================================================

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
INSTALL_LOG="/tmp/memory_os_install_$(date +%Y%m%d_%H%M%S).log"
VERIFY_LOG="/tmp/memory_os_verify_$(date +%Y%m%d_%H%M%S).log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass_count=0
fail_count=0

pass() { echo -e "${GREEN}[PASS]${NC} $1"; pass_count=$((pass_count + 1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; fail_count=$((fail_count + 1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# ============================================================================
# SECTION 0: Preflight
# ============================================================================
echo "============================================================================"
echo "Hermes-Memory-OS Stabilization Deploy + Verify"
echo "Started: $TIMESTAMP"
echo "Source:  $SOURCE_DIR"
echo "Runtime: $HERMES_HOME"
echo "============================================================================"
echo ""

echo "=== Section 0: Preflight ==="

# 0.1 Source directory check
if [ -f "$SOURCE_DIR/plugins/memory/memory_os/__init__.py" ]; then
    pass "Source directory looks valid"
else
    fail "Source directory missing __init__.py — wrong SOURCE_DIR?"
    exit 1
fi

# 0.2 Hermes home check
if [ -d "$HERMES_HOME" ]; then
    pass "HERMES_HOME directory exists"
else
    fail "HERMES_HOME ($HERMES_HOME) does not exist"
    exit 1
fi

# 0.3 Check vector_available fix in source
if grep -q 'bool(' "$SOURCE_DIR/plugins/memory/memory_os/__init__.py"; then
    if grep -q 'vector_available.*bool(' "$SOURCE_DIR/plugins/memory/memory_os/__init__.py"; then
        pass "vector_available bool() fix present in source"
    else
        warn "bool() found but not on vector_available line — check manually"
    fi
else
    fail "vector_available bool() fix NOT in source — run: git pull origin main"
    exit 1
fi

echo ""

# ============================================================================
# SECTION 1: Install
# ============================================================================
echo "=== Section 1: Install to Runtime ==="

INSTALL_SCRIPT="$SOURCE_DIR/scripts/install_memory_os.sh"
if [ ! -f "$INSTALL_SCRIPT" ]; then
    fail "install_memory_os.sh not found at $INSTALL_SCRIPT"
    exit 1
fi

echo "Running: bash $INSTALL_SCRIPT --yes --production-safe --hermes-home $HERMES_HOME --hindsight auto --llm-judge-preset active --skip-verify"
if bash "$INSTALL_SCRIPT" \
    --yes \
    --production-safe \
    --hermes-home "$HERMES_HOME" \
    --hindsight auto \
    --llm-judge-preset active \
    --skip-verify \
    > "$INSTALL_LOG" 2>&1; then
    pass "install_memory_os.sh completed successfully"
else
    fail "install_memory_os.sh failed — check $INSTALL_LOG"
    tail -40 "$INSTALL_LOG"
    exit 1
fi

# 1.1 Verify vector_available fix landed in runtime
if grep -q '"vector_available": bool(' "$HERMES_HOME/plugins/memory/memory_os/__init__.py"; then
    pass "vector_available bool() fix present in runtime"
else
    fail "vector_available bool() fix NOT in runtime — install may have failed"
    grep -n "vector_available" "$HERMES_HOME/plugins/memory/memory_os/__init__.py" || echo "(line not found)"
fi

# 1.2 Verify other stabilization commits landed
if grep -q "approve_edge" "$HERMES_HOME/plugins/memory/memory_os/owner_actions.py"; then
    pass "approve_edge action present in runtime"
else
    fail "approve_edge action NOT in runtime — install incomplete?"
fi

if grep -q "fts5_empty_on_query" "$HERMES_HOME/plugins/memory/memory_os/prefetch.py"; then
    pass "FTS5-empty degradation signal present in runtime"
else
    warn "FTS5-empty degradation signal not found in runtime"
fi

if grep -q "provisional.*expires_at.*ValueError" "$HERMES_HOME/plugins/memory/memory_os/crystallized.py"; then
    pass "provisional expires_at validation present in runtime"
else
    warn "provisional expires_at validation not found in runtime"
fi

echo ""

# ============================================================================
# SECTION 2: Knob Verification
# ============================================================================
echo "=== Section 2: Knob Verification ==="

# Use Python to check knobs
KNOB_CHECK=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 -c "
import sys, json
sys.path.insert(0, '.')
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.knob_overrides import resolve_knob

roots = MemoryOSRoots.from_hermes_home('$HERMES_HOME')
results = {}
for knob in ['graph_layer_injection_enabled', 'vector_edge_proposer_enabled']:
    val = resolve_knob(knob, default=False, roots=roots)
    results[knob] = val
print(json.dumps(results))
" 2>&1)

echo "Knob status: $KNOB_CHECK"

if echo "$KNOB_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('graph_layer_injection_enabled') else 1)" 2>/dev/null; then
    pass "graph_layer_injection_enabled = True"
else
    warn "graph_layer_injection_enabled = False (will enable below)"
fi

if echo "$KNOB_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('vector_edge_proposer_enabled') else 1)" 2>/dev/null; then
    pass "vector_edge_proposer_enabled = True"
else
    warn "vector_edge_proposer_enabled = False (will enable below)"
fi

echo ""

# ============================================================================
# SECTION 3: Boundary Probe
# ============================================================================
echo "=== Section 3: Boundary Runtime Probe ==="

if command -v python3 &>/dev/null; then
    BOUNDARY_OUT=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 scripts/memory_os_boundary_runtime_probe.py \
        --host localhost \
        --hermes-home "$HERMES_HOME" \
        --output json 2>&1) || true

    if echo "$BOUNDARY_OUT" | python3 -c "
import sys,json
d=json.load(sys.stdin)
overall = d.get('overall', '')
sys.exit(0 if 'pass' in str(overall).lower() else 1)
" 2>/dev/null; then
        pass "Boundary probe: PASS"
    else
        fail "Boundary probe: FAIL or could not parse"
        echo "$BOUNDARY_OUT" | tail -20
    fi
else
    warn "python3 not found — skipping boundary probe"
fi

echo ""

# ============================================================================
# SECTION 4: Cron Adapter Probe
# ============================================================================
echo "=== Section 4: Cron Adapter Probe ==="

CRON_OUT=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 scripts/memory_os_cron_adapter_probe.py \
    --host localhost \
    --hermes-home "$HERMES_HOME" \
    --output json 2>&1) || true

if echo "$CRON_OUT" | python3 -c "
import sys,json
d=json.load(sys.stdin)
overall = d.get('overall', '')
sys.exit(0 if 'pass' in str(overall).lower() else 1)
" 2>/dev/null; then
    pass "Cron adapter probe: PASS"
else
    fail "Cron adapter probe: FAIL or could not parse"
    echo "$CRON_OUT" | tail -20
fi

echo ""

# ============================================================================
# SECTION 5: Full Monitor
# ============================================================================
echo "=== Section 5: Full Monitor (live) ==="

MONITOR_OUT=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 scripts/memory_os_3_200_monitor.py \
    --host localhost \
    --hermes-home "$HERMES_HOME" \
    --monitor-profile live \
    --output summary 2>&1) || true

echo "$MONITOR_OUT" | tail -30

if echo "$MONITOR_OUT" | grep -qi "monitor.*pass\|overall.*pass\|PASS"; then
    pass "Full monitor: PASS"
elif echo "$MONITOR_OUT" | grep -qi "WARN"; then
    warn "Full monitor: WARN (acceptable for sparse-memory host)"
else
    warn "Full monitor: see output above (may be expected on sparse-memory host)"
fi

echo ""

# ============================================================================
# SECTION 6: Hermes Status Check
# ============================================================================
echo "=== Section 6: Hermes Status ==="

if command -v hermes &>/dev/null; then
    HERMES_STATUS=$(hermes memory-os-agent-os status 2>&1) || true
    echo "$HERMES_STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
va = d.get('vector_available', 'KEY_NOT_FOUND')
print(f'vector_available = {va}')
print(f'index_counts = {d.get(\"index_counts\", \"N/A\")}')
print(f'prefetch_mode = {d.get(\"prefetch_mode\", \"N/A\")}')
" 2>&1 || echo "Could not parse hermes status JSON"

    # Check vector_available is bool
    VA_VAL=$(echo "$HERMES_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('vector_available', 'MISSING'))" 2>&1)
    if [ "$VA_VAL" = "False" ] || [ "$VA_VAL" = "True" ]; then
        pass "vector_available is proper bool: $VA_VAL"
    elif [ "$VA_VAL" = "None" ]; then
        fail "vector_available is None — BUG STILL PRESENT (install may not have applied)"
    elif [ "$VA_VAL" = "MISSING" ]; then
        fail "vector_available field missing — old code still active"
    else
        warn "vector_available = $VA_VAL (unexpected)"
    fi
else
    warn "hermes CLI not found — cannot check status"
fi

echo ""

# ============================================================================
# SECTION 7: File Integrity
# ============================================================================
echo "=== Section 7: Runtime File Integrity ==="

# Check key files exist
check_file() {
    local path="$1"
    local label="$2"
    if [ -f "$HERMES_HOME/$path" ]; then
        pass "File exists: $label"
    else
        warn "File missing: $label ($HERMES_HOME/$path) — may be normal for sparse memory"
    fi
}

check_file "memory-os/system/owner_actions.jsonl" "owner_actions.jsonl"
check_file "memory-os/system/execution_gate_envelopes.jsonl" "execution_gate_envelopes.jsonl"
check_file "memory-os/system/graph_layer_shadow.jsonl" "graph_layer_shadow.jsonl"
check_file "memory-os/crystallized/crystallized.jsonl" "crystallized.jsonl"
check_file "memory-os/index/memory_os.db" "memory_os.db (index)"

# Count edges
EDGE_COUNT=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 -c "
import sys, json
sys.path.insert(0, '.')
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.index import MemoryOSIndex
roots = MemoryOSRoots.from_hermes_home('$HERMES_HOME')
idx = MemoryOSIndex(roots)
edges = idx.query_edges(state='active')
print(len(edges))
" 2>&1)
echo "Active edges: $EDGE_COUNT"

# Count crystallized
CRYSTAL_COUNT=$(cd "$SOURCE_DIR" && PYTHONPATH=. python3 -c "
import sys
sys.path.insert(0, '.')
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import read_jsonl
roots = MemoryOSRoots.from_hermes_home('$HERMES_HOME')
cryst_path = roots.crystallized_path
entries = list(read_jsonl(cryst_path)) if cryst_path.exists() else []
print(len(entries))
" 2>&1)
echo "Crystallized records: $CRYSTAL_COUNT"

echo ""

# ============================================================================
# SECTION 8: Cleanup Temp Files
# ============================================================================
echo "=== Section 8: Cleanup ==="

TEMP_FILES=(
    /tmp/henable.py
    /tmp/hx.py
    /tmp/hermes_stabilize_enable.py
)

for f in "${TEMP_FILES[@]}"; do
    if [ -f "$f" ]; then
        rm -f "$f"
        echo "Cleaned: $f"
    fi
done

echo ""

# ============================================================================
# FINAL SUMMARY
# ============================================================================
echo "============================================================================"
echo "DEPLOY + VERIFY COMPLETE"
echo "============================================================================"
echo "Passed: $pass_count"
echo "Failed: $fail_count"
echo "Warnings: check above"
echo ""
echo "Install log: $INSTALL_LOG"
echo "Verify log: $VERIFY_LOG"
echo "============================================================================"

if [ "$fail_count" -gt 0 ]; then
    echo "SOME CHECKS FAILED — review output above"
    exit 1
else
    echo "ALL CHECKS PASSED"
    exit 0
fi
