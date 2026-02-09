"""Tests for connector history-backed statistics aggregation."""

import os
import shutil
import tempfile
import unittest

from trinetra.database import DatabaseManager


class TestHistoryBackedStats(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db_manager = DatabaseManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_printing_stats_and_calendar_are_derived_from_history_events(self):
        events = [
            {
                "event_uid": "evt-1",
                "printer_uid": "printer-a",
                "status": "2",
                "event_at": "2025-01-01T10:00:00Z",
                "duration_seconds": 3600,
                "filament_used_mm": 1000,
            },
            {
                "event_uid": "evt-2",
                "printer_uid": "printer-a",
                "status": "3",
                "event_at": "2025-01-01T11:00:00Z",
                "duration_seconds": 1800,
                "filament_used_mm": 500,
            },
            {
                # Millisecond epoch should be normalized to seconds.
                "event_uid": "evt-3",
                "printer_uid": "printer-a",
                "status": "completed",
                "event_at": 1735776000000,
                "duration_seconds": 1800,
                "filament_used_mm": 500,
            },
        ]

        sync_result = self.db_manager.sync_print_history_events(
            integration_id="bambu",
            integration_mode="cloud",
            events=events,
        )

        self.assertEqual(sync_result["inserted"], 3)

        stats = self.db_manager.get_printing_stats()
        self.assertEqual(stats["total_prints"], 3)
        self.assertEqual(stats["successful_prints"], 2)
        self.assertEqual(stats["canceled_prints"], 1)
        self.assertAlmostEqual(stats["avg_print_time_hours"], (3600 + 1800 + 1800) / 3 / 3600)
        self.assertAlmostEqual(stats["total_filament_meters"], 2.0)
        self.assertEqual(stats["print_days"], 2)

        calendar = self.db_manager.get_activity_calendar()
        self.assertEqual(calendar["2025-01-01"], 2)
        self.assertEqual(calendar["2025-01-02"], 1)

    def test_calendar_falls_back_to_raw_payload_timestamps(self):
        events = [
            {
                "event_uid": "evt-raw-1",
                "printer_uid": "printer-a",
                "status": "2",
                "raw_payload": {"startTime": "2025-11-17T04:15:25Z", "endTime": "2025-11-17T04:31:07Z"},
            }
        ]
        sync_result = self.db_manager.sync_print_history_events(
            integration_id="bambu",
            integration_mode="cloud",
            events=events,
        )
        self.assertEqual(sync_result["inserted"], 1)

        stats = self.db_manager.get_printing_stats()
        self.assertEqual(stats["total_prints"], 1)
        self.assertEqual(stats["print_days"], 1)

        calendar = self.db_manager.get_activity_calendar()
        self.assertEqual(sum(calendar.values()), 1)
        self.assertEqual(len(calendar), 1)


if __name__ == "__main__":
    unittest.main()
