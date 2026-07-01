"""services/visualization.py — Chart and report generation from JARVIS data."""
import json
import uuid
from pathlib import Path
from config.settings import BASE_DIR

CHARTS_DIR = BASE_DIR / "data" / "charts"


def _ensure_dir():
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


class DataViz:

    def chart(self, data: list | dict, chart_type: str = "auto", title: str = "") -> str:
        """Generate an interactive chart as HTML. Returns a chart_id for /stark/viz/{id}."""
        try:
            import plotly.graph_objects as go
        except ImportError:
            return ""

        _ensure_dir()
        chart_id = uuid.uuid4().hex[:10]

        if isinstance(data, dict):
            x = list(data.keys())
            y = list(data.values())
        else:
            x = list(range(len(data)))
            y = data

        if chart_type == "auto":
            chart_type = "pie" if isinstance(data, dict) and len(data) <= 8 else "bar"

        if chart_type == "pie":
            fig = go.Figure(go.Pie(labels=x, values=y))
        elif chart_type == "line":
            fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers"))
        elif chart_type == "scatter":
            fig = go.Figure(go.Scatter(x=x, y=y, mode="markers"))
        elif chart_type == "area":
            fig = go.Figure(go.Scatter(x=x, y=y, fill="tozeroy"))
        else:
            fig = go.Figure(go.Bar(x=x, y=y))

        fig.update_layout(title=title, template="plotly_dark",
                          paper_bgcolor="#0b1316", plot_bgcolor="#0b1316",
                          font_color="#d7f5ef")

        _ensure_dir()
        path = CHARTS_DIR / f"{chart_id}.html"
        fig.write_html(str(path), include_plotlyjs="cdn")
        return chart_id

    def spending_chart(self, period: str = "month") -> str:
        try:
            from services.finance import finance
            analysis = finance.spending_analysis()
            categories = analysis.get("by_category", {})
            if not categories:
                return ""
            return self.chart(categories, "pie", f"Spending — {period}")
        except Exception:
            return ""

    def health_timeline(self, metric: str = "sleep", days: int = 30) -> str:
        try:
            from services.health import health_monitor
            analysis = health_monitor.sleep_analysis()
            series = analysis.get("daily", {})
            if not series:
                return ""
            return self.chart(series, "line", f"{metric.title()} — last {days} days")
        except Exception:
            return ""

    def system_history(self, metric: str = "cpu", hours: int = 24) -> str:
        try:
            from services.sentinel import threats
            events = threats(hours)
            counts: dict[str, int] = {}
            for e in events:
                cat = e.get("category", "unknown")
                counts[cat] = counts.get(cat, 0) + 1
            if not counts:
                return ""
            return self.chart(counts, "bar", f"System events — last {hours}h")
        except Exception:
            return ""

    def goal_progress_chart(self) -> str:
        try:
            from services.workshop import workshop
            projects = workshop.list_projects()
            data = {p.get("name", "?"): 1 for p in projects}
            if not data:
                return ""
            return self.chart(data, "bar", "Active Projects")
        except Exception:
            return ""

    def network_topology(self) -> str:
        try:
            import plotly.graph_objects as go
            from services.network_intel import network
            devices = network.scan_network()
            if not devices:
                return ""

            _ensure_dir()
            chart_id = uuid.uuid4().hex[:10]
            n = len(devices)
            import math
            xs = [math.cos(2 * math.pi * i / n) for i in range(n)]
            ys = [math.sin(2 * math.pi * i / n) for i in range(n)]
            labels = [d.get("hostname", d.get("ip", "?")) for d in devices]

            fig = go.Figure()
            for i in range(n):
                fig.add_trace(go.Scatter(x=[0, xs[i]], y=[0, ys[i]], mode="lines",
                                         line=dict(color="#2dd9c4", width=1), showlegend=False))
            fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers+text", text=["router"],
                                     marker=dict(size=20, color="#00d4ff"), showlegend=False))
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=labels,
                                     marker=dict(size=14, color="#2dd9c4"), showlegend=False))
            fig.update_layout(title="Network Topology", template="plotly_dark",
                             paper_bgcolor="#0b1316", plot_bgcolor="#0b1316", font_color="#d7f5ef")
            path = CHARTS_DIR / f"{chart_id}.html"
            fig.write_html(str(path), include_plotlyjs="cdn")
            return chart_id
        except Exception:
            return ""

    def generate_report(self, title: str, sections: list[dict]) -> str:
        """sections: [{heading, content, chart_data (optional)}]"""
        _ensure_dir()
        report_id = uuid.uuid4().hex[:10]
        parts = [f"<html><head><title>{title}</title><style>"
                 "body{background:#020c14;color:#d7f5ef;font-family:monospace;padding:40px;}"
                 "h1{color:#00d4ff;} h2{color:#2dd9c4;border-bottom:1px solid #143;}"
                 "</style></head><body>", f"<h1>{title}</h1>"]

        for sec in sections:
            parts.append(f"<h2>{sec.get('heading','')}</h2><p>{sec.get('content','')}</p>")
            if sec.get("chart_data"):
                chart_id = self.chart(sec["chart_data"], title=sec.get("heading", ""))
                if chart_id:
                    parts.append(f"<iframe src='/stark/viz/{chart_id}' width='100%' height='400' frameborder='0'></iframe>")

        parts.append("</body></html>")
        path = CHARTS_DIR / f"report_{report_id}.html"
        path.write_text("\n".join(parts))
        return f"report_{report_id}"

    def get_chart_path(self, chart_id: str) -> Path | None:
        path = CHARTS_DIR / f"{chart_id}.html"
        return path if path.exists() else None


data_viz = DataViz()
