"""
Documentation Generator - Auto-generate API docs, guides, and training materials
Supports Markdown, HTML, and PDF output formats
"""

import json
import logging
import inspect
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class OutputFormat(Enum):
    """Output formats"""
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    JSON = "json"


@dataclass
class APIEndpoint:
    """API endpoint documentation"""
    name: str
    method: str  # GET, POST, etc.
    path: str
    description: str
    parameters: List[Dict[str, str]]  # name, type, description
    request_body: Optional[Dict] = None
    response: Optional[Dict] = None
    examples: List[Dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClassDocumentation:
    """Class documentation"""
    name: str
    module: str
    description: str
    methods: List[Dict]
    attributes: List[Dict]
    examples: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GuideSection:
    """Documentation guide section"""
    title: str
    content: str
    subsections: List['GuideSection'] = None
    code_examples: List[Dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "subsections": [s.to_dict() for s in (self.subsections or [])],
            "code_examples": self.code_examples or []
        }


class MarkdownGenerator:
    """Generate Markdown documentation"""

    @staticmethod
    def generate_api_docs(endpoints: List[APIEndpoint]) -> str:
        """Generate API documentation in Markdown"""
        lines = ["# API Documentation\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")

        for endpoint in endpoints:
            lines.append(f"## {endpoint.name}\n")
            lines.append(f"**Method:** `{endpoint.method}`\n")
            lines.append(f"**Path:** `{endpoint.path}`\n\n")
            lines.append(f"{endpoint.description}\n\n")

            if endpoint.parameters:
                lines.append("### Parameters\n")
                lines.append("| Name | Type | Description |\n")
                lines.append("|------|------|-------------|\n")
                for param in endpoint.parameters:
                    lines.append(
                        f"| {param.get('name', '')} | {param.get('type', '')} | "
                        f"{param.get('description', '')} |\n"
                    )
                lines.append("\n")

            if endpoint.request_body:
                lines.append("### Request Body\n")
                lines.append("```json\n")
                lines.append(json.dumps(endpoint.request_body, indent=2))
                lines.append("\n```\n\n")

            if endpoint.response:
                lines.append("### Response\n")
                lines.append("```json\n")
                lines.append(json.dumps(endpoint.response, indent=2))
                lines.append("\n```\n\n")

            if endpoint.examples:
                lines.append("### Examples\n")
                for i, example in enumerate(endpoint.examples, 1):
                    lines.append(f"#### Example {i}\n")
                    if "description" in example:
                        lines.append(f"{example['description']}\n\n")
                    if "curl" in example:
                        lines.append("```bash\n")
                        lines.append(example["curl"])
                        lines.append("\n```\n\n")

        return "".join(lines)

    @staticmethod
    def generate_class_docs(class_doc: ClassDocumentation) -> str:
        """Generate class documentation in Markdown"""
        lines = [f"# {class_doc.name}\n"]
        lines.append(f"**Module:** `{class_doc.module}`\n\n")
        lines.append(f"{class_doc.description}\n\n")

        if class_doc.attributes:
            lines.append("## Attributes\n")
            for attr in class_doc.attributes:
                lines.append(f"- **{attr.get('name', '')}** ({attr.get('type', '')}): {attr.get('description', '')}\n")
            lines.append("\n")

        if class_doc.methods:
            lines.append("## Methods\n")
            for method in class_doc.methods:
                lines.append(f"### {method.get('name', '')}()\n")
                lines.append(f"{method.get('description', '')}\n\n")
                if "parameters" in method:
                    lines.append("**Parameters:**\n")
                    for param in method["parameters"]:
                        lines.append(f"- `{param.get('name', '')}` ({param.get('type', '')}): {param.get('description', '')}\n")
                    lines.append("\n")
                if "returns" in method:
                    lines.append(f"**Returns:** {method['returns']}\n\n")

        if class_doc.examples:
            lines.append("## Examples\n")
            for i, example in enumerate(class_doc.examples, 1):
                lines.append(f"### Example {i}\n")
                lines.append("```python\n")
                lines.append(example)
                lines.append("\n```\n\n")

        return "".join(lines)

    @staticmethod
    def generate_guide(sections: List[GuideSection]) -> str:
        """Generate guide in Markdown"""
        lines = []

        def process_section(section: GuideSection, level: int = 1):
            lines.append(f"{'#' * level} {section.title}\n\n")
            lines.append(f"{section.content}\n\n")

            if section.code_examples:
                lines.append("### Code Examples\n")
                for example in section.code_examples:
                    if "description" in example:
                        lines.append(f"{example['description']}\n\n")
                    if "code" in example:
                        lines.append("```python\n")
                        lines.append(example["code"])
                        lines.append("\n```\n\n")

            if section.subsections:
                for subsection in section.subsections:
                    process_section(subsection, level + 1)

        for section in sections:
            process_section(section)

        return "".join(lines)


class HTMLGenerator:
    """Generate HTML documentation"""

    HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1, h2, h3 {{
            color: #333;
            border-bottom: 2px solid #007acc;
            padding-bottom: 10px;
        }}
        h1 {{
            font-size: 32px;
        }}
        h2 {{
            font-size: 24px;
            margin-top: 30px;
        }}
        h3 {{
            font-size: 18px;
            border: none;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "Courier New", monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background: #007acc;
            color: white;
        }}
        .timestamp {{
            color: #666;
            font-size: 12px;
            margin-top: 20px;
            border-top: 1px solid #eee;
            padding-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        {content}
        <div class="timestamp">Generated: {timestamp}</div>
    </div>
</body>
</html>
"""

    @staticmethod
    def generate_html(title: str, markdown_content: str) -> str:
        """Convert markdown to HTML and wrap in template - safely escaping content"""
        # Security: Always escape user content first to prevent XSS
        safe_title = escape(title)

        # Use basic safe markdown conversion
        # This is a simplified version - for production, use 'markdown' or 'mistune' library
        content = markdown_content

        # Escape HTML entities FIRST
        content = escape(content)

        # Then apply safe conversions (content is now HTML-escaped)
        # Replace escaped versions of code markers back
        content = content.replace("&lt;code&gt;", "<code>")
        content = content.replace("&lt;/code&gt;", "</code>")
        content = content.replace("&lt;pre&gt;", "<pre>")
        content = content.replace("&lt;/pre&gt;", "</pre>")

        # Safe header conversion (after escaping)
        import re
        for i in range(6, 0, -1):
            pattern = f"^{'#' * i} (.+)$"
            content = re.sub(pattern, f"<h{i}>\\1</h{i}>", content, flags=re.MULTILINE)

        return HTMLGenerator.HTML_TEMPLATE.format(
            title=safe_title,
            content=content,
            timestamp=datetime.now().isoformat()
        )


class DocumentationGenerator:
    """Main documentation generator"""

    def __init__(self, output_dir: str = ".elyan/docs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_api_documentation(self, endpoints: List[APIEndpoint],
                                  format: OutputFormat = OutputFormat.MARKDOWN) -> str:
        """Generate API documentation"""
        if format == OutputFormat.MARKDOWN:
            content = MarkdownGenerator.generate_api_docs(endpoints)
            output_file = self.output_dir / "api.md"
        elif format == OutputFormat.HTML:
            md_content = MarkdownGenerator.generate_api_docs(endpoints)
            content = HTMLGenerator.generate_html("API Documentation", md_content)
            output_file = self.output_dir / "api.html"
        elif format == OutputFormat.JSON:
            content = json.dumps([e.to_dict() for e in endpoints], indent=2)
            output_file = self.output_dir / "api.json"
        else:
            return ""

        with open(output_file, "w") as f:
            f.write(content)

        logger.info(f"Generated API docs: {output_file}")
        return str(output_file)

    def generate_guide(self, title: str, sections: List[GuideSection],
                      format: OutputFormat = OutputFormat.MARKDOWN) -> str:
        """Generate user guide"""
        if format == OutputFormat.MARKDOWN:
            content = MarkdownGenerator.generate_guide(sections)
            output_file = self.output_dir / "guide.md"
        elif format == OutputFormat.HTML:
            md_content = MarkdownGenerator.generate_guide(sections)
            content = HTMLGenerator.generate_html(title, md_content)
            output_file = self.output_dir / "guide.html"
        elif format == OutputFormat.JSON:
            content = json.dumps([s.to_dict() for s in sections], indent=2)
            output_file = self.output_dir / "guide.json"
        else:
            return ""

        with open(output_file, "w") as f:
            f.write(content)

        logger.info(f"Generated guide: {output_file}")
        return str(output_file)

    def generate_training_materials(self) -> Dict[str, str]:
        """Generate comprehensive training materials"""
        materials = {}

        # Quick start guide
        quick_start = [
            GuideSection(
                title="Getting Started",
                content="This guide will help you get started with Elyan in 5 minutes.",
                code_examples=[
                    {
                        "description": "Install and import Elyan",
                        "code": "from elyan import AgentIntegrationAdapter\nadapter = AgentIntegrationAdapter.get_adapter()"
                    }
                ]
            ),
            GuideSection(
                title="Configuration",
                content="Configure Elyan for your use case.",
                code_examples=[
                    {
                        "description": "Set up basic configuration",
                        "code": "adapter.configure({'model': 'gpt-4', 'temperature': 0.7})"
                    }
                ]
            )
        ]

        quickstart_file = self.generate_guide("Quick Start", quick_start)
        materials["quick_start"] = quickstart_file

        # Best practices
        practices = [
            GuideSection(
                title="Best Practices",
                content="Follow these practices for optimal results.",
                subsections=[
                    GuideSection(
                        title="Error Handling",
                        content="Always handle errors gracefully."
                    ),
                    GuideSection(
                        title="Performance",
                        content="Optimize for performance with caching and batching."
                    )
                ]
            )
        ]

        practices_file = self.generate_guide("Best Practices", practices)
        materials["best_practices"] = practices_file

        # API reference
        endpoints = [
            APIEndpoint(
                name="Process Request",
                method="POST",
                path="/api/process",
                description="Process a user request",
                parameters=[
                    {"name": "input", "type": "string", "description": "User input"},
                    {"name": "context", "type": "object", "description": "Optional context"}
                ],
                request_body={"input": "string", "context": {}},
                response={"status": "string", "result": "object"}
            )
        ]

        api_file = self.generate_api_documentation(endpoints)
        materials["api_reference"] = api_file

        return materials

    def get_status(self) -> Dict[str, Any]:
        """Get generator status"""
        docs = list(self.output_dir.glob("*"))
        return {
            "timestamp": datetime.now().isoformat(),
            "output_directory": str(self.output_dir),
            "generated_files": [str(f.name) for f in docs],
            "total_files": len(docs)
        }

    def __repr__(self) -> str:
        return f"<DocumentationGenerator output_dir={self.output_dir}>"
