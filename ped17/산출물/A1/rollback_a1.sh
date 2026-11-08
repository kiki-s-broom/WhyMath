#!/bin/bash
# PED-17 A1 마이그레이션 되돌리기 — 내보내기가 검증되지 않으면 downgrade를 실행하지 않는다.
#
# 이 스크립트가 지우는 것: 두 기록 테이블(concept_state_transition, concept_exposure_event)과
# concept_content의 두 컬럼(lifecycle_status, content_origin). 지우기 전에 두 테이블을 CSV로,
# concept_content를 pg_dump로 내보내고, 내보낸 행 수가 DB와 같은지 확인한다. 하나라도 어긋나면 멈춘다.
#
# 실행 위치: src/backend (alembic.ini가 있는 폴더)
# 필요한 환경변수(비밀번호를 파일에 적지 않으려고 표준 libpq 변수를 쓴다):
#   PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD
# 선택: OUT_DIR(내보내기 폴더), PYTHON(alembic을 실행할 파이썬, 기본 python3)
set -euo pipefail

for v in PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD; do
  [ -n "${!v:-}" ] || { echo "환경변수 $v 가 비었다 — 중단"; exit 1; }
done
OUT_DIR="${OUT_DIR:-$HOME/ped17_a1_rollback_$(date +%Y%m%d_%H%M%S)}"
PYTHON="${PYTHON:-python3}"

# 실행 위치 확인 — alembic.ini가 있는 src/backend에서 실행해야 한다.
[ -f alembic.ini ] || { echo "src/backend 폴더에서 실행하라(alembic.ini 없음) — 중단"; exit 1; }

# 0) 지금 head가 b1a4d7c92e05인지 확인한다. 아니면 되돌릴 대상이 아니다.
HEAD_NOW=$(psql -At -c "select version_num from alembic_version")
[ "$HEAD_NOW" = "b1a4d7c92e05" ] || { echo "현재 head가 b1a4d7c92e05가 아니다($HEAD_NOW) — 중단"; exit 1; }

# 1) 내보내기 — 하나라도 실패하면 set -e가 여기서 멈춘다(downgrade까지 가지 않는다).
mkdir -p "$OUT_DIR"
psql -c "\copy concept_state_transition TO '$OUT_DIR/concept_state_transition.csv' CSV HEADER"
psql -c "\copy concept_exposure_event TO '$OUT_DIR/concept_exposure_event.csv' CSV HEADER"
pg_dump -t concept_content -Fc -f "$OUT_DIR/concept_content.dump"

# 2) 검증 — 파일의 행 수(헤더 제외, 따옴표 안 줄바꿈 처리)가 DB 행 수와 같아야 한다.
for t in concept_state_transition concept_exposure_event; do
  db_rows=$(psql -At -c "select count(*) from $t")
  file_rows=$("$PYTHON" -c "import csv,sys; print(sum(1 for _ in csv.reader(open(sys.argv[1], encoding='utf-8'))) - 1)" "$OUT_DIR/$t.csv")
  [ "$db_rows" = "$file_rows" ] || { echo "내보내기 불일치: $t DB=$db_rows 파일=$file_rows — downgrade 중단"; exit 1; }
  echo "내보내기 확인: $t ${db_rows}행"
done
[ -s "$OUT_DIR/concept_content.dump" ] || { echo "concept_content 백업이 비었다 — downgrade 중단"; exit 1; }

# 3) alembic용 접속 문자열을 조립한다(사용자·비밀번호는 퍼센트 인코딩).
ALEMBIC_URL=$("$PYTHON" -c 'import os,urllib.parse as u; e=os.environ; q=lambda k: u.quote(e[k], safe=""); print("postgresql+asyncpg://%s:%s@%s:%s/%s" % (q("PGUSER"), q("PGPASSWORD"), e["PGHOST"], e["PGPORT"], q("PGDATABASE")))')

# 4) 여기까지 통과했을 때만 되돌린다.
WHYMATH_DATABASE_URL="$ALEMBIC_URL" "$PYTHON" -m alembic downgrade a8c4e1f7b3d9
echo "되돌리기 완료: head=$(psql -At -c 'select version_num from alembic_version')"
echo "내보내기 위치: $OUT_DIR"
