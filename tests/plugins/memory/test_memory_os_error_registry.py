"""Tests for error-code registry."""

import pytest
from plugins.memory.memory_os.error_registry import (
    ErrorCode,
    register_error_code,
    lookup_error_code,
    list_error_codes,
    unregistered_error_code,
    build_registry_report,
    ERROR_REGISTRY_SCHEMA_VERSION,
)


class TestErrorRegistry:
    def test_register_and_lookup(self):
        ec = ErrorCode(
            code="test_error",
            producer="test.py",
            consumer="test",
            production_severity="warning",
            clean_host_severity="error",
            recoverability="auto",
            description="test error code",
        )
        register_error_code(ec)
        found = lookup_error_code("test_error")
        assert found is not None
        assert found.code == "test_error"
        assert found.producer == "test.py"

    def test_lookup_nonexistent(self):
        assert lookup_error_code("nonexistent_code") is None

    def test_unregistered_code(self):
        ec = unregistered_error_code("unknown_code")
        assert ec.code == "unknown_code"
        assert ec.producer == "unknown"

    def test_list_error_codes(self):
        codes = list_error_codes()
        assert len(codes) > 0
        # Check built-in codes are present
        codes_set = {ec.code for ec in codes}
        assert "crystallized_file_unparseable" in codes_set
        assert "source_cursor_not_found" in codes_set

    def test_build_registry_report(self):
        report = build_registry_report()
        assert report["schema_version"] == ERROR_REGISTRY_SCHEMA_VERSION
        assert report["registered_count"] > 0
        assert len(report["codes"]) == report["registered_count"]

    def test_builtin_error_codes_have_producer(self):
        for ec in list_error_codes():
            assert ec.code, f"Error code missing: {ec}"
            assert ec.producer, f"Error code {ec.code} has no producer"

    def test_builtin_error_codes_have_valid_severity(self):
        valid = {"info", "warning", "error", "fail", "unknown"}
        for ec in list_error_codes():
            assert ec.production_severity in valid, f"{ec.code} has invalid production_severity"
            assert ec.clean_host_severity in valid, f"{ec.code} has invalid clean_host_severity"