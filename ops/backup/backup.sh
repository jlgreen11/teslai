#!/usr/bin/env bash
# teslai database backups.
#   backup.sh once     dump now, prune dumps older than KEEP_DAYS
#   backup.sh verify   restore the newest dump into a scratch database, compare row counts
#   backup.sh loop     dump every INTERVAL_SECONDS, verify every VERIFY_EVERY dumps
# Dumps land in BACKUP_DIR as teslai-<UTC timestamp>.dump (pg_dump custom format).
# Offsite copies are not handled here; copy BACKUP_DIR elsewhere (docs/runbooks/deploy.md).
set -euo pipefail

export PGHOST="${PGHOST:-db}" PGUSER="${PGUSER:-teslai}" PGDATABASE="${PGDATABASE:-teslai}"
export PGPASSWORD="${PGPASSWORD:?PGPASSWORD is required}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-86400}"
VERIFY_EVERY="${VERIFY_EVERY:-7}"
SCRATCH_DB="teslai_restore_check"
TABLES="vehicles sessions telemetry_events connectivity_events api_usage"

log() { echo "$(date -u +%FT%TZ) backup: $*"; }

once() {
  mkdir -p "$BACKUP_DIR"
  local ts tmp final
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$BACKUP_DIR/.teslai-$ts.dump.partial"
  final="$BACKUP_DIR/teslai-$ts.dump"
  pg_dump -Fc -f "$tmp"
  mv "$tmp" "$final"
  find "$BACKUP_DIR" -maxdepth 1 -name 'teslai-*.dump' -mtime +"$KEEP_DAYS" -delete
  log "wrote $(basename "$final") ($(du -h "$final" | cut -f1))"
}

verify() {
  local latest status="ok" details=""
  latest="$(ls -1t "$BACKUP_DIR"/teslai-*.dump 2>/dev/null | head -1 || true)"
  if [ -z "$latest" ]; then
    log "no dump to verify"; status="failed"; details="no dump found"
  else
    dropdb --if-exists "$SCRATCH_DB"
    createdb "$SCRATCH_DB"
    if ! pg_restore --no-owner -d "$SCRATCH_DB" "$latest" 2>"$BACKUP_DIR/.restore.log"; then
      if grep -qv "extension\|already exists\|COMMENT" "$BACKUP_DIR/.restore.log"; then
        status="failed"; details="pg_restore errors; see .restore.log"
      fi
    fi
    for t in $TABLES; do
      live="$(psql -tAc "SELECT count(*) FROM $t")"
      restored="$(psql -d "$SCRATCH_DB" -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo missing)"
      details="$details $t=$restored/$live"
      if [ "$restored" = "missing" ] || { [ "$live" -gt 0 ] && [ "$restored" -eq 0 ]; }; then
        status="failed"
      fi
    done
    dropdb --if-exists "$SCRATCH_DB"
  fi
  printf '{"verified_at": "%s", "dump": "%s", "status": "%s", "tables": "%s"}\n' \
    "$(date -u +%FT%TZ)" "$(basename "${latest:-none}")" "$status" "${details# }" \
    > "$BACKUP_DIR/last-verify.json"
  log "verify $status:$details"
  [ "$status" = "ok" ]
}

case "${1:-loop}" in
  once) once ;;
  verify) verify ;;
  loop)
    n=0
    while true; do
      once || log "dump failed"
      n=$((n + 1))
      if [ $((n % VERIFY_EVERY)) -eq 1 ]; then verify || log "verify failed"; fi
      sleep "$INTERVAL_SECONDS"
    done
    ;;
  *) echo "usage: backup.sh once|verify|loop" >&2; exit 2 ;;
esac
