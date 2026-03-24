"""ActionExecutor — Execute ComputerAction objects

Mouse, keyboard, screen control via pynput and pyautogui.
Fallback to accessibility APIs when available.
"""

import asyncio
import time
from typing import Optional

from core.observability.logger import get_structured_logger
from elyan.computer_use.tool import ComputerAction

slog = get_structured_logger("action_executor")


class ActionExecutor:
    """Execute individual computer actions"""

    def __init__(self):
        """Initialize executor with input controllers"""
        self.mouse = None
        self.keyboard = None
        self._init_controllers()

    def _init_controllers(self):
        """Lazy initialize pynput controllers"""
        try:
            from pynput.mouse import Controller as MouseController
            from pynput.mouse import Button
            from pynput.keyboard import Controller as KeyController

            self.mouse = MouseController()
            self.keyboard = KeyController()
            self.Button = Button
        except ImportError as e:
            slog.log_event("pynput_import_failed", {
                "error": str(e)
            }, level="error")
            # Fallback to pyautogui
            try:
                import pyautogui
                self.pyautogui = pyautogui
            except ImportError:
                raise RuntimeError(
                    "Neither pynput nor pyautogui available. "
                    "Install with: pip install pynput pyautogui"
                )

    async def execute(self, action: ComputerAction) -> dict:
        """
        Execute a single ComputerAction

        Returns:
            {
                "success": bool,
                "error": optional error message,
                "task_completed": bool (if action indicates task completion),
                "extracted_data": optional data extracted by action
            }
        """
        try:
            slog.log_event("action_execute_start", {
                "action_type": action.action_type,
                "confidence": action.confidence
            })

            result = None

            if action.action_type == "left_click":
                result = self._execute_left_click(action)

            elif action.action_type == "right_click":
                result = self._execute_right_click(action)

            elif action.action_type == "double_click":
                result = self._execute_double_click(action)

            elif action.action_type == "type":
                result = self._execute_type(action)

            elif action.action_type == "scroll":
                result = self._execute_scroll(action)

            elif action.action_type == "drag":
                result = self._execute_drag(action)

            elif action.action_type == "hotkey":
                result = self._execute_hotkey(action)

            elif action.action_type == "mouse_move":
                result = self._execute_mouse_move(action)

            elif action.action_type == "wait":
                result = await self._execute_wait(action)

            elif action.action_type == "noop":
                result = {"success": True}

            else:
                return {
                    "success": False,
                    "error": f"Unknown action type: {action.action_type}"
                }

            if result is None:
                result = {"success": True}

            slog.log_event("action_execute_complete", {
                "action_type": action.action_type,
                "success": result.get("success", True)
            })

            return result

        except Exception as e:
            slog.log_event("action_execute_error", {
                "action_type": action.action_type,
                "error": str(e)
            }, level="error")

            return {
                "success": False,
                "error": str(e)
            }

    def _execute_left_click(self, action: ComputerAction) -> dict:
        """Click at (x, y)"""
        if action.x is None or action.y is None:
            return {"success": False, "error": "Missing x or y coordinate"}

        try:
            if self.mouse:
                self.mouse.position = (action.x, action.y)
                self.mouse.click(self.Button.left)
            else:
                # Fallback to pyautogui
                self.pyautogui.click(action.x, action.y)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_right_click(self, action: ComputerAction) -> dict:
        """Right-click at (x, y) for context menu"""
        if action.x is None or action.y is None:
            return {"success": False, "error": "Missing x or y coordinate"}

        try:
            if self.mouse:
                self.mouse.position = (action.x, action.y)
                self.mouse.click(self.Button.right)
            else:
                self.pyautogui.rightClick(action.x, action.y)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_double_click(self, action: ComputerAction) -> dict:
        """Double-click at (x, y)"""
        if action.x is None or action.y is None:
            return {"success": False, "error": "Missing x or y coordinate"}

        try:
            if self.mouse:
                self.mouse.position = (action.x, action.y)
                self.mouse.click(self.Button.left, 2)  # 2 = double-click
            else:
                self.pyautogui.doubleClick(action.x, action.y)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_type(self, action: ComputerAction) -> dict:
        """Type text"""
        if action.text is None:
            return {"success": False, "error": "No text provided"}

        try:
            if self.keyboard:
                self.keyboard.type(action.text)
            else:
                self.pyautogui.typewrite(action.text, interval=0.05)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_scroll(self, action: ComputerAction) -> dict:
        """Scroll at current position (or at x, y)"""
        # Scroll amount in lines/clicks
        dy = action.dy or 3  # Scroll down if positive
        dx = action.dx or 0  # Horizontal scroll

        try:
            if self.mouse:
                # pynput doesn't have scroll, fallback to pyautogui
                x = action.x or 500
                y = action.y or 500
                self.pyautogui.scroll(dy, x=x, y=y)
            else:
                x = action.x or 500
                y = action.y or 500
                self.pyautogui.scroll(dy, x=x, y=y)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_drag(self, action: ComputerAction) -> dict:
        """Drag from (x, y) to (x2, y2)"""
        if None in [action.x, action.y, action.x2, action.y2]:
            return {"success": False, "error": "Missing drag coordinates"}

        try:
            if self.mouse:
                self.mouse.position = (action.x, action.y)
                self.mouse.press(self.Button.left)
                asyncio.sleep(0.05)
                self.mouse.position = (action.x2, action.y2)
                asyncio.sleep(0.05)
                self.mouse.release(self.Button.left)
            else:
                self.pyautogui.moveTo(action.x, action.y)
                self.pyautogui.mouseDown()
                time.sleep(0.05)
                self.pyautogui.moveTo(action.x2, action.y2, duration=0.3)
                time.sleep(0.05)
                self.pyautogui.mouseUp()

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_hotkey(self, action: ComputerAction) -> dict:
        """Execute keyboard hotkey (Ctrl+C, Cmd+A, etc)"""
        if action.key_combination is None or len(action.key_combination) == 0:
            return {"success": False, "error": "No key combination provided"}

        try:
            if self.keyboard:
                self.keyboard.hotkey(*action.key_combination)
            else:
                # pyautogui hotkey
                self.pyautogui.hotkey(*action.key_combination)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_mouse_move(self, action: ComputerAction) -> dict:
        """Move mouse to (x, y) without clicking"""
        if action.x is None or action.y is None:
            return {"success": False, "error": "Missing x or y coordinate"}

        try:
            if self.mouse:
                self.mouse.position = (action.x, action.y)
            else:
                self.pyautogui.moveTo(action.x, action.y, duration=0.5)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_wait(self, action: ComputerAction) -> dict:
        """Wait for N milliseconds"""
        wait_time = action.wait_ms / 1000.0
        try:
            await asyncio.sleep(wait_time)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# SINGLETON
# ============================================================================

_executor: Optional[ActionExecutor] = None


def get_action_executor() -> ActionExecutor:
    """Get or create ActionExecutor singleton"""
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor
