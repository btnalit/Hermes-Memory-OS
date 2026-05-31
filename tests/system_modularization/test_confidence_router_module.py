from plugins.modules.governance.confidence_router import ConfidenceRouterModule


def test_confidence_router_writes_shadow_routes_without_live_apply(tmp_path):
    module = ConfidenceRouterModule(tmp_path, profile="main")

    result = module.route_records(
        [
            {"subject_ref": "working:low", "subject_kind": "working", "maturity_score": 0.2, "score_id": "s1"},
            {"subject_ref": "candidate:mid", "subject_kind": "crystallized_candidate", "maturity_score": 0.6, "score_id": "s2"},
            {"subject_ref": "candidate:high", "subject_kind": "crystallized_candidate", "maturity_score": 0.9, "score_id": "s3"},
        ]
    )

    assert result["route_count"] == 3
    assert result["actual_execute"] is False
    assert result["route_live_applied"] is False
    routes = module.read_routes()
    assert [route["band"] for route in routes] == ["low", "mid", "high"]
    assert {route["live_applied"] for route in routes} == {False}
    assert routes[2]["route_intent"] == "owner_agenda_candidate"


def test_confidence_router_status_is_ok_after_zero_route_run(tmp_path):
    module = ConfidenceRouterModule(tmp_path, profile="main")

    result = module.route_records([])

    assert result["route_count"] == 0
    status = module.status()
    assert status["status"] == "ok"
    assert status["run_count"] == 1
    assert status["route_live_applied"] is False
