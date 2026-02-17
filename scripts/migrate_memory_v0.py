#!/usr/bin/env python3
"""
Memory Migration Script: SQLite → Markdown
Migrates learning.db to ~/.elyan/memory/ directory
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any


def migrate_memory():
    """Migrate SQLite memory to Markdown files in ~/.elyan/memory/"""

    elyan_dir = Path.home() / ".elyan"
    memory_dir = elyan_dir / "memory"
    memory_dir.mkdir(exist_ok=True)

    db_path = elyan_dir / "learning.db"
    if not db_path.exists():
        print(f"⚠️  No learning.db found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    print("🔄 Migrating memory from SQLite to Markdown...\n")

    # 1. Migrate learned patterns
    migrate_patterns(cursor, memory_dir)

    # 2. Migrate user preferences
    migrate_preferences(cursor, memory_dir)

    # 3. Migrate interaction history
    migrate_history(cursor, memory_dir)

    # 4. Migrate skill memory
    migrate_skills(cursor, memory_dir)

    conn.close()
    print(f"\n✅ Migration complete! Files saved to: {memory_dir}\n")


def migrate_patterns(cursor, memory_dir: Path):
    """Migrate learned_patterns table to patterns.md"""

    cursor.execute("""
        SELECT pattern, intent, action, frequency, success_rate
        FROM learned_patterns
        ORDER BY frequency DESC
        LIMIT 50
    """)

    patterns = cursor.fetchall()
    if not patterns:
        print("⚠️  No patterns found")
        return

    md_content = """# Learned Patterns

Last updated: {timestamp}

## Summary
- Total patterns: {count}
- Based on interactions analysis

## Patterns by Frequency

""".format(
        timestamp=datetime.now().isoformat(),
        count=len(patterns)
    )

    for pattern, intent, action, frequency, success_rate in patterns:
        md_content += f"""
### {pattern}
- **Intent:** {intent}
- **Action:** {action}
- **Frequency:** {frequency}
- **Success Rate:** {success_rate:.1%}
"""

    output_file = memory_dir / "patterns.md"
    output_file.write_text(md_content)
    print(f"✅ Patterns: {output_file} ({len(patterns)} patterns)")


def migrate_preferences(cursor, memory_dir: Path):
    """Migrate user_preferences table to preferences.md"""

    cursor.execute("""
        SELECT key, value, confidence, last_updated
        FROM user_preferences
        ORDER BY last_updated DESC
    """)

    prefs = cursor.fetchall()
    if not prefs:
        print("⚠️  No preferences found")
        return

    md_content = """# User Preferences

Last updated: {timestamp}

## Summary
- Learned preferences: {count}
- Confidence-weighted

## Preferences

""".format(
        timestamp=datetime.now().isoformat(),
        count=len(prefs)
    )

    for key, value, confidence, last_updated in prefs:
        dt = datetime.fromtimestamp(last_updated).isoformat() if last_updated else "unknown"
        md_content += f"""
### {key}
- **Value:** {value}
- **Confidence:** {confidence:.1%}
- **Last Updated:** {dt}
"""

    output_file = memory_dir / "preferences.md"
    output_file.write_text(md_content)
    print(f"✅ Preferences: {output_file} ({len(prefs)} preferences)")


def migrate_history(cursor, memory_dir: Path):
    """Migrate recent interactions to history.md"""

    cursor.execute("""
        SELECT timestamp, user_id, input_text, intent, action, success
        FROM interactions
        ORDER BY timestamp DESC
        LIMIT 100
    """)

    interactions = cursor.fetchall()
    if not interactions:
        print("⚠️  No interaction history found")
        return

    md_content = """# Conversation History Summary

Last updated: {timestamp}

## Recent Interactions ({count})

Most recent interactions from this session:

""".format(
        timestamp=datetime.now().isoformat(),
        count=len(interactions)
    )

    for ts, user_id, input_text, intent, action, success in interactions[:20]:
        dt = datetime.fromtimestamp(ts).isoformat() if ts else "unknown"
        status = "✅ Success" if success else "❌ Failed"
        md_content += f"""
### {dt} | {status}
- **User:** {user_id}
- **Input:** {input_text[:80]}...
- **Intent:** {intent}
- **Action:** {action}
"""

    if len(interactions) > 20:
        md_content += f"\n... and {len(interactions) - 20} more interactions (see SQLite for full history)\n"

    output_file = memory_dir / "history.md"
    output_file.write_text(md_content)
    print(f"✅ History: {output_file} ({len(interactions)} interactions)")


def migrate_skills(cursor, memory_dir: Path):
    """Migrate skill_memory table to skills.md"""

    cursor.execute("""
        SELECT domain, pattern, preferred_tools, preferred_output, quality_focus
        FROM skill_memory
        ORDER BY domain
    """)

    skills = cursor.fetchall()
    if not skills:
        print("⚠️  No skill memory found")
        return

    md_content = """# Skill Memory

Last updated: {timestamp}

## Domain-Specific Patterns ({count})

Learned skill patterns and preferences by domain:

""".format(
        timestamp=datetime.now().isoformat(),
        count=len(skills)
    )

    current_domain = None
    for domain, pattern, preferred_tools, preferred_output, quality_focus in skills:
        if domain != current_domain:
            md_content += f"\n## {domain}\n"
            current_domain = domain

        md_content += f"""
### {pattern}
- **Tools:** {preferred_tools}
- **Output:** {preferred_output}
- **Quality Focus:** {quality_focus}
"""

    output_file = memory_dir / "skills.md"
    output_file.write_text(md_content)
    print(f"✅ Skills: {output_file} ({len(skills)} skill patterns)")


if __name__ == "__main__":
    migrate_memory()
