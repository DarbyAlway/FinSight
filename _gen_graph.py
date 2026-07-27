"""One-off: render the orchestrator's compiled LangGraph to a PNG via
get_graph().draw_mermaid_png(). Falls back to saving the raw Mermaid text if
PNG rendering can't reach the renderer.
"""
import os

from orchestrator import _GRAPH

g = _GRAPH.get_graph()
os.makedirs("docs", exist_ok=True)
png_path = "docs/orchestrator-graph.png"

# Always keep the Mermaid source too (cheap, offline, renders on GitHub/IDE).
with open("docs/orchestrator-graph.mmd", "w", encoding="utf-8") as f:
    f.write(g.draw_mermaid())

try:
    g.draw_mermaid_png(output_file_path=png_path)
    print(f"PNG written: {png_path} ({os.path.getsize(png_path)} bytes)")
except Exception as e:
    print(f"PNG render failed ({type(e).__name__}: {e}).")
    print("Mermaid source still written to docs/orchestrator-graph.mmd")
