from __future__ import annotations

import json
import unittest

from download_manager import PostgresHistoryStore


class FakeCursor:
    def __init__(self, select_rows: list[tuple[str]] | None = None) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.select_rows = select_rows or []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executions.append((" ".join(sql.split()), params))

    def fetchall(self) -> list[tuple[str]]:
        return self.select_rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class PostgresHistoryStoreTests(unittest.TestCase):
    def test_add_entry_serializes_payload_for_neon_jsonb(self) -> None:
        cursor = FakeCursor()
        store = PostgresHistoryStore(
            "postgresql://user:pass@example.test/db?sslmode=require",
            connect_factory=lambda _: FakeConnection(cursor),
        )
        cursor.executions.clear()

        store.add_entry(
            {
                "id": "job123",
                "title": "Musica",
                "completed_at": "2026-07-01T10:00:00",
            }
        )

        insert_calls = [
            item for item in cursor.executions if item[0].startswith("INSERT INTO")
        ]
        self.assertEqual(len(insert_calls), 1)
        self.assertEqual(insert_calls[0][1][0], "job123")
        self.assertEqual(insert_calls[0][1][1], "2026-07-01T10:00:00")
        self.assertEqual(json.loads(str(insert_calls[0][1][2]))["title"], "Musica")

    def test_list_entries_reads_jsonb_payloads_in_recent_order(self) -> None:
        cursor = FakeCursor(
            select_rows=[
                (
                    json.dumps(
                        {
                            "id": "job123",
                            "title": "Video",
                            "completed_at": "2026-07-01T10:00:00",
                        }
                    ),
                )
            ]
        )
        store = PostgresHistoryStore(
            "postgresql://user:pass@example.test/db?sslmode=require",
            connect_factory=lambda _: FakeConnection(cursor),
        )

        entries = store.list_entries()

        self.assertEqual(entries[0]["id"], "job123")
        self.assertEqual(entries[0]["title"], "Video")

    def test_clear_entries_deletes_download_history_rows(self) -> None:
        cursor = FakeCursor()
        store = PostgresHistoryStore(
            "postgresql://user:pass@example.test/db?sslmode=require",
            connect_factory=lambda _: FakeConnection(cursor),
        )
        cursor.executions.clear()

        store.clear()

        delete_calls = [
            item
            for item in cursor.executions
            if item[0].startswith("DELETE FROM download_history")
        ]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(delete_calls[0][1], ())


if __name__ == "__main__":
    unittest.main()
