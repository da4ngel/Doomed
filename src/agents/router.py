"""Entry behavior changes the first tool, not the evidence or verification rules."""

from src.agents.analyst import Analysis
from src.agents.retriever import Action
from src.api.schemas import AnswerMode


def route(analysis: Analysis, mode: AnswerMode) -> tuple[AnswerMode, Action]:
    if mode == "auto":
        mode = (
            "rich"
            if analysis.requires_visual
            else ("graph" if analysis.intent == "multi_hop" else "agent")
        )
    seeds = analysis.seed_entities
    if mode == "graph" and len(seeds) >= 2:
        return mode, Action(
            action="graph_paths",
            query=analysis.normalized,
            args={"from": seeds[0].entity_id, "to": seeds[1].entity_id},
        )
    if mode == "graph" and seeds:
        return mode, Action(
            action="graph_neighbors",
            query=seeds[0].surface,
            args={"entity_id": seeds[0].entity_id, "hops": 1},
        )
    action = "figure_search" if mode == "rich" and analysis.requires_visual else "hybrid_search"
    return mode, Action(action=action, query=analysis.normalized)
