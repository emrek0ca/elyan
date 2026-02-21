
import pytest
from core.multi_agent.specialists import get_specialist_registry

def test_specialist_selection():
    registry = get_specialist_registry()
    
    # Coding uzmanı seçilmeli
    s1 = registry.select_for_input("Python ile bir script yazıp debug eder misin?")
    assert s1.domain == "coding"
    assert "Software Engineer" in s1.role
    
    # Araştırma uzmanı seçilmeli
    s2 = registry.select_for_input("Küresel ısınma hakkında derin bir araştırma yap")
    assert s2.domain == "research"
    assert "Research" in s2.name
    
    # Sistem uzmanı seçilmeli
    s3 = registry.select_for_input("Terminalde çalışan prosesleri listele")
    assert s3.domain == "system"
    assert "Administrator" in s3.role

def test_registry_get():
    registry = get_specialist_registry()
    coder = registry.get("coder")
    assert coder is not None
    assert coder.name == "Elyan Code"
    
    none_agent = registry.get("non_existent")
    assert none_agent is None
