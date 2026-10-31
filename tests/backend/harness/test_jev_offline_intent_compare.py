"""PED-49 — Jev 오프라인 의도 비교 스크립트 테스트.

라이브 서버 없이 `httpx.MockTransport`로 Jev·Laya 응답을 흉내 낸다. 핵심 동결 대상:
① 합성 게이트가 *외부 호출 전에* 막는지 ② 실패가 정확도 분모에서 빠지지 않는지 ③ 원문 미출력.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "jev_offline_intent_compare", ROOT / "scripts/analysis/jev_offline_intent_compare.py"
)
mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["jev_offline_intent_compare"] = mod
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def _ok_body(choice: str, conf: float = 0.9) -> dict:
    # 실물 laya-serve 응답 픽스처와 같은 모양(answers.intent.choice·answer_confidence·usage)
    return {
        "answers": {"intent": {"choice": choice, "answer_confidence": conf}, "pii": {"noul": 0.0}},
        "usage": {"input_tokens": 200, "output_tokens": 0},
    }


@pytest.fixture
def patch_client(monkeypatch):
    """스크립트 안 httpx.AsyncClient를 MockTransport 클라이언트로 바꾼다. 호출 기록을 돌려준다."""
    calls: list[httpx.Request] = []

    def install(handler):
        def wrapped(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return handler(request)

        real = httpx.AsyncClient
        monkeypatch.setattr(
            mod.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(wrapped), timeout=kw.get("timeout")),
        )
        return calls

    return install


def test_non_synthetic_row_aborts_before_any_call(tmp_path, monkeypatch, patch_client, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    calls = patch_client(lambda r: httpx.Response(200, json=_ok_body("hint")))
    path = _write(
        tmp_path,
        [
            {"text": "힌트 주세요", "label": "hint", "synthetic": True},
            {"text": "실제 학생 문장", "label": "stuck"},  # synthetic 표시 없음
        ],
    )
    rc = mod.main(["--input", str(path), "--output", str(tmp_path / "o.json")])
    assert rc == 2
    assert calls == []  # 첫 행조차 보내지 않았다 — 검사가 전송보다 먼저
    assert "synthetic" in capsys.readouterr().err


def test_unknown_label_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    path = _write(tmp_path, [{"text": "a", "label": "foo", "synthetic": True}])
    assert mod.main(["--input", str(path), "--output", str(tmp_path / "o.json")]) == 2


def test_compare_ok_and_no_raw_text_in_output(tmp_path, monkeypatch, patch_client):
    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-key")
    monkeypatch.setenv("LAYA_API_KEY", "laya-key")

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["questions"] == mod.LAYA_QUESTIONS  # 같은 질문지
        if req.url.host == "api.typesafe.ai":
            assert body["model"] == "jev-1.13.0"  # 버전 고정
            assert req.headers["Authorization"] == "Bearer jev-key"
            return httpx.Response(200, json=_ok_body("answer_only"))
        assert req.headers["Authorization"] == "Bearer laya-key"
        return httpx.Response(
            200, json=_ok_body("stuck" if "모르" in body["state"] else "answer_only")
        )

    calls = patch_client(handler)
    secret_text = "그냥 답만 알려줘 비밀문장XYZ"
    path = _write(
        tmp_path,
        [
            {"text": secret_text, "label": "answer_only", "synthetic": True},
            {"text": "모르겠어요", "label": "stuck", "synthetic": True},
        ],
    )
    out = tmp_path / "o.json"
    assert (
        mod.main(
            ["--input", str(path), "--output", str(out), "--laya-url", "http://127.0.0.1:18080"]
        )
        == 0
    )
    assert len(calls) == 4  # 2행 × (Jev + Laya)
    text = out.read_text(encoding="utf-8")
    assert "비밀문장XYZ" not in text  # 원문 미출력
    rep = json.loads(text)
    assert rep["jev"]["accuracy"] == 0.5
    assert rep["laya"]["accuracy"] == 1.0
    assert rep["agreement_jev_laya"] == 0.5
    assert rep["jev"]["input_tokens_total"] == 400
    assert rep["rule"]["n"] == 2 and "accuracy" not in rep["rule"]  # 규칙은 교차표만


def test_failures_stay_in_denominator_with_type_name(tmp_path, monkeypatch, patch_client):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=_ok_body("hint"))

    patch_client(handler)
    path = _write(
        tmp_path,
        [
            {"text": "a", "label": "hint", "synthetic": True},
            {"text": "b", "label": "hint", "synthetic": True},
        ],
    )
    out = tmp_path / "o.json"
    assert mod.main(["--input", str(path), "--output", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["jev"]["failures"] == 1
    assert rep["jev"]["failure_types"] == {"HTTPStatusError": 1}
    assert rep["jev"]["accuracy"] == 0.5  # 실패 행을 빼고 1.0으로 위장하지 않는다


def test_missing_key_refuses_to_run(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = _write(tmp_path, [{"text": "a", "label": "hint", "synthetic": True}])
    with pytest.raises(SystemExit):
        mod.main(["--input", str(path), "--output", str(tmp_path / "o.json")])


def test_skip_jev_runs_rule_only_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    path = _write(tmp_path, [{"text": "왜 그래요?", "label": "concept", "synthetic": True}])
    out = tmp_path / "o.json"
    assert mod.main(["--input", str(path), "--output", str(out), "--skip-jev"]) == 0
    assert "jev" not in json.loads(out.read_text(encoding="utf-8"))
