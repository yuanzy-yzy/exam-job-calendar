from __future__ import annotations

import csv
import ctypes
import json
import os
import re
import shutil
import sqlite3
import sys
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    from PySide6.QtCore import QByteArray, QDate, QDateTime, QEvent, QObject, QPoint, QRect, QSize, QTime, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QFont, QIcon, QPainter, QPalette
    from PySide6.QtWidgets import (
        QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
        QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
        QMenu, QMessageBox, QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
        QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton,
        QVBoxLayout, QWidget
    )
    QT_BINDING = "PySide6"
except ImportError:
    from PyQt5.QtCore import QByteArray, QDate, QDateTime, QEvent, QObject, QPoint, QRect, QSize, QTime, Qt, QTimer, pyqtSignal as Signal
    from PyQt5.QtGui import QColor, QCloseEvent, QDesktopServices, QFont, QIcon, QPainter, QPalette
    from PyQt5.QtWidgets import (
        QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
        QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
        QMenu, QMessageBox, QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
        QStyle, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton,
        QVBoxLayout, QWidget
    )
    QT_BINDING = "PyQt5"


APP_NAME = "公考与求职截止日历"
LEGACY_APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ExamJobCalendar"


def default_app_dir() -> Path:
    configured = os.environ.get("EXAM_JOB_CALENDAR_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    e_drive = Path("E:/")
    if sys.platform == "win32" and e_drive.exists():
        return e_drive / "公考求职日历数据"
    return LEGACY_APP_DIR


APP_DIR = default_app_dir()
DB_PATH = APP_DIR / "calendar.db"
SETTINGS_PATH = APP_DIR / "settings.json"
BACKUP_DIR = APP_DIR / "backups"
LOG_PATH = APP_DIR / "calendar.log"

EVENT_TYPES: dict[str, str] = {
    "公务员考试": "#7c3aed", "报名开始": "#0ea5e9", "报名截止": "#ef4444",
    "缴费截止": "#f97316", "准考证打印": "#06b6d4", "笔试": "#8b5cf6",
    "面试": "#a855f7", "资格复审": "#6366f1", "体检": "#14b8a6",
    "政审": "#64748b", "简历投递截止": "#dc2626", "网申截止": "#e11d48",
    "宣讲会": "#16a34a", "笔试确认": "#d97706", "其他": "#475569",
}
PRIORITIES = ["低", "普通", "高", "紧急"]
STATUSES = ["待办", "进行中", "已完成", "已取消"]
DEFAULT_SETTINGS = {
    "widget_visible": True,
    "widget_locked": False,
    "widget_opacity": 0.96,
    "autostart": False,
    "theme": "system",
    "font_auto": True,
    "font_size": 12,
    "overdue_remind": True,
    "last_backup": "",
    "widget_geometry": "",
    "main_splitter_sizes": [180, 900, 340],
}


_DATA_DIR_READY = False


def ensure_dirs() -> None:
    global _DATA_DIR_READY
    APP_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if _DATA_DIR_READY or APP_DIR == LEGACY_APP_DIR or not LEGACY_APP_DIR.exists():
        _DATA_DIR_READY = True
        return
    try:
        legacy_db = LEGACY_APP_DIR / "calendar.db"
        if legacy_db.exists() and not DB_PATH.exists():
            source = sqlite3.connect(legacy_db)
            target = sqlite3.connect(DB_PATH)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        for name in ("settings.json", "calendar.log"):
            source_file = LEGACY_APP_DIR / name
            target_file = APP_DIR / name
            if source_file.exists() and not target_file.exists():
                shutil.copy2(source_file, target_file)
        legacy_backups = LEGACY_APP_DIR / "backups"
        if legacy_backups.exists():
            for source_file in legacy_backups.glob("*.db"):
                target_file = BACKUP_DIR / source_file.name
                if not target_file.exists():
                    shutil.copy2(source_file, target_file)
    finally:
        _DATA_DIR_READY = True


def log_error(exc: BaseException) -> None:
    ensure_dirs()
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] {exc}\n")
        f.write(traceback.format_exc())


def dt_to_text(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def text_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def display_dt(value: str, all_day: bool = False) -> str:
    dt = text_to_dt(value)
    if not dt:
        return "未设置"
    return dt.strftime("%m月%d日" if all_day else "%m月%d日 %H:%M")


def qdatetime_to_python(value: QDateTime) -> datetime:
    return value.toPython() if hasattr(value, "toPython") else value.toPyDateTime()


def mouse_local_y(event) -> int:
    point = event.position() if hasattr(event, "position") else event.pos()
    return int(point.y())


def mouse_global_point(event) -> QPoint:
    point = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
    return point


def countdown_text(value: str) -> str:
    target = text_to_dt(value)
    if not target:
        return ""
    delta = target - datetime.now()
    seconds = int(delta.total_seconds())
    if seconds < 0:
        days = abs(seconds) // 86400
        return f"已逾期 {days} 天" if days else "已逾期"
    if seconds < 86400:
        hours = max(1, seconds // 3600)
        return f"剩余 {hours} 小时"
    return f"剩余 {seconds // 86400 + (1 if seconds % 86400 else 0)} 天"


def event_due(event: dict[str, Any]) -> datetime | None:
    return text_to_dt(event.get("deadline_at")) or text_to_dt(event.get("start_at"))


def is_overdue(event: dict[str, Any]) -> bool:
    due = event_due(event)
    return bool(due and due < datetime.now() and event.get("status") not in ("已完成", "已取消"))


DATE_TOKEN = r"(?:(?:20\d{2})年)?(?:1[0-2]|0?[1-9])月(?:3[01]|[12]\d|0?[1-9])日(?:\s*(?:[01]?\d|2[0-3])\s*(?:(?::|时|点)\s*(?:[0-5]?\d)?\s*分?)?)?"


def normalize_chinese_text(text: str) -> str:
    return (text or "").replace("∶", ":").replace("：", ":").replace("—", "-").replace("－", "-").replace("﹒", "。")


def parse_chinese_datetime(token: str, default_year: int, deadline: bool = False) -> tuple[datetime | None, bool]:
    token = normalize_chinese_text(token).strip()
    match = re.search(
        r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})\s*(?:(?::|时|点)\s*(\d{1,2})?\s*分?)?)?",
        token,
    )
    if not match:
        return None, False
    year = int(match.group(1) or default_year)
    hour_text = match.group(4)
    minute_text = match.group(5)
    explicit_time = hour_text is not None
    hour = int(hour_text) if explicit_time else (23 if deadline else 0)
    minute = int(minute_text or 0) if explicit_time else (59 if deadline else 0)
    try:
        return datetime(year, int(match.group(2)), int(match.group(3)), hour, minute), explicit_time
    except ValueError:
        return None, False


def extract_first_link(text: str) -> str:
    match = re.search(r"https?://[^\s，。；;）)]+", text, re.I)
    if match:
        return match.group(0)
    match = re.search(r"(?<![@\w])(?:[a-z0-9-]+\.)+(?:gov\.cn|com\.cn|com|cn)(?:/[^\s，。；;）)]*)?", text, re.I)
    return "https://" + match.group(0) if match else ""


def extract_smart_events(text: str, title_prefix: str = "") -> list[dict[str, Any]]:
    """Parse common Chinese recruitment/exam time nodes locally with deterministic rules."""
    clean = normalize_chinese_text(text)
    explicit_year = re.search(r"(20\d{2})年", clean)
    base_year = int(explicit_year.group(1)) if explicit_year else datetime.now().year
    title_prefix = title_prefix.strip().strip("·-— ")
    link = extract_first_link(clean)
    candidates: list[dict[str, Any]] = []

    def title_for(label: str) -> str:
        return f"{title_prefix} · {label}" if title_prefix else label

    def add_candidate(
        event_type: str,
        label: str,
        start: datetime,
        deadline: datetime | None = None,
        all_day: bool = True,
        confidence: int = 1,
    ) -> None:
        due = deadline or start
        delta = due - datetime.now()
        candidates.append({
            "title": title_for(label),
            "type": event_type if event_type in EVENT_TYPES else "其他",
            "start_at": dt_to_text(start),
            "deadline_at": dt_to_text(deadline),
            "all_day": all_day,
            "location": "线上" if event_type in ("报名开始", "报名截止", "缴费截止", "网申截止", "简历投递截止", "准考证打印") else "",
            "link": link,
            "notes": "[智能识别导入]\n" + text.strip(),
            "priority": "高" if timedelta(0) <= delta < timedelta(days=7) else "普通",
            "status": "待办",
            "important": timedelta(0) <= delta < timedelta(days=30),
            "confidence": confidence,
        })

    deadline_specs = (
        ("报名截止", "报名截止", r"报名(?:的)?(?:截止时间|截止日期|截止)"),
        ("缴费截止", "缴费截止", r"缴费(?:的)?(?:截止时间|截止日期|截止)"),
        ("网申截止", "网申截止", r"网申(?:的)?(?:截止时间|截止日期|截止)"),
        ("简历投递截止", "简历投递截止", r"简历投递(?:的)?(?:截止时间|截止日期|截止)"),
        ("笔试确认", "笔试确认截止", r"笔试确认(?:的)?(?:截止时间|截止日期|截止)"),
    )
    for event_type, label, keyword in deadline_specs:
        pattern = re.compile(rf"{keyword}\s*(?:为|是|:)?\s*(?P<date>{DATE_TOKEN})")
        for match in pattern.finditer(clean):
            value, has_time = parse_chinese_datetime(match.group("date"), base_year, deadline=True)
            if value:
                add_candidate(event_type, label, value, value, not has_time, 3)

    timed_specs = (
        ("笔试", "笔试", r"(?:笔试|素质测试)"),
        ("面试", "面试", r"面试"),
        ("资格复审", "资格复审", r"资格复审"),
        ("体检", "体检", r"体检"),
        ("政审", "政审", r"政审"),
    )
    for event_type, label, keyword in timed_specs:
        pattern = re.compile(rf"{keyword}[^。；;\n]{{0,60}}?(?:时间|日期)\s*(?:为|是|:)?\s*(?P<date>{DATE_TOKEN})")
        for match in pattern.finditer(clean):
            value, has_time = parse_chinese_datetime(match.group("date"), base_year)
            if value:
                add_candidate(event_type, label, value, None, not has_time, 3)

    range_pattern = re.compile(
        rf"(?P<prefix>[^。；;\n]{{0,55}}?)(?P<start>{DATE_TOKEN})\s*(?:至|到|-)\s*(?P<end>{DATE_TOKEN})(?P<suffix>[^。；;\n]{{0,55}})"
    )
    for match in range_pattern.finditer(clean):
        context = match.group("prefix") + match.group("suffix")
        start, start_has_time = parse_chinese_datetime(match.group("start"), base_year)
        if not start:
            continue
        end, end_has_time = parse_chinese_datetime(match.group("end"), start.year, deadline=True)
        if not end:
            continue
        if end < start and "年" not in match.group("end"):
            try:
                end = end.replace(year=end.year + 1)
            except ValueError:
                continue
        if "准考证" in context or "打印" in context:
            add_candidate("准考证打印", "准考证打印", start, end, not (start_has_time or end_has_time), 2)
        elif any(word in context for word in ("报名", "报考", "填报", "登录")):
            add_candidate("报名开始", "报名开始", start, None, not start_has_time, 2)
            add_candidate("报名截止", "报名截止", end, end, not end_has_time, 1)
        elif "缴费" in context:
            add_candidate("缴费截止", "缴费截止", end, end, not end_has_time, 1)

    start_pattern = re.compile(rf"(?:报名|网申|填报)[^。；;\n]{{0,25}}?(?:开始时间|开始日期|自)\s*(?:为|是|:)?\s*(?P<date>{DATE_TOKEN})")
    for match in start_pattern.finditer(clean):
        value, has_time = parse_chinese_datetime(match.group("date"), base_year)
        if value:
            add_candidate("报名开始", "报名开始", value, None, not has_time, 3)

    # Keep the most precise result for the same kind of node on the same day.
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        due_text = item.get("deadline_at") or item["start_at"]
        key = (item["type"], due_text[:10])
        previous = merged.get(key)
        if previous is None or item["confidence"] > previous["confidence"]:
            merged[key] = item
    result = sorted(merged.values(), key=lambda item: item["start_at"])
    for item in result:
        item.pop("confidence", None)
    return result


class Settings:
    def __init__(self) -> None:
        ensure_dirs()
        self.data = dict(DEFAULT_SETTINGS)
        try:
            if SETTINGS_PATH.exists():
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
        except Exception as exc:
            log_error(exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        SETTINGS_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


class Database:
    def __init__(self) -> None:
        ensure_dirs()
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                start_at TEXT NOT NULL,
                deadline_at TEXT,
                all_day INTEGER NOT NULL DEFAULT 0,
                location TEXT DEFAULT '',
                link TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                priority TEXT NOT NULL DEFAULT '普通',
                status TEXT NOT NULL DEFAULT '待办',
                reminder_enabled INTEGER NOT NULL DEFAULT 0,
                reminder_offsets TEXT NOT NULL DEFAULT '[]',
                important INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                last_overdue_reminded TEXT
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0,
                UNIQUE(event_id, remind_at),
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at);
            CREATE INDEX IF NOT EXISTS idx_events_deadline ON events(deadline_at);
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(fired, remind_at);
            """
        )
        self.conn.commit()

    @staticmethod
    def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["all_day"] = bool(item.get("all_day"))
        item["reminder_enabled"] = bool(item.get("reminder_enabled"))
        item["important"] = bool(item.get("important"))
        try:
            item["reminder_offsets"] = json.loads(item.get("reminder_offsets") or "[]")
        except json.JSONDecodeError:
            item["reminder_offsets"] = []
        return item

    def list_events(self, include_cancelled: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events"
        if not include_cancelled:
            sql += " WHERE status <> '已取消'"
        sql += " ORDER BY COALESCE(NULLIF(deadline_at,''), start_at), priority DESC"
        return [self.row_to_dict(r) for r in self.conn.execute(sql).fetchall()]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return self.row_to_dict(row) if row else None

    def save_event(self, data: dict[str, Any]) -> str:
        now = dt_to_text(datetime.now())
        event_id = data.get("id") or str(uuid.uuid4())
        existing = self.get_event(event_id)
        created = existing.get("created_at") if existing else now
        completed = data.get("completed_at")
        if data.get("status") == "已完成" and not completed:
            completed = now
        if data.get("status") != "已完成":
            completed = ""
        values = (
            event_id, data["title"].strip(), data["type"], data["start_at"], data.get("deadline_at", ""),
            int(bool(data.get("all_day"))), data.get("location", "").strip(), data.get("link", "").strip(),
            data.get("notes", "").strip(), data.get("priority", "普通"), data.get("status", "待办"),
            int(bool(data.get("reminder_enabled"))), json.dumps(data.get("reminder_offsets", [])),
            int(bool(data.get("important"))), created, now, completed, data.get("last_overdue_reminded", ""),
        )
        self.conn.execute(
            """INSERT INTO events
            (id,title,type,start_at,deadline_at,all_day,location,link,notes,priority,status,
             reminder_enabled,reminder_offsets,important,created_at,updated_at,completed_at,last_overdue_reminded)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,type=excluded.type,start_at=excluded.start_at,deadline_at=excluded.deadline_at,
              all_day=excluded.all_day,location=excluded.location,link=excluded.link,notes=excluded.notes,
              priority=excluded.priority,status=excluded.status,reminder_enabled=excluded.reminder_enabled,
              reminder_offsets=excluded.reminder_offsets,important=excluded.important,updated_at=excluded.updated_at,
              completed_at=excluded.completed_at,last_overdue_reminded=excluded.last_overdue_reminded""",
            values,
        )
        self.rebuild_reminders(event_id, data)
        self.conn.commit()
        return event_id

    def rebuild_reminders(self, event_id: str, data: dict[str, Any]) -> None:
        self.conn.execute("DELETE FROM reminders WHERE event_id=?", (event_id,))
        if not data.get("reminder_enabled") or data.get("status") in ("已完成", "已取消"):
            return
        target = text_to_dt(data.get("deadline_at")) or text_to_dt(data.get("start_at"))
        if not target:
            return
        for minutes in sorted(set(int(x) for x in data.get("reminder_offsets", []))):
            remind_at = target - timedelta(minutes=minutes)
            self.conn.execute(
                "INSERT OR IGNORE INTO reminders(event_id,remind_at,fired) VALUES(?,?,0)",
                (event_id, dt_to_text(remind_at)),
            )

    def delete_event(self, event_id: str) -> None:
        self.conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        self.conn.commit()

    def set_status(self, event_id: str, status: str) -> None:
        event = self.get_event(event_id)
        if not event:
            return
        event["status"] = status
        self.save_event(event)

    def due_reminders(self) -> list[dict[str, Any]]:
        now = dt_to_text(datetime.now())
        rows = self.conn.execute(
            """SELECT r.id AS reminder_id, e.* FROM reminders r
               JOIN events e ON e.id=r.event_id
               WHERE r.fired=0 AND r.remind_at<=? AND e.status NOT IN ('已完成','已取消')
               ORDER BY r.remind_at LIMIT 20""", (now,)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            result.append(item)
            self.conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (item["reminder_id"],))
        self.conn.commit()
        return result

    def overdue_for_reminder(self) -> list[dict[str, Any]]:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        result = []
        for event in self.list_events(False):
            if not event.get("reminder_enabled") or not is_overdue(event):
                continue
            if (event.get("last_overdue_reminded") or "")[:10] == today:
                continue
            result.append(event)
            self.conn.execute(
                "UPDATE events SET last_overdue_reminded=? WHERE id=?", (dt_to_text(now), event["id"])
            )
        self.conn.commit()
        return result

    def backup(self, destination: Path | None = None) -> Path:
        destination = destination or BACKUP_DIR / f"calendar_{datetime.now():%Y%m%d_%H%M%S}.db"
        target = sqlite3.connect(destination)
        self.conn.backup(target)
        target.close()
        return destination

    def restore(self, source: Path) -> None:
        check = sqlite3.connect(source)
        table = check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
        check.close()
        if not table:
            raise ValueError("所选文件不是有效的日历数据库备份。")
        self.conn.close()
        shutil.copy2(source, DB_PATH)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init_schema()

    def export_json(self, path: Path) -> None:
        payload = {"app": APP_NAME, "version": 1, "exported_at": dt_to_text(datetime.now()), "events": self.list_events()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_json(self, path: Path) -> int:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("events", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("JSON 中没有有效的 events 数组")
        count = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("title") or not item.get("start_at"):
                continue
            item["id"] = item.get("id") or str(uuid.uuid4())
            self.save_event(item)
            count += 1
        return count


class SmartImportDialog(QDialog):
    imported = Signal(int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.events: list[dict[str, Any]] = []
        self.setWindowTitle("智能识别时间节点")
        self.resize(980, 680)
        self.setMinimumSize(760, 560)
        self.build_ui()

    def build_ui(self) -> None:
        root = QVBoxLayout(self)
        intro = QLabel("粘贴公告或招聘信息，程序会在本机识别报名、缴费、准考证、笔试、面试等时间节点。内容不会上传。")
        intro.setWordWrap(True)
        root.addWidget(intro)

        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("事项名称前缀（可选）"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("例如：江苏省选调生；识别结果会显示为“江苏省选调生 · 报名截止”")
        prefix_row.addWidget(self.prefix_edit, 1)
        root.addLayout(prefix_row)

        self.source_edit = QTextEdit()
        self.source_edit.setPlaceholderText("请粘贴包含日期的公告正文……")
        self.source_edit.setMinimumHeight(175)
        root.addWidget(self.source_edit)

        action_row = QHBoxLayout()
        recognize = QPushButton("识别时间节点")
        recognize.setObjectName("primaryButton")
        recognize.clicked.connect(self.recognize)
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: (self.source_edit.clear(), self.table.setRowCount(0)))
        self.reminder_enabled = QCheckBox("导入后启用提醒（提前1天、2小时）")
        self.reminder_enabled.setChecked(True)
        action_row.addWidget(recognize)
        action_row.addWidget(clear)
        action_row.addStretch()
        action_row.addWidget(self.reminder_enabled)
        root.addLayout(action_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["导入", "类型", "标题", "开始时间", "截止时间", "全天"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        hint = QLabel("识别结果可直接双击修改。请核对标题和时间后再导入；无法明确判断的日期不会自动写入。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("导入勾选事项")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.import_selected)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.source_edit.setFocus()

    def recognize(self) -> None:
        source = self.source_edit.toPlainText().strip()
        if not source:
            QMessageBox.warning(self, "没有内容", "请先粘贴需要识别的公告或招聘信息。")
            return
        self.events = extract_smart_events(source, self.prefix_edit.text())
        self.table.setRowCount(0)
        for event in self.events:
            row = self.table.rowCount()
            self.table.insertRow(row)
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            checked.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, checked)
            values = [
                event["type"], event["title"], event["start_at"][:16],
                (event.get("deadline_at") or "")[:16], "是" if event.get("all_day") else "否",
            ]
            for col, value in enumerate(values, 1):
                self.table.setItem(row, col, QTableWidgetItem(value))
        if not self.events:
            QMessageBox.information(self, "未识别到节点", "没有找到足够明确的时间节点。请保留“报名截止、缴费截止、笔试时间”等关键词后重试。")

    def import_selected(self) -> None:
        if not self.events or self.table.rowCount() == 0:
            QMessageBox.warning(self, "没有识别结果", "请先点击“识别时间节点”。")
            return
        selected: list[dict[str, Any]] = []
        errors: list[str] = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            event = dict(self.events[row])
            event_type = (self.table.item(row, 1).text() if self.table.item(row, 1) else "其他").strip()
            event["type"] = event_type if event_type in EVENT_TYPES else "其他"
            event["title"] = (self.table.item(row, 2).text() if self.table.item(row, 2) else "").strip()
            start_text = (self.table.item(row, 3).text() if self.table.item(row, 3) else "").strip()
            deadline_text = (self.table.item(row, 4).text() if self.table.item(row, 4) else "").strip()
            start = text_to_dt(start_text)
            deadline = text_to_dt(deadline_text) if deadline_text else None
            if not event["title"] or not start or (deadline_text and not deadline):
                errors.append(str(row + 1))
                continue
            event["start_at"] = dt_to_text(start)
            event["deadline_at"] = dt_to_text(deadline)
            all_day_text = (self.table.item(row, 5).text() if self.table.item(row, 5) else "否").strip().lower()
            event["all_day"] = all_day_text in ("是", "true", "1", "yes", "全天")
            event["reminder_enabled"] = self.reminder_enabled.isChecked()
            event["reminder_offsets"] = [1440, 120] if self.reminder_enabled.isChecked() else []
            selected.append(event)
        if errors:
            QMessageBox.warning(self, "内容有误", f"第 {', '.join(errors)} 行的标题或时间格式不正确，请使用 yyyy-MM-dd HH:mm 格式。")
            return
        if not selected:
            QMessageBox.warning(self, "没有勾选", "请至少勾选一条要导入的事项。")
            return
        for event in selected:
            self.db.save_event(event)
        self.imported.emit(len(selected))
        QMessageBox.information(self, "导入完成", f"已添加 {len(selected)} 条事项。")
        self.accept()


class EventDialog(QDialog):
    saved = Signal()

    def __init__(self, db: Database, event: dict[str, Any] | None = None, default_date: QDate | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.event = event or {}
        self.setWindowTitle("编辑事项" if event else "新建事项")
        self.setMinimumWidth(560)
        self.build_ui(default_date)
        if event:
            self.load_event(event)

    def build_ui(self, default_date: QDate | None) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("例如：国考报名截止")
        form.addRow("标题 *", self.title_edit)

        row = QHBoxLayout()
        self.type_combo = QComboBox(); self.type_combo.addItems(EVENT_TYPES.keys())
        self.priority_combo = QComboBox(); self.priority_combo.addItems(PRIORITIES); self.priority_combo.setCurrentText("普通")
        self.status_combo = QComboBox(); self.status_combo.addItems(STATUSES)
        row.addWidget(QLabel("类型")); row.addWidget(self.type_combo, 2)
        row.addWidget(QLabel("优先级")); row.addWidget(self.priority_combo)
        row.addWidget(QLabel("状态")); row.addWidget(self.status_combo)
        form.addRow(row)

        self.all_day = QCheckBox("全天事项")
        self.important = QCheckBox("设为重要倒计时")
        flag_row = QHBoxLayout(); flag_row.addWidget(self.all_day); flag_row.addWidget(self.important); flag_row.addStretch()
        form.addRow(flag_row)

        base = default_date or QDate.currentDate()
        default_time = QTime.currentTime(); default_time.setHMS(default_time.hour(), 0, 0)
        self.start_edit = QDateTimeEdit(QDateTime(base, default_time))
        self.start_edit.setCalendarPopup(True); self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.deadline_edit = QDateTimeEdit(QDateTime(base, default_time))
        self.deadline_edit.setCalendarPopup(True); self.deadline_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.has_deadline = QCheckBox("设置截止时间"); self.has_deadline.setChecked(True)
        deadline_row = QHBoxLayout(); deadline_row.addWidget(self.has_deadline); deadline_row.addWidget(self.deadline_edit, 1)
        form.addRow("开始时间", self.start_edit)
        form.addRow("截止时间", deadline_row)
        self.has_deadline.toggled.connect(self.deadline_edit.setEnabled)

        self.location_edit = QLineEdit(); self.location_edit.setPlaceholderText("线上或具体地点")
        self.link_edit = QLineEdit(); self.link_edit.setPlaceholderText("https://...")
        form.addRow("地点", self.location_edit); form.addRow("链接", self.link_edit)

        self.reminder_enabled = QCheckBox("启用提醒")
        reminder_box = QGroupBox("提醒设置")
        reminder_layout = QVBoxLayout(reminder_box); reminder_layout.addWidget(self.reminder_enabled)
        preset_row = QHBoxLayout()
        self.reminder_checks: dict[int, QCheckBox] = {}
        for minutes, label in ((10080, "提前7天"), (4320, "提前3天"), (1440, "提前1天"), (120, "提前2小时"), (30, "提前30分钟"), (0, "截止时")):
            check = QCheckBox(label); self.reminder_checks[minutes] = check; preset_row.addWidget(check)
        reminder_layout.addLayout(preset_row)
        custom_row = QHBoxLayout(); self.custom_enabled = QCheckBox("自定义提前")
        self.custom_value = QSpinBox(); self.custom_value.setRange(1, 999); self.custom_value.setValue(4)
        self.custom_unit = QComboBox(); self.custom_unit.addItems(["分钟", "小时", "天"])
        custom_row.addWidget(self.custom_enabled); custom_row.addWidget(self.custom_value); custom_row.addWidget(self.custom_unit); custom_row.addStretch()
        reminder_layout.addLayout(custom_row)
        form.addRow(reminder_box)

        self.notes_edit = QTextEdit(); self.notes_edit.setPlaceholderText("资格要求、材料清单、联系人等"); self.notes_edit.setFixedHeight(90)
        form.addRow("备注", self.notes_edit)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.title_edit.setFocus()

    def load_event(self, event: dict[str, Any]) -> None:
        self.title_edit.setText(event.get("title", "")); self.type_combo.setCurrentText(event.get("type", "其他"))
        self.priority_combo.setCurrentText(event.get("priority", "普通")); self.status_combo.setCurrentText(event.get("status", "待办"))
        self.all_day.setChecked(bool(event.get("all_day"))); self.important.setChecked(bool(event.get("important")))
        start = text_to_dt(event.get("start_at")) or datetime.now(); self.start_edit.setDateTime(QDateTime(start))
        deadline = text_to_dt(event.get("deadline_at")); self.has_deadline.setChecked(bool(deadline))
        if deadline: self.deadline_edit.setDateTime(QDateTime(deadline))
        self.deadline_edit.setEnabled(bool(deadline))
        self.location_edit.setText(event.get("location", "")); self.link_edit.setText(event.get("link", "")); self.notes_edit.setPlainText(event.get("notes", ""))
        self.reminder_enabled.setChecked(bool(event.get("reminder_enabled")))
        offsets = [int(x) for x in event.get("reminder_offsets", [])]
        for minutes, check in self.reminder_checks.items(): check.setChecked(minutes in offsets)
        custom = [x for x in offsets if x not in self.reminder_checks]
        if custom:
            self.custom_enabled.setChecked(True); value = custom[0]
            if value % 1440 == 0: self.custom_value.setValue(value // 1440); self.custom_unit.setCurrentText("天")
            elif value % 60 == 0: self.custom_value.setValue(value // 60); self.custom_unit.setCurrentText("小时")
            else: self.custom_value.setValue(value); self.custom_unit.setCurrentText("分钟")

    def accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "缺少标题", "请输入事项标题。"); self.title_edit.setFocus(); return
        start = qdatetime_to_python(self.start_edit.dateTime())
        deadline = qdatetime_to_python(self.deadline_edit.dateTime()) if self.has_deadline.isChecked() else None
        if deadline and deadline < start:
            answer = QMessageBox.question(self, "时间确认", "截止时间早于开始时间，仍然保存吗？")
            if answer != QMessageBox.Yes: return
        offsets = [m for m, check in self.reminder_checks.items() if check.isChecked()]
        if self.custom_enabled.isChecked():
            multiplier = {"分钟": 1, "小时": 60, "天": 1440}[self.custom_unit.currentText()]
            offsets.append(self.custom_value.value() * multiplier)
        data = dict(self.event)
        data.update({
            "title": self.title_edit.text(), "type": self.type_combo.currentText(),
            "start_at": dt_to_text(start), "deadline_at": dt_to_text(deadline), "all_day": self.all_day.isChecked(),
            "location": self.location_edit.text(), "link": self.link_edit.text(), "notes": self.notes_edit.toPlainText(),
            "priority": self.priority_combo.currentText(), "status": self.status_combo.currentText(),
            "reminder_enabled": self.reminder_enabled.isChecked(), "reminder_offsets": offsets,
            "important": self.important.isChecked(),
        })
        self.db.save_event(data); self.saved.emit(); super().accept()


class EventChip(QFrame):
    changed = Signal()

    def __init__(self, db: Database, event: dict[str, Any], compact: bool = True, parent=None):
        super().__init__(parent)
        self.db = db; self.event = event
        color = "#dc2626" if is_overdue(event) else EVENT_TYPES.get(event.get("type", "其他"), "#64748b")
        rgb = QColor(color)
        self.setObjectName("eventChip")
        self.setStyleSheet(
            f"QFrame#eventChip{{border-left:3px solid {color};"
            f"background:rgba({rgb.red()},{rgb.green()},{rgb.blue()},26);border-radius:5px;}}"
        )
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        row = QHBoxLayout(self); row.setContentsMargins(5, 3, 3, 3); row.setSpacing(4)
        done = QCheckBox(); done.setChecked(event.get("status") == "已完成"); done.setToolTip("标记完成")
        done.toggled.connect(self.toggle_done); row.addWidget(done)
        action_width = round(32 * max(1.0, min(1.35, getattr(QApplication.instance(), "current_font_pt", 12) / 12)))
        edit = QToolButton(); edit.setObjectName("eventAction"); edit.setFixedWidth(action_width); edit.setText("✎"); edit.setToolTip("编辑"); edit.clicked.connect(self.edit_event); row.addWidget(edit)
        delete = QToolButton(); delete.setObjectName("eventAction"); delete.setFixedWidth(action_width); delete.setText("×"); delete.setToolTip("删除"); delete.clicked.connect(self.delete_event); row.addWidget(delete)
        title = event["title"]
        if not compact:
            due = text_to_dt(event.get("deadline_at") or event.get("start_at"))
            if due:
                short_date = due.strftime("%m/%d" if event.get("all_day") else "%m/%d %H:%M")
                title = f"{short_date} · {title}"
        label = QLabel(title); label.setTextInteractionFlags(Qt.TextSelectableByMouse); label.setToolTip(self.tooltip_text()); label.setWordWrap(not compact)
        label.setContextMenuPolicy(Qt.CustomContextMenu)
        label.customContextMenuRequested.connect(lambda point, source=label: self.show_context_menu(source.mapTo(self, point)))
        if compact:
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(title) + 12)
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        else:
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if event.get("status") == "已完成": label.setStyleSheet("text-decoration:line-through;color:#7b8794;")
        row.addWidget(label, 1)

    def tooltip_text(self) -> str:
        e = self.event
        parts = [e.get("title", ""), f"类型：{e.get('type','')}", f"状态：{e.get('status','')}", f"开始：{display_dt(e.get('start_at',''), e.get('all_day'))}"]
        if e.get("deadline_at"): parts.append(f"截止：{display_dt(e['deadline_at'], e.get('all_day'))}")
        if e.get("location"): parts.append(f"地点：{e['location']}")
        return "\n".join(parts)

    def toggle_done(self, checked: bool) -> None:
        self.db.set_status(self.event["id"], "已完成" if checked else "待办"); self.changed.emit()

    def edit_event(self) -> None:
        dlg = EventDialog(self.db, self.db.get_event(self.event["id"]), parent=self.window())
        dlg.saved.connect(self.changed); dlg.exec()

    def show_context_menu(self, point: QPoint) -> None:
        menu = QMenu(self)
        edit_action = menu.addAction("编辑事项")
        delete_action = menu.addAction("删除事项")
        chosen = menu.exec(self.mapToGlobal(point))
        if chosen == edit_action:
            self.edit_event()
        elif chosen == delete_action:
            self.delete_event()

    def delete_event(self) -> None:
        if QMessageBox.question(self.window(), "删除事项", f"确定删除“{self.event['title']}”吗？") == QMessageBox.Yes:
            self.db.delete_event(self.event["id"]); self.changed.emit()


class DayCell(QFrame):
    add_requested = Signal(QDate)
    changed = Signal()

    def __init__(self, date: QDate, current_month: int, events: list[dict[str, Any]], parent=None):
        super().__init__(parent); self.date = date
        self.setObjectName("dayCell")
        other = date.month() != current_month
        today = date == QDate.currentDate()
        bg = "#eaf3ff" if today else ("#f3f5f8" if other else "#ffffff")
        border = "2px solid #2563eb" if today else "1px solid #d8dee8"
        self.setStyleSheet(f"QFrame#dayCell{{background:{bg};border:{border};border-radius:5px;}}")
        layout = QVBoxLayout(self); layout.setContentsMargins(5, 4, 5, 4); layout.setSpacing(3)
        top = QHBoxLayout(); number = QLabel(str(date.day())); number.setStyleSheet("font-weight:700;color:#2563eb;" if today else ("color:#9aa4b2;" if other else "font-weight:600;"))
        add = QToolButton(); add.setText("＋"); add.setToolTip("添加事项"); add.clicked.connect(lambda: self.add_requested.emit(self.date))
        top.addWidget(number); top.addStretch(); top.addWidget(add); layout.addLayout(top)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:0;}QScrollArea>QWidget>QWidget{background:transparent;}")
        content = QWidget(); content.setStyleSheet("background:transparent;"); v = QVBoxLayout(content); v.setSizeConstraint(QLayout.SetMinimumSize); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
        for event in events:
            chip = EventChip(self.window().db if hasattr(self.window(), "db") else parent.db, event, True)
            chip.changed.connect(self.changed); v.addWidget(chip)
        v.addStretch(); scroll.setWidget(content); layout.addWidget(scroll, 1)


class MonthView(QWidget):
    changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db = db; now = QDate.currentDate(); self.year = now.year(); self.month = now.month()
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(6)
        nav = QHBoxLayout(); prev = QPushButton("‹ 上月"); today = QPushButton("今天"); nxt = QPushButton("下月 ›")
        self.title = QLabel(); self.title.setObjectName("sectionTitle"); self.title.setAlignment(Qt.AlignCenter)
        prev.clicked.connect(lambda: self.change_month(-1)); nxt.clicked.connect(lambda: self.change_month(1)); today.clicked.connect(self.go_today)
        nav.addWidget(prev); nav.addWidget(today); nav.addStretch(); nav.addWidget(self.title); nav.addStretch(); nav.addWidget(nxt); root.addLayout(nav)
        self.grid = QGridLayout(); self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setSpacing(4)
        root.addLayout(self.grid, 1); self.refresh()

    def clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def refresh(self, events: list[dict[str, Any]] | None = None) -> None:
        events = events if events is not None else self.db.list_events()
        self.clear_grid(); self.title.setText(f"{self.year}年 {self.month}月")
        for col, name in enumerate(("周一", "周二", "周三", "周四", "周五", "周六", "周日")):
            label = QLabel(name); label.setAlignment(Qt.AlignCenter); label.setStyleSheet("font-weight:700;padding:4px;color:#526174;")
            self.grid.addWidget(label, 0, col)
        first = QDate(self.year, self.month, 1); start = first.addDays(-(first.dayOfWeek() - 1))
        by_date: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            start_dt = text_to_dt(event.get("start_at")); due_dt = text_to_dt(event.get("deadline_at"))
            dates = {d.strftime("%Y-%m-%d") for d in (start_dt, due_dt) if d}
            for key in dates: by_date.setdefault(key, []).append(event)
        for index in range(42):
            date = start.addDays(index); key = date.toString("yyyy-MM-dd")
            cell = DayCell(date, self.month, by_date.get(key, []), self)
            cell.add_requested.connect(self.add_event); cell.changed.connect(self.changed)
            self.grid.addWidget(cell, index // 7 + 1, index % 7)
        for row in range(1, 7): self.grid.setRowStretch(row, 1)
        for col in range(7): self.grid.setColumnStretch(col, 1)

    def add_event(self, date: QDate) -> None:
        dlg = EventDialog(self.db, default_date=date, parent=self.window()); dlg.saved.connect(self.changed); dlg.exec()

    def change_month(self, offset: int) -> None:
        d = QDate(self.year, self.month, 1).addMonths(offset); self.year, self.month = d.year(), d.month(); self.refresh()

    def go_today(self) -> None:
        d = QDate.currentDate(); self.year, self.month = d.year(), d.month(); self.refresh()


class WeekView(QWidget):
    changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db = db; self.week_start = QDate.currentDate().addDays(-(QDate.currentDate().dayOfWeek() - 1))
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout(); prev = QPushButton("‹ 上周"); today = QPushButton("本周"); nxt = QPushButton("下周 ›"); self.title = QLabel(); self.title.setObjectName("sectionTitle"); self.title.setAlignment(Qt.AlignCenter)
        prev.clicked.connect(lambda: self.move(-7)); today.clicked.connect(self.go_today); nxt.clicked.connect(lambda: self.move(7))
        nav.addWidget(prev); nav.addWidget(today); nav.addStretch(); nav.addWidget(self.title); nav.addStretch(); nav.addWidget(nxt); root.addLayout(nav)
        self.days = QHBoxLayout(); self.days.setSpacing(5); root.addLayout(self.days, 1); self.refresh()

    def refresh(self, events: list[dict[str, Any]] | None = None) -> None:
        events = events if events is not None else self.db.list_events()
        while self.days.count():
            item = self.days.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        end = self.week_start.addDays(6); self.title.setText(f"{self.week_start.toString('yyyy年M月d日')} - {end.toString('M月d日')}")
        for i in range(7):
            date = self.week_start.addDays(i); key = date.toString("yyyy-MM-dd")
            group = QGroupBox(f"{'一二三四五六日'[i]}\n{date.toString('M/d')}"); v = QVBoxLayout(group)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            content = QWidget(); event_layout = QVBoxLayout(content); event_layout.setSizeConstraint(QLayout.SetMinimumSize)
            event_layout.setContentsMargins(0, 0, 0, 0); event_layout.setSpacing(4)
            matches = [e for e in events if key in ((e.get("start_at") or "")[:10], (e.get("deadline_at") or "")[:10])]
            for event in matches:
                chip = EventChip(self.db, event, True); chip.changed.connect(self.changed); event_layout.addWidget(chip)
            event_layout.addStretch(); scroll.setWidget(content); v.addWidget(scroll, 1)
            add = QPushButton("＋ 添加"); add.clicked.connect(lambda _, d=date: self.add_event(d)); v.addWidget(add); self.days.addWidget(group, 1)

    def add_event(self, date: QDate) -> None:
        dlg = EventDialog(self.db, default_date=date, parent=self.window()); dlg.saved.connect(self.changed); dlg.exec()

    def move(self, days: int) -> None: self.week_start = self.week_start.addDays(days); self.refresh()
    def go_today(self) -> None: self.week_start = QDate.currentDate().addDays(-(QDate.currentDate().dayOfWeek() - 1)); self.refresh()


class AgendaView(QWidget):
    changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db = db
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 7); self.table.setHorizontalHeaderLabels(["完成", "日期", "标题", "类型", "优先级", "状态", "倒计时"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table.doubleClicked.connect(self.edit_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.show_context_menu)
        root.addWidget(self.table); self.refresh()

    def refresh(self, events: list[dict[str, Any]] | None = None) -> None:
        events = events if events is not None else self.db.list_events(); self.table.setRowCount(0)
        for event in events:
            row = self.table.rowCount(); self.table.insertRow(row)
            done = QCheckBox(); done.setChecked(event.get("status") == "已完成"); done.toggled.connect(lambda checked, eid=event["id"]: self.toggle(eid, checked))
            wrap = QWidget(); lay = QHBoxLayout(wrap); lay.setContentsMargins(0,0,0,0); lay.setAlignment(Qt.AlignCenter); lay.addWidget(done); self.table.setCellWidget(row, 0, wrap)
            values = [display_dt(event.get("deadline_at") or event.get("start_at"), event.get("all_day")), event["title"], event["type"], event["priority"], event["status"], countdown_text(event.get("deadline_at") or event.get("start_at"))]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value); item.setData(Qt.UserRole, event["id"])
                if is_overdue(event): item.setForeground(QColor("#dc2626"))
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def toggle(self, event_id: str, checked: bool) -> None: self.db.set_status(event_id, "已完成" if checked else "待办"); self.changed.emit()
    def edit_selected(self) -> None:
        row = self.table.currentRow(); item = self.table.item(row, 1) if row >= 0 else None
        if not item: return
        event = self.db.get_event(item.data(Qt.UserRole)); dlg = EventDialog(self.db, event, parent=self.window()); dlg.saved.connect(self.changed); dlg.exec()

    def show_context_menu(self, point: QPoint) -> None:
        row = self.table.rowAt(point.y())
        if row < 0:
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        edit_action = menu.addAction("编辑事项")
        delete_action = menu.addAction("删除事项")
        chosen = menu.exec(self.table.viewport().mapToGlobal(point))
        if chosen == edit_action:
            self.edit_selected()
        elif chosen == delete_action:
            item = self.table.item(row, 1)
            event = self.db.get_event(item.data(Qt.UserRole)) if item else None
            if event and QMessageBox.question(self, "删除事项", f"确定删除“{event['title']}”吗？") == QMessageBox.Yes:
                self.db.delete_event(event["id"]); self.changed.emit()


class DashboardPanel(QScrollArea):
    changed = Signal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db = db; self.setWidgetResizable(True); self.setFrameShape(QFrame.NoFrame)
        self.content = QWidget(); self.layout = QVBoxLayout(self.content); self.layout.setSizeConstraint(QLayout.SetMinimumSize); self.layout.setContentsMargins(8, 0, 0, 0); self.layout.setSpacing(9); self.setWidget(self.content); self.refresh()

    def clear(self) -> None:
        self.content.setMinimumHeight(0)
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def section(self, title: str) -> QVBoxLayout:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.section_box = box
        self.layout.addWidget(box)
        return v

    def refresh(self, events: list[dict[str, Any]] | None = None) -> None:
        events = events if events is not None else self.db.list_events(False); self.clear(); now = datetime.now(); today = now.strftime("%Y-%m-%d")
        important = [e for e in events if e.get("important") and e.get("status") not in ("已完成", "已取消") and event_due(e)]
        important.sort(key=lambda e: event_due(e) or datetime.max)
        if important:
            v = self.section("重要倒计时")
            e = important[0]; big = QLabel(countdown_text(e.get("deadline_at") or e.get("start_at"))); big.setObjectName("countdownBig"); big.setAlignment(Qt.AlignCenter)
            name = QLabel(e["title"]); name.setAlignment(Qt.AlignCenter); name.setWordWrap(True); v.addWidget(name); v.addWidget(big)
            scale = max(0.9, getattr(QApplication.instance(), "current_font_pt", 12) / 12)
            v.section_box.setMinimumHeight(round(118 * scale))
        today_events = [e for e in events if today in ((e.get("start_at") or "")[:10], (e.get("deadline_at") or "")[:10])]
        v = self.section(f"今日事项 · {len(today_events)}")
        if not today_events: v.addWidget(QLabel("今天暂无事项，可以安心推进计划。"))
        for e in today_events:
            chip = EventChip(self.db, e, False); chip.changed.connect(self.changed); v.addWidget(chip)
        scale = max(0.9, getattr(QApplication.instance(), "current_font_pt", 12) / 12)
        v.section_box.setMinimumHeight(round(max(72, 42 + len(today_events) * 62) * scale))
        upcoming = []
        limit = now + timedelta(days=7)
        for e in events:
            due = event_due(e)
            if due and now <= due <= limit and e.get("status") not in ("已完成", "已取消"): upcoming.append(e)
        upcoming.sort(key=lambda e: event_due(e) or datetime.max)
        v = self.section(f"未来7天 · {len(upcoming)}")
        if not upcoming: v.addWidget(QLabel("未来7天暂无截止事项。"))
        for e in upcoming[:12]:
            chip = EventChip(self.db, e, False); chip.changed.connect(self.changed); v.addWidget(chip)
        v.section_box.setMinimumHeight(round(max(72, 42 + min(12, len(upcoming)) * 62) * scale))
        month_prefix = now.strftime("%Y-%m")
        month_events = [e for e in events if (e.get("start_at") or "").startswith(month_prefix) or (e.get("deadline_at") or "").startswith(month_prefix)]
        exams = sum(e.get("type") in ("公务员考试", "笔试", "面试") for e in month_events)
        jobs = sum(e.get("type") in ("简历投递截止", "网申截止", "宣讲会", "笔试确认") for e in month_events)
        completed = sum(e.get("status") == "已完成" for e in month_events); pending = sum(e.get("status") not in ("已完成", "已取消") for e in month_events)
        overdue = sum(is_overdue(e) for e in events)
        v = self.section("本月统计"); stats = QLabel(f"考试节点  {exams}\n求职节点  {jobs}\n已完成    {completed}\n待办      {pending}\n已逾期    {overdue}"); stats.setObjectName("statsLabel"); v.addWidget(stats); v.section_box.setMinimumHeight(round(145 * scale))
        self.layout.addStretch()
        self.layout.activate()
        self.content.setMinimumHeight(self.layout.sizeHint().height())


class DesktopWidget(QWidget):
    expand_requested = Signal()
    changed = Signal()

    def __init__(self, db: Database, settings: Settings):
        super().__init__(); self.db = db; self.settings = settings; self.drag_start: QPoint | None = None; self.start_geometry: QRect | None = None; self.resize_mode = ""
        self.setWindowTitle(APP_NAME + "小组件"); self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setMinimumSize(330, 430); self.resize(380, 580)
        root = QVBoxLayout(self); root.setContentsMargins(8, 8, 8, 8)
        self.panel = QFrame(); self.panel.setObjectName("widgetPanel"); self.panel.setStyleSheet("QFrame#widgetPanel{background:rgba(250,252,255,242);border:1px solid rgba(120,135,155,80);border-radius:14px;color:#172033;}")
        panel_layout = QVBoxLayout(self.panel); panel_layout.setContentsMargins(14, 10, 14, 12); panel_layout.setSpacing(8)
        title_row = QHBoxLayout(); self.date_label = QLabel(); self.date_label.setObjectName("widgetDate")
        self.lock_button = QToolButton(); self.lock_button.setCheckable(True); self.lock_button.setChecked(bool(settings.get("widget_locked"))); self.update_lock_icon(); self.lock_button.clicked.connect(self.toggle_lock)
        expand = QToolButton(); expand.setText("↗"); expand.setToolTip("展开完整窗口"); expand.clicked.connect(self.expand_requested)
        hide = QToolButton(); hide.setText("×"); hide.setToolTip("隐藏小组件"); hide.clicked.connect(self.hide)
        title_row.addWidget(self.date_label); title_row.addStretch(); title_row.addWidget(self.lock_button); title_row.addWidget(expand); title_row.addWidget(hide); panel_layout.addLayout(title_row)
        self.body = QVBoxLayout(); panel_layout.addLayout(self.body, 1)
        self.grip = QSizeGrip(self.panel); grip_row = QHBoxLayout(); grip_row.addStretch(); grip_row.addWidget(self.grip); panel_layout.addLayout(grip_row)
        root.addWidget(self.panel); self.setWindowOpacity(float(settings.get("widget_opacity", 0.96)))
        geometry = settings.get("widget_geometry", "")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        self.refresh()

    def update_lock_icon(self) -> None:
        locked = self.lock_button.isChecked(); self.lock_button.setText("🔒" if locked else "🔓"); self.lock_button.setToolTip("解锁位置" if locked else "锁定位置"); self.grip.setVisible(not locked) if hasattr(self, "grip") else None

    def toggle_lock(self, checked: bool) -> None: self.settings.set("widget_locked", checked); self.update_lock_icon()

    def clear_body(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def refresh(self) -> None:
        self.clear_body(); now = datetime.now(); weekdays = "一二三四五六日"; self.date_label.setText(f"{now:%m月%d日} 周{weekdays[now.weekday()]}")
        events = self.db.list_events(False)
        important = sorted([e for e in events if e.get("important") and event_due(e) and e.get("status") not in ("已完成", "已取消")], key=lambda e: event_due(e) or datetime.max)
        if important:
            e = important[0]; card = QFrame(); card.setStyleSheet("background:#eaf2ff;border-radius:9px;"); v = QVBoxLayout(card); name = QLabel(e["title"]); name.setAlignment(Qt.AlignCenter); name.setWordWrap(True); count = QLabel(countdown_text(e.get("deadline_at") or e.get("start_at"))); count.setObjectName("countdownBig"); count.setAlignment(Qt.AlignCenter); v.addWidget(name); v.addWidget(count); self.body.addWidget(card)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); content = QWidget(); v = QVBoxLayout(content); v.setContentsMargins(0,0,0,0)
        today = now.strftime("%Y-%m-%d"); today_events = [e for e in events if today in ((e.get("start_at") or "")[:10], (e.get("deadline_at") or "")[:10])]
        heading = QLabel(f"今天 · {len(today_events)}"); heading.setObjectName("panelHeading"); v.addWidget(heading)
        if not today_events: v.addWidget(QLabel("暂无事项"))
        for e in today_events:
            chip = EventChip(self.db, e, False); chip.changed.connect(self.changed); v.addWidget(chip)
        limit = now + timedelta(days=7); upcoming = sorted([e for e in events if event_due(e) and now < event_due(e) <= limit and today not in ((e.get("start_at") or "")[:10], (e.get("deadline_at") or "")[:10])], key=lambda e: event_due(e) or datetime.max)
        heading = QLabel(f"未来7天 · {len(upcoming)}"); heading.setObjectName("panelHeading"); v.addWidget(heading)
        if not upcoming: v.addWidget(QLabel("暂无临近截止"))
        for e in upcoming[:10]:
            chip = EventChip(self.db, e, False); chip.changed.connect(self.changed); v.addWidget(chip)
        v.addStretch(); scroll.setWidget(content); self.body.addWidget(scroll, 1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.lock_button.isChecked() and mouse_local_y(event) < 58:
            self.drag_start = mouse_global_point(event) - self.frameGeometry().topLeft(); event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_start is not None and event.buttons() & Qt.LeftButton: self.move(mouse_global_point(event) - self.drag_start); event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.drag_start = None; self.save_geometry(); super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "settings"): QTimer.singleShot(250, self.save_geometry)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "settings"): QTimer.singleShot(250, self.save_geometry)

    def save_geometry(self) -> None:
        try: self.settings.set("widget_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception: pass


class SettingsDialog(QDialog):
    applied = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent); self.settings = settings; self.setWindowTitle("设置"); self.setMinimumWidth(430)
        root = QVBoxLayout(self); form = QFormLayout()
        self.theme = QComboBox(); self.theme.addItem("跟随系统", "system"); self.theme.addItem("浅色", "light"); self.theme.addItem("深色", "dark"); self.theme.setCurrentIndex(max(0, self.theme.findData(settings.get("theme"))))
        self.autostart = QCheckBox("登录 Windows 后自动启动"); self.autostart.setChecked(bool(settings.get("autostart")))
        self.overdue = QCheckBox("逾期未完成事项每天提醒一次"); self.overdue.setChecked(bool(settings.get("overdue_remind", True)))
        self.opacity = QSpinBox(); self.opacity.setRange(65, 100); self.opacity.setSuffix(" %"); self.opacity.setValue(round(float(settings.get("widget_opacity", .96))*100))
        self.font_auto = QCheckBox("随窗口尺寸自动调整"); self.font_auto.setChecked(bool(settings.get("font_auto", True)))
        self.font_size = QSpinBox(); self.font_size.setRange(10, 22); self.font_size.setSuffix(" 磅"); self.font_size.setValue(int(settings.get("font_size", 12)))
        self.font_size.setEnabled(not self.font_auto.isChecked()); self.font_auto.toggled.connect(lambda checked: self.font_size.setEnabled(not checked))
        font_row = QHBoxLayout(); font_row.addWidget(self.font_auto); font_row.addWidget(self.font_size); font_row.addStretch()
        form.addRow("界面主题", self.theme); form.addRow("文字大小", font_row); form.addRow("开机启动", self.autostart); form.addRow("逾期提醒", self.overdue); form.addRow("小组件不透明度", self.opacity); root.addLayout(form)
        info = QLabel(f"数据保存在：\n{APP_DIR}\n\n所有数据仅存储在本机，不会上传。"); info.setTextInteractionFlags(Qt.TextSelectableByMouse); info.setWordWrap(True); root.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Save).setText("保存"); buttons.button(QDialogButtonBox.Cancel).setText("取消"); buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def save(self) -> None:
        self.settings.set("theme", self.theme.currentData()); self.settings.set("font_auto", self.font_auto.isChecked()); self.settings.set("font_size", self.font_size.value()); self.settings.set("overdue_remind", self.overdue.isChecked()); self.settings.set("widget_opacity", self.opacity.value()/100)
        ok, message = set_autostart(self.autostart.isChecked())
        if ok: self.settings.set("autostart", self.autostart.isChecked())
        else: QMessageBox.warning(self, "开机启动设置失败", message)
        self.applied.emit(); self.accept()


def set_autostart(enabled: bool) -> tuple[bool, str]:
    if sys.platform != "win32": return False, "当前只支持 Windows 开机启动。"
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if getattr(sys, "frozen", False): command = f'"{sys.executable}"'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe"); command = f'"{pythonw}" "{Path(__file__).resolve()}"'
        if enabled: winreg.SetValueEx(key, "ExamJobCalendar", 0, winreg.REG_SZ, command)
        else:
            try: winreg.DeleteValue(key, "ExamJobCalendar")
            except FileNotFoundError: pass
        winreg.CloseKey(key); return True, ""
    except Exception as exc: return False, str(exc)


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings: Settings):
        super().__init__(); self.db = db; self.settings = settings; self.allow_close = False
        self.font_resize_timer = QTimer(self); self.font_resize_timer.setSingleShot(True); self.font_resize_timer.setInterval(180); self.font_resize_timer.timeout.connect(self.apply_auto_font)
        self.splitter_save_timer = QTimer(self); self.splitter_save_timer.setSingleShot(True); self.splitter_save_timer.setInterval(300); self.splitter_save_timer.timeout.connect(self.save_splitter_sizes)
        self.setWindowTitle(APP_NAME); self.resize(1420, 860); self.setMinimumSize(1050, 680)
        self.build_ui(); self.refresh_all(); self.auto_backup()

    def build_ui(self) -> None:
        central = QWidget(); self.setCentralWidget(central); root = QVBoxLayout(central); root.setContentsMargins(12, 10, 12, 10); root.setSpacing(8)
        toolbar = QHBoxLayout(); logo = QLabel(APP_NAME); logo.setObjectName("appLogo")
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索标题、地点、备注……"); self.search.setClearButtonEnabled(True); self.search.setMinimumWidth(260); self.search.textChanged.connect(self.refresh_all)
        add = QPushButton("＋ 新建事项"); add.setObjectName("primaryButton"); add.clicked.connect(self.add_event)
        smart = QPushButton("智能识别"); smart.setToolTip("粘贴公告文字，自动提取报名、缴费、准考证、笔试等时间节点"); smart.clicked.connect(self.smart_import)
        widget_btn = QPushButton("桌面小组件"); widget_btn.clicked.connect(self.show_widget)
        data_btn = QPushButton("数据与备份 ▾"); menu = QMenu(data_btn)
        for text, fn in (("导出 JSON", self.export_json), ("导入 JSON", self.import_json), ("导出 CSV", self.export_csv), ("导出 ICS", self.export_ics), ("立即备份数据库", self.backup_now), ("从数据库备份恢复", self.restore_backup), ("打开数据文件夹", self.open_data_folder)):
            action = menu.addAction(text); action.triggered.connect(fn)
        data_btn.setMenu(menu)
        font_smaller = QToolButton(); font_smaller.setText("A−"); font_smaller.setToolTip("减小文字（切换为自定义字号）"); font_smaller.clicked.connect(lambda: self.adjust_font(-1))
        font_larger = QToolButton(); font_larger.setText("A＋"); font_larger.setToolTip("增大文字（切换为自定义字号）"); font_larger.clicked.connect(lambda: self.adjust_font(1))
        settings_btn = QPushButton("设置"); settings_btn.clicked.connect(self.open_settings)
        toolbar.addWidget(logo); toolbar.addStretch(); toolbar.addWidget(self.search); toolbar.addWidget(add); toolbar.addWidget(smart); toolbar.addWidget(widget_btn); toolbar.addWidget(data_btn); toolbar.addWidget(font_smaller); toolbar.addWidget(font_larger); toolbar.addWidget(settings_btn); root.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal); self.splitter = splitter; splitter.setChildrenCollapsible(False); splitter.setHandleWidth(8); root.addWidget(splitter, 1)
        sidebar = QFrame(); self.sidebar = sidebar; sidebar.setMinimumWidth(165); sidebar.setMaximumWidth(220); side = QVBoxLayout(sidebar); side.setContentsMargins(0,0,8,0)
        side.addWidget(QLabel("事件类型")); self.type_filter = QListWidget(); self.type_filter.addItem("全部类型"); self.type_filter.addItems(EVENT_TYPES.keys()); self.type_filter.setCurrentRow(0); self.type_filter.currentRowChanged.connect(self.refresh_all); side.addWidget(self.type_filter, 1)
        side.addWidget(QLabel("状态")); self.status_filter = QComboBox(); self.status_filter.addItems(["全部状态"] + STATUSES + ["已逾期"]); self.status_filter.currentTextChanged.connect(self.refresh_all); side.addWidget(self.status_filter)
        side.addWidget(QLabel("范围")); self.range_filter = QComboBox(); self.range_filter.addItems(["全部时间", "今天", "未来7天", "未来30天"]); self.range_filter.currentTextChanged.connect(self.refresh_all); side.addWidget(self.range_filter); side.addStretch(); splitter.addWidget(sidebar)

        self.tabs = QTabWidget(); self.month_view = MonthView(self.db, self); self.week_view = WeekView(self.db, self); self.agenda_view = AgendaView(self.db, self)
        self.tabs.addTab(self.month_view, "月视图"); self.tabs.addTab(self.week_view, "周视图"); self.tabs.addTab(self.agenda_view, "议程视图"); splitter.addWidget(self.tabs)
        self.dashboard = DashboardPanel(self.db, self); self.dashboard.setMinimumWidth(240); splitter.addWidget(self.dashboard); splitter.setStretchFactor(1, 1)
        saved_sizes = self.settings.get("main_splitter_sizes", [180, 900, 340])
        splitter.setSizes(saved_sizes if isinstance(saved_sizes, list) and len(saved_sizes) == 3 else [180, 900, 340])
        splitter.splitterMoved.connect(lambda *_: self.splitter_save_timer.start())
        for source in (self.month_view, self.week_view, self.agenda_view, self.dashboard): source.changed.connect(self.refresh_all)
        self.statusBar().showMessage(f"本地数据：{DB_PATH}")

    def filtered_events(self) -> list[dict[str, Any]]:
        events = self.db.list_events(); query = self.search.text().strip().lower(); event_type = self.type_filter.currentItem().text() if self.type_filter.currentItem() else "全部类型"; status = self.status_filter.currentText(); range_text = self.range_filter.currentText(); now = datetime.now(); today = now.strftime("%Y-%m-%d")
        result = []
        for e in events:
            haystack = " ".join(str(e.get(k, "")) for k in ("title", "location", "notes", "type")).lower()
            if query and query not in haystack: continue
            if event_type != "全部类型" and e.get("type") != event_type: continue
            if status == "已逾期" and not is_overdue(e): continue
            if status not in ("全部状态", "已逾期") and e.get("status") != status: continue
            due = event_due(e)
            if range_text == "今天" and today not in ((e.get("start_at") or "")[:10], (e.get("deadline_at") or "")[:10]): continue
            if range_text in ("未来7天", "未来30天"):
                days = 7 if range_text == "未来7天" else 30
                if not due or not (now <= due <= now + timedelta(days=days)): continue
            result.append(e)
        return result

    def refresh_all(self, *args) -> None:
        events = self.filtered_events(); self.month_view.refresh(events); self.week_view.refresh(events); self.agenda_view.refresh(events); self.dashboard.refresh(events)
        if hasattr(self, "desktop_widget"): self.desktop_widget.refresh()

    def add_event(self) -> None:
        dlg = EventDialog(self.db, parent=self); dlg.saved.connect(self.refresh_all); dlg.exec()

    def smart_import(self) -> None:
        dlg = SmartImportDialog(self.db, self)
        dlg.imported.connect(lambda count: self.refresh_all())
        dlg.exec()

    def save_splitter_sizes(self) -> None:
        if hasattr(self, "splitter"):
            self.settings.set("main_splitter_sizes", self.splitter.sizes())

    def show_widget(self) -> None:
        self.desktop_widget.show(); self.desktop_widget.raise_(); self.desktop_widget.activateWindow(); self.settings.set("widget_visible", True)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self); dlg.applied.connect(self.apply_settings); dlg.exec()

    def apply_settings(self) -> None:
        self.ensure_font_workspace(); QApplication.instance().apply_theme(force=True); self.desktop_widget.setWindowOpacity(float(self.settings.get("widget_opacity", .96))); self.refresh_all()

    def adjust_font(self, delta: int) -> None:
        current = int(getattr(QApplication.instance(), "current_font_pt", self.settings.get("font_size", 12)))
        self.settings.set("font_auto", False)
        self.settings.set("font_size", max(10, min(22, current + delta)))
        self.ensure_font_workspace()
        QApplication.instance().apply_theme(force=True)
        self.refresh_all()

    def ensure_font_workspace(self) -> None:
        if self.settings.get("font_auto", True):
            return
        font_pt = max(10, min(22, int(self.settings.get("font_size", 12))))
        if font_pt <= 12:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        target_width = min(round(available.width() * 0.96), round(1420 * font_pt / 12))
        target_height = min(round(available.height() * 0.94), round(860 * min(1.18, font_pt / 12)))
        if self.width() < target_width or self.height() < target_height:
            self.resize(max(self.width(), target_width), max(self.height(), target_height))

    def update_font_geometry(self, font_pt: int) -> None:
        scale = max(0.9, min(1.6, font_pt / 12))
        self.sidebar.setMinimumWidth(round(180 * scale)); self.sidebar.setMaximumWidth(round(235 * scale))
        self.dashboard.setMinimumWidth(round(240 * scale)); self.dashboard.setMaximumWidth(16777215)
        self.search.setMinimumWidth(round(260 * scale))

    def apply_auto_font(self) -> None:
        if not self.settings.get("font_auto", True):
            return
        if QApplication.instance().apply_theme():
            self.refresh_all()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "font_resize_timer") and self.settings.get("font_auto", True):
            self.font_resize_timer.start()

    def export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", str(Path.home() / f"日历备份_{datetime.now():%Y%m%d}.json"), "JSON 文件 (*.json)")
        if path: self.db.export_json(Path(path)); QMessageBox.information(self, "导出完成", f"数据已导出到：\n{path}")

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入 JSON", str(Path.home()), "JSON 文件 (*.json)")
        if not path: return
        try:
            self.db.backup(); count = self.db.import_json(Path(path)); self.refresh_all(); QMessageBox.information(self, "导入完成", f"成功导入 {count} 条事项。导入前的数据已自动备份。")
        except Exception as exc: QMessageBox.critical(self, "导入失败", str(exc))

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", str(Path.home() / f"日历事项_{datetime.now():%Y%m%d}.csv"), "CSV 文件 (*.csv)")
        if not path: return
        fields = ["标题", "类型", "开始时间", "截止时间", "全天", "地点", "链接", "备注", "优先级", "状态", "是否提醒"]
        keys = ["title", "type", "start_at", "deadline_at", "all_day", "location", "link", "notes", "priority", "status", "reminder_enabled"]
        with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f); writer.writerow(fields)
            for e in self.db.list_events(): writer.writerow([e.get(k, "") for k in keys])
        QMessageBox.information(self, "导出完成", f"CSV 已保存到：\n{path}")

    def export_ics(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 ICS", str(Path.home() / f"日历事项_{datetime.now():%Y%m%d}.ics"), "日历文件 (*.ics)")
        if not path: return
        def esc(s: str) -> str: return str(s).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ExamJobCalendar//CN", "CALSCALE:GREGORIAN"]
        for e in self.db.list_events():
            start = text_to_dt(e.get("start_at")); end = text_to_dt(e.get("deadline_at")) or start
            if not start: continue
            lines += ["BEGIN:VEVENT", f"UID:{e['id']}@exam-job-calendar", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}", f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}", f"SUMMARY:{esc(e['title'])}", f"DESCRIPTION:{esc(e.get('notes',''))}", f"LOCATION:{esc(e.get('location',''))}", "END:VEVENT"]
        lines.append("END:VCALENDAR"); Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="utf-8"); QMessageBox.information(self, "导出完成", f"ICS 已保存到：\n{path}")

    def backup_now(self) -> None:
        path = self.db.backup(); QMessageBox.information(self, "备份完成", f"数据库已备份到：\n{path}")

    def restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择数据库备份", str(BACKUP_DIR), "数据库备份 (*.db)")
        if not path:
            return
        if QMessageBox.warning(self, "确认恢复", "恢复会用所选备份替换当前数据。程序会先自动备份当前数据，是否继续？", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.db.backup()
            self.db.restore(Path(path))
            self.refresh_all()
            QMessageBox.information(self, "恢复完成", "数据已从备份恢复。")
        except Exception as exc:
            QMessageBox.critical(self, "恢复失败", str(exc))

    def auto_backup(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self.settings.get("last_backup") != today:
            self.db.backup(); self.settings.set("last_backup", today)
            backups = sorted(BACKUP_DIR.glob("calendar_*.db"), reverse=True)
            for old in backups[20:]:
                try: old.unlink()
                except OSError: pass

    def open_data_folder(self) -> None: QDesktopServices.openUrl(Path(APP_DIR).as_uri())

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_splitter_sizes()
        if self.allow_close: event.accept()
        else: event.ignore(); self.hide(); self.tray.showMessage(APP_NAME, "程序仍在后台运行，可从系统托盘重新打开。", QSystemTrayIcon.Information, 2500)


class CalendarApplication(QApplication):
    def __init__(self, argv):
        super().__init__(argv); self.setApplicationName(APP_NAME); self.setOrganizationName("LocalFirstTools"); self.setQuitOnLastWindowClosed(False)
        self.settings = Settings(); self.db = Database(); self.current_font_pt = 0; self._applied_theme = ""; self.apply_theme(force=True); self.window = MainWindow(self.db, self.settings); self.window.ensure_font_workspace(); self.widget = DesktopWidget(self.db, self.settings); self.window.desktop_widget = self.widget
        self.apply_theme(force=True)
        self.widget.expand_requested.connect(self.show_main); self.widget.changed.connect(self.window.refresh_all)
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self); self.window.tray = self.tray; self.build_tray(); self.tray.show()
        self.reminder_timer = QTimer(self); self.reminder_timer.timeout.connect(self.check_reminders); self.reminder_timer.start(30000); QTimer.singleShot(1500, self.check_reminders)
        self.hotkey_registered = False
        self.register_global_hotkey()
        if self.settings.get("widget_visible", True): self.widget.show()
        self.window.show()

    def build_tray(self) -> None:
        menu = QMenu(); show = menu.addAction("打开完整日历"); show.triggered.connect(self.show_main); widget = menu.addAction("显示桌面小组件"); widget.triggered.connect(self.show_widget); add = menu.addAction("新建事项"); add.triggered.connect(self.window.add_event); menu.addSeparator(); quit_action = menu.addAction("退出程序"); quit_action.triggered.connect(self.quit_app); self.tray.setContextMenu(menu); self.tray.setToolTip(APP_NAME); self.tray.activated.connect(lambda reason: self.show_main() if reason == QSystemTrayIcon.DoubleClick else None)

    def show_main(self) -> None: self.window.show(); self.window.raise_(); self.window.activateWindow()
    def show_widget(self) -> None: self.widget.show(); self.widget.raise_(); self.widget.activateWindow()

    def quit_app(self) -> None:
        if self.hotkey_registered and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(None, 1)
        self.window.allow_close = True; self.settings.set("widget_visible", self.widget.isVisible()); self.widget.save_geometry(); self.tray.hide(); self.window.close(); self.widget.close(); self.quit()

    def register_global_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        try:
            # Ctrl + Alt + Space：在任何程序中呼出完整日历。
            self.hotkey_registered = bool(ctypes.windll.user32.RegisterHotKey(None, 1, 0x0001 | 0x0002, 0x20))
            if self.hotkey_registered:
                self.hotkey_timer = QTimer(self)
                self.hotkey_timer.timeout.connect(self.poll_global_hotkey)
                self.hotkey_timer.start(120)
        except Exception as exc:
            log_error(exc)

    def poll_global_hotkey(self) -> None:
        try:
            from ctypes import wintypes
            message = wintypes.MSG()
            while ctypes.windll.user32.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 1):
                self.show_main()
        except Exception as exc:
            log_error(exc)

    def check_reminders(self) -> None:
        try:
            for event in self.db.due_reminders():
                body = f"{event.get('type','事项')} · {display_dt(event.get('deadline_at') or event.get('start_at'), bool(event.get('all_day')))}\n{countdown_text(event.get('deadline_at') or event.get('start_at'))}"
                self.tray.showMessage("提醒：" + event["title"], body, QSystemTrayIcon.Information, 10000)
            if self.settings.get("overdue_remind", True):
                overdue = self.db.overdue_for_reminder()
                if overdue:
                    titles = "、".join(e["title"] for e in overdue[:3]); suffix = f"等 {len(overdue)} 项" if len(overdue) > 3 else ""
                    self.tray.showMessage("逾期事项提醒", f"{titles}{suffix}尚未完成，请及时处理。", QSystemTrayIcon.Warning, 12000)
            self.widget.refresh()
        except Exception as exc: log_error(exc)

    def effective_font_size(self) -> int:
        if not self.settings.get("font_auto", True):
            return max(10, min(22, int(self.settings.get("font_size", 12))))
        window = getattr(self, "window", None)
        if window is None:
            return 12
        width = max(1050, window.width())
        height = max(680, window.height())
        area_ratio = (width * height) / (1420 * 860)
        return max(11, min(18, round(12 * area_ratio ** 0.5)))

    def apply_theme(self, force: bool = False) -> bool:
        mode = self.settings.get("theme", "system")
        if mode == "system":
            mode = "dark" if self.palette().color(QPalette.Window).lightness() < 128 else "light"
        font_pt = self.effective_font_size()
        if not force and font_pt == self.current_font_pt and mode == self._applied_theme:
            return False
        self.current_font_pt = font_pt
        self._applied_theme = mode
        window = getattr(self, "window", None)
        if window is not None and hasattr(window, "update_font_geometry"):
            window.update_font_geometry(font_pt)
        title_pt = min(22, font_pt + 3)
        logo_pt = min(25, font_pt + 4)
        countdown_pt = min(30, font_pt + 8)
        common_labels = f"""
            QLabel#appLogo{{font-size:{logo_pt}pt;font-weight:800;color:#215bb8;}}
            QLabel#sectionTitle{{font-size:{title_pt}pt;font-weight:700;}}
            QLabel#countdownBig{{font-size:{countdown_pt}pt;font-weight:800;color:#2563eb;}}
            QLabel#statsLabel{{font-size:{font_pt + 1}pt;}}
            QLabel#widgetDate{{font-size:{font_pt + 2}pt;font-weight:700;}}
            QLabel#panelHeading{{font-size:{font_pt + 1}pt;font-weight:700;margin-top:4px;}}
            QToolButton#eventAction{{padding:2px;}}
        """
        if mode == "dark":
            self.setStyleSheet(f"""
                QWidget{{background:#171b22;color:#e7ecf3;font-family:'Microsoft YaHei UI';font-size:{font_pt}pt;}}
                QMainWindow,QDialog{{background:#171b22;}} QLineEdit,QComboBox,QDateTimeEdit,QTextEdit,QListWidget,QTableWidget{{background:#202631;border:1px solid #3a4352;border-radius:5px;padding:5px;}}
                QPushButton,QToolButton{{background:#29313d;border:1px solid #465163;border-radius:5px;padding:5px 9px;}} QPushButton:hover,QToolButton:hover{{background:#354052;}}
                QPushButton#primaryButton{{background:#2563eb;color:white;border-color:#2563eb;}} QGroupBox{{border:1px solid #384252;border-radius:7px;margin-top:8px;padding-top:9px;font-weight:600;}} QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}} QTabWidget::pane{{border:1px solid #384252;}} QTabBar::tab{{padding:8px 18px;background:#222936;}} QTabBar::tab:selected{{background:#315ea8;color:white;}}
                {common_labels}
            """)
        else:
            self.setStyleSheet(f"""
                QWidget{{color:#1f2937;font-family:'Microsoft YaHei UI';font-size:{font_pt}pt;}} QMainWindow,QDialog{{background:#f5f7fb;}}
                QLineEdit,QComboBox,QDateTimeEdit,QTextEdit,QListWidget,QTableWidget{{background:white;border:1px solid #cdd5e1;border-radius:5px;padding:5px;}}
                QPushButton,QToolButton{{background:#fff;border:1px solid #c8d1df;border-radius:5px;padding:5px 9px;}} QPushButton:hover,QToolButton:hover{{background:#edf4ff;border-color:#7aa6ea;}}
                QPushButton#primaryButton{{background:#2563eb;color:white;border-color:#2563eb;font-weight:600;}} QGroupBox{{border:1px solid #d4dbe6;border-radius:7px;margin-top:8px;padding-top:9px;font-weight:600;}} QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}} QTabWidget::pane{{border:1px solid #d4dbe6;}} QTabBar::tab{{padding:8px 18px;background:#edf1f6;}} QTabBar::tab:selected{{background:#2563eb;color:white;}}
                {common_labels}
            """)
        return True


def main() -> int:
    ensure_dirs()
    try:
        app = CalendarApplication(sys.argv)
        return app.exec()
    except Exception as exc:
        log_error(exc)
        try: ctypes.windll.user32.MessageBoxW(None, f"程序启动失败：\n{exc}\n\n日志：{LOG_PATH}", APP_NAME, 0x10)
        except Exception: print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
