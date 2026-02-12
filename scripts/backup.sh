#!/bin/sh
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
BACKUP_FILE="${BACKUP_DIR}/aihm_${TIMESTAMP}.sql.gz"

echo "[$(date)] Starting backup..."

pg_dump -h "$PGHOST" -U "$PGUSER" "$PGDATABASE" | gzip > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Backup OK: $BACKUP_FILE ($SIZE)"
else
    echo "[$(date)] ERROR: Backup failed"
    exit 1
fi

# Cleanup backups older than 7 days
DELETED=$(find "$BACKUP_DIR" -name "aihm_*.sql.gz" -mtime +7 -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] Cleaned up $DELETED old backup(s)"
fi

echo "[$(date)] Backup complete"
