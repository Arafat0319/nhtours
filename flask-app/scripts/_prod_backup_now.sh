#!/bin/bash
set -euo pipefail
SSH=(ssh -i "$HOME/.ssh/nhtours.pem" -o IdentitiesOnly=yes ubuntu@54.69.40.218)
SCP=(scp -i "$HOME/.ssh/nhtours.pem" -o IdentitiesOnly=yes)

# Dump on remote
REMOTE_OUT=$("${SSH[@]}" bash -s <<'REMOTE'
set -euo pipefail
python3 <<'PY'
from pathlib import Path
from urllib.parse import urlparse, unquote
raw = None
for line in Path("/var/www/nhtours/flask-app/.env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        raw = line.split("=", 1)[1].strip().strip("\"'")
        break
if not raw:
    raise SystemExit("DATABASE_URL missing")
u = urlparse(raw.replace("mysql+pymysql://", "mysql://", 1))
user = unquote(u.username or "")
password = unquote(u.password or "")
db = (u.path or "/").lstrip("/") or "nhtours"
host = u.hostname or "localhost"
p = Path("/tmp/.nhtours_mysql_dump.cnf")
p.write_text(f"[client]\nuser={user}\npassword={password}\nhost={host}\n")
p.chmod(0o600)
print(f"dumping db={db} user={user} host={host}", flush=True)
PY
STAMP=$(date -u +%Y%m%d_%H%M%S)
OUT=/tmp/nhtours_prod_prewipe_${STAMP}.sql.gz
# db name from .env may not be nhtours — parse again for mysqldump
DB=$(python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlparse
raw = None
for line in Path("/var/www/nhtours/flask-app/.env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        raw = line.split("=", 1)[1].strip().strip("\"'")
        break
u = urlparse(raw.replace("mysql+pymysql://", "mysql://", 1))
print((u.path or "/").lstrip("/") or "nhtours")
PY
)
mysqldump --defaults-extra-file=/tmp/.nhtours_mysql_dump.cnf \
  --set-gtid-purged=OFF --column-statistics=0 --no-tablespaces \
  --skip-lock-tables --routines --triggers --databases "$DB" | gzip -c > "$OUT"
ls -lh "$OUT"
rm -f /tmp/.nhtours_mysql_dump.cnf
echo "DUMP_PATH=$OUT"
REMOTE
)

echo "$REMOTE_OUT"
DUMP_PATH=$(echo "$REMOTE_OUT" | grep '^DUMP_PATH=' | cut -d= -f2)
if [ -z "$DUMP_PATH" ]; then
  echo "Failed to get dump path" >&2
  exit 1
fi

# Local dest (Windows path via /mnt/e)
LOCAL_DIR="/mnt/e/nh/nhtours-website-main - 副本 - 副本/flask-app/_prod_sync"
mkdir -p "$LOCAL_DIR"
BASE=$(basename "$DUMP_PATH")
"${SCP[@]}" "ubuntu@54.69.40.218:$DUMP_PATH" "$LOCAL_DIR/$BASE"
ls -lh "$LOCAL_DIR/$BASE"
echo "LOCAL=$LOCAL_DIR/$BASE"
# cleanup remote dump? keep for now
"${SSH[@]}" "rm -f '$DUMP_PATH'"
echo BACKUP_DONE
