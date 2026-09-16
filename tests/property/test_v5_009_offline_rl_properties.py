from dataclasses import replace

from hypothesis import given, strategies as st

from futures_agent_os.research_experiment import OfflineRlModule, OfflineRlPlan


@given(
    module=st.sampled_from(tuple(OfflineRlModule)),
    feature_count=st.integers(min_value=1, max_value=16),
    action_count=st.integers(min_value=2, max_value=16),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_plan_digest_is_deterministic_for_every_supported_low_dimensional_shape(
    module: OfflineRlModule, feature_count: int, action_count: int, seed: int
) -> None:
    plan = OfflineRlPlan(
        "offline-rl:property:v1",
        module,
        tuple(f"feature-{index}" for index in range(feature_count)),
        tuple(f"action-{index}" for index in range(action_count)),
        "reward:v1",
        "dataset:frozen:v1",
        "a" * 64,
        "behavior-policy:v1",
        "evaluation-protocol:v1",
        "deadbeef",
        "environment:v1",
        seed,
    )
    assert plan.digest == replace(plan).digest
    assert plan.digest != replace(plan, seed=seed + 1).digest
