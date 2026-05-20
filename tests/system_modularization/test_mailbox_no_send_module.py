from plugins.modules.messaging.mailbox import MailboxNoSendModule, mailbox_manifest
from plugins.system.lifecycle import ModuleLifecycle


def test_mailbox_manifest_installs_through_lifecycle(tmp_path):
    lifecycle = ModuleLifecycle(
        tmp_path,
        profile="main",
        available_dependencies=("memory_os", "scheduler"),
    )

    status = lifecycle.install(mailbox_manifest())
    enabled = lifecycle.enable("mailbox")

    assert status.installed is True
    assert enabled.enabled is True
    assert enabled.delivery_mode == "no-send"
    assert lifecycle.doctor("mailbox").status == "ok"


def test_mailbox_status_reports_roots_without_private_bodies(tmp_path):
    module = MailboxNoSendModule(tmp_path, profile="main")
    (tmp_path / "mailbox" / "inbox").mkdir(parents=True)
    (tmp_path / "mailbox" / "inbox" / "letter.json").write_text(
        '{"body":"private text must not appear"}\n',
        encoding="utf-8",
    )

    status = module.status()

    assert status["module"] == "mailbox"
    assert status["delivery_mode"] == "no-send"
    assert status["roots"]["mailbox_exists"] is True
    assert "private text" not in str(status)
    assert "letter.json" not in str(status)


def test_mailbox_doctor_warns_when_roots_are_missing(tmp_path):
    module = MailboxNoSendModule(tmp_path, profile="main")

    report = module.doctor()

    assert report["status"] == "warning"
    assert report["findings"][0]["code"] == "mailbox_root_missing"
    assert "body" not in str(report).lower()


def test_mailbox_no_send_records_would_send_without_body(tmp_path):
    module = MailboxNoSendModule(tmp_path, profile="main")

    record = module.record_would_send(
        to="sannai",
        channel="mailbox",
        payload_ref="fixture://letter-1",
        reason="slice-24-test",
    )

    records = module.read_would_send_records()
    assert records == [record]
    assert record["mode"] == "would_send"
    assert record["actual_send"] is False
    assert record["payload_ref"] == "fixture://letter-1"
    assert "body" not in record


def test_mailbox_refuses_real_send_mode(tmp_path):
    module = MailboxNoSendModule(tmp_path, profile="main", delivery_mode="send")

    report = module.doctor()

    assert report["status"] == "error"
    assert report["findings"][0]["code"] == "delivery_send_enabled"
