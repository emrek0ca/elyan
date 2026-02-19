from tools import AVAILABLE_TOOLS


def test_lazy_loader_exposes_extended_tools():
    # Regression: these names existed in catalog but were not loadable from lazy loader.
    expected = [
        "read_word",
        "write_word",
        "read_excel",
        "write_excel",
        "analyze_excel_data",
        "send_email",
        "get_emails",
        "get_unread_emails",
        "search_emails",
        "execute_python_code",
        "execute_javascript_code",
        "execute_shell_command",
        "debug_code",
        "ollama_list_models",
        "ollama_remove_model",
        "create_chart",
        "create_research_visualization",
        "get_chart_generator",
    ]
    for tool_name in expected:
        tool = AVAILABLE_TOOLS.get(tool_name)
        assert callable(tool), f"{tool_name} should be lazily loadable"
