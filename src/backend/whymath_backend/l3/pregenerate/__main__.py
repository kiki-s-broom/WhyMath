"""사전적재 CLI — JSONL 스펙 → CachePrewarmer → 사람읽는 리포트.

사용법:
    python -m whymath_backend.l3.pregenerate <specs.jsonl> \\
        [--overwrite] [--ttl-seconds N] [--min-length N] [--generation-log PATH]

스펙 형식(한 줄당 JSON):
    {"prompt": "...", "system": "...",
     "request": {RoutingRequest 필드}, "precomputed_response": "..." | null}

기본 의존성: CompositeProvider(Ollama+Anthropic) + RedisCache + BasicSeedValidator.

생성 로그(EOS-55 집행 별항): 이 경로는 **기본으로** 항목별 `GenerationLog`(모델·재현
좌석·입력 스냅샷 해시+참조)를 `<specs>.genlog.jsonl`에 즉시 flush로 적재한다 —
`--generation-log`로 경로만 바꿀 수 있다(끄는 옵션은 두지 않는다: 적재가 기본이어야
"경로가 적재한다"가 참이다·정본화≠집행). 적재 실패는 배치를 깨지 않는다(타입명 경고).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from whymath_backend.l3.interfaces import CacheBackend, LLMProvider
from whymath_backend.l3.pregenerate.models import PregenItem, PrewarmReport
from whymath_backend.l3.pregenerate.prewarmer import CachePrewarmer
from whymath_backend.l3.pregenerate.provenance_bridge import append_generation_log_jsonl
from whymath_backend.l3.pregenerate.validator import default_seed_validator
from whymath_backend.schema.provenance import GenerationLog


def _build_default_provider() -> LLMProvider:
    """표준 provider 조립(라이브 전용) — 지연 import·지연 연결(구성만으로 네트워크 0)."""
    from whymath_backend.l3.providers.composite import CompositeProvider
    from whymath_backend.l3.providers.factory import build_cloud_provider
    from whymath_backend.l3.providers.ollama import OllamaProvider

    return CompositeProvider(local=OllamaProvider(), cloud=build_cloud_provider())


def _build_default_cache() -> CacheBackend:
    """표준 캐시 조립(라이브 전용) — 지연 import(hermetic 테스트는 가짜 캐시 주입)."""
    from whymath_backend.l3.cache import RedisCache

    return RedisCache()


def default_generation_log_path(specs_path: Path) -> Path:
    """생성 로그 기본 경로 — 스펙 파일 곁 사이드카 `<specs>.genlog.jsonl`(항상 적재)."""
    return specs_path.with_suffix(".genlog.jsonl")


def load_items(text: str) -> list[PregenItem]:
    """JSONL 텍스트(한 줄당 PregenItem JSON) → 항목 리스트. 빈 줄·`#` 주석 무시.

    파싱 오류는 line 번호와 함께 ValueError로 던진다(어떤 줄이 잘못됐는지 명시).
    """
    items: list[PregenItem] = []
    for line_num, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            items.append(PregenItem.model_validate_json(stripped))
        except Exception as exc:  # noqa: BLE001 — 줄 번호 컨텍스트와 함께 재던짐
            raise ValueError(f"line {line_num}: {exc}") from exc
    return items


def format_report(report: PrewarmReport) -> str:
    """사람읽는 1줄 요약 + 실패/스킵 항목 상세."""
    lines: list[str] = [
        (
            f"total={report.total} written={report.written} "
            f"skipped_exists={report.skipped_exists} "
            f"failed_validation={report.failed_validation} errored={report.errored}"
        ),
    ]
    for item in report.items:
        if item.status == "written":
            continue
        key = item.cache_key or "(no key)"
        reason = item.error or ""
        lines.append(f"  [{item.status}] {key} — {reason}")
    return "\n".join(lines)


async def _run(
    specs_path: Path,
    *,
    overwrite: bool,
    ttl_seconds: int,
    min_length: int,
    generation_log_path: Path | None = None,
    provider: LLMProvider | None = None,
    cache: CacheBackend | None = None,
) -> int:
    """CLI 본처리 — provider/cache는 주입 가능(hermetic 통합 테스트 seam·기본은 라이브 조립).

    `generation_log_path=None`이면 사이드카 기본 경로(`default_generation_log_path`)에
    적재한다 — 이 CLI 경로는 *항상* GenerationLog를 남긴다(EOS-55 집행 별항).
    """
    text = specs_path.read_text(encoding="utf-8")
    items = load_items(text)
    resolved_provider = provider if provider is not None else _build_default_provider()
    resolved_cache = cache if cache is not None else _build_default_cache()
    # 기본 게이트: 위생 → 산술 → 부등식 AND 체인 (단일 정본 default_seed_validator).
    validator = default_seed_validator(min_length=min_length)
    genlog_path = (
        generation_log_path
        if generation_log_path is not None
        else default_generation_log_path(specs_path)
    )

    def _sink(log: GenerationLog) -> None:
        """항목별 즉시 flush 적재(2026-08-22 규칙 ① — 도중 사망에도 이력 보존)."""
        append_generation_log_jsonl(genlog_path, log)

    prewarmer = CachePrewarmer(
        provider=resolved_provider,
        cache=resolved_cache,
        validator=validator,
        generation_log_sink=_sink,
    )
    report = await prewarmer.prewarm(items, ttl_seconds=ttl_seconds, overwrite=overwrite)
    print(format_report(report))
    return 0 if report.errored == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리. 종료 코드 0(성공) / 1(하나 이상 error 항목 있음)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l3.pregenerate",
        description="L3 캐시 사전적재 — 런타임과 같은 키로 검증된 시드를 캐시에 채워 넣는다.",
    )
    parser.add_argument("specs_path", type=str, help="JSONL 스펙 파일 경로 (한 줄당 PregenItem)")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 캐시 키가 있어도 덮어쓰기(기본은 스킵)",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=0,
        help="캐시 TTL(초). 0(기본)=무만료(사전생성물은 만료되지 않게).",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=1,
        help="BasicSeedValidator 최소 응답 길이(strip 후).",
    )
    parser.add_argument(
        "--generation-log",
        type=Path,
        default=None,
        help=(
            "GenerationLog JSONL 경로(EOS-55). 미지정 시 <specs>.genlog.jsonl 사이드카에 "
            "항상 적재한다(끄기 없음 — 적재가 기본)."
        ),
    )
    args = parser.parse_args(argv)
    specs_path: str = args.specs_path
    overwrite: bool = args.overwrite
    ttl_seconds: int = args.ttl_seconds
    min_length: int = args.min_length
    generation_log: Path | None = args.generation_log
    return asyncio.run(
        _run(
            Path(specs_path),
            overwrite=overwrite,
            ttl_seconds=ttl_seconds,
            min_length=min_length,
            generation_log_path=generation_log,
        )
    )


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, _run/main이 테스트 대상
    sys.exit(main())
