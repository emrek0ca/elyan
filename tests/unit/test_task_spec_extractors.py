from core.spec.extractors import get_domain_fewshot
from core.spec.task_spec import _ALLOWED_ACTIONS


def test_domain_fewshots_use_allowed_actions():
    domains = ["filesystem", "api", "research", "coding", "office", "automation"]
    for domain in domains:
        samples = get_domain_fewshot(domain)
        assert samples, f"fewshot samples are empty for domain={domain}"
        for sample in samples:
            steps = sample.get("steps", [])
            assert isinstance(steps, list) and steps
            for step in steps:
                action = str(step.get("action") or "").strip().lower()
                assert action in _ALLOWED_ACTIONS, f"unsupported action in {domain}: {action}"
