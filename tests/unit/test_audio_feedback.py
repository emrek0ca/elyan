import pytest
from unittest.mock import patch, MagicMock
from core.voice.audio_feedback import AudioFeedbackEngine

def test_audio_feedback_success_mac():
    with patch("sys.platform", "darwin"):
        with patch("subprocess.Popen") as mock_popen:
            with patch("os.path.exists", return_value=True):
                engine = AudioFeedbackEngine()
                engine.play_success()
                
                mock_popen.assert_called_once()
                args, _ = mock_popen.call_args
                assert args[0][0] == "afplay"
                assert "Glass" in args[0][1]

def test_audio_feedback_error_mac():
    with patch("sys.platform", "darwin"):
        with patch("subprocess.Popen") as mock_popen:
            with patch("os.path.exists", return_value=True):
                engine = AudioFeedbackEngine()
                engine.play_error()
                
                mock_popen.assert_called_once()
                args, _ = mock_popen.call_args
                assert "Basso" in args[0][1]

def test_audio_feedback_disabled():
    with patch("sys.platform", "darwin"):
        with patch("subprocess.Popen") as mock_popen:
            with patch("config.elyan_config.elyan_config.get", return_value=False):
                engine = AudioFeedbackEngine()
                # Force reload of config value simulation if needed, but engine checks config on init or call.
                # The engine._should_play checks config.get every time.
                
                engine.play_success()
                mock_popen.assert_not_called()
