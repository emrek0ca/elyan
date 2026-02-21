"""macOS Calendar and Reminders Integration"""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from utils.logger import get_logger

logger = get_logger("macos.calendar")


async def get_today_events() -> dict[str, Any]:
    """Get today's calendar events"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        script = f'''
        set today to current date
        set startOfDay to today - (time of today)
        set endOfDay to startOfDay + (24 * 60 * 60) - 1

        set eventList to {{}}

        tell application "Calendar"
            set allCalendars to every calendar
            repeat with cal in allCalendars
                set calEvents to (every event of cal whose start date >= startOfDay and start date <= endOfDay)
                repeat with evt in calEvents
                    set evtStart to start date of evt
                    set evtEnd to end date of evt
                    set evtSummary to summary of evt
                    set startStr to (time string of evtStart)
                    set endStr to (time string of evtEnd)
                    set eventList to eventList & {{evtSummary & " | " & startStr & " - " & endStr}}
                end repeat
            end repeat
        end tell

        set AppleScript's text item delimiters to linefeed
        return eventList as text
        '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode().strip()
            # Calendar access might be denied
            if "not allowed" in error.lower() or "access" in error.lower():
                return {
                    "success": False,
                    "error": "Takvim erişim izni gerekli. Sistem Tercihleri > Gizlilik ve Güvenlik > Takvim"
                }
            return {"success": False, "error": error}

        output = stdout.decode().strip()
        events = []

        if output:
            for line in output.split("\n"):
                if " | " in line:
                    parts = line.split(" | ")
                    events.append({
                        "title": parts[0],
                        "time": parts[1] if len(parts) > 1 else ""
                    })

        logger.info(f"Retrieved {len(events)} events for today")

        return {
            "success": True,
            "date": today,
            "events": events,
            "count": len(events)
        }

    except Exception as e:
        logger.error(f"Get events error: {e}")
        return {"success": False, "error": str(e)}


async def create_event(
    title: str,
    start_time: str = None,
    end_time: str = None,
    date: str = None,
    notes: str = ""
) -> dict[str, Any]:
    """Create a calendar event

    Args:
        title: Event title
        start_time: Start time (HH:MM format), defaults to next hour
        end_time: End time (HH:MM format), defaults to 1 hour after start
        date: Date (YYYY-MM-DD format), defaults to today
        notes: Optional notes/description
    """
    try:
        now = datetime.now()

        # Default date is today
        if not date:
            date = now.strftime("%Y-%m-%d")

        # Default start time is next hour
        if not start_time:
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0)
            start_time = next_hour.strftime("%H:%M")

        # Default end time is 1 hour after start
        if not end_time:
            start_parts = start_time.split(":")
            start_hour = int(start_parts[0])
            end_hour = (start_hour + 1) % 24
            end_time = f"{end_hour:02d}:{start_parts[1] if len(start_parts) > 1 else '00'}"

        # Build AppleScript
        script = f'''
        set eventDate to date "{date}"
        set startParts to {{"{start_time}"}}
        set endParts to {{"{end_time}"}}

        tell application "Calendar"
            tell calendar 1
                set newEvent to make new event with properties {{summary:"{title}", start date:date ("{date} {start_time}"), end date:date ("{date} {end_time}")}}
            end tell
        end tell
        return "success"
        '''

        # Simpler approach
        script = f'''
        tell application "Calendar"
            activate
            tell calendar 1
                set startDate to current date
                set hours of startDate to {int(start_time.split(":")[0])}
                set minutes of startDate to {int(start_time.split(":")[1]) if ":" in start_time else 0}
                set seconds of startDate to 0

                set endDate to startDate + (1 * 60 * 60)

                make new event with properties {{summary:"{title}", start date:startDate, end date:endDate}}
            end tell
        end tell
        return "created"
        '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode().strip()
            if "not allowed" in error.lower() or "access" in error.lower():
                return {
                    "success": False,
                    "error": "Takvim erişim izni gerekli."
                }
            return {"success": False, "error": error}

        logger.info(f"Created event: {title}")

        return {
            "success": True,
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "date": date
        }

    except Exception as e:
        logger.error(f"Create event error: {e}")
        return {"success": False, "error": str(e)}


async def get_reminders(list_name: str = None) -> dict[str, Any]:
    """Get reminders from the Reminders app

    Args:
        list_name: Optional specific list name, defaults to all lists
    """
    try:
        if list_name:
            script = f'''
            tell application "Reminders"
                set reminderList to {{}}
                try
                    set theList to list "{list_name}"
                    set rems to reminders of theList whose completed is false
                    repeat with r in rems
                        set reminderList to reminderList & {{name of r}}
                    end repeat
                end try
            end tell

            set AppleScript's text item delimiters to linefeed
            return reminderList as text
            '''
        else:
            script = '''
            tell application "Reminders"
                set reminderList to {}
                repeat with theList in every list
                    set rems to reminders of theList whose completed is false
                    repeat with r in rems
                        set listName to name of theList
                        set reminderList to reminderList & {(name of r) & " [" & listName & "]"}
                    end repeat
                end repeat
            end tell

            set AppleScript's text item delimiters to linefeed
            return reminderList as text
            '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode().strip()
            if "not allowed" in error.lower() or "access" in error.lower():
                return {
                    "success": False,
                    "error": "Anımsatıcılar erişim izni gerekli."
                }
            return {"success": False, "error": error}

        output = stdout.decode().strip()
        reminders = []

        if output:
            for line in output.split("\n"):
                if line.strip():
                    if " [" in line:
                        parts = line.rsplit(" [", 1)
                        reminders.append({
                            "title": parts[0],
                            "list": parts[1].rstrip("]") if len(parts) > 1 else "Anımsatıcılar"
                        })
                    else:
                        reminders.append({"title": line, "list": list_name or "Anımsatıcılar"})

        logger.info(f"Retrieved {len(reminders)} reminders")

        return {
            "success": True,
            "reminders": reminders,
            "count": len(reminders)
        }

    except Exception as e:
        logger.error(f"Get reminders error: {e}")
        return {"success": False, "error": str(e)}


async def create_reminder(
    title: str,
    due_date: str = None,
    due_time: str = None,
    list_name: str = None,
    notes: str = ""
) -> dict[str, Any]:
    """Create a new reminder

    Args:
        title: Reminder title
        due_date: Due date (YYYY-MM-DD format)
        due_time: Due time (HH:MM format)
        list_name: List to add to, defaults to first list
        notes: Optional notes
    """
    try:
        # Build reminder properties
        properties = f'name:"{title}"'

        if notes:
            properties += f', body:"{notes}"'

        # Build the script
        if list_name:
            list_selector = f'list "{list_name}"'
        else:
            list_selector = "first list"

        if due_date and due_time:
            script = f'''
            tell application "Reminders"
                set dueDateTime to current date
                set year of dueDateTime to {due_date.split("-")[0]}
                set month of dueDateTime to {int(due_date.split("-")[1])}
                set day of dueDateTime to {int(due_date.split("-")[2])}
                set hours of dueDateTime to {int(due_time.split(":")[0])}
                set minutes of dueDateTime to {int(due_time.split(":")[1]) if ":" in due_time else 0}

                tell {list_selector}
                    make new reminder with properties {{{properties}, due date:dueDateTime}}
                end tell
            end tell
            return "created"
            '''
        elif due_date:
            script = f'''
            tell application "Reminders"
                set dueDateTime to current date
                set year of dueDateTime to {due_date.split("-")[0]}
                set month of dueDateTime to {int(due_date.split("-")[1])}
                set day of dueDateTime to {int(due_date.split("-")[2])}
                set hours of dueDateTime to 9
                set minutes of dueDateTime to 0

                tell {list_selector}
                    make new reminder with properties {{{properties}, due date:dueDateTime}}
                end tell
            end tell
            return "created"
            '''
        else:
            script = f'''
            tell application "Reminders"
                tell {list_selector}
                    make new reminder with properties {{{properties}}}
                end tell
            end tell
            return "created"
            '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = stderr.decode().strip()
            if "not allowed" in error.lower() or "access" in error.lower():
                return {
                    "success": False,
                    "error": "Anımsatıcılar erişim izni gerekli."
                }
            return {"success": False, "error": error}

        logger.info(f"Created reminder: {title}")

        return {
            "success": True,
            "title": title,
            "due_date": due_date,
            "due_time": due_time,
            "list": list_name or "varsayılan"
        }

    except Exception as e:
        logger.error(f"Create reminder error: {e}")
        return {"success": False, "error": str(e)}
