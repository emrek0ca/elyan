
import pytest
from core.context_intelligence import get_context_intelligence

def test_detect_web_context():
    intel = get_context_intelligence()
    ctx = intel.detect("Bana bir portfolio websitesi yap, React kullanalım")
    assert ctx["domain"] == "web_dev"
    assert ctx["stack"] == "javascript"
    
    prompt = intel.get_specialized_prompt(ctx)
    assert "Frontend Architect" in prompt
    assert "JAVASCRIPT" in prompt

def test_detect_system_context():
    intel = get_context_intelligence()
    ctx = intel.detect("Masaüstündeki büyük dosyaları listele ve sistem bilgilerini göster")
    assert ctx["domain"] == "system"
    
    tools = intel.get_preferred_tools(ctx["domain"])
    assert "list_files" in tools
    assert "get_system_info" in tools

def test_detect_creative_context():
    intel = get_context_intelligence()
    ctx = intel.detect("Bana bugünle ilgili kısa bir şiir yazar mısın?")
    assert ctx["is_creative"] is True
    assert ctx["domain"] == "general" # Creative is a flag, not a domain
