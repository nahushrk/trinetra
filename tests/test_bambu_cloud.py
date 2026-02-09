"""Tests for Bambu cloud integration components."""

from unittest.mock import patch

from trinetra.integrations.bambu.api import BambuCloudAPI
from trinetra.integrations.bambu.plugin import BambuIntegration


class TestBambuCloudAPI:
    def test_get_history_maps_tasks_into_jobs(self):
        api = BambuCloudAPI(access_token="token")
        with patch.object(
            api,
            "get_tasks",
            return_value=[
                {
                    "id": "job-1",
                    "title": "sample_file.gcode",
                    "status": "finished",
                    "cost_time": 120,
                    "length": 300,
                    "start_time": 1735689600,
                    "end_time": 1735689720,
                }
            ],
        ):
            history = api.get_history(limit=10)

        assert "jobs" in history
        assert len(history["jobs"]) == 1
        first = history["jobs"][0]
        assert first["job_id"] == "job-1"
        assert first["filename"] == "sample_file.gcode"
        assert first["status"] == "completed"


class TestBambuIntegration:
    def test_get_settings_cloud(self):
        integration = BambuIntegration()
        runtime = {
            "integrations": {
                "bambu": {
                    "enabled": True,
                    "mode": "cloud",
                    "cloud": {
                        "access_token": "a",
                        "refresh_token": "b",
                        "region": "global",
                    },
                }
            }
        }

        settings = integration.get_settings(runtime)
        assert settings.enabled is True
        assert settings.mode == "cloud"
        assert settings.configured is True

    def test_fetch_history_events_requires_event_id(self):
        integration = BambuIntegration()
        runtime = {
            "integrations": {
                "bambu": {
                    "enabled": True,
                    "mode": "cloud",
                    "cloud": {"access_token": "a", "refresh_token": "", "region": "global"},
                }
            }
        }

        mock_client = BambuCloudAPI(access_token="a")
        with patch.object(integration, "create_client", return_value=mock_client):
            with patch.object(
                mock_client,
                "get_tasks",
                return_value=[
                    {"title": "no-id.gcode", "status": "finished"},
                    {
                        "id": "evt-2",
                        "title": "with-id.gcode",
                        "status": "finished",
                        "cost_time": 10,
                    },
                ],
            ):
                events = integration.fetch_history_events(runtime)

        assert len(events) == 1
        assert events[0]["event_uid"] == "evt-2"
        assert events[0]["file_name"] == "with-id.gcode"

    def test_fetch_history_events_normalizes_camel_case_fields(self):
        integration = BambuIntegration()
        runtime = {
            "integrations": {
                "bambu": {
                    "enabled": True,
                    "mode": "cloud",
                    "cloud": {"access_token": "a", "refresh_token": "", "region": "global"},
                }
            }
        }

        mock_client = BambuCloudAPI(access_token="a")
        with patch.object(integration, "create_client", return_value=mock_client):
            with patch.object(
                mock_client,
                "get_tasks",
                return_value=[
                    {
                        "id": "evt-3",
                        "title": "leaf_lamp.gcode",
                        "status": 2,
                        "startTime": "2025-11-17T04:15:25Z",
                        "endTime": "2025-11-17T04:31:07Z",
                        "costTime": 849,
                        "length": 100,
                        "deviceId": "00M09D551000876",
                    }
                ],
            ):
                events = integration.fetch_history_events(runtime)

        assert len(events) == 1
        event = events[0]
        assert event["event_uid"] == "evt-3"
        assert event["status"] == "completed"
        assert event["duration_seconds"] == 849
        assert event["filament_used_mm"] == 100
        assert event["printer_uid"] == "00M09D551000876"
        assert event["event_at"] is not None
