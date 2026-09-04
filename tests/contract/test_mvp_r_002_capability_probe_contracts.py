"""Synthetic contracts for the explicit MVP-R-002 minimal capability probe."""

from __future__ import annotations

import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any, Mapping, cast

import pytest

import futures_agent_os.adapters.codex_app_server as codex_app_server

from futures_agent_os.research_experiment.model_routing import (
    MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
    MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
)
from futures_agent_os.research_experiment.mvp_r_002_runtime import (
    MvpR002PhaseZeroOrchestrator,
    MvpR002RuntimeFailureCode,
    mvp_r_002_capability_probe_plan,
)


_ROOT = Path(__file__).parents[2]


def _script_module() -> ModuleType:
    path = _ROOT / "scripts" / "probe_mvp_r_002_capability.py"
    module_spec = importlib.util.spec_from_file_location("mvp_r_002_capability_probe_script", path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def _research_output() -> dict[str, object]:
    ref = {"artifact_sha256": "a" * 64, "json_pointer": "/evidence", "label": "frozen"}
    claim = {"category": "SCREENING_SUPPORTS_RESEARCH", "evidence_refs": [ref], "numeric_value": None, "unit": None}
    return {
        "intent": "RESEARCH_ONLY",
        "action": "TEST_NEXT",
        "why_now": "SCREENING_SUPPORTS_RESEARCH",
        "supporting_claims": [claim],
        "strongest_counter_claim": claim,
        "additional_unknowns": ["INDEPENDENT_WINDOW_UNKNOWN"],
        "falsifiable_hypothesis": "FROZEN_HYPOTHESIS",
        "source_refs": [ref],
    }


def _final_output(workload: str) -> dict[str, object]:
    if workload == MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD:
        return _research_output()
    if workload == MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD:
        return {"design_category": "USE_FROZEN_BINDING"}
    return {"decision": "PASS", "reason_category": "SCREENING_SUPPORTS_RESEARCH"}


def _response(workload: str) -> dict[str, object]:
    effort = "high" if workload == MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD else "medium"
    return {
        "model_provider": "openai",
        "model": "gpt-5.6-terra",
        "reasoning_effort": effort,
        "response_id": f"response-{workload.replace('.', '-')}",
        "usage": {
            "inputTokens": 12,
            "cachedInputTokens": 0,
            "outputTokens": 8,
            "reasoningOutputTokens": 0,
            "cacheWriteInputTokens": 0,
            "totalTokens": 20,
        },
        "latencyMs": 9,
        "provider_turn_started": True,
        "provider_response_observed": True,
        "cost_mode": "SUBSCRIPTION_UNAVAILABLE",
        "cost_available": False,
        "cost_amount": None,
        "reroutes": (),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("agentMessage",),
        "status": "completed",
        "timed_out": False,
        "final_texts": (json.dumps(_final_output(workload)),),
    }


class _FakeTransport:
    def __init__(self) -> None:
        self.payloads: list[Mapping[str, object]] = []
        self.mutations: dict[str, tuple[str, object]] = {}

    def __call__(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.payloads.append(payload)
        assert set(payload) == {"model", "effort", "instructions", "input", "tools", "output_schema", "timeout_seconds"}
        schema = cast(Mapping[str, object], payload["output_schema"])
        properties = cast(Mapping[str, object], schema["properties"])
        workload = (
            MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD
            if "supporting_claims" in properties
            else MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD
            if "design_category" in properties
            else MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD
        )
        response = _response(workload)
        if workload in self.mutations:
            key, value = self.mutations[workload]
            if key == "__remove__":
                response.pop(cast(str, value))
            else:
                response[key] = value
        return response


def test_plan_is_at_most_three_attempts_with_a_separate_fifteen_receipt_gate() -> None:
    script = _script_module()
    plan = cast(dict[str, Any], script.build_plan())

    assert [item.workload_id for item in mvp_r_002_capability_probe_plan()] == [
        MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD,
        MVP_R_002_PREREGISTRATION_DESIGN_WORKLOAD,
        MVP_R_002_ADVERSARIAL_CRITIQUE_WORKLOAD,
    ]
    assert plan["minimal_capability_probe"]["expected_max_transport_attempts"] == 3
    assert plan["minimal_capability_probe"]["failure_policy"] == "FIXED_ORDER_STOP_ON_FIRST_FAILURE"
    assert plan["minimal_capability_probe"]["expected_provider"] == "openai"
    assert plan["full_qualification_not_executed"]["minimum_required_qualification_receipt_count"] == 15
    assert plan["minimal_capability_probe"]["uses_diagnostic_roster"] is False
    assert plan["full_qualification_not_executed"]["minimal_receipts_are_qualification_receipts"] is False


def test_public_orchestrator_runs_only_frozen_empty_tool_profile_calls_and_sanitizes_success() -> None:
    transport = _FakeTransport()
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(transport)

    receipts = orchestrator.run_plan_once()

    assert all(receipt.status == "COMPLETED" for receipt in receipts)
    assert all(receipt.usage is not None and receipt.latency_ms == 9 for receipt in receipts)
    assert all(receipt.reroute_sha256s == () and receipt.activity_sha256s == () for receipt in receipts)
    assert all(receipt.to_dict()["qualification_status"] == "NOT_A_QUALIFICATION_RECEIPT" for receipt in receipts)
    assert len(transport.payloads) == 3
    assert all(payload["tools"] == () and payload["timeout_seconds"] == 120 for payload in transport.payloads)
    assert all("candidate" not in cast(str, payload["input"]) for payload in transport.payloads)
    serialized = json.dumps(receipts[0].to_dict(), sort_keys=True)
    assert "MVP-R-002 research synthesis" not in serialized
    assert "SCREENING_SUPPORTS_RESEARCH" not in serialized


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (("reasoning_effort", "high"), MvpR002RuntimeFailureCode.EFFORT_DRIFT),
        (("final_texts", ("{}",)), MvpR002RuntimeFailureCode.RESPONSE_SCHEMA_INVALID),
        (("reroutes", ("rerouted",)), MvpR002RuntimeFailureCode.REROUTE_REJECTED),
        (("server_requests", ("item/tool/call",)), MvpR002RuntimeFailureCode.ACTIVITY_REJECTED),
        (("reasoning_effort_error", "EFFORT_METADATA_CONFLICT"), MvpR002RuntimeFailureCode.EFFORT_METADATA_CONFLICT),
        (("cost_mode", "API_DOLLARS"), MvpR002RuntimeFailureCode.COST_INCONSISTENT),
        (("cost_amount", 1), MvpR002RuntimeFailureCode.COST_AMOUNT_REJECTED),
        (("__remove__", "cost_mode"), MvpR002RuntimeFailureCode.COST_MISSING),
        (("provider_turn_started", False), MvpR002RuntimeFailureCode.TURN_START_UNPROVEN),
        (("provider_response_observed", False), MvpR002RuntimeFailureCode.RESPONSE_UNPROVEN),
    ],
)
def test_probe_fails_closed_for_observation_and_schema_contract_breaks(
    mutation: tuple[str, object], code: MvpR002RuntimeFailureCode
) -> None:
    transport = _FakeTransport()
    transport.mutations[MVP_R_002_HYPOTHESIS_SYNTHESIS_WORKLOAD] = mutation
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(transport)

    receipt = orchestrator.run_plan_once()[0]

    assert receipt.status == "FAILED"
    assert receipt.failure_code == code.value
    assert receipt.actual_provider == "openai"
    assert receipt.response_sha256 is not None
    assert receipt.response_id is not None
    assert len(transport.payloads) == 1
    assert "response_id" not in receipt.to_dict()
    assert receipt.response_id not in json.dumps(receipt.to_dict(), sort_keys=True)


def test_probe_is_one_shot_and_evidence_writes_are_new_and_atomic(tmp_path: Path) -> None:
    transport = _FakeTransport()
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(transport)
    assert len(orchestrator.run_plan_once()) == 3
    with pytest.raises(PermissionError, match="already consumed"):
        orchestrator.run_plan_once()
    assert len(transport.payloads) == 3

    script = _script_module()
    path = script._safe_evidence_path("probe.json", repository_root=tmp_path)
    payload: dict[str, Any] = {"record_type": "test", "value": 1}
    reservation = script.reserve_new_evidence(path)
    assert path.exists() is False and reservation.temp_path.exists() and reservation.lock_path.exists()
    reservation.publish(payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert reservation.lock_path.exists() is False
    with pytest.raises(FileExistsError, match="already exists"):
        script.reserve_new_evidence(path)
    with pytest.raises(ValueError, match="simple canonical"):
        script._safe_evidence_path("../probe.json", repository_root=tmp_path)


def test_concurrent_probe_reuse_is_rejected_before_any_additional_transport() -> None:
    transport = _FakeTransport()
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(transport)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(orchestrator.run_plan_once) for _ in range(2))
    results = [future.result() if future.exception() is None else future.exception() for future in futures]

    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(isinstance(result, PermissionError) for result in results) == 1
    assert len(transport.payloads) == 3


def test_existing_evidence_path_blocks_execute_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _script_module()
    existing = tmp_path / "already.json"
    existing.write_text("prior", encoding="utf-8")
    attempts = 0

    def forbidden_execute(_run_id: str) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise AssertionError("transport must not be reached")

    monkeypatch.setattr(script, "_safe_evidence_path", lambda _value: existing)
    monkeypatch.setattr(script, "execute_probe", forbidden_execute)

    with pytest.raises(FileExistsError, match="already exists"):
        script.main(["--execute", "--evidence-file", "already.json", "--run-id", "probe-run"])
    assert attempts == 0


def test_reservation_lock_blocks_another_attempt_before_transport(tmp_path: Path) -> None:
    script = _script_module()
    path = script._safe_evidence_path("locked.json", repository_root=tmp_path)
    reservation = script.reserve_new_evidence(path)

    with pytest.raises(FileExistsError, match="already reserved"):
        script.reserve_new_evidence(path)
    reservation.abandon()
    assert reservation.lock_path.exists() is False and reservation.temp_path.exists() is False


def test_temp_open_failure_cleans_only_our_lock_temp_and_descriptors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _script_module()
    path = script._safe_evidence_path("open-failure.json", repository_root=tmp_path)
    real_open = script.os.open
    real_close = script.os.close
    closed: list[int] = []

    def fail_temp_open(target: object, flags: int, mode: int = 0o777) -> int:
        if str(target).endswith(".tmp"):
            raise OSError("temp open failed")
        return real_open(target, flags, mode)

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(script.os, "open", fail_temp_open)
    monkeypatch.setattr(script.os, "close", record_close)

    with pytest.raises(OSError, match="temp open failed"):
        script.reserve_new_evidence(path)
    assert closed
    assert path.exists() is False
    assert not list(path.parent.glob(".open-failure.json.*"))


def test_temp_name_collision_never_deletes_an_unowned_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = _script_module()
    path = script._safe_evidence_path("collision.json", repository_root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    other_temp = path.parent / ".collision.json.existing.tmp"
    other_temp.write_text("other", encoding="utf-8")
    monkeypatch.setattr(script, "uuid4", lambda: "existing")

    with pytest.raises(FileExistsError):
        script.reserve_new_evidence(path)
    assert other_temp.read_text(encoding="utf-8") == "other"
    assert not (path.parent / ".collision.json.lock").exists()


def test_first_directory_fsync_failure_cleans_lock_temp_and_descriptors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _script_module()
    path = script._safe_evidence_path("fsync-failure.json", repository_root=tmp_path)
    real_fsync = script.os.fsync
    real_close = script.os.close
    closed: list[int] = []
    fsync_calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("first directory fsync failed")
        real_fsync(descriptor)

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(script.os, "fsync", fail_first_fsync)
    monkeypatch.setattr(script.os, "close", record_close)

    with pytest.raises(OSError, match="first directory fsync failed"):
        script.reserve_new_evidence(path)
    assert fsync_calls >= 1 and len(closed) >= 2
    assert path.exists() is False
    assert not list(path.parent.glob(".fsync-failure.json.*"))


def test_failed_atomic_publish_leaves_no_final_or_partial_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = _script_module()
    path = script._safe_evidence_path("publish.json", repository_root=tmp_path)
    reservation = script.reserve_new_evidence(path)
    monkeypatch.setattr(script.os, "link", lambda _source, _target: (_ for _ in ()).throw(OSError("link failed")))

    with pytest.raises(OSError, match="link failed"):
        reservation.publish({"record_type": "test"})
    assert path.exists() is False
    assert reservation.temp_path.exists() is False
    assert reservation.lock_path.exists() is False


class _Dump:
    def __init__(self, payload: Mapping[str, object], *, identifier: str | None = None) -> None:
        self._payload = payload
        if identifier is not None:
            self.id = identifier

    def model_dump(self, **_kwargs: object) -> Mapping[str, object]:
        return self._payload


def _official_payload() -> dict[str, object]:
    return {
        "model": "gpt-5.6-terra",
        "effort": "medium",
        "instructions": "fixed instructions",
        "input": "fixed input",
        "tools": (),
        "output_schema": {"type": "object"},
        "timeout_seconds": 120,
    }


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch, *, conflict: bool, timeout: bool = False
) -> tuple[list[int], list[str], list[Mapping[str, object]]]:
    timers: list[int] = []
    interrupts: list[str] = []
    sdk_params: list[Mapping[str, object]] = []

    class FakeTimer:
        def __init__(self, seconds: int, _callback: object) -> None:
            timers.append(seconds)
            self.daemon = False
            self._callback = cast(Any, _callback)

        def start(self) -> None:
            if timeout:
                self._callback()
            return None

        def cancel(self) -> None:
            return None

    class FakeClient:
        def __init__(self, _config: object, *, approval_handler: object) -> None:
            self.events = [
                SimpleNamespace(
                    method="thread/tokenUsage/updated",
                    payload=SimpleNamespace(
                        token_usage=SimpleNamespace(
                            last=_Dump(
                                {
                                    "inputTokens": 12,
                                    "cachedInputTokens": 0,
                                    "outputTokens": 8,
                                    "reasoningOutputTokens": 0,
                                    "cacheWriteInputTokens": 0,
                                    "totalTokens": 20,
                                }
                            )
                        )
                    ),
                ),
                SimpleNamespace(
                    method="item/completed", payload=SimpleNamespace(item=_Dump({"type": "agentMessage", "text": "{}"}))
                ),
                SimpleNamespace(method="turn/completed", payload=SimpleNamespace(turn=_Dump({"status": "completed"}))),
            ]

        def start(self) -> None:
            return None

        def initialize(self) -> None:
            return None

        def thread_start(self, params: object) -> object:
            assert type(params) is dict
            json.dumps(params, allow_nan=False)
            sdk_params.append(cast(Mapping[str, object], params))
            return SimpleNamespace(
                thread=SimpleNamespace(id="thread"),
                model="gpt-5.6-terra",
                model_provider="openai",
                model_dump=lambda **_kwargs: {"reasoningEffort": "medium"},
            )

        def turn_start(self, _thread_id: str, _input: str, params: object) -> object:
            assert type(params) is dict
            json.dumps(params, allow_nan=False)
            sdk_params.append(cast(Mapping[str, object], params))
            return SimpleNamespace(
                turn=_Dump({"effort": "high" if conflict else "medium"}, identifier="turn"),
            )

        def next_turn_notification(self, _turn_id: str) -> object:
            return self.events.pop(0)

        def turn_interrupt(self, _thread_id: str, turn_id: str) -> None:
            interrupts.append(turn_id)

        def close(self) -> None:
            return None

    clock = iter((1_000_000, 5_000_000))
    monkeypatch.setattr(codex_app_server, "CodexClient", FakeClient)
    monkeypatch.setattr(codex_app_server, "Timer", FakeTimer)
    monkeypatch.setattr(codex_app_server, "perf_counter_ns", lambda: next(clock))
    return timers, interrupts, sdk_params


def test_official_transport_reports_started_turn_latency_timeout_and_fixed_subscription_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timers, _, sdk_params = _install_fake_sdk(monkeypatch, conflict=False)

    result = codex_app_server.OfficialCodexAppServerTransport()(_official_payload())

    assert timers == [120]
    assert result["provider_turn_started"] is True
    assert result["latencyMs"] == 4
    assert result["cost_mode"] == "SUBSCRIPTION_UNAVAILABLE"
    assert result["cost_available"] is False and result["cost_amount"] is None
    assert result["reasoning_effort"] == "medium"
    assert len(sdk_params) == 2


def test_official_transport_effort_metadata_conflict_preserves_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_sdk(monkeypatch, conflict=True)

    result = codex_app_server.OfficialCodexAppServerTransport()(_official_payload())

    assert result["reasoning_effort_error"] == "EFFORT_METADATA_CONFLICT"
    assert "reasoning_effort" not in result
    assert result["model_provider"] == "openai"
    assert result["usage"] is not None and result["latencyMs"] == 4


def test_official_conflict_shape_reaches_orchestrator_with_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_sdk(monkeypatch, conflict=True)
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(
        codex_app_server.OfficialCodexAppServerTransport()
    )

    receipt = orchestrator.run_plan_once()[0]

    assert receipt.failure_code == MvpR002RuntimeFailureCode.EFFORT_METADATA_CONFLICT.value
    assert receipt.actual_provider == "openai" and receipt.actual_model_id == "gpt-5.6-terra"
    assert receipt.usage is not None and receipt.latency_ms == 4
    assert receipt.response_sha256 is not None and receipt.provider_turn_started is True


def test_timer_timeout_interrupts_turn_and_orchestrator_keeps_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    _, interrupts, _ = _install_fake_sdk(monkeypatch, conflict=False, timeout=True)
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(
        codex_app_server.OfficialCodexAppServerTransport()
    )

    receipt = orchestrator.run_plan_once()[0]

    assert interrupts == ["turn"]
    assert receipt.failure_code == MvpR002RuntimeFailureCode.TURN_INCOMPLETE.value
    assert receipt.actual_provider == "openai" and receipt.usage is not None
    assert receipt.latency_ms == 4 and receipt.provider_turn_started is True
