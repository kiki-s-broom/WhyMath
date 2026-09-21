#!/usr/bin/env bash
# PR 자동 재동기화 — merge queue 대체 (HARN-85)
#
# 배경: 브랜치 보호에 `Require branches to be up to date`가 켜져 있고 CI가 20~30분인데
# main은 15~30분마다 전진한다. 30분짜리 게이트는 15~30분 간격의 전진을 산술적으로 이길 수
# 없다(PR #935 재동기화 4회 · PR #952가 CI green 3회를 확보하고도 behind로 3라운드).
# GitHub merge queue가 이 문제를 풀지만 **조직 소유 저장소 전용**이라 이 저장소
# (owner.type=User)에서는 쓸 수 없다 — 근거·실패 경위는 .github/branch-protection-setup.md.
#
# 그래서 보호를 낮추는 대신(strict 해제 아님) **충족을 자동화**한다: auto-merge가 켜져 있고
# behind인 PR만 update-branch로 최신화한다. 사람이 누르던 "Update branch"를 기계가 누른다.
#
# 설계 원칙(CLAUDE.md):
#   · 실패해도 증거가 남는다 — 실패 PR 번호 + **HTTP 응답 본문**을 로그에 남긴다.
#   · 실패 원인이 남는다 — 409(충돌)/403·401(권한)/그 외를 구분해 처분이 다르다.
#   · 측정 실패가 "0건 통과"로 위장되지 않는다 — 목록 조회가 실패하면 exit 1.
#   · 모른다 ≠ 아니다 — mergeStateStatus가 UNKNOWN이면 건드리지 않고 그 사실을 출력한다.
#   · 0건도 읽히게 — 분모(스캔한 PR 수)와 분류별 개수를 항상 요약에 낸다.
#   · 쓸 수 없는 토큰으로는 **쓰지 않는다**(아래 fail-closed) — 반쪽 성공이 더 나쁘다.
#
# 환경변수:
#   REPO              (필수) owner/name
#   GH_TOKEN          (필수) gh가 읽는 토큰
#   RESYNC_TOKEN_KIND (필수) `pat` | `github_token` — 워크플로가 실제로 넘긴 토큰의 종류
#   DRY_RUN           (선택) 1이면 쓰기 생략(읽기만 — 토큰 종류와 무관하게 허용)

# -e는 의도적으로 쓰지 않는다 — 한 PR의 실패가 나머지 PR 처리를 막으면 안 된다.
set -uo pipefail

REPO="${REPO:?REPO 미설정 — owner/name 형식으로 넘겨야 한다}"
DRY_RUN="${DRY_RUN:-0}"

fatal=0
am_on=0
behind_any=0
behind_am=0
updated=0
conflict=0
unknown=0
other_err=0
recheck_calls=0
recheck_resolved=0

echo "── PR 자동 재동기화 (repo=$REPO · dry_run=$DRY_RUN · token=${RESYNC_TOKEN_KIND:-미지정})"

# ⓪ 토큰 위생 사전 검사 (HARN-89) — **어떤 gh 호출보다 먼저**.
#
# 경위: PAT를 시크릿에 붙여넣을 때 끝에 개행이 함께 들어가, 그 값으로 만든 첫 실행이
# Go net/http의 내부 오류 문면(`invalid header field value for "Authorization"`)으로만
# 실패했다. 그 메시지는 처방으로 번역되지 않는다 — 원인 규명에는 Actions 로그에서
# `GH_TOKEN: ***` 다음 줄에 타임스탬프 없는 빈 줄이 있다는, 사람이 스스로 도달하기
# 어려운 단서가 필요했다. 그래서 헤더에 넣기 전에 여기서 형태를 검사해 무엇이
# 잘못됐는지 이름을 붙인다. 토큰 값 자체는 절대 출력하지 않는다(길이·불리언만 —
# CLAUDE.md 시크릿 자가검증 규칙).
#
# 문자 위생(개행·제어문자·비ASCII)은 **토큰 종류 무관 전 실행**에 적용한다 — 헤더에
# 넣을 수 없는 값은 어느 토큰이든 실패한다. 형식 검사(github_pat_ 접두·길이 범위)는
# RESYNC_TOKEN_KIND=pat일 때만 적용한다 — github_token 경로(GITHUB_TOKEN 폴백, ghs_
# 접두)에서는 접두가 다른 것이 정상이다(PR #1062 Codex P2 수용 — acceptance ④).
raw_token="${GH_TOKEN:-}"
if [ -z "$raw_token" ]; then
  echo "::error::GH_TOKEN 위생 검사 실패 — 값이 비어 있다. gh를 호출하기 전에 멈춘다."
  exit 1
fi

# 앞뒤 공백·개행(스페이스·탭·CR·LF 등)을 제거한다. 조용히 고치지 않는다 — 값이 아니라
# '고쳤다는 사실'만 로그에 남긴다.
trimmed_token="${raw_token#"${raw_token%%[![:space:]]*}"}"
trimmed_token="${trimmed_token%"${trimmed_token##*[![:space:]]}"}"

if [ "$trimmed_token" != "$raw_token" ]; then
  echo "::warning::GH_TOKEN 값의 앞/뒤 공백문자(스페이스·탭·개행 등)를 제거했다 — 시크릿 등록 시"
  echo "함께 붙여넣힌 것으로 보인다(원본 길이=${#raw_token} → 정리 후 길이=${#trimmed_token}). 값 자체는 출력하지 않는다."
fi

if [ -z "$trimmed_token" ]; then
  echo "::error::GH_TOKEN 위생 검사 실패 — 공백만 제거해도 빈 문자열이다(원본 길이=${#raw_token})."
  exit 1
fi

# 남은 이상 — 값 내부의 공백·제어문자·비ASCII. LC_ALL=C는 이 검사에만 한정한다(서브셸)
# — 뒤이은 한국어 로그 출력에 영향을 주지 않기 위함.
if (
  export LC_ALL=C
  [[ "$trimmed_token" == *[[:space:]]* ]] || [[ "$trimmed_token" == *[![:print:]]* ]]
); then
  echo "::error::GH_TOKEN 위생 검사 실패 — 앞뒤 공백 제거 후에도 값 내부에 공백·개행·제어문자·비ASCII"
  echo "문자가 남아 있다(길이=${#trimmed_token}). HTTP 헤더 값에 들어갈 수 없는 문자는 net/http가"
  echo "'invalid header field value'로만 보고한다 — 시크릿을 다시 정확히(따옴표·개행 없이) 등록하라."
  exit 1
fi

if [ "${RESYNC_TOKEN_KIND:-}" = "pat" ]; then
  case "$trimmed_token" in
    github_pat_*) ;;
    *)
      echo "::error::GH_TOKEN 형식 검사 실패 — RESYNC_TOKEN_KIND=pat인데 값이 'github_pat_' 접두로"
      echo "시작하지 않는다(길이=${#trimmed_token}). fine-grained PAT가 아닌 값이 등록됐을 수 있다."
      exit 1
      ;;
  esac
  pat_len=${#trimmed_token}
  if [ "$pat_len" -lt 60 ] || [ "$pat_len" -gt 255 ]; then
    echo "::error::GH_TOKEN 형식 검사 실패 — fine-grained PAT치고 길이가 비정상이다(길이=${pat_len},"
    echo "기대 범위=60~255). 잘리거나 다른 값이 섞여 등록됐을 수 있다."
    exit 1
  fi
fi

if [ "$trimmed_token" != "$raw_token" ]; then
  GH_TOKEN="$trimmed_token"
  export GH_TOKEN
fi

# ① 쓰기 자격 검사 — **어떤 변경보다 먼저**. (Codex P1 · PR #1040)
#
# GITHUB_TOKEN이 만든 push는 workflow를 재발화시키지 않는다(GitHub 문서화 제약).
# 그 토큰으로 update-branch를 하면 브랜치는 최신화되지만 **새 head에 required check가
# 하나도 보고되지 않는다** — strict(up-to-date 강제) 하에서 그 PR은 "체크 대기"로
# 영구히 막힌다. behind는 사람이 Update branch를 눌러 풀 수 있지만(사람 행위는 CI를
# 재발화시킨다), 체크 없는 head는 그 탈출구마저 없앤다. **즉 이 폴백은 아무것도 안
# 하느니만 못하다** — 성공을 보고하면서 PR을 좌초시킨다.
#
# 그래서 fail-open(경고 후 진행)이 아니라 fail-closed(멈춤)로 간다. 이 판단은 제약의
# 성립 여부와 무관하게 옳다: 제약이 없다면 비용은 "PAT를 불필요하게 요구했다" 1회이고,
# 있다면 폴백의 비용은 "좌초된 PR"이다. 비대칭이 크다.
#
# DRY_RUN은 읽기만 하므로 토큰 종류와 무관하게 허용한다 — 배선 확인 경로를 남긴다.
if [ "${RESYNC_TOKEN_KIND:-}" != "pat" ] && [ "$DRY_RUN" != "1" ]; then
  echo "::error::쓰기 자격 없음 — RESYNC_TOKEN_KIND='${RESYNC_TOKEN_KIND:-미지정}' (필요: pat)."
  echo "저장소 시크릿 PR_AUTO_RESYNC_TOKEN(fine-grained PAT · contents:write + pull_requests:write)이"
  echo "설정되지 않았다. GITHUB_TOKEN으로 update-branch를 하면 새 head에 체크가 보고되지 않아"
  echo "PR이 영구히 막히므로, 아무것도 바꾸지 않고 멈춘다(fail-closed). 게이트 G-pr-auto-resync-token."
  exit 1
fi

# ② 목록 조회. 실패는 "대상 0건"과 반드시 구분한다.
payload=$(gh pr list --repo "$REPO" --state open --limit 100 \
  --json number,mergeStateStatus,autoMergeRequest,headRefName 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "::error::PR 목록 조회 실패(exit=$rc) — 이것은 '대상 0건'이 아니라 측정 실패다."
  echo "응답: $payload"
  exit 1
fi

scanned=$(printf '%s' "$payload" | jq 'length' 2>/dev/null)
if [ -z "${scanned:-}" ]; then
  echo "::error::PR 목록 파싱 실패 — gh 출력이 JSON 배열이 아니다."
  echo "응답: $payload"
  exit 1
fi

# ③ 후보 선별 + 처리
#
# UNKNOWN 재조회 (HARN-99) — 일괄 조회(list)는 머지 가능성 계산을 유발하지 않아
# mergeStateStatus가 UNKNOWN으로 오는 경우가 실측상 흔하다(2026-09-08 관측: PR #1059가
# 같은 시각 REST 단건 조회로는 `behind`였다). 단건 조회(`gh pr view`)는 계산을 촉발하고,
# 첫 응답도 미판정이면 짧게 재시도하면 대개 해소된다(이 태스크의 2026-09-10 REST 단건
# 실측 — 같은 저장소 열린 PR 19건 중 최초 조회에서 미판정 6건, 그중 5건이 재조회 1회로
# 해소되고 1건은 2회째도 미판정으로 남았다 — "재조회해도 끝까지 UNKNOWN이면 건드리지
# 않는다" 계약이 실제로 발생하는 입력임을 확인). 비용 절제를 위해 **auto-merge가 켜진
# 후보만** 재조회한다 — 꺼진 PR은 BEHIND로 밝혀져도 어차피 건드리지 않으므로 API
# 호출을 쓸 이유가 없다(같은 실측에서 auto-merge 켜짐 6건 중 미판정은 2건뿐이었다 —
# 재조회 후보를 auto-merge로 좁히지 않았다면 불필요한 호출이 6건이 아니라 19건 규모로
# 늘었을 것).
retry_attempts="${UNKNOWN_RECHECK_ATTEMPTS:-2}"
retry_sleep="${UNKNOWN_RECHECK_SLEEP_SECONDS:-2}"

while IFS= read -r row; do
  [ -z "$row" ] && continue
  n=$(printf '%s' "$row" | jq -r '.number')
  head=$(printf '%s' "$row" | jq -r '.headRefName')
  state=$(printf '%s' "$row" | jq -r '.mergeStateStatus // "UNKNOWN"')
  automerge=$(printf '%s' "$row" | jq -r 'if .autoMergeRequest == null then "off" else "on" end')

  if { [ "$state" = "UNKNOWN" ] || [ -z "$state" ] || [ "$state" = "null" ]; } \
    && [ "$automerge" = "on" ]; then
    attempt=1
    while [ "$attempt" -le "$retry_attempts" ]; do
      recheck_calls=$((recheck_calls + 1))
      view_json=$(gh pr view "$n" --repo "$REPO" --json mergeStateStatus 2>&1)
      view_rc=$?
      if [ "$view_rc" -eq 0 ]; then
        new_state=$(printf '%s' "$view_json" | jq -r '.mergeStateStatus // "UNKNOWN"' 2>/dev/null)
        if [ -n "$new_state" ] && [ "$new_state" != "UNKNOWN" ] && [ "$new_state" != "null" ]; then
          state="$new_state"
          recheck_resolved=$((recheck_resolved + 1))
          break
        fi
      fi
      attempt=$((attempt + 1))
      if [ "$attempt" -le "$retry_attempts" ] && [ "$retry_sleep" != "0" ]; then
        sleep "$retry_sleep"
      fi
    done
  fi

  if [ "$state" = "UNKNOWN" ] || [ -z "$state" ] || [ "$state" = "null" ]; then
    # GitHub이 아직(또는 재조회 후에도) 머지 가능성을 계산하지 않은 상태. 모른다를
    # 아니다로 접지 않는다 — 재조회로도 못 뚫은 것은 기존 계약 그대로 건너뛴다.
    unknown=$((unknown + 1))
    echo "· #$n ($head): mergeStateStatus 미판정 — 이번 주기 건너뜀(모른다 ≠ 아니다)"
    continue
  fi

  # 버리기 **전에** 각 축을 따로 센다 (HARN-87). 원래 이 두 줄은 카운터 없이 곧장
  # continue했고, 그래서 요약의 "BEHIND+auto-merge 0건"이 서로 처방이 다른 세 상태를
  # 한 화면으로 만들었다: ⓐauto-merge를 켠 PR이 아예 없다(자동화가 구조적으로 발화 불가)
  # ⓑBEHIND가 없다(정상 대기) ⓒ둘 다 있으나 서로 다른 PR이다. "알고리즘을 붙였으면 그것이
  # 작동한 비율을 리포트가 말해야 한다"(CLAUDE.md 2026-08-03)의 이 워크플로 축이다.
  [ "$automerge" = "on" ] && am_on=$((am_on + 1))
  [ "$state" = "BEHIND" ] && behind_any=$((behind_any + 1))

  # auto-merge를 켜지 않은 PR은 건드리지 않는다 — 리뷰 중인 diff를 임의로 전진시키지 않기 위함.
  [ "$automerge" != "on" ] && continue
  [ "$state" != "BEHIND" ] && continue

  behind_am=$((behind_am + 1))
  if [ "$DRY_RUN" = "1" ]; then
    echo "· #$n ($head): BEHIND + auto-merge — DRY_RUN이라 update-branch 생략"
    continue
  fi

  body=$(gh api --method PUT "repos/$REPO/pulls/$n/update-branch" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    updated=$((updated + 1))
    echo "✔ #$n ($head): 최신화 완료"
    continue
  fi

  code=$(printf '%s' "$body" | grep -oE 'HTTP [0-9]{3}' | head -1 | awk '{print $2}')
  case "${code:-}" in
    409)
      # 내용 충돌 — 자동 해소 대상이 아니다. 건너뛰되 조용히 넘기지 않는다.
      conflict=$((conflict + 1))
      echo "::warning::#$n ($head) 재동기화 충돌(HTTP 409) — 사람이 해소해야 한다. 응답: $body"
      ;;
    401 | 403)
      # 토큰 권한 부족. 이것을 경고로 넘기면 자동화가 상시 무력인 채 초록으로 보인다.
      fatal=1
      echo "::error::#$n ($head) 권한 거부(HTTP $code) — 자동 재동기화가 무력 상태다. 응답: $body"
      ;;
    *)
      other_err=$((other_err + 1))
      echo "::warning::#$n ($head) 재동기화 실패(HTTP ${code:-미상}·exit=$rc). 응답: $body"
      ;;
  esac
done <<<"$(printf '%s' "$payload" | jq -c '.[]')"

# ④ 요약 — 분모를 항상 낸다. "0건"이 침묵이 아니라 값으로 보여야 한다.
#
# 분모가 세 층이다: 스캔(전체) → 판정(mergeStateStatus를 아는 것) → 각 축(auto-merge·BEHIND)
# → 교집합(실제 대상). 마지막 하나만 내면 0의 의미를 복원할 수 없다.
decided=$((scanned - unknown))
echo "── 요약: 스캔 ${scanned}건 · 판정 ${decided}건 · auto-merge 켜짐 ${am_on}건 · BEHIND ${behind_any}건 ·"
echo "        BEHIND+auto-merge ${behind_am}건 · 최신화 ${updated}건 ·"
echo "        충돌 ${conflict}건 · 미판정 ${unknown}건 · 기타실패 ${other_err}건 ·"
echo "        재조회 ${recheck_calls}건(해소 ${recheck_resolved}건) — HARN-99 API 호출 비용"

# ⑤ 대상이 0건이면 **왜** 0인지 말한다 (HARN-87).
#
# 셋은 처방이 완전히 다르다. ⓐ는 이 자동화가 아무리 자주 돌아도 발화할 수 없다는 뜻이라
# 주기 조정이 아니라 운용 관행(또는 설계)을 바꿔야 하고, ⓑ·ⓒ는 정상 대기다. 이 줄이
# 없으면 ⓐ가 ⓑ처럼 보이고, 그 오독은 "경합이 없어서 안 돌았다"는 잘못된 안심을 만든다.
if [ "$behind_am" -eq 0 ]; then
  if [ "$decided" -eq 0 ]; then
    echo "ⓘ 대상 0건 — 판정된 PR이 0건이다(전부 미판정이거나 열린 PR이 없다). 대상 집합을 아직 모른다."
  elif [ "$am_on" -eq 0 ]; then
    echo "::notice::대상 0건의 원인 = auto-merge를 켠 PR이 하나도 없다(판정 ${decided}건 중 0건)."
    echo "이 자동화는 auto-merge가 켜진 PR만 다루므로, 이 상태에서는 예약이 아무리 자주 돌아도"
    echo "구조적으로 발화하지 않는다 — '경합이 없었다'가 아니라 '대상 집합이 비어 있다'."
  elif [ "$behind_any" -eq 0 ]; then
    echo "ⓘ 대상 0건 — auto-merge 켜짐 ${am_on}건은 있으나 BEHIND가 0건이다. 할 일이 없는 정상 상태."
  else
    echo "ⓘ 대상 0건 — auto-merge 켜짐 ${am_on}건·BEHIND ${behind_any}건이 각각 존재하나 교집합이 없다(서로 다른 PR)."
  fi
fi

exit "$fatal"
