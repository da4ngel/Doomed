"""Explicit A1 → (A2 → A3)* → A4 → A5 → A6, with request-local state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.analyst import Analysis, QueryAnalyst
from src.agents.composer import AnswerComposer
from src.agents.context import focused_chunks
from src.agents.critic import Critique, SufficiencyCritic
from src.agents.merger import merge_evidence
from src.agents.retriever import Action, Evidence, RetrievalAgent, tune_for_intent
from src.agents.router import route
from src.agents.runtime import Budget, BudgetExceeded
from src.agents.verifier import AnswerVerifier
from src.api.schemas import (
    AnswerMode,
    AnswerPacket,
    ChatRequest,
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    SearchHit,
    TraceStep,
    Warning,
    WarningType,
)
from src.core.trace import TraceStore
from src.core.usage import to_usage_record
from src.synthesis.render import render_packet


@dataclass
class RunState:
    chunks: dict[str, SearchHit] = field(default_factory=dict)
    edges: dict[str, Any] = field(default_factory=dict)
    history: list[Action] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    stagnant: int = 0
    intent: str = ""
    sequence: int = 0
    usage_offset: int = 0
    critique: Critique = field(default_factory=Critique)


class Orchestrator:
    def __init__(
        self,
        analyst: QueryAnalyst,
        retriever: RetrievalAgent,
        critic: SufficiencyCritic,
        composer: AnswerComposer,
        verifier: AnswerVerifier,
        traces: TraceStore,
        budget: Budget,
        *,
        llm: object | None = None,
        conflict_detector: Any = None,
    ) -> None:
        self.analyst, self.retriever, self.critic = analyst, retriever, critic
        self.composer, self.verifier, self.traces = composer, verifier, traces
        self.budget, self.llm, self.conflict_detector = budget, llm, conflict_detector

    def run(
        self, request: ChatRequest, *, trace_id: str | None = None, normalize: bool = True
    ) -> AnswerPacket:
        trace_id = trace_id or self.traces.start(request.question, request.mode)
        state = RunState()
        try:
            packet = self._run(request, trace_id, state, normalize)
        except Exception as error:
            warning: WarningType = (
                "budget_exhausted" if isinstance(error, BudgetExceeded) else "tool_failure"
            )
            packet = AnswerPacket(
                trace_id=trace_id,
                mode=request.mode,
                partial=True,
                warnings=state.warnings + [Warning(type=warning, detail=type(error).__name__)],
                iterations=len(state.history),
                missing_information=[
                    f"The requested answer could not be established: {request.question}"
                ],
            )
            packet.answer_markdown = render_packet(packet)
        if self.budget.stop_reason:
            packet.partial = True
            packet.confidence = min(packet.confidence, 0.6)
            packet.warnings.append(Warning(type="budget_exhausted", detail=self.budget.stop_reason))
            packet.missing_information.append("Investigation stopped: " + self.budget.stop_reason)
            packet.answer_markdown += "\n\nInvestigation stopped: " + self.budget.stop_reason
        packet.reasoning_trace = self.traces.steps(trace_id)
        packet.usage = self.traces.usage(trace_id)
        self.traces.save_result(trace_id, packet)
        self.traces.finish(trace_id, "partial" if packet.partial else "ok")
        return packet

    def _run(
        self, request: ChatRequest, trace_id: str, state: RunState, normalize: bool
    ) -> AnswerPacket:
        self.budget.remaining()
        analysis = self.analyst.analyze(request.question, normalize=normalize)
        state.intent = analysis.intent
        mode, action = route(analysis, request.mode)
        state.warnings.extend(Warning(type=w) for w in analysis.warnings)
        self._record(
            trace_id,
            state,
            "A1",
            "analyze",
            query=analysis.normalized,
            learned=f"Intent: {analysis.intent}; {len(analysis.seed_entities)} linked entities",
        )
        if not request.question.strip():
            return AnswerPacket(
                trace_id=trace_id,
                mode=mode,
                partial=True,
                answer_markdown="Please enter a question about the archive.",
                missing_information=["A question is required."],
            )
        try:
            self._loop(
                analysis, action, trace_id, state, min(request.budget, self.budget.max_steps)
            )
        except BudgetExceeded as error:
            state.critique = Critique(missing=list(analysis.sub_questions))
            state.warnings.append(Warning(type="budget_exhausted", detail=str(error)))
        return self._finalize(analysis, mode, trace_id, state)

    def _compose(
        self, analysis: Analysis, mode: AnswerMode, trace_id: str, state: RunState
    ) -> tuple:
        chunks = focused_chunks(analysis, list(state.chunks.values()))
        enriched = self.retriever.assets(chunks)
        state.warnings.extend(enriched.warnings)
        bundle = merge_evidence(
            chunks,
            hop_order=[e.evidence_chunk_id for e in state.edges.values()],
            detector=self.conflict_detector,
        )
        self._record(
            trace_id,
            state,
            "A4",
            "merge",
            found=len(bundle.chunks),
            learned=f"{len(bundle.conflicts)} detected conflicts; "
            f"{len(bundle.chunks)} distinct chunks",
        )
        packet = self.composer.compose(
            analysis.normalized,
            bundle,
            enriched.assets,
            trace_id=trace_id,
            mode=mode,
            missing=state.critique.missing,
            partial=not state.critique.sufficient,
            requires_visual=analysis.requires_visual,
        )
        self._record(
            trace_id,
            state,
            "A5",
            "compose",
            found=len(packet.claims),
            missing="; ".join(packet.missing_information),
        )
        return packet, bundle, enriched.assets

    def _finalize(
        self, analysis: Analysis, mode: AnswerMode, trace_id: str, state: RunState
    ) -> AnswerPacket:
        packet, bundle, assets = self._compose(analysis, mode, trace_id, state)
        packet.warnings.extend(state.warnings)
        verified = self.verifier.verify(packet, bundle.chunks, assets)
        packet = verified.packet
        self.traces.save_verification(trace_id, verified.verification.model_dump())
        self._record(
            trace_id,
            state,
            "A6",
            "verify",
            found=len(packet.claims),
            learned=f"{verified.verification.claims_downgraded} downgraded, "
            f"{verified.verification.claims_removed} removed",
        )
        packet.iterations = len(state.history)
        packet.corrections = [
            f"{c.original} → {c.to} (score {c.score:.2f})" for c in analysis.corrections
        ]
        packet.evidence_graph = self._graph(state, packet)
        return packet

    def _loop(
        self, analysis: Any, action: Action, trace_id: str, state: RunState, limit: int
    ) -> None:
        for step in range(1, limit + 1):
            self.budget.remaining()
            result = self._retrieve(action, trace_id, state)
            state.critique = self.critic.assess(
                analysis,
                focused_chunks(analysis, list(state.chunks.values())),
                result,
                step,
                state.history,
            )
            self._record(
                trace_id,
                state,
                "A3",
                "assess",
                query=(state.critique.next_action.query if state.critique.next_action else None),
                learned=state.critique.reason,
                missing="; ".join(state.critique.missing),
            )
            if state.critique.degraded:
                state.warnings.append(
                    Warning(
                        type="tool_failure",
                        action="critic_degraded",
                        detail="Coverage could not be validated",
                    )
                )

            # Every give-up exit from this loop now says why. Previously only the
            # step-limit exit warned, so a run that stopped through stagnation or a null
            # next_action was indistinguishable in the trace from one that succeeded.
            def gave_up(reason: str) -> None:
                state.warnings.append(
                    Warning(type="budget_exhausted", action="loop_stopped", detail=reason)
                )

            if state.critique.sufficient:
                break
            if state.stagnant >= 2:
                gave_up("retrieval returned nothing new twice")
                break
            next_action = state.critique.next_action
            if next_action is None:
                gave_up("the critic proposed no further action")
                break
            action = next_action
        if not state.critique.sufficient:
            state.critique.missing = state.critique.missing or list(analysis.sub_questions)
            if len(state.history) >= limit:
                state.warnings.append(
                    Warning(type="budget_exhausted", detail="Retrieval step limit reached")
                )

    def _retrieve(self, action: Action, trace_id: str, state: RunState) -> Evidence:
        # Applied here rather than in the router so it reaches EVERY action, including
        # the ones the critic proposes on later loop iterations - which are exactly the
        # multi-hop follow-ups that need expansion most.
        action = tune_for_intent(action, state.intent)
        result = self.retriever.execute(
            action,
            seen_chunks=set(state.chunks),
            seen_docs={c.doc_id for c in state.chunks.values()},
        )
        state.history.append(action)
        before = len(state.edges)
        state.edges.update({e.model_dump_json(): e for e in result.edges})
        state.stagnant = (
            state.stagnant + 1 if result.new_chunks == 0 and len(state.edges) == before else 0
        )
        state.chunks.update({c.chunk_id: c for c in result.chunks})
        state.warnings.extend(result.warnings)
        self._record(
            trace_id,
            state,
            "A2",
            action.action,
            query=action.query,
            found=len(result.chunks) + len(result.edges),
            learned=" | ".join(
                f"{e.subject} -{e.predicate}-> {e.object} " f"[{e.evidence_chunk_id}]"
                for e in result.edges
            ),
            new_gold_docs=result.new_gold_docs,
            latency_ms=result.latency_ms,
        )
        self.traces.record_evidence(
            trace_id,
            state.sequence,
            {
                "action": action.model_dump(),
                "chunks": [{"chunk_id": c.chunk_id, "doc_id": c.doc_id} for c in result.chunks],
                "edges": [e.model_dump() for e in result.edges],
            },
        )
        return result

    def _record(
        self, trace_id: str, state: RunState, agent: str, action: str, **details: Any
    ) -> None:
        state.sequence += 1
        self.traces.record(
            trace_id, TraceStep(step=state.sequence, agent=agent, action=action, **details)
        )
        usage = getattr(self.llm, "usage", [])
        for response in usage[state.usage_offset :]:
            self.traces.record_usage(
                trace_id, to_usage_record(response, state.sequence, f"{agent}: {action}")
            )
        state.usage_offset = len(usage)

    @staticmethod
    def _graph(state: RunState, packet: AnswerPacket) -> EvidenceGraph:
        nodes: dict[str, GraphNode] = {}
        edges = []
        for edge in state.edges.values():
            for entity_id, name in [(edge.subject_id, edge.subject), (edge.object_id, edge.object)]:
                nodes[entity_id] = GraphNode(id=entity_id, type="entity", label=name)
            edges.append(
                GraphEdge.model_validate(
                    {"from": edge.subject_id, "to": edge.object_id, "type": "relates"}
                )
            )
        for claim in packet.claims:
            nodes[claim.claim_id] = GraphNode(id=claim.claim_id, type="claim", label=claim.text)
            for citation in packet.citations:
                if citation.id in claim.citation_ids:
                    nodes[citation.doc_id] = GraphNode(
                        id=citation.doc_id, type="document", label=citation.title
                    )
                    edges.append(
                        GraphEdge.model_validate(
                            {"from": citation.doc_id, "to": claim.claim_id, "type": "supports"}
                        )
                    )
        return EvidenceGraph(nodes=list(nodes.values()), edges=edges)
