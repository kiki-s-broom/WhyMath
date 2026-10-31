# P3-78 라이브 튜터 응답 수집 런북 (Kiki PC · Phaiakes9)

판정 기준: 브랜치 `claude/p3-78-ai-quality-live-run` 커밋 `699626e33f8f4079490f46ccf2c283c1bf3f4ca0`
(수집 CLI `src/backend/whymath_backend/harness/ai_quality_live_collect.py` · origin/main `5d309758` 병합 후 · 이 런북을 싣는 커밋과 수집 코드 동일)

P3-10 AI 품질 평가셋 244사례에 라이브 튜터(WH-1 primary · 라우터 경유 · Langfuse 추적)를 돌려 응답 파일을 만들고, 그 파일을
저장소 브랜치로 올리는 절차다. 8축 평가(`ai_quality_eval --responses`)는 결정론이라 클라우드 세션이 받은 파일로 돌리고 리포트를
커밋한다. **Kiki PC에서는 수집만 한다.**

## 6항목 브리핑

1. **과제 명칭**: P3-78 라이브 튜터 응답 수집(244사례).
2. **목적**: 결정론 후보만으로 잰 AI 품질 8축(P3-10)을 실제 LLM 튜터 응답으로 다시 잰다. 결과는 임계값 확정(D16)의 입력이다.
3. **절차**(약 30~70분): 블록 1 작업 폴더 준비·HEAD 대조(1분) → 블록 2 환경 점검(1분) → 블록 3 시험 수집 3건(1~2분) →
   블록 4 본 수집 244건(사례당 최대 15초 · 약 20~60분) → 블록 5 결과 올리기(1분).
4. **성공 기준**: 블록 1 `HEAD_OK=True` · 블록 2 `READY=True` · 블록 3 `COLLECT_EXIT=5`(3건만 돈 미완결 — 정상) ·
   블록 4 `COLLECT_EXIT=0`(완결 · 라이브 비율 ≥ 0.5) 또는 `4`(완결 · 라이브 비율 부족 — 결과 자체가 측정값이니 그대로 올린다) ·
   블록 5 `PUSH_EXIT=0`. 블록 4가 `3`(미완결 + 실패)이면 블록 4-재개를 돈다. 그 밖의 값·`False`·`WRITE_REFUSED`가 나오면 다음 블록으로
   가지 말고 그 블록 출력 전체를 세션에 붙인다.
5. **실행 환경**: Phaiakes9의 Windows PowerShell. 공유 클론 `C:\Users\kiki\Desktop\__AI\WhyMath`는 브랜치를 옮기지 않고
   가상환경(`.venv`)과 `.env`만 빌려 쓴다. 실제 작업 폴더는 별도 worktree `C:\Users\kiki\Desktop\__AI\WhyMath-01B-p378`.
   선행 조건: Ollama 실행 중 + 모델 `qwen2.5:3b` 설치(튜터 정책은 라우터가 LOCAL GENERAL FAST로 보낸다).
6. **창 구분**: 새 PowerShell 창 하나(이하 "P3-78 창")에서 블록을 순서대로 **하나씩** 붙여넣는다. 서버를 띄우지 않으므로 창 점유는 없다.

## 블록 개요 (블록 본문은 세션이 채팅으로 준다 — 자리표시자 0개)

- 블록 1: 공유 클론에서 fetch → worktree가 없으면 `git worktree add --detach`, 있으면 그 폴더만 대상 커밋으로 `checkout --detach` → `HEAD_OK`.
- 블록 2: HEAD 재대조 · 공유 클론 `.venv` 파이썬 + `PYTHONPATH`(worktree 코드) · `whymath_backend.__file__`이 worktree인지 ·
  Ollama `/api/tags`에 `qwen2.5:3b` · 공유 클론 `.env`를 worktree로 복사(없을 때만 · git 제외 대상) · Langfuse 키 **이름** 존재 여부만 출력 → `READY`.
- 블록 3: 조건 재계산 후 `--limit 3`을 `data\runs\p3_78-live\smoke\live.jsonl`로.
- 블록 4: 조건 재계산 후 244건을 `data\runs\p3_78-live\live.jsonl`로. 블록 4-재개는 같은 명령에 `--resume`(같은 설정·HEAD에서만 받아들여진다).
- 블록 5: 조건 재계산 후 worktree에서 새 브랜치 `p3-78/live-output-20261031`을 만들어 `data/runs/p3_78-live/`만 커밋·push.
  `.env`는 git 제외 대상이고 명시 경로만 `git add`하므로 올라가지 않는다.

## 종료 코드 (`ai_quality_live_collect`)

| 코드 | 뜻 | 다음 행동 |
|---|---|---|
| 0 | 전 사례 응답 완결 ∧ 라이브 비율 ≥ `--min-live-rate`(기본 0.5 — 제안값, 확정은 D16과 함께) | 블록 5 |
| 1 | 준비 실패(평가셋·설정·HEAD 지문 불일치 포함) 또는 파일 전체 라이브 0건 | 출력 전체를 세션에 |
| 2 | 인자 오류 | 출력 전체를 세션에 |
| 3 | 미완결 + 이번 실행에 실패 있음 | 블록 4-재개 |
| 4 | 완결이지만 라이브 비율 < 하한 | 블록 5(측정값으로 올린다) |
| 5 | 미완결 + 실패 0(`--limit`로 멈춤) | 블록 3에서는 정상 |

산출물 세 개: `live.jsonl`(응답 — 원문은 여기에만) · `live.jsonl.failures.jsonl`(실패 — 예외 타입·HTTP 상태·본문 300자·타임아웃) ·
`live.jsonl.run.json`(실행 식별 — 평가셋 sha256 · git HEAD · 설정 지문 · 선언/관측 모델 · 결말 분포 · 유효 표본 상한 · Langfuse 구성·flush 결과).

## 측정 한계 (리포트에 함께 적는다)

- 튜터 프롬프트에 문항 본문·학생 원문이 들어가지 않아(P3-72 설계) 244사례 중 서로 다른 첫 프롬프트는 66개다(스크립트 실행 실측). 축별 Wilson 판정은 유효 표본 상한과 함께 읽는다.
- 스킬·교수법 팩·tutor_context 매니페스트·probe 후보·session_recall은 평가셋에 재료가 없어 공급하지 않는다 — 금지모드 가드와 select_probe는 측정 밖이다(run.json `unsupplied`).
- 오개념 진단은 결정론이라 오개념 축은 결정론 후보와 구조적으로 같다.

## 되돌리기

운영 DB 쓰기 없음. worktree는 `git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-01B-p378`로 지운다(복사한 `.env`도 함께 지워진다).
올린 브랜치는 세션이 결과를 받은 뒤 정리한다.
