"""
core/vision_dom/coordinate_mapper.py
─────────────────────────────────────────────────────────────────────────────
Translates (X, Y) pixel coordinates derived from Multi-Modal Vision AI into 
physical OS-level Mouse and Keyboard actions via PyAutoGUI.
"""

from typing import Optional
from utils.logger import get_logger

logger = get_logger("coordinate_mapper")

try:
    import pyautogui
    # Failsafe moving mouse to a corner aborts program
    pyautogui.FAILSAFE = True
    HAS_GUI_DEPS = True
except ImportError:
    HAS_GUI_DEPS = False
    logger.warning("GUI dependencies missing. Run: pip install pyautogui")

class CoordinateMapper:
    def __init__(self):
        if HAS_GUI_DEPS:
            # Add a slight delay between commands to mimic human behavior and avoid rate limits
            pyautogui.PAUSE = 0.5
            
    def click(self, x: int, y: int, clicks: int = 1, button: str = 'left'):
        """Executes a physical mouse click at given coordinates."""
        if not HAS_GUI_DEPS:
            logger.error("CoordinateMapper failed: pyautogui not installed.")
            return False
            
        try:
            logger.info(f"🖱️ Clicking {button} {clicks}x at ({x}, {y})")
            # Move smoothly to the coordinates
            pyautogui.moveTo(x, y, duration=0.5, tween=pyautogui.easeInOutQuad)
            pyautogui.click(clicks=clicks, button=button)
            return True
        except pyautogui.FailSafeException:
            logger.critical("🚨 PyAutoGUI FailSafe Triggered! Mouse moved to a corner.")
            return False
        except Exception as e:
            logger.error(f"Click exception: {e}")
            return False

    def type_text(self, text: str, x: Optional[int] = None, y: Optional[int] = None):
        """Clicks a coordinate (optional) and types a string."""
        if not HAS_GUI_DEPS:
            return False
            
        if x is not None and y is not None:
            if not self.click(x, y):
                return False
                
        try:
            logger.info(f"⌨️ Typing text: '{text[:20]}...'")
            # Type characters sequentially like a human
            pyautogui.write(text, interval=0.05)
            pyautogui.press('enter')
            return True
        except pyautogui.FailSafeException:
            logger.critical("🚨 PyAutoGUI FailSafe Triggered!")
            return False
        except Exception as e:
            logger.error(f"Typing exception: {e}")
            return False
            
    def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int):
        """Drags mouse from start coordinates to end coordinates."""
        if not HAS_GUI_DEPS: return False
        try:
            logger.info(f"🤚 Dragging from ({start_x},{start_y}) to ({end_x},{end_y})")
            pyautogui.moveTo(start_x, start_y, duration=0.3)
            pyautogui.dragTo(end_x, end_y, duration=0.8, button='left')
            return True
        except Exception as e:
            logger.error(f"Drag exception: {e}")
            return False

coordinate_mapper = CoordinateMapper()
