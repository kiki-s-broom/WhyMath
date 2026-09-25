"""초기 백로그 시딩 데이터 — 실제 로드맵에서 옮겨 적은 것 (날조 금지).

원천 문서:
    ROADMAP.md §현재 위치 (S1 잔여 대기분·S2 목표·병목 Top5·Kiki 수동 대기)
    docs/strategy/status_roadmap_2026-07.md   (S0~S5 정본)
    docs/strategy/subject_expansion_e_axis_v1.md (E1~E6 과목 순서·착수 트리거)
    docs/architecture/subject_expansion_readiness.md §8 (E1 물리 보류 대장)

주의: 지구과학은 E축 문서에 배치가 없다 → 하네스가 순서를 날조하지 않고
"배치 결정" 태스크(owner: kiki)로만 시딩한다.
"""

from __future__ import annotations

from models import Gate, Task, Track

SEED_DATE = "2026-07-08"  # 시딩 기준일 (하네스 교체 결정일)

STAGE_ORDER = ["S0", "S1", "S2", "S3", "S4", "S5", "E1", "E2", "E3", "E4", "E5", "E6"]


def build_seed() -> tuple[list[str], list[Track], list[Gate], list[Task]]:
    """(stage_order, 트랙, 게이트, 태스크) — seed 커맨드가 파일로 실체화한다."""

    tracks = [
        Track(
            id="math-completion",
            title="수학 완성 S0~S5 (중·고·대학 K-12+)",
            roadmap_ref="docs/strategy/status_roadmap_2026-07.md",
        ),
        Track(
            id="subject-expansion",
            title="다과목 확장 E축 — 물리→화학→생물→역사·사회(경제·역사·세계사)→국어→영어",
            roadmap_ref="docs/strategy/subject_expansion_e_axis_v1.md",
            entry_gate="G-s5-subject-expansion",  # 수학 완성 게이트 전 하드락
        ),
        Track(
            id="infra-debt",
            title="인프라·아키텍처 감사 상환 (플레이북 불변식 상시 감시)",
            roadmap_ref="docs/standards/build_checkpoint_questions.md",
        ),
    ]

    gates = [
        Gate(
            id="G-phaiakes9-key",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="Kiki 머신 작업 — 라이브 키 투입은 사람이 직접 행동한다(입력 태스크 없음)",
            title="Phaiakes9 라이브 키 투입 + 실측 비용 검증",
            kind="human",
            assignee="kiki",
            requested="2026-07-05",
            remind_after_days=7,
            notes="ROADMAP 병목 ② — S1 라이브 선행분 전체의 선결 조건",
        ),
        Gate(
            id="G-kiki-device-demo",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="Kiki 실기기 시연 — 사람이 직접 행동한다(입력 태스크 없음)",
            title="S1 탈출 게이트 ① — 실기기 학습 루프 시연",
            kind="human",
            assignee="kiki",
            requested="2026-07-08",
            remind_after_days=14,
        ),
        Gate(
            id="G-orphan-prod-run",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="Kiki 머신 prod 실행 — 사람이 직접 행동한다(입력 태스크 없음)",
            title="orphan 진단 스크립트 prod 실행 (scripts/diagnose_atom_orphans.py)",
            kind="human",
            assignee="kiki",
            requested="2026-07-05",
            remind_after_days=14,
        ),
        Gate(
            id="G-domain-partner",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="외부 인력 영입 — 대장 밖 행동이다(입력 태스크 없음)",
            title="수학 도메인 파트너 영입 (병목 ④ — 검수 큐 가동 조건)",
            kind="human",
            assignee="kiki",
            requested="2026-07-05",
            remind_after_days=30,
        ),
        Gate(
            id="G-crosswalk-approval",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="사람 승인 — 검수자가 직접 판정한다(입력 태스크 없음)",
            title="crosswalk 사람 승인 (docs/standards/crosswalk_gate_contract.md)",
            kind="human",
            assignee="kiki",
            requested="2026-07-08",
            remind_after_days=14,
        ),
        Gate(
            id="G-s5-subject-expansion",
            # HARN-174: pending 게이트는 여는 작업 또는 입력 없음 사유 중 하나가 필수
            no_inputs_reason="시딩 시점에는 판정 태스크가 없다 — 실대장은 판정 태스크를 입력으로 건다(HARN-174 백필)",
            title="S5 타과목 확장 게이트 — E축 착수 판정 체크리스트 전부 충족 (e_axis_v1 §5)",
            kind="decision",
            assignee="kiki",
            notes="수학 K-12 완성 전 어떤 과목도 착수 금지 (불변 전제)",
        ),
    ]

    tasks: list[Task] = []

    def add(task: Task) -> None:
        task.updated = task.updated or SEED_DATE
        tasks.append(task)

    # ── math-completion / S1 잔여 (라이브 선행분) ──────────────────────────
    add(
        Task(
            id="S1-10-audit-repay-1",
            title="감사 상환 #1 (라이브 선행분)",
            track="math-completion",
            stage="S1",
            layer="backend",
            priority=1,
            requires_gates=["G-phaiakes9-key"],
            acceptance=["s1_structure_audit_2026-07.md 상환 #1 항목 해소 + 테스트 green"],
            notes="ROADMAP S1 대기(라이브 선행) 목록",
        )
    )
    add(
        Task(
            id="S1-11-coach-harness-converge",
            title="상환 #3 완전 — coach→하네스 단일 수렴",
            track="math-completion",
            stage="S1",
            layer="backend",
            priority=1,
            requires_gates=["G-phaiakes9-key"],
            acceptance=[
                "coach 경로가 WH-1 하네스로 단일 수렴 (이중 경로 제거)",
                "회귀 테스트 green",
            ],
        )
    )
    add(
        Task(
            id="S1-12-phaiakes9-live-verify",
            title="Phaiakes9 라이브 검증 — 비용/지연 실측·verify 게이트 승격",
            track="math-completion",
            stage="S1",
            layer="backend",
            priority=1,
            requires_gates=["G-phaiakes9-key"],
            acceptance=[
                "라이브 호출 비용·지연 실측치를 docs/strategy에 기록",
                "verify 커버리지 게이트 승격 판정 + MEMORY.md 결정로그",
            ],
            notes="ROADMAP 병목 ② 대응",
        )
    )
    add(
        Task(
            id="S1-13-cost-calibration",
            title="비용/지연 실측 보정 + 프롬프트 캐싱 검토",
            track="math-completion",
            stage="S1",
            layer="backend",
            priority=2,
            depends_on=["S1-12-phaiakes9-live-verify"],
            acceptance=["라우터 est 단가표를 실측으로 보정", "캐싱 적용 여부 결정로그"],
        )
    )
    add(
        Task(
            id="S1-14-exit-gate-judgement",
            title="S1 탈출 게이트 판정 (실기기 시연 후)",
            track="math-completion",
            stage="S1",
            layer="docs",
            priority=1,
            owner="kiki",
            depends_on=["S1-12-phaiakes9-live-verify"],
            requires_gates=["G-kiki-device-demo"],
            acceptance=["탈출 게이트 3종 판정 기록 → ROADMAP·MEMORY 갱신"],
        )
    )

    # ── math-completion / S2 콘텐츠 공장 ──────────────────────────────────
    add(
        Task(
            id="S2-01-equiv-problems-100",
            title="동등문제 100문+ 생성 파이프라인 가동 (저작권 안전 대체 코퍼스)",
            track="math-completion",
            stage="S2",
            layer="data-pipeline",
            priority=1,
            depends_on=["S1-12-phaiakes9-live-verify"],
            requires_gates=["G-crosswalk-approval"],
            acceptance=["동등문제 100문 이상 materialize + 인간 검수 큐 적재"],
        )
    )
    add(
        Task(
            id="S2-02-whs-production-run",
            title="WH-S 솔버 하네스 실가동 — 동등문제 검증 풀이 공급",
            track="math-completion",
            stage="S2",
            layer="backend",
            priority=1,
            depends_on=["S2-01-equiv-problems-100"],
            acceptance=[
                "WH-S 배치가 동등문제에 검증 풀이·PRM 라벨 공급",
                "3-tier 검증 통과율 기록",
            ],
        )
    )
    add(
        Task(
            id="S2-03-problem-concept-relink",
            title="problem_concept 재연결 (S0 연기분)",
            track="math-completion",
            stage="S2",
            layer="backend",
            priority=2,
            acceptance=[
                "problem_concept 링크가 원자 백본 기준으로 재연결",
                "마이그레이션 + 테스트",
            ],
            notes="S0에서 S2로 연기된 항목 (ROADMAP S0 절)",
        )
    )
    add(
        Task(
            id="S2-04-orphan-129-cleanup",
            title="원자 그래프 orphan 129건 정리",
            track="math-completion",
            stage="S2",
            layer="data-pipeline",
            priority=2,
            requires_gates=["G-orphan-prod-run"],
            acceptance=["prod 진단 결과 기반 orphan 정리 + cleanup_atom_orphans.py 실행 기록"],
        )
    )
    add(
        Task(
            id="S2-05-domain-partner-onboard",
            title="도메인 파트너 검수 큐 온보딩",
            track="math-completion",
            stage="S2",
            layer="docs",
            priority=2,
            owner="kiki",
            requires_gates=["G-domain-partner"],
            acceptance=["파트너가 검수 큐에서 첫 배치 검수 완료"],
        )
    )
    add(
        Task(
            id="S2-06-l6-suneung-mode",
            title="L6 수능 모드 보강 (병목 ⑤ — S3 파일럿 준비)",
            track="math-completion",
            stage="S2",
            layer="backend",
            priority=2,
            acceptance=["수능 모드 시그니처·기출 메타 기반 문제 추천 루프 동작", "테스트 green"],
        )
    )

    # ── math-completion / S3~S5 대표 태스크 (스테이지 전환 가시화) ────────
    add(
        Task(
            id="S3-01-pilot-cohort",
            title="파일럿 5~10명 + 측정 하네스 가동",
            track="math-completion",
            stage="S3",
            layer="docs",
            priority=1,
            owner="kiki",
            depends_on=["S2-01-equiv-problems-100", "S2-06-l6-suneung-mode"],
            acceptance=["파일럿 코호트 모집·측정 하네스 KPI 베이스라인 기록"],
        )
    )
    add(
        Task(
            id="S4-01-math-k12-complete",
            title="수학 K-12 완성 — 초·중 확장 + 대학과정 연결",
            track="math-completion",
            stage="S4",
            layer="data-pipeline",
            priority=1,
            depends_on=["S3-01-pilot-cohort"],
            acceptance=["초·중·고+대학 4축 활성 + traversal 성능 예산 실부하 통과"],
            notes="대학과정 포함 — 개념 그래프는 학년 무관(Curriculum-as-Overlay)",
        )
    )
    add(
        Task(
            id="S5-01-expansion-gate-judgement",
            title="S5 타과목 확장 게이트 판정 → 통과 시 G-s5-subject-expansion clear",
            track="math-completion",
            stage="S5",
            layer="docs",
            priority=1,
            owner="kiki",
            depends_on=["S4-01-math-k12-complete"],
            acceptance=["e_axis_v1 §5 체크리스트 전수 판정 + 게이트 clear (evidence 필수)"],
        )
    )

    # ── infra-debt / 아키텍처 감사 (반복 태스크) ──────────────────────────
    add(
        Task(
            id="ARCH-01-playbook-audit",
            title="아키텍처 감사 1회차 — 플레이북 불변식·7계층 경계·이중 truth source 점검",
            track="infra-debt",
            stage="S1",
            layer="docs",
            priority=3,
            subject="cross",
            acceptance=[
                "build_checkpoint_questions.md 10단계 스냅샷 갱신",
                "playbook_part_review_questions.md Part 0~12 위반 여부 기록",
                "위반 발견 시 상환 태스크를 backlog add로 등록",
            ],
            notes="반복 태스크 — done 시 다음 회차(ARCH-02...)를 add로 재생성한다",
        )
    )

    # ── subject-expansion / E축 (entry_gate 하드락 — S5 전 착수 불가) ─────
    add(
        Task(
            id="E1-01-dimensional-consistency",
            title=(
                "물리 검증 primitive — dimensional_consistency "
                "(sympy.physics.units 형제 primitive)"
            ),
            track="subject-expansion",
            stage="E1",
            layer="backend",
            priority=1,
            subject="physics",
            acceptance=["{consistent/inconsistent/undecidable/parse_error} 4상태 계약 + 테스트"],
            notes="subject_expansion_readiness.md §8 보류 대장 항목",
        )
    )
    add(
        Task(
            id="E1-02-problem-subject-area",
            title="Problem.subject_area 컬럼 도입 (스키마 변경 0 원칙 검증 동반)",
            track="subject-expansion",
            stage="E1",
            layer="backend",
            priority=1,
            subject="physics",
            acceptance=["마이그레이션 + 임베딩 namespace 거버넌스 테스트 통과"],
        )
    )
    add(
        Task(
            id="E1-03-phy-area-registration",
            title="물리 AREA 니모닉 실등록 — MECH·ELEC·WAVE·THERMO·MODPHY",
            track="subject-expansion",
            stage="E1",
            layer="data-pipeline",
            priority=1,
            subject="physics",
            acceptance=["_TOPIC_AREA_MAP 레지스트리 규약으로 5종 등록 + 성취기준 크롤 연결"],
        )
    )
    add(
        Task(
            id="E1-04-physics-misconception-seed",
            title="물리 오개념 시드 — phys- 접두, FCI 분류 체계만 참조 (원문항 미사용)",
            track="subject-expansion",
            stage="E1",
            layer="data-pipeline",
            priority=2,
            subject="physics",
            acceptance=["misconceptions_phys_v1 시드 + reactive retrieval 연결"],
        )
    )
    add(
        Task(
            id="E2-01-chemistry-pack",
            title="화학 팩 6단계 — 플레이북 첫 재실행 (한계비용 50% 이하 실증)",
            track="subject-expansion",
            stage="E2",
            layer="data-pipeline",
            priority=1,
            subject="chemistry",
            depends_on=[
                "E1-01-dimensional-consistency",
                "E1-02-problem-subject-area",
                "E1-03-phy-area-registration",
                "E1-04-physics-misconception-seed",
            ],
            acceptance=["6단계 소요 실측이 E1 대비 50~60% + 통합과학 cross-subject 진단 작동"],
        )
    )
    add(
        Task(
            id="E3-01-biology-pack",
            title="생물 팩 — 사실 검증 축(근거 인용 RAG) 신설·과학 3부작 완성",
            track="subject-expansion",
            stage="E3",
            layer="data-pipeline",
            priority=1,
            subject="biology",
            depends_on=["E2-01-chemistry-pack"],
            acceptance=["사실 검증 축 undecidable 비율 허용선 이내 + 과학 3과목 통합 진단"],
        )
    )
    add(
        Task(
            id="E4-01-history-social-pack",
            title="역사·사회 팩 — 통합사회 진입 (경제·역사·세계사, 사건 네트워크·Polya 역사 대응)",
            track="subject-expansion",
            stage="E4",
            layer="data-pipeline",
            priority=1,
            subject="social",
            depends_on=["E3-01-biology-pack"],
            acceptance=["서술형 근거-주장 평가 검수자 일치율 실측 + 사료 라이선스 법무 확인"],
            notes=(
                "경제학·역사·세계사는 이 팩의 하위 코퍼스 "
                "(subject 세분: economics/history/world-history)"
            ),
        )
    )
    add(
        Task(
            id="E5-01-korean-pack",
            title="국어 팩 — 법무 선행 필수 (저작권 최고 위험·지문 4트랙)",
            track="subject-expansion",
            stage="E5",
            layer="data-pipeline",
            priority=1,
            subject="korean",
            depends_on=["E4-01-history-social-pack"],
            acceptance=["지문 4트랙 법무 승인 + 오독 진단 검수자 일치율 + 파일럿 D7"],
        )
    )
    add(
        Task(
            id="E6-01-english-pack",
            title="영어 팩 — 루브릭 평가 하네스 (인간 채점 일치율 κ 목표)",
            track="subject-expansion",
            stage="E6",
            layer="data-pipeline",
            priority=1,
            subject="english",
            depends_on=["E5-01-korean-pack"],
            acceptance=["루브릭 평가 인간 일치율(κ) 목표 도달 + 학교 영어 파일럿"],
        )
    )
    add(
        Task(
            id="E1-90-earth-science-placement",
            title="지구과학 E축 배치 결정 (현 E축 문서에 미배정 — 순서 날조 금지)",
            track="subject-expansion",
            stage="E1",
            layer="docs",
            priority=3,
            subject="earth-science",
            owner="kiki",
            acceptance=["subject_expansion_e_axis_v1.md 개정으로 지구과학 스테이지 확정"],
            notes="통합과학 완전 커버는 물리·화학·생물 3부작 기준 — 지구과학 위치는 Kiki 결정",
        )
    )

    return STAGE_ORDER, tracks, gates, tasks
