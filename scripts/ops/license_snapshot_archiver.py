#!/usr/bin/env python3
"""Tier1 소스 약관 스냅샷 아카이버 (LIC-02) — 확인 시점 약관 HTML+SHA256 보관.

왜 존재하는가 (저작권 K4 계약 — ★소급 불가)
--------------------------------------------
법적 안전조합(`docs/data/licensing_safety.md`)의 근거는 "확인 시점의 약관"이다.
라이선스 페이지는 언제든 바뀔 수 있고, 바뀐 뒤에는 과거 약관을 재구성할 수 없다
(소급 불가). 그래서 확인 시점의 약관 원문(바이트)·SHA256·수집 시각을 지금 보관한다.

무엇을 수집하는가
-----------------
`TIER1_SOURCES` — licensing_safety.md 매트릭스에서 실측 추출한 외부 소스
(자체작성 제외 · 상업 OK ✅ 무조건부 · 외부 약관/라이선스 문서 실재).
목록 도출 규약과 "14곳" 선언 대조(실측 20곳)는 `docs/data/license_snapshot_archive.md` 참조.

실패 경로 설계 (CLAUDE.md 2026-08-22 규칙)
------------------------------------------
① 소스별 즉시 flush — 스냅샷·메타·감사로그·run manifest를 소스 하나 처리할 때마다
   디스크에 기록한다(마지막 일괄 저장 금지 — 중간에 죽어도 그때까지의 증거가 남는다).
② 모든 외부 호출 타임아웃 — 기본 30s. 멈춤은 "타임아웃 사실 자체"를 기록한다.
③ 실패 원인 기록 — HTTP 실패는 상태코드+본문 발췌, 예외는 타입명+메시지.
④ 이번 실행 식별 — run manifest(`runs/<run_id>.json`) + 감사로그 전 라인에 run_id
   (이전 실행 증거를 이번 원인으로 오독하지 않게 한다).
⑤ 0곳 수집 = 측정 실패 exit 1 — 0건을 통과로 위장하지 않는다.

멱등(content-addressed) 규약
----------------------------
같은 내용 재수집 → 파일 신규 생성 없이 감사로그에 "unchanged" 기록.
내용 변경 → 새 스냅샷 파일 + "changed" 기록(prev_sha256 동봉). 최초 수집 → "new".
해시 비교는 **바이트 기준**(정규화 없음 — 표기 차이 오탐 방지의 반대급부로,
동적 요소가 있는 페이지는 changed가 과다 발화할 수 있다. 약관 증거 가치는 불변).
수집 시각은 메타·감사로그에만 있어 동일성 판정을 오염하지 않는다.

수집 예절: 1회 실행당 소스당 정확히 1요청(재시도 = 다음 실행) · 요청 간 지연
(기본 1.0s) · UA 명시. 프록시는 표준 환경변수(HTTPS_PROXY)를 urllib 기본 동작으로 존중.

사용:  python3 scripts/ops/license_snapshot_archiver.py [--out data/licenses]
       [--sources id1,id2] [--timeout 30] [--delay 1.0] [--list]
종료:  0 전곳 성공 / 1 0곳 성공(측정 실패) / 2 사용법 오류 / 3 부분 실패
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path

USER_AGENT = "WhyMathLicenseArchiver/1.0 (license-terms archival; 1 req/source/run)"
MAX_BODY_BYTES = 8 * 1024 * 1024  # 약관 페이지 상한 — 초과는 실패로 기록(무한 응답 방어)
OK_EVENTS = frozenset({"new", "unchanged", "changed"})

# URL 출처 라벨 (Tier1Source.url_origin)
_ORIGIN_GUIDE = "copyright_guide_v2.md §10.1 MONITORED_URLS"
_ORIGIN_OFFICIAL = "공식 사이트 (licensing_safety.md에 URL 부재 — LIC-02에서 확정)"
_ORIGIN_REPO = "공식 저장소 LICENSE (raw / HEAD=기본 브랜치 해석 — LIC-02에서 확정)"
_ORIGIN_DISCOVERED = "공식 사이트 홈페이지 링크에서 발견 (구 URL 404 — LIC-02 2026-08-31 정정)"


@dataclasses.dataclass(frozen=True)
class Tier1Source:
    """Tier1 아카이빙 대상 소스 1곳.

    Attributes:
        source_id: 안정 슬러그 — 감사로그·스냅샷 디렉터리의 영속 키(변경 금지).
        name_ko: licensing_safety.md 매트릭스 상의 자원명.
        license_label: 문서 선언 라이선스.
        url: 약관/라이선스 페이지(수집 대상).
        url_origin: URL의 출처(문서 명시인지, 공식 사이트 상수인지).
    """

    source_id: str
    name_ko: str
    license_label: str
    url: str
    url_origin: str


# 목록 정본 = docs/data/licensing_safety.md 매트릭스 (도출 규칙·"14곳" 선언 대조는
# docs/data/license_snapshot_archive.md). 편입 기준: 외부 소스 · 상업 OK ✅ 무조건부 ·
# 외부 약관/라이선스 문서 실재. 자체작성(약관 없음)·⚠️/❌(백본 아님)는 제외.
TIER1_SOURCES: tuple[Tier1Source, ...] = (
    # ── 한국 자원 (§한국 자원 — 4곳) ─────────────────────────────────────────
    Tier1Source(
        source_id="ncic",
        name_ko="NCIC 성취기준",
        license_label="공공누리 1유형",
        # 루트 페이지 — 하단 공공누리 유형 표시·저작권 고지의 시점 증거
        url="https://www.ncic.go.kr/",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="kogl-license-types",
        name_ko="공공누리 AI유형 (라이선스 유형 본문 — 1유형 포함)",
        license_label="공공누리 AI (2026-01)",
        url="https://www.kogl.or.kr/info/license.do",
        url_origin=_ORIGIN_GUIDE,
    ),
    Tier1Source(
        source_id="aihub",
        name_ko="AIHub 수학 데이터셋 (이용정책)",
        license_label="영리 허용 (AIHub 4조건)",
        url="https://aihub.or.kr/intrcn/guid/usagepolicy.do",
        url_origin=_ORIGIN_GUIDE,
    ),
    Tier1Source(
        source_id="schoolinfo",
        name_ko="학교알리미",
        license_label="공공데이터",
        # 루트 페이지 — 공공데이터 제공·저작권 고지의 시점 증거
        url="https://www.schoolinfo.go.kr/",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    # ── 글로벌 자원 (§글로벌 자원 — 상업 OK ✅ 3곳) ─────────────────────────
    Tier1Source(
        source_id="openstax",
        name_ko="OpenStax",
        license_label="CC BY 4.0",
        url="https://openstax.org/tos",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="siyavula",
        name_ko="Siyavula",
        license_label="CC BY",
        # 2026-08-31 정정: 구 URL `/terms`는 HTTP 404였다(망 제약 없는 Kiki 머신에서도 동일 —
        # egress 문제가 아니라 URL 결함). 홈페이지 href 스캔으로 실제 경로를 *발견*해 확정.
        # 같은 스캔에서 `/info/privacy-policy`도 매칭됐으나 개인정보처리방침은 라이선스 조항이
        # 아니므로 채택하지 않았다(PR #918 리뷰 P2 — 키워드 매칭≠라이선스 근거).
        url="https://www.siyavula.com/info/terms-and-conditions",
        url_origin=_ORIGIN_DISCOVERED,
    ),
    Tier1Source(
        source_id="illustrative-mathematics",
        name_ko="Illustrative Math",
        license_label="CC BY 4.0",
        url="https://illustrativemathematics.org/terms-of-use/",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    # ── LLM 학습 데이터셋 (§LLM 학습 데이터셋 — 상업 OK ✅ 13곳) ────────────
    # (GSM8K · MATH는 문서 한 행이지만 약관 문서가 저장소별로 달라 소스 2곳)
    Tier1Source(
        source_id="numinamath-cot",
        name_ko="NuminaMath-CoT",
        license_label="Apache 2.0",
        url="https://huggingface.co/datasets/AI-MO/NuminaMath-CoT",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="numinamath-tir",
        name_ko="NuminaMath-TIR",
        license_label="Apache 2.0",
        url="https://huggingface.co/datasets/AI-MO/NuminaMath-TIR",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="prm800k",
        name_ko="PRM800K",
        license_label="MIT",
        url="https://raw.githubusercontent.com/openai/prm800k/HEAD/LICENSE",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="phet",
        name_ko="PhET 시뮬레이션",
        license_label="CC BY",
        url="https://phet.colorado.edu/en/licensing",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="metamath-set-mm",
        name_ko="Metamath set.mm",
        license_label="CC0",
        url="https://raw.githubusercontent.com/metamath/set.mm/HEAD/LICENSE",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="omnimath",
        name_ko="OmniMath",
        license_label="공개",
        url="https://huggingface.co/datasets/KbsdJames/Omni-MATH",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="minif2f",
        name_ko="miniF2F",
        license_label="폴더별 상이(lean·isabelle=Apache 2.0 · metamath=MIT · hollight=FreeBSD)",
        # LICENSE 파일 부재 실측(2026-08-30 404) — README §License 절이 라이선스 선언
        # 원문(폴더별 4종: lean=Apache · isabelle=Apache · metamath=MIT · hollight=FreeBSD).
        # 우리가 쓰는 488 Lean 문항은 Apache 2.0이다(LIC-08 — 종전 'MIT' 단일 표기 정정).
        # 기존 스냅샷 meta(9b6de2b0a301c318.meta.json)의 license_label='MIT'는 첫 수집
        # 시점의 선언 기록이라 고치지 않는다 — 이 도구는 스냅샷이 이미 있으면 meta를
        # 다시 쓰지 않으며, 재생성하려면 증거 스냅샷을 지워야 한다(증거 불변 우선).
        url="https://raw.githubusercontent.com/openai/miniF2F/HEAD/README.md",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="olymmath",
        name_ko="OlymMATH",
        license_label="공개",
        url="https://huggingface.co/datasets/RUC-AIBOX/OlymMATH",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="mathlib4",
        name_ko="Mathlib4",
        license_label="Apache 2.0",
        url="https://raw.githubusercontent.com/leanprover-community/mathlib4/HEAD/LICENSE",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="gsm8k",
        name_ko="GSM8K",
        license_label="MIT",
        url="https://raw.githubusercontent.com/openai/grade-school-math/HEAD/LICENSE",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="math-hendrycks",
        name_ko="MATH (Hendrycks)",
        license_label="MIT",
        url="https://raw.githubusercontent.com/hendrycks/math/HEAD/LICENSE",
        url_origin=_ORIGIN_REPO,
    ),
    Tier1Source(
        source_id="openmathinstruct-1",
        name_ko="OpenMathInstruct-1",
        license_label="NVIDIA License",
        url="https://huggingface.co/datasets/nvidia/OpenMathInstruct-1",
        url_origin=_ORIGIN_OFFICIAL,
    ),
    Tier1Source(
        source_id="dlmf",
        name_ko="DLMF",
        license_label="US Gov Work (퍼블릭 도메인)",
        # 경로 미확정(문서 URL 부재) — 404 시 NIST 저작권 정책 페이지로 교체(후속)
        url="https://dlmf.nist.gov/about/notices",
        url_origin=_ORIGIN_OFFICIAL,
    ),
)


@dataclasses.dataclass
class FetchResult:
    """트랜스포트 응답 — status는 HTTP 상태코드, body는 원문 바이트."""

    status: int
    body: bytes
    content_type: str


# hermetic 테스트용 주입 seam — (url, timeout, user_agent) -> FetchResult
FetchFn = Callable[[str, float, str], FetchResult]


def default_fetch(url: str, timeout: float, user_agent: str) -> FetchResult:
    """urllib 기반 기본 트랜스포트 — 프록시 환경변수(HTTPS_PROXY)를 표준 동작으로 존중.

    HTTPError(4xx/5xx)도 '응답'이므로 FetchResult로 돌려준다(상태코드+본문 발췌 기록용).
    그 외(연결 실패·타임아웃·TLS)는 예외로 전파해 호출자가 원인 유형을 기록한다.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(MAX_BODY_BYTES + 1)
            ctype = str(resp.headers.get("Content-Type", "") or "")
            return FetchResult(status=int(resp.status), body=body, content_type=ctype)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096) or b""
        except Exception as read_exc:  # 본문 발췌 실패도 타입명으로 남긴다(침묵 실패 금지)
            body = f"(본문 읽기 실패: {type(read_exc).__name__})".encode()
        ctype = str(exc.headers.get("Content-Type", "") or "") if exc.headers else ""
        return FetchResult(status=int(exc.code), body=body, content_type=ctype)


@dataclasses.dataclass
class SourceOutcome:
    """소스 1곳의 이번 실행 결과(감사로그 1라인과 1:1)."""

    source_id: str
    event: str  # new | unchanged | changed | fetch_failed
    sha256: str | None = None
    http_status: int | None = None
    error_type: str | None = None
    error_detail: str | None = None


@dataclasses.dataclass
class RunSummary:
    """이번 실행 전체 요약 — exit_code가 판정이다(화면 문자열이 아니라)."""

    run_id: str
    outcomes: list[SourceOutcome]
    ok: int
    failed: int
    exit_code: int


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """임시 파일에 쓰고 os.replace — 중단돼도 반쪽 파일이 정본 행세를 못 하게."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _append_audit(audit_path: Path, record: dict) -> None:
    """감사로그(JSONL·append-only)에 1라인 추가하고 **즉시** 디스크로 flush한다."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes(manifest_path, payload.encode("utf-8"))


def _load_last_hashes(audit_path: Path) -> dict[str, str]:
    """감사로그에서 소스별 마지막 관측 SHA256을 복원한다(멱등·변경 판정 기준).

    append-only 로그가 진실 원천이다. 파싱 불가 라인(중단으로 잘린 꼬리 등)은
    건너뛰되 **라인 번호와 예외 타입명을 stderr에 남긴다**(침묵 실패 금지).
    """
    last: dict[str, str] = {}
    if not audit_path.exists():
        return last
    with audit_path.open("r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                print(
                    f"[warn] 감사로그 L{lineno} 파싱 불가({type(exc).__name__}) — 건너뜀",
                    file=sys.stderr,
                )
                continue
            sid, sha = rec.get("source_id"), rec.get("sha256")
            if sid and sha and rec.get("event") in OK_EVENTS:
                last[sid] = sha
    return last


def _classify_error(exc: BaseException, timeout: float) -> tuple[str, str]:
    """예외 → (error_type, error_detail). 멈춤은 타임아웃 사실 자체를 기록한다."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
        return "Timeout", f"응답 없음 — {timeout:g}s 타임아웃 초과"
    detail = str(exc) or repr(exc)
    if reason is not None:
        detail = f"{detail} (reason={reason!r})"
    return type(exc).__name__, detail[:300]


def _ext_for(content_type: str) -> str:
    ctype = content_type.split(";", 1)[0].strip().lower()
    if "html" in ctype:
        return ".html"
    if ctype.startswith("text/") or "json" in ctype or not ctype:
        return ".txt"
    return ".bin"


def archive_one(
    source: Tier1Source,
    out_dir: Path,
    last_hashes: dict[str, str],
    fetch_fn: FetchFn,
    timeout: float,
    run_id: str,
) -> SourceOutcome:
    """소스 1곳을 수집·판정하고 **이 함수 안에서** 스냅샷·감사로그를 디스크에 남긴다.

    Exception만 잡는다 — KeyboardInterrupt 등 BaseException은 전파돼 실행이 중단되며,
    그때까지 처리한 소스의 증거는 이미 flush되어 남아 있다(소스별 즉시 flush 계약).
    """
    audit_path = out_dir / "audit_log.jsonl"
    started = time.monotonic()
    record: dict = {
        "ts": _utc_now_iso(),
        "run_id": run_id,
        "source_id": source.source_id,
        "url": source.url,
    }

    try:
        result = fetch_fn(source.url, timeout, USER_AGENT)
    except Exception as exc:
        etype, edetail = _classify_error(exc, timeout)
        record.update(
            {
                "event": "fetch_failed",
                "error_type": etype,
                "error_detail": edetail,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        )
        _append_audit(audit_path, record)
        return SourceOutcome(
            source.source_id, "fetch_failed", error_type=etype, error_detail=edetail
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if not 200 <= result.status < 300:
        excerpt = result.body[:400].decode("utf-8", errors="replace")
        etype = f"HTTP{result.status}"
        record.update(
            {
                "event": "fetch_failed",
                "http_status": result.status,
                "error_type": etype,
                "error_detail": excerpt,
                "elapsed_ms": elapsed_ms,
            }
        )
        _append_audit(audit_path, record)
        return SourceOutcome(
            source.source_id,
            "fetch_failed",
            http_status=result.status,
            error_type=etype,
            error_detail=excerpt,
        )

    if len(result.body) > MAX_BODY_BYTES:
        etype = "ResponseTooLarge"
        edetail = f"본문 {len(result.body)}B > 상한 {MAX_BODY_BYTES}B"
        record.update(
            {
                "event": "fetch_failed",
                "http_status": result.status,
                "error_type": etype,
                "error_detail": edetail,
                "elapsed_ms": elapsed_ms,
            }
        )
        _append_audit(audit_path, record)
        return SourceOutcome(
            source.source_id,
            "fetch_failed",
            http_status=result.status,
            error_type=etype,
            error_detail=edetail,
        )

    # content-addressed 저장 — 동일성 판정은 바이트 SHA256뿐(시각은 메타에만)
    sha = hashlib.sha256(result.body).hexdigest()
    prev = last_hashes.get(source.source_id)
    if prev is None:
        event = "new"
    elif prev == sha:
        event = "unchanged"
    else:
        event = "changed"

    snap_dir = out_dir / "snapshots" / source.source_id
    snap_path = snap_dir / f"{sha[:16]}{_ext_for(result.content_type)}"
    if not snap_path.exists():  # unchanged 재수집이면 파일이 이미 있어 신규 쓰기 없음
        _atomic_write_bytes(snap_path, result.body)
        meta = {
            "source_id": source.source_id,
            "name_ko": source.name_ko,
            "license_label": source.license_label,
            "url": source.url,
            "sha256": sha,
            "bytes": len(result.body),
            "http_status": result.status,
            "content_type": result.content_type,
            "first_fetched_at": record["ts"],
            "first_run_id": run_id,
        }
        meta_payload = json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _atomic_write_bytes(snap_dir / f"{sha[:16]}.meta.json", meta_payload.encode("utf-8"))

    record.update(
        {
            "event": event,
            "http_status": result.status,
            "content_type": result.content_type,
            "sha256": sha,
            "bytes": len(result.body),
            "snapshot_path": str(snap_path.relative_to(out_dir)),
            "elapsed_ms": elapsed_ms,
        }
    )
    if event == "changed":
        record["prev_sha256"] = prev
    _append_audit(audit_path, record)
    last_hashes[source.source_id] = sha
    return SourceOutcome(source.source_id, event, sha256=sha, http_status=result.status)


def archive_all(
    sources: list[Tier1Source],
    out_dir: Path,
    *,
    fetch_fn: FetchFn | None = None,
    timeout: float = 30.0,
    delay: float = 1.0,
    sleep_fn: Callable[[float], None] | None = None,
    run_id: str | None = None,
) -> RunSummary:
    """전체 소스를 순회 수집한다. 소스마다 증거를 즉시 flush하고 manifest를 갱신한다."""
    if fetch_fn is None:
        fetch_fn = default_fetch
    if sleep_fn is None:
        sleep_fn = time.sleep
    run_id = run_id or _new_run_id()

    manifest_path = out_dir / "runs" / f"{run_id}.json"
    manifest: dict = {
        "run_id": run_id,
        "started_at": _utc_now_iso(),
        "status": "running",  # completed로 못 바뀌었다면 중단된 실행이라는 증거
        "timeout_s": timeout,
        "planned": [s.source_id for s in sources],
        "results": {},
    }
    _write_manifest(manifest_path, manifest)  # 실행 시작 즉시 기록 — 이번 실행 식별

    last_hashes = _load_last_hashes(out_dir / "audit_log.jsonl")
    outcomes: list[SourceOutcome] = []
    for i, source in enumerate(sources):
        if i > 0 and delay > 0:
            sleep_fn(delay)  # 수집 예절 — 요청 간 지연
        outcome = archive_one(source, out_dir, last_hashes, fetch_fn, timeout, run_id)
        outcomes.append(outcome)
        manifest["results"][source.source_id] = {
            "event": outcome.event,
            "sha256": outcome.sha256,
            "error_type": outcome.error_type,
        }
        _write_manifest(manifest_path, manifest)  # 소스별 즉시 flush
        if outcome.event in OK_EVENTS:
            print(f"[ok  {outcome.event:9s}] {source.source_id} sha256={outcome.sha256[:16]}…")
        else:
            print(f"[FAIL {outcome.error_type:8s}] {source.source_id} {outcome.error_detail}")

    ok = sum(1 for o in outcomes if o.event in OK_EVENTS)
    failed = len(outcomes) - ok
    if ok == 0:
        exit_code = 1  # 0곳 수집 = 측정 실패 (0건 통과 위장 금지)
    elif failed == 0:
        exit_code = 0
    else:
        exit_code = 3  # 부분 실패 — 성공·전멸과 구분되는 신호

    manifest.update(
        {
            "status": "completed",
            "finished_at": _utc_now_iso(),
            "ok": ok,
            "failed": failed,
            "exit_code": exit_code,
        }
    )
    _write_manifest(manifest_path, manifest)
    return RunSummary(run_id=run_id, outcomes=outcomes, ok=ok, failed=failed, exit_code=exit_code)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Tier1 소스 약관 스냅샷 아카이버 (LIC-02) — 확인 시점 약관 보관"
    )
    parser.add_argument(
        "--out", default="data/licenses", help="보관소 디렉터리 (기본: %(default)s)"
    )
    parser.add_argument("--sources", default=None, help="쉼표 구분 source_id 필터 (기본: 전체)")
    parser.add_argument("--timeout", type=float, default=30.0, help="요청 타임아웃 초 (기본: 30)")
    parser.add_argument("--delay", type=float, default=1.0, help="요청 간 지연 초 (기본: 1.0)")
    parser.add_argument(
        "--list", action="store_true", help="소스 목록만 출력하고 종료 (네트워크 0)"
    )
    args = parser.parse_args(argv)

    sources = list(TIER1_SOURCES)
    if args.sources:
        wanted = [w.strip() for w in args.sources.split(",") if w.strip()]
        known = {s.source_id: s for s in sources}
        unknown = [w for w in wanted if w not in known]
        if unknown:
            print(f"알 수 없는 source_id: {', '.join(unknown)}", file=sys.stderr)
            print(f"사용 가능: {', '.join(known)}", file=sys.stderr)
            return 2
        sources = [known[w] for w in wanted]

    if args.list:
        for s in sources:
            print(f"{s.source_id:26s} {s.license_label:28s} {s.url}")
        print(f"\nTier1 소스 {len(sources)}곳 (규약: docs/data/license_snapshot_archive.md)")
        return 0

    out_dir = Path(args.out)
    summary = archive_all(sources, out_dir, timeout=args.timeout, delay=args.delay)

    counts = Counter(o.event for o in summary.outcomes)
    breakdown = " · ".join(
        f"{ev}={counts[ev]}" for ev in ("new", "changed", "unchanged") if counts[ev]
    )
    print(f"\nrun_id={summary.run_id}")
    print(f"감사로그: {out_dir / 'audit_log.jsonl'}")
    print(f"manifest: {out_dir / 'runs' / (summary.run_id + '.json')}")
    print(
        f"수집 성공 {summary.ok}/{len(summary.outcomes)}곳"
        + (f" ({breakdown})" if breakdown else "")
        + f" · 실패 {summary.failed}곳 · exit={summary.exit_code}"
    )
    if summary.ok == 0:
        print("0곳 수집 — 측정 실패로 판정(exit 1). 소스별 원인은 감사로그 참조.", file=sys.stderr)
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
