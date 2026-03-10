"""
LAZY LOADING TOOL SYSTEM - Fast startup, load tools on demand
"""

from core.compat.legacy_tool_wrappers import wrap_legacy_tool

_loaded_tools = {}
_tool_load_errors = {}


def get_tool_load_errors() -> dict:
    """Return lazy-load errors collected while resolving tools."""
    return dict(_tool_load_errors)

def _lazy_load_tool(tool_name: str):
    """Lazy load a single tool when accessed"""
    if tool_name in _loaded_tools:
        return _loaded_tools[tool_name]
    
    # File Tools
    if tool_name in ["list_files", "read_file", "write_file", "search_files", "delete_file",
                     "move_file", "copy_file", "rename_file", "create_folder"]:
        from .file_tools import (
            list_files, read_file, write_file, search_files, delete_file,
            move_file, copy_file, rename_file, create_folder
        )
        tools = {
            "list_files": list_files, "read_file": read_file, "write_file": write_file,
            "search_files": search_files, "delete_file": delete_file, "move_file": move_file,
            "copy_file": copy_file, "rename_file": rename_file, "create_folder": create_folder
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)
    
    # System Tools
    if tool_name in ["get_system_info", "get_battery_status", "open_app", "open_url", "get_running_apps",
                     "take_screenshot", "analyze_screen", "screen_workflow", "vision_operator_loop", "operator_mission_control", "computer_use", "read_clipboard", "write_clipboard", "set_wallpaper",
                     "close_app", "shutdown_system", "restart_system", "sleep_system", "lock_screen",
                     "set_volume", "send_notification", "kill_process",
                     "get_process_info", "run_safe_command", "get_installed_apps", "get_display_info",
                     "open_project_in_ide", "record_screen", "get_weather", "run_code"]:
        if tool_name == "record_screen":
            from .screen_recorder import record_screen
            _loaded_tools["record_screen"] = record_screen
            return _loaded_tools["record_screen"]

        from .system_tools import (
            get_system_info, get_battery_status, open_app, open_url, get_running_apps, set_wallpaper,
            take_screenshot, analyze_screen, screen_workflow, vision_operator_loop, operator_mission_control, computer_use, capture_region, read_clipboard, write_clipboard,
            close_app, shutdown_system, restart_system, sleep_system, lock_screen,
            set_volume, send_notification, kill_process, get_process_info,
            run_safe_command, get_installed_apps, get_display_info, open_project_in_ide,
            get_weather, run_code,
        )
        tools = {
            "get_system_info": get_system_info, "get_battery_status": get_battery_status, "open_app": open_app, "open_url": open_url,
            "get_running_apps": get_running_apps, "take_screenshot": take_screenshot,
            "analyze_screen": analyze_screen, "screen_workflow": screen_workflow, "vision_operator_loop": vision_operator_loop,
            "operator_mission_control": operator_mission_control,
            "computer_use": computer_use, "capture_region": capture_region,
            "read_clipboard": read_clipboard, "write_clipboard": write_clipboard,
            "shutdown_system": shutdown_system, "restart_system": restart_system,
            "sleep_system": sleep_system, "lock_screen": lock_screen,
            "close_app": close_app, "set_volume": set_volume, "send_notification": send_notification,
            "kill_process": kill_process, "get_process_info": get_process_info,
            "run_safe_command": run_safe_command,
            "get_installed_apps": get_installed_apps,
            "get_display_info": get_display_info,
            "open_project_in_ide": open_project_in_ide,
            "get_weather": get_weather,
            "run_code": run_code,
            "set_wallpaper": set_wallpaper,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)
    
    # Script Tools
    if tool_name == "run_command":
        from .script_tools import run_command
        _loaded_tools["run_command"] = run_command
        return _loaded_tools["run_command"]

    # macOS Tools
    if tool_name in ["toggle_dark_mode", "get_appearance", "set_brightness", "get_brightness",
                     "wifi_status", "wifi_toggle", "bluetooth_status",
                     "get_wifi_details", "get_public_ip", "scan_local_network",
                     "get_today_events", "create_event", "get_reminders", "create_reminder",
                     "spotlight_search", "get_system_preferences"]:
        from .macos_tools import (
            toggle_dark_mode, get_appearance,
            wifi_status, wifi_toggle, bluetooth_status,
            get_wifi_details, get_public_ip, scan_local_network,
            get_today_events, create_event, get_reminders, create_reminder,
            spotlight_search, get_system_preferences
        )
        from .macos_tools.appearance import set_brightness, get_brightness
        tools = {
            "toggle_dark_mode": toggle_dark_mode, "get_appearance": get_appearance,
            "set_brightness": set_brightness, "get_brightness": get_brightness,
            "wifi_status": wifi_status, "wifi_toggle": wifi_toggle,
            "bluetooth_status": bluetooth_status,
            "get_wifi_details": get_wifi_details, "get_public_ip": get_public_ip,
            "scan_local_network": scan_local_network,
            "get_today_events": get_today_events, "create_event": create_event,
            "get_reminders": get_reminders, "create_reminder": create_reminder,
            "spotlight_search": spotlight_search, "get_system_preferences": get_system_preferences,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Office Tools
    if tool_name in ["read_word", "write_word", "read_excel", "write_excel",
                     "read_pdf", "get_pdf_info", "summarize_document", "analyze_excel_data", "search_in_pdf"]:
        tools = {}
        # Core office tools should remain loadable even if optional PDF/OCR deps are missing.
        try:
            from .office_tools.word_tools import read_word, write_word
            tools.update({"read_word": read_word, "write_word": write_word})
        except Exception:
            pass
        try:
            from .office_tools.excel_tools import read_excel, write_excel, analyze_excel_data
            tools.update({
                "read_excel": read_excel,
                "write_excel": write_excel,
                "analyze_excel_data": analyze_excel_data,
            })
        except Exception:
            pass
        try:
            from .office_tools.pdf_tools import read_pdf, get_pdf_info, search_in_pdf
            tools.update({
                "read_pdf": read_pdf,
                "get_pdf_info": get_pdf_info,
                "search_in_pdf": search_in_pdf,
            })
        except Exception:
            pass
        try:
            from .office_tools.document_summarizer import summarize_document
            tools.update({"summarize_document": summarize_document})
        except Exception:
            pass
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Web Tools
    if tool_name in ["fetch_page", "extract_text", "web_search",
                     "start_research", "get_research_status"]:
        from .web_tools import (
            fetch_page, extract_text, web_search,
            start_research, get_research_status
        )
        tools = {
            "fetch_page": fetch_page, "extract_text": extract_text,
            "web_search": web_search, "start_research": start_research,
            "get_research_status": get_research_status,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Browser Tools
    if tool_name in ["browser_open", "browser_click", "browser_type", "browser_screenshot", 
                     "browser_get_text", "browser_scroll", "browser_wait", "browser_close", 
                     "browser_status", "scrape_page", "scrape_links", "scrape_table"]:
        from .browser import (
            browser_open, browser_click, browser_type, browser_screenshot,
            browser_get_text, browser_scroll, browser_wait, browser_close,
            browser_status, scrape_page, scrape_links, scrape_table
        )
        tools = {
            "browser_open": browser_open, "browser_click": browser_click, "browser_type": browser_type,
            "browser_screenshot": browser_screenshot, "browser_get_text": browser_get_text,
            "browser_scroll": browser_scroll, "browser_wait": browser_wait,
            "browser_close": browser_close, "browser_status": browser_status,
            "scrape_page": scrape_page, "scrape_links": scrape_links, "scrape_table": scrape_table
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Email Tools
    if tool_name in ["send_email", "get_emails", "get_unread_emails", "search_emails"]:
        from .email_tools import (
            send_email, get_emails, get_unread_emails, search_emails
        )
        tools = {
            "send_email": send_email,
            "get_emails": get_emails,
            "get_unread_emails": get_unread_emails,
            "search_emails": search_emails,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Code Execution Tools
    if tool_name in ["execute_python_code", "execute_javascript_code", "execute_shell_command", "debug_code"]:
        from .code_execution_tools import (
            execute_python_code, execute_javascript_code, execute_shell_command, debug_code
        )
        tools = {
            "execute_python_code": execute_python_code,
            "execute_javascript_code": execute_javascript_code,
            "execute_shell_command": execute_shell_command,
            "debug_code": debug_code,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # AI Provider Tools
    if tool_name in ["ollama_list_models", "ollama_pull_model", "ollama_remove_model"]:
        from .ai_tools import ollama_list_models, ollama_pull_model, ollama_remove_model
        tools = {
            "ollama_list_models": ollama_list_models,
            "ollama_pull_model": ollama_pull_model,
            "ollama_remove_model": ollama_remove_model,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Media Tools
    if tool_name in ["control_music", "get_now_playing", "set_display_brightness"]:
        from .media_tools import control_music, get_now_playing, set_display_brightness
        tools = {
            "control_music": control_music,
            "get_now_playing": get_now_playing,
            "set_display_brightness": set_display_brightness
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Advanced Tools
    if tool_name in ["smart_summarize", "create_smart_file", "analyze_document", "generate_report", "analyze_image", "process_image_file", "verify_visual_quality"]:
        if tool_name == "analyze_image":
            from .vision_tools import analyze_image
            _loaded_tools["analyze_image"] = analyze_image
        elif tool_name == "process_image_file":
            from .vision_tools import process_image_file
            _loaded_tools["process_image_file"] = process_image_file
        elif tool_name == "verify_visual_quality":
            from .browser.visual_qa import verify_visual_quality
            _loaded_tools["verify_visual_quality"] = verify_visual_quality
        else:
            from .advanced_tools import smart_summarize, create_smart_file, analyze_document, generate_report
            tools = {
                "smart_summarize": smart_summarize, "create_smart_file": create_smart_file,
                "analyze_document": analyze_document, "generate_report": generate_report,
            }
            _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Note Tools
    if tool_name in ["create_note", "list_notes", "search_notes", "update_note", "delete_note", "get_note"]:
        from .note_tools import create_note, list_notes, search_notes, update_note, delete_note, get_note
        tools = {
            "create_note": create_note, "list_notes": list_notes, "search_notes": search_notes,
            "update_note": update_note, "delete_note": delete_note, "get_note": get_note,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Planning Tools
    if tool_name in ["create_plan", "execute_plan", "get_plan_status", "cancel_plan", "list_plans"]:
        from .planning_tools import create_plan, execute_plan, get_plan_status, cancel_plan, list_plans
        tools = {
            "create_plan": create_plan, "execute_plan": execute_plan,
            "get_plan_status": get_plan_status, "cancel_plan": cancel_plan, "list_plans": list_plans,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Document Tools
    if tool_name in ["edit_text_file", "batch_edit_text", "edit_word_document",
                     "merge_documents", "merge_pdfs", "merge_word_documents"]:
        from .document_tools import (
            edit_text_file, batch_edit_text, edit_word_document,
            merge_documents, merge_pdfs, merge_word_documents
        )
        tools = {
            "edit_text_file": edit_text_file, "batch_edit_text": batch_edit_text,
            "edit_word_document": edit_word_document,
            "merge_documents": merge_documents, "merge_pdfs": merge_pdfs,
            "merge_word_documents": merge_word_documents,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Research Tools
    if tool_name in ["advanced_research", "evaluate_source", "quick_research",
                     "synthesize_findings", "create_research_report",
                     "deep_research", "get_research_engine"]:
        from .research_tools import (
            advanced_research, evaluate_source, quick_research,
            synthesize_findings, create_research_report,
            deep_research, get_research_engine
        )
        tools = {
            "advanced_research": advanced_research, "evaluate_source": evaluate_source,
            "quick_research": quick_research, "synthesize_findings": synthesize_findings,
            "create_research_report": create_research_report,
            "deep_research": deep_research, "get_research_engine": get_research_engine,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Document Generator Tools
    if tool_name in ["generate_research_document", "get_document_generator", "create_presentation"]:
        if tool_name == "create_presentation":
            from .generators.slidev_generator import slidev_gen
            _loaded_tools["create_presentation"] = slidev_gen.create_presentation
            return _loaded_tools["create_presentation"]
        from .document_generator import (
            generate_research_document, get_document_generator
        )
        tools = {
            "generate_research_document": generate_research_document,
            "get_document_generator": get_document_generator,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Visualization Tools
    if tool_name in ["create_chart", "create_research_visualization", "get_chart_generator"]:
        from .visualization.chart_generator import (
            create_chart, create_research_visualization, get_chart_generator
        )
        tools = {
            "create_chart": create_chart,
            "create_research_visualization": create_research_visualization,
            "get_chart_generator": get_chart_generator,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Professional Workflows
    if tool_name in ["create_web_project_scaffold", "generate_document_pack", "research_document_delivery", "create_image_workflow_profile", "create_software_project_pack", "create_coding_delivery_plan", "create_coding_verification_report", "create_delivery_project", "verify_web_project_smoke_test"]:
        if tool_name == "create_delivery_project":
            from core.delivery.engine import delivery_engine
            _loaded_tools["create_delivery_project"] = delivery_engine.create_project
            return _loaded_tools["create_delivery_project"]
        from .pro_workflows import (
            create_web_project_scaffold,
            generate_document_pack,
            research_document_delivery,
            create_image_workflow_profile,
            create_software_project_pack,
            create_coding_delivery_plan,
            create_coding_verification_report,
            verify_web_project_smoke_test,
        )
        tools = {
            "create_web_project_scaffold": create_web_project_scaffold,
            "generate_document_pack": generate_document_pack,
            "research_document_delivery": research_document_delivery,
            "create_image_workflow_profile": create_image_workflow_profile,
            "create_software_project_pack": create_software_project_pack,
            "create_coding_delivery_plan": create_coding_delivery_plan,
            "create_coding_verification_report": create_coding_verification_report,
            "verify_web_project_smoke_test": verify_web_project_smoke_test,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Multimodal Tools
    if tool_name in ["transcribe_audio_file", "speak_text_local", "create_visual_asset_pack", "analyze_and_narrate_image", "get_multimodal_capability_report"]:
        from .multimodal_tools import (
            transcribe_audio_file,
            speak_text_local,
            create_visual_asset_pack,
            analyze_and_narrate_image,
            get_multimodal_capability_report,
        )
        tools = {
            "transcribe_audio_file": transcribe_audio_file,
            "speak_text_local": speak_text_local,
            "create_visual_asset_pack": create_visual_asset_pack,
            "analyze_and_narrate_image": analyze_and_narrate_image,
            "get_multimodal_capability_report": get_multimodal_capability_report,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Database Tools
    if tool_name in ["db_connect", "db_execute", "db_schema", "db_backup"]:
        from .database_tools import db_connect, db_execute, db_schema, db_backup
        tools = {"db_connect": db_connect, "db_execute": db_execute, "db_schema": db_schema, "db_backup": db_backup}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Git Tools
    if tool_name in ["git_clone", "git_status", "git_commit", "git_push", "git_pull", "git_branch", "git_diff", "git_log"]:
        from .git_tools import git_clone, git_status, git_commit, git_push, git_pull, git_branch, git_diff, git_log
        tools = {"git_clone": git_clone, "git_status": git_status, "git_commit": git_commit, "git_push": git_push, "git_pull": git_pull, "git_branch": git_branch, "git_diff": git_diff, "git_log": git_log}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Container Tools
    if tool_name in ["docker_build", "docker_run", "docker_stop", "docker_ps", "docker_logs", "docker_images", "docker_compose_up", "docker_compose_down", "generate_dockerfile"]:
        from .container_tools import docker_build, docker_run, docker_stop, docker_ps, docker_logs, docker_images, docker_compose_up, docker_compose_down, generate_dockerfile
        tools = {"docker_build": docker_build, "docker_run": docker_run, "docker_stop": docker_stop, "docker_ps": docker_ps, "docker_logs": docker_logs, "docker_images": docker_images, "docker_compose_up": docker_compose_up, "docker_compose_down": docker_compose_down, "generate_dockerfile": generate_dockerfile}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Deploy Tools
    if tool_name in ["deploy_to_vercel", "deploy_to_netlify", "deploy_docker", "get_deploy_status"]:
        from .deploy_tools import deploy_to_vercel, deploy_to_netlify, deploy_docker, get_deploy_status
        tools = {"deploy_to_vercel": deploy_to_vercel, "deploy_to_netlify": deploy_to_netlify, "deploy_docker": deploy_docker, "get_deploy_status": get_deploy_status}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # API Test Tools
    if tool_name in ["http_request", "graphql_query", "api_health_check"]:
        from .api_tools import http_request, graphql_query, api_health_check
        tools = {"http_request": http_request, "graphql_query": graphql_query, "api_health_check": api_health_check}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Data Tools
    if tool_name in ["read_csv", "read_json", "analyze_data", "data_query"]:
        from .data_tools import read_csv, read_json, analyze_data, data_query
        tools = {"read_csv": read_csv, "read_json": read_json, "analyze_data": analyze_data, "data_query": data_query}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Package Tools
    if tool_name in ["pip_install", "pip_list", "npm_install", "npm_run", "brew_install", "brew_list"]:
        from .package_tools import pip_install, pip_list, npm_install, npm_run, brew_install, brew_list
        tools = {"pip_install": pip_install, "pip_list": pip_list, "npm_install": npm_install, "npm_run": npm_run, "brew_install": brew_install, "brew_list": brew_list}
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    # Free API Tools (Zero cost, no API key)
    if tool_name in ["get_wikipedia_summary", "get_word_definition", "get_random_advice",
                     "get_random_fact", "get_random_quote"]:
        from .free_apis.free_knowledge_apis import (
            get_wikipedia_summary, get_word_definition, get_random_advice,
            get_random_fact, get_random_quote
        )
        tools = {
            "get_wikipedia_summary": get_wikipedia_summary,
            "get_word_definition": get_word_definition,
            "get_random_advice": get_random_advice,
            "get_random_fact": get_random_fact,
            "get_random_quote": get_random_quote,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    if tool_name in ["get_weather_by_city", "get_weather_openmeteo",
                     "get_crypto_price", "get_exchange_rate"]:
        from .free_apis.free_realtime_apis import (
            get_weather_by_city, get_weather_openmeteo,
            get_crypto_price, get_exchange_rate
        )
        tools = {
            "get_weather_by_city": get_weather_by_city,
            "get_weather_openmeteo": get_weather_openmeteo,
            "get_crypto_price": get_crypto_price,
            "get_exchange_rate": get_exchange_rate,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    if tool_name in ["get_ip_geolocation", "get_country_info", "get_postal_code_info"]:
        from .free_apis.free_geo_apis import (
            get_ip_geolocation, get_country_info, get_postal_code_info
        )
        tools = {
            "get_ip_geolocation": get_ip_geolocation,
            "get_country_info": get_country_info,
            "get_postal_code_info": get_postal_code_info,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    if tool_name in ["ddg_instant_answer", "search_academic_papers"]:
        from .free_apis.free_search_apis import (
            ddg_instant_answer, search_academic_papers
        )
        tools = {
            "ddg_instant_answer": ddg_instant_answer,
            "search_academic_papers": search_academic_papers,
        }
        _loaded_tools.update(tools)
        return _loaded_tools.get(tool_name)

    return None

# Lazy dictionary class
class LazyToolDict(dict):
    """Dictionary that lazy-loads tools on demand"""

    def __init__(self):
        super().__init__()
        self._tool_names = {
            # File Tools
            "list_files", "read_file", "write_file", "search_files", "delete_file",
            "move_file", "copy_file", "rename_file", "create_folder",
            # System Tools
            "get_system_info", "get_battery_status", "run_command", "run_safe_command", "open_app", "open_url",
            "get_running_apps", "take_screenshot", "analyze_screen", "screen_workflow", "vision_operator_loop", "operator_mission_control", "computer_use", "capture_region", "read_clipboard", "write_clipboard",
            "close_app", "shutdown_system", "restart_system", "sleep_system", "lock_screen",
            "set_volume", "send_notification", "kill_process", "get_process_info",
            "get_installed_apps", "get_display_info", "open_project_in_ide", "record_screen",
            "get_weather", "run_code",
            # macOS Tools
            "toggle_dark_mode", "get_appearance", "set_brightness", "get_brightness",
            "wifi_status", "wifi_toggle", "bluetooth_status",
            "get_wifi_details", "get_public_ip", "scan_local_network",
            "get_today_events", "create_event", "get_reminders",
            "create_reminder", "spotlight_search", "get_system_preferences",
            # Media Tools
            "control_music", "get_now_playing", "set_display_brightness",
            # Office Tools
            "read_word", "write_word", "read_excel", "write_excel", "read_pdf",
            "get_pdf_info", "summarize_document", "analyze_excel_data", "search_in_pdf",
            # Web Tools
            "fetch_page", "extract_text", "web_search", "start_research", "get_research_status",
            # Advanced Tools
            "smart_summarize", "create_smart_file", "analyze_document", "generate_report", "analyze_image", "process_image_file", "verify_visual_quality",
            # Note Tools
            "create_note", "list_notes", "search_notes", "update_note", "delete_note", "get_note",
            # Planning Tools
            "create_plan", "execute_plan", "get_plan_status", "cancel_plan", "list_plans",
            # Document Tools
            "edit_text_file", "batch_edit_text", "edit_word_document", "merge_documents",
            "merge_pdfs", "merge_word_documents",
            # Research Tools
            "advanced_research", "evaluate_source", "quick_research", "synthesize_findings",
            "create_research_report", "deep_research", "get_research_engine",
            # Document Generator Tools
            "generate_research_document", "get_document_generator", "create_presentation",
            # Visualization Tools
            "create_chart", "create_research_visualization", "get_chart_generator",
            # Email Tools
            "send_email", "get_emails", "get_unread_emails", "search_emails",
            # Code Execution Tools
            "execute_python_code", "execute_javascript_code", "execute_shell_command", "debug_code",
            # AI Tools
            "ollama_list_models", "ollama_remove_model",
            # Professional Workflows
            "create_web_project_scaffold", "generate_document_pack", "research_document_delivery", "create_image_workflow_profile", "create_software_project_pack", "create_coding_delivery_plan", "create_coding_verification_report",
            "create_delivery_project", "verify_web_project_smoke_test",
            # Multimodal Tools
            "transcribe_audio_file", "speak_text_local", "create_visual_asset_pack", "analyze_and_narrate_image",
            "get_multimodal_capability_report",
            # Browser Tools
            "browser_open", "browser_click", "browser_type", "browser_screenshot", 
            "browser_get_text", "browser_scroll", "browser_wait", "browser_close", 
            "browser_status", "scrape_page", "scrape_links", "scrape_table",
            # Database Tools
            "db_connect", "db_execute", "db_schema", "db_backup",
            # Git Tools
            "git_clone", "git_status", "git_commit", "git_push", "git_pull", "git_branch", "git_diff", "git_log",
            # Container Tools
            "docker_build", "docker_run", "docker_stop", "docker_ps", "docker_logs", "docker_images",
            "docker_compose_up", "docker_compose_down", "generate_dockerfile",
            # Deploy Tools
            "deploy_to_vercel", "deploy_to_netlify", "deploy_docker", "get_deploy_status",
            # API Tools
            "http_request", "graphql_query", "api_health_check",
            # Data Tools
            "read_csv", "read_json", "analyze_data", "data_query",
            # Package Tools
            "pip_install", "pip_list", "npm_install", "npm_run", "brew_install", "brew_list",
            # Free API Tools (Zero cost, no API key)
            "get_wikipedia_summary", "get_word_definition", "get_random_advice",
            "get_random_fact", "get_random_quote",
            "get_weather_by_city", "get_weather_openmeteo", "get_crypto_price", "get_exchange_rate",
            "get_ip_geolocation", "get_country_info", "get_postal_code_info",
            "ddg_instant_answer", "search_academic_papers",
        }

    def __getitem__(self, key):
        if key not in _loaded_tools and key in self._tool_names:
            try:
                _lazy_load_tool(key)
                if key in _loaded_tools:
                    _tool_load_errors.pop(key, None)
                else:
                    _tool_load_errors[key] = (
                        "Tool yüklenemedi (eksik bağımlılık veya import sorunu)."
                    )
            except Exception as exc:
                _tool_load_errors[key] = str(exc)
        tool = _loaded_tools.get(key)
        return wrap_legacy_tool(key, tool) if callable(tool) else tool

    def __contains__(self, key):
        return key in self._tool_names or key in _loaded_tools

    def __len__(self):
        return len(self._tool_names)

    def __iter__(self):
        return iter(self._tool_names)

    def items(self):
        # Load all tools and return items
        for tool_name in self._tool_names:
            if tool_name not in _loaded_tools:
                try:
                    _lazy_load_tool(tool_name)
                    if tool_name not in _loaded_tools:
                        _tool_load_errors[tool_name] = (
                            "Tool yüklenemedi (eksik bağımlılık veya import sorunu)."
                        )
                except Exception as exc:
                    _tool_load_errors[tool_name] = str(exc)
        return _loaded_tools.items()

    def values(self):
        # Load all tools and return values
        for tool_name in self._tool_names:
            if tool_name not in _loaded_tools:
                try:
                    _lazy_load_tool(tool_name)
                    if tool_name not in _loaded_tools:
                        _tool_load_errors[tool_name] = (
                            "Tool yüklenemedi (eksik bağımlılık veya import sorunu)."
                        )
                except Exception as exc:
                    _tool_load_errors[tool_name] = str(exc)
        return _loaded_tools.values()

    def get(self, key, default=None):
        try:
            return self[key] if key in self else default
        except:
            return default

    def keys(self):
        return self._tool_names

# CORE TOOLS - Fast core imports only
from .file_tools import (
    list_files, read_file, write_file, search_files, delete_file,
    move_file, copy_file, rename_file, create_folder
)
from .system_tools import (
    get_system_info, get_battery_status, open_app, open_url, get_running_apps,
    take_screenshot, read_clipboard, write_clipboard,
    close_app, shutdown_system, restart_system, sleep_system, lock_screen,
    set_volume, send_notification, kill_process, get_process_info, run_safe_command,
    open_project_in_ide,
)
from .script_tools import run_command

# Pre-populate core tools (no lazy loading for these)
_loaded_tools.update({
    "list_files": list_files, "read_file": read_file, "write_file": write_file,
    "search_files": search_files, "delete_file": delete_file, "move_file": move_file,
    "copy_file": copy_file, "rename_file": rename_file, "create_folder": create_folder,
    "get_system_info": get_system_info, "get_battery_status": get_battery_status, "open_app": open_app, "open_url": open_url,
    "get_running_apps": get_running_apps, "take_screenshot": take_screenshot,
    "read_clipboard": read_clipboard, "write_clipboard": write_clipboard,
    "shutdown_system": shutdown_system, "restart_system": restart_system,
    "sleep_system": sleep_system, "lock_screen": lock_screen,
    "close_app": close_app, "set_volume": set_volume, "send_notification": send_notification,
    "kill_process": kill_process, "get_process_info": get_process_info,
    "run_safe_command": run_safe_command, "open_project_in_ide": open_project_in_ide,
    "run_command": run_command
})

# Use lazy dict for AVAILABLE_TOOLS
AVAILABLE_TOOLS = LazyToolDict()
