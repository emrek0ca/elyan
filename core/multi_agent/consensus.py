from __future__ import annotations

from collections import Counter
from typing import Dict, List, Tuple


class SwarmConsensus:
    def weighted_voting(self, votes: List[Tuple[str, float]], method: str = "borda") -> Tuple[str, float]:
        if not votes:
            return "", 0.0
        if method == "approval":
            filtered = [(answer, score) for answer, score in votes if score >= 0.7]
            if not filtered:
                best = max(votes, key=lambda item: item[1])
                return best[0], best[1]
            counter = Counter(answer for answer, _ in filtered)
            best_answer, _ = counter.most_common(1)[0]
            total = sum(score for _, score in filtered) or 1.0
            best_score = sum(score for answer, score in filtered if answer == best_answer)
            return best_answer, best_score / total
        scores: Dict[str, float] = {}
        for answer, confidence in votes:
            scores[answer] = scores.get(answer, 0.0) + float(confidence)
        total = sum(scores.values()) or 1.0
        best_answer = max(scores.items(), key=lambda item: item[1])[0]
        return best_answer, scores[best_answer] / total

    def detect_byzantine_agents(self, agent_answers: Dict[str, str], threshold: float = 0.33) -> List[str]:
        if not agent_answers:
            return []
        majority_answer, majority_count = Counter(agent_answers.values()).most_common(1)[0]
        total = len(agent_answers)
        ratio = 1.0 - (majority_count / total)
        if ratio <= threshold:
            return [agent_id for agent_id, answer in agent_answers.items() if answer != majority_answer and total > 2]
        return [agent_id for agent_id, answer in agent_answers.items() if answer != majority_answer]
