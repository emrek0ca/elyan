"""
Professional Report Visualizations
Generates charts, graphs, and visual metrics for research reports
"""

import io
import base64
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("report_visualizations")


@dataclass
class VisualizationConfig:
    """Visualization configuration"""
    style: str = "professional"  # professional, minimalist, colorful
    color_primary: str = "#2c3e50"
    color_secondary: str = "#3498db"
    color_accent: str = "#27ae60"
    font_family: str = "Arial, sans-serif"
    dpi: int = 300
    figure_width: float = 10
    figure_height: float = 6


class ReportVisualizations:
    """Professional visualization generator for reports"""

    def __init__(self, config: Optional[VisualizationConfig] = None):
        self.config = config or VisualizationConfig()
        self._import_matplotlib()

    def _import_matplotlib(self):
        """Safely import matplotlib"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            self.plt = plt
            self.matplotlib = matplotlib
            self.available = True
        except ImportError:
            logger.warning("matplotlib not available - text-based fallbacks will be used")
            self.available = False
            self.plt = None

    def generate_source_reliability_chart(
        self,
        sources: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Generate source reliability visualization
        Returns HTML SVG representation or base64 encoded image
        """
        if not sources or not self.available:
            return self._generate_text_reliability_table(sources)

        try:
            import matplotlib.pyplot as plt

            sorted_sources = sorted(
                sources,
                key=lambda x: x.get("reliability_score", 0),
                reverse=True
            )[:15]  # Top 15 sources

            fig, ax = plt.subplots(figsize=(12, 6))

            titles = [s.get("title", "Unknown")[:40] for s in sorted_sources]
            scores = [s.get("reliability_score", 0) * 100 for s in sorted_sources]

            bars = ax.barh(range(len(titles)), scores, color=self.config.color_secondary)

            # Color bars based on reliability
            for i, (bar, score) in enumerate(zip(bars, scores)):
                if score >= 80:
                    bar.set_color(self.config.color_accent)  # Green
                elif score >= 60:
                    bar.set_color(self.config.color_secondary)  # Blue
                else:
                    bar.set_color("#e74c3c")  # Red

            ax.set_yticks(range(len(titles)))
            ax.set_yticklabels(titles, fontsize=9)
            ax.set_xlabel("Reliability Score (%)", fontsize=10, fontweight="bold")
            ax.set_title("Source Reliability Analysis", fontsize=12, fontweight="bold", pad=20)
            ax.set_xlim(0, 100)

            # Add value labels on bars
            for i, score in enumerate(scores):
                ax.text(score + 2, i, f"{score:.0f}%", va="center", fontsize=8)

            ax.grid(axis="x", alpha=0.3)
            ax.set_axisbelow(True)

            plt.tight_layout()

            return self._figure_to_base64(fig)

        except Exception as e:
            logger.error(f"Failed to generate source reliability chart: {e}")
            return self._generate_text_reliability_table(sources)

    def generate_findings_distribution_chart(
        self,
        findings: List[str],
        categories: Optional[Dict[str, int]] = None
    ) -> Optional[str]:
        """
        Generate findings distribution visualization
        Shows number of findings per category or finding length distribution
        """
        if not findings or not self.available:
            return self._generate_text_findings_distribution(findings)

        try:
            import matplotlib.pyplot as plt

            if categories:
                return self._generate_category_pie_chart(categories)
            else:
                return self._generate_findings_bar_chart(findings)

        except Exception as e:
            logger.error(f"Failed to generate findings distribution: {e}")
            return self._generate_text_findings_distribution(findings)

    def _generate_category_pie_chart(self, categories: Dict[str, int]) -> Optional[str]:
        """Generate pie chart for categories"""
        try:
            fig, ax = self.plt.subplots(figsize=(10, 8))

            labels = list(categories.keys())
            sizes = list(categories.values())
            colors = [self.config.color_primary, self.config.color_secondary,
                     self.config.color_accent, "#e74c3c", "#f39c12"]
            colors = colors[:len(labels)]

            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=labels,
                autopct="%1.1f%%",
                colors=colors,
                startangle=90,
                textprops={"fontsize": 10}
            )

            for autotext in autotexts:
                autotext.set_color("white")
                autotext.set_fontweight("bold")

            ax.set_title("Findings Distribution by Category", fontsize=12, fontweight="bold", pad=20)

            self.plt.tight_layout()
            return self._figure_to_base64(fig)

        except Exception as e:
            logger.error(f"Failed to generate category pie chart: {e}")
            return None

    def _generate_findings_bar_chart(self, findings: List[str]) -> Optional[str]:
        """Generate bar chart for findings count"""
        try:
            fig, ax = self.plt.subplots(figsize=(10, 6))

            # Categorize by finding length/importance
            short = len([f for f in findings if len(f) < 50])
            medium = len([f for f in findings if 50 <= len(f) < 150])
            long = len([f for f in findings if len(f) >= 150])

            categories = ["Brief\nFindings", "Detailed\nFindings", "Comprehensive\nFindings"]
            counts = [short, medium, long]
            colors = [self.config.color_secondary, self.config.color_accent, self.config.color_primary]

            bars = ax.bar(categories, counts, color=colors, edgecolor="black", linewidth=1.5)

            ax.set_ylabel("Count", fontsize=10, fontweight="bold")
            ax.set_title("Findings by Depth", fontsize=12, fontweight="bold", pad=20)
            ax.set_ylim(0, max(counts) * 1.2)

            # Add value labels on bars
            for bar, count in zip(bars, counts):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f"{int(count)}",
                       ha="center", va="bottom", fontweight="bold")

            ax.grid(axis="y", alpha=0.3)
            ax.set_axisbelow(True)

            self.plt.tight_layout()
            return self._figure_to_base64(fig)

        except Exception as e:
            logger.error(f"Failed to generate findings bar chart: {e}")
            return None

    def generate_quality_metrics_visualization(
        self,
        coverage_score: float,
        reliability_score: float,
        completeness_score: float
    ) -> Optional[str]:
        """
        Generate quality metrics gauge visualization
        Shows coverage, reliability, and completeness scores
        """
        if not self.available:
            return self._generate_text_metrics(coverage_score, reliability_score, completeness_score)

        try:
            import matplotlib.pyplot as plt
            import numpy as np

            fig, axes = self.plt.subplots(1, 3, figsize=(14, 5), subplot_kw=dict(projection='polar'))

            metrics = [
                ("Coverage", coverage_score, self.config.color_secondary),
                ("Reliability", reliability_score, self.config.color_accent),
                ("Completeness", completeness_score, self.config.color_primary)
            ]

            for ax, (label, score, color) in zip(axes, metrics):
                # Create gauge
                theta = np.linspace(0, np.pi, 100)
                r = np.ones(100)

                ax.fill_between(theta, 0, r, color=color, alpha=0.3)
                ax.plot(theta, r, color=color, linewidth=2)

                # Add score indicator
                angle = (score / 100) * np.pi
                ax.plot([angle, angle], [0, 1], color=color, linewidth=3)
                ax.scatter([angle], [1], color=color, s=200, zorder=5)

                ax.set_ylim(0, 1.3)
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_title(f"{label}\n{score:.0f}%", fontsize=11, fontweight="bold", pad=20)
                ax.spines['polar'].set_visible(False)

            self.plt.tight_layout()
            return self._figure_to_base64(fig)

        except Exception as e:
            logger.error(f"Failed to generate quality metrics: {e}")
            return self._generate_text_metrics(coverage_score, reliability_score, completeness_score)

    def generate_research_timeline(
        self,
        started_at: Optional[str],
        completed_at: Optional[str]
    ) -> Optional[str]:
        """Generate research timeline visualization"""
        if not started_at or not completed_at or not self.available:
            return self._generate_text_timeline(started_at, completed_at)

        try:
            from datetime import datetime
            import matplotlib.pyplot as plt

            start = datetime.fromisoformat(started_at.replace("Z", "+00:00")) if isinstance(started_at, str) else started_at
            end = datetime.fromisoformat(completed_at.replace("Z", "+00:00")) if isinstance(completed_at, str) else completed_at
            duration = (end - start).total_seconds()

            fig, ax = self.plt.subplots(figsize=(12, 3))

            # Timeline bar
            ax.barh(0, duration, left=0, height=0.3, color=self.config.color_secondary, edgecolor="black", linewidth=2)

            # Add markers
            ax.scatter([0], [0], s=200, color=self.config.color_primary, marker="o", zorder=5)
            ax.scatter([duration], [0], s=200, color=self.config.color_accent, marker="s", zorder=5)

            # Labels
            ax.text(0, 0.25, f"Started\n{start.strftime('%H:%M:%S')}", ha="center", fontsize=9, fontweight="bold")
            ax.text(duration, 0.25, f"Completed\n{end.strftime('%H:%M:%S')}", ha="center", fontsize=9, fontweight="bold")
            ax.text(duration/2, -0.35, f"Duration: {duration:.0f}s", ha="center", fontsize=10, fontweight="bold")

            ax.set_xlim(-5, duration + 5)
            ax.set_ylim(-0.5, 0.5)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_visible(False)
            ax.spines['bottom'].set_visible(False)

            ax.set_title("Research Timeline", fontsize=12, fontweight="bold", pad=20)

            self.plt.tight_layout()
            return self._figure_to_base64(fig)

        except Exception as e:
            logger.error(f"Failed to generate timeline: {e}")
            return self._generate_text_timeline(started_at, completed_at)

    def _figure_to_base64(self, fig) -> Optional[str]:
        """Convert matplotlib figure to base64 PNG"""
        try:
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=self.config.dpi, bbox_inches="tight")
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.read()).decode()
            self.plt.close(fig)
            return f"data:image/png;base64,{image_base64}"
        except Exception as e:
            logger.error(f"Failed to convert figure to base64: {e}")
            return None

    def _generate_text_reliability_table(self, sources: List[Dict[str, Any]]) -> str:
        """Fallback: Generate text-based reliability table"""
        if not sources:
            return "<p>No sources available</p>"

        sorted_sources = sorted(
            sources,
            key=lambda x: x.get("reliability_score", 0),
            reverse=True
        )[:10]

        html = '<table style="width:100%; border-collapse:collapse; margin:20px 0;">'
        html += '<tr style="background:#2c3e50; color:white;"><th style="padding:10px; text-align:left;">Source</th><th style="padding:10px;">Reliability</th></tr>'

        for source in sorted_sources:
            score = source.get("reliability_score", 0) * 100
            title = source.get("title", "Unknown")[:50]
            color = "#27ae60" if score >= 80 else "#3498db" if score >= 60 else "#e74c3c"
            html += f'<tr style="border-bottom:1px solid #ecf0f1;"><td style="padding:10px;">{title}</td><td style="padding:10px; text-align:center; color:{color}; font-weight:bold;">{score:.0f}%</td></tr>'

        html += '</table>'
        return html

    def _generate_text_findings_distribution(self, findings: List[str]) -> str:
        """Fallback: Generate text-based findings distribution"""
        short = len([f for f in findings if len(f) < 50])
        medium = len([f for f in findings if 50 <= len(f) < 150])
        long = len([f for f in findings if len(f) >= 150])

        html = '<div style="margin:20px 0;">'
        html += f'<p><strong>Brief Findings:</strong> {short}</p>'
        html += f'<p><strong>Detailed Findings:</strong> {medium}</p>'
        html += f'<p><strong>Comprehensive Findings:</strong> {long}</p>'
        html += '</div>'
        return html

    def _generate_text_metrics(
        self,
        coverage: float,
        reliability: float,
        completeness: float
    ) -> str:
        """Fallback: Generate text-based metrics display"""
        html = '<div style="display:flex; gap:20px; margin:20px 0;">'

        def create_metric_box(label: str, value: float, color: str) -> str:
            return f'''
            <div style="flex:1; padding:20px; background:#f8f9fa; border-left:4px solid {color}; border-radius:4px;">
                <div style="font-weight:bold; color:#2c3e50; font-size:14px;">{label}</div>
                <div style="font-size:24px; font-weight:bold; color:{color}; margin-top:10px;">{value:.0f}%</div>
            </div>
            '''

        html += create_metric_box("Coverage", coverage, "#3498db")
        html += create_metric_box("Reliability", reliability, "#27ae60")
        html += create_metric_box("Completeness", completeness, "#2c3e50")
        html += '</div>'
        return html

    def _generate_text_timeline(self, started_at: Optional[str], completed_at: Optional[str]) -> str:
        """Fallback: Generate text-based timeline"""
        if not started_at or not completed_at:
            return "<p>Timeline data not available</p>"

        html = '<div style="margin:20px 0; padding:20px; background:#f8f9fa; border-radius:4px;">'
        html += f'<p><strong>Started:</strong> {started_at}</p>'
        html += f'<p><strong>Completed:</strong> {completed_at}</p>'
        html += '</div>'
        return html


class ReportChartBuilder:
    """Builder for creating complex multi-chart visualizations"""

    def __init__(self):
        self.viz = ReportVisualizations()

    def create_comprehensive_analysis_page(
        self,
        sources: List[Dict[str, Any]],
        findings: List[str],
        coverage_score: float,
        reliability_score: float,
        completeness_score: float
    ) -> Dict[str, str]:
        """Create complete analysis page with all visualizations"""
        return {
            "reliability_chart": self.viz.generate_source_reliability_chart(sources),
            "findings_chart": self.viz.generate_findings_distribution_chart(findings),
            "quality_metrics": self.viz.generate_quality_metrics_visualization(
                coverage_score,
                reliability_score,
                completeness_score
            )
        }

    def create_source_analysis_page(self, sources: List[Dict[str, Any]]) -> Dict[str, str]:
        """Create page focused on source analysis"""
        return {
            "reliability_chart": self.viz.generate_source_reliability_chart(sources),
            "reliability_table": self.viz._generate_text_reliability_table(sources)
        }

    def create_quality_dashboard(
        self,
        coverage_score: float,
        reliability_score: float,
        completeness_score: float,
        started_at: Optional[str],
        completed_at: Optional[str]
    ) -> Dict[str, str]:
        """Create quality dashboard with metrics and timeline"""
        return {
            "quality_metrics": self.viz.generate_quality_metrics_visualization(
                coverage_score,
                reliability_score,
                completeness_score
            ),
            "timeline": self.viz.generate_research_timeline(started_at, completed_at)
        }
