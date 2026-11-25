from __future__ import annotations

import json
import os
from functools import wraps
from urllib.parse import urljoin, urlparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, session, url_for
APP_VERSION = "2.0"
DATA_FILE = Path(__file__).resolve().with_name("activity_board_data.json")
USERS_FILE = Path(__file__).resolve().with_name("activity_board_users.json")
PLAN_STEP_DAYS = 10
STATUS_SEQUENCE = ["review", "design", "owner1", "owner2", "owner3", "transport", "setup"]
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5050

SPEC_OPTIONS = {
    "건조로, 세정로, 열처리로": [
        "TYPE1 : 밀폐형 룸 설치, 급기 및 배기 덕트 설치, 조명설치, 소방배관 설치, (직수배관설치)",
        "TYPE2 : 밀폐형 룸 설치, 급기 및 배기 덕트 설치, 조명설치, 소방배관 설치, (직수배관설치) 스크러버 및 집진기 설비, 관련 덕트 설치, (덕트크기에 따른 하부 소방배관 설치)",
    ],
    "용접설비": [
        "TYPE1 : 밀폐형 룸 설치, 급기 및 배기 덕트 설치, 조명설치, 소방배관 설치, (직수배관설치)",
        "TYPE2 : 일반 급기 및 배기 덕트 설치 (덕트크기에 따른 하부 소방배관 설치)",
    ],
    "유해물질 발생 설비": [
        "TYPE1 : 이물질이 섞여있지 않은 매연 제거를 위한 국소배기 장치 셧업 배기덕트 및 헵 설치",
        "TYPE2 : 이물질이 섞여있지 않은 매연 제거를 위한 국소배기 장치 셧업(유량부족시) 급기 배관 및 헵 and 배기덕트 및 헵 설치",
        "TYPE3 : 이물질이 섞여있는 매연 제거를 위한 국소배기 및 환경 장치 셧업 집진기 및 덕트 설치",
    ],
}

PLAN_ROW_TEMPLATES: list[dict[str, str | bool]] = [
    {"id": "review", "parent": "root", "text": "검토", "status": "W", "open": True},
    {"id": "design", "parent": "root", "text": "제작", "status": "", "open": True},
    {"id": "owner1", "parent": "design", "text": "생기담당_DR", "status": "", "open": False},
    {"id": "owner2", "parent": "design", "text": "생기담당_안전검사", "status": "", "open": False},
    {"id": "owner3", "parent": "design", "text": "생기담당_SAT", "status": "", "open": False},
    {"id": "transport", "parent": "root", "text": "운송", "status": "", "open": False},
    {"id": "setup", "parent": "root", "text": "셋업", "status": "", "open": False},
]

REFERENCE_ROWS = [
    {
        "equipment": "금속이나 그 밖의 광물의 용해로",
        "criteria": "용량 3톤 이상",
        "details": "금속 또는 비금속 광물을 해당 물질의 녹는점 이상으로 가열하여 용해하는 설비",
    },
    {
        "equipment": "화학설비 (특수화학설비)",
        "criteria": "하루 제조·취급량(저장량 포함)이 위험물질 기준량 이상",
        "details": "발열반응 장치, 분리 장치, 고온·고압(350℃ 이상 또는 980kPa 이상) 운전 설비, 이상 화학반응 우려 설비 등",
    },
    {
        "equipment": "건조설비",
        "criteria": "연료 최대 소비량 50kg/hr 이상 또는 정격 소비전력 50kW 이상",
        "details": "유기화합물 건조, 인화성 증기 발생 건조 작업, 가연성 분진 발생 건조 작업 중 하나에 해당하는 경우",
    },
    {
        "equipment": "가스집합 용접장치",
        "criteria": "인화성 가스 집합량 1,000kg 이상",
        "details": "용접용단용으로 인화성 가스 저장 용기를 도관으로 연결한 고정식 일관 설비",
    },
    {
        "equipment": "국소배기장치, 전체환기장치, 밀폐설비",
        "criteria": "배풍량 60㎥/분 이상 또는 150㎥/분 이상",
        "details": "유해물질 가스, 증기, 분진 발산원을 밀폐하거나 제거하기 위해 설치하는 설비",
    },
    {
        "equipment": "그 외 자동화 설비 기준",
        "criteria": "소비전력 300KW 이상",
        "details": "전자부품, 반도체, 기계장비, 화학제품 제조업 등에서 사용하는 자동화 설비",
    },
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ACTIVITY_BOARD_SECRET_KEY", "activity-board-dev-secret")


def get_default_user() -> tuple[str, str]:
    default_name = os.environ.get("ACTIVITY_BOARD_DEFAULT_NAME", "관리자").strip() or "관리자"
    default_employee_id = os.environ.get("ACTIVITY_BOARD_DEFAULT_EMPLOYEE_ID", "1000").strip() or "1000"
    return default_name, default_employee_id


def is_safe_redirect_target(target: str) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in {"http", "https"} and host_url.netloc == test_url.netloc


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("logged_in"):
            return view_func(*args, **kwargs)

        if request.query_string:
            next_target = f"{request.path}?{request.query_string.decode()}"
        else:
            next_target = request.path
        return redirect(url_for("login", next=next_target))

    return wrapped_view


class UserStore:
    def __init__(self, users_file: Path):
        self.users_file = users_file
        self.database_url = os.environ.get("DATABASE_URL", "").strip()
        self._db_enabled = bool(self.database_url)
        self._pg_driver = None

        if self._db_enabled:
            self._ensure_users_table()
            self._ensure_seed_user_db()
        else:
            self._ensure_users_file()

    def _get_db_connection(self):
        if self._pg_driver is None:
            try:
                import psycopg  # type: ignore[reportMissingImports]
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL이 설정되어 있지만 psycopg 패키지가 설치되지 않았습니다. "
                    "requirements를 설치해 주세요."
                ) from exc
            self._pg_driver = psycopg
        return self._pg_driver.connect(self.database_url, autocommit=True)

    def _default_user_record(self) -> dict[str, Any]:
        name, employee_id = get_default_user()
        return {
            "name": name,
            "employee_id": employee_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _is_valid_user_record(self, user: dict[str, Any]) -> bool:
        return bool(str(user.get("name", "")).strip()) and bool(str(user.get("employee_id", "")).strip())

    def _ensure_users_table(self) -> None:
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

    def _ensure_seed_user_db(self) -> None:
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                row = cur.fetchone()
                user_count = int(row[0]) if row else 0

        if user_count > 0:
            return

        default_user = self._default_user_record()
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (employee_id, name, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (employee_id)
                    DO UPDATE SET name = EXCLUDED.name
                    """,
                    (
                        default_user["employee_id"],
                        default_user["name"],
                        default_user["created_at"],
                    ),
                )

    def _ensure_users_file(self) -> None:
        if not self.users_file.exists():
            self.save_users([self._default_user_record()])
            return

        users = self.load_users()
        if any(self._is_valid_user_record(user) for user in users):
            return
        users.append(self._default_user_record())
        self.save_users(users)

    def load_users(self) -> list[dict[str, Any]]:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT name, employee_id, created_at FROM users ORDER BY created_at ASC")
                    rows = cur.fetchall()

            users: list[dict[str, Any]] = []
            for name, employee_id, created_at in rows:
                created_at_text = (
                    created_at.isoformat(timespec="seconds")
                    if hasattr(created_at, "isoformat")
                    else str(created_at)
                )
                users.append(
                    {
                        "name": str(name),
                        "employee_id": str(employee_id),
                        "created_at": created_at_text,
                    }
                )
            return users

        try:
            with self.users_file.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (json.JSONDecodeError, OSError):
            return []
        users = payload.get("users", [])
        return users if isinstance(users, list) else []

    def save_users(self, users: list[dict[str, Any]]) -> None:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("TRUNCATE TABLE users")
                    for user in users:
                        if not self._is_valid_user_record(user):
                            continue
                        created_at = str(user.get("created_at", "")).strip() or datetime.now().isoformat(timespec="seconds")
                        cur.execute(
                            """
                            INSERT INTO users (employee_id, name, created_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (employee_id)
                            DO UPDATE SET
                                name = EXCLUDED.name,
                                created_at = EXCLUDED.created_at
                            """,
                            (
                                str(user.get("employee_id", "")).strip(),
                                str(user.get("name", "")).strip(),
                                created_at,
                            ),
                        )
            return

        with self.users_file.open("w", encoding="utf-8") as file:
            json.dump({"users": users}, file, ensure_ascii=False, indent=2)

    def find_user_by_employee_id(self, employee_id: str) -> dict[str, Any] | None:
        normalized = employee_id.strip()
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT name, employee_id, created_at FROM users WHERE employee_id = %s",
                        (normalized,),
                    )
                    row = cur.fetchone()
            if row is None:
                return None
            name, employee_id_value, created_at = row
            created_at_text = (
                created_at.isoformat(timespec="seconds")
                if hasattr(created_at, "isoformat")
                else str(created_at)
            )
            return {
                "name": str(name),
                "employee_id": str(employee_id_value),
                "created_at": created_at_text,
            }

        for user in self.load_users():
            if str(user.get("employee_id", "")).strip() == normalized:
                return user
        return None

    def create_user(self, name: str, employee_id: str) -> tuple[bool, str]:
        cleaned_name = name.strip()
        cleaned_employee_id = employee_id.strip()

        if len(cleaned_name) < 2:
            return False, "이름은 2자 이상이어야 합니다."
        if not cleaned_employee_id.isdigit():
            return False, "사번은 숫자만 입력해 주세요."
        if self.find_user_by_employee_id(cleaned_employee_id) is not None:
            return False, "이미 등록된 사번입니다."

        if self._db_enabled:
            created_at = datetime.now().isoformat(timespec="seconds")
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (employee_id, name, created_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (employee_id)
                        DO NOTHING
                        """,
                        (cleaned_employee_id, cleaned_name, created_at),
                    )
                    if cur.rowcount == 0:
                        return False, "이미 등록된 사번입니다."
        else:
            users = self.load_users()
            users.append(
                {
                    "name": cleaned_name,
                    "employee_id": cleaned_employee_id,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            self.save_users(users)

        return True, "사용자 등록이 완료되었습니다."


class PlanStore:
    def __init__(self, data_file: Path):
        self.data_file = data_file
        self.database_url = os.environ.get("DATABASE_URL", "").strip()
        self._db_enabled = bool(self.database_url)
        self._pg_driver = None

        if self._db_enabled:
            self._ensure_db_table()
            self._ensure_seed_data_db()
        else:
            self._ensure_data_file()

    def _get_db_connection(self):
        if self._pg_driver is None:
            try:
                import psycopg  # type: ignore[reportMissingImports]
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL이 설정되어 있지만 psycopg 패키지가 설치되지 않았습니다. "
                    "requirements를 설치해 주세요."
                ) from exc
            self._pg_driver = psycopg
        return self._pg_driver.connect(self.database_url, autocommit=True)

    def _ensure_db_table(self) -> None:
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS plans (
                        plan_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL
                    )
                    """
                )

    def _ensure_seed_data_db(self) -> None:
        with self._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM plans")
                row = cur.fetchone()
                plan_count = int(row[0]) if row else 0

        if plan_count > 0:
            return

        seed_plan = create_plan_record(
            selection="Y",
            equipment_spec="건조로, 세정로, 열처리로",
            type_option=SPEC_OPTIONS["건조로, 세정로, 열처리로"][0],
            equipment_name="샘플 자동화 설비",
            plan_start=date.today().isoformat(),
        )
        self.upsert_plan(seed_plan)

    def _ensure_data_file(self) -> None:
        if self.data_file.exists():
            return
        seed_plan = create_plan_record(
            selection="Y",
            equipment_spec="건조로, 세정로, 열처리로",
            type_option=SPEC_OPTIONS["건조로, 세정로, 열처리로"][0],
            equipment_name="샘플 자동화 설비",
            plan_start=date.today().isoformat(),
        )
        self.save({"plans": [seed_plan]})

    def load(self) -> dict[str, Any]:
        if self._db_enabled:
            raise RuntimeError("DB 모드에서는 load()를 사용하지 않습니다.")
        with self.data_file.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save(self, payload: dict[str, Any]) -> None:
        if self._db_enabled:
            raise RuntimeError("DB 모드에서는 save()를 사용하지 않습니다.")
        with self.data_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

    def list_plans(self) -> list[dict[str, Any]]:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM plans")
                    rows = cur.fetchall()

            plans: list[dict[str, Any]] = []
            for row in rows:
                payload = row[0]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                plans.append(payload)
        else:
            payload = self.load()
            plans = payload.get("plans", [])
        return sorted(plans, key=lambda plan: plan["updated_at"], reverse=True)

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM plans WHERE plan_id = %s", (plan_id,))
                    row = cur.fetchone()
            if row is None:
                return None
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return payload

        payload = self.load()
        for plan in payload.get("plans", []):
            if plan["id"] == plan_id:
                return plan
        return None

    def upsert_plan(self, updated_plan: dict[str, Any]) -> None:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO plans (plan_id, payload)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (plan_id)
                        DO UPDATE SET payload = EXCLUDED.payload
                        """,
                        (updated_plan["id"], json.dumps(updated_plan, ensure_ascii=False)),
                    )
            return

        payload = self.load()
        plans = payload.get("plans", [])
        replaced = False
        for index, plan in enumerate(plans):
            if plan["id"] == updated_plan["id"]:
                plans[index] = updated_plan
                replaced = True
                break
        if not replaced:
            plans.append(updated_plan)
        payload["plans"] = plans
        self.save(payload)

    def delete_plan(self, plan_id: str) -> bool:
        if self._db_enabled:
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM plans WHERE plan_id = %s", (plan_id,))
                    return bool(cur.rowcount)

        payload = self.load()
        plans = payload.get("plans", [])
        filtered = [plan for plan in plans if plan.get("id") != plan_id]
        if len(filtered) == len(plans):
            return False
        payload["plans"] = filtered
        self.save(payload)
        return True

def build_rows(equipment_name: str, plan_start: str) -> list[dict[str, Any]]:
    base_date = date.fromisoformat(plan_start)
    rows: list[dict[str, Any]] = [
        {
            "id": "root",
            "parent": "",
            "text": equipment_name,
            "values": ["", "", plan_start, plan_start, "", ""],
            "open": True,
        }
    ]

    current_start = base_date
    for template in PLAN_ROW_TEMPLATES:
        plan_end = current_start + timedelta(days=PLAN_STEP_DAYS)
        rows.append(
            {
                "id": str(template["id"]),
                "parent": str(template["parent"]),
                "text": str(template["text"]),
                "values": [
                    str(template["status"]),
                    "",
                    current_start.isoformat(),
                    plan_end.isoformat(),
                    "",
                    "",
                ],
                "open": bool(template["open"]),
            }
        )
        current_start = plan_end

    rows[0]["values"] = [
        rows[0]["values"][0],
        rows[0]["values"][1],
        rows[1]["values"][2],
        rows[-1]["values"][3],
        rows[0]["values"][4],
        rows[0]["values"][5],
    ]
    update_all_parent_plan_dates(rows)
    return rows


def create_plan_record(
    selection: str,
    equipment_spec: str,
    type_option: str,
    equipment_name: str,
    plan_start: str,
    created_by: str = "",
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "id": uuid4().hex[:10],
        "selection": selection,
        "equipment_spec": equipment_spec,
        "type_option": type_option,
        "equipment_name": equipment_name,
        "created_by": created_by,
        "plan_start": plan_start,
        "created_at": now,
        "updated_at": now,
        "rows": build_rows(equipment_name, plan_start),
    }


def calculate_delay(plan_end: str, actual_end: str = "") -> str:
    if not plan_end or not actual_end:
        return ""
    delay_days = (date.fromisoformat(actual_end) - date.fromisoformat(plan_end)).days
    return str(delay_days) if delay_days > 0 else ""


def calculate_duration(plan_start: str, plan_end: str) -> str:
    if not plan_start or not plan_end:
        return ""
    return str((date.fromisoformat(plan_end) - date.fromisoformat(plan_start)).days)


def format_status_display(status: str) -> str:
    if status == "C":
        return "완료"
    if status == "W":
        return "진행 중"
    return "대기"


def has_child_rows(rows: list[dict[str, Any]], row_id: str) -> bool:
    return any(row["parent"] == row_id for row in rows)


def get_child_row_ids(rows: list[dict[str, Any]], row_id: str) -> list[str]:
    return [str(row["id"]) for row in rows if row["parent"] == row_id]


def get_descendant_row_ids(rows: list[dict[str, Any]], row_id: str) -> list[str]:
    descendants: list[str] = []
    for child_id in get_child_row_ids(rows, row_id):
        descendants.append(child_id)
        descendants.extend(get_descendant_row_ids(rows, child_id))
    return descendants


def can_edit_actual_dates(rows: list[dict[str, Any]], row_id: str) -> bool:
    return row_id != "root" and not has_child_rows(rows, row_id)


def calculate_root_duration(rows: list[dict[str, Any]]) -> str:
    return str(
        sum(
            int(calculate_duration(row["values"][2], row["values"][3]) or "0")
            for row in rows
            if row["id"] != "root"
        )
    )


def activate_next_activity(row_lookup: dict[str, dict[str, Any]], row_id: str) -> None:
    if row_id not in STATUS_SEQUENCE:
        return
    next_index = STATUS_SEQUENCE.index(row_id) + 1
    if next_index >= len(STATUS_SEQUENCE):
        return
    next_row_id = STATUS_SEQUENCE[next_index]
    if row_lookup[next_row_id]["values"][0] == "":
        row_lookup[next_row_id]["values"][0] = "W"


def auto_complete_parent_activities(rows: list[dict[str, Any]], row_lookup: dict[str, dict[str, Any]], start_row_id: str) -> None:
    current_parent = row_lookup[start_row_id]["parent"]
    while current_parent:
        child_ids = get_child_row_ids(rows, current_parent)
        if not child_ids or any(row_lookup[child_id]["values"][0] != "C" for child_id in child_ids):
            break
        if row_lookup[current_parent]["values"][0] != "C":
            row_lookup[current_parent]["values"][0] = "C"
            activate_next_activity(row_lookup, current_parent)
        current_parent = row_lookup[current_parent]["parent"]


def update_parent_actual_dates(rows: list[dict[str, Any]], row_lookup: dict[str, dict[str, Any]], start_row_id: str) -> None:
    current_parent = row_lookup[start_row_id]["parent"]
    while current_parent:
        child_ids = get_child_row_ids(rows, current_parent)
        actual_starts = [row_lookup[child_id]["values"][4] for child_id in child_ids if row_lookup[child_id]["values"][4]]
        actual_ends = [row_lookup[child_id]["values"][5] for child_id in child_ids if row_lookup[child_id]["values"][5]]
        row_lookup[current_parent]["values"][4] = min(actual_starts) if actual_starts else ""
        row_lookup[current_parent]["values"][5] = max(actual_ends) if actual_ends else ""
        current_parent = row_lookup[current_parent]["parent"]


def update_parent_plan_dates(rows: list[dict[str, Any]], row_lookup: dict[str, dict[str, Any]], start_row_id: str) -> None:
    current_parent = row_lookup[start_row_id]["parent"]
    while current_parent:
        child_ids = get_child_row_ids(rows, current_parent)
        child_plan_starts = [row_lookup[child_id]["values"][2] for child_id in child_ids if row_lookup[child_id]["values"][2]]
        child_plan_ends = [row_lookup[child_id]["values"][3] for child_id in child_ids if row_lookup[child_id]["values"][3]]
        row_lookup[current_parent]["values"][2] = min(child_plan_starts) if child_plan_starts else ""
        row_lookup[current_parent]["values"][3] = max(child_plan_ends) if child_plan_ends else ""
        current_parent = row_lookup[current_parent]["parent"]


def update_all_parent_plan_dates(rows: list[dict[str, Any]]) -> None:
    row_lookup = {str(row["id"]): row for row in rows}
    for row in reversed(rows):
        if row["id"] != "root":
            update_parent_plan_dates(rows, row_lookup, str(row["id"]))


def recalculate_schedule_from(rows: list[dict[str, Any]], start_row_id: str, new_start: str) -> None:
    sequence = [str(row["id"]) for row in rows if row["id"] != "root"]
    start_index = 0 if start_row_id == "root" else sequence.index(start_row_id)
    current_start = date.fromisoformat(new_start)
    row_lookup = {str(row["id"]): row for row in rows}
    for row_id in sequence[start_index:]:
        row_lookup[row_id]["values"][2] = current_start.isoformat()
        plan_end = current_start + timedelta(days=PLAN_STEP_DAYS)
        row_lookup[row_id]["values"][3] = plan_end.isoformat()
        current_start = plan_end
    update_all_parent_plan_dates(rows)


def get_plan_end_target_row_id(rows: list[dict[str, Any]], row_id: str) -> str:
    sequence = [str(row["id"]) for row in rows if row["id"] != "root"]
    if not sequence:
        raise ValueError("수정할 일정이 없습니다.")
    if row_id == "root":
        return sequence[-1]

    descendant_ids = get_descendant_row_ids(rows, row_id)
    if not descendant_ids:
        return row_id

    descendant_set = set(descendant_ids)
    target_candidates = [sequence_id for sequence_id in sequence if sequence_id in descendant_set]
    if not target_candidates:
        return row_id
    return target_candidates[-1]


def update_plan_start(plan: dict[str, Any], row_id: str, selected_date: str) -> None:
    rows = plan["rows"]
    row_lookup = {str(row["id"]): row for row in rows}
    if row_lookup[row_id]["values"][0] == "C":
        raise ValueError("완료 상태인 Activity의 Plan Start는 변경할 수 없습니다.")
    if date.fromisoformat(selected_date) < date.today():
        raise ValueError("Plan Start는 오늘 이전 날짜로 변경할 수 없습니다.")
    recalculate_schedule_from(rows, row_id, selected_date)
    plan["plan_start"] = rows[1]["values"][2]


def update_plan_end(plan: dict[str, Any], row_id: str, selected_date: str) -> None:
    rows = plan["rows"]
    row_lookup = {str(row["id"]): row for row in rows}
    target_row_id = get_plan_end_target_row_id(rows, row_id)
    target_row = row_lookup[target_row_id]

    if target_row["values"][0] == "C":
        raise ValueError("완료 상태인 Activity의 Plan End는 변경할 수 없습니다.")

    target_start = target_row["values"][2]
    if not target_start:
        raise ValueError("기준 Plan Start가 없어 Plan End를 변경할 수 없습니다.")
    if date.fromisoformat(selected_date) < date.fromisoformat(target_start):
        raise ValueError("Plan End는 Plan Start보다 빠를 수 없습니다.")

    target_row["values"][3] = selected_date
    sequence = [str(row["id"]) for row in rows if row["id"] != "root"]
    target_index = sequence.index(target_row_id)
    current_start = date.fromisoformat(selected_date)

    for next_row_id in sequence[target_index + 1:]:
        next_row = row_lookup[next_row_id]
        next_row["values"][2] = current_start.isoformat()
        next_end = current_start + timedelta(days=PLAN_STEP_DAYS)
        next_row["values"][3] = next_end.isoformat()
        current_start = next_end

    update_all_parent_plan_dates(rows)
    plan["plan_start"] = rows[1]["values"][2]


def update_actual_date(plan: dict[str, Any], row_id: str, field_name: str, selected_date: str) -> None:
    rows = plan["rows"]
    row_lookup = {str(row["id"]): row for row in rows}
    if not can_edit_actual_dates(rows, row_id):
        raise ValueError("설비명 행과 부모 Activity행의 Actual 날짜는 직접 입력할 수 없습니다.")
    values = row_lookup[row_id]["values"]
    if field_name == "actual_start":
        if values[5] and date.fromisoformat(selected_date) > date.fromisoformat(values[5]):
            raise ValueError("Actual Start는 Actual End보다 늦을 수 없습니다.")
        values[4] = selected_date
    else:
        if values[4] and date.fromisoformat(selected_date) < date.fromisoformat(values[4]):
            raise ValueError("Actual End는 Actual Start보다 빠를 수 없습니다.")
        values[5] = selected_date
    update_parent_actual_dates(rows, row_lookup, row_id)


def mark_activity_complete(plan: dict[str, Any], row_id: str) -> None:
    rows = plan["rows"]
    row_lookup = {str(row["id"]): row for row in rows}
    if row_id == "root":
        raise ValueError("설비명 행은 완료 처리할 수 없습니다.")
    values = row_lookup[row_id]["values"]
    if not values[4] or not values[5]:
        raise ValueError("완료 처리 전 Actual Start와 Actual End를 모두 입력해야 합니다.")
    if row_id in STATUS_SEQUENCE:
        current_index = STATUS_SEQUENCE.index(row_id)
        incomplete_previous = [
            previous_row_id
            for previous_row_id in STATUS_SEQUENCE[:current_index]
            if row_lookup[previous_row_id]["values"][0] != "C" and not has_child_rows(rows, previous_row_id)
        ]
        if incomplete_previous:
            raise ValueError("이전 단계의 Activity가 완료되지 않아 완료 처리할 수 없습니다.")
    values[0] = "C"
    activate_next_activity(row_lookup, row_id)
    auto_complete_parent_activities(rows, row_lookup, row_id)


def touch_plan(plan: dict[str, Any]) -> None:
    plan["updated_at"] = datetime.now().isoformat(timespec="seconds")


def format_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""
    return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def get_row_depth(rows: list[dict[str, Any]], row_id: str) -> int:
    row_lookup = {str(row["id"]): row for row in rows}
    depth = 0
    current_parent = row_lookup[row_id]["parent"]
    while current_parent:
        depth += 1
        current_parent = row_lookup[current_parent]["parent"]
    return max(0, depth - 1)


def get_row_tone(row: dict[str, Any]) -> str:
    if row["id"] == "root":
        return "tone-root"
    if row["parent"] == "root":
        return "tone-parent"
    return "tone-child"


def plan_progress(plan: dict[str, Any]) -> dict[str, int]:
    actionable_rows = [row for row in plan["rows"] if row["id"] != "root"]
    completed = sum(1 for row in actionable_rows if row["values"][0] == "C")
    delayed = sum(1 for row in actionable_rows if calculate_delay(row["values"][3], row["values"][5]))
    in_progress = sum(1 for row in actionable_rows if row["values"][0] == "W")
    duration_total = sum(int(calculate_duration(row["values"][2], row["values"][3]) or "0") for row in actionable_rows)
    duration_completed = sum(
        int(calculate_duration(row["values"][2], row["values"][3]) or "0")
        for row in actionable_rows
        if row["values"][0] == "C"
    )
    return {
        "total": len(actionable_rows),
        "completed": completed,
        "delayed": delayed,
        "in_progress": in_progress,
        "duration_total": duration_total,
        "duration_completed": duration_completed,
    }


def calculate_progress_percent(progress: dict[str, int]) -> int:
    total = progress["duration_total"]
    if total == 0:
        return 0
    return round((progress["duration_completed"] / total) * 100)


def format_dday(plan_end: str) -> str:
    if not plan_end:
        return ""
    remaining_days = (date.fromisoformat(plan_end) - date.today()).days
    if remaining_days == 0:
        return "D-Day"
    if remaining_days > 0:
        return f"D-{remaining_days}"
    return f"D+{abs(remaining_days)}"


def get_progress_dday(plan: dict[str, Any]) -> str:
    actionable_rows = [row for row in plan["rows"] if row["id"] != "root"]
    completed_rows = [row for row in actionable_rows if row["values"][0] == "C"]
    if completed_rows:
        return format_dday(completed_rows[-1]["values"][3])
    current_row = next((row for row in actionable_rows if row["values"][0] == "W"), None)
    if current_row is not None:
        return format_dday(current_row["values"][3])
    if actionable_rows:
        return format_dday(actionable_rows[0]["values"][3])
    return ""


def is_overdue_dday(progress_dday: str) -> bool:
    return progress_dday.startswith("D+")


def get_current_stage(plan: dict[str, Any]) -> str:
    actionable_rows = [row for row in plan["rows"] if row["id"] != "root"]
    current_row = next((row for row in actionable_rows if row["values"][0] == "W"), None)
    if current_row is not None:
        return str(current_row["text"])
    if actionable_rows and all(row["values"][0] == "C" for row in actionable_rows):
        return "완료"
    return "대기"


def is_plan_completed(plan: dict[str, Any]) -> bool:
    actionable_rows = [row for row in plan["rows"] if row["id"] != "root"]
    return bool(actionable_rows) and all(row["values"][0] == "C" for row in actionable_rows)


def build_detail_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = plan["rows"]
    root_duration = calculate_root_duration(rows)
    detail_rows: list[dict[str, Any]] = []
    for row in rows:
        if row["id"] == "root":
            continue
        duration = root_duration if row["id"] == "root" else calculate_duration(row["values"][2], row["values"][3])
        detail_rows.append(
            {
                "id": row["id"],
                "text": row["text"],
                "status": row["values"][0],
                "status_label": format_status_display(row["values"][0]),
                "duration": duration,
                "delay": calculate_delay(row["values"][3], row["values"][5]),
                "plan_start": row["values"][2],
                "plan_end": row["values"][3],
                "actual_start": row["values"][4],
                "actual_end": row["values"][5],
                "depth": get_row_depth(rows, str(row["id"])),
                "tone": get_row_tone(row),
                "editable_plan_dates": row["values"][0] != "C",
                "editable_actual": can_edit_actual_dates(rows, str(row["id"])),
                "has_children": has_child_rows(rows, str(row["id"])),
                "has_delay": bool(calculate_delay(row["values"][3], row["values"][5])),
                "is_completed": row["values"][0] == "C",
            }
        )
    return detail_rows


def build_complete_targets(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"id": str(row["id"]), "text": str(row["text"]) }
        for row in rows
        if row["id"] != "root" and row["values"][0] != "C"
    ]


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    root_row = next(row for row in plan["rows"] if row["id"] == "root")
    progress = plan_progress(plan)
    progress_dday = get_progress_dday(plan)
    is_completed = is_plan_completed(plan)
    return {
        "id": plan["id"],
        "equipment_name": plan["equipment_name"],
        "equipment_spec": plan["equipment_spec"],
        "type_option": plan["type_option"],
        "selection": plan["selection"],
        "created_by": plan.get("created_by", ""),
        "plan_start": root_row["values"][2],
        "plan_end": root_row["values"][3],
        "updated_at": plan["updated_at"],
        "progress": progress,
        "progress_percent": calculate_progress_percent(progress),
        "progress_dday": progress_dday,
        "progress_dday_overdue": is_overdue_dday(progress_dday),
        "is_completed": is_completed,
        "current_stage": get_current_stage(plan),
    }


store = PlanStore(DATA_FILE)
user_store = UserStore(USERS_FILE)


def is_plan_owner(plan: dict[str, Any], login_user: str) -> bool:
    owner = str(plan.get("created_by", "")).strip()
    return bool(owner) and owner == login_user.strip()


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if session.get("logged_in"):
        return redirect(url_for("index"))

    next_target = request.args.get("next", "").strip()
    remembered_name = request.cookies.get("activity_board_login_name", "").strip()
    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        if not employee_id.isdigit():
            flash("사번은 숫자만 입력해 주세요.", "error")
            return render_template(
                "login.html",
                app_version=APP_VERSION,
                next_target=next_target,
                remembered_name=remembered_name,
            )

        user = user_store.find_user_by_employee_id(employee_id)
        if user is not None:
            login_name = str(user.get("name", "")).strip() or "사용자"
            session.clear()
            session["logged_in"] = True
            session["login_user"] = login_name
            session["employee_id"] = employee_id

            submitted_next = request.form.get("next", "").strip()
            if is_safe_redirect_target(submitted_next):
                response = redirect(submitted_next)
            else:
                response = redirect(url_for("index"))
            response.set_cookie("activity_board_login_name", login_name, max_age=60 * 60 * 24 * 30)
            return response

        flash("등록되지 않은 사번입니다.", "error")

    return render_template(
        "login.html",
        app_version=APP_VERSION,
        next_target=next_target,
        remembered_name=remembered_name,
    )


@app.route("/register", methods=["GET", "POST"])
def register_user() -> Any:
    if session.get("logged_in"):
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        employee_id = request.form.get("employee_id", "").strip()

        if not name:
            flash("이름을 입력해 주세요.", "error")
        elif not employee_id:
            flash("사번을 입력해 주세요.", "error")
        else:
            created, message = user_store.create_user(name, employee_id)
            flash(message, "success" if created else "error")
            if created:
                return redirect(url_for("login"))

    return render_template("register.html", app_version=APP_VERSION)


@app.post("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index() -> Any:
    keyword = request.args.get("q", "").strip().casefold()
    status_filter = request.args.get("status", "").strip().casefold()
    plans = [summarize_plan(plan) for plan in store.list_plans()]
    if keyword:
        plans = [plan for plan in plans if keyword in plan["equipment_name"].casefold()]
    stats = {
        "plan_count": len(plans),
        "in_progress_count": sum(1 for plan in plans if plan["progress"]["in_progress"] > 0),
        "completed_count": sum(1 for plan in plans if plan["is_completed"]),
    }
    if status_filter == "in_progress":
        plans = [plan for plan in plans if plan["progress"]["in_progress"] > 0]
    elif status_filter == "completed":
        plans = [plan for plan in plans if plan["is_completed"]]
    return render_template(
        "index.html",
        app_version=APP_VERSION,
        plans=plans,
        stats=stats,
        keyword=keyword,
        status_filter=status_filter,
    )


@app.route("/plans/new", methods=["GET", "POST"])
@login_required
def new_plan() -> Any:
    if request.method == "POST":
        selection = request.form.get("selection", "").strip()
        equipment_spec = request.form.get("equipment_spec", "").strip()
        type_option = request.form.get("type_option", "").strip()
        equipment_name = request.form.get("equipment_name", "").strip()
        plan_start = request.form.get("plan_start", "").strip()
        if selection not in {"Y", "N"}:
            flash("제출 대상 여부를 선택해 주세요.", "error")
        elif not equipment_spec:
            flash("설비 사양을 선택해 주세요.", "error")
        elif not equipment_name:
            flash("설비명을 입력해 주세요.", "error")
        elif not plan_start:
            flash("계획 시작일을 입력해 주세요.", "error")
        elif date.fromisoformat(plan_start) < date.today():
            flash("계획 시작일은 오늘 이전 날짜로 설정할 수 없습니다.", "error")
        else:
            login_name = str(session.get("login_user", "")).strip()
            plan = create_plan_record(selection, equipment_spec, type_option, equipment_name, plan_start, created_by=login_name)
            store.upsert_plan(plan)
            flash("새 계획을 등록했습니다.", "success")
            return redirect(url_for("plan_detail", plan_id=plan["id"]))
    return render_template(
        "new_plan.html",
        app_version=APP_VERSION,
        spec_options=SPEC_OPTIONS,
        reference_rows=REFERENCE_ROWS,
        login_user=str(session.get("login_user", "")),
        today=date.today().isoformat(),
    )


@app.get("/plans/<plan_id>")
@login_required
def plan_detail(plan_id: str) -> Any:
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    login_user = str(session.get("login_user", "")).strip()
    detail_rows = build_detail_rows(plan)
    return render_template(
        "detail.html",
        app_version=APP_VERSION,
        plan=plan,
        created_by=plan.get("created_by", "-"),
        can_delete=is_plan_owner(plan, login_user),
        created_at_display=format_timestamp(plan["created_at"]),
        updated_at_display=format_timestamp(plan["updated_at"]),
        summary=summarize_plan(plan),
        progress=plan_progress(plan),
        rows=detail_rows,
        complete_targets=build_complete_targets(plan["rows"]),
        today=date.today().isoformat(),
    )


@app.post("/plans/<plan_id>/delete")
@login_required
def delete_plan_route(plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))

    login_user = str(session.get("login_user", "")).strip()
    if not is_plan_owner(plan, login_user):
        flash("등록자만 아이템을 삭제할 수 있습니다.", "error")
        return redirect(url_for("plan_detail", plan_id=plan_id))

    deleted = store.delete_plan(plan_id)
    if not deleted:
        flash("아이템 삭제에 실패했습니다. 다시 시도해 주세요.", "error")
        return redirect(url_for("plan_detail", plan_id=plan_id))

    flash("아이템을 삭제했습니다.", "success")
    return redirect(url_for("index"))


@app.post("/plans/<plan_id>/rows/<row_id>/plan-start")
@login_required
def update_plan_start_route(plan_id: str, row_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    try:
        update_plan_start(plan, row_id, request.form.get("plan_start", "").strip())
        touch_plan(plan)
        store.upsert_plan(plan)
        flash("Plan Start를 갱신했습니다.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("plan_detail", plan_id=plan_id))


@app.post("/plans/<plan_id>/rows/<row_id>/plan-end")
@login_required
def update_plan_end_route(plan_id: str, row_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    try:
        update_plan_end(plan, row_id, request.form.get("plan_end", "").strip())
        touch_plan(plan)
        store.upsert_plan(plan)
        flash("Plan End를 갱신했습니다.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("plan_detail", plan_id=plan_id))


@app.post("/plans/<plan_id>/rows/<row_id>/actual-date")
@login_required
def update_actual_date_route(plan_id: str, row_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    field_name = request.form.get("field_name", "").strip()
    selected_date = request.form.get("selected_date", "").strip()
    confirm_complete = request.form.get("confirm_complete", "").strip() == "1"
    try:
        if field_name not in {"actual_start", "actual_end"}:
            raise ValueError("수정할 Actual 날짜 필드가 올바르지 않습니다.")
        update_actual_date(plan, row_id, field_name, selected_date)
        if field_name == "actual_end" and confirm_complete:
            mark_activity_complete(plan, row_id)
        touch_plan(plan)
        store.upsert_plan(plan)
        if field_name == "actual_end" and confirm_complete:
            flash("Actual End 입력으로 Activity를 완료 처리했습니다.", "success")
        else:
            flash("Actual 날짜를 갱신했습니다.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("plan_detail", plan_id=plan_id))


@app.post("/plans/<plan_id>/rows/<row_id>/complete")
@login_required
def mark_complete_route(plan_id: str, row_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    try:
        mark_activity_complete(plan, row_id)
        touch_plan(plan)
        store.upsert_plan(plan)
        flash("Activity를 완료 처리했습니다.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("plan_detail", plan_id=plan_id))


@app.post("/plans/<plan_id>/complete")
@login_required
def mark_selected_complete_route(plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        flash("요청한 계획을 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))

    selected_row_ids = [row_id.strip() for row_id in request.form.getlist("row_ids") if row_id.strip()]
    if not selected_row_ids:
        flash("완료 처리할 Activity를 체크해 주세요.", "error")
        return redirect(url_for("plan_detail", plan_id=plan_id))
    if len(selected_row_ids) > 1:
        flash("한 번에 하나의 Activity만 완료 처리할 수 있습니다.", "error")
        return redirect(url_for("plan_detail", plan_id=plan_id))

    row_id = selected_row_ids[0]

    try:
        mark_activity_complete(plan, row_id)
        touch_plan(plan)
        store.upsert_plan(plan)
        flash("선택한 Activity를 완료 처리했습니다.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("plan_detail", plan_id=plan_id))


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


def get_server_host() -> str:
    return os.environ.get("ACTIVITY_BOARD_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def get_server_port() -> int:
    # Managed hosting platforms usually expose the HTTP port as PORT.
    port_text = (
        os.environ.get("ACTIVITY_BOARD_PORT")
        or os.environ.get("PORT")
        or str(DEFAULT_PORT)
    ).strip()
    try:
        return int(port_text)
    except ValueError as exc:
        raise ValueError("ACTIVITY_BOARD_PORT 또는 PORT는 숫자여야 합니다.") from exc


def serve_app() -> None:
    host = get_server_host()
    port = get_server_port()
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port, debug=False)
        return
    serve(app, host=host, port=port)


if __name__ == "__main__":
    serve_app()
