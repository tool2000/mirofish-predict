"""Tests for tiered agents and convergence."""
import random
import math
import os
import importlib.util
import pytest
from collections import Counter

# Direct import to avoid __init__.py chain issues
_mod_path = os.path.join(os.path.dirname(__file__), "..", "app", "utils", "action_routing.py")
_spec = importlib.util.spec_from_file_location("action_routing", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

rule_based_action = _mod.rule_based_action
compute_topic_relevance = _mod.compute_topic_relevance
assign_tiers = _mod.assign_tiers
compute_action_distribution = _mod.compute_action_distribution
kl_divergence = _mod.kl_divergence


class TestRuleBasedAction:
    def test_no_feed_returns_do_nothing(self):
        config = {"interested_topics": ["AI"]}
        assert rule_based_action(config, []) == "DO_NOTHING"

    def test_relevant_feed_returns_action(self):
        random.seed(42)
        config = {"interested_topics": ["AI", "Tech"]}
        feed = ["AI breakthrough announced today"]
        result = rule_based_action(config, feed)
        assert result in ("LIKE_POST", "REPOST", "DO_NOTHING")

    def test_irrelevant_feed_returns_do_nothing(self):
        config = {"interested_topics": ["Cooking"]}
        feed = ["Political debate"]
        assert rule_based_action(config, feed) == "DO_NOTHING"


class TestAssignTiers:
    def test_assigns_tiers_by_influence(self):
        agents = [
            {"agent_id": 0, "influence_weight": 2.0},
            {"agent_id": 1, "influence_weight": 1.0},
            {"agent_id": 2, "influence_weight": 0.5},
            {"agent_id": 3, "influence_weight": 0.3},
            {"agent_id": 4, "influence_weight": 0.1},
        ]
        result = assign_tiers(agents)
        tiers = {a["agent_id"]: a["tier"] for a in result}
        assert tiers[0] == 1  # Top 20%
        assert tiers[4] == 3  # Bottom

    def test_preserves_existing_tier(self):
        agents = [{"agent_id": 0, "influence_weight": 2.0, "tier": 3}]
        result = assign_tiers(agents)
        assert result[0]["tier"] == 3  # Preserved


class TestConvergence:
    def test_identical_distributions_zero_divergence(self):
        dist = {"LIKE_POST": 0.5, "DO_NOTHING": 0.5}
        assert kl_divergence(dist, dist) == pytest.approx(0.0)

    def test_different_distributions_positive(self):
        p = {"LIKE_POST": 0.9, "DO_NOTHING": 0.1}
        q = {"LIKE_POST": 0.1, "DO_NOTHING": 0.9}
        assert kl_divergence(p, q) > 0.5

    def test_compute_action_distribution(self):
        actions = [{"action_type": "LIKE"}, {"action_type": "LIKE"}, {"action_type": "SKIP"}]
        dist = compute_action_distribution(actions)
        assert dist["LIKE"] == pytest.approx(2/3)

    def test_empty_actions(self):
        assert compute_action_distribution([]) == {}
