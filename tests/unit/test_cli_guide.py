from cli.commands.guide import build_install_to_ui_guide


def test_install_to_ui_guide_prefers_setup_when_not_ready():
    guide = build_install_to_ui_guide(setup_ready=False, gateway_running=False)

    assert guide["current"] == "elyan setup"
    assert guide["steps"][0]["command"] == "elyan setup"
    assert guide["verification"] == "bootstrap-owner -> login -> auth/me -> logout"


def test_install_to_ui_guide_moves_to_desktop_once_gateway_is_running():
    guide = build_install_to_ui_guide(setup_ready=True, gateway_running=True)

    assert guide["current"] == "elyan desktop"
    assert guide["steps"][1]["command"] == "elyan launch"
    assert guide["steps"][2]["command"] == "elyan desktop"
