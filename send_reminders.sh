#!/bin/bash
# Nightly cron script — sends audition reminder emails for tomorrow's slots.
# Logs output to logs/reminders.log
#
# Suggested cron entry (runs at 6:00 PM every evening):
#   0 18 * * * /bin/bash "/Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python Scripts/Theatre_Info/send_reminders.sh"

PROJECT_DIR="/Users/neillkernohan/Library/CloudStorage/OneDrive-Personal/Python Scripts/Theatre_Info"
FLASK="$PROJECT_DIR/.venv/bin/flask"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/reminders.log"

mkdir -p "$LOG_DIR"

echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---" >> "$LOG_FILE"

cd "$PROJECT_DIR" && \
    FLASK_APP=app.py "$FLASK" send-reminders >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
