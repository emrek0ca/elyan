"""
Analytics Engine - Real-time metrics and business intelligence
"""

import logging
from typing import Dict, List, Any
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Tracks and analyzes metrics"""

    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.events: List[Dict] = []
        self.roi_data: Dict[str, Dict] = {}

    def record_metric(self, name: str, value: float):
        """Record a metric"""
        self.metrics[name].append(value)
        self.events.append({
            "type": "metric",
            "name": name,
            "value": value,
            "timestamp": datetime.now().isoformat()
        })

    def record_operation(self, operation: str, cost: float, duration: float, success: bool):
        """Record operation with cost tracking"""
        self.events.append({
            "type": "operation",
            "operation": operation,
            "cost": cost,
            "duration": duration,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })

        # Calculate ROI
        if success:
            self.roi_data[operation] = {
                "cost": cost,
                "duration": duration,
                "roi": 1.0 if cost > 0 else 0.0
            }

    def get_metrics_summary(self) -> Dict:
        """Get summary of metrics"""
        summary = {}
        for name, values in self.metrics.items():
            summary[name] = {
                "count": len(values),
                "avg": sum(values) / len(values) if values else 0,
                "min": min(values) if values else 0,
                "max": max(values) if values else 0
            }
        return summary

    def get_cost_analysis(self) -> Dict:
        """Analyze costs"""
        total_cost = sum(e["cost"] for e in self.events if e["type"] == "operation")
        operation_costs = defaultdict(float)

        for event in self.events:
            if event["type"] == "operation":
                operation_costs[event["operation"]] += event["cost"]

        return {
            "total_cost": total_cost,
            "by_operation": dict(operation_costs),
            "estimated_monthly": total_cost * 30
        }

    def get_performance_report(self) -> Dict:
        """Get performance metrics"""
        successful_ops = sum(1 for e in self.events if e.get("success"))
        total_ops = sum(1 for e in self.events if e["type"] == "operation")

        return {
            "success_rate": successful_ops / total_ops if total_ops > 0 else 0,
            "total_operations": total_ops,
            "avg_duration": sum(e["duration"] for e in self.events if "duration" in e) / total_ops if total_ops > 0 else 0
        }
