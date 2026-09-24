#!/usr/bin/env bash
# =============================================================================
# Carreb Excel Synchronization Runner & Cron Executor
# =============================================================================
# Usage:
#   ./carreb_crontab.sh all               # Run all 29 sheet sync commands via master
#   ./carreb_crontab.sh sheet <sheet_num> # Run specific sheet command (e.g. 05, 10)
#   ./carreb_crontab.sh dry-run           # Run all commands in dry-run mode
# =============================================================================

set -e

# Base directories
PROJECT_DIR="/home/ali/Carreb-backend"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"
LOG_DIR="${PROJECT_DIR}/logs/cron_sync"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "${LOG_DIR}"

export DJANGO_SETTINGS_MODULE="config.settings.base"
export PYTHONUNBUFFERED=1
cd "${PROJECT_DIR}"

MODE="${1:-all}"
TARGET="${2:-}"

case "${MODE}" in
  all)
    echo "[$(date)] Starting Master Sheet Sync (All 29 Sheets)..."
    ${VENV_PYTHON} manage.py sync_all_sheets >> "${LOG_DIR}/sync_master_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Master Sheet Sync Completed. Log: ${LOG_DIR}/sync_master_${TIMESTAMP}.log"
    ;;
  dry-run)
    echo "[$(date)] Starting Master Sheet Sync in DRY-RUN mode..."
    ${VENV_PYTHON} manage.py sync_all_sheets --dry-run >> "${LOG_DIR}/sync_dry_run_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Dry-run completed. Log: ${LOG_DIR}/sync_dry_run_${TIMESTAMP}.log"
    ;;
  sheet)
    if [ -z "${TARGET}" ]; then
      echo "Error: Please specify sheet number (e.g. ./carreb_crontab.sh sheet 08)"
      exit 1
    fi
    CMD_NAME=$(find apps/vehicles/management/commands/ -name "sync_sheet_${TARGET}*.py" -exec basename {} .py \;)
    if [ -z "${CMD_NAME}" ]; then
      echo "Error: Command for sheet '${TARGET}' not found."
      exit 1
    fi
    echo "[$(date)] Running ${CMD_NAME}..."
    ${VENV_PYTHON} manage.py "${CMD_NAME}" >> "${LOG_DIR}/${CMD_NAME}_${TIMESTAMP}.log" 2>&1
    echo "[$(date)] Finished ${CMD_NAME}. Log: ${LOG_DIR}/${CMD_NAME}_${TIMESTAMP}.log"
    ;;
  *)
    echo "Usage: $0 {all|dry-run|sheet <sheet_num>}"
    exit 1
    ;;
esac
