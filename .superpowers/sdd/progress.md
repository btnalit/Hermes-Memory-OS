Task 1: complete (commits 5e3dff8..bb1ad0d, review clean)
Task 2: complete (commits bb1ad0d..660f025, review clean)
Task 3: complete (commits 660f025..8c9c7df, review clean)
Task 4: complete (full suite 1436P/4F all pre-existing Windows, static checks PASS)
P1a Step 2 (production gate): complete (2026-06-22)
  - Mechanism verified: shadow log, knob gate, cross-section dedup, edge resolution all PASS
  - Edge quality: 16% same-topic in artificial test (expected — structural proposer needs diverse timestamps)
  - Phase 2 injection demo: Related Memory surfaces edge-connected non-matched records correctly
  - Recommend: deploy with knob OFF, seed real records, evaluate edge quality on 3.200
P1b Task 1: complete (commits 8c9c7df..c5a12b4, review clean) — LocalEmbedder
P1b Task 2: complete (commits c5a12b4..8e33046, review clean) — _index_embeddings
P1b Task 3: complete (commits 8e33046..8061280, review clean) — vector_search + RRF union + vector lane
P1b Task 4: complete (commits 8061280..31db0bb, review clean) — knob + embedder threading + integration

P1b ③ Vector Edge Proposer: complete (commit 51f1439, review clean)
  - vector_edge_proposer.py: run_vector_proposer() — pairwise cosine similarity → edges
  - Knob: vector_edge_proposer_enabled (lane_switch, default=False)
  - 24 tests all PASS

横切 A Silent Failure Audit: complete (2026-06-22)
  - Audited all ~60 except Exception blocks across core + modules + adapters + substrates
  - Result: codebase is well-disciplined — zero violations found
  - All bare except blocks fall into legitimate categories:
    1. Fail-open read paths (return [], {}, None) — intentional degradation
    2. Fail-open shadow/audit paths (explicitly marked "fail-open") — non-critical
    3. Error recording (build_error_record / append_audit) — correct pattern
    4. Embedder guard (is_available) — graceful degradation
    5. Last-resort (error handler itself failed) — no lower level
  - No bare except: blocks anywhere in the codebase
  - No write-path silent passes (store.py has zero bare except blocks)
  - All jsonl_io.py failures produce error_records
  - P0.1 (stale FTS) was the only real silent-failure bug — already fixed
Task 1: complete (commits e6ed97b..e4f3fc7, review clean)
Task 2: complete (commits e4f3fc7..b505fea, review clean)
Task 3: complete (commits b505fea..117333f, review clean)
Task 4: complete (commits 117333f..2a5992f, review clean)
Final whole-branch review (e6ed97b..2a5992f): 4 Minor findings, 0 Critical/Important
  1. prefetch.py:1358 — boundary marker appears on empty session_id (cosmetic, spec-designed)
  2. test_memory_os_prefetch.py:1089 — S.7 no dedicated cross-check test (implicitly covered by S.1+S.3)
  3. prefetch.py:1126 — redundant sort in fallback path (no-op on ≤8 events)
  4. prefetch.py:401 — build_context_router_report without session_id (reporting-only, cosmetic)
  Full suite: 1503P/5F (all failures pre-existing Windows PermissionError)
  Static checks: all pass
Task 1: complete (commits 5b9ad72..f092365, review clean)
Task 2: complete (commits f092365..7b1596c, review clean)
Task 3: complete (commits 7b1596c..910496a, review clean)

## Stabilization Sprint — 2026-06-24

- Task 1: complete (commits 910496a..945835a, review clean) — A.1 FTS5 empty degradation signal
- Task 2: complete (commits 945835a..c6bc8ec, review clean) — A.2 embedder availability in tool_status
- Task 3: complete (commits c6bc8ec..ff0b013, review clean) — A.5 provisional expires_at validation
- Task 4: complete (commits ff0b013..ef10947, review clean) — Edge owner review actions (approve_edge/reject_edge)
- Task 5: complete (commits ef10947..10e5340, review clean) — Shadow analyzer + checklist finalization

All tests: 1525 passed, 4 pre-existing Windows failures, 3 skipped.
All static checks: write_surface_check ✅, import_cycle_check ✅, static_hygiene ✅

## Deterministic Recall Floor (v4) — 2026-06-25

- Task 1: complete (commits 10e5340..e9a3bde, review clean) — Enhanced mtime fallback + floor match scoring + self-exposure annotation
- Task 2: complete — Keyword table cleanup (remove 6 project terms, add 10 content words, add stop-word filter, config override)
- Task 3: complete — Permanent core baseline (top-5 recurrence during degradation, reorder-only)

All tests: 1525 passed, 4 pre-existing Windows failures, 3 skipped.
All static checks: write_surface_check ✅, import_cycle_check ✅, static_hygiene ✅

## Code Review Fixes (8 findings from v4 review) — 2026-06-25

- Commit `0790984`: 8 code-review findings fixed (3 files, +58/-24)
  - #1 (HIGH): `subprocess.TimeoutExpired` added to 4 except clauses in `install_memory_os_plugin.py`
  - #2 (HIGH): parenthetical suffix stripped in `_section_source_class()` + `_budget_keep_priority()`
  - #3 (MEDIUM): body_cache eliminates double file I/O in degradation path
  - #4 (MEDIUM): CLI `vector_available` semantics documented (import-only vs full load)
  - #5 (LOW): `lru_cache` on `plan_query_route()` — 3× redundant calls → 1
  - #6 (LOW): dead `PERMANENT_BASELINE_N` removed, comment updated
  - #7 (LOW): O(N×T×B) complexity documented in `_floor_match_score()` docstring
  - #8 (LOW): keyword divergence between routing and task-detection documented

All tests: 1525 passed, 4 pre-existing Windows failures, 3 skipped.
All static checks: write_surface_check ✅, import_cycle_check ✅, static_hygiene ✅

## Code Review Bug Fixes — 2026-06-24
- Task 1: complete (commits c504ee4..7eef777, review clean) — LLM packages post-install import verification
- Task 2: complete (commits 7eef777..16da44d, review clean) — Silent except → error_record in owner_actions
- Task 3: complete (commits 16da44d..84539ce, review clean) — Lightweight vector_available import-only check
- Task 4: complete (no commits — all 5 items CLEANUP, not bugs)
