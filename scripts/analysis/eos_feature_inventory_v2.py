"""EOS 기능 인벤토리 **v2 — 기능 단위 전수 장부** + Migration Map (EOS-83 · EOS-68 후속).

v1(`eos_feature_inventory.py`)은 모집단을 *라우터 1개 = 기능 1개*(23행)로 잡았다 — Gate 0-D
판정에는 충분했지만, 계획서 100 §3.3이 말하는 "기능"(사용자에게 의미 있는 서빙 능력 1단위)보다
훨씬 굵다(`me` 라우터 하나가 36 엔드포인트·16개 기능을 품는다). v1 문서 §1이 스스로 "이 표의
행 수는 하한이다"라고 적었고, 이 v2가 그 하한을 **기능 단위**로 내려 전수화한다.

## 모집단 정의 v2 (먼저 적는다 — 이 정의로 잡히지 않는 것은 "전수"가 아니다)

**기능 = 사용자(학생·보호자·운영자·플랫폼)에게 의미가 있는 능력 1단위.** 네 평면으로 나눠
각 평면의 *전수성*을 기계가 검사한다:

- **S 서빙 표면** — `app.py`가 include한 라우터의 *엔드포인트 그룹*(경로 접두·의미 단위).
  전수성: 모든 엔드포인트가 정확히 1행에 귀속. 미귀속·중복 귀속은 exit 1.
- **E 백엔드 엔진** — `whymath_backend` 하위 모듈 *가족*(l1~l6·whs·harness 런타임·schema·db·
  infra). 전수성: 모든 `.py` 모듈이 정확히 1행에 귀속(S 평면의 라우터 모듈 제외). 미귀속·
  중복은 exit 1.
- **C 클라이언트** — Flutter `lib/features/*`·`lib/core`·web 그래핑 계산기. 전수성: 모든
  feature 디렉터리가 1행에 귀속.
- **O 운영자 도구** — `ops`·`privacy` CLI·`harness` 배치/게이트/리포트 가족. E 평면과 같은
  모듈 귀속 검사에 포함.

**모집단이 아닌 것**: backlog 태스크(작업 단위) · 테스트 파일 · alembic 리비전 개별 · docs.
`data_pipeline` ETL은 독립 행이 아니라 **대응 L1 적재 행의 "현재 위치"에 병기**한다(ETL과
적재기는 한 기능의 두 절반이다).

계획서의 "기존 120개"는 저장소 외부 xlsx 수치라 개수 정합은 판정 대상이 아니다(v1 §1과 동일).
이 장부의 행 수는 위 정의에서 **기계로 도출**되며, 정의가 바뀌면 행 수도 바뀐다.

## 가장 중요한 두 필드 — 둘 다 기계가 낸다

- **EOS Ownership**: `eos_core_adapter_boundary_scan.BOUNDARY_MAP`(EOS-65 정본)으로 행의 *자기
  모듈*을 판정한다. 전부 CORE → `CORE` · 전부 ADAPTER → `ADAPTER` · CORE와 ADAPTER 동거 또는
  MIXED 모듈 포함 → `MIXED` · 횡단 → `INFRA` · 클라 → `CLIENT`. S 평면은 라우터가 호출하는
  모듈의 1-hop 폐쇄로 판정하며 ADAPTER 의존이 있으면 `CORE+ADAPTER_DEP`(SubjectAdapter 경유로
  절단해야 하는 의존)로 적는다.
- **Migration Action**: 계획서 100 §3.14 6축 18점 매트릭스(임계는 v1에서 import — 이중 정의
  금지) → KEEP/REFACTOR/HEAVY_REFACTOR/REPLACE_CANDIDATE. 여기에 **POSTPONE** 규칙 1개를 더한다:
  출시 우선도(제안)가 P2(2027 이월 후보)이면 판정을 `POSTPONE`으로 덮고 매트릭스 판정은
  `matrix_action`에 그대로 남긴다 — 이월은 삭제가 아니므로(계획서 006 §26) 원 판정을 잃지 않는다.

## 6축 대리지표 — v1 상속 + 평면별 확장 (한계 명시)

- **A 과목결합** — S: 폐쇄의 ADAPTER/MIXED 수(v1 규칙). E/O: 소유가 ADAPTER면 **0**(소속이지
  부채가 아님) · MIXED면 **3** · CORE/INFRA면 v1 규칙. C: 0(수학 판정 금지 거버넌스 테스트).
- **B DB결합** — 폐쇄(또는 자기 모듈 import)의 `db.models.*` 수. C: 0.
- **C 모듈결합** — S: 엔드포인트 본문이 참조하는 내부 모듈 수. E/O: 자기 모듈 밖 내부 import 수.
  C: 타 feature·core import 수.
- **D 테스트부족** — S: 경로 리터럴을 담은 테스트 파일의 test fn 수. E/O: 자기 모듈(또는 직계
  부모 패키지)을 import하는 테스트 파일의 test fn 수. C: feature 경로를 담은 dart 테스트의
  test/testWidgets 수.
- **E 상태변경** — S: 쓰기 엔드포인트 수. E/O: ORM 변이 호출 수(`.add/.commit/.flush/insert(`…).
  C: 쓰기 HTTP 호출 수.
- **F 데이터이전** — B와 동일 원천의 다른 밴드(v1 한계 그대로). C: 0.

한계: 1-hop만 본다 · 문자열·동적 import 사각 · D축은 파일 단위라 공유 스위트를 과대평가할 수 있다
(한 테스트 파일이 여러 행에 중복 계상될 수 있다 — 행 간 비교용이지 절대치가 아니다) · 가족이
클수록 B~F가 합산으로 커진다(가족 전체를 옮기는 난이도라는 뜻이지 코드 품질이 아니다).

## 파생 필드 규칙 (전부 기계)

- **결합도** = C축 0~1 Low · 2 Med · 3 High
- **테스트** = D축 0 Full · 1~2 Partial · 3 None
- **Migration Risk** = 총점 ≥10 또는 소유 MIXED → High · 5~9 → Med · ≤4 → Low
- **상태** = 카탈로그 선언값. 단 `flag`가 지정된 행은 `config.py`의 **기본값을 실측**해 꺼져 있으면
  `Flag-off`로 덮는다(선언과 실체가 다르면 실체가 이긴다)
- **출시 우선도**는 **제안**이다(v1 acceptance ④ 동일) — P0 = 12월 검증 G1~G5 차단 조건 경로 또는
  불변 계약 · P1 = 검증 경로에 있으나 차단 조건 아님 · P2 = 이월 후보(선언 §6-5 N군). 확정은 Kiki.

사용법:
    python3 scripts/analysis/eos_feature_inventory_v2.py            # 대시보드 + 마크다운 표
    python3 scripts/analysis/eos_feature_inventory_v2.py --write    # yaml·csv 장부 생성

`--write`가 내는 두 파일은 **저장소에 커밋하지 않는다**(`.gitignore` · OPS-76). 이 생성기의
입력에 백로그 대장과 소스 LOC가 들어가므로 백로그를 건드리는 거의 모든 PR이 전 행을 재생성하고,
그 결과는 자동 병합이 안 된다 — 그리고 충돌한 PR은 GitHub이 `refs/pull/N/merge`를 만들지 못해
CI가 아예 발화하지 않는다. 필요할 때 각자 만들어 보는 산출물로 다룬다.

종료코드: 0 측정 성공 · 1 측정 실패(전수성 위반·모집단 붕괴 — 빈 장부를 성공으로 위장 금지).
"""

from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import importlib.util
import io
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "src" / "backend" / "whymath_backend"
PIPELINE = REPO / "src" / "data-pipeline" / "data_pipeline"
MOBILE = REPO / "src" / "mobile"
WEB_CALC = REPO / "src" / "web" / "graphing-calculator"
TESTS = REPO / "tests"
LEDGER_YAML = REPO / "backlog" / "inventory" / "feature_inventory_v2.yaml"
LEDGER_CSV = REPO / "backlog" / "inventory" / "feature_inventory_v2.csv"
V1_SCRIPT = pathlib.Path(__file__).with_name("eos_feature_inventory.py")
SCAN_SCRIPT = pathlib.Path(__file__).with_name("eos_core_adapter_boundary_scan.py")

PLANES = {"S": "서빙 표면", "E": "백엔드 엔진", "C": "클라이언트", "O": "운영자 도구"}
OWNERSHIP_VOCAB = ("CORE", "CORE+ADAPTER_DEP", "ADAPTER", "MIXED", "INFRA", "CLIENT")
EOS_TARGET = {
    "CORE": "EOS Core",
    "CORE+ADAPTER_DEP": "EOS Core (Adapter 의존 → SubjectAdapter 경유 절단)",
    "ADAPTER": "Math Adapter",
    "MIXED": "Core/Adapter 분리 필요",
    "INFRA": "EOS Infra",
    "CLIENT": "Client (View Layer)",
}
PRIORITIES = ("P0", "P1", "P2", "P3")
# ── 12/31 폐쇄루프 씨앗 — "이 기능이 없으면 폐쇄루프가 깨지는가"의 *기계 판정* 출발점 ──
# 학생 루프: 계획서 300 §12 API 12종 ↔ 저장소 대응표(eos_phase2_plan_300_gap_review §3) 그대로.
STUDENT_LOOP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("auth", "POST /{provider}/callback"),
        ("auth", "POST /refresh"),
        ("users", "GET /me"),
        ("users", "PATCH /me"),
        ("me", "GET /diagnosis/concepts"),
        ("me", "GET /diagnosis/summary"),
        ("me", "POST /assessments/assemble"),
        ("me", "GET /next-problem"),
        ("me", "POST /attempts"),
        ("me", "GET /mastery/current"),
        ("me", "GET /weak-concepts"),
        ("me", "GET /weak-concepts/{concept_id}/learning-path"),
        ("problems", "GET /{problem_id}"),
        ("problems", "GET /{problem_id}/steps"),
        ("concepts", "GET /content"),
        ("concepts", "GET /{concept_id}"),
        ("coach", "POST /coach/sessions"),
        ("coach", "POST /coach/sessions/{dialogue_id}/turns"),
        ("coach", "GET /coach/sessions/{dialogue_id}"),
        ("verify", "POST /verify-step"),
        ("verify", "POST /verify-solution"),
        ("verify", "POST /verify-answer"),
        ("study", "POST /{objective_id}/study"),
        ("study", "POST /{objective_id}/outcome"),
        ("solution_paths", "GET /{solution_path_id}/steps"),
    }
)
# 앵커 콘텐츠 생산 루프: 선언 부록 E G1~G3·G5 차단 조건의 집행 지점.
PRODUCTION_LOOP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("app", "POST /v1/generate"),
        ("app", "GET /v1/jobs/{job_id}"),
        ("dsl", "POST /generate"),
        ("dsl", "POST /validate"),
        ("dsl", "POST /compile"),
    }
)
PRODUCTION_LOOP_MODULES: tuple[str, ...] = (
    "harness.problem_corpus_accumulate",  # G1 앵커 1개 E2E(생성→검증→검수큐)
    "harness.review_session",  # G1 HIT 이벤트 적재
    "harness.review_timer",
    "harness.needs_review_worklist",  # G1 검수큐
    "ops.hit_cu_metrics",  # G2 HIT 중앙값 판독
    "harness.qa_pipeline",  # G2 자동검증률 · G3 누설 0
    "harness.golden_benchmark",  # G2 자동검증이 맞는지(EOS-60 FN율)
    "harness.anchor_round_ledger",  # G2 CU 물량 회차 대장(EOS-64)
    "ops.provenance_audit",  # G1 provenance 레일 · G2 금칙 소스
    "ops.validation_scorecard",  # G5 Go/No-Go 판정기
)
# 불변 계약(선언 §0-6): 루프 도달성과 무관하게 P0 — 미성년 PII·저작권 레일·Langfuse 추적·동의.
# *구현*하는 모듈만 본다(서빙 표면은 호출 폐쇄에, 엔진은 자기 모듈에). `api._auth`처럼 모든
# 엔드포인트가 *사용*하는 인증 배관은 여기 넣지 않는다 — 넣으면 인증이 걸린 전 표면이 P0가 된다.
INVARIANT_MODULE_PREFIXES: tuple[str, ...] = (
    "privacy.",
    "consent",
    "l1.rights",
    "l3.data_export_policy",
    "l3.data_grade_defaults",
    "l3.trace",
    "ops.log_scrubber",
)
# 인증·암호화 배관 자체(User/Auth — 계획서 100 P0 예시) — 자기 모듈로만 판정.
INVARIANT_AUTH_MODULES: tuple[str, ...] = ("security", "api._auth", "api._crypto")
AXES = ("A_subject", "B_db", "C_coupling", "D_tests", "E_state", "F_data")
# data_pipeline 패키지 배정 — BOUNDARY_MAP은 backend만 다루므로 ETL 절반은 여기서 판정한다.
# 규칙은 l1 배정과 동일: 실어 나르는 엔티티가 수식(latex·canonical)이면 MIXED.
PIPELINE_MAP: dict[str, str] = {
    "formula_graph": "MIXED",
    "strategy_graph": "MIXED",
}
_DB_MUTATION = re.compile(
    r"\.(?:commit|flush|add|add_all|merge|bulk_save_objects)\(|\b(?:insert|delete|update)\(\s*[A-Z]"
)
_DART_TEST = re.compile(r"^\s*(?:test|testWidgets)\(", re.M)
_JS_TEST = re.compile(r"^\s*(?:test|it)\(", re.M)
_DART_WRITE = re.compile(r"\.(?:post|patch|delete|put)\s*(?:<[^>]*>)?\s*\(")
_PY_TESTFN = re.compile(r"(?m)^\s*(?:async )?def test_")
_CLIENT_SUFFIXES = {".dart", ".js", ".jsx", ".ts", ".tsx"}

# 코드젠 산출물은 저장소의 *기능*이 아니라 빌드 부산물이다(`src/mobile/.gitignore` 22~25행이
# freezed·json_serializable·riverpod 출력을 무시한다 — CI가 build_runner로 매번 만든다).
# 이걸 세면 **로컬에 build_runner를 돌렸는지 여부에 따라 장부가 달라진다** — 2026-09-05 실측:
# `features/ocr`이 추적 파일만 822줄인데 산출물 포함 2188줄로 잡혀 드리프트 테스트가 CI에서
# RED가 됐다(로컬은 초록 — 정확히 "내 기계에선 되는데"의 형태). 파일 목록은 디스크가 아니라
# **추적 대상**을 따라야 결정론이 성립한다.
_GENERATED_CLIENT = re.compile(r"\.(?:g|freezed|gr|config|mocks)\.dart$")

# 의존성·빌드 산출물 디렉터리도 저장소의 기능이 아니다 — `src/web/graphing-calculator/.gitignore`가
# node_modules/·dist/·coverage/·.vite/를, `src/mobile`이 build/·.dart_tool/을 무시한다. rglob은
# 무시 목록을 모르므로 여기서 이름으로 자른다. 안 자르면 `npm ci`·`vitest --coverage`·`vite build`를
# 돌린 기계에서만 WM-C-007의 loc이 부풀어 위 코드젠 사고와 같은 형태의 드리프트가 난다
# (PR #980 Codex P2 지적 — 정정 2026-09-06).
_EXCLUDED_CLIENT_DIRS = frozenset(
    {"node_modules", "dist", "coverage", ".vite", "build", ".dart_tool"}
)


def _client_source_files(root: pathlib.Path) -> list[pathlib.Path]:
    """클라 디렉터리 아래 *소스*만 — 코드젠 산출물·의존성·빌드 디렉터리는 제외(결정론)."""
    return [
        q
        for q in sorted(root.rglob("*"))
        if q.suffix in _CLIENT_SUFFIXES
        and not _GENERATED_CLIENT.search(q.name)
        and not (_EXCLUDED_CLIENT_DIRS & set(q.relative_to(root).parts[:-1]))
    ]


# ──────────────────────────────────────────────────────────────────────
# 카탈로그 — 측정 불가 필드(이름·사용자·Domain·우선도 제안·근거)만 손으로 든다.
# 귀속(어느 모듈·어느 엔드포인트가 이 행인가)은 손으로 적지만 전수성은 기계가 검사한다.
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Spec:
    fid: str
    name: str
    plane: str
    user: str
    domain: str
    priority: str
    seat: str
    router: str = ""  # S: api 모듈명(또는 "app")
    routes: tuple[str, ...] = ()  # S: "METHOD /path" — 라우터 prefix 제외·루트는 "/"
    modules: tuple[str, ...] = ()  # E/O: whymath_backend 점 경로(패키지·fnmatch 허용·"-x"는 제외)
    pipelines: tuple[str, ...] = ()  # data_pipeline 패키지(E-L1 행의 ETL 절반)
    client: tuple[str, ...] = ()  # C: src/ 기준 상대 경로
    flag: str = ""  # config.Settings 필드 — 기본값 실측으로 status 덮기
    status: str = "Production"
    duplicate_of: str = ""  # §3.4 REPLACE 신호 '동일 기능 중복 구현' — 원본 행 ID(선언·근거는 seat)
    loop_seed: bool = False  # 폐쇄루프 진입점 선언(클라 앱 셸처럼 import 그래프에 안 잡히는 좌석)
    horizon: str = ""  # "P3" = 장기 연구/플랫폼 선언(근거는 seat) — P3는 선언으로만 생긴다


def _s(
    fid: str,
    name: str,
    user: str,
    domain: str,
    pr: str,
    seat: str,
    router: str,
    *routes: str,
    flag: str = "",
    status: str = "Production",
) -> Spec:
    return Spec(
        fid,
        name,
        "S",
        user,
        domain,
        pr,
        seat,
        router=router,
        routes=routes,
        flag=flag,
        status=status,
    )


def _e(
    fid: str,
    name: str,
    user: str,
    domain: str,
    pr: str,
    seat: str,
    *modules: str,
    pipelines: tuple[str, ...] = (),
    flag: str = "",
    status: str = "Production",
    plane: str = "E",
    duplicate_of: str = "",
    horizon: str = "",
    loop_seed: bool = False,
) -> Spec:
    return Spec(
        fid,
        name,
        plane,
        user,
        domain,
        pr,
        seat,
        modules=modules,
        pipelines=pipelines,
        flag=flag,
        status=status,
        duplicate_of=duplicate_of,
        horizon=horizon,
        loop_seed=loop_seed,
    )


def _o(
    fid: str,
    name: str,
    user: str,
    domain: str,
    pr: str,
    seat: str,
    *modules: str,
    flag: str = "",
    status: str = "Batch",
) -> Spec:
    return _e(fid, name, user, domain, pr, seat, *modules, flag=flag, status=status, plane="O")


def _c(
    fid: str,
    name: str,
    user: str,
    domain: str,
    pr: str,
    seat: str,
    *client: str,
    status: str = "Production",
    loop_seed: bool = False,
) -> Spec:
    return Spec(
        fid, name, "C", user, domain, pr, seat, client=client, status=status, loop_seed=loop_seed
    )


# fmt: off
CATALOG: tuple[Spec, ...] = (
    # ════════════════════ S 서빙 표면 — 엔드포인트 그룹 ════════════════════
    _s("WM-S-001", "헬스체크·상태 조회", "Platform", "Operations", "P1",
       "OPS-01 관측성 — /health·/status", "app",
       "GET /health", "GET /health/live", "GET /health/ready", "GET /status"),
    _s("WM-S-002", "LLM 생성 게이트웨이(동기·비동기 잡)", "Platform", "AI Orchestration", "P0",
       "C1·A5 — /v1/generate 생성 표면", "app",
       "POST /v1/generate", "GET /v1/jobs/{job_id}"),
    _s("WM-S-003", "소셜 로그인(OAuth 카카오·네이버)", "Student", "Identity", "P0",
       "계획서 100 P0 'User/Auth' — 폐쇄루프 진입점", "auth",
       "GET /{provider}/state", "POST /{provider}/callback"),
    _s("WM-S-004", "토큰 회전·로그아웃", "Student", "Identity", "P0",
       "SEC 축 — 리프레시 회전·denylist", "auth", "POST /refresh", "POST /logout"),
    _s("WM-S-005", "활성 세션 목록·원격 로그아웃", "Student", "Security", "P1",
       "SEC-10 낯선 기기 인지", "auth",
       "GET /sessions", "DELETE /sessions", "DELETE /sessions/{session_id}"),
    _s("WM-S-006", "내 프로필 조회·수정(온보딩)", "Student", "Identity", "P0",
       "폐쇄루프 진입 — 학년·학교유형 입력(EOS-82)", "users", "GET /me", "PATCH /me"),
    _s("WM-S-007", "법정대리인 동의 기록·철회·조회", "Parent", "Security", "P0",
       "PIPA §22-2 — 법령 유래 절차(기계 대체 금지)", "users",
       "POST /me/parental-consent", "DELETE /me/parental-consent", "GET /me/parental-consent",
       flag="parental_consent_grant_enabled"),
    _s("WM-S-008", "디바이스 등록·폐기·목록", "Student", "Security", "P1",
       "디바이스 서명 인증 — SEC 축", "devices",
       "POST /register", "POST /{device_id}/revoke", "GET /"),
    _s("WM-S-009", "개인정보 처리 권한 판정(PEP)", "Platform", "Security", "P0",
       "미성년 PII PEP — 불변 계약(선언 §0-6)", "privacy", "POST /authorize"),
    _s("WM-S-010", "내 학습 세션 이력·종료·삭제", "Student", "Event", "P1",
       "E3 학습 이력 — GDPR 삭제 포함", "me",
       "GET /sessions", "PATCH /sessions/{session_id}/end", "DELETE /sessions/{session_id}"),
    _s("WM-S-011", "내 진단 이력·완료·삭제", "Student", "Assessment", "P1",
       "E4 진단 이력", "me",
       "GET /assessments", "PATCH /assessments/{assessment_id}/complete",
       "DELETE /assessments/{assessment_id}"),
    _s("WM-S-012", "평가 조립(청사진)·측정 캡처", "Student", "Assessment", "P0",
       "계획서 300 Gate2 ②진단 — ASM-03/04", "me",
       "POST /assessments/capture", "POST /assessments/assemble"),
    _s("WM-S-013", "내 코치 대화 이력·종료·삭제", "Student", "Pedagogy", "P1",
       "E3 대화 이력 — GDPR 삭제 포함", "me",
       "GET /dialogues", "PATCH /dialogues/{dialogue_id}/end", "DELETE /dialogues/{dialogue_id}"),
    _s("WM-S-014", "내 개인정보 감사 이력 조회(삭제·접근)", "Student", "Security", "P1",
       "SEC-09 감사 4종 — 학생 열람권", "me", "GET /deletions", "GET /privacy-audit"),
    _s("WM-S-015", "풀이 채점 제출(attempt 적재+숙달 갱신)", "Student", "Learning Model", "P0",
       "E3 AttemptEvent — 폐쇄루프 서버 뒷반쪽(EOS-81)", "me", "POST /attempts"),
    _s("WM-S-016", "개념·스킬 숙달 곡선 조회", "Student", "Learning Model", "P0",
       "E4 mastery 조회 — G2 ⑧", "me",
       "GET /mastery", "GET /skill-mastery", "GET /mastery/current"),
    _s("WM-S-017", "IRT 능력(θ) 추정·스냅샷·성장 곡선", "Student", "Learning Model", "P0",
       "E4 — θ 추정·시계열", "me",
       "GET /ability", "POST /ability/snapshots", "GET /ability/snapshots",
       "GET /ability/by-concept", "GET /ability/history"),
    _s("WM-S-018", "개념 진단(BKT↔IRT 교차검증)·요약", "Student", "Assessment", "P0",
       "계획서 300 Gate2 ②진단 완료", "me", "GET /diagnosis/concepts", "GET /diagnosis/summary"),
    _s("WM-S-019", "약개념 추천·복습 우선순위 큐", "Student", "Recommendation", "P0",
       "Gate2 ④ Concept 자동 선택", "me", "GET /weak-concepts", "GET /review-queue"),
    _s("WM-S-020", "선수개념 갭·학습 경로·개념 코칭 결정", "Student", "Recommendation", "P0",
       "Gate2 ④·⑨ — 선수 traversal·위상정렬", "me",
       "GET /weak-concepts/{concept_id}/prerequisites",
       "GET /weak-concepts/{concept_id}/coaching",
       "GET /weak-concepts/{concept_id}/learning-path"),
    _s("WM-S-021", "적응형 다음 문항 추천(IRT CAT)", "Student", "Recommendation", "P0",
       "Gate2 ⑨ 다음 학습 자동 추천 — REC-03 회계", "me", "GET /next-problem"),
    _s("WM-S-022", "목표 진행 상황(D-day·성취기준 커버리지)", "Student", "Learning Model", "P2",
       "수능 목표 축 — 12월 검증 비관여", "me", "GET /target-progress"),
    _s("WM-S-023", "계정 삭제권·데이터 이동권(내보내기)", "Student", "Security", "P0",
       "R11 삭제권·열람권 — 미성년 PII 불변 계약", "me", "DELETE /", "GET /export"),
    _s("WM-S-024", "성장 증거 노출(학생 안전)·대리지표 원시값(admin)", "Student", "Pedagogy", "P1",
       "PED-06/08 노출 계약 — 반게임화 축", "me", "GET /growth-evidence", "GET /harness-metrics"),
    _s("WM-S-025", "학습시간 통계", "Student", "Analytics", "P1",
       "COLLAB-03 롤업의 조회 표면", "me", "GET /learning-metrics"),
    _s("WM-S-026", "학습목표 맞춤 학습 단위 공급·결과 기록", "Student", "Pedagogy", "P0",
       "E1 학습 공급·교수법 처치(MOB-13)", "study",
       "POST /{objective_id}/study", "POST /{objective_id}/outcome"),
    _s("WM-S-027", "교수학 통합 결정(stateless 코치)", "Student", "Pedagogy", "P0",
       "E2·C7 코칭 결정 표면", "coach", "POST /coach"),
    _s("WM-S-028", "코치 대화 세션(생성·턴 추가·조회)", "Student", "Pedagogy", "P0",
       "E2 — 채점 연동 코칭·S3-32 완료 경로(attempt 생산자)", "coach",
       "POST /coach/sessions", "POST /coach/sessions/{dialogue_id}/turns",
       "GET /coach/sessions/{dialogue_id}"),
    _s("WM-S-029", "결정론 채점 3종(단계·풀이·답 검산)", "Student", "Math Engine", "P0",
       "D1·E2 — SymPy 단일 권위 서빙 표면", "verify",
       "POST /verify-step", "POST /verify-solution", "POST /verify-answer"),
    _s("WM-S-030", "문제 조회(공개 투영·단계·관계)", "Student", "Content", "P0",
       "B7 문제 DB 서빙 — 정답 유도 필드 제외 투영", "problems",
       "GET /", "GET /{problem_id}", "GET /{problem_id}/steps", "GET /{problem_id}/relations"),
    _s("WM-S-031", "문제 저작 CRUD", "Admin", "Content", "P1",
       "B7 — 운영자 저작 표면", "problems",
       "POST /", "PATCH /{problem_id}", "DELETE /{problem_id}"),
    _s("WM-S-032", "검증 풀이 경로 단계 점층 공개", "Student", "Content", "P0",
       "C5 단계별 풀이", "solution_paths", "GET /{solution_path_id}/steps"),
    _s("WM-S-033", "개념 그래프 조회(목록·단건·엣지)", "Student", "Knowledge Graph", "P0",
       "B4 개념 DB 조회", "concepts", "GET /", "GET /{concept_id}", "GET /{concept_id}/edges"),
    _s("WM-S-034", "개념 의미검색(pgvector)", "Student", "Knowledge Graph", "P1",
       "원자 검색 좌석 — S0-4a", "concepts", "GET /search"),
    _s("WM-S-035", "개념 콘텐츠(정의·비유·예시) 조회", "Student", "Content", "P0",
       "Gate2 ⑤ Content→Problem 연결", "concepts", "GET /content"),
    _s("WM-S-036", "개념 노드 저작 CRUD", "Admin", "Knowledge Graph", "P1",
       "B4 — 운영자 저작 표면", "concepts",
       "POST /", "PATCH /{concept_id}", "DELETE /{concept_id}"),
    _s("WM-S-037", "교육과정 프레임워크·버전·노드 조회", "Admin", "Curriculum", "P0",
       "B1 — CUR-10/11 과목 중립 API", "curricula",
       "GET /curricula", "GET /curricula/{framework_id}", "GET /curricula/{framework_id}/nodes"),
    _s("WM-S-038", "성취기준(학습 성과) 단건 조회", "Admin", "Curriculum", "P0",
       "B1 성취기준 895", "curricula", "GET /learning-outcomes/{norm_id}"),
    _s("WM-S-039", "개념↔성취기준 정렬 통합 조회", "Admin", "Curriculum", "P0",
       "B2·F1 앵커 매핑 조회", "alignments", "GET /"),
    _s("WM-S-040", "권리(저작권) 판정 게이트웨이", "Platform", "Content", "P0",
       "A4·G1~G6 저작권 레일(LIC-01) — 전용 테스트 0건은 v1이 검출", "rights",
       "POST /check", "POST /batch-check", "GET /{content_type}/{content_id}"),
    _s("WM-S-041", "L6 응용 모드 게이팅 6종(재수·수능·학교진도·사고력·메타인지·영재)",
       "Student", "Application Mode", "P2", "L6 모드는 12월 검증 밖(v1 동일 판정)", "gating",
       "GET /retake", "GET /suneung", "GET /school-progress", "GET /thinking",
       "GET /metacognition", "GET /gifted"),
    _s("WM-S-042", "약점 개념 맞춤 시각화 생성", "Student", "Interaction", "P2",
       "시각화 축 — 검증설계서 대응 없음", "visualization", "POST /weak-concept"),
    _s("WM-S-043", "시각화 명세 검증·공유 링크", "Student", "Interaction", "P2",
       "Graph2dSpec 라운드트립", "visualization", "POST /spec", "GET /spec"),
    _s("WM-S-044", "약점 개념 맞춤 학습 장면 생성", "Student", "Interaction", "P2",
       "LearningScene DSL", "scene", "POST /weak-concept"),
    _s("WM-S-045", "시각화 조작 이벤트 적재", "Student", "Event", "P1",
       "L2 행동 분석 입력 — E3 계열", "interactions", "POST /"),
    _s("WM-S-046", "손글씨 풀이 OCR(단일·다중 페이지)", "Student", "Math Engine", "P2",
       "E1은 MathLive 입력이지 OCR 아님(검증설계서 §2)", "ocr", "POST /", "POST /pages",
       flag="ocr_enabled"),
    _s("WM-S-047", "수식 한국어 낭독 명세 생성", "Student", "Math Engine", "P2",
       "접근성 축", "speech", "POST /latex"),
    _s("WM-S-048", "DSL 콘텐츠 생성·검증·컴파일", "Admin", "Content", "P0",
       "C2 DSL 생성기 표면", "dsl", "POST /generate", "POST /validate", "POST /compile"),
    _s("WM-S-049", "학생 결함 신고 접수", "Student", "QA", "P1",
       "RPT-01 — 무인증 append-only", "reports", "POST /defects"),
    # ════════════════════ E 백엔드 엔진 — L1 데이터 기반 ════════════════════
    _e("WM-E-101", "원자 백본 그래프 적재·검색·중복 검수", "Platform", "Knowledge Graph", "P0",
       "B3 선수 그래프 2,683노드·2,210엣지", "l1.atom_graph", pipelines=("atom_graph",)),
    _e("WM-E-102", "구 개념그래프 적재·임베딩·검색", "Platform", "Knowledge Graph", "P1",
       "B4 개념 437 — 원자 축 이전(S0-2·ARCH-13) 후 보조 좌석 — 동일 기능 중복", "l1.concept_graph",
       "api._concept_orchestration", pipelines=("concept_graph",), duplicate_of="WM-E-101"),
    _e("WM-E-103", "개념↔원자 크로스워크 이전", "Platform", "Knowledge Graph", "P1",
       "S0-2 437키 자산 이전", "l1.concept_atom_crosswalk", pipelines=("concept_atom_crosswalk",)),
    _e("WM-E-104", "개념 콘텐츠 4종 적재·해석", "Platform", "Content", "P0",
       "Gate2 ⑤ — 정의·비유·예시·직관", "l1.concept_content",
       pipelines=("concept_content", "concept_content_university")),
    _e("WM-E-105", "교육과정 프레임워크 로더·해석", "Platform", "Curriculum", "P0",
       "B1 — CUR-10", "l1.curriculum"),
    _e("WM-E-106", "성취기준·평가기준 적재·정렬 질의·앵커 레지스트리", "Platform", "Curriculum",
       "P0", "B1·F1 앵커 성취기준 코드셋", "l1.standards",
       pipelines=("ncic", "standards_university")),
    _e("WM-E-107", "오개념 카탈로그·크로스링크 적재·승인 게이트", "Platform", "Pedagogy", "P0",
       "B6 오개념 843 + 게이트 계약 동결", "l1.misconception", pipelines=("misconception",)),
    _e("WM-E-108", "교수법 팩·단원 DSL 컴파일·적재", "Platform", "Pedagogy", "P0",
       "PED-01 팩 — 프롬프트 4계층 입력", "l1.pedagogy"),
    _e("WM-E-109", "문제은행 적재·임베딩·시그니처·페르소나 적합·정답분포", "Platform", "Content",
       "P0", "B7 코퍼스 2,647문", "l1.problem_bank"),
    _e("WM-E-110", "공식 그래프 적재", "Platform", "Knowledge Graph", "P2",
       "S4-06 — 수식 엔티티 적재(MIXED)", "l1.formula_graph", pipelines=("formula_graph",)),
    _e("WM-E-111", "스킬 그래프 적재·해석", "Platform", "Knowledge Graph", "P0",
       "계획서 300 Skill 27건 — 얇음", "l1.skill_graph", pipelines=("skill_graph",)),
    _e("WM-E-112", "풀이 전략 그래프 적재", "Platform", "Pedagogy", "P2",
       "전략 카탈로그(MIXED)", "l1.strategy_graph", pipelines=("strategy_graph",)),
    _e("WM-E-113", "문제 유형 그래프 적재", "Platform", "Content", "P1",
       "S3-27 유형 태깅", "l1.problem_type_graph", pipelines=("problem_type_graph",)),
    _e("WM-E-114", "진단문항·소크라테스 프로브 적재", "Platform", "Assessment", "P1",
       "Phase 3 Slice 3", "l1.atom_probe"),
    _e("WM-E-115", "저작권 게이트웨이·정책 엔진·귀속", "Platform", "Content", "P0",
       "A4 저작권 원장 — LIC-01", "l1.rights"),
    _e("WM-E-116", "개념 시각화·시각 스타일 오버레이", "Platform", "Interaction", "P2",
       "VIZ 축", "l1.concept_visualization", "l1.concept_visual_style"),
    _e("WM-E-117", "임베딩 제공자 셀렉터(bge-m3·OpenAI·fake)", "Platform", "AI Orchestration",
       "P1", "MEMORY 슬105 — 최종 확정 미결", "l1.embedding_provider",
       "l1.embedding_primitives"),
    _e("WM-E-118", "그래프 분석 유틸(ETL 측)", "Platform", "Knowledge Graph", "P2",
       "data_pipeline 분석 — backend 대응 없음", pipelines=("graph_analytics",)),
    # ════════════════════ E — L2 학습자 모델 ════════════════════
    _e("WM-E-201", "BKT 숙달 추정·개념/스킬 숙달 이력 영속", "Student", "Learning Model", "P0",
       "Gate2 ⑧ Mastery 자동 갱신", "l2.bkt", "l2.mastery_tracking",
       "l2.skill_mastery_tracking"),
    _e("WM-E-202", "IRT 문항·능력 동시 추정·θ 시계열", "Student", "Learning Model", "P0",
       "Gate2 ②·⑨ — CAT 기반", "l2.irt", "l2.ability_estimation", "l2.ability_tracking"),
    _e("WM-E-203", "문항 난이도 JMLE 보정 배치", "Admin", "Assessment", "P1",
       "D3 난이도 타당도 KPI 재료", "l2.item_calibration", "l2.calibrate_items", status="Batch"),
    _e("WM-E-204", "개념 진단(BKT↔IRT 교차)·LearnerState 조립", "Student", "Assessment", "P0",
       "Gate2 ②·③ — LearnerState 단일 API는 갭", "l2.concept_diagnosis", "l2.learner_state"),
    _e("WM-E-205", "약·강·선수개념 추천·학습 경로·복습 큐", "Student", "Recommendation", "P0",
       "Gate2 ④·⑨ — ASM-13 강개념(strong_points) 편입", "l2.weak_concept_recommendation",
       "l2.strong_concept_recommendation", "l2.prerequisite_recommendation",
       "l2.learning_path", "l2.review_queue", "l2.axis_exclusions"),
    _e("WM-E-206", "학습 증거 이벤트 적재(attempt·처치·추천 회계)", "Student", "Event", "P0",
       "E3 Event — REC-03·PED-03·EOS-57", "l2.evidence_event_store", "l2.attempt_skill_event",
       "l2.pedagogy_evidence", "l2.recommendation_evidence"),
    _e("WM-E-207", "목표 진행 조회 좌석", "Student", "Learning Model", "P2",
       "수능 D-day 축", "l2.target_progress"),
    _e("WM-E-208", "일별 학습 지표 롤업 writer", "Admin", "Analytics", "P1",
       "COLLAB-03 시계열 3테이블", "l2.learning_metrics_rollup",
       "harness.learning_metrics_rollup_cli"),
    # ════════════════════ E — L3 콘텐츠 생성·검증 (Core) ════════════════════
    _e("WM-E-301", "LLM 라우터(3축 결정·모델 매트릭스·seed 정책)", "Platform", "AI Orchestration",
       "P0", "A5 AI Model Gateway", "l3.router", "l3.models", "l3.escalation_defaults",
       "l3.generation_seed"),
    _e("WM-E-302", "LLM 제공자(Ollama·Anthropic·복합)", "Platform", "AI Orchestration", "P0",
       "A5 — 로컬 우선", "l3.providers"),
    _e("WM-E-303", "생성 파이프라인·Redis 캐시·Langfuse 관측", "Platform", "AI Orchestration",
       "P0", "C1 사슬 골격 — 캐싱·추적 불변 계약", "l3.pipeline", "l3.cache", "l3.interfaces",
       "l3.trace"),
    _e("WM-E-304", "QUALITY 티어 비동기 큐(Celery)", "Platform", "AI Orchestration", "P1",
       "OPS-27 워커 미배포 — 202 영구 pending", "l3.queue"),
    _e("WM-E-305", "데이터 등급 → 국외 반출 게이트", "Platform", "Security", "P0",
       "EOS-59 — AI Hub 반출 무해화(선언 §6-3)", "l3.data_export_policy",
       "l3.data_grade_defaults"),
    _e("WM-E-306", "빌드타임 캐시 사전생성(pre-warm)·시드 검증", "Admin", "AI Orchestration",
       "P1", "S1 비용 게이트 재료", "l3.pregenerate", status="Batch"),
    _e("WM-E-307", "DSL 콘텐츠 생성기(컴파일·검증·복구·변수 엔진)", "Admin", "Content", "P0",
       "C2 DSL — 1건→다건 인스턴스", "l3.dsl"),
    _e("WM-E-308", "교수법 렌더 어댑터 5종·평가 재료 뱅크", "Platform", "Pedagogy", "P0",
       "E1 render-vs-generate", "l3.render"),
    _e("WM-E-309", "교수 콘텐츠 슬롯 파이프라인(생성→예심→검수)", "Admin", "QA", "P0",
       "D1·D2 Publish Gate 계열", "l3.pedagogy.slot_generator", "l3.pedagogy.prescreen",
       "l3.pedagogy.review", "l3.pedagogy.diag_item_projector"),
    _e("WM-E-310", "비유·예시 생성기·결함 검출기", "Platform", "Pedagogy", "P1",
       "C8 — PED-09/24 회수 완료", "l3.pedagogy.analogy_generator",
       "l3.pedagogy.analogy_checker", "l3.pedagogy.analogy_demand",
       "l3.pedagogy.example_generator"),
    _e("WM-E-311", "독립 다관점 LLM 교차검증", "Platform", "QA", "P1",
       "S4-13 잔여 축 검출기", "l3.cross_verify"),
    _e("WM-E-312", "풀이 경로(SolutionPath) 구조·조회 store", "Platform", "Content", "P0",
       "C5 단계별 풀이 — S4-09", "l3.solution_path", "l3.solution_path_store"),
    _e("WM-E-313", "시각화 명세 생성기·품질 채점", "Platform", "Interaction", "P2",
       "05 §5.2 선언적 명세", "l3.visualization", "l3.viz_eval"),
    _e("WM-E-314", "프롬프트 자산 레지스트리", "Platform", "Versioning", "P0",
       "OPS-16 — docs/prompts 단일 진실 원천", "l3.prompt_assets"),
    # ════════════════════ E — L3 (Math Adapter) ════════════════════
    _e("WM-E-351", "동등문제 생성 파이프라인(생성·수용 게이트·정규화·rephrase·감사)", "Admin",
       "Math Engine", "P0", "C1·C3·C4 — 앵커 CU 생산 사슬", "l3.equivalent.generator",
       "l3.equivalent.llm_generator", "l3.equivalent.orchestrator", "l3.equivalent.acceptance",
       "l3.equivalent.skeleton_generator", "l3.equivalent.difficulty",
       "l3.equivalent.canonicalize", "l3.equivalent.rephrase", "l3.equivalent.rephrase_hygiene",
       "l3.equivalent.retag", "l3.equivalent.latex_gate", "l3.equivalent.counterexample_fuzz",
       "l3.equivalent.defect_seeder"),
    _e("WM-E-352", "단원별 스켈레톤 생성기 41종(초·중·고·대)", "Admin", "Math Engine", "P0",
       "B7 코퍼스 30종 생성기 — PB-13", "l3.equivalent.*_skeleton_generator",
       "l3.equivalent.*_mc_generator"),
    _e("WM-E-353", "기호 동치·해집합 보존 판정 primitive", "Platform", "Math Engine", "P0",
       "SymPy 단일 권위 — 불변 계약", "l3.symbolic_equivalence", "l3.solution_set"),
    _e("WM-E-354", "답 검산(Tier1 수치·형태·최종답)", "Student", "Math Engine", "P0",
       "D1·E2 — EOS-28 답 형태", "l3.verify_answer", "l3.verify_answer_form",
       "l3.verify_final_answer"),
    _e("WM-E-355", "단계·풀이 연쇄 검증·검증 등급", "Student", "Math Engine", "P0",
       "C5 인접 단계 동치 — S4-54/55", "l3.verify_step", "l3.verify_solution", "l3.verifier",
       "l3.verification_tier"),
    _e("WM-E-356", "SymPy 불가 영역 검산(유한확률 전수·통계 자료형)", "Platform", "Math Engine",
       "P1", "A3 비대수 앵커 — S4-13/53", "l3.finite_probability", "l3.statistical_claim"),
    _e("WM-E-357", "다중 풀이법 생성(접근법 6종)", "Platform", "Math Engine", "P2",
       "C6 이월 — S4-10 done", "l3.multi_solution"),
    _e("WM-E-358", "표기 커버리지 게이트", "Admin", "Math Engine", "P1",
       "NS-03 — 교육과정 표기 범위", "l3.notation_coverage", status="Batch"),
    _e("WM-E-359", "수식 낭독(AST→한국어)·역파서·학년별 프로파일", "Student", "Math Engine", "P2",
       "접근성 축", "l3.speech", "l3.speech_parse", "l4.speech"),
    # ════════════════════ E — L4 교수학 엔진 ════════════════════
    _e("WM-E-401", "Polya 4단계 코칭 엔진·전이", "Student", "Pedagogy", "P0",
       "절대 원칙 — 모든 학습 경로 Polya 매핑", "l4.polya"),
    _e("WM-E-402", "소크라테스 6카테고리 선택", "Student", "Pedagogy", "P0",
       "E2 코칭 발화 구조", "l4.socratic"),
    _e("WM-E-403", "LTHC 적응(진입점·확장·비계)", "Student", "Pedagogy", "P1",
       "04 교수학 — Low Threshold High Ceiling", "l4.lthc"),
    _e("WM-E-404", "답 미루기 4단계 힌트·정서 안전 톤필터", "Student", "Pedagogy", "P0",
       "C7 힌트 누설 무관용 — PED-35", "l4.hint_deferral", "l4.tone_filter"),
    _e("WM-E-405", "메타인지·보정·선수복습 코칭 결정", "Student", "Pedagogy", "P0",
       "메타인지 코어 — 페르소나 공유 축", "l4.metacognitive_trigger",
       "l4.calibration_coaching", "l4.prerequisite_coaching"),
    _e("WM-E-406", "완료 상태머신·턴 메타·세션 회상", "Student", "Pedagogy", "P0",
       "S3-32 완료 경로 — attempt 생산자", "l4.completion", "l4.turn_meta",
       "l4.session_recall"),
    _e("WM-E-407", "풀이 계산오류 → 검산 코칭 오케스트레이터", "Student", "Pedagogy", "P0",
       "L3→L4 결선(MIXED)", "l4.solution_coaching"),
    _e("WM-E-408", "콘텐츠 공급 경로(DSL 캐시·render-vs-generate)", "Student", "Pedagogy", "P0",
       "E1 학습 공급", "l4.content_supply"),
    _e("WM-E-409", "교수전략 선택기·팩 프롬프트 조립·금지모드 가드", "Student", "Pedagogy", "P0",
       "PED-01/14 — 4계층 프롬프트", "l4.pedagogy.runtime_selector",
       "l4.pedagogy.strategy_registry", "l4.pedagogy.pack_registry",
       "l4.pedagogy.prompt_assembler", "l4.pedagogy.k_type_resolver", "l4.pedagogy.mode_guard",
       flag="pedagogy_pack_prompt_enabled"),
    _e("WM-E-410", "적응 교수법 policy(Thompson sampling·안전제약)", "Student", "Pedagogy", "P1",
       "PED-03 — 승격 게이트 대기", "l4.pedagogy.adaptive"),
    _e("WM-E-411", "오개념 진단·개입·매칭 게이트·distractor 카탈로그", "Student", "Pedagogy", "P0",
       "B6·Gate2 ⑦ 오개념 기록", "l4.misconception.catalog", "l4.misconception.diagnose",
       "l4.misconception.combined", "l4.misconception.models", "l4.misconception.intervene",
       "l4.misconception.match_gate", "l4.misconception.distractor",
       "l4.misconception.validate", "l4.misconception.visualize", "l4.misconception.audit"),
    _e("WM-E-412", "활성 오개념 가설·프로브 선택·웜스타트·증거 저장", "Student", "Pedagogy", "P0",
       "WH-1 §8.4 — 가설 감쇠·ε 규칙", "l4.misconception.hypothesis",
       "l4.misconception.hypothesis_store", "l4.misconception.probe_selection",
       "l4.misconception.probes", "l4.misconception.warmstart",
       "l4.misconception.evidence_store"),
    _e("WM-E-413", "오개념 의미(임베딩) 매칭 + shadow", "Student", "Pedagogy", "P1",
       "slice 104~111 — 방향맹 FP 측정 중", "l4.misconception.semantic",
       "l4.misconception.semantic_eval", "l4.misconception.semantic_shadow_harvest",
       "l4.misconception.shadow", flag="misconception_semantic_mode", status="Shadow"),
    _e("WM-E-414", "오개념 방향 판별 LLM-judge + shadow", "Student", "Pedagogy", "P1",
       "슬108 — coach 미배선", "l4.misconception.judge", "l4.misconception.judge_prompts",
       "l4.misconception.judge_seam", "l4.misconception.judge_shadow_harvest",
       flag="misconception_judge_enabled", status="Shadow"),
    _e("WM-E-415", "오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수·shadow", "Admin", "Pedagogy",
       "P0", "crosswalk_gate_contract.md 코드 동결", "l4.misconception.crosslink_*",
       "l4.misconception.anchor_seat_gap",
       flag="misconception_crosslink_mode", status="Shadow"),
    _e("WM-E-416", "오답 형태 SymPy 매칭(canonical_wrong_form) + shadow", "Student", "Math Engine",
       "P1", "B6 기계판정 채널 — MISC-07", "l4.misconception.wrong_form_match",
       "l4.misconception.wrong_form_shadow_harvest", flag="misconception_wrong_form_mode",
       status="Shadow"),
    _e("WM-E-417", "중간 단계 등가성 shadow 관측·평가", "Student", "Pedagogy", "P1",
       "비노출·비차단 진단", "l4.step_shadow", "l4.step_shadow_eval", "l4.step_shadow_harvest",
       flag="l4_step_shadow_enabled", status="Shadow"),
    _e("WM-E-418", "학습 장면(LearningScene) DSL·생성·시각화 정책", "Student", "Interaction", "P2",
       "S2·S3 장면 명세", "l4.learning_scene", "l4.scene_generation", "l4.visualization_policy"),
    _e("WM-E-419", "SubjectAdapter 계약 + 수학 구현", "Platform", "AI Orchestration", "P0",
       "EOS-66 — Core/Adapter 경계의 유일한 다리", "l4.subject_adapter_math",
       "schema.subject_adapter"),
    _e("WM-E-420", "L4 공용 모델·인터페이스", "Platform", "Pedagogy", "P0",
       "Pydantic·Protocol", "l4.models"),
    # ════════════════════ E — L5·L6 ════════════════════
    _e("WM-E-501", "OCR 파이프라인(검출→라우팅→인식→조립·검증)", "Student", "Math Engine", "P2",
       "PaddleOCR+Qwen3-VL — 라이브 정확도 미검증", "l5.ocr", "api.ocr_handoff",
       flag="ocr_enabled"),
    _e("WM-E-601", "L6 모드 게이팅 로직 5종(재수·학교진도·사고력·메타인지·영재)", "Student",
       "Application Mode", "P2",
       "L6 — 수학 신호 0(Physics 무수정 구역) · 수능 모드는 WM-E-602", "l6.gifted",
       "l6.metacognition", "l6.retake", "l6.school_progress", "l6.thinking"),
    _e("WM-E-602", "수능 모드 게이팅·적응 추천(게이팅×IRT CAT)", "Student", "Recommendation", "P1",
       "next-problem이 소비 — 공용 게이팅 헬퍼 포함", "l6.suneung", "l6._shared"),
    _e("WM-E-603", "평가 청사진 테스트셋 조립", "Student", "Assessment", "P0",
       "ASM-04 — assemble 표면의 엔진", "l6.blueprint"),
    # ════════════════════ E — WH-S·WH-1 하네스(런타임) ════════════════════
    _e("WM-E-701", "WH-S 솔버 하네스(루프·판정·저장소·코퍼스 replay)", "Platform", "Math Engine",
       "P1", "03b 설계 — 솔버 자기진화 플랫폼(PRM 라벨 공급) — 12월 폐쇄루프 밖·장기 연구",
       "whs.harness", "whs.verdict", "whs.baseline", "whs.node_store", "whs.lemma_store",
       "whs.dead_end_store", "whs.solution_bank", "whs.corpus_replay", horizon="P3"),
    _e("WM-E-702", "WH-S 자기진화(PRM·SFT 학습셋 export)", "Admin", "Math Engine", "P2",
       "설계 §5 — 2027 학습 파이프라인(PRM·SFT) — 장기 연구", "whs.prm_builder",
       "whs.prm_builder_export_cli", "whs.self_evolution", "whs.self_evolution_export_cli",
       status="Batch", horizon="P3"),
    _e("WM-E-703", "bank_solution → SolutionPath 승격 writer", "Admin", "Content", "P0",
       "S4-09 D1", "whs.path_promotion", status="Batch"),
    _e("WM-E-704", "WH-1 튜터링 하네스(턴 루프·LLM 정책·프로즈·프로브 공급)", "Student",
       "Pedagogy", "P0", "04a — 학생 대면 발화 primary", "harness.wh1_loop",
       "harness.wh1_llm_policy", "harness.wh1_primary", "harness.wh1_session",
       "harness.wh1_prose", "harness.wh1_probe_supply", flag="wh1_primary_enabled"),
    _e("WM-E-705", "WH-1 shadow 관측·수확·2단계 종료 게이트", "Platform", "QA", "P1",
       "S1-b·S1-15 shadow 축적", "harness.wh1_shadow", "harness.wh1_shadow_harvest",
       "harness.agreement_gate", "harness.agreement_gate_cli",
       "harness.agreement_gate_semantic", flag="wh1_harness_shadow_enabled", status="Shadow"),
    _e("WM-E-706", "성장 증거 대리지표 7종·노출 계약·베이스라인", "Student", "Pedagogy", "P1",
       "PED-06/08 — 반게임화 노출 계약", "harness.wh1_evaluation",
       "harness.growth_evidence_exposure", "harness.surrogate_baseline_report",
       "harness.pilot_kpi_baseline"),
    # ════════════════════ E — 계약·영속·횡단 인프라 ════════════════════
    _e("WM-E-801", "Pydantic 계약 스키마(문항·활동·이벤트·권리 등 40종)", "Platform",
       "Versioning", "P0", "A2 Subject-neutral Contract — S1-16 후에도 MIXED", "schema",
       "-schema.subject_adapter"),
    _e("WM-E-802", "ORM 모델 54종·세션·스키마 버전·alembic", "Platform", "Versioning", "P0",
       "W2 되돌릴 수 없는 스키마 — 91 리비전", "db"),
    _e("WM-E-803", "인증·인가·암호화·레이트리밋·동시성 배관", "Platform", "Security", "P0",
       "JWT·디바이스 서명·봉투 암호화 — 불변 계약", "security", "api._auth", "api._crypto",
       "api._rate_limit", "api._concurrency", "api._degradation", "api._query_filters"),
    _e("WM-E-804", "OAuth 제공자 구현(카카오·네이버 httpx)", "Platform", "Identity", "P0",
       "OAuth-a2 — auth callback이 app.state DI(OAUTH_PROVIDERS_KEY)로 호출 → DI 다리로 도달",
       "api.oauth_providers"),
    _e("WM-E-805", "동의 절차(14세 미만·동의 부여)", "Parent", "Security", "P0",
       "법령 유래 절차 — 기계 대체 금지", "consent", "consent_grant"),
    _e("WM-E-806", "디바이스 저장소·서명 실패 metric", "Platform", "Security", "P1",
       "device_store_mode 기본 none", "api._device_store", "api._device_metrics"),
    _e("WM-E-807", "앱 조립·합성 루트·설정·app.state 배관", "Platform", "Operations", "P0",
       "composition = 경계의 유일한 배선 지점(EOS-69)", "composition", "config",
       "api._l3_state", "api._ocr_state", "api._misconception_state",
       "api._growth_evidence_state", "api._segmentation_state",
       # EOS-89: 과목 능력 5종의 app.state 등록 주소·조회(등록 형태의 배관). `_l3_state`와
       # 같은 성격이라 같은 좌석에 귀속한다 — 판정 로직 0, 키·getter만.
       "api._subject_capability_state",
       # MOB-18(PB-04): L6 6모드 도달 카운터의 app.state 등록 주소·조회. 공개면이
       # `_growth_evidence_state`와 동형(KEY 상수 + Snapshot + Counters + set/get)이고
       # 교육적 판정 로직이 0이라 같은 배관 좌석에 귀속한다.
       "api._l6_mode_reach_state"),
    _e("WM-E-808", "한국어 조사 유틸", "Platform", "Content", "P1",
       "EOS-69 B분류 해소처 — 과목 무관", "lang"),
    _e("WM-E-809", "데모 인증(시연 전용 가짜 OAuth provider)", "Admin", "Identity", "P1",
       "S1 탈출 게이트 ① 실기기 시연 인에이블먼트 — 기본 OFF", "api.demo_auth",
       flag="demo_auth_enabled"),
    # ════════════════════ O 운영자 도구 — privacy·ops·harness ════════════════════
    _o("WM-O-901", "개인정보 삭제권·이동권·PEP·감사 writer", "Student", "Security", "P0",
       "R11·SEC-09 — me 라우터가 소비", "privacy.erasure", "privacy.export",
       "privacy.authorize", "privacy.audit", status="Production"),
    _o("WM-O-902", "PII 보존기한 파기·대화·학생답안 봉투 암호화 백필", "Admin", "Security", "P0",
       "security_privacy.md 보존·파기 정본", "privacy.retention", "privacy.retention_purge_cli",
       "privacy.dialogue_content_backfill",
       # SEC-31: 학생 답안/풀이 3테이블(problem_attempt·answer_submission·
       # student_solution_step) 봉투 암호화 백필 — dialogue_content_backfill과 동일 성격
       # (평문→암호화 전환 ops CLI)이라 같은 좌석에 귀속한다.
       "privacy.student_work_backfill"),
    _o("WM-O-903", "서비스 헬스 딥체크·프리플라이트·DB 도달성 진단·로그 스크러버", "Admin",
       "Operations", "P0", "OPS-01·SEC-05·SEC-11·OPS-72", "ops.service_health",
       "ops.live_preflight", "ops.dialogue_encryption_preflight", "ops.log_scrubber",
       "ops.db_host_reachability", status="Production"),
    _o("WM-O-904", "LLM 비용 프로브·비용 리포트", "Admin", "Analytics", "P0",
       "단위비용 KPI(≤250원) 판독기", "ops.cost_probe", "ops.cost_report"),
    _o("WM-O-905", "12월 검증 스코어카드·QA 혼동행렬·HIT/CU 계측", "Admin", "QA", "P0",
       "EOS-54/60/61 — Go/No-Go 판정기", "ops.validation_scorecard",
       "ops.qa_confusion_matrix", "ops.hit_cu_metrics",
       # OPS-56: EOS-51 §6 "기술 KPI 6종" 주간 cron 집계기 — hit_cu_metrics.aggregate()를
       # 재사용하는 소비자라 같은 좌석(같은 Go/No-Go 계측 묶음)에 귀속한다.
       "ops.weekly_metrics_report"),
    _o("WM-O-906", "콘텐츠 출처·라이선스 감사 게이트·사이드카", "Admin", "Content", "P0",
       "ARCH-20·PB-11 — 저작권 레일 · EOS-97 리콜(genlog 사이드카 선별·처분)",
       "ops.provenance_audit", "ops.corpus_provenance_sidecar", "ops.generation_recall"),
    _o("WM-O-907", "선언≠배선 감사·추천/슬롯 도달 리포트", "Admin", "QA", "P1",
       "OPS-22·REC-01/06·PED-06 — '작동한 비율'", "ops.declared_unwired_audit",
       "ops.recommendation_reach_report", "ops.repeat_recommendation_report",
       "ops.pedagogy_content_slot_reach_report"),
    _o("WM-O-908", "운영자 계정 부트스트랩·역할 좌석·shadow 합성 트래픽", "Admin", "Operations",
       "P1", "ADMIN-01/11", "ops.account_bootstrap_cli", "ops.role_grant_cli",
       "ops.wh1_shadow_probe"),
    _o("WM-O-909", "동등문제 코퍼스 축적·후처리 배치(36 단원 배치 포함)", "Admin", "Content", "P0",
       "C1·C3 — 앵커 CU 물량", "harness.problem_corpus_*", "harness.*_batch",
       "-harness.concept_content_review_batch",
       "harness.problem_type_backfill", "harness.problem_type_mapping",
       "harness.rephrased_corpus_hygiene"),
    _o("WM-O-910", "검수 워크플로(HIT 타이머·검수 세션·워크리스트·표본 패키지)", "Admin", "QA",
       "P0", "EOS-54/78 — HIT 중앙값 KPI 생산자", "harness.review_session",
       "harness.review_timer", "harness.needs_review_worklist",
       "harness.reviewer_sample_package", "harness.concept_content_review_apply",
       "harness.concept_content_review_batch", "harness.concept_content_audit",
       # MP-05 — 회차 앞머리 카나리 구간을 검수 큐 JSONL로 잘라내는 CLI. 검수 워크플로의
       # *입력 생산자*라 여기 귀속한다(산출을 먹는 쪽이 harness.review_session이다).
       "harness.canary_slice"),
    _o("WM-O-911", "골든 벤치마크 승격·경로 게이트·앵커 회차 대장", "Admin", "QA", "P0",
       "EOS-60/64 — 판정기의 FN율", "harness.golden_benchmark",
       "harness.golden_promotion_gate", "harness.anchor_round_ledger"),
    _o("WM-O-912", "QA 파이프라인·강등전 게이트(Wilson·결함주입·금칙어)", "Admin", "QA", "P0",
       "초인간 검증 기준 v1 — 기계 게이트 승격 절차", "harness.qa_pipeline", "harness.wilson",
       "harness.*_eval", "harness.*_battle", "harness.corpus_reverify",
       "harness.problem_duplication_audit", "harness.pedagogical_rubric",
       "harness.prompt_asset_audit", "harness.generation_seed_replay_probe",
       "harness.batch_safety"),
    _o("WM-O-913", "커버리지·도달률 관측 리포트 가족", "Admin", "Analytics", "P1",
       "OPS-19 — 리포트 11개 중 러너 배선은 별도", "harness.*_report",
       "-harness.surrogate_baseline_report",
       "harness.problem_bank_coverage", "harness.objective_coverage",
       # OPS-68 — `*_report` 와일드카드에 안 걸리는 짝(표본 *생성*기라 이름이 _probe다).
       # 리포트가 볼 표본을 만드는 도구이므로 관측 가족에 함께 귀속한다.
       "harness.attempt_skill_reach_probe",
       "harness.concept_assessment_index"),
    _o("WM-O-914", "데이터 무결성 게이트(orphan·dangling·duplicate 6종)", "Admin", "QA", "P0",
       "OPS-55 — 느슨참조 드리프트 감사(v_integrity_violations) · 주간 지표 #4 산출원",
       "ops.integrity_violations_gate"),
    # ════════════════════ C 클라이언트 — Flutter·Web ════════════════════
    _c("WM-C-001", "로그인·계정 보안 화면·토큰 배관", "Student", "Client UX", "P0",
       "폐쇄루프 진입 — 클라 절반", "mobile/lib/features/auth", "mobile/lib/core"),
    _c("WM-C-002", "온보딩(학년·학교유형·목표)", "Student", "Client UX", "P0",
       "Gate2 ① — EOS-82 클라 축", "mobile/lib/features/onboarding"),
    _c("WM-C-003", "홈·탭 셸·라우팅", "Student", "Client UX", "P0",
       "MOB-08 indexedStack — 앱 진입점·라우팅(없으면 어떤 화면에도 못 간다)",
       "mobile/lib/features/home", "mobile/lib/app.dart", "mobile/lib/main.dart",
       "mobile/lib/theme", loop_seed=True),
    _c("WM-C-004", "코치 채팅(턴·단계 패널·완료 신호)", "Student", "Client UX", "P0",
       "E2 — MOB-20 완료 신호 3필드", "mobile/lib/features/chat/application",
       "mobile/lib/features/chat/data/coach_api.dart",
       "mobile/lib/features/chat/data/coach_models.dart",
       "mobile/lib/features/chat/data/interaction_logger.dart",
       "mobile/lib/features/chat/domain", "mobile/lib/features/chat/presentation/chat_screen.dart",
       "mobile/lib/features/chat/presentation/coach_emphasis_text.dart",
       "mobile/lib/features/chat/presentation/coach_signal_card.dart",
       "mobile/lib/features/verify"),
    _c("WM-C-005", "MathLive 수식 입력(WebView 임베드)", "Student", "Client UX", "P0",
       "E1 학생 입력 표준(28_mathlive_input.md) — 코치 턴 입력 표면·API 호출 0이라 씨앗 선언",
       "mobile/lib/features/chat/presentation/mathlive_input_screen.dart",
       "mobile/lib/features/chat/presentation/mathlive_input_webview.dart",
       "mobile/lib/features/chat/presentation/webview_fallback.dart",
       "mobile/assets/mathlive_input", loop_seed=True),
    _c("WM-C-006", "학습 장면·풀이 경로 렌더러", "Student", "Client UX", "P2",
       "scene 계약 테스트 동결", "mobile/lib/features/chat/presentation/scene_renderer.dart",
       "mobile/lib/features/chat/data/scene_api.dart",
       "mobile/lib/features/chat/data/scene_models.dart",
       "mobile/lib/features/chat/data/solution_path_api.dart",
       "mobile/lib/features/chat/data/solution_path_models.dart"),
    _c("WM-C-007", "그래핑 계산기(React WebView 임베드)", "Student", "Client UX", "P2",
       "국소 임베드 2 비상구 — 수학 판정 금지 거버넌스",
       "mobile/lib/features/chat/presentation/graphing_calculator_webview.dart",
       "mobile/assets/graphing_calculator", "web/graphing-calculator"),
    _c("WM-C-008", "진단·문제 풀기 화면", "Student", "Client UX", "P0",
       "Gate2 ② 진단 — diagnosis_controller", "mobile/lib/features/problems"),
    _c("WM-C-009", "손글씨 촬영·OCR 캡처", "Student", "Client UX", "P2",
       "OCR 축 이월 후보와 동행", "mobile/lib/features/ocr", status="Flag-off"),
    _c("WM-C-010", "나(프로필)·성장 증거 탭", "Student", "Client UX", "P1",
       "PED-08 노출 계약 소비", "mobile/lib/features/profile"),
    _c("WM-C-011", "탐구(Explore) 탭", "Student", "Client UX", "P2",
       "MOB-08 — 자리표시 수준", "mobile/lib/features/explore"),
    _c("WM-C-012", "결함 신고 버튼", "Student", "Client UX", "P1",
       "RPT-01 클라 절반", "mobile/lib/features/reports"),
)
# fmt: on


# ──────────────────────────────────────────────────────────────────────
# 측정
# ──────────────────────────────────────────────────────────────────────
def _load_script(path: pathlib.Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"스크립트 로드 불가: {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _backend_modules() -> list[str]:
    out = []
    for p in sorted(BACKEND.rglob("*.py")):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        out.append(".".join(p.relative_to(BACKEND).with_suffix("").parts))
    return out


def _module_path(mod: str) -> pathlib.Path | None:
    cand = BACKEND / (mod.replace(".", "/") + ".py")
    if cand.is_file():
        return cand
    pkg = BACKEND / mod.replace(".", "/")
    return pkg if pkg.is_dir() else None


def _resolve_modules(entry: str, universe: list[str]) -> list[str]:
    """카탈로그 항목 → 실제 모듈 목록. 파일·패키지·fnmatch 세 형태를 받는다."""
    if "*" in entry:
        return [m for m in universe if fnmatch.fnmatchcase(m, entry)]
    p = _module_path(entry)
    if p is None:
        return []
    if p.is_file():
        return [entry]
    return [m for m in universe if m == entry or m.startswith(entry + ".")]


_INIT_SYMBOLS: dict[str, dict[str, str]] = {}


def _init_symbol_map(pkg: str) -> dict[str, str]:
    """패키지 `__init__`이 재수출하는 심볼 → 정의 모듈.

    `from whymath_backend.l4 import PolyaCoach`를 `l4.polya.engine`으로 푼다.
    """
    if pkg in _INIT_SYMBOLS:
        return _INIT_SYMBOLS[pkg]
    out: dict[str, str] = {}
    init = BACKEND / pkg.replace(".", "/") / "__init__.py"
    if init.is_file():
        tree = ast.parse(init.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level and not node.module.startswith("whymath_backend"):
                    base = f"{pkg}.{node.module}"  # 상대 import(`from .polya.engine import …`)
                elif node.module.startswith("whymath_backend"):
                    base = node.module[len("whymath_backend") :].lstrip(".")
                else:
                    continue
                for a in node.names:
                    deeper = f"{base}.{a.name}"
                    out[a.asname or a.name] = (
                        deeper if (_module_path(deeper) or pathlib.Path()).is_file() else base
                    )
    _INIT_SYMBOLS[pkg] = out
    return out


def _import_alias_map(tree: ast.AST) -> dict[str, str]:
    """import 별칭 → 내부 모듈 점 경로.

    `from l2 import bkt`는 파일 l2.bkt로, `from l4 import PolyaCoach`는 `l4/__init__`의 재수출을
    따라 l4.polya.engine으로 해석한다. 둘 다 아니면 패키지 자신(`__init__`)에 귀속한다.
    """
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith("whymath_backend"):
                continue
            base = node.module[len("whymath_backend") :].lstrip(".")
            for a in node.names:
                deeper = f"{base}.{a.name}" if base else a.name
                if (_module_path(deeper) or pathlib.Path()).is_file():
                    target = deeper
                else:
                    target = _init_symbol_map(base).get(a.name, base) if base else a.name
                alias[a.asname or a.name] = target
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("whymath_backend."):
                    alias[a.asname or a.name] = a.name[len("whymath_backend.") :]
    return alias


@dataclass
class Endpoint:
    method: str
    path: str
    func: str
    refs: set[str]  # 본문 1-hop 참조 — 6축 매트릭스(기능 단위 결합) 재료
    contract: bool = True  # response_model 선언 또는 204(본문 없음) — §3.4 'API 계약' 신호
    deep_refs: set[str] = field(
        default_factory=set
    )  # 모듈 내 헬퍼 사슬 포함 — 폐쇄루프 도달성 재료


def _names_in(node: ast.AST) -> set[str]:
    """노드 안에서 참조되는 이름(속성 접근은 루트 이름)."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            root: ast.expr = n
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
    return names


_DI_MAP: dict[str, set[str]] = {}


def _app_state_di_map() -> dict[str, set[str]]:
    """app.py가 `app.state.__setattr__(KEY, expr)`로 배선한 값 → KEY 상수명 → expr이 참조하는 모듈.

    엔드포인트는 `getattr(request.app.state, KEY)`로 부품을 꺼내 쓰므로 정적 import 그래프에는
    안 보인다(OAuth provider·LLM provider·캐시·큐·트레이스). KEY 상수명은 저장소 전체에서
    고유하므로 이름으로 잇는다 — 엔드포인트 deep_refs에 KEY가 나타나면 배선 모듈을 의존으로 더한다.
    """
    if _DI_MAP:
        return _DI_MAP
    tree = ast.parse((BACKEND / "app.py").read_text(encoding="utf-8"))
    alias = _import_alias_map(tree)
    # app.py가 KEY를 `as _X`로 들여왔으면 원 이름(_l3_state·auth가 쓰는 이름)도 같은 키로 잇는다
    original_name: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.asname:
                    original_name[a.asname] = a.name
    local_syms: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    local_syms.setdefault(t.id, set()).update(_names_in(node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            local_syms.setdefault(node.target.id, set()).update(_names_in(node.value))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_syms.setdefault(node.name, set()).update(_names_in(node))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "__setattr__" or ast.unparse(node.func.value) != "app.state":
            continue
        if len(node.args) != 2 or not isinstance(node.args[0], ast.Name):
            continue
        names = set(_names_in(node.args[1]))
        frontier = [x for x in names if x in local_syms]
        while frontier:
            sym = frontier.pop()
            for extra in local_syms[sym] - names:
                names.add(extra)
                if extra in local_syms:
                    frontier.append(extra)
        mods = {alias[x] for x in names if x in alias and alias[x] not in ("config", "app")}
        key = node.args[0].id
        _DI_MAP.setdefault(key, set()).update(mods)
        if key in original_name:
            _DI_MAP.setdefault(original_name[key], set()).update(mods)
    return _DI_MAP


_MODULE_KEY_REFS: dict[str, set[str]] = {}


def _module_di_keys(mod: str) -> set[str]:
    """api 헬퍼 모듈(`_l3_state` 등)이 본문에서 참조하는 DI KEY 상수명.

    엔드포인트가 헬퍼 경유로 `getattr(request.app.state, KEY)`를 부르는 경우를 잇는다.
    """
    if mod not in _MODULE_KEY_REFS:
        path = _module_path(mod)
        names: set[str] = set()
        if path is not None and path.is_file():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = _names_in(tree) & set(_app_state_di_map())
        _MODULE_KEY_REFS[mod] = names
    return _MODULE_KEY_REFS[mod]


def _endpoints(router_mod: str) -> list[Endpoint]:
    path = BACKEND / ("app.py" if router_mod == "app" else f"api/{router_mod}.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    alias = _import_alias_map(tree)
    target_obj = "app" if router_mod == "app" else "router"
    # 모듈 수준 심볼(헬퍼 함수·클래스·상수) → 그 정의가 참조하는 이름. 엔드포인트가 `_run_coach()`를
    # 부르면 그 헬퍼가 import한 모듈도 엔드포인트의 의존이다(1-hop 본문만 보면 놓친다).
    local_syms: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            targets = [node.name]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if targets:
            names_in = _names_in(node)
            for t in targets:
                local_syms.setdefault(t, set()).update(names_in)
    out: list[Endpoint] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
                continue
            if d.func.attr not in ("get", "post", "put", "patch", "delete"):
                continue
            if not (isinstance(d.func.value, ast.Name) and d.func.value.id == target_obj):
                continue
            raw = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else ""
            body_names = set(_names_in(node))
            names = set(body_names)
            frontier = [x for x in names if x in local_syms]
            while frontier:  # 모듈 내 헬퍼 호출 사슬을 따라 이름을 모은다(visited = names)
                sym = frontier.pop()
                for extra in local_syms[sym] - names:
                    names.add(extra)
                    if extra in local_syms:
                        frontier.append(extra)
            refs = {alias[x] for x in body_names if x in alias}
            deep_refs = {alias[x] for x in names if x in alias}
            di = _app_state_di_map()
            keys = names & set(di)  # app.state DI 다리 — KEY 상수 참조 = 배선 모듈 의존
            for helper in [m for m in deep_refs if m.startswith("api.")]:
                keys |= _module_di_keys(helper)  # 헬퍼(`api._l3_state`) 경유 참조
            for key in keys:
                deep_refs |= di[key]
            kw = {k.arg: k.value for k in d.keywords if k.arg}
            no_body = "status_code" in kw and "204" in ast.unparse(kw["status_code"])
            contract = "response_model" in kw or no_body
            out.append(
                Endpoint(d.func.attr.upper(), str(raw) or "/", node.name, refs, contract, deep_refs)
            )
    return out


def _router_prefix(router_mod: str) -> str:
    if router_mod == "app":
        return ""
    src = (BACKEND / f"api/{router_mod}.py").read_text(encoding="utf-8")
    m = re.search(r'APIRouter\(\s*prefix="([^"]*)"', src)
    return m.group(1) if m else ""


def _config_defaults() -> dict[str, str]:
    src = (BACKEND / "config.py").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(
        r"^\s+([a-z0-9_]+)\s*:\s*[^=\n]+?=\s*Field\(\s*\n?\s*(?:default=)?([^,\n]+)", src, re.M
    ):
        out[m.group(1)] = m.group(2).strip()
    return out


def _flag_is_on(default: str) -> bool:
    return default.strip().strip('"').strip("'").lower() not in {"false", "off", "none", ""}


@dataclass
class TestIndex:
    """테스트 파일 → (import한 내부 모듈 집합, test fn 수). 한 번 만들어 전 행이 공유한다."""

    py: list[tuple[pathlib.Path, str, set[str], int]] = field(default_factory=list)
    dart: list[tuple[pathlib.Path, str, int]] = field(default_factory=list)
    js: list[tuple[pathlib.Path, str, int]] = field(default_factory=list)

    @classmethod
    def build(cls) -> TestIndex:
        idx = cls()
        for p in sorted(TESTS.rglob("test_*.py")):
            text = p.read_text(encoding="utf-8")
            try:
                mods = set(_import_alias_map(ast.parse(text)).values())
            except SyntaxError:
                mods = set()
            idx.py.append((p, text, mods, len(_PY_TESTFN.findall(text))))
        for p in sorted((MOBILE / "test").rglob("*_test.dart")):
            text = p.read_text(encoding="utf-8")
            idx.dart.append((p, text, len(_DART_TEST.findall(text))))
        for p in sorted((WEB_CALC / "test").glob("*.test.js*")):
            text = p.read_text(encoding="utf-8")
            idx.js.append((p, text, len(_JS_TEST.findall(text))))
        return idx

    def fns_importing(self, modules: set[str]) -> tuple[int, int]:
        """자기 모듈을 직접 import했거나, *직계 부모 패키지*를 import한 테스트를 센다.

        `from whymath_backend.l1.concept_visualization import (…)`처럼 패키지 `__init__`
        재수출 경유 import는 모듈 파일명이 나타나지 않는다 — 부모 1단계까지만 허용한다
        (`l3` 같은 최상위 패키지 import가 하위 전 행에 계상되는 과대평가를 막는다).
        """
        parents = {m.rpartition(".")[0] for m in modules if "." in m}
        hits = [(p, n) for p, _, mods, n in self.py if (mods & modules) or (mods & parents)]
        return len(hits), sum(n for _, n in hits)

    def fns_under(self, directory: pathlib.Path) -> tuple[int, int]:
        hits = [(p, n) for p, _, _, n in self.py if directory in p.parents]
        return len(hits), sum(n for _, n in hits)

    def fns_matching_routes(self, patterns: list[re.Pattern[str]]) -> tuple[int, int]:
        hits = [(p, n) for p, text, _, n in self.py if any(rx.search(text) for rx in patterns)]
        return len(hits), sum(n for _, n in hits)

    def dart_fns(self, fragments: list[str]) -> tuple[int, int]:
        hits = [(p, n) for p, text, n in self.dart if any(f in text for f in fragments)]
        return len(hits), sum(n for _, n in hits)

    def js_fns(self) -> tuple[int, int]:
        return len(self.js), sum(n for _, _, n in self.js)


@dataclass
class Row:
    spec: Spec
    location: str
    own_modules: list[str]
    loc: int
    endpoints: int
    write_endpoints: int
    closure: list[str]
    adapter_deps: list[str]
    mixed_deps: list[str]
    db_models: list[str]
    coupling_count: int
    test_files: int
    test_functions: int
    mutations: int
    ownership: str
    status: str
    flag_default: str
    scores: dict[str, int] = field(default_factory=dict)
    total: int = 0
    matrix_action: str = ""
    migration_action: str = ""
    migration_risk: str = ""
    coupling: str = ""
    tests: str = ""
    # §3.4 기준 재료 — 측정값
    fan_in: int = 0  # 자기 모듈을 import하는 타 백엔드 모듈 수(API 명확성 대리)
    has_cli: bool = False  # argparse/main 진입점 보유(운영자 도구의 계약)
    contract_gaps: int = 0  # response_model도 204도 없는 엔드포인트 수
    mixed_own_schema: int = 0  # 자기 모듈 중 MIXED 판정 schema.* 수(모델 충돌 대리)
    criteria: dict[str, bool] = field(default_factory=dict)
    keep_met: int = 0
    replace_signals: int = 0
    criteria_action: str = ""
    action_basis: str = ""
    # 폐쇄루프 도달성 — P0 판정 재료
    loop_hits: dict[str, bool] = field(default_factory=dict)  # student/production/invariant/seed
    client_seed_routes: int = 0  # C: 소스에 폐쇄루프 씨앗 경로 리터럴이 몇 개 나오나
    release_priority: str = ""  # 파생(기계) — 카탈로그 priority는 선행 제안으로 남는다
    priority_basis: str = ""


def _band(value: int, cuts: tuple[int, int, int]) -> int:
    return 0 if value <= cuts[0] else 1 if value <= cuts[1] else 2 if value <= cuts[2] else 3


def _ownership_from_own(verdicts: set[str]) -> str:
    v = {x for x in verdicts if x != "INFRA"}
    if not v:
        return "INFRA"
    if "MIXED" in v or ({"CORE", "ADAPTER"} <= v):
        return "MIXED"
    if v == {"ADAPTER"}:
        return "ADAPTER"
    return "CORE"


def _score(row: Row, v1: Any) -> None:
    own = row.ownership
    if own in ("ADAPTER", "CLIENT"):
        a = 0
    elif own == "MIXED":
        a = 3
    elif len(row.adapter_deps) >= 2:
        a = 3
    elif len(row.adapter_deps) == 1:
        a = 3 if row.mixed_deps else 2
    else:
        a = 1 if row.mixed_deps else 0
    d_cuts = v1.D_TESTFN
    if row.test_functions >= d_cuts[0]:
        d = 0
    elif row.test_functions >= d_cuts[1]:
        d = 1
    elif row.test_functions >= d_cuts[2]:
        d = 2
    else:
        d = 3
    e_src = row.write_endpoints if row.spec.plane == "S" else row.mutations
    row.scores = {
        "A_subject": a,
        "B_db": _band(len(row.db_models), v1.B_DBMODEL),
        "C_coupling": _band(row.coupling_count, v1.C_IMPORTS),
        "D_tests": d,
        "E_state": _band(e_src, v1.E_WRITES),
        "F_data": _band(len(row.db_models), v1.F_TABLES),
    }
    row.total = sum(row.scores.values())
    for upper, verdict in v1.BANDS:
        if row.total <= upper:
            row.matrix_action = verdict
            break
    _apply_criteria_34(row)
    if row.total >= 10 or own == "MIXED":
        row.migration_risk = "High"
    elif row.total >= 5:
        row.migration_risk = "Med"
    else:
        row.migration_risk = "Low"
    row.coupling = ("Low", "Low", "Med", "High")[row.scores["C_coupling"]]
    row.tests = ("Full", "Partial", "Partial", "None")[row.scores["D_tests"]]


def _derive_priority(
    row: Row,
    student: set[str],
    production: set[str],
    seed_routes: set[tuple[str, str]],
) -> None:
    """P0 = "없으면 12/31 폐쇄루프가 깨지는가"에 YES — 도달성·씨앗·불변 계약 셋 중 하나.

    P3 = 카탈로그 `horizon` 선언(장기 연구/플랫폼) · P1/P2 = 선행 제안(카탈로그 `priority`)을
    승계하되 **선행 P0인데 기계가 도달하지 못한 행은 P1로 강등**한다(우회 가능 = P1의 정의).
    """
    spec = row.spec
    own = set(row.own_modules)
    scope = own | set(row.closure) if spec.plane == "S" else own
    loop_tables = {m for m in student | production if m.startswith("db.models.")}
    hits = {
        "seed_route": any((spec.router, r) in seed_routes for r in spec.routes)
        or row.client_seed_routes > 0,
        "seed_declared": spec.loop_seed,
        "student_loop": bool(own & student) if spec.plane != "S" else False,
        "production_loop": bool(own & production) if spec.plane != "S" else False,
        # L1 적재기가 루프가 읽는 테이블을 채운다 — 데이터가 없으면 루프는 빈 화면이다.
        # (2패스: P0 writer가 없는 루프 테이블의 유일 생산자도 켜진다 — _promote_sole_suppliers)
        "data_supplier": spec.plane != "S"
        and any(m.startswith("l1.") for m in own)
        and bool(set(row.db_models) & loop_tables),
        "invariant": any(m.startswith(INVARIANT_MODULE_PREFIXES) for m in scope)
        or any(m.startswith(INVARIANT_AUTH_MODULES) for m in own),
    }
    row.loop_hits = hits
    _finalize_priority(row)


_REACH_ONLY = {"student_loop", "production_loop", "data_supplier"}


def _finalize_priority(row: Row) -> None:
    spec = row.spec
    reasons = [k for k, v in row.loop_hits.items() if v]
    reached_only = set(reasons) <= _REACH_ONLY
    if reasons and reached_only and row.status in ("Flag-off", "Shadow"):
        row.release_priority = "P1"
        row.priority_basis = f"정적 도달({', '.join(reasons)})했으나 {row.status} — 우회 가능"
    elif reasons:
        row.release_priority, row.priority_basis = "P0", "폐쇄루프: " + ", ".join(reasons)
    elif spec.horizon == "P3":
        row.release_priority, row.priority_basis = "P3", "장기 연구/플랫폼(horizon 선언)"
    elif spec.priority == "P0":
        row.release_priority = "P1"
        row.priority_basis = "선행 P0 → 강등: 폐쇄루프 미도달(우회 가능)"
    else:
        row.release_priority = spec.priority
        row.priority_basis = f"선행 제안 승계({spec.priority}) — 폐쇄루프 미도달"


def _promote_sole_suppliers(rows: list[Row], loop_tables: set[str]) -> set[str]:
    """2패스 — 루프가 읽는 테이블에 P0 writer가 하나도 없으면, 그 테이블의 writer를 P0로 올린다.

    "없으면 루프가 깨지는가"의 데이터 축: 읽기 표면이 P0인데 쓰는 쪽이 전부 P1이면 12월 앵커 콘텐츠
    (새 문항·새 풀이)가 그 테이블에 실리지 않는다. 제외: Flag-off/Shadow(꺼진 채널의 writer),
    horizon P3, 선행 제안 P2(전환 선언 crosswalk의 *이월* 선언 — 예: 다중 풀이 C6). 남는 테이블은
    dashboard `loop_tables_without_p0_writer`로 드러낸다(0이 아니면 판정 후보).
    """
    writers: dict[str, list[Row]] = {t: [] for t in loop_tables}
    for r in rows:
        if r.spec.plane == "S" or r.mutations == 0:
            continue
        for t in set(r.db_models) & loop_tables:
            writers[t].append(r)
    unresolved: set[str] = set()
    for table, ws in writers.items():
        if not ws or any(w.release_priority == "P0" for w in ws):
            continue
        promoted = False
        for w in ws:
            if (
                w.status in ("Flag-off", "Shadow")
                or w.spec.horizon == "P3"
                or w.spec.priority == "P2"
            ):
                continue
            w.loop_hits["data_supplier"] = True
            w.priority_basis = (
                f"유일 data_supplier: {table.removeprefix('db.models.')} 테이블에 P0 writer 없음"
            )
            _finalize_priority(w)
            if w.release_priority == "P0":
                w.priority_basis = (
                    f"폐쇄루프: data_supplier(유일 writer — {table.removeprefix('db.models.')})"
                )
            promoted = True
        if not promoted:
            unresolved.add(table)
    return unresolved


_STATE_TRACKERS = re.compile(
    r"audit|evidence|provenance|history|timeseries|_event|generation_log|ledger"
)
KEEP_MIN_CRITERIA = 5  # §3.4 "아래를 대부분 만족하면" — 6조건 중 5
REPLACE_MIN_SIGNALS = 3  # §3.4 REPLACE 신호 6종(측정 가능분) 중 3 — 단독 신호로 REPLACE 선고 금지


def _apply_criteria_34(row: Row) -> None:
    """계획서 100 §3.4 KEEP/REFACTOR/REPLACE/POSTPONE 기준의 *측정 가능한 부분*을 불리언으로.

    §3.4는 서술형 기준이고 §3.14는 점수다. 둘을 이렇게 결합한다:
    POSTPONE = 우선도 P2 · REPLACE = 매트릭스 14+ 또는 REPLACE 신호 ≥3 · HEAVY = 매트릭스 10~13 ·
    KEEP = §3.4 KEEP 6조건 중 ≥5 · 나머지 REFACTOR. "수정 비용 > 재작성 비용"은 측정 불가라
    신호에 넣지 않았다(사람 판단). §3.4 단독 판정(`criteria_action`)도 남겨 매트릭스와 어긋난
    행을 대시보드가 세게 한다.
    """
    sc, plane = row.scores, row.spec.plane
    own_and_closure = set(row.own_modules) | set(row.closure)
    tracked = any(_STATE_TRACKERS.search(m) for m in own_and_closure)
    keep = {
        "k1_subject_low": sc["A_subject"] <= 1,
        "k2_api_clear": plane in ("S", "C") or row.fan_in >= 1 or row.has_cli,
        "k3_tests_exist": sc["D_tests"] <= 2,
        "k4_model_ok": row.ownership != "MIXED" and row.mixed_own_schema == 0,
        "k5_coupling_low": sc["C_coupling"] <= 1,
        "k6_verified": row.status not in ("Flag-off", "Shadow") and row.test_functions >= 1,
    }
    replace = {
        "r1_model_conflict": row.mixed_own_schema > 0,
        "r2_subject_in_core": row.ownership in ("CORE", "INFRA", "MIXED") and sc["A_subject"] == 3,
        "r3_untestable": sc["D_tests"] == 3,
        "r4_duplicate": bool(row.spec.duplicate_of),
        "r5_state_untracked": sc["E_state"] >= 2 and not tracked,
        "r6_no_api_contract": plane == "S" and row.contract_gaps > 0,
    }
    row.criteria = {**keep, **replace}
    row.keep_met = sum(keep.values())
    row.replace_signals = sum(replace.values())
    if row.release_priority in ("P2", "P3"):
        row.criteria_action = "POSTPONE"
    elif row.replace_signals >= REPLACE_MIN_SIGNALS:
        row.criteria_action = "REPLACE_CANDIDATE"
    elif row.keep_met >= KEEP_MIN_CRITERIA:
        row.criteria_action = "KEEP"
    else:
        row.criteria_action = "REFACTOR"

    matrix = row.matrix_action
    if row.release_priority in ("P2", "P3"):
        row.migration_action = "POSTPONE"
        row.action_basis = f"{row.release_priority}(12월 폐쇄루프 비관여 — 이월≠삭제)"
    elif matrix == "REPLACE_CANDIDATE" or row.replace_signals >= REPLACE_MIN_SIGNALS:
        row.migration_action = "REPLACE_CANDIDATE"
        row.action_basis = (
            f"매트릭스 {row.total}점 / REPLACE 신호 {row.replace_signals}/6 "
            "— 경계 복구 가능성은 사람 판정"
        )
    elif matrix == "HEAVY_REFACTOR":
        row.migration_action, row.action_basis = "HEAVY_REFACTOR", f"매트릭스 {row.total}점(10~13)"
    elif row.keep_met >= KEEP_MIN_CRITERIA:
        row.migration_action, row.action_basis = "KEEP", f"§3.4 KEEP {row.keep_met}/6 충족"
    else:
        failed = [k for k, v in keep.items() if not v]
        row.migration_action = "REFACTOR"
        row.action_basis = f"§3.4 KEEP {row.keep_met}/6 — 미충족 {', '.join(failed)}"


def _status(spec: Spec, defaults: dict[str, str]) -> tuple[str, str]:
    if not spec.flag:
        return spec.status, ""
    default = defaults.get(spec.flag)
    if default is None:
        raise KeyError(f"{spec.fid}: config.Settings에 플래그 {spec.flag!r}가 없다")
    return (spec.status if _flag_is_on(default) else "Flag-off"), f"{spec.flag}={default}"


def _route_patterns(prefix: str, matched: list[Endpoint]) -> list[re.Pattern[str]]:
    """테스트 본문에서 경로 리터럴을 찾는 정규식 — `{param}`은 한 세그먼트 와일드카드."""
    out: list[re.Pattern[str]] = []
    for e in matched:
        literal = prefix + ("" if e.path == "/" else e.path)
        escaped = re.escape(literal).replace(r"\{", "{").replace(r"\}", "}")
        out.append(re.compile(re.sub(r"\{[^}]+\}", r"[^/\"'\\s]+", escaped)))
    return out


def _measure_serving(
    spec: Spec,
    eps: list[Endpoint],
    classify: Any,
    tests: TestIndex,
    endpoint_owner: dict[tuple[str, str, str], str],
    errors: list[str],
) -> Row:
    prefix = _router_prefix(spec.router)
    router_mod = "app" if spec.router == "app" else f"api.{spec.router}"
    matched: list[Endpoint] = []
    for route in spec.routes:
        method, _, path = route.partition(" ")
        hit = [e for e in eps if e.method == method and e.path == path]
        if len(hit) != 1:
            errors.append(f"{spec.fid}: 경로 {route!r} 매칭 {len(hit)}건 (기대 1)")
            continue
        key = (spec.router, method, path)
        if key in endpoint_owner:
            errors.append(f"{spec.fid}: 엔드포인트 {route!r}는 {endpoint_owner[key]}에 이미 귀속")
        endpoint_owner[key] = spec.fid
        matched.append(hit[0])
    closure = sorted(set().union(*(e.refs for e in matched)) if matched else set())
    adapter = [m for m in closure if classify(m)[0] == "ADAPTER"]
    mixed = [m for m in closure if classify(m)[0] == "MIXED"]
    if classify(router_mod)[0] == "MIXED":
        mixed.append(router_mod)
    dbm = [m for m in closure if m.startswith("db.models.")]
    tf, tfn = tests.fns_matching_routes(_route_patterns(prefix, matched))
    if adapter:
        ownership = "CORE+ADAPTER_DEP"
    elif router_mod in mixed:
        ownership = "MIXED"
    else:
        ownership = "CORE"
    file = BACKEND / ("app.py" if spec.router == "app" else f"api/{spec.router}.py")
    routes_text = ", ".join(
        f"{e.method} {prefix}{'' if e.path == '/' else e.path}" for e in matched
    )
    status, flag_default = _STATUS_CACHE[spec.fid]
    return Row(
        spec=spec,
        location=f"{file.relative_to(REPO)} :: {routes_text}",
        own_modules=[router_mod],
        loc=0,
        endpoints=len(matched),
        write_endpoints=sum(1 for e in matched if e.method != "GET"),
        closure=closure,
        adapter_deps=adapter,
        mixed_deps=mixed,
        db_models=dbm,
        coupling_count=len(closure),
        test_files=tf,
        test_functions=tfn,
        mutations=0,
        ownership=ownership,
        status=status,
        flag_default=flag_default,
        contract_gaps=sum(1 for e in matched if not e.contract),
    )


def _measure_modules(
    spec: Spec,
    universe: list[str],
    classify: Any,
    v1: Any,
    tests: TestIndex,
    module_owner: dict[str, str],
    errors: list[str],
) -> Row:
    own_acc: set[str] = set()
    for entry in spec.modules:
        if entry.startswith("-"):
            excluded = set(_resolve_modules(entry[1:], universe))
            if not excluded & own_acc:
                errors.append(f"{spec.fid}: 제외 항목 {entry!r}이 아무것도 빼지 않는다")
            own_acc -= excluded
            continue
        resolved = _resolve_modules(entry, universe)
        if not resolved:
            errors.append(f"{spec.fid}: 모듈 항목 {entry!r} 해석 0건")
        own_acc |= set(resolved)
    own = sorted(own_acc)
    for m in own:
        if m in module_owner:
            errors.append(f"{spec.fid}: 모듈 {m}은 {module_owner[m]}에 이미 귀속")
        module_owner[m] = spec.fid
    loc = 0
    mutations = 0
    imports: set[str] = set()
    verdicts: set[str] = set()
    places: set[str] = set()
    has_cli = False
    mixed_own_schema = 0
    for m in own:
        path = _module_path(m)
        assert path is not None and path.is_file()
        text = path.read_text(encoding="utf-8")
        loc += text.count("\n") + 1
        mutations += len(_DB_MUTATION.findall(text))
        has_cli = has_cli or "argparse" in text or "\ndef main(" in text
        verdict = classify(m)[0]
        verdicts.add(verdict)
        if verdict == "MIXED" and m.startswith("schema."):
            mixed_own_schema += 1
        imports.update(v1._internal_imports(path))
        places.add(str((path if path.parent == BACKEND else path.parent).relative_to(REPO)))
    for pkg in spec.pipelines:
        pdir = PIPELINE / pkg
        if not pdir.is_dir():
            errors.append(f"{spec.fid}: data_pipeline 패키지 {pkg!r} 없음")
            continue
        verdicts.add(PIPELINE_MAP.get(pkg, "CORE"))
        places.add(str(pdir.relative_to(REPO)))
        has_cli = has_cli or (pdir / "__main__.py").is_file()
        for p in sorted(pdir.rglob("*.py")):
            if p.name == "__init__.py":
                continue
            text = p.read_text(encoding="utf-8")
            loc += text.count("\n") + 1
            mutations += len(_DB_MUTATION.findall(text))
    closure = sorted(m for m in imports if m not in own_acc)
    adapter = [m for m in closure if classify(m)[0] == "ADAPTER"]
    mixed = [m for m in closure if classify(m)[0] == "MIXED"]
    tf, tfn = tests.fns_importing(own_acc)
    for pkg in spec.pipelines:
        pf, pfn = tests.fns_under(TESTS / "data_pipeline" / pkg)
        tf, tfn = tf + pf, tfn + pfn
    status, flag_default = _STATUS_CACHE[spec.fid]
    return Row(
        spec=spec,
        location=", ".join(sorted(places)),
        own_modules=own,
        loc=loc,
        endpoints=0,
        write_endpoints=0,
        closure=closure,
        adapter_deps=adapter,
        mixed_deps=mixed,
        db_models=sorted(m for m in closure if m.startswith("db.models.")),
        coupling_count=len(closure),
        test_files=tf,
        test_functions=tfn,
        mutations=mutations,
        ownership=_ownership_from_own(verdicts),
        status=status,
        flag_default=flag_default,
        has_cli=has_cli,
        mixed_own_schema=mixed_own_schema,
    )


_SEED_PATTERNS: list[re.Pattern[str]] = []


def _seed_route_patterns() -> list[re.Pattern[str]]:
    """학생 루프 씨앗 경로를 클라 소스에서 찾는 정규식 — 서빙 표면 테스트 매칭과 같은 규칙."""
    if not _SEED_PATTERNS:
        for router, route in sorted(STUDENT_LOOP_ROUTES):
            method, _, path = route.partition(" ")
            stub = Endpoint(method, path, "", set())
            _SEED_PATTERNS.extend(_route_patterns(_router_prefix(router), [stub]))
    return _SEED_PATTERNS


def _measure_client(spec: Spec, tests: TestIndex, errors: list[str]) -> Row:
    files: list[pathlib.Path] = []
    for rel in spec.client:
        p = REPO / "src" / rel
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(_client_source_files(p))
        else:
            errors.append(f"{spec.fid}: 클라 경로 {rel!r} 없음")
    loc = 0
    writes = 0
    cross: set[str] = set()
    own_frag = {re.sub(r"^mobile/lib/", "", r).rstrip("/") for r in spec.client}
    for f in files:
        text = f.read_text(encoding="utf-8")
        loc += text.count("\n") + 1
        writes += len(_DART_WRITE.findall(text))
        for m in re.finditer(r"package:korean_math_app/([a-z_/]+)", text):
            target = m.group(1)
            if any(target.startswith(o) for o in own_frag):
                continue
            parts = target.split("/")
            cross.add(parts[1] if parts[0] == "features" and len(parts) > 1 else parts[0])
    seed_hits = 0
    if files:
        blob = "\n".join(f.read_text(encoding="utf-8") for f in files)
        for rx in _seed_route_patterns():
            if rx.search(blob):
                seed_hits += 1
    # dart 테스트는 `package:korean_math_app/<lib 이하 경로>`로 import한다 — 그 문자열로 맞춘다
    frags = [
        "korean_math_app/" + re.sub(r"^mobile/lib/", "", r)
        for r in spec.client
        if r.startswith("mobile/lib")
    ]
    tf, tfn = tests.dart_fns(frags) if frags else (0, 0)
    if any(r.startswith("web/") for r in spec.client):
        jf, jfn = tests.js_fns()
        tf, tfn = tf + jf, tfn + jfn
    status, flag_default = _STATUS_CACHE[spec.fid]
    return Row(
        spec=spec,
        location=", ".join("src/" + r for r in spec.client),
        own_modules=[],
        loc=loc,
        endpoints=0,
        write_endpoints=0,
        closure=sorted(cross),
        adapter_deps=[],
        mixed_deps=[],
        db_models=[],
        coupling_count=len(cross),
        test_files=tf,
        test_functions=tfn,
        mutations=writes,
        ownership="CLIENT",
        status=status,
        flag_default=flag_default,
        client_seed_routes=seed_hits,
    )


_STATUS_CACHE: dict[str, tuple[str, str]] = {}
_TEST_INDEX: list[TestIndex] = []


def _test_index() -> TestIndex:
    """테스트 851파일 AST 파싱은 비싸다 — 프로세스 안에서 1회만 만든다(결함 주입 재측정 공유)."""
    if not _TEST_INDEX:
        _TEST_INDEX.append(TestIndex.build())
    return _TEST_INDEX[0]


def _completeness_errors(
    endpoint_cache: dict[str, list[Endpoint]],
    endpoint_owner: dict[tuple[str, str, str], str],
    universe: list[str],
    module_owner: dict[str, str],
    router_modules_seen: set[str],
) -> list[str]:
    errors: list[str] = []
    for router_mod, eps in endpoint_cache.items():
        for e in eps:
            if (router_mod, e.method, e.path) not in endpoint_owner:
                errors.append(f"미귀속 엔드포인트: {router_mod} {e.method} {e.path} ({e.func})")
    app_src = (BACKEND / "app.py").read_text(encoding="utf-8")
    for alias_name in set(re.findall(r"app\.include_router\((\w+)\)", app_src)):
        if alias_name.removesuffix("_router") not in endpoint_cache:
            errors.append(f"include_router({alias_name}) 라우터에 S 행이 하나도 없다")
    for m in universe:
        if m not in module_owner and m not in router_modules_seen:
            errors.append(f"미귀속 모듈: {m}")
    for m, fid in module_owner.items():
        if m in router_modules_seen:
            errors.append(f"라우터 모듈 {m}이 E/O 행({fid})에도 귀속")
    seen: set[str] = set()
    for spec in CATALOG:
        if spec.fid in seen:
            errors.append(f"Feature ID 중복: {spec.fid}")
        seen.add(spec.fid)
    mobile_features = {p.name for p in (MOBILE / "lib" / "features").iterdir() if p.is_dir()}
    claimed = {
        r.split("/")[3]
        for s in CATALOG
        if s.plane == "C"
        for r in s.client
        if r.startswith("mobile/lib/features/")
    }
    for f in sorted(mobile_features - claimed):
        errors.append(f"미귀속 Flutter feature: {f}")
    # 클라 경로는 *경로 단위*로 정확히 1행 — `claimed`는 feature 디렉터리 이름 집합이라 부재만 잡고,
    # 같은 경로(또는 그 상위·하위)를 두 C 행이 지정하면 loc·테스트가 이중 계상되는데도 통과했다
    # (PR #980 Codex P2 지적 — 정정 2026-09-06). 백엔드 모듈·엔드포인트 검사와 같은 형태로 막는다.
    client_owner: dict[str, str] = {}
    for spec in CATALOG:
        for rel in spec.client:
            key = rel.rstrip("/")
            if key in client_owner:
                errors.append(f"{spec.fid}: 클라 경로 {key!r}은 {client_owner[key]}에 이미 귀속")
                continue
            for prev, fid in client_owner.items():
                if key.startswith(prev + "/") or prev.startswith(key + "/"):
                    errors.append(
                        f"{spec.fid}: 클라 경로 {key!r}이 {fid}의 {prev!r}과 중첩 — 이중 계상"
                    )
            client_owner[key] = spec.fid
    return errors


def _effective_import_graph(universe: list[str], v1: Any) -> dict[str, set[str]]:
    """모듈 → 실효 내부 import 집합(심볼 단위 해석).

    `api.coach`가 `from whymath_backend.l4 import PolyaCoach`로 부르면 import 문에는 `l4`만
    남는다 — `l4/__init__`의 재수출을 따라 **그 심볼을 정의한 모듈**(l4.polya.engine)로 푼다.
    패키지 전체로 펼치지 않으므로(`l6` import가 L6 게이팅 9모듈 전부로 번지지 않음) fan-in과
    폐쇄루프 도달성 양쪽에서 과대 도달을 막는다. 6축 C·B 점수는 v1 규칙(문 단위)을 그대로 쓴다.
    """
    graph: dict[str, set[str]] = {}
    for m in universe:
        path = _module_path(m)
        assert path is not None
        tree = ast.parse(path.read_text(encoding="utf-8"))
        graph[m] = set(_import_alias_map(tree).values())
    return graph


def _reach(seeds: set[str], graph: dict[str, set[str]]) -> set[str]:
    """씨앗에서 import 간선을 따라 닿는 모듈 전부(BFS·visited)."""
    seen: set[str] = set()
    frontier = [m for m in seeds if m in graph]
    while frontier:
        m = frontier.pop()
        if m in seen:
            continue
        seen.add(m)
        frontier.extend(n for n in graph.get(m, ()) if n not in seen and n in graph)
    return seen


def measure(log: Any) -> tuple[list[Row], dict[str, Any]]:
    v1 = _load_script(V1_SCRIPT, "_eos_inventory_v1")
    scan = _load_script(SCAN_SCRIPT, "_eos_boundary_scan_v2")
    classify = scan.classify
    universe = _backend_modules()
    defaults = _config_defaults()
    tests = _test_index()
    log(
        f"[population] backend 모듈 {len(universe)} · 테스트 파일 py {len(tests.py)} "
        f"dart {len(tests.dart)} js {len(tests.js)}"
    )

    module_owner: dict[str, str] = {}
    endpoint_owner: dict[tuple[str, str, str], str] = {}
    endpoint_cache: dict[str, list[Endpoint]] = {}
    router_modules_seen: set[str] = set()
    errors: list[str] = []
    rows: list[Row] = []
    _STATUS_CACHE.clear()

    for spec in CATALOG:
        if spec.plane not in PLANES or spec.priority not in PRIORITIES:
            errors.append(f"{spec.fid}: plane/priority 어휘 위반")
            continue
        _STATUS_CACHE[spec.fid] = _status(spec, defaults)
        if spec.plane == "S":
            eps = endpoint_cache.setdefault(spec.router, _endpoints(spec.router))
            router_modules_seen.add("app" if spec.router == "app" else f"api.{spec.router}")
            rows.append(_measure_serving(spec, eps, classify, tests, endpoint_owner, errors))
        elif spec.plane in ("E", "O"):
            rows.append(_measure_modules(spec, universe, classify, v1, tests, module_owner, errors))
        else:
            rows.append(_measure_client(spec, tests, errors))

    errors += _completeness_errors(
        endpoint_cache, endpoint_owner, universe, module_owner, router_modules_seen
    )
    import_graph = _effective_import_graph(universe, v1)
    seed_routes = set(STUDENT_LOOP_ROUTES | PRODUCTION_LOOP_ROUTES)
    for router, route in seed_routes:
        method, _, path = route.partition(" ")
        eps = endpoint_cache.get(router, [])
        if not any(e.method == method and e.path == path for e in eps):
            errors.append(f"폐쇄루프 씨앗 경로가 실재하지 않는다: {router} {route}")
    for m in PRODUCTION_LOOP_MODULES:
        if m not in import_graph:
            errors.append(f"폐쇄루프 씨앗 모듈이 실재하지 않는다: {m}")

    def _route_refs(routes: frozenset[tuple[str, str]]) -> set[str]:
        out: set[str] = set()
        for router, route in routes:
            method, _, path = route.partition(" ")
            for e in endpoint_cache.get(router, []):
                if e.method == method and e.path == path:
                    out |= e.deep_refs
        return out

    student = _reach(_route_refs(STUDENT_LOOP_ROUTES), import_graph)
    production = _reach(
        _route_refs(PRODUCTION_LOOP_ROUTES) | set(PRODUCTION_LOOP_MODULES), import_graph
    )
    for row in rows:
        own = set(row.own_modules)
        if own and row.spec.plane != "S":
            row.fan_in = sum(1 for m, imps in import_graph.items() if m not in own and imps & own)
        _derive_priority(row, student, production, seed_routes)
    loop_tables = {m for m in student | production if m.startswith("db.models.")}
    tables_without_p0_writer = _promote_sole_suppliers(rows, loop_tables)
    for row in rows:
        _score(row, v1)
        log(
            f"[measure] {row.spec.fid} {row.spec.plane} own={row.ownership} "
            f"score={row.total} → {row.migration_action} ({row.status})"
        )
    info = {
        "backend_modules": len(universe),
        "endpoints": sum(len(v) for v in endpoint_cache.values()),
        "errors": errors,
        "student_loop_reach": len(student),
        "production_loop_reach": len(production),
        "loop_tables": sorted(loop_tables),
        "loop_tables_without_p0_writer": sorted(tables_without_p0_writer),
        "di_keys": sorted(_app_state_di_map()),
    }
    return rows, info


# ──────────────────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────────────────
def dashboard(rows: list[Row], info: dict[str, Any]) -> dict[str, Any]:
    def count(key: Any) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            k = key(r)
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))

    return {
        "population": len(rows),
        "backend_modules_covered": info["backend_modules"],
        "endpoints_covered": info["endpoints"],
        "by_plane": count(lambda r: r.spec.plane),
        "by_ownership": count(lambda r: r.ownership),
        "by_migration_action": count(lambda r: r.migration_action),
        "by_matrix_action": count(lambda r: r.matrix_action),
        "by_priority_proposed": count(lambda r: r.release_priority),
        "by_priority_prior_manual": count(lambda r: r.spec.priority),
        "priority_changed_from_prior": sum(
            1 for r in rows if r.release_priority != r.spec.priority
        ),
        "student_loop_reach_modules": info["student_loop_reach"],
        "production_loop_reach_modules": info["production_loop_reach"],
        "loop_tables": len(info["loop_tables"]),
        "loop_tables_without_p0_writer": info["loop_tables_without_p0_writer"],
        "di_keys_bridged": len(info["di_keys"]),
        "by_status": count(lambda r: r.status),
        "by_risk": count(lambda r: r.migration_risk),
        "release_p0_proposed": sum(1 for r in rows if r.release_priority == "P0"),
        "classification_rate": f"{len(rows)}/{len(rows)}",
        "by_criteria_action": count(lambda r: r.criteria_action),
        "keep_criteria_histogram": count(lambda r: f"{r.keep_met}/6"),
        "replace_signal_histogram": count(lambda r: f"{r.replace_signals}/6"),
        "final_differs_from_matrix": sum(
            1 for r in rows if r.spec.priority != "P2" and r.migration_action != r.matrix_action
        ),
        "final_differs_from_criteria": sum(
            1 for r in rows if r.migration_action != r.criteria_action
        ),
    }


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


_DASH_GROUPS = (
    "by_criteria_action",
    "keep_criteria_histogram",
    "replace_signal_histogram",
    "by_plane",
    "by_ownership",
    "by_migration_action",
    "by_matrix_action",
    "by_priority_proposed",
    "by_priority_prior_manual",
    "by_status",
    "by_risk",
)


def to_yaml(rows: list[Row], dash: dict[str, Any]) -> str:
    lines = [
        "# EOS 기능 인벤토리 v2 — 기능 단위 전수 장부 + Migration Map (기계 생성)",
        "# 재생성: python3 scripts/analysis/eos_feature_inventory_v2.py --write",
        "# 손편집 금지 — 카탈로그·임계·규칙은 생성기(정본)에 있다. 여기 고치면 다음 생성이 덮는다.",
        "# 출시 우선도(release_priority)는 *제안*이다 — 확정은 Kiki.",
        "schema_version: 2",
        "dashboard:",
        f"  population: {dash['population']}",
        f"  classification_rate: {dash['classification_rate']}",
        f"  backend_modules_covered: {dash['backend_modules_covered']}",
        f"  endpoints_covered: {dash['endpoints_covered']}",
        f"  release_p0_proposed: {dash['release_p0_proposed']}",
        f"  priority_changed_from_prior: {dash['priority_changed_from_prior']}",
        f"  student_loop_reach_modules: {dash['student_loop_reach_modules']}",
        f"  production_loop_reach_modules: {dash['production_loop_reach_modules']}",
        f"  loop_tables: {dash['loop_tables']}",
        f"  loop_tables_without_p0_writer: [{', '.join(dash['loop_tables_without_p0_writer'])}]",
        f"  di_keys_bridged: {dash['di_keys_bridged']}",
        f"  final_differs_from_matrix: {dash['final_differs_from_matrix']}",
        f"  final_differs_from_criteria: {dash['final_differs_from_criteria']}",
    ]
    for key in _DASH_GROUPS:
        lines.append(f"  {key}:")
        lines += [f"    {k}: {v}" for k, v in dash[key].items()]
    lines.append("features:")
    for r in rows:
        s = r.spec
        lines += [
            f"  - feature_id: {s.fid}",
            f"    name: {_q(s.name)}",
            f"    plane: {s.plane}",
            f"    location: {_q(r.location)}",
            f"    user: {s.user}",
            f"    domain: {_q(s.domain)}",
            f"    eos_ownership: {r.ownership}",
            f"    eos_target: {_q(EOS_TARGET[r.ownership])}",
            f"    status: {r.status}",
            f"    flag: {_q(r.flag_default)}",
            f"    coupling: {r.coupling}",
            f"    tests: {r.tests}",
            f"    migration_action: {r.migration_action}",
            f"    matrix_action: {r.matrix_action}",
            f"    release_priority_proposed: {r.release_priority}",
            f"    release_priority_prior_manual: {s.priority}",
            f"    priority_basis: {_q(r.priority_basis)}",
            f"    migration_risk: {r.migration_risk}",
            f"    loc: {r.loc}",
            f"    endpoints: {r.endpoints}",
            f"    write_endpoints: {r.write_endpoints}",
            f"    db_mutation_calls: {r.mutations}",
            f"    own_modules: {len(r.own_modules)}",
            f"    adapter_deps: [{', '.join(r.adapter_deps)}]",
            f"    mixed_deps: [{', '.join(r.mixed_deps)}]",
            f"    db_model_modules: {len(r.db_models)}",
            f"    coupling_count: {r.coupling_count}",
            f"    test_files: {r.test_files}",
            f"    test_functions: {r.test_functions}",
            "    matrix:",
        ]
        lines += [f"      {k}: {v}" for k, v in r.scores.items()]
        lines += [
            f"    matrix_total: {r.total}",
            f"    criteria_action: {r.criteria_action}",
            f"    keep_criteria_met: {r.keep_met}/6",
            f"    replace_signals: {r.replace_signals}/6",
            f"    action_basis: {_q(r.action_basis)}",
            f"    fan_in: {r.fan_in}",
            f"    contract_gaps: {r.contract_gaps}",
            f"    duplicate_of: {_q(s.duplicate_of)}",
            "    loop_hits:",
        ]
        lines += [f"      {k}: {str(v).lower()}" for k, v in r.loop_hits.items()]
        lines += [
            "    criteria_34:",
        ]
        lines += [f"      {k}: {str(v).lower()}" for k, v in r.criteria.items()]
        lines += [f"    seat: {_q(s.seat)}"]
    return "\n".join(lines) + "\n"


CSV_HEADER = [
    "Feature ID",
    "기능명",
    "평면",
    "현재 위치",
    "사용자",
    "Domain",
    "EOS Ownership",
    "EOS 대상",
    "상태",
    "플래그",
    "결합도",
    "테스트",
    "Migration Action",
    "매트릭스 판정",
    "출시 우선도(제안)",
    "우선도 근거",
    "선행 제안(v2.0)",
    "Migration Risk",
    "A과목",
    "B DB",
    "C결합",
    "D테스트",
    "E상태",
    "F데이터",
    "총점",
    "LOC",
    "엔드포인트",
    "쓰기EP",
    "Adapter 의존",
    "Mixed 의존",
    "DB모델수",
    "테스트fn",
    "§3.4 KEEP충족(/6)",
    "§3.4 REPLACE신호(/6)",
    "§3.4 기준판정",
    "판정 근거",
    "근거",
]


def to_csv(rows: list[Row]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for r in rows:
        s = r.spec
        w.writerow(
            [
                s.fid,
                s.name,
                PLANES[s.plane],
                r.location,
                s.user,
                s.domain,
                r.ownership,
                EOS_TARGET[r.ownership],
                r.status,
                r.flag_default,
                r.coupling,
                r.tests,
                r.migration_action,
                r.matrix_action,
                r.release_priority,
                r.priority_basis,
                s.priority,
                r.migration_risk,
                *(r.scores[k] for k in AXES),
                r.total,
                r.loc,
                r.endpoints,
                r.write_endpoints,
                ";".join(r.adapter_deps),
                ";".join(r.mixed_deps),
                len(r.db_models),
                r.test_functions,
                r.keep_met,
                r.replace_signals,
                r.criteria_action,
                r.action_basis,
                s.seat,
            ]
        )
    return buf.getvalue()


def to_markdown(rows: list[Row], dash: dict[str, Any]) -> str:
    lines = [
        "| ID | 기능명 | 위치 | 사용자 | Domain | Ownership | 상태 | 결합 | 테스트 "
        "| Action | 우선도 | Risk | 6축 | 계 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        s = r.spec
        axes = " ".join(str(r.scores[k]) for k in AXES)
        loc = r.location.split(" :: ")[0].replace("src/backend/whymath_backend/", "…/")
        lines.append(
            f"| {s.fid} | {s.name} | `{loc}` | {s.user} | {s.domain} | {r.ownership} "
            f"| {r.status} | {r.coupling} | {r.tests} | **{r.migration_action}** "
            f"| {r.release_priority} | {r.migration_risk} | {axes} | {r.total} |"
        )
    lines += ["", f"**대시보드**: {dash}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="backlog/inventory/*_v2.{yaml,csv} 갱신"
    )
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        rows, info = measure(log)
    except Exception as exc:  # noqa: BLE001 — 계측기 최상위: 원인 타입을 남기고 실패
        log(f"[fatal] 측정 실패 {type(exc).__name__}: {exc}")
        return 1
    if info["errors"]:
        for e in info["errors"]:
            log(f"[전수성 위반] {e}")
        log(f"[fatal] 전수성 위반 {len(info['errors'])}건 — 장부를 쓰지 않는다")
        return 1
    if len(rows) < 100:
        log(f"[fatal] 모집단 {len(rows)}행 — 카탈로그가 무너졌다(빈 장부 위장 금지)")
        return 1
    dash = dashboard(rows, info)
    print(to_markdown(rows, dash))
    if args.write:
        LEDGER_YAML.parent.mkdir(parents=True, exist_ok=True)
        LEDGER_YAML.write_text(to_yaml(rows, dash), encoding="utf-8")
        # Excel(한국어 Windows)이 UTF-8로 읽게 BOM을 붙인다 — CLAUDE.md 인코딩 규칙
        LEDGER_CSV.write_text(to_csv(rows), encoding="utf-8-sig")
        log(f"[out] {LEDGER_YAML.relative_to(REPO)} · {LEDGER_CSV.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
