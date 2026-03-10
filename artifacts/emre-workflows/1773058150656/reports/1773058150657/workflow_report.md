# Emre Workflow Pack

Pass rate: 5/5

| workflow | final_status | completed_steps | retries | replans | failure_code |
| --- | --- | --- | ---: | ---: | --- |
| Telegram-triggered desktop task completion | completed | open_safari | 0 | 1 | none |
| Research -> document creation -> file verification | completed | research_document_delivery | 0 | 0 | none |
| Safari / Cursor / Terminal / Finder switching tasks | completed | open_finder, open_terminal, open_cursor, open_safari, fill_screen_field | 0 | 0 | none |
| Login -> continue -> upload | completed | open_safari, open_login_page, fill_email, fill_password, click_login, click_continue, confirm_upload_dialog | 0 | 2 | none |
| Interrupted resume after partial completion | completed | open_safari, open_upload_page, screen_fallback_confirm-upload-dialog, click_save | 1 | 1 | none |
