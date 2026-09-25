import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from dateutil import parser as date_parser

from ..config.manager import ConfigManager
from ..utils.formatters import print_info, print_error, print_warning, print_success


class ReminderService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        data_dir: Path = config_manager.data_dir
        self.db_path = data_dir / "reminders.db"
        self._ensure_schema()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    calendar_id TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    offset_minutes INTEGER NOT NULL,
                    notify_cli INTEGER NOT NULL,
                    notify_desktop INTEGER NOT NULL,
                    notify_email INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def schedule_reminders(self, event: Dict[str, Any], calendar_id: str, offsets_minutes: List[int], notify_cli: bool, notify_desktop: bool, notify_email: bool) -> None:
        if not offsets_minutes:
            return
        start_value = event.get("start")
        if not start_value:
            return
        start_dt = date_parser.parse(start_value)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(start_dt.tzinfo)
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            for offset in offsets_minutes:
                scheduled_at = start_dt - timedelta(minutes=offset)
                if scheduled_at < now:
                    continue
                cur.execute(
                    """
                    INSERT INTO reminders (
                        event_id,
                        calendar_id,
                        scheduled_at,
                        offset_minutes,
                        notify_cli,
                        notify_desktop,
                        notify_email,
                        created_at,
                        status,
                        attempts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.get("id"),
                        calendar_id,
                        scheduled_at.isoformat(),
                        int(offset),
                        1 if notify_cli else 0,
                        1 if notify_desktop else 0,
                        1 if notify_email else 0,
                        now.isoformat(),
                        "pending",
                        0,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_due_reminders(self, now: Optional[datetime] = None, limit: int = 50) -> List[Dict[str, Any]]:
        current = now or datetime.utcnow()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, event_id, calendar_id, scheduled_at, offset_minutes,
                       notify_cli, notify_desktop, notify_email, status, attempts
                FROM reminders
                WHERE status = 'pending'
                  AND attempts < 3
                ORDER BY scheduled_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
            reminders = []
            for row in rows:
                try:
                    scheduled_at = date_parser.parse(row[3])
                    if scheduled_at.tzinfo is None:
                        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
                    if scheduled_at > current:
                        continue
                except Exception:
                    scheduled_at = None
                reminders.append(
                    {
                        "id": row[0],
                        "event_id": row[1],
                        "calendar_id": row[2],
                        "scheduled_at": row[3],
                        "offset_minutes": row[4],
                        "notify_cli": bool(row[5]),
                        "notify_desktop": bool(row[6]),
                        "notify_email": bool(row[7]),
                        "status": row[8],
                        "attempts": row[9],
                    }
                )
            return reminders
        finally:
            conn.close()

    def mark_sent(self, reminder_id: int) -> None:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE reminders
                SET status = 'sent',
                    sent_at = ?,
                    attempts = attempts + 1,
                    error = NULL
                WHERE id = ?
                """,
                (datetime.utcnow().isoformat(), reminder_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, reminder_id: int, error_message: str) -> None:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE reminders
                SET status = CASE WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                    attempts = attempts + 1,
                    error = ?
                WHERE id = ?
                """,
                (error_message, reminder_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _send_cli_notification(self, summary: str, scheduled_at: str, offset_minutes: int) -> None:
        message = f"Reminder: {summary} in {offset_minutes} minutes (scheduled at {scheduled_at})"
        print_success(message)

    def _send_desktop_notification(self, summary: str, offset_minutes: int) -> None:
        try:
            from plyer import notification

            notification.notify(
                title="Calendar Reminder",
                message=f"{summary} in {offset_minutes} minutes",
                timeout=10,
            )
        except Exception:
            print_warning("Desktop notifications are not available on this system")

    def _send_email_notification(self, summary: str, scheduled_at: str, offset_minutes: int) -> None:
        cfg = self.config_manager.config.notifications
        if not cfg.smtp_server:
            print_warning("SMTP server is not configured for email notifications")
            return
        to_address = cfg.from_email or cfg.smtp_username
        if not to_address:
            print_warning("No recipient email configured for notifications")
            return
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = f"Calendar reminder: {summary}"
            msg["From"] = cfg.from_email or cfg.smtp_username
            msg["To"] = to_address
            body = f"Reminder: {summary} in {offset_minutes} minutes (scheduled at {scheduled_at})"
            msg.set_content(body)

            with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port) as server:
                if cfg.use_tls:
                    server.starttls()
                if cfg.smtp_username:
                    server.login(cfg.smtp_username, cfg.smtp_password)
                server.send_message(msg)
        except Exception as e:
            raise RuntimeError(str(e))

    def dispatch_reminder(self, reminder: Dict[str, Any], event_summary: str) -> None:
        reminder_id = reminder["id"]
        scheduled_at = reminder["scheduled_at"]
        offset_minutes = reminder["offset_minutes"]
        try:
            cfg = self.config_manager.config.notifications
            if reminder["notify_cli"] and cfg.cli_enabled:
                self._send_cli_notification(event_summary, scheduled_at, offset_minutes)
            if reminder["notify_desktop"] and cfg.desktop_enabled:
                self._send_desktop_notification(event_summary, offset_minutes)
            if reminder["notify_email"] and cfg.email_enabled:
                self._send_email_notification(event_summary, scheduled_at, offset_minutes)
            self.mark_sent(reminder_id)
        except Exception as e:
            self.mark_failed(reminder_id, str(e))
            print_error(f"Failed to send notification: {e}")
