"""Settings 단위테스트 — 환경변수 주입·캐시 동작 (시크릿 하드코딩 금지 확인)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from whymath_backend.config import Settings, get_settings


def test_defaults_are_harmless_local() -> None:
    """기본값은 무해한 로컬 루프백 — 코드에 호스트/시크릿 하드코딩 없음."""
    s = Settings()
    assert s.ollama_host == "http://127.0.0.1:11434"
    assert s.ollama_request_timeout_s > 0
    assert s.cache_ttl_s >= 0


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHYMATH_ 접두사 환경변수로 값이 덮어써진다."""
    monkeypatch.setenv("WHYMATH_OLLAMA_HOST", "http://phaiakes9.local:11434")
    monkeypatch.setenv("WHYMATH_OLLAMA_REQUEST_TIMEOUT_S", "5.5")
    s = Settings()
    assert s.ollama_host == "http://phaiakes9.local:11434"
    assert s.ollama_request_timeout_s == 5.5


def test_get_settings_is_cached() -> None:
    """get_settings()는 같은 인스턴스를 재사용(lru_cache)."""
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()


def test_unknown_env_keys_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """다른 슬라이스(DB·결제)의 환경변수가 있어도 무시하고 깨지지 않는다."""
    monkeypatch.setenv("WHYMATH_SOME_FUTURE_DB_URL", "postgres://x")
    s = Settings()  # extra=ignore → 예외 없이 생성
    assert s.ollama_host  # 정상 로드


def test_l4_theta_noise_guard_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """slice 76: 개념 θ 노이즈 가드 임계 — 기본(응답 3·SE 1.0)·env 오버라이드."""
    s = Settings()
    assert s.l4_theta_min_responses == 3
    assert s.l4_theta_max_se == 1.0
    monkeypatch.setenv("WHYMATH_L4_THETA_MIN_RESPONSES", "5")
    monkeypatch.setenv("WHYMATH_L4_THETA_MAX_SE", "0.5")
    s2 = Settings()
    assert s2.l4_theta_min_responses == 5
    assert s2.l4_theta_max_se == 0.5


def test_min_app_version_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPS-17: 기본 0.0.0(게이트 사실상 비활성) — WHYMATH_MIN_APP_VERSION으로 오버라이드."""
    s = Settings()
    assert s.min_app_version == "0.0.0"
    monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "1.3.0")
    s2 = Settings()
    assert s2.min_app_version == "1.3.0"


def test_l4_theta_thresholds_validated() -> None:
    """SE 상한 양수(gt=0)·최소 응답수 음수 불가(ge=0)."""
    with pytest.raises(ValidationError):
        Settings(l4_theta_max_se=0.0)
    with pytest.raises(ValidationError):
        Settings(l4_theta_min_responses=-1)


# ──────────────────────────────────────────────────────────────────────────
# 클라우드 LLM (Anthropic, S5)
# ──────────────────────────────────────────────────────────────────────────
def test_anthropic_model_defaults() -> None:
    """CLOUD_MID=Sonnet 4.6, CLOUD_HIGH=Opus 4.7 alias가 기본값(03a §A.0)."""
    s = Settings()
    assert s.anthropic_model_mid == "claude-sonnet-4-6"
    assert s.anthropic_model_high == "claude-opus-4-7"
    assert s.anthropic_max_tokens == 16000
    assert s.anthropic_request_timeout_s > 0


def test_anthropic_configured_false_when_empty() -> None:
    """키가 비면 미설정(anthropic_configured=False) — 클라우드 생성 불가."""
    s = Settings(anthropic_api_key=SecretStr(""))
    assert s.anthropic_configured is False


def test_anthropic_configured_true_when_set() -> None:
    """키가 채워지고 사용 스위치가 켜지면 설정 완료(anthropic_configured=True)."""
    s = Settings(anthropic_api_key=SecretStr("sk-ant-xyz"), anthropic_api_enabled=True)
    assert s.anthropic_configured is True
    assert s.anthropic_policy_blocked is False


def test_anthropic_api_disabled_by_default_even_with_key() -> None:
    """ARCH-66: 2026-09-24 Kiki 결정 — 기본값은 사용 중단. 키가 있어도 미설정으로 본다."""
    s = Settings(anthropic_api_key=SecretStr("sk-ant-xyz"))
    assert s.anthropic_api_enabled is False
    assert s.anthropic_configured is False
    assert s.anthropic_policy_blocked is True


def test_anthropic_policy_not_blocked_without_key() -> None:
    """키가 없으면 '정책 차단'이 아니라 '미설정'이다 — 두 원인을 섞어 보고하지 않는다."""
    s = Settings(anthropic_api_key=SecretStr(""))
    assert s.anthropic_policy_blocked is False


def test_anthropic_secret_not_leaked_in_repr() -> None:
    """API 키는 SecretStr — repr/str에 평문이 새어나오지 않는다(보안 금기)."""
    s = Settings(anthropic_api_key=SecretStr("sk-ant-supersecret"))
    assert "sk-ant-supersecret" not in repr(s)
    assert "sk-ant-supersecret" not in str(s.anthropic_api_key)
    # 평문은 get_secret_value()로만 꺼낼 수 있다.
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-supersecret"


def test_anthropic_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHYMATH_ANTHROPIC_* 환경변수로 키·모델·토큰이 덮어써진다."""
    monkeypatch.setenv("WHYMATH_ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_MODEL_MID", "claude-sonnet-x")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_MODEL_HIGH", "claude-opus-x")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_MAX_TOKENS", "2048")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_API_ENABLED", "true")
    s = Settings()
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-env"
    assert s.anthropic_model_mid == "claude-sonnet-x"
    assert s.anthropic_model_high == "claude-opus-x"
    assert s.anthropic_max_tokens == 2048
    assert s.anthropic_configured is True


def test_anthropic_tuning_knobs_default_off() -> None:
    """effort/thinking/caching 노브는 기본 OFF(생략) — 현 동작 유지(03a §H#4)."""
    s = Settings(anthropic_effort="", anthropic_thinking=False, anthropic_prompt_caching=False)
    assert s.anthropic_effort == ""
    assert s.anthropic_thinking is False
    assert s.anthropic_prompt_caching is False


def test_anthropic_tuning_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHYMATH_ANTHROPIC_EFFORT/THINKING/PROMPT_CACHING 환경변수로 켤 수 있다."""
    monkeypatch.setenv("WHYMATH_ANTHROPIC_EFFORT", "xhigh")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_THINKING", "true")
    monkeypatch.setenv("WHYMATH_ANTHROPIC_PROMPT_CACHING", "1")
    s = Settings()
    assert s.anthropic_effort == "xhigh"
    assert s.anthropic_thinking is True
    assert s.anthropic_prompt_caching is True


# ──────────────────────────────────────────────────────────────────────────
# SEC-26: CORS/TrustedHost allowlist (48_보안 §P0 "CORS/보안 헤더 미들웨어" 갭)
# ──────────────────────────────────────────────────────────────────────────
def test_cors_allowed_origins_default_deny() -> None:
    """기본값(미설정) → 빈 리스트 = deny-by-default. 네이티브 앱은 CORS 미적용 대상."""
    s = Settings()
    assert s.cors_allowed_origins_list == []
    assert s.cors_allow_credentials is False


def test_cors_allowed_origins_parsed_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """콤마 구분 원시값이 공백 제거·빈 항목 제외로 파싱된다(oauth_redirect_uris와 동일 패턴)."""
    monkeypatch.setenv(
        "WHYMATH_CORS_ALLOWED_ORIGINS", "https://admin.whymath.kr, https://teacher.whymath.kr,"
    )
    s = Settings()
    assert s.cors_allowed_origins_list == [
        "https://admin.whymath.kr",
        "https://teacher.whymath.kr",
    ]


def test_cors_wildcard_with_credentials_rejected_at_boot() -> None:
    """`*` + allow_credentials=True는 부팅 시점에 ValidationError(fail-closed)."""
    with pytest.raises(ValidationError):
        Settings(cors_allowed_origins="*", cors_allow_credentials=True)


def test_cors_wildcard_without_credentials_allowed() -> None:
    """`*`만 단독으로는 허용(credentials 없는 CORS 와일드카드는 표준적으로 안전)."""
    s = Settings(cors_allowed_origins="*", cors_allow_credentials=False)
    assert s.cors_allowed_origins_list == ["*"]


def test_cors_specific_origin_with_credentials_allowed() -> None:
    """와일드카드가 아닌 명시 origin + credentials는 허용된다(금지 대상은 조합 자체가 아니다)."""
    s = Settings(cors_allowed_origins="https://admin.whymath.kr", cors_allow_credentials=True)
    assert s.cors_allow_credentials is True


def test_trusted_hosts_default_wildcard() -> None:
    """미설정 → `["*"]`(전부 허용) — Host 헤더 검증 미구성 상태의 현재 동작 무회귀."""
    s = Settings()
    assert s.trusted_hosts_list == ["*"]


def test_trusted_hosts_parsed_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정되면 명시 리스트로 좁혀진다."""
    monkeypatch.setenv("WHYMATH_TRUSTED_HOSTS_ALLOWLIST", "api.whymath.kr, api2.whymath.kr")
    s = Settings()
    assert s.trusted_hosts_list == ["api.whymath.kr", "api2.whymath.kr"]


# ──────────────────────────────────────────────────────────────────────────
# ARCH-49 — 벤더 표준 키 이름 병행 수용 (DEEPSEEK_API_KEY / OPENROUTER_API_KEY)
#
# 왜 별칭을 두는가: 두 키는 Phaiakes9 User 환경변수에 **벤더 표준 이름으로 이미 등록돼
# 라이브 확인**됐다(2026-09-16). `WHYMATH_` 접두만 읽으면 Kiki에게 재등록 왕복을 요구하게
# 되는데, 그 왕복은 이 저장소가 반복해서 대가를 치른 부류다.
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("env_name", "field_name"),
    [
        ("DEEPSEEK_API_KEY", "deepseek_api_key"),
        ("OPENROUTER_API_KEY", "openrouter_api_key"),
        ("WHYMATH_DEEPSEEK_API_KEY", "deepseek_api_key"),
        ("WHYMATH_OPENROUTER_API_KEY", "openrouter_api_key"),
    ],
)
def test_provider_keys_read_both_vendor_and_prefixed_names(
    monkeypatch: pytest.MonkeyPatch, env_name: str, field_name: str
) -> None:
    """네 이름 전부가 읽힌다 — 한쪽만 읽히면 이 격자의 절반이 RED."""
    monkeypatch.setenv(env_name, "key-from-env")
    assert getattr(Settings(), field_name).get_secret_value() == "key-from-env"


def test_prefixed_name_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """둘 다 있으면 `WHYMATH_` 접두가 이긴다 — 저장소 규약이 벤더 관례를 덮는다.

    우선순위 절이 없으면 어느 쪽이 이길지 알 수 없고, 운영자가 접두 이름으로 덮어쓰려 해도
    조용히 무시될 수 있다(그 상태는 증상이 원인에서 멀다).
    """
    monkeypatch.setenv("WHYMATH_DEEPSEEK_API_KEY", "prefixed")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "vendor")
    assert Settings().deepseek_api_key.get_secret_value() == "prefixed"


def test_unset_provider_keys_report_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """미설정이면 `*_configured`가 False — 키가 없는데 있다고 말하지 않는다."""
    for name in (
        "DEEPSEEK_API_KEY",
        "WHYMATH_DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "WHYMATH_OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.deepseek_configured is False
    assert settings.openrouter_configured is False


def test_alias_does_not_disturb_prefixed_only_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`populate_by_name` 도입이 별칭 없는 기존 필드의 환경변수 규약을 바꾸지 않는가.

    접두 없는 `OLLAMA_HOST`는 **읽히지 않아야** 한다 — 별칭을 연 것은 두 필드뿐이고,
    모델 전역 설정이 다른 필드까지 벤더 이름에 열었다면 이 단언이 실패한다.
    """
    monkeypatch.delenv("WHYMATH_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://should-not-be-read:1")
    assert Settings().ollama_host != "http://should-not-be-read:1"
    monkeypatch.setenv("WHYMATH_OLLAMA_HOST", "http://read-me:2")
    assert Settings().ollama_host == "http://read-me:2"
