"""Tests that the per-worker database connection budget is enforced."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import app as world_pulse


class DatabaseConnectionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.old_wait = world_pulse.DB_CONNECTION_WAIT_SECONDS
        self.old_retry_after = world_pulse._DB_RETRY_AFTER
        self.old_status = dict(world_pulse._LAST_DB_STATUS)
        world_pulse.DB_CONNECTION_WAIT_SECONDS = 0
        world_pulse._DB_RETRY_AFTER = 0.0

    def tearDown(self):
        world_pulse.DB_CONNECTION_WAIT_SECONDS = self.old_wait
        world_pulse._DB_RETRY_AFTER = self.old_retry_after
        world_pulse._LAST_DB_STATUS.clear()
        world_pulse._LAST_DB_STATUS.update(self.old_status)

    def _take_all_slots(self):
        taken = 0
        while taken < world_pulse.DB_MAX_CONCURRENT_CONNECTIONS:
            if not world_pulse._DB_CONNECTION_SLOTS.acquire(blocking=False):
                break
            taken += 1
        return taken

    def test_connection_is_deferred_when_local_budget_is_full(self):
        taken = self._take_all_slots()
        self.assertEqual(taken, world_pulse.DB_MAX_CONCURRENT_CONNECTIONS)
        try:
            with patch.object(world_pulse, "_database_url", return_value="postgresql://example"):
                with patch.object(world_pulse.psycopg2, "connect") as connect:
                    self.assertIsNone(world_pulse._connect_db())
                    connect.assert_not_called()
                    self.assertEqual(
                        world_pulse._LAST_DB_STATUS.get("error_code"),
                        "local_connection_limit",
                    )
        finally:
            for _ in range(taken):
                world_pulse._DB_CONNECTION_SLOTS.release()

    def test_releasing_connection_returns_its_slot(self):
        fake_connection = MagicMock()
        with patch.object(world_pulse, "_database_url", return_value="postgresql://example"):
            with patch.object(world_pulse.psycopg2, "connect", return_value=fake_connection):
                connection = world_pulse._connect_db()
        self.assertIs(connection, fake_connection)
        world_pulse._release_db_connection(connection)
        fake_connection.close.assert_called_once()

        taken = self._take_all_slots()
        try:
            self.assertEqual(taken, world_pulse.DB_MAX_CONCURRENT_CONNECTIONS)
        finally:
            for _ in range(taken):
                world_pulse._DB_CONNECTION_SLOTS.release()


if __name__ == "__main__":
    unittest.main()
