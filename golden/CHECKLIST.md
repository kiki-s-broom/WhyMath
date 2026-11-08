# 골든 패스 체크리스트

학생 경로 여섯 단계가 끝까지 이어지는지 확인하는 목록이다. 칸은 해당 단계를 처음 초록으로 만든 세션이 채운다.

| 단계 | 내용 | 확인 방법 | 상태 | 세션 |
| --- | --- | --- | --- | --- |
| GP-1 | 세션 시작(닉네임만) | `POST /golden/session` 200 | 미완 | |
| GP-2 | 문제 제시(30문항 순서대로) | `GET /golden/next` 200 · `id`가 `LF-`로 시작 | 미완 | |
| GP-3 | 텍스트 답변 | `POST /golden/answer` 본문 수신 | 미완 | |
| GP-4 | 튜터 되묻기(최대 3턴) | 오답에 `kind="tutor_turn"` | 미완 | |
| GP-5 | 정답 판정(SymPy) | 정답에 `kind="graded"`·`correct=true` | 미완 | |
| GP-6 | 숙련도 갱신(+0.10/−0.05) | `mastery > 0.0` · DB `golden.students` 갱신 | 미완 | |
| 전체 | e2e | `cd src/backend && python -m pytest ../../tests/golden` exit 0 | 빨강(S2 의도) | S2 |
