from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    data_file = base_dir / "activity_board_data.json"
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise SystemExit("DATABASE_URL 환경변수를 설정해 주세요.")
    if not data_file.exists():
        raise SystemExit(f"데이터 파일이 없습니다: {data_file}")

    with data_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    plans = payload.get("plans", [])

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

    print(f"완료: {len(plans)}건 이관")


if __name__ == "__main__":
    main()
