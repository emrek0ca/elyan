#!/usr/bin/env python3
import json
import re
import sys
from collections import Counter

STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "then", "when",
    "bir", "ve", "ile", "icin", "için", "gibi", "daha", "sonra", "gore", "göre", "olan",
    "olarak", "user", "kullanici", "kullanıcı", "elyan",
}


def compact(value: str, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def tokenize(value: str):
    cleaned = re.sub(r"[^a-z0-9çğıöşü_\s.-]", " ", value.lower())
    tokens = []
    for token in cleaned.split():
        if len(token) >= 3 and token not in STOP_WORDS:
            tokens.append(token)
    return tokens[:80]


def has_followup(text: str) -> bool:
    return bool(re.search(r"\b(devam|follow up|next step|sonraki|yar[ıi]n|pending|bekliyor|açık|acik|s[üu]rd[üu]r)\b", text, re.I))


def main():
    raw = sys.stdin.read()
    if not raw:
        print("{}")
        return

    payload = json.loads(raw)
    facts = payload.get("facts", [])[:20]
    episodes = payload.get("episodes", [])[:12]

    tokens = []
    for fact in facts:
        tokens.extend(tokenize(f"{fact.get('key', '')} {fact.get('value', '')}"))
    for episode in episodes:
        tokens.extend(tokenize(f"{episode.get('episodeType', '')} {episode.get('summary', '')}"))

    top_tokens = [token for token, _count in Counter(tokens).most_common(6)]
    recent_topics = f"Recent recurring topics: {', '.join(top_tokens[:4])}" if top_tokens else None

    followup_count = sum(1 for episode in episodes if has_followup(str(episode.get("summary", ""))))
    technical_count = 0
    for fact in facts:
        text = f"{fact.get('key', '')} {fact.get('value', '')} {fact.get('factType', '')}"
        if re.search(r"\b(auth|backend|api|debug|fix|plan|architecture|flutter|server|memory|technical_stack|project_context)\b", text, re.I):
            technical_count += 1

    continuity_style = None
    reasoning_style = None
    if followup_count >= 2:
        continuity_style = "When work spans multiple turns, restate the carried goal and the next unresolved step explicitly."
    elif technical_count >= 2:
        continuity_style = "For ongoing work, preserve architecture and prior constraints unless the user clearly changes direction."

    if technical_count >= 3:
        reasoning_style = "Ongoing implementation work benefits from stepwise, architecture-preserving reasoning instead of broad rewrites."
    elif followup_count >= 2:
        reasoning_style = "Multi-turn work benefits from checking whether the user is continuing the same thread before answering."

    result = {
        "recentTopics": compact(recent_topics, 180) if recent_topics else None,
        "continuityStyle": compact(continuity_style, 220) if continuity_style else None,
        "reasoningStyle": compact(reasoning_style, 220) if reasoning_style else None,
        "topicTokens": top_tokens[:6],
        "evidenceCount": len(facts) + len(episodes),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
