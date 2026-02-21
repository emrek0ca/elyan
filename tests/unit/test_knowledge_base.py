
import pytest
import os
from core.knowledge_base import KnowledgeBase

def test_kb_record_and_find():
    kb = KnowledgeBase()
    # Mock records for testing
    kb._records = []
    
    # Bir başarı kaydet
    kb.record_success(
        task_type="write_word",
        problem="permission_denied",
        solution={"params": {"path": "~/Desktop/test.docx"}},
        context={"platform": "mac"}
    )
    
    # Çözümü bulmayı dene
    solution = kb.find_solution("write_word", "permission_denied")
    assert solution is not None
    assert "Desktop" in solution["params"]["path"]
    
    # Farklı ama benzer bir problem ipucu ile bulmayı dene
    solution2 = kb.find_solution("write_word", "permission_denied error on mac")
    assert solution2 is not None

def test_kb_deduplication():
    kb = KnowledgeBase()
    kb._records = []
    
    for _ in range(3):
        kb.record_success(
            task_type="list_files",
            problem="not_found",
            solution={"params": {"path": "."}},
            context={}
        )
    
    assert len(kb._records) == 1
    assert kb._records[0]["success_count"] == 3
