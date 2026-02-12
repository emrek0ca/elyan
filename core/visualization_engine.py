"""
Data Visualization Engine
Charts, graphs, dashboards with text and image output
"""

import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
import json

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("visualization")


@dataclass
class ChartConfig:
    """Chart configuration"""
    title: str
    chart_type: str  # bar, line, pie, scatter, histogram
    data: Dict[str, Any]
    width: int = 80
    height: int = 20
    colors: Optional[List[str]] = None


class VisualizationEngine:
    """
    Data Visualization Engine
    - Text-based charts (ASCII art)
    - Image-based charts (matplotlib optional)
    - Bar charts, line charts, pie charts
    - Real-time dashboards
    - Export to PNG/SVG
    """

    def __init__(self):
        self.charts: Dict[str, ChartConfig] = {}
        self.output_dir = HOME_DIR / ".wiqo" / "visualizations"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if matplotlib is available
        try:
            import matplotlib
            self.has_matplotlib = True
        except ImportError:
            self.has_matplotlib = False
            logger.info("Matplotlib not available, using text-based visualizations")

        logger.info("Visualization Engine initialized")

    def create_bar_chart(
        self,
        data: Dict[str, float],
        title: str = "Bar Chart",
        text_mode: bool = True
    ) -> str:
        """Create a bar chart"""
        if text_mode or not self.has_matplotlib:
            return self._text_bar_chart(data, title)
        else:
            return self._image_bar_chart(data, title)

    def _text_bar_chart(
        self,
        data: Dict[str, float],
        title: str,
        width: int = 60
    ) -> str:
        """Create text-based bar chart"""
        if not data:
            return "No data to display"

        max_value = max(data.values()) if data.values() else 1
        max_label_len = max(len(str(k)) for k in data.keys())

        lines = []
        lines.append(f"\n{title}")
        lines.append("=" * (width + max_label_len + 5))

        for label, value in data.items():
            bar_length = int((value / max_value) * width) if max_value > 0 else 0
            bar = "█" * bar_length
            lines.append(f"{label:>{max_label_len}} | {bar} {value:.1f}")

        lines.append("=" * (width + max_label_len + 5))

        return "\n".join(lines)

    def _image_bar_chart(
        self,
        data: Dict[str, float],
        title: str
    ) -> str:
        """Create image-based bar chart"""
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 6))

            labels = list(data.keys())
            values = list(data.values())

            ax.bar(labels, values)
            ax.set_title(title)
            ax.set_xlabel('Categories')
            ax.set_ylabel('Values')

            # Rotate labels if many
            if len(labels) > 5:
                plt.xticks(rotation=45, ha='right')

            plt.tight_layout()

            # Save to file
            filename = f"bar_chart_{int(time.time())}.png"
            filepath = self.output_dir / filename
            plt.savefig(filepath)
            plt.close()

            return str(filepath)

        except Exception as e:
            logger.error(f"Image chart creation failed: {e}")
            return self._text_bar_chart(data, title)

    def create_line_chart(
        self,
        data: Dict[str, List[float]],
        title: str = "Line Chart",
        text_mode: bool = True
    ) -> str:
        """Create a line chart"""
        if text_mode or not self.has_matplotlib:
            return self._text_line_chart(data, title)
        else:
            return self._image_line_chart(data, title)

    def _text_line_chart(
        self,
        data: Dict[str, List[float]],
        title: str,
        width: int = 60,
        height: int = 15
    ) -> str:
        """Create text-based line chart"""
        if not data:
            return "No data to display"

        lines = []
        lines.append(f"\n{title}")
        lines.append("=" * width)

        # Simple ASCII line chart
        for series_name, values in data.items():
            if not values:
                continue

            min_val = min(values)
            max_val = max(values)
            range_val = max_val - min_val if max_val != min_val else 1

            # Normalize values to chart height
            normalized = [
                int(((v - min_val) / range_val) * (height - 1))
                for v in values
            ]

            # Create chart matrix
            matrix = [[' ' for _ in range(len(values))] for _ in range(height)]

            # Plot points
            for x, y in enumerate(normalized):
                matrix[height - 1 - y][x] = '●'

            # Draw connections
            for x in range(len(normalized) - 1):
                y1 = height - 1 - normalized[x]
                y2 = height - 1 - normalized[x + 1]

                if y1 != y2:
                    step = 1 if y2 > y1 else -1
                    for y in range(y1, y2, step):
                        matrix[y][x] = '│'

            # Add series name
            lines.append(f"\n{series_name}:")

            # Print matrix
            for row in matrix:
                lines.append(''.join(row))

            lines.append(f"Min: {min_val:.1f}  Max: {max_val:.1f}")

        lines.append("=" * width)

        return "\n".join(lines)

    def _image_line_chart(
        self,
        data: Dict[str, List[float]],
        title: str
    ) -> str:
        """Create image-based line chart"""
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 6))

            for series_name, values in data.items():
                ax.plot(values, label=series_name, marker='o')

            ax.set_title(title)
            ax.set_xlabel('Index')
            ax.set_ylabel('Value')
            ax.legend()
            ax.grid(True, alpha=0.3)

            plt.tight_layout()

            filename = f"line_chart_{int(time.time())}.png"
            filepath = self.output_dir / filename
            plt.savefig(filepath)
            plt.close()

            return str(filepath)

        except Exception as e:
            logger.error(f"Image chart creation failed: {e}")
            return self._text_line_chart(data, title)

    def create_pie_chart(
        self,
        data: Dict[str, float],
        title: str = "Pie Chart",
        text_mode: bool = True
    ) -> str:
        """Create a pie chart"""
        if text_mode or not self.has_matplotlib:
            return self._text_pie_chart(data, title)
        else:
            return self._image_pie_chart(data, title)

    def _text_pie_chart(
        self,
        data: Dict[str, float],
        title: str
    ) -> str:
        """Create text-based pie chart"""
        if not data:
            return "No data to display"

        total = sum(data.values())
        if total == 0:
            return "No data to display"

        lines = []
        lines.append(f"\n{title}")
        lines.append("=" * 50)

        for label, value in sorted(data.items(), key=lambda x: x[1], reverse=True):
            percentage = (value / total) * 100
            bar_length = int(percentage / 2)  # Max 50 chars
            bar = "█" * bar_length

            lines.append(f"{label:20} | {bar} {percentage:.1f}% ({value:.1f})")

        lines.append("=" * 50)
        lines.append(f"Total: {total:.1f}")

        return "\n".join(lines)

    def _image_pie_chart(
        self,
        data: Dict[str, float],
        title: str
    ) -> str:
        """Create image-based pie chart"""
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 8))

            labels = list(data.keys())
            values = list(data.values())

            ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
            ax.set_title(title)

            plt.tight_layout()

            filename = f"pie_chart_{int(time.time())}.png"
            filepath = self.output_dir / filename
            plt.savefig(filepath)
            plt.close()

            return str(filepath)

        except Exception as e:
            logger.error(f"Image chart creation failed: {e}")
            return self._text_pie_chart(data, title)

    def create_histogram(
        self,
        data: List[float],
        bins: int = 10,
        title: str = "Histogram",
        text_mode: bool = True
    ) -> str:
        """Create a histogram"""
        if text_mode or not self.has_matplotlib:
            return self._text_histogram(data, bins, title)
        else:
            return self._image_histogram(data, bins, title)

    def _text_histogram(
        self,
        data: List[float],
        bins: int,
        title: str
    ) -> str:
        """Create text-based histogram"""
        if not data:
            return "No data to display"

        min_val = min(data)
        max_val = max(data)
        bin_width = (max_val - min_val) / bins if max_val != min_val else 1

        # Create bins
        histogram = [0] * bins
        for value in data:
            bin_index = min(int((value - min_val) / bin_width), bins - 1)
            histogram[bin_index] += 1

        max_count = max(histogram) if histogram else 1

        lines = []
        lines.append(f"\n{title}")
        lines.append("=" * 60)

        for i, count in enumerate(histogram):
            bin_start = min_val + i * bin_width
            bin_end = bin_start + bin_width
            bar_length = int((count / max_count) * 40)
            bar = "█" * bar_length

            lines.append(f"{bin_start:8.1f} - {bin_end:8.1f} | {bar} {count}")

        lines.append("=" * 60)
        lines.append(f"Total values: {len(data)}")

        return "\n".join(lines)

    def _image_histogram(
        self,
        data: List[float],
        bins: int,
        title: str
    ) -> str:
        """Create image-based histogram"""
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 6))

            ax.hist(data, bins=bins, edgecolor='black')
            ax.set_title(title)
            ax.set_xlabel('Value')
            ax.set_ylabel('Frequency')
            ax.grid(True, alpha=0.3)

            plt.tight_layout()

            filename = f"histogram_{int(time.time())}.png"
            filepath = self.output_dir / filename
            plt.savefig(filepath)
            plt.close()

            return str(filepath)

        except Exception as e:
            logger.error(f"Image chart creation failed: {e}")
            return self._text_histogram(data, bins, title)

    def create_dashboard(
        self,
        charts: List[Dict[str, Any]],
        title: str = "Dashboard"
    ) -> str:
        """Create a dashboard with multiple charts"""
        lines = []
        lines.append(f"\n{'=' * 80}")
        lines.append(f"{title:^80}")
        lines.append(f"{'=' * 80}\n")

        for chart_config in charts:
            chart_type = chart_config.get("type", "bar")
            chart_title = chart_config.get("title", "Chart")
            chart_data = chart_config.get("data", {})

            if chart_type == "bar":
                chart_output = self.create_bar_chart(chart_data, chart_title, text_mode=True)
            elif chart_type == "line":
                chart_output = self.create_line_chart(chart_data, chart_title, text_mode=True)
            elif chart_type == "pie":
                chart_output = self.create_pie_chart(chart_data, chart_title, text_mode=True)
            else:
                chart_output = "Unknown chart type"

            lines.append(chart_output)
            lines.append("\n")

        lines.append(f"{'=' * 80}")
        lines.append(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"{'=' * 80}\n")

        return "\n".join(lines)

    def save_dashboard(
        self,
        dashboard_config: Dict[str, Any],
        filename: str
    ):
        """Save dashboard configuration"""
        filepath = self.output_dir / f"{filename}.json"

        with open(filepath, 'w') as f:
            json.dump(dashboard_config, f, indent=2)

        logger.info(f"Saved dashboard to {filepath}")

    def load_dashboard(self, filename: str) -> Optional[Dict[str, Any]]:
        """Load dashboard configuration"""
        filepath = self.output_dir / f"{filename}.json"

        if not filepath.exists():
            return None

        with open(filepath, 'r') as f:
            return json.load(f)

    def get_summary(self) -> Dict[str, Any]:
        """Get visualization engine summary"""
        return {
            "output_directory": str(self.output_dir),
            "matplotlib_available": self.has_matplotlib,
            "saved_charts": len(list(self.output_dir.glob("*.png"))),
            "saved_dashboards": len(list(self.output_dir.glob("*.json")))
        }


# Global instance
_visualization_engine: Optional[VisualizationEngine] = None


def get_visualization_engine() -> VisualizationEngine:
    """Get or create global visualization engine instance"""
    global _visualization_engine
    if _visualization_engine is None:
        _visualization_engine = VisualizationEngine()
    return _visualization_engine
