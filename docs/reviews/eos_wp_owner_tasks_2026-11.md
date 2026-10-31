# EOS 감리 WP 소유 태스크 표 (2026-11)

> **판정 기준**: main `3a83ed64` (2026-10-30). 출처 = EOS 감리 이행 지시문 세트 2026-10-30(v3) 레인 01-D(WP-J 후속).
>
> **이 문서가 하는 일**: 남은 감리 WP마다 그 일을 맡은 백로그 태스크 id를 한 곳에 적는다. 다른 레인과 다음 세션이 "이 WP는 누가 하나"를 대장에서 바로 찾게 하는 색인이다. 분류 결정(D13 — 어느 태스크가 12/31 필수인가)은 별도 분류표 `docs/reviews/eos_followup_triage_2026-11.md`(같은 레인의 별도 PR · 이 문서 작성 시점 **미머지**)가 다루며, 이 표는 D13을 기다리지 않는다.
>
> 초안은 독립 검토(읽기 전용 · 결함만)를 한 번 거쳤고, 지적을 정정 항(acceptance append)·등급 조정·게이트 입력으로 반영했다(§4).
>
> **등재 방식**: 새 태스크는 전부 `backlog.py add`로 등재했고(번호는 CLI가 원격 예약으로 확정), 선행 관계는 `depends_on`으로만 집행했다(notes 산문 선행 없음). 게이트 입력 간선은 `backlog.py gates amend --depends`로 붙였다.

## 1. WP별 소유 태스크

"구분"의 신규 = 이 PR에서 등재 · 기존 = 등재 전부터 대장에 있던 태스크.

| WP | 태스크 id | 구분 | EOS 등급 | 내용 |
|---|---|---|---|---|
| WP-K | `EOS-220` | 신규 | P0 | 자동검증 1차 통과율·재작업률을 `metrics/weekly.json`에 measured로 기록 (G4 ≥70% 판정 입력) |
| WP-L | `EOS-221` | 신규 | P1 | Kiki PC(Phaiakes9) 실행 표준 문서 — 저작·검수·측정 런북 공통 실행 규약 색인 |
| WP-L | `EOS-203` | 기존 | P1 | 로컬 좌석 저작 수락률 — 사고 모드 끄기 실측 비교 · Ollama 타임아웃 |
| WP-L | `EOS-204` | 기존 | P1 | 저작 산출물 구조적 중복 사전 차단 |
| WP-L | `EOS-205` | 기존 | P1 | 동등문제 생성기 산출 결함 — 동어반복 검산식 거부 · 정답 키·단원 코드 고정 |
| WP-L | `EOS-209` | 기존 | P1 | 저작 회차 오케스트레이터 보완 · 첫 Windows 실회차 확인 |
| WP-L | `EOS-212` | 기존 | P1 | GenerationLog `error_detail`에서 공급사 응답 본문 제거 |
| WP-E | `EOS-222` | 신규 | P1 | LLM 저작 산출물 8-gram 일치율 기록 (대조 가능한 원본 한정) |
| WP-E | `EOS-223` | 신규 | P1 | KICE 평가기준·성취수준 보고서 라이선스 확인 결과 반영 (근거 없으면 미확인 유지) |
| WP-E | `EOS-224` | 신규 | P1 | 저작권 가이드 Tier 0~3 ↔ `LicenseType` 대응표 + 어긋남 검사 (enums.py 미변경) |
| WP-E | `LIC-08-license-registry-minif2f-label-correction` | 기존 | P2 | license_snapshot_archiver 레지스트리 miniF2F 라벨 정정 |
| WP-F | `EOS-225` | 신규 | P0 | A4(중3 이차방정식) 2회차 LLM 저작 ≥30 CU 산출물·GenerationLog·주간 KPI 커밋 (G4 누적 60 CU) |
| WP-F | `EOS-226` | 신규 | P1 | 사람 단독(AI 보조 없음) 검수 HIT 유효 표본 ≥15 (A4 CU 첫 검수 · G5 F-Ⅰ 입력) |
| WP-F | `EOS-227` | 신규 | P0 | G4 측정 문서 — 조건 5개 실측표 (판정은 Kiki) |
| WP-G | `EOS-228` | 신규 | P1 | G5 증거 문서 `docs/reviews/eos_g5_evidence_2026-12-27.md` · 12/27 데이터 동결 태그 |
| WP-G | `ARCH-67-required-tier-unexercised-watch-r2` | 기존 | P2 | 필수층 미사용 감시 2회차 — G5(12/27) 재확인 |
| WP-H | `EOS-229` | 신규 | P1 | 12/31 내부 완성 판정문 — `G-internal-completion-2026-12-31` 조건 ①②③ 실측 (판정 3택은 Kiki) |

참고: WP-J(11/15 판정 입력 집행)의 대장 변경은 `P3-17-week3-release-gate-judgment`의 `depends_on` 5건이며, PR #1780(**미머지**)이 담고 있다.

ADR-007 결과 절은 WP-F에 '비용'도 넣는다. 비용 KPI(`unit_cost_krw`)는 EOS-197 회차에서 이미 measured로 기록됐고(`metrics/weekly.json` 2026-10-28 레코드), 그 정의 정리(실패 시도 비용 제외 — 약 3.4배 과소)는 기존 `EOS-206`(P2 · 분류표의 2027 이월 제안)이 소유한다. 이 표에 별도 신규 태스크는 두지 않았다.

## 2. 선행 사슬 (대장 `depends_on` 그대로)

- `EOS-225`(A4 2회차 저작) ← `EOS-220`(WP-K) · `EOS-203` · `EOS-204` · `EOS-205` · `EOS-212`
- `EOS-226`(사람 단독 HIT) ← `EOS-225`
- `EOS-227`(G4 측정 문서) ← `EOS-225`
- `EOS-228`(G5 증거) ← `EOS-227` · `EOS-226`
- `EOS-229`(12/31 판정문) ← `EOS-228` · `P3-17-week3-release-gate-judgment`

지시문이 명시한 간선 외에 두 개를 더 붙였다. 이유:
- `EOS-228` ← `EOS-226`: 실패정의 F-Ⅰ(중등 기준선 앵커 A3·A4의 HIT 중앙값 > 12분/CU)은 G5에서 원문 그대로 판정한다(ADR-007 결정 4). A3는 12월에 생산하지 않으므로 A4 사람 단독 HIT가 F-Ⅰ의 유일한 입력이다(앵커 레지스트리 주석: A3·A4 = F-Ⅰ 판정 대상).
- `EOS-229` ← `P3-17-week3-release-gate-judgment`: 12/31 조건 ①(Phase 3 Release Gate A~E PASS)의 판정문이 P3-17 산출물이다. P3-17이 S4라 `EOS-229`도 S4로 두었다(후행 스테이지 의존 금지).

`EOS-209`는 선행으로 걸지 않았다 — 그 태스크 ②(첫 Windows 실회차 확인)는 A4 회차 실행 중에 함께 수행하는 동반 작업이다(`EOS-225` acceptance ④).

## 3. 게이트 입력 간선 (이 PR에서 추가)

| 게이트 | 추가한 입력 | 이유 |
|---|---|---|
| `G-eos-g4` | `EOS-227` · `P3-17-week3-release-gate-judgment` | G4 판정 재료(측정 문서)를 대장 간선으로. 조건 "무개입 루프 3연속"은 Phase 3 Gate A와 같은 회차(ADR-007 결정 3)라 그 판정 회차 P3-17도 잇는다 — 측정 문서 `EOS-227`은 S3라 S4인 P3-17에 직접 의존할 수 없어 게이트(스테이지 제약 없음)에 붙였다. 기존 입력 `EOS-155`(blocked)는 그대로 |
| `G-eos-g5` | `EOS-228` | notes가 증거 문서를 "WP-G"라는 산문으로만 가리키고 있었다(selector는 notes를 읽지 않는다) — 기존 입력 `ARCH-67`은 그대로 |
| `G-internal-completion-2026-12-31` | `EOS-229` | 12/31 판정문(WP-H)을 판정 입력으로 — 기존 입력 `P3-17`은 그대로 |

되돌리려면 `backlog.py gates amend <게이트> --remove-depends <태스크> --reason ...`.

## 4. 알아 둘 점

- **P0는 3건(`EOS-220`·`EOS-225`·`EOS-227`)이다** — G4(12/13) 전에 끝나야 하는 것만 P0로 두었다. 처음엔 6건을 P0로 등재했으나, G4 조건 "P0 결함 0"을 비종결 P0 태스크로 읽으면(종전 `G-internal-completion` ③ 문면이 그렇게 읽은 선례가 있다) G4 판정일 뒤에 끝나는 판정 작업(`EOS-226`·`EOS-228`·`EOS-229`)이 G4를 자동 FAIL로 만들 수 있어 P1로 내렸다. 순서는 등급이 아니라 `depends_on`과 게이트 입력이 집행한다. 등재 전 비종결 P0는 0건이었고 예산은 50건이다(`scripts/harness/models.py` `eos_p0_budget`). "P0 결함"의 집계 기준 자체는 `EOS-227` acceptance ③이 Kiki께 확인한다.
- **P0인 `EOS-225`가 P1 4건(EOS-203·204·205·212)에 막혀 있다** — 등급 정의("P1 = 우회 가능")와 어긋난다. 그 4건의 등급은 D13(분류표) 결정 대상이라 이 PR에서 바꾸지 않았다. G4 판정일(12/13)에서 거꾸로 세면 4건과 WP-K가 11월 안에 끝나야 한다(`EOS-212`는 priority 3이라 `next` 순서가 늦다).
- **`G-eos-g4`의 기존 입력 `EOS-155`는 지금 blocked**다. G4 clear는 입력 전부가 done이어야 통과한다.
- **G4 조건 중 생산 태스크가 없는 것**: "무개입 루프 3연속"은 P3-17 판정 회차에서 나온다(위 게이트 입력). "내부 테스트 계정 표본 ≥20건"을 만드는 태스크는 대장에서 찾지 못했다(EOS-135·EOS-143은 조건 정의뿐 — 내가 찾은 방법으로는 0건). `EOS-227` ⑦은 생산 경로가 없으면 측정 실패로 적게 했다.
- **기존 소유 태스크 중 P2라 `next`에 안 보이는 것**: `ARCH-67`(G5 필수 입력)·`LIC-08`은 P2라 selector가 기본으로 숨긴다(EOS_DEFERRED). ARCH-67은 `G-required-tier-caller-recheck-g5`를 기다리므로 12/27 전에는 어차피 착수할 수 없지만, 등급을 올릴지는 D13에서 함께 볼 일이다.
- **독립 검토 반영 요약**: `EOS-220` ⑥(증적을 `generated_at`으로 고정 — 주간 cron이 매주 measured:false 레코드를 덧붙임) · `EOS-225` ⑥⑦(WP 경계 · 상태 파일 자격증명 grep · 첫 검수는 AI 보조 없이) · `EOS-226` ⑥(첫 검수 HIT만 · 다시 보기 문항 제외) · `EOS-227` ⑤⑥⑦(Wilson 하한 판정 · 레지스트리 depth 플래그는 A4뿐 · 생산 경로 공백) · `EOS-228` ⑤⑥(EOS-61 판정 실행기 `validation_scorecard.py` 사용 · ARCH-67을 선행으로 걸지 않는 이유) · `EOS-221` paths에 저작 회차 런북 추가.

## 5. 소유 태스크 찾기 (표의 id 실재 확인)

저장소 루트에서 실행한다. 표의 id가 하나라도 대장에 없거나 cancelled이면 `MISSING <id>` 또는 `CANCELLED <id>`를 내고 exit 1, 전부 살아 있으면 id별 상태·등급과 `ALL_FOUND`를 내고 exit 0이다(서브셸이라 붙여넣어도 셸이 닫히지 않는다).

```bash
(for id in EOS-220 EOS-221 EOS-203 EOS-204 EOS-205 EOS-209 EOS-212 EOS-222 EOS-223 EOS-224 LIC-08-license-registry-minif2f-label-correction EOS-225 EOS-226 EOS-227 EOS-228 ARCH-67-required-tier-unexercised-watch-r2 EOS-229; do
  python3 -c "
import glob, sys, yaml
i = sys.argv[1]
f = glob.glob(f'backlog/tasks/{i}.yaml') + glob.glob(f'backlog/tasks/{i}-*.yaml')
if not f:
    print('MISSING', i); sys.exit(1)
t = yaml.safe_load(open(f[0], encoding='utf-8'))
if t['status'] == 'cancelled':
    print('CANCELLED', i); sys.exit(1)
print(i, t['status'], t.get('eos_priority'))
" "$id" || exit 1
done; echo "ALL_FOUND"); echo "EXIT=$?"
```
