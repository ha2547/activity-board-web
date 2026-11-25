from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    data_file = base_dir / "activity_board_data.json"
    users_file = base_dir / "activity_board_users.json"
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise SystemExit("DATABASE_URL 환경변수를 설정해 주세요.")
    if not data_file.exists():
        raise SystemExit(f"데이터 파일이 없습니다: {data_file}")

    with data_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    plans = payload.get("plans", [])

    users: list[dict] = []
    if users_file.exists():
        with users_file.open("r", encoding="utf-8") as f:
            users_payload = json.load(f)
        loaded_users = users_payload.get("users", [])
        if isinstance(loaded_users, list):
            users = loaded_users

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    payload JSONB NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    employee_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            for plan in plans:
                cur.execute(
                    """
                    INSERT INTO plans (plan_id, payload)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (plan_id)
                    DO UPDATE SET payload = EXCLUDED.payload
                    """,
                    (plan["id"], json.dumps(plan, ensure_ascii=False)),
                )

            for user in users:
                name = str(user.get("name", "")).strip()
                employee_id = str(user.get("employee_id", "")).strip()
                created_at = str(user.get("created_at", "")).strip() or None
                if not name or not employee_id:
                    continue

                cur.execute(
                    """
                    INSERT INTO users (employee_id, name, created_at)
                    VALUES (%s, %s, COALESCE(%s::timestamptz, NOW()))
                    ON CONFLICT (employee_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        created_at = EXCLUDED.created_at
                    """,
                    (employee_id, name, created_at),
                )

    print(f"완료: plans {len(plans)}건, users {len(users)}건 이관")


if __name__ == "__main__":
    main()
