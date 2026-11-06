# P3-94 튜터 좌석 3개 비교 수집 런북 (Kiki PC · Phaiakes9)

판정 기준: 브랜치 `claude/p3-94-llm-draft-measure` — 이 런북을 싣는 커밋과 수집 코드가 같다. 정확한 커밋 해시는
세션이 채팅으로 주는 블록 1의 기대값(`$Expect`)이 정본이다(문서에 해시를 적으면 이 문서를 싣는 커밋과 순환한다).

P3-94(D16 ⓐ)의 **LLM 초안 측정 경로**로 튜터 정책 좌석 3개를 같은 20사례에서 비교한다. 결과는 Kiki의 **튜터 모델 결정**의 입력이고,
그 결정 뒤 본 수집(244사례 · 선택한 좌석 1개)이 D16 임계값 6개 결정의 입력이 된다. **Kiki PC에서는 수집만 한다** — 평가
(`ai_quality_eval --drafts`)는 결정론이라 클라우드 세션이 받은 파일로 돌리고 리포트를 커밋한다.

## 무엇이 바뀌었나 (서빙 무변경)

- 수집기(`ai_quality_live_collect`)가 provider 원시 출력에서 `end_turn` 발화를 꺼내 사례 결말과 무관하게 `<out>.drafts.jsonl`에 쓴다.
  학생 응답 경로·러너·정책 코드는 그대로다 — 초안은 그 파일에만 있다.
- `--policy-seat`: 튜터 정책 호출의 라우터 결정(LOCAL·GENERAL·FAST)만 **이 수집기 프로세스 안에서** 다른 좌석으로 바꾼다.
  Kiki 2026-11-06 승인 후보 3개 = `local-fast`(`qwen2.5:3b` · 현행) · `local-mid`(`qwen2.5:7b`) · `cloud-mid`(OpenRouter
  `deepseek/deepseek-v4.1-flash`). 클라우드 호출 비용 사용 승인.
- 평가기 `--drafts`: 문장 축 6개만 판정하고 오개념 판정·Curriculum 범위 2축은 "대상 아님"으로 표기한다. 초안 0건이면 측정 불가(exit 2).

## 비교 사례 20건 (`data/runs/p3_94/seat_compare_eval_20.jsonl`)

정본 평가셋 244사례에서 **P3-78 실측 첫 정책 프롬프트 지문이 서로 다른 사례만**(전체 66종) 골랐다 — 같은 프롬프트를 두 번 재면 표본이
늘지 않는다. 평가셋 규칙(사다리 위치는 1..n 연속)에 맞춰 사다리 단위로 골랐다: 힌트 14건(완전 사다리 4개 = 1·2·3단계 × 4 + 1·2단계
사다리 1개) + 선택 6건(오답 4 · 정답 2) · 개념 6개 · 지문 20종. 줄은 정본 파일의 원문 그대로다(평가셋 sha256 `a756289cdab5…`).

20건은 축별 최소 표본(30)에 못 미치므로 이 회차의 축 판정은 **측정 불가(UNMEASURED)가 정상**이다. 비교의 주 지표는 판정이 아니라
아래 좌석별 회계와 축별 관측 비율이다.

## 6항목 브리핑

1. **과제 명칭**: P3-94 튜터 좌석 3개 비교 수집(20사례 × 3좌석).
2. **목적**: 튜터 정책을 어느 모델이 맡을지(Kiki 결정)의 근거를 만든다 — 좌석마다 LLM이 실제로 발화를 쓰는지(초안 수), 출력 계약을
   얼마나 어기는지(강등), 15초 예산 안에 끝나는지(지연·시간 초과), 쓴 문장이 6개 축에서 어떤지를 같은 사례로 나란히 본다.
3. **절차**(약 15~40분): 블록 1 작업 폴더·HEAD 대조(1분) → 블록 2 환경 점검(1분 · `qwen2.5:7b`가 없으면 내려받기 약 5~10분) →
   블록 3 좌석 3개 수집(좌석당 20사례 · 사례당 최대 약 28초 → 좌석당 약 2~10분) → 블록 4 결과 올리기(1분).
4. **성공 기준**: 블록 1 `HEAD_OK=True` · 블록 2 `READY=True` · 블록 3 좌석마다 `COLLECT_EXIT`가 0·3·4 중 하나이고
   `DRAFTS[좌석]` 값이 출력됨(0이어도 그 자체가 측정값이다) · 블록 4 `PUSH_EXIT=0`. 블록 3의 3(실패 포함)은 이 비교에서는
   **정상 결과**다 — 시간 초과·provider 오류도 좌석의 성질이므로 `--resume`으로 메우지 않는다. 1·2 또는 `False`·`WRITE_REFUSED`가
   나오면 다음 블록으로 가지 말고 그 블록 출력 전체를 세션에 붙인다.
5. **실행 환경**: Phaiakes9의 Windows PowerShell. 공유 클론 `C:\Users\kiki\Desktop\__AI\WhyMath`는 브랜치를 옮기지 않고 가상환경
   (`.venv`)과 `.env`만 빌려 쓴다. 실제 작업 폴더는 별도 worktree `C:\Users\kiki\Desktop\__AI\WhyMath-01B-p394`. 선행 조건:
   Ollama 실행 중 + 모델 `qwen2.5:3b`·`qwen2.5:7b` + OpenRouter 키(`WHYMATH_OPENROUTER_API_KEY` — `.env` 또는 사용자 환경변수).
6. **창 구분**: 새 PowerShell 창 하나(이하 "P3-94 창")에서 블록을 순서대로 **하나씩** 붙여넣는다. 서버를 띄우지 않으므로 창 점유는 없다.

## 블록 개요 (블록 본문은 세션이 채팅으로 준다 — 자리표시자 0개)

- 블록 1: 공유 클론에서 브랜치 fetch → worktree가 없으면 `git worktree add --detach`, 있으면 그 폴더만 기대 커밋으로
  `checkout --detach` → `HEAD_OK`.
- 블록 2: HEAD 재대조 · 공유 클론 `.venv` 파이썬 + `PYTHONPATH`(worktree 코드) · `whymath_backend.__file__`이 worktree인지 ·
  Ollama `/api/tags`에 두 모델 · `.env`를 worktree로 복사(없을 때만 · git 제외 대상) · OpenRouter 키는 **존재와 길이만** 출력 ·
  비교 평가셋 파일 존재 → `READY`.
- 블록 3: 조건(HEAD·READY 재료) 재계산 후 단일 `if … { … } else { WRITE_REFUSED … }` 안에서 좌석 3개를 차례로
  `--eval-set data\runs\p3_94\seat_compare_eval_20.jsonl --policy-seat <좌석>`으로 `data\runs\p3_94\seat-<좌석>\live.jsonl`에 수집하고,
  좌석마다 `COLLECT_EXIT`와 `run.json`의 초안 수(`DRAFTS`)를 되읽어 출력한다.
- 블록 4: 조건 재계산 후 worktree에서 새 브랜치를 만들어 `data/runs/p3_94/`만 커밋·push. `.env`는 git 제외 대상이고 명시 경로만
  `git add`하므로 올라가지 않는다.

## 종료 코드 (`ai_quality_live_collect`)

| 코드 | 뜻 | 이 비교에서 |
|---|---|---|
| 0 | 전 사례 응답 완결 ∧ 라이브 비율 ≥ 0.5 | 정상 |
| 1 | 준비 실패(평가셋·설정·HEAD 지문 불일치 포함) 또는 **라이브 0건 그리고 초안 0건**(공허) | 출력 전체를 세션에 |
| 2 | 인자 오류 | 출력 전체를 세션에 |
| 3 | 미완결 + 이번 실행에 실패(시간 초과·provider 오류) 있음 | 정상(실패도 좌석의 성질 — 재개하지 않는다) |
| 4 | 완결 · 라이브 비율 < 0.5 | 정상(P3-78은 라이브 0% — 초안이 측정 재료다) |
| 5 | 미완결 + 실패 0(`--limit`로 멈춤) | 이 런북은 `--limit`를 쓰지 않는다 |

좌석마다 산출물 네 개: `live.jsonl`(학생 대면 응답) · `live.jsonl.drafts.jsonl`(**LLM 초안 — 측정 전용 · 원문은 여기에만**) ·
`live.jsonl.failures.jsonl`(실패 원인) · `live.jsonl.run.json`(실행 식별 + 좌석 비교 회계: `counts.drafts` · `counts.policy_seat_calls` ·
`counts.turn_latency_ms` · `counts.provider_calls_per_case` · `counts.tokens` · `observed_models`).

## 세션이 받은 뒤 하는 일

좌석마다 `python -m whymath_backend.harness.ai_quality_eval --eval-set data/runs/p3_94/seat_compare_eval_20.jsonl --drafts
data/runs/p3_94/seat-<좌석>/live.jsonl.drafts.jsonl --json …`로 문장 축 6개를 재고, 좌석 비교표(결말 분포 · 출력 계약 위반율 ·
초안 수 · 축별 관측 비율 · 턴 지연 중앙값·p95 · 턴당 호출 수 · 토큰)를 `docs/reviews/`에 커밋한다. 튜터 모델 확정과 MEMORY 결정
기록은 Kiki 몫이다(P3-94 ⑥ — 이 태스크는 비교 입력만 낸다).

## 측정 한계 (리포트에 함께 적는다)

- **트레이스 표기**: 좌석 교체는 파이프라인 바깥(provider 래퍼)에서 일어나므로 Langfuse·`calls`의 `cost_tier`·원가는 **원래 결정
  (LOCAL)**의 것이다. 실제로 답한 모델은 `served_model`(provider 사용량)로, 교체 건수는 `policy_seat_calls`로 따로 센다. 클라우드
  비용은 토큰 수(`counts.tokens`)로 사후 계산한다.
- **판정기 사각**: 6개 축 판정기는 규칙 기반이다(`ai_quality_judges.BLIND_SPOTS`) — 등호 없는 수학 서술·지어낸 개념 *이름*·의미적
  일관성은 못 본다. 축별 비율은 "규칙이 잡은 것"의 비율이다. 사람 채점 대조는 본 수집 뒤 별도로 한다(검토의견 우려 ①).
- 튜터 프롬프트에 문항 본문·학생 원문이 없어(P3-72 설계) 20사례는 지문이 서로 다르게 골랐지만, 같은 개념끼리 비슷한 출력이 날 수 있다.
- 스킬·교수법 팩·tutor_context 매니페스트·probe 후보·session_recall은 공급하지 않는다(P3-78과 같다 — `run.json` `unsupplied`).

## 되돌리기

운영 DB 쓰기 없음. worktree는 `git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-01B-p394`로 지운다(복사한 `.env`도
함께 지워진다). 올린 브랜치는 세션이 결과를 받은 뒤 정리한다.
