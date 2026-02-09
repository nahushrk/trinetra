"""Bambu cloud API client for telemetry/history sync."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import requests

from trinetra.logger import get_logger

logger = get_logger(__name__)


_BAMBU_API_BASE = {
    "global": "https://api.bambulab.com",
    "cn": "https://api.bambulab.cn",
    "china": "https://api.bambulab.cn",
}

_SUCCESS_STATUS = {"finished", "completed", "success", "succeeded"}
_CANCELED_STATUS = {"cancelled", "canceled", "failed", "aborted"}


class BambuCloudAPI:
    """Cloud client for Bambu telemetry APIs."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str = "",
        region: str = "global",
        timeout: int = 15,
    ) -> None:
        self.access_token = access_token.strip()
        self.refresh_token = refresh_token.strip()
        self.region = region.strip().lower() or "global"
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def base_url(self) -> str:
        return _BAMBU_API_BASE.get(self.region, _BAMBU_API_BASE["global"])

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        retry_on_auth: bool = True,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(
                method,
                url,
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
            if response.status_code == 401 and retry_on_auth and self.refresh_token:
                logger.info("Bambu cloud token expired, attempting refresh")
                if self.refresh_access_token():
                    return self._request(
                        method,
                        endpoint,
                        retry_on_auth=False,
                        **kwargs,
                    )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Bambu cloud request failed for %s: %s", url, exc)
            return None
        except ValueError as exc:
            logger.error("Bambu cloud JSON parse failed for %s: %s", url, exc)
            return None

    def refresh_access_token(self) -> bool:
        """Refresh access token using refresh token when supported by cloud API."""
        if not self.refresh_token:
            return False

        url = f"{self.base_url}/v1/user-service/user/refreshtoken"
        payload = {"refreshToken": self.refresh_token}
        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json() or {}
            # API responses vary: direct fields or nested data/result.
            token_data = data.get("data") or data.get("result") or data
            new_access = str(token_data.get("accessToken") or token_data.get("access_token") or "").strip()
            new_refresh = str(token_data.get("refreshToken") or token_data.get("refresh_token") or "").strip()
            if not new_access:
                logger.error("Bambu token refresh returned no access token")
                return False
            self.access_token = new_access
            if new_refresh:
                self.refresh_token = new_refresh
            return True
        except requests.exceptions.RequestException as exc:
            logger.error("Bambu token refresh failed: %s", exc)
            return False
        except ValueError as exc:
            logger.error("Bambu token refresh JSON parse failed: %s", exc)
            return False

    def get_tasks(self, limit: int = 500, device_id: str = "") -> List[Dict[str, Any]]:
        """Fetch cloud task history entries."""
        params: Dict[str, Any] = {"limit": limit}
        if device_id:
            params["deviceId"] = device_id

        payload = self._request("GET", "/v1/user-service/my/tasks", params=params)
        if not payload:
            return []

        return _extract_list(payload, preferred_keys=("hits", "tasks", "items", "list"))

    def get_devices(self) -> List[Dict[str, Any]]:
        """Fetch bound devices for cloud account."""
        payload = self._request("GET", "/v1/iot-service/api/user/bind")
        if not payload:
            return []

        return _extract_list(payload, preferred_keys=("devices", "hits", "items", "list"))

    # Protocol compatibility (current app still expects these methods on clients).
    def get_history(self, limit: int = 1000) -> Dict[str, List[Dict[str, Any]]]:
        tasks = self.get_tasks(limit=limit)
        jobs: List[Dict[str, Any]] = []
        for task in tasks:
            status = _normalize_status(task)
            duration = _to_float(
                task.get("costTime")
                or task.get("cost_time")
                or task.get("printDuration")
                or task.get("print_duration")
                or 0.0
            )
            filament_used = _to_float(
                task.get("length") or task.get("filamentUsed") or task.get("filament_used") or 0.0
            )
            start_time = _to_epoch(task.get("startTime") or task.get("start_time"))
            end_time = _to_epoch(task.get("endTime") or task.get("end_time"))
            filename = _extract_filename(task)
            job_id = str(
                task.get("id") or task.get("task_id") or task.get("taskId") or task.get("job_id") or ""
            )
            jobs.append(
                {
                    "filename": filename,
                    "status": status,
                    "print_duration": duration,
                    "filament_used": filament_used,
                    "start_time": start_time,
                    "end_time": end_time,
                    "job_id": job_id,
                }
            )
        return {"jobs": jobs}

    def queue_job(self, filenames: Sequence[str], reset: bool = False) -> bool:
        logger.warning("Bambu cloud mode is telemetry-only; queue_job is unsupported")
        return False



def _extract_list(payload: Dict[str, Any], preferred_keys: Sequence[str]) -> List[Dict[str, Any]]:
    candidates: List[Any] = [payload]
    nested = payload.get("data")
    if isinstance(nested, dict):
        candidates.append(nested)
    nested_result = payload.get("result")
    if isinstance(nested_result, dict):
        candidates.append(nested_result)

    for candidate in candidates:
        for key in preferred_keys:
            value = candidate.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]

    for candidate in candidates:
        for value in candidate.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return [entry for entry in value if isinstance(entry, dict)]

    return []



def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _to_epoch(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        if abs(numeric) > 1e11:
            numeric /= 1000.0
        return numeric
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            numeric = float(raw)
            if abs(numeric) > 1e11:
                numeric /= 1000.0
            return numeric
        except ValueError:
            pass
        parsed = _parse_datetime(raw)
        if parsed is None:
            return 0.0
        return parsed.timestamp()
    return 0.0



def _parse_datetime(raw: str) -> Optional[datetime]:
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None



def _normalize_status(task: Dict[str, Any]) -> str:
    raw_status = task.get("status") or task.get("state") or "unknown"
    if isinstance(raw_status, (int, float)):
        status_code = int(raw_status)
        if status_code == 2:
            return "completed"
        if status_code in {3, 4}:
            return "cancelled"
        return str(status_code)
    status = str(raw_status).strip().lower()
    if status.isdigit():
        status_code = int(status)
        if status_code == 2:
            return "completed"
        if status_code in {3, 4}:
            return "cancelled"
        return status
    if status in _SUCCESS_STATUS:
        return "completed"
    if status in _CANCELED_STATUS:
        return "cancelled"
    return status



def _extract_filename(task: Dict[str, Any]) -> str:
    keys = (
        "filename",
        "file_name",
        "fileName",
        "gcode_name",
        "gcodeName",
        "project_name",
        "projectName",
        "title",
        "design_title",
        "designTitle",
    )
    for key in keys:
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
