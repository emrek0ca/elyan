"""
Chart Generator - Create visualizations from data
Supports various chart types and data sources
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
from utils.logger import get_logger

logger = get_logger("chart_generator")


class ChartType(Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    AREA = "area"
    HORIZONTAL_BAR = "horizontal_bar"
    DONUT = "donut"
    RADAR = "radar"
    HISTOGRAM = "histogram"


@dataclass
class ChartConfig:
    """Chart configuration"""
    title: str
    chart_type: ChartType
    width: int = 800
    height: int = 600
    colors: List[str] = None
    show_legend: bool = True
    show_grid: bool = True
    animation: bool = False
    theme: str = "default"  # default, dark, minimal

    def __post_init__(self):
        if self.colors is None:
            self.colors = [
                "#3498db", "#2ecc71", "#e74c3c", "#f39c12",
                "#9b59b6", "#1abc9c", "#34495e", "#e67e22"
            ]


class ChartGenerator:
    """Generate charts and visualizations"""

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir) if output_dir else Path.home() / "Desktop" / "ElyanCharts"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check for matplotlib availability
        self.has_matplotlib = self._check_matplotlib()

    def _check_matplotlib(self) -> bool:
        """Check if matplotlib is available"""
        try:
            import matplotlib
            return True
        except ImportError:
            logger.warning("matplotlib not installed, using text-based charts")
            return False

    def create_chart(
        self,
        data: Dict[str, Any],
        config: ChartConfig
    ) -> Dict[str, Any]:
        """
        Create a chart from data

        Args:
            data: Chart data with labels and values
            config: Chart configuration

        Returns:
            Result with chart path and info
        """
        try:
            if self.has_matplotlib:
                return self._create_matplotlib_chart(data, config)
            else:
                return self._create_text_chart(data, config)

        except Exception as e:
            logger.error(f"Chart creation error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _create_matplotlib_chart(
        self,
        data: Dict[str, Any],
        config: ChartConfig
    ) -> Dict[str, Any]:
        """Create chart using matplotlib"""
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt

        # Extract data
        labels = data.get("labels", [])
        values = data.get("values", [])
        datasets = data.get("datasets", [{"values": values}])

        # Create figure
        fig, ax = plt.subplots(figsize=(config.width/100, config.height/100))

        # Apply theme
        if config.theme == "dark":
            plt.style.use('dark_background')
        elif config.theme == "minimal":
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

        # Create chart based on type
        if config.chart_type == ChartType.BAR:
            self._create_bar_chart(ax, labels, datasets, config)
        elif config.chart_type == ChartType.HORIZONTAL_BAR:
            self._create_horizontal_bar_chart(ax, labels, datasets, config)
        elif config.chart_type == ChartType.LINE:
            self._create_line_chart(ax, labels, datasets, config)
        elif config.chart_type == ChartType.PIE:
            self._create_pie_chart(ax, labels, values, config)
        elif config.chart_type == ChartType.DONUT:
            self._create_donut_chart(ax, labels, values, config)
        elif config.chart_type == ChartType.SCATTER:
            self._create_scatter_chart(ax, data, config)
        elif config.chart_type == ChartType.AREA:
            self._create_area_chart(ax, labels, datasets, config)
        elif config.chart_type == ChartType.RADAR:
            self._create_radar_chart(fig, labels, datasets, config)
        elif config.chart_type == ChartType.HISTOGRAM:
            self._create_histogram(ax, values, config)

        # Set title
        ax.set_title(config.title, fontsize=14, fontweight='bold')

        # Grid
        if config.show_grid and config.chart_type not in [ChartType.PIE, ChartType.DONUT, ChartType.RADAR]:
            ax.grid(True, alpha=0.3)

        # Legend
        if config.show_legend and len(datasets) > 1:
            ax.legend()

        plt.tight_layout()

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chart_{config.chart_type.value}_{timestamp}.png"
        filepath = self.output_dir / filename
        plt.savefig(str(filepath), dpi=150, bbox_inches='tight')
        plt.close()

        return {
            "success": True,
            "path": str(filepath),
            "filename": filename,
            "chart_type": config.chart_type.value,
            "title": config.title,
            "data_points": len(labels) if labels else len(values),
            "message": f"Grafik oluşturuldu: {filename}"
        }

    def _create_bar_chart(self, ax, labels, datasets, config):
        """Create vertical bar chart"""
        import numpy as np

        x = np.arange(len(labels))
        width = 0.8 / len(datasets)

        for i, dataset in enumerate(datasets):
            offset = (i - len(datasets)/2 + 0.5) * width
            values = dataset.get("values", [])
            label = dataset.get("label", f"Veri {i+1}")
            color = config.colors[i % len(config.colors)]
            ax.bar(x + offset, values, width, label=label, color=color)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha='right')

    def _create_horizontal_bar_chart(self, ax, labels, datasets, config):
        """Create horizontal bar chart"""
        import numpy as np

        y = np.arange(len(labels))
        height = 0.8 / len(datasets)

        for i, dataset in enumerate(datasets):
            offset = (i - len(datasets)/2 + 0.5) * height
            values = dataset.get("values", [])
            label = dataset.get("label", f"Veri {i+1}")
            color = config.colors[i % len(config.colors)]
            ax.barh(y + offset, values, height, label=label, color=color)

        ax.set_yticks(y)
        ax.set_yticklabels(labels)

    def _create_line_chart(self, ax, labels, datasets, config):
        """Create line chart"""
        for i, dataset in enumerate(datasets):
            values = dataset.get("values", [])
            label = dataset.get("label", f"Veri {i+1}")
            color = config.colors[i % len(config.colors)]
            ax.plot(labels, values, marker='o', label=label, color=color, linewidth=2)

        ax.tick_params(axis='x', rotation=45)

    def _create_pie_chart(self, ax, labels, values, config):
        """Create pie chart"""
        colors = config.colors[:len(values)]
        explode = [0.02] * len(values)

        ax.pie(values, labels=labels, colors=colors, explode=explode,
               autopct='%1.1f%%', startangle=90)
        ax.axis('equal')

    def _create_donut_chart(self, ax, labels, values, config):
        """Create donut chart"""
        colors = config.colors[:len(values)]

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, colors=colors,
            autopct='%1.1f%%', startangle=90,
            pctdistance=0.75
        )

        # Add center circle for donut effect
        centre_circle = plt.Circle((0, 0), 0.5, fc='white')
        ax.add_artist(centre_circle)
        ax.axis('equal')

    def _create_scatter_chart(self, ax, data, config):
        """Create scatter plot"""
        x_values = data.get("x", [])
        y_values = data.get("y", [])

        ax.scatter(x_values, y_values, c=config.colors[0], alpha=0.6, s=50)
        ax.set_xlabel(data.get("x_label", "X"))
        ax.set_ylabel(data.get("y_label", "Y"))

    def _create_area_chart(self, ax, labels, datasets, config):
        """Create area chart"""
        for i, dataset in enumerate(datasets):
            values = dataset.get("values", [])
            label = dataset.get("label", f"Veri {i+1}")
            color = config.colors[i % len(config.colors)]
            ax.fill_between(range(len(labels)), values, alpha=0.3, color=color)
            ax.plot(labels, values, label=label, color=color, linewidth=2)

        ax.tick_params(axis='x', rotation=45)

    def _create_radar_chart(self, fig, labels, datasets, config):
        """Create radar/spider chart"""
        import numpy as np

        # Clear figure and create polar axes
        fig.clear()
        ax = fig.add_subplot(111, polar=True)

        # Number of variables
        num_vars = len(labels)
        angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
        angles += angles[:1]  # Complete the loop

        for i, dataset in enumerate(datasets):
            values = dataset.get("values", [])
            values += values[:1]  # Complete the loop
            label = dataset.get("label", f"Veri {i+1}")
            color = config.colors[i % len(config.colors)]

            ax.plot(angles, values, 'o-', linewidth=2, label=label, color=color)
            ax.fill(angles, values, alpha=0.25, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels)

    def _create_histogram(self, ax, values, config):
        """Create histogram"""
        ax.hist(values, bins='auto', color=config.colors[0], alpha=0.7, edgecolor='white')
        ax.set_xlabel("Değer")
        ax.set_ylabel("Frekans")

    def _create_text_chart(
        self,
        data: Dict[str, Any],
        config: ChartConfig
    ) -> Dict[str, Any]:
        """Create text-based chart (fallback when matplotlib unavailable)"""
        labels = data.get("labels", [])
        values = data.get("values", [])

        if not values:
            return {"success": False, "error": "Veri bulunamadı"}

        # Generate text representation
        lines = []
        lines.append(f"═" * 50)
        lines.append(f"  {config.title}")
        lines.append(f"═" * 50)
        lines.append("")

        max_value = max(values) if values else 1
        max_bar_width = 40

        if config.chart_type in [ChartType.BAR, ChartType.HORIZONTAL_BAR]:
            for i, (label, value) in enumerate(zip(labels, values)):
                bar_width = int((value / max_value) * max_bar_width)
                bar = "█" * bar_width
                lines.append(f"{label[:15]:15} | {bar} {value}")

        elif config.chart_type == ChartType.PIE:
            total = sum(values)
            lines.append("  Kategori        | Yüzde   | Değer")
            lines.append("  " + "─" * 40)
            for label, value in zip(labels, values):
                pct = (value / total) * 100
                lines.append(f"  {label[:15]:15} | %{pct:5.1f}  | {value}")

        else:
            # Generic text output
            for i, (label, value) in enumerate(zip(labels, values)):
                lines.append(f"  {label}: {value}")

        lines.append("")
        lines.append(f"─" * 50)
        lines.append(f"  Grafik Türü: {config.chart_type.value}")
        lines.append(f"  Veri Noktası: {len(labels)}")
        lines.append(f"═" * 50)

        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chart_{config.chart_type.value}_{timestamp}.txt"
        filepath = self.output_dir / filename
        filepath.write_text("\n".join(lines), encoding="utf-8")

        return {
            "success": True,
            "path": str(filepath),
            "filename": filename,
            "chart_type": config.chart_type.value,
            "title": config.title,
            "data_points": len(labels),
            "text_output": "\n".join(lines),
            "message": f"Metin grafiği oluşturuldu: {filename}"
        }

    def create_research_visualization(
        self,
        research_data: Dict[str, Any],
        output_format: str = "png"
    ) -> Dict[str, Any]:
        """
        Create visualizations from research data

        Args:
            research_data: Research results from deep_research
            output_format: Output format (png/html/txt)

        Returns:
            Result with visualization paths
        """
        results = {
            "success": True,
            "charts": [],
            "messages": []
        }

        try:
            statistics = research_data.get("statistics", {})
            findings = research_data.get("findings", [])
            sources = research_data.get("sources", [])
            topic = research_data.get("topic", "Araştırma")

            # 1. Source Types Distribution (Pie Chart)
            source_types = statistics.get("source_types", {})
            if source_types:
                labels = []
                values = []
                type_names = {
                    "academic": "Akademik",
                    "news": "Haber",
                    "wiki": "Vikipedi",
                    "web": "Web"
                }
                for stype, count in source_types.items():
                    if count > 0:
                        labels.append(type_names.get(stype, stype))
                        values.append(count)

                if labels:
                    config = ChartConfig(
                        title=f"{topic} - Kaynak Dağılımı",
                        chart_type=ChartType.PIE
                    )
                    chart_result = self.create_chart(
                        {"labels": labels, "values": values},
                        config
                    )
                    if chart_result.get("success"):
                        results["charts"].append(chart_result)

            # 2. Finding Categories (Bar Chart)
            finding_cats = statistics.get("finding_categories", {})
            if finding_cats:
                cat_names = {
                    "definition": "Tanımlar",
                    "statistics": "İstatistikler",
                    "research": "Araştırmalar",
                    "expert_opinion": "Uzman Görüşleri",
                    "historical": "Tarihsel",
                    "general": "Genel"
                }
                labels = [cat_names.get(c, c) for c in finding_cats.keys()]
                values = list(finding_cats.values())

                config = ChartConfig(
                    title=f"{topic} - Bulgu Kategorileri",
                    chart_type=ChartType.BAR
                )
                chart_result = self.create_chart(
                    {"labels": labels, "values": values},
                    config
                )
                if chart_result.get("success"):
                    results["charts"].append(chart_result)

            # 3. Source Reliability (Horizontal Bar)
            if sources:
                # Top 10 sources by reliability
                sorted_sources = sorted(
                    sources,
                    key=lambda s: s.get("reliability_score", 0),
                    reverse=True
                )[:10]

                labels = [s.get("domain", "Unknown")[:20] for s in sorted_sources]
                values = [s.get("reliability_score", 0) * 100 for s in sorted_sources]

                config = ChartConfig(
                    title=f"{topic} - Kaynak Güvenilirliği",
                    chart_type=ChartType.HORIZONTAL_BAR,
                    height=500
                )
                chart_result = self.create_chart(
                    {"labels": labels, "values": values, "datasets": [{"values": values}]},
                    config
                )
                if chart_result.get("success"):
                    results["charts"].append(chart_result)

            # 4. Finding Importance Distribution
            if findings:
                importance_counts = {}
                for f in findings:
                    imp = f.get("importance", 1)
                    importance_counts[imp] = importance_counts.get(imp, 0) + 1

                labels = [f"Önem {i}" for i in sorted(importance_counts.keys())]
                values = [importance_counts[i] for i in sorted(importance_counts.keys())]

                config = ChartConfig(
                    title=f"{topic} - Bulgu Önem Dağılımı",
                    chart_type=ChartType.BAR
                )
                chart_result = self.create_chart(
                    {"labels": labels, "values": values},
                    config
                )
                if chart_result.get("success"):
                    results["charts"].append(chart_result)

            results["message"] = f"{len(results['charts'])} görselleştirme oluşturuldu"

        except Exception as e:
            logger.error(f"Research visualization error: {e}")
            results["success"] = False
            results["error"] = str(e)

        return results


# Singleton instance
_generator_instance = None


def get_chart_generator() -> ChartGenerator:
    """Get or create chart generator instance"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ChartGenerator()
    return _generator_instance


async def create_chart(
    data: Dict[str, Any],
    chart_type: str = "bar",
    title: str = "Grafik",
    width: int = 800,
    height: int = 600,
    theme: str = "default"
) -> Dict[str, Any]:
    """
    Create a chart from data

    Args:
        data: Chart data with labels and values
        chart_type: Type of chart (bar/line/pie/scatter/area/donut/radar)
        title: Chart title
        width: Chart width
        height: Chart height
        theme: Chart theme (default/dark/minimal)

    Returns:
        Result with chart path
    """
    generator = get_chart_generator()

    type_map = {
        "bar": ChartType.BAR,
        "line": ChartType.LINE,
        "pie": ChartType.PIE,
        "scatter": ChartType.SCATTER,
        "area": ChartType.AREA,
        "horizontal_bar": ChartType.HORIZONTAL_BAR,
        "donut": ChartType.DONUT,
        "radar": ChartType.RADAR,
        "histogram": ChartType.HISTOGRAM
    }

    config = ChartConfig(
        title=title,
        chart_type=type_map.get(chart_type.lower(), ChartType.BAR),
        width=width,
        height=height,
        theme=theme
    )

    return generator.create_chart(data, config)


async def create_research_visualization(
    research_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create visualizations from research data

    Args:
        research_data: Research results

    Returns:
        Result with visualization paths
    """
    generator = get_chart_generator()
    return generator.create_research_visualization(research_data)
