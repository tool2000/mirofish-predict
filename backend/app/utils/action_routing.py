"""
Shared action routing utilities for Tier 2/3 agents.
Used by run_twitter_simulation.py, run_reddit_simulation.py, run_parallel_simulation.py.
"""
import random
import math
from collections import Counter
from typing import Dict, Any, List, Optional


def compute_topic_relevance(agent_config: Dict[str, Any], feed_items: List[Any]) -> float:
    """
    Compute relevance score between agent's interests and feed content.
    Returns float 0.0-1.0.
    """
    topics = agent_config.get("interested_topics", [])
    if not topics or not feed_items:
        return 0.0
    feed_text = " ".join(str(item) for item in feed_items).lower()
    matches = sum(1 for t in topics if t.lower() in feed_text)
    return min(matches / max(len(topics), 1), 1.0)


def rule_based_action(agent_config: Dict[str, Any], feed_items: List[Any]) -> str:
    """
    Rule-based action for Tier 2/3 agents.
    Returns action type string: LIKE_POST, REPOST, or DO_NOTHING.
    """
    if not feed_items:
        return "DO_NOTHING"
    relevance = compute_topic_relevance(agent_config, feed_items)
    if relevance > 0.3:
        roll = random.random()
        if roll < 0.4:
            return "LIKE_POST"
        elif roll < 0.6:
            return "REPOST"
        else:
            return "DO_NOTHING"
    return "DO_NOTHING"


def assign_tiers(agent_configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Assign tiers to agents based on influence_weight.
    - Tier 1 (top 20%): Full LLM decision making
    - Tier 2 (next 30%): LLM for content creation only
    - Tier 3 (bottom 50%): Rule-based only
    """
    sorted_agents = sorted(agent_configs, key=lambda a: a.get("influence_weight", 1.0), reverse=True)
    total = len(sorted_agents)
    for i, agent in enumerate(sorted_agents):
        if "tier" not in agent:
            ratio = i / max(total, 1)
            if ratio < 0.2:
                agent["tier"] = 1
            elif ratio < 0.5:
                agent["tier"] = 2
            else:
                agent["tier"] = 3
    return sorted_agents


# === Convergence Detection (Strategy 6) ===

def compute_action_distribution(actions: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute normalized action type distribution."""
    counter = Counter(a.get("action_type", "UNKNOWN") for a in actions)
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


def kl_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """KL divergence between two distributions. Returns 0 if identical."""
    if not p or not q:
        return float('inf')
    all_keys = set(p.keys()) | set(q.keys())
    div = 0.0
    for k in all_keys:
        p_val = p.get(k, 1e-10)
        q_val = q.get(k, 1e-10)
        if p_val > 0:
            div += p_val * math.log(p_val / q_val)
    return div
