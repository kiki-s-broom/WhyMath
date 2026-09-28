# scripts/constitution — 원본 출처와 로컬 패치 기록

판정 기준: 이식 브랜치 `claude/ecstatic-feynman-bxxxvd` · 2026-09-27~28 · 태스크 `CONST-02`

이 폴더의 도구는 Kiki가 2026-09-26에 준 코딩 헌법 꾸러미(v1.0 제정 · v1.1 갱신)에서 왔다.
원본을 그대로 두지 않은 이유는 두 가지다. 첫째, 이 저장소의 CI가 `scripts/` 전체에 ruff·black(줄
길이 100)을 강제해 원본 그대로는 harness-integrity 잡이 red가 된다(원본 3파일에 E501 22건·black
재포맷 필요 — 1차 조사 실측). 둘째, 원본 `audit.py`에 실측으로 확인된 결함이 있었다.

## 원본 파일 지문 (sha256)

| 파일 | 출처 | sha256 |
|---|---|---|
| `audit.py` | v1.1 갱신 꾸러미 · `WhyMath_constitution_v1.1_update/scripts/constitution/audit.py` | `dd40d4292984dc5606173c06d6e446baa4246ef0960f49a3549f7434593a0590` |
| `audit.py (v1.0 참고)` | v1.0 꾸러미 · `WhyMath_constitution/scripts/constitution/audit.py` | `19310f7cfb51dbda73f850c9387d8f7af77facfc20cf10778b9936d5802134c4` |
| `pipeline_check.py` | v1.0 꾸러미 · `WhyMath_constitution/scripts/constitution/pipeline_check.py` | `b30aecc195d047519d9a374d73c21f5986a5f2eac9a4618d496abae545e8d980` |
| `merge_rules.py` | v1.1 갱신 꾸러미(최상위) · `WhyMath_constitution_v1.1_update/merge_rules.py` | `a0200dc928adacf7da8aaadbea83065ed3dee8516f499d6b7b8423692444c827` |
| `pipeline.yaml (제안본)` | v1.0 꾸러미 · `WhyMath_constitution/pipeline.yaml` | `28a3f75e5b6e719a32adcb9c8286937c938e6f3c5edf2c0fafbdbd17612844f1` |
| `rules_additions_v1.1.yaml` | v1.1 갱신 꾸러미 · `WhyMath_constitution_v1.1_update/rules_additions_v1.1.yaml` | `a506d734e22f255400e3a0e18ec9e0d4d684f6d75fb973aa13eee5b131bcbeb6` |
| `A0002 초안` | v1.1 갱신 꾸러미 · `WhyMath_constitution_v1.1_update/A0002_파트II-VII규칙_초안.md` | `dc36c9c8e6c59b5f026b479881ef0c4d7f571edc504466dcc9fa268c3059e242` |

## 로컬 패치 목록 (코드에는 `# whymath 패치(CONST-02):` 주석으로 표시)

| 파일 | 패치 | 왜 |
|---|---|---|
| `audit.py` | ⓐ `--stage N` 미리보기 | 단계를 올리기 전에 무엇이 켜지는지 STAGE 파일을 고치지 않고 본다 |
| `audit.py` | ⓑ L4·L5 규칙의 `run`이 비면 '집행 장치 없음'(차단) | 원본은 `"" in 워크플로텍스트`가 항상 참이라 '연결됨'으로 보고 실행 없이 '통과'였다(주입 실측) |
| `audit.py` | ⓒ 외부 원본 `version`의 자리표시자("확인 후 기입" 등)는 위반 | 원본은 `bool(version)`만 봐서 자리표시자가 ✅로 나왔다 |
| `audit.py` | ⓓ `--json FILE` 결과 출력 | 래칫이 한국어 표를 긁지 않고 읽는다(출력 문구가 바뀌어도 판정이 안 깨진다) |
| `audit.py` | ⓔ 심사 불가는 모드와 무관하게 exit 2 | 원본은 일반 모드에서 1로 끝나 '위반'과 '심사 불가'가 같은 코드였다 |
| `audit.py` | 예외 메시지에 타입명 병기 | CLAUDE.md '침묵 실패 금지' — 예외 타입명을 남긴다 |
| `pipeline_check.py` | `--direct-upstream-of TARGET:NODE` | 원본 `--upstream-of`는 추이적이라 우회 간선이 있어도 통과했다(주입 실측) |
| `pipeline_check.py` | 노드 0개·설정 오류는 exit 2 | '0건 통과' 위장 금지 |
| `merge_rules.py` | 줄 단위 `rules:` 탐색 · `--bump-stage-note` · 경로 안내 | 원본은 CRLF·뒤 공백에서 IndexError, 머리말 단계 표기는 손편집을 요구했다 |
| `merge_rules.py` | `--apply` 는 AI 세션(`CLAUDECODE`)에서 exit 3 거부 | 가드 훅은 명령 문자열만 보므로 '스크립트가 constitution/ 에 쓰는' 경로를 못 본다 — 제9조 이중 방어 |

## 이 저장소가 새로 만든 도구

| 파일 | 역할 |
|---|---|
| `audit_ratchet.py` | 위헌 심사 래칫 — 기준선(`metrics/coding_constitution_audit_baseline.json`)에 없는 차단 사유가 생기면 exit 1 · CI harness-integrity 잡 |
| `selftest_guard.py` | 규칙 R0-01의 run — `.claude/hooks/guard_constitution.py`를 픽스처로 실행(차단·통과 양방향) |
| `diag/` | 260927 EOS 통합정밀진단 묶음의 진단 도구 벤더링(`diag/UPSTREAM.md`) |
| `run_baseline.py` | 진단 도구 일괄 실행 러너(출력은 gitignore된 `work/diag/`) |
| `adopt_amendment.py` | **사람 전용** 개정 채택 도우미 — A0003(원본 등록부 절만 교체·규칙 불변 단언·단계 1칸 상향)·A0002(조문 삽입 제안본·규칙 병합). UTF-8(BOM 없음)·LF로만 쓰고, AI 세션에서는 `--apply` 거부(exit 3) |

## Kiki가 새 꾸러미를 주면 — 재동기화 절차

1. 새 원본의 sha256을 위 표와 비교한다. 같으면 할 일이 없다.
2. 다르면 원본을 이 폴더에 덮어쓰지 말고 차이(diff)를 읽는다. 위 패치 목록의 각 항목이 새 원본에서
   이미 고쳐졌는지 확인하고, 남은 패치만 다시 적용한다.
3. `ruff check scripts`·`black --check --line-length 100 scripts`·`python3 -m pytest tests/infra -k coding_constitution` 를 돌려
   exit code 0을 확인한다.
4. 이 표의 sha256과 패치 목록을 갱신하고, 결정 로그(MEMORY.md)에 한 줄 남긴다.

`constitution/` 폴더 자체는 이 절차의 대상이 아니다 — 헌법 원문은 사람(Kiki)만 바꾼다(제9조·제11조).
