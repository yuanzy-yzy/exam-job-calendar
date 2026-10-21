from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path


MARKER = "[自动采集-央国企]"
REMINDER_OFFSETS = [10080, 4320, 1440, 120]


def data_directory() -> Path:
    configured = os.environ.get("EXAM_JOB_CALENDAR_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    e_drive = Path("E:/")
    if sys.platform == "win32" and e_drive.exists():
        return e_drive / "公考求职日历数据"
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "ExamJobCalendar"


def to_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def same_moment(left: str | None, right: str | None) -> bool:
    """Compare calendar timestamps without treating optional seconds as a change."""
    try:
        return datetime.fromisoformat(left or "") == datetime.fromisoformat(right or "")
    except ValueError:
        return (left or "") == (right or "")


def run() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: update_recruitment_calendar.py events.json")

    payload_path = Path(sys.argv[1])
    items = json.loads(payload_path.read_text(encoding="utf-8"))
    app_dir = data_directory()
    db_path = app_dir / "calendar.db"
    if not db_path.exists():
        raise FileNotFoundError(f"calendar database not found: {db_path}")

    backup_dir = app_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"calendar-before-soe-update-{stamp}.db"

    source = sqlite3.connect(db_path)
    source.execute("PRAGMA busy_timeout=10000")
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()

    now = datetime.now()
    now_text = now.strftime("%Y-%m-%d %H:%M")
    added: list[dict] = []
    updated: list[dict] = []
    skipped: list[dict] = []

    try:
        source.execute("PRAGMA foreign_keys=ON")
        source.execute("BEGIN IMMEDIATE")
        for item in items:
            key = "|".join((item["company"], item["batch"], item["link"]))
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "soe-recruitment:" + key))
            existing = source.execute(
                "SELECT * FROM events WHERE id=?", (event_id,)
            ).fetchone()
            if existing is not None:
                columns = [x[0] for x in source.execute("SELECT * FROM events LIMIT 0").description]
                old = dict(zip(columns, existing))
                if MARKER not in (old.get("notes") or ""):
                    skipped.append({"company": item["company"], "reason": "id belongs to a manual event"})
                    continue
            else:
                old = None

            deadline = to_dt(item["deadline_at"])
            days_left = max(0, (deadline.date() - now.date()).days)
            priority = "高" if deadline - now < timedelta(days=7) else "普通"
            important = int(deadline - now < timedelta(days=30))
            notes = "\n".join(
                [
                    MARKER,
                    f"企业名称：{item['company']}",
                    f"招聘批次：{item['batch']}",
                    f"当前状态：{item['current_status']}",
                    f"开始时间：{item['start_at']}",
                    f"截止时间：{item['deadline_display']}",
                    f"剩余天数：{days_left}天",
                    f"官方来源：{item['source_name']}",
                    f"官方链接：{item['link']}",
                    f"最后核验日期：{now.strftime('%Y-%m-%d')}",
                ]
            )
            title = f"【{item['company']}】{item['batch']}网申截止"
            created_at = old["created_at"] if old else now_text
            values = (
                event_id,
                title,
                "网申截止",
                item["start_at"],
                item["deadline_at"],
                int(item["all_day"]),
                "线上网申",
                item["link"],
                notes,
                priority,
                "待办",
                1,
                json.dumps(REMINDER_OFFSETS, ensure_ascii=False),
                important,
                created_at,
                now_text,
                "",
                old.get("last_overdue_reminded", "") if old else "",
            )
            source.execute(
                """
                INSERT INTO events
                (id,title,type,start_at,deadline_at,all_day,location,link,notes,priority,status,
                 reminder_enabled,reminder_offsets,important,created_at,updated_at,completed_at,last_overdue_reminded)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,type=excluded.type,start_at=excluded.start_at,deadline_at=excluded.deadline_at,
                  all_day=excluded.all_day,location=excluded.location,link=excluded.link,notes=excluded.notes,
                  priority=excluded.priority,status=excluded.status,reminder_enabled=excluded.reminder_enabled,
                  reminder_offsets=excluded.reminder_offsets,important=excluded.important,updated_at=excluded.updated_at
                """,
                values,
            )
            source.execute("DELETE FROM reminders WHERE event_id=?", (event_id,))
            for minutes in REMINDER_OFFSETS:
                remind_at = deadline - timedelta(minutes=minutes)
                fired = int(remind_at <= now)
                source.execute(
                    "INSERT OR IGNORE INTO reminders(event_id,remind_at,fired) VALUES(?,?,?)",
                    (event_id, remind_at.strftime("%Y-%m-%d %H:%M"), fired),
                )

            record = {
                "company": item["company"],
                "batch": item["batch"],
                "start_at": item["start_at"],
                "deadline_at": item["deadline_display"],
                "days_left": days_left,
                "link": item["link"],
            }
            if old is None:
                added.append(record)
            else:
                changed = (
                    not same_moment(old.get("start_at"), item["start_at"])
                    or not same_moment(old.get("deadline_at"), item["deadline_at"])
                    or old.get("link") != item["link"]
                )
                if changed:
                    updated.append(record)

        source.commit()
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        count = source.execute(
            "SELECT COUNT(*) FROM events WHERE instr(notes, ?) > 0", (MARKER,)
        ).fetchone()[0]
    except Exception:
        source.rollback()
        if backup_path.exists():
            source.close()
            shutil.copy2(backup_path, db_path)
        raise
    finally:
        try:
            source.close()
        except Exception:
            pass

    print(
        json.dumps(
            {
                "database": str(db_path),
                "backup": str(backup_path),
                "integrity": integrity,
                "auto_event_count": count,
                "added": added,
                "updated": updated,
                "skipped": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
