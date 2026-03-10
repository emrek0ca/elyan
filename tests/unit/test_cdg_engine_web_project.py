import asyncio

from core.cdg_engine import CDGEngine


def test_cdg_web_project_plan_uses_rich_portfolio_assets():
    engine = CDGEngine()

    plan = asyncio.run(
        engine.create_plan(
            "test_web_project",
            "web_project",
            "sari ve turuncu renklerde bir portfolyo sitesi yap",
        )
    )

    nodes = {node.id: node for node in plan.nodes}
    scaffold_params = nodes["scaffold"].params
    html_content = str(nodes["html"].params.get("content", ""))
    css_content = str(nodes["css"].params.get("content", ""))
    js_content = str(nodes["js"].params.get("content", ""))

    assert scaffold_params["project_name"] == "Sunset Portfolio"
    assert "Proje dosyalari Elyan CDG ile olusturuldu." not in html_content
    assert "portfolio-hero" in html_content
    assert "project-showcase" in html_content
    assert "#f59e0b" in css_content
    assert "#f97316" in css_content
    assert "DOMContentLoaded" in js_content
