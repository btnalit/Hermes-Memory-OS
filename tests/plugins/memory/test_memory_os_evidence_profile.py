from plugins.memory.memory_os.evidence_profile import build_evidence_profile


def test_evidence_profile_derives_owner_assertion_and_l0():
    profile = build_evidence_profile(
        subject_ref="crystallized_candidate:cand_1",
        subject_kind="crystallized_candidate",
        source_ref="memory_os:crystallized_candidate:cand_1",
        evidence_summary="owner approved stable preference",
        tags=["owner_review"],
    )

    assert profile["derivation"] == "owner_assertion"
    assert profile["coverage"]["source_diversity"] >= 1
    assert profile["abstraction_level"] == "L0"
    assert profile["provenance"] == "observed"


def test_evidence_profile_keeps_simulated_provenance_separate_from_observed():
    profile = build_evidence_profile(
        subject_ref="simulation:owner_can_be_wrong",
        subject_kind="simulation",
        source_ref="v7_simulated:owner_can_be_wrong",
        evidence_summary="simulated owner-approved memory is later contradicted",
        tags=["simulated", "confab"],
        provenance="simulated",
    )

    assert profile["derivation"] == "simulated"
    assert profile["provenance"] == "simulated"
    assert profile["coverage"]["source_diversity"] == 0
    assert profile["abstraction_level"] == "L3"
