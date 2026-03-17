"""
ELYAN Reasoning Engine - Phase 7
Chain-of-thought, tree-of-thought, causal reasoning, uncertainty quantification.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class ReasoningStrategy(Enum):
    CHAIN_OF_THOUGHT = "chain_of_thought"
    TREE_OF_THOUGHT = "tree_of_thought"
    CAUSAL = "causal"
    ANALOGICAL = "analogical"
    COUNTERFACTUAL = "counterfactual"


class Confidence(Enum):
    VERY_LOW = 0.1
    LOW = 0.3
    MEDIUM = 0.5
    HIGH = 0.7
    VERY_HIGH = 0.9


@dataclass
class ThoughtStep:
    step_id: str
    content: str
    reasoning: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ThoughtChain:
    chain_id: str
    question: str
    steps: List[ThoughtStep] = field(default_factory=list)
    conclusion: str = ""
    overall_confidence: float = 0.0
    strategy: ReasoningStrategy = ReasoningStrategy.CHAIN_OF_THOUGHT
    created_at: float = 0.0
    duration_ms: float = 0.0

    def add_step(self, content: str, reasoning: str, confidence: float, **kwargs) -> ThoughtStep:
        step = ThoughtStep(
            step_id=f"step_{len(self.steps) + 1}",
            content=content,
            reasoning=reasoning,
            confidence=confidence,
            evidence=kwargs.get("evidence", []),
            assumptions=kwargs.get("assumptions", []),
        )
        self.steps.append(step)
        return step

    def finalize(self, conclusion: str):
        self.conclusion = conclusion
        if self.steps:
            self.overall_confidence = sum(s.confidence for s in self.steps) / len(self.steps)
        self.duration_ms = (time.time() - self.created_at) * 1000


@dataclass
class ThoughtNode:
    node_id: str
    content: str
    score: float
    children: List["ThoughtNode"] = field(default_factory=list)
    parent_id: Optional[str] = None
    depth: int = 0
    is_terminal: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CausalRelation:
    cause: str
    effect: str
    strength: float
    mechanism: str = ""
    conditions: List[str] = field(default_factory=list)
    is_bidirectional: bool = False


@dataclass
class UncertaintyEstimate:
    value: float
    lower_bound: float
    upper_bound: float
    confidence_level: float = 0.95
    method: str = "heuristic"
    factors: List[str] = field(default_factory=list)


class ChainOfThought:
    """Step-by-step reasoning with explicit thought chains."""

    def __init__(self):
        self._chains: Dict[str, ThoughtChain] = {}

    def reason(self, question: str, context: Optional[Dict[str, Any]] = None) -> ThoughtChain:
        chain = ThoughtChain(
            chain_id=f"cot_{uuid.uuid4().hex[:8]}",
            question=question,
            strategy=ReasoningStrategy.CHAIN_OF_THOUGHT,
            created_at=time.time(),
        )
        chain.add_step(
            content=f"Understanding the question: {question}",
            reasoning="Parse the question to identify key components and requirements",
            confidence=0.9,
            evidence=[question],
        )
        if context:
            relevant = [f"{k}: {v}" for k, v in context.items() if v]
            chain.add_step(
                content=f"Analyzing available context ({len(relevant)} items)",
                reasoning="Evaluate context for relevance and reliability",
                confidence=0.8,
                evidence=relevant[:5],
            )
        chain.add_step(
            content="Formulating approach based on analysis",
            reasoning="Combine question understanding with context to determine solution path",
            confidence=0.7,
            assumptions=["Context is accurate", "Question is well-formed"],
        )
        chain.add_step(
            content="Synthesizing answer from reasoning chain",
            reasoning="Combine all previous steps into coherent conclusion",
            confidence=0.75,
        )
        chain.finalize(f"Reasoned answer for: {question}")
        self._chains[chain.chain_id] = chain
        return chain

    def get_chain(self, chain_id: str) -> Optional[ThoughtChain]:
        return self._chains.get(chain_id)

    def list_chains(self, limit: int = 10) -> List[ThoughtChain]:
        return list(self._chains.values())[-limit:]


class TreeOfThought:
    """Multi-path reasoning with tree exploration and scoring."""

    def __init__(self, max_depth: int = 4, branching_factor: int = 3):
        self.max_depth = max_depth
        self.branching_factor = branching_factor
        self._trees: Dict[str, ThoughtNode] = {}

    def explore(
        self,
        question: str,
        evaluator: Optional[Callable[[str], float]] = None,
    ) -> ThoughtNode:
        root = ThoughtNode(
            node_id=f"tot_{uuid.uuid4().hex[:8]}",
            content=question,
            score=1.0,
            depth=0,
        )
        eval_fn = evaluator or self._default_evaluator
        self._expand(root, eval_fn, depth=0)
        self._trees[root.node_id] = root
        return root

    def _expand(self, node: ThoughtNode, evaluator: Callable, depth: int):
        if depth >= self.max_depth:
            node.is_terminal = True
            return
        perspectives = self._generate_perspectives(node.content, depth)
        for i, perspective in enumerate(perspectives[:self.branching_factor]):
            child = ThoughtNode(
                node_id=f"{node.node_id}_c{i}",
                content=perspective,
                score=evaluator(perspective),
                parent_id=node.node_id,
                depth=depth + 1,
            )
            node.children.append(child)
            if child.score >= 0.5 and depth + 1 < self.max_depth:
                self._expand(child, evaluator, depth + 1)

    def _generate_perspectives(self, content: str, depth: int) -> List[str]:
        if depth == 0:
            return [
                f"Direct approach: {content}",
                f"Alternative perspective: {content}",
                f"Contrarian view: {content}",
            ]
        elif depth == 1:
            return [
                f"Detailed analysis of: {content}",
                f"Counter-argument to: {content}",
            ]
        else:
            return [f"Refinement of: {content}"]

    @staticmethod
    def _default_evaluator(content: str) -> float:
        score = 0.5
        if len(content) > 50:
            score += 0.1
        if "?" in content:
            score += 0.05
        if any(w in content.lower() for w in ["because", "therefore", "evidence", "cunku", "dolayisiyla"]):
            score += 0.15
        return min(1.0, score)

    def get_best_path(self, root: ThoughtNode) -> List[ThoughtNode]:
        path = [root]
        current = root
        while current.children:
            best_child = max(current.children, key=lambda c: c.score)
            path.append(best_child)
            current = best_child
        return path

    def get_all_paths(self, root: ThoughtNode) -> List[List[ThoughtNode]]:
        paths = []
        self._collect_paths(root, [], paths)
        return paths

    def _collect_paths(self, node: ThoughtNode, current_path: List[ThoughtNode], all_paths: List):
        current_path = current_path + [node]
        if node.is_terminal or not node.children:
            all_paths.append(current_path)
        else:
            for child in node.children:
                self._collect_paths(child, current_path, all_paths)


class CausalReasoner:
    """Cause-effect relationship analysis and reasoning."""

    def __init__(self):
        self._relations: List[CausalRelation] = []
        self._knowledge: Dict[str, List[CausalRelation]] = {}

    def add_relation(
        self,
        cause: str,
        effect: str,
        strength: float,
        mechanism: str = "",
        conditions: Optional[List[str]] = None,
        bidirectional: bool = False,
    ) -> CausalRelation:
        relation = CausalRelation(
            cause=cause,
            effect=effect,
            strength=min(1.0, max(0.0, strength)),
            mechanism=mechanism,
            conditions=conditions or [],
            is_bidirectional=bidirectional,
        )
        self._relations.append(relation)
        self._knowledge.setdefault(cause.lower(), []).append(relation)
        if bidirectional:
            self._knowledge.setdefault(effect.lower(), []).append(relation)
        return relation

    def find_causes(self, effect: str) -> List[CausalRelation]:
        return [r for r in self._relations if r.effect.lower() == effect.lower()]

    def find_effects(self, cause: str) -> List[CausalRelation]:
        return self._knowledge.get(cause.lower(), [])

    def trace_chain(self, start: str, max_depth: int = 5) -> List[List[CausalRelation]]:
        chains: List[List[CausalRelation]] = []
        visited = {start.lower()}
        self._trace(start.lower(), [], chains, visited, max_depth)
        return chains

    def _trace(self, current: str, path: List, chains: List, visited: set, depth: int):
        if depth <= 0:
            if path:
                chains.append(list(path))
            return
        effects = self.find_effects(current)
        if not effects:
            if path:
                chains.append(list(path))
            return
        for rel in effects:
            next_node = rel.effect.lower()
            if next_node not in visited:
                visited.add(next_node)
                path.append(rel)
                self._trace(next_node, path, chains, visited, depth - 1)
                path.pop()
                visited.remove(next_node)

    def get_counterfactual(self, cause: str, negate: bool = True) -> Dict[str, Any]:
        effects = self.find_effects(cause)
        counterfactuals = []
        for rel in effects:
            if negate:
                modified_strength = 1.0 - rel.strength
            else:
                modified_strength = rel.strength
            counterfactuals.append({
                "original_cause": rel.cause,
                "effect": rel.effect,
                "original_strength": rel.strength,
                "counterfactual_strength": modified_strength,
                "implication": f"If '{cause}' were {'removed' if negate else 'strengthened'}, "
                               f"'{rel.effect}' would be {'weakened' if negate else 'enhanced'} "
                               f"(strength: {modified_strength:.2f})",
            })
        return {
            "cause": cause,
            "negated": negate,
            "affected_effects": counterfactuals,
        }


class UncertaintyQuantifier:
    """Estimate and propagate uncertainty in reasoning."""

    def estimate(
        self,
        value: float,
        factors: Optional[List[Tuple[str, float]]] = None,
        method: str = "heuristic",
    ) -> UncertaintyEstimate:
        if factors:
            weights = [f[1] for f in factors]
            avg_conf = sum(weights) / len(weights)
            margin = (1.0 - avg_conf) * value * 0.5
        else:
            margin = value * 0.2
        factor_names = [f[0] for f in (factors or [])]
        return UncertaintyEstimate(
            value=value,
            lower_bound=max(0, value - margin),
            upper_bound=value + margin,
            confidence_level=0.95,
            method=method,
            factors=factor_names,
        )

    def propagate(self, estimates: List[UncertaintyEstimate]) -> UncertaintyEstimate:
        if not estimates:
            return UncertaintyEstimate(0, 0, 0, 0.95)
        combined_value = sum(e.value for e in estimates) / len(estimates)
        all_lowers = [e.lower_bound for e in estimates]
        all_uppers = [e.upper_bound for e in estimates]
        combined_lower = sum(all_lowers) / len(all_lowers)
        combined_upper = sum(all_uppers) / len(all_uppers)
        all_factors = []
        for e in estimates:
            all_factors.extend(e.factors)
        return UncertaintyEstimate(
            value=combined_value,
            lower_bound=combined_lower,
            upper_bound=combined_upper,
            confidence_level=0.95,
            method="propagated",
            factors=list(set(all_factors)),
        )

    @staticmethod
    def confidence_to_label(confidence: float) -> str:
        if confidence >= 0.9:
            return "very_high"
        elif confidence >= 0.7:
            return "high"
        elif confidence >= 0.5:
            return "medium"
        elif confidence >= 0.3:
            return "low"
        return "very_low"


class ReasoningEngine:
    """Unified reasoning engine combining all strategies."""

    def __init__(self):
        self.chain_of_thought = ChainOfThought()
        self.tree_of_thought = TreeOfThought()
        self.causal_reasoner = CausalReasoner()
        self.uncertainty = UncertaintyQuantifier()

    def reason(
        self,
        question: str,
        strategy: ReasoningStrategy = ReasoningStrategy.CHAIN_OF_THOUGHT,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        if strategy == ReasoningStrategy.CHAIN_OF_THOUGHT:
            chain = self.chain_of_thought.reason(question, context)
            result = {
                "strategy": strategy.value,
                "chain_id": chain.chain_id,
                "steps": [
                    {"content": s.content, "confidence": s.confidence}
                    for s in chain.steps
                ],
                "conclusion": chain.conclusion,
                "confidence": chain.overall_confidence,
            }
        elif strategy == ReasoningStrategy.TREE_OF_THOUGHT:
            tree = self.tree_of_thought.explore(question)
            best_path = self.tree_of_thought.get_best_path(tree)
            result = {
                "strategy": strategy.value,
                "tree_id": tree.node_id,
                "best_path": [
                    {"content": n.content, "score": n.score, "depth": n.depth}
                    for n in best_path
                ],
                "total_nodes": self._count_nodes(tree),
                "confidence": best_path[-1].score if best_path else 0.0,
            }
        elif strategy == ReasoningStrategy.CAUSAL:
            effects = self.causal_reasoner.find_effects(question)
            chains = self.causal_reasoner.trace_chain(question)
            result = {
                "strategy": strategy.value,
                "direct_effects": [
                    {"effect": r.effect, "strength": r.strength}
                    for r in effects
                ],
                "causal_chains": len(chains),
                "confidence": 0.7 if effects else 0.3,
            }
        elif strategy == ReasoningStrategy.COUNTERFACTUAL:
            cf = self.causal_reasoner.get_counterfactual(question)
            result = {
                "strategy": strategy.value,
                "counterfactual": cf,
                "confidence": 0.6,
            }
        else:
            result = {
                "strategy": strategy.value,
                "error": "Strategy not implemented",
                "confidence": 0.0,
            }
        duration_ms = (time.time() - start_time) * 1000
        result["duration_ms"] = round(duration_ms, 2)
        uncertainty = self.uncertainty.estimate(
            result.get("confidence", 0.5),
            factors=[("reasoning_strategy", 0.7), ("context_quality", 0.6)],
        )
        result["uncertainty"] = {
            "lower": round(uncertainty.lower_bound, 3),
            "upper": round(uncertainty.upper_bound, 3),
            "label": self.uncertainty.confidence_to_label(result.get("confidence", 0.5)),
        }
        return result

    @staticmethod
    def _count_nodes(node: ThoughtNode) -> int:
        count = 1
        for child in node.children:
            count += ReasoningEngine._count_nodes(child)
        return count


_reasoning_engine: Optional[ReasoningEngine] = None


def get_reasoning_engine() -> ReasoningEngine:
    global _reasoning_engine
    if _reasoning_engine is None:
        _reasoning_engine = ReasoningEngine()
    return _reasoning_engine
