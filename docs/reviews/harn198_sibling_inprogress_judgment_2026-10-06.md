# HARN-198 설계 판정 — done이 claim을 놓고 기록이 보이기까지의 착수 공백

> 판정 기준: main `ee0389982` (2026-10-06). 이 문서가 서술하는 코드는 모두 그 시점 main 기준이며,
> 구현은 같은 PR(브랜치 `claude/gallant-euler-blngpj`)에 있다. 미머지 근거는 쓰지 않았다.

## 1. 무엇이 일어났나 (acceptance ① 요약)

2026-09-29 `S4-11-hint-content-generation`이 두 세션에서 같은 슬라이스로 구현됐다.

- 먼저 끝낸 세션: 04:17:49 start → 07:24:36 `done`(원격 claim 즉시 해제) → done 기록이 원격에 오른 것은
  08:10:31. 그 사이 46분 동안 그 브랜치의 **원격 사본은 `in_progress`** 였다.
- 늦게 온 세션: 07:29:15 start. 원격 claim `ok`(대장이 비어 있었다). 약 1시간 반을 구현한 뒤, 다른 목적의
  점검에서 우연히 이미 머지된 것을 보고 폐기했다.

## 2. 왜 못 막았나 — 착수 차단 세 겹이 전부 비는 창

| 겹 | 무엇을 보나 | 그 창에서 |
|---|---|---|
| ⑴ 원격 claim 대장 | `harness-claims` 브랜치의 claim 파일 | `done`이 즉시 걷어 **비어 있다** |
| ⑵ 트렁크 사본 | `requires_gates`·`depends_on` | 그 태스크는 트렁크에서 그냥 `todo` |
| ⑶ 미머지 done | 다른 브랜치 사본의 `status: done` | 사본은 아직 `in_progress`라 **못 본다** |

읽기측 탐지 `scan_remote_in_progress`는 이 신호(형제 사본의 `in_progress`)를 읽을 수 있었다. 그러나
`cmd_start`에서 **원격 claim(CAS)이 offline/error일 때만** 호출된다. 이 사고는 CAS가 *성공한* 정상
환경에서 났으므로 그 코드는 한 번도 불리지 않았다. 확인(소스를 읽어서 그렇게 보인다 + 신규 테스트의
전제 고정 `test_premise_the_three_existing_layers_are_all_blind`가 세 겹이 비었음을 실제 git으로 확인).

## 3. 후보 판정 (acceptance ③)

| 후보 | 내용 | 판정 |
|---|---|---|
| ⓐ 쓰기측 | `done`이 claim 해제를 done 기록이 원격에 오른 뒤로 미룬다 | **이번엔 채택하지 않음** |
| ⓑ 읽기측 | `start`·`next`·`brief`가 형제 사본의 in_progress/review를 항상 읽는다 | **채택(구현)** |
| ⓒ 둘 다 | | ⓐ를 미뤘으므로 해당 없음 |

**ⓐ를 미룬 이유**

1. 해제를 미루려면 "done 기록이 원격에 올랐다"를 `done` 안에서 확인해야 하는데, 이는 `done`이 push까지
   책임지는 것이다. 이 환경은 push 경로가 프록시 영향을 받아 왔고(HARN-07 이력: `refs/claims/*` push
   상시 403) `done`의 성공 조건에 push를 묶으면 `done`이 네트워크에 종속된다.
2. 해제를 *하지 않는* 쪽(청소 경로의 `task_done`에 맡김)은 push 확인이 필요 없지만, `stale_claims`의
   `task_done`은 **실행 주체의 로컬 백로그**로 판정한다(`remote_claims.py` `stale_claims`). 그 브랜치에서
   `claims reap`을 돌리면 자기 claim을 즉시 지워 공백이 그대로 재현된다. 이를 고치려면 `task_done`의
   판정 기준을 트렁크로 옮겨야 하고, 그것은 HARN-27(자동 청소 안전 범위)의 계약을 바꾸는 별건이다.
3. ⓐ는 "끝낸 세션"의 공백만 닫는다. **start 직후 push한 진행 중 세션**(claim이 어떤 이유로 사라진 경우:
   `branch_gone`·`ttl` 청소·수동 release)은 ⓑ만 닫는다. 읽기측이 두 경우를 모두 덮는다.

재평가 조건: ⓑ 착지 뒤 같은 형태(claim 대장·트렁크·미머지 done이 모두 빈 중복 착수)가 다시 관측되면
ⓐ를 `task_done` 기준 트렁크 이전과 함께 착수한다.

## 4. 오탐 비용 — 실측 (2026-10-06, main `ee0389982` + 원격 브랜치 52개)

새 스캔을 현재 todo 316건 전부에 돌렸다(`ttl_hours=72`, 내 브랜치 제외).

- 소요: **2.7초**(캐시된 ref 기준 — `start`는 직전 fetch에 편승하므로 추가 왕복 0).
- 막는 태스크 **5건**: `EOS-39`·`P3-24`·`QUAL-10`·`QUAL-11`·`S4-01`. 앞의 4건은 세션 브리핑의 원격 claim
  목록과 겹친다(이미 막히는 것을 새 스캔이 다시 지목). **새로 막힌 것은 `S4-01` 1건**이며, 그 브랜치는
  3일 안에 계속 커밋 중이고(슬라이스 3 = #1413) 트렁크 사본은 `todo`로 남아 있다 — 실제로 형제가 진행 중인
  다슬라이스 태스크다(오탐 아님).
- 과탐 방어로 **제외한 것 3건**(전부 `tip_stale` — 팁이 72시간을 넘긴 브랜치).

한계(정직 기술): ① 팁이 72시간 *안*인 방치 브랜치는 과탐한다 — 메시지가 브랜치를 지목하고
`--ignore-remote-claim`으로 넘길 수 있으며 우회는 `start_ignored_sibling_in_progress` 이벤트로 남는다.
`S4-01`은 팁이 66.5시간이라 경계에 가깝다. ② push되지 않은 브랜치는 볼 수 없다 — 이 스캔은 CAS의
원자성을 대체하지 못하는 읽기측 보강이다. ③ PR 열림 여부는 API 의존이라 쓰지 않았다(오프라인·프록시
환경에서 fail-open이 되므로 의도적 미채택 — `backlog.py done`의 PR 증적 검사와 같은 판단).

## 5. 과탐 방어 4종 (구현)

| 규칙 | 사유 코드 | 대조 픽스처 |
|---|---|---|
| 내 세션의 사본 | `own_session` | `test_my_own_session_copy_does_not_block_me` |
| 트렁크가 이미 done/cancelled | `trunk_settled` | `test_task_already_settled_on_trunk_is_residue_not_holder` |
| 트렁크 사본과 같은 상태·같은 session | `trunk_inherited` | `test_state_inherited_from_trunk_is_not_a_claim_by_that_branch` (역: `test_a_different_holder_than_trunk_still_counts`) |
| 팁이 `claim_ttl_hours` 초과 | `tip_stale` | `test_abandoned_branch_past_ttl_does_not_block` (역: `test_same_branch_within_ttl_still_blocks`) |

팁 시각을 못 읽으면 "모른다 ≠ 오래됐다"로 홀더에 센다(`test_unknown_tip_age_counts_as_holder_not_stale`).

## 6. HARN-193(게이트 부착 스캔)과의 대조

두 스캔은 **같은 원격 브랜치 사본을 읽는다.** 둘 다 `cat-file --batch` 한 번으로 (트렁크 + 브랜치) ×
태스크 블롭을 읽고, `start`에서는 `scan_remote_done(fetch=True)`가 최신화한 ref를 공유한다(fetch 1회).
**판정은 합치지 않았다** — 읽는 필드(`requires_gates` 차집합 vs `status`·`session`), 거부 사유, 우회
이벤트(`start_ignored_unmerged_gate_attach` vs `start_ignored_sibling_in_progress`), 과탐 방어 규칙이 서로
달라 합치면 한쪽 수정이 다른 쪽 판정을 흔든다. 합칠 수 있는 것은 블롭 읽기뿐이며, 태스크 1건을 보는
`start`에서는 이득이 없고 후보 전체를 보는 `next`·`brief`에서도 2.7초 안이라 이번엔 공통화하지 않았다.

## 7. 변별력 (acceptance ④)

픽스처는 진짜 git 원격이다. 사고 상태(형제 사본 in_progress · claim 대장 빔 · 트렁크 todo)에서 `start`는
exit 1이고 대장은 그대로이며 브랜치명을 낸다. 대조군은 §5와 같다. 판정 절을 하나씩 제거하는 뮤테이션
**14종 전건 RED**(주입 적용 `count==1`·`원본≠변경` 단언, 바이트 동일 원복 단언). 첫 회차에 M9(팁 시각
불명을 stale로 접는 변형)가 살아남아, 그 절을 밟는 픽스처를 추가한 뒤 RED를 확인했다.

## 8. 집행 지점 (acceptance ⑤ — 정본화와 별항)

| 서빙 경로 | 배선 | 동결 |
|---|---|---|
| `start` | 프리플라이트 0.8 — CAS(`remote_claims.claim`)보다 **앞**에서 항상 실행 | `test_start_scan_is_independent_of_cas_outcome` |
| `next` | 후보 제외 + 판정 불가 경고 | `test_next_excludes_the_task_and_says_why` |
| `brief`(SessionStart) | 후보 제외 + stdout에 이유(훅이 stderr를 버린다) | `test_brief_excludes_the_task_and_says_why_on_stdout` |

세 경로 모두 `inspect.getsource`로 호출 존재를 동결한다(`TestEnforcementWiring`).
