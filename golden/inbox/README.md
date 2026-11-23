# golden/inbox — Kiki PC에서 올라온 지시문 보관함

Kiki PC 폴더 `2026-11-15_골든 다음`(1~5단계 AI지시문 + data)을 2026-11-23 브랜치
`golden-inbox/2026-11-23-golden-next`(커밋 `06faf9ce`)로 올렸다. 그 브랜치는 머지하지 않고, 이 폴더에는
**저장소에 없던 것만** 옮겼다. 대조 기준: main `4181e901`.

| 올라온 폴더 | 저장소 대응 | 대조 결과 | 처리 |
| --- | --- | --- | --- |
| `WhyMath_1단계_두껍게_AI지시문_개정판` | `golden/prompts_phase1` | 23파일 같은 이름 · PC에만 있는 줄 94 · 저장소에만 있는 줄 476 — 저장소 판이 2026-11-17 「실학생 대체 결정」(AI 학생으로 진행)을 반영한 새 판이다 | 옮기지 않음(저장소 판이 정본) |
| `WhyMath_1단계_두꺼게_AI지시문_개정판` | 위와 같음 | 위 폴더와 바이트 단위로 같다(이름 철자만 다른 중복) | 옮기지 않음 |
| `WhyMath_2단계_두번째단원_AI지시문` | `golden/prompts_phase2` | PC만 118 · 저장소만 425 — 저장소 판이 새 판 | 옮기지 않음 |
| `WhyMath_3단계_SubjectContract_AI지시문` | `golden/prompts_phase3` | PC만 84 · 저장소만 285 — 저장소 판이 새 판 | 옮기지 않음 |
| `WhyMath_4단계_파일럿_AI지시문` | `golden/prompts_phase4` | PC만 287 · 저장소만 800 — 저장소 판은 실학생 대신 AI 코호트 20명(S84·S85·S88·S97·S100·S105가 바뀜) | 옮기지 않음 |
| `WhyMath_5단계_봄공개_AI지시문` | 없음 | 새것 — 43파일(README + 지시문 42 · S106~S145 · H7·H8) | **`phase5_봄공개/`로 옮김**(줄바꿈 CRLF→LF만 바꿈) |
| `data` | — | 파일 0개(빈 폴더) | 없음 |

## phase5_봄공개 — 아직 실행 묶음이 아니다

- 2027 봄 공개(앱 심사 제출 5/28 · 공개 6/7) 계획의 지시문이다. 접두 `LA`, 보고 폴더 `golden/reports_phase5/`.
- **2026-11-17 결정 이전 판이다.** 4단계가 실제 학생 파일럿을 했다는 전제(S108 "파일럿 발견 1개 반영" · 내부 베타 신규 20명 · H8 베타 20명 모집)로 쓰여 있다.
  저장소 4단계는 그 결정으로 AI 코호트로 바뀌었고, 4단계 게이트(S105)는 "공개 여부는 판정하지 않는다"로 고쳐졌다. 그래서 5단계를 그대로 열 수 없다.
- 다음 지시문 계산기(`python -m golden.driver.next_task`)는 이 폴더를 읽지 않는다. 편입은 4단계 게이트 뒤 Kiki 결정으로 한다 — 그때
  ①4단계 결과에 맞게 다시 쓰고 ②`golden/prompts_phase5/`로 옮기고 ③접두 `LA`를 세션 등록 훅(`.claude/hooks/golden_session_register.py` — golden 밖)에 더한다.
  (③ 없이 `golden/prompts_phase5/`로 옮기면 `tests/infra/test_golden_session_register.py`가 첫 줄 형식을 못 읽어 실패한다.)
