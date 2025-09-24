import time
from typing import Dict, Any
from collections import defaultdict, Counter

class MetricsCollector:
    def __init__(self):
        self.counters = defaultdict(int)
        self.gauges = {}
        self.histograms = defaultdict(list)
        self.start_time = time.time()
    
    def increment(self, metric_name: str, value: int = 1, labels: Dict[str, str] = None):
        """Increment a counter metric"""
        key = self._make_key(metric_name, labels)
        self.counters[key] += value
    
    def set_gauge(self, metric_name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge metric"""
        key = self._make_key(metric_name, labels)
        self.gauges[key] = value
    
    def record_histogram(self, metric_name: str, value: float, labels: Dict[str, str] = None):
        """Record a histogram value"""
        key = self._make_key(metric_name, labels)
        self.histograms[key].append(value)
        # Keep only last 1000 values
        if len(self.histograms[key]) > 1000:
            self.histograms[key] = self.histograms[key][-1000:]
    
    def _make_key(self, metric_name: str, labels: Dict[str, str] = None) -> str:
        if not labels:
            return metric_name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{metric_name}{{{label_str}}}"
    
    def get_metrics(self) -> Dict[str, Any]:
        """Return all metrics as JSON-serializable dict"""
        uptime = time.time() - self.start_time
        
        # Calculate histogram percentiles
        histogram_stats = {}
        for key, values in self.histograms.items():
            if values:
                sorted_values = sorted(values)
                n = len(sorted_values)
                histogram_stats[key] = {
                    "count": n,
                    "avg": sum(sorted_values) / n,
                    "p50": sorted_values[int(n * 0.5)] if n > 0 else 0,
                    "p95": sorted_values[int(n * 0.95)] if n > 0 else 0,
                    "p99": sorted_values[int(n * 0.99)] if n > 0 else 0,
                }
        
        return {
            "uptime_seconds": uptime,
            "timestamp": time.time(),
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "histograms": histogram_stats
        }

# Global metrics instance
metrics = MetricsCollector()