-- S9: 닉네임 self-1의 서버 측 대화 기록(golden.turns)을 CSV로 뽑는다.
-- 닉네임·session_id 열은 넣지 않는다(지시서 할 일 3 · 공통 규칙 9). 순서는 기록된 순서(id).
-- 컨테이너 안에서 psql -f 로 실행하고, 결과 파일은 docker cp로 꺼낸다(PowerShell이 한글 출력을 거치지 않게).
\copy (SELECT t.id, t.problem_id, t.turn_no, t.kind, t.correct, t.student_text, t.tutor_text, t.created_at FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'self-1' ORDER BY t.id) TO '/tmp/self1_turns.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
SELECT 'ROWS=' || count(*) FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'self-1';
