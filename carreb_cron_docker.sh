#!/usr/bin/env bash
# =============================================================================
# Carreb Production Docker Cron Executor
# =============================================================================
# Usage:
#   ./carreb_cron_docker.sh all               # Run all 29 sheets via Docker
#   ./carreb_cron_docker.sh dry-run           # Run all sheets in dry-run mode
#   ./carreb_cron_docker.sh sheet <sheet_num> # Run specific sheet (e.g. 05, 18)
# =============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.prod.yml"
LOG_DIR="${PROJECT_DIR}/logs/cron_sync"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "${LOG_DIR}"

MODE="${1:-all}"
TARGET="${2:-}"

case "${MODE}" in
  all)
    echo "[$(date)] Starting Master Sheet Sync via Docker..."
    docker compose -f "${COMPOSE_FILE}" exec -T web python manage.py sync_all_sheets >> "${LOG_DIR}/sync_master_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Master Sheet Sync Completed. Log: ${LOG_DIR}/sync_master_${TIMESTAMP}.log"
    ;;
  dry-run)
    echo "[$(date)] Starting Master Sheet Sync in DRY-RUN mode via Docker..."
    docker compose -f "${COMPOSE_FILE}" exec -T web python manage.py sync_all_sheets --dry-run >> "${LOG_DIR}/sync_dry_run_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Dry-run completed. Log: ${LOG_DIR}/sync_dry_run_${TIMESTAMP}.log"
    ;;
  sheet)
    if [ -z "${TARGET}" ]; then
      echo "Error: Please specify sheet number (e.g. ./carreb_cron_docker.sh sheet 05)"
      exit 1
    fi
    SHEET_PADDED=$(printf "%02d" "$((10#${TARGET}))")
    CMD_NAME=$(find "${PROJECT_DIR}/apps/vehicles/management/commands/" -name "sync_sheet_${SHEET_PADDED}*.py" -exec basename {} .py \;)
    if [ -z "${CMD_NAME}" ]; then
      echo "Error: Command for sheet '${TARGET}' not found."
      exit 1
    fi
    echo "[$(date)] Running ${CMD_NAME} via Docker..."
    docker compose -f "${COMPOSE_FILE}" exec -T web python manage.py "${CMD_NAME}" >> "${LOG_DIR}/${CMD_NAME}_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Finished ${CMD_NAME}. Log: ${LOG_DIR}/${CMD_NAME}_${TIMESTAMP}.log"
    ;;
  *)
    echo "Usage: $0 {all|dry-run|sheet <sheet_num>}"
    exit 1
    ;;
esac
