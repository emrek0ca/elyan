"""Built-in skills that wrap existing Elyan tools."""

from typing import List


def get_builtin_skills() -> List:
    """Return instances of all built-in skills."""
    skills = []
    try:
        from .system_skill import SystemSkill
        skills.append(SystemSkill())
    except Exception:
        pass
    try:
        from .files_skill import FilesSkill
        skills.append(FilesSkill())
    except Exception:
        pass
    try:
        from .research_skill import ResearchSkill
        skills.append(ResearchSkill())
    except Exception:
        pass
    try:
        from .browser_skill import BrowserSkill
        skills.append(BrowserSkill())
    except Exception:
        pass
    try:
        from .office_skill import OfficeSkill
        skills.append(OfficeSkill())
    except Exception:
        pass
    try:
        from .email_skill import EmailSkill
        skills.append(EmailSkill())
    except Exception:
        pass
    return skills
