"""A3 maps concrete gaps to one next action grounded in the latest discovery."""

from __future__ import annotations

from pydantic import Field

from src.agents.analyst import Analysis
from src.agents.retriever import Action, Evidence
from src.agents.runtime import CompletionClient
from src.api.schemas import Frozen, SearchHit
from src.synthesis.prompts import messages


class Coverage(Frozen):
    sub_question: str
    chunk_id: str
    quote: str = Field(min_length=1)


class Critique(Frozen):
    sufficient: bool = False
    covered: list[Coverage] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    next_action: Action | None = None
    discovered_term: str = ""
    reason: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    degraded: bool = False


INSTRUCTION = """You are A3, a sufficiency critic, not an answer composer.
Return JSON: {sufficient: bool, covered: [{sub_question, chunk_id, quote}],
missing: [specific unanswered questions], next_action: {action, query, args} or null,
discovered_term: string, reason: string, confidence: number}.
Coverage requires a verbatim quote that ANSWERS that exact sub-question. Merely
mentioning the subject is not coverage. Cover every sub-question before sufficient.
Use next_action only from hybrid_search, figure_search, graph_neighbors, graph_paths,
list_mentions. Do not use read_section (not available). graph_paths args use from/to;
graph_neighbors uses entity_id. list_mentions query must be the entity NAME.
On multi-hop tasks, choose a term first discovered in latest evidence as discovered_term,
copy it into next_action.query and explain the discovery in reason. Do not invent a term.
Never repeat a failed action. Figure questions require evidence from the correct figure;
a wiki about a similar name is not coverage. Conflicting sources must remain visible.
"""


class SufficiencyCritic:
    def __init__(self, llm: CompletionClient | None = None) -> None:
        self.llm = llm
        self._seen_text = ""

    def assess(
        self,
        analysis: Analysis,
        chunks: list[SearchHit],
        latest: Evidence,
        step: int,
        history: list[Action],
    ) -> Critique:
        fallback = self._fallback(analysis, latest, history)
        if self.llm is None:
            return self._remember(fallback, latest)
        payload = {
            "question": analysis.normalized,
            "sub_questions": analysis.sub_questions,
            "evidence_so_far": [c.model_dump() for c in chunks],
            "latest": latest.model_dump(),
            "steps_taken": step,
            "previous_actions": [a.model_dump() for a in history],
        }
        for _attempt in range(2):
            try:
                response = self.llm.complete(
                    messages(INSTRUCTION, payload), json_mode=True, max_tokens=1200
                )
                result = Critique.model_validate(response.json_payload())
                return self._remember(
                    self._validate(result, analysis, chunks, latest, step, history), latest
                )
            except Exception:
                payload["repair"] = "Previous output was invalid. Return the exact JSON schema."
        fallback.degraded = True
        return self._remember(fallback, latest)

    def _remember(self, result: Critique, latest: Evidence) -> Critique:
        self._seen_text += "\n" + self._latest_text(latest)
        return result

    def _validate(
        self,
        result: Critique,
        analysis: Analysis,
        chunks: list[SearchHit],
        latest: Evidence,
        step: int,
        history: list[Action],
    ) -> Critique:
        sources = {c.chunk_id: c for c in chunks}
        valid = {
            c.sub_question
            for c in result.covered
            if c.chunk_id in sources and c.quote in sources[c.chunk_id].text
        }
        result.sufficient = result.sufficient and set(analysis.sub_questions) <= valid
        if result.sufficient:
            result.missing = []
        if analysis.intent == "multi_hop" and step < 2:
            result.sufficient = False
        if not result.sufficient:
            result.missing = result.missing or [q for q in analysis.sub_questions if q not in valid]
            result.missing = result.missing or [
                f"The complete relationship chain for {analysis.normalized}"
            ]
        if result.next_action:
            if result.next_action.model_dump() in [a.model_dump() for a in history]:
                result.next_action = None
            elif analysis.intent == "multi_hop":
                term = result.discovered_term.strip()
                latest_text = self._latest_text(latest)
                if (
                    len(term) < 3
                    or term.casefold() in analysis.normalized.casefold()
                    or term.casefold() in self._seen_text.casefold()
                    or term.casefold() in " ".join(a.query for a in history).casefold()
                    or term.casefold() not in latest_text.casefold()
                    or term.casefold() not in result.next_action.query.casefold()
                ):
                    result.next_action = None
        if not result.sufficient and result.next_action is None:
            result.next_action = self._fallback(analysis, latest, history).next_action
        return result

    @staticmethod
    def _latest_text(latest: Evidence) -> str:
        return "\n".join(
            [c.text for c in latest.chunks]
            + [e.canonical_name for e in latest.entities]
            + [name for e in latest.edges for name in [e.subject, e.object]]
        )

    def _fallback(self, analysis: Analysis, latest: Evidence, history: list[Action]) -> Critique:
        names = [e.canonical_name for e in latest.entities]
        names += [name for edge in latest.edges for name in [edge.subject, edge.object]]
        used = (
            " ".join(a.query for a in history) + analysis.normalized + self._seen_text
        ).casefold()
        new = next((name for name in names if name.casefold() not in used), "")
        action = Action(query=f"{new} {analysis.normalized}") if new else None
        if action is None and analysis.requires_visual:
            action = Action(action="figure_search", query=analysis.normalized)
        if action is None:
            action = Action(query=analysis.normalized)
        if action.model_dump() in [a.model_dump() for a in history]:
            action = None
        return Critique(
            missing=list(analysis.sub_questions),
            next_action=action,
            discovered_term=new,
            reason=(
                f"Latest evidence names {new}; retrieve its source."
                if new
                else "Coverage remains unverified."
            ),
        )
