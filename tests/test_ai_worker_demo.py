from canto.core.ai_worker_demo import run_ai_worker_pool_demo


def test_ai_worker_pool_demo_selects_runs_captures_and_accepts():
    result = run_ai_worker_pool_demo()

    assert result.status == "accepted"
    assert result.model_key == "demo-local:canto-scripted-coder"
    assert result.selection_decision_id.startswith("selection_")
    assert result.result_revision == 1
    assert result.actual_cost_usd == 0
    assert result.cleaned_up is True


def test_ai_worker_pool_demo_can_apply_exact_accepted_result():
    result = run_ai_worker_pool_demo(apply=True)

    assert result.status == "promoted"
