from core.process_profiles import build_task_packets


def test_build_task_packets_sanitizes_target_files():
    packets = build_task_packets(
        objective="Harden packet scope",
        workflow_id="wf_1",
        nexus_mode="micro",
        plan=[
            {
                "id": "task_1",
                "title": "Patch auth",
                "action": "write_file",
                "description": "Update ../../secrets.txt and src/auth.py and https://example.com/file.py",
                "params": {"path": "/tmp/unsafe.py"},
            }
        ],
    )

    assert len(packets) == 1
    assert packets[0].target_files == ["src/auth.py"]
    assert packets[0].scope_guard == ["src/auth.py"]
