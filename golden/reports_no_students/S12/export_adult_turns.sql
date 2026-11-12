-- S12: 성인 지인 adult-1·adult-2의 서버 측 대화 기록(golden.turns)을 사람마다 CSV 1개로 뽑는다.
-- 닉네임·session_id 열은 넣지 않는다(공통 규칙 9). 순서는 기록된 순서(id). 열은 S9·S11 CSV와 같다.
-- 컨테이너 안에서 psql -f 로 실행하고, 결과 파일은 docker cp로 꺼낸다(PowerShell이 한글 출력을 거치지 않게).
\copy (SELECT t.id, t.problem_id, t.turn_no, t.kind, t.correct, t.student_text, t.tutor_text, t.created_at FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'adult-1' ORDER BY t.id) TO '/tmp/adult1_turns.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy (SELECT t.id, t.problem_id, t.turn_no, t.kind, t.correct, t.student_text, t.tutor_text, t.created_at FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'adult-2' ORDER BY t.id) TO '/tmp/adult2_turns.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
SELECT 'ROWS_ADULT1=' || count(*) FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'adult-1';
SELECT 'ROWS_ADULT2=' || count(*) FROM golden.turns t JOIN golden.sessions s ON s.session_id = t.session_id WHERE s.nickname = 'adult-2';
