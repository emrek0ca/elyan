from __future__ import annotations

import asyncio
from pathlib import Path

from tools.office_tools.document_summarizer import summarize_document
from tools.research_tools.document_rag import (
    DocumentRAGEngine,
    build_research_narrative,
    document_rag_qa,
    split_text_recursive,
    summarize_document_rag,
)


def test_split_text_recursive_keeps_chunk_limit_and_overlap():
    text = " ".join(f"token{i}" for i in range(1400))
    chunks = split_text_recursive(text, max_tokens=120, overlap_tokens=20)
    assert len(chunks) > 1
    assert all(chunk["token_count"] <= 120 for chunk in chunks)
    first = chunks[0]["text"].split()
    second = chunks[1]["text"].split()
    assert set(first[-20:]) & set(second[:20])


def test_build_research_narrative_produces_full_body():
    paragraphs = build_research_narrative(
        "PyTorch",
        findings=[
            "• PyTorch dinamik hesaplama grafiği sunar. (Kaynak: pytorch.org, Güven: %94)",
            "• TorchVision görüntü iş akışlarını hızlandırır. (Kaynak: pytorch.org, Güven: %91)",
        ],
        sources=[
            {"title": "PyTorch Docs", "url": "https://pytorch.org/docs/", "reliability_score": 0.96},
        ],
        brief="PyTorch hakkında araştırma yapar mısın",
        summary="PyTorch derin öğrenme için esnek bir çerçevedir.",
    )
    joined = "\n\n".join(paragraphs)
    assert "PyTorch" in joined
    assert "Kaynakça" in joined
    assert len(joined) > 200


def test_document_rag_round_trip_search_and_answer(tmp_path: Path):
    storage_dir = tmp_path / "rag"
    engine = DocumentRAGEngine(storage_dir=storage_dir, allow_remote_models=False)

    pytorch = tmp_path / "pytorch.txt"
    pytorch.write_text(
        "PyTorch is an open source machine learning framework.\n"
        "It provides dynamic computation graphs and automatic differentiation.\n"
        "TorchVision supports image models and computer vision tasks.\n"
        "TorchText helps with NLP experiments.",
        encoding="utf-8",
    )
    cats = tmp_path / "cats.txt"
    cats.write_text(
        "Cats are independent animals.\n"
        "They enjoy sleeping and grooming.\n"
        "Nutrition and veterinary care matter for cats.",
        encoding="utf-8",
    )

    ingest_pytorch = asyncio.run(engine.ingest_document(str(pytorch)))
    ingest_cats = asyncio.run(engine.ingest_document(str(cats)))
    assert ingest_pytorch["success"] is True
    assert ingest_cats["success"] is True

    search = asyncio.run(engine.search("dynamic computation graphs autograd", top_k=1))
    assert search["success"] is True
    assert search["results"]
    assert "pytorch" in search["results"][0]["source_name"].lower()

    answer = asyncio.run(
        document_rag_qa(
            path=str(pytorch),
            question="PyTorch ne sağlar?",
            top_k=3,
            storage_dir=storage_dir,
            use_llm=False,
        )
    )
    assert answer["success"] is True
    assert "PyTorch" in answer["answer"]
    assert answer["citations"]
    assert any(item["citation_id"] in answer["answer"] for item in answer["citations"])


def test_document_rag_persistence_round_trip(tmp_path: Path):
    storage_dir = tmp_path / "rag"
    doc = tmp_path / "ml.txt"
    doc.write_text(
        "Machine learning relies on data, optimization and evaluation.\n"
        "PyTorch provides tensors, autograd and GPU acceleration.",
        encoding="utf-8",
    )

    engine1 = DocumentRAGEngine(storage_dir=storage_dir, allow_remote_models=False)
    ingest = asyncio.run(engine1.ingest_document(str(doc)))
    assert ingest["success"] is True

    engine2 = DocumentRAGEngine(storage_dir=storage_dir, allow_remote_models=False)
    search = asyncio.run(engine2.search("autograd gpu acceleration", top_k=2))
    assert search["success"] is True
    assert search["results"]
    assert "pytorch" in search["results"][0]["source_name"].lower() or "ml.txt" in search["results"][0]["source_name"].lower()


def test_document_summarizer_prefers_rag(monkeypatch, tmp_path: Path):
    storage_dir = tmp_path / "rag"
    doc = tmp_path / "report.txt"
    doc.write_text(
        "PyTorch is an open source machine learning framework.\n"
        "It supports dynamic computation graphs.\n"
        "TorchVision and TorchText extend the ecosystem.\n"
        "The community and documentation are widely used.",
        encoding="utf-8",
    )

    engine = DocumentRAGEngine(storage_dir=storage_dir, allow_remote_models=False)
    monkeypatch.setattr("tools.research_tools.document_rag.get_document_rag_engine", lambda storage_dir=None: engine)

    result = asyncio.run(summarize_document(path=str(doc), style="detailed"))
    assert result["success"] is True
    assert result["summary_kind"] in {"extractive", "hybrid", "rag", "llm_fallback"}
    assert len(result["summary"]) > 120
    assert result.get("highlights")

