"""
Knowledge Graph — visual map of which (niche → variant → theme → palette) combos win.

Builds a NetworkX-style graph in pure Python (no external lib required).
Renders as Markdown / HTML / plain text for the Intelligence UI.

Each edge weight = how many times the combo was observed × avg true_quality.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from modules.learning.feedback     import load_all_feedback
from modules.learning.multi_signal import compute_true_quality

logger = logging.getLogger(__name__)


@dataclass
class Edge:
    src:    str
    dst:    str
    weight: float
    avg_q:  float
    n:      int


def build_graph(learning_dir: Path) -> Dict:
    """
    Returns {nodes: list, edges: list[Edge]}.
    Nodes are typed: niche / variant / theme / publisher.
    """
    feedbacks = load_all_feedback(learning_dir)
    if not feedbacks:
        return {"nodes": [], "edges": []}

    nodes: set = set()
    edge_data: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    for f in feedbacks:
        slug = (f.get("niche") or "").lower().replace(" ", "-")
        if not slug:
            continue
        tq = compute_true_quality(learning_dir, slug)
        q  = tq.true_score
        niche_node   = f"niche:{slug}"
        variant_node = f"variant:{f.get('variant_id')}" if f.get('variant_id') else None
        theme_node   = f"theme:{f.get('theme_name')}" if f.get('theme_name') else None
        pub_node     = f"pub:{f.get('publisher')}" if f.get('publisher') else None
        # Add nodes
        nodes.add(niche_node)
        for n in (variant_node, theme_node, pub_node):
            if n:
                nodes.add(n)
        # Add edges niche ↔ each attribute, scored by quality
        for tgt in (variant_node, theme_node, pub_node):
            if tgt:
                edge_data[(niche_node, tgt)].append(q)

    edges: List[Edge] = []
    for (s, d), scores in edge_data.items():
        avg_q = sum(scores) / len(scores)
        edges.append(Edge(s, d, len(scores) * avg_q, round(avg_q, 1), len(scores)))

    return {
        "nodes": sorted(nodes),
        "edges": sorted(edges, key=lambda e: -e.weight),
    }


def render_graph_markdown(graph: Dict, max_edges: int = 30) -> str:
    """Plain Markdown summary of the knowledge graph."""
    if not graph["nodes"]:
        return "_Pas encore de données — note quelques livres pour construire le graph._"
    lines = [
        f"**Graph stats** : {len(graph['nodes'])} nodes · {len(graph['edges'])} edges",
        "",
        "**Top winning combos** :",
    ]
    for e in graph["edges"][:max_edges]:
        emoji = "🟢" if e.avg_q >= 70 else ("🟡" if e.avg_q >= 50 else "🔴")
        lines.append(
            f"  {emoji} `{e.src}` ↔ `{e.dst}`  ·  avg q **{e.avg_q}**  ·  n={e.n}"
        )
    return "\n".join(lines)


def find_strong_paths(graph: Dict, min_q: float = 70.0) -> List[str]:
    """List 'X → Y → Z' paths where every edge has avg_q ≥ min_q."""
    strong = {(e.src, e.dst): e for e in graph["edges"] if e.avg_q >= min_q}
    paths = []
    for (a, b), e1 in list(strong.items())[:50]:
        for (c, d), e2 in strong.items():
            if c == b and a != d:
                paths.append(
                    f"`{a}` →[{e1.avg_q}] `{b}` →[{e2.avg_q}] `{d}`"
                )
    return paths[:15]
