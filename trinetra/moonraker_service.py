"""Modular service for querying moonraker and managing file statistics."""

import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from .models import GCodeFile, GCodeFileStats
from .moonraker import MoonrakerAPI

logger = logging.getLogger(__name__)


class MoonrakerService:
    """Service for handling moonraker queries and file statistics management."""

    def __init__(self, moonraker_client: MoonrakerAPI):
        self.client = moonraker_client

    def fetch_all_file_statistics(self) -> Dict[str, Dict[str, Any]]:
        """Fetch statistics for all files from moonraker in a single query."""
        try:
            logger.debug("Fetching history from Moonraker")
            # Query moonraker history for all files with high limit
            history_response = self.client.get_history(limit=1000)
            logger.debug(f"History response: {history_response}")

            if not history_response:
                logger.debug("No history response")
                return {}

            jobs = history_response["result"].get("jobs", [])

            # Group jobs by filename for efficient processing
            file_stats_map = {}

            for job in jobs:
                filename = job.get("filename")
                if not filename:
                    continue

                if filename not in file_stats_map:
                    file_stats_map[filename] = {
                        "jobs": [],
                        "print_count": 0,
                        "total_print_time": 0.0,
                        "total_filament_used": 0.0,
                        "successful_prints": 0,
                        "last_job": None,
                    }

                file_stats_map[filename]["jobs"].append(job)

            # Calculate statistics for each file
            result = {}
            for filename, stats in file_stats_map.items():
                jobs = stats["jobs"]

                stats["print_count"] = len(jobs)
                stats["total_print_time"] = sum(job.get("print_duration", 0) for job in jobs)
                stats["total_filament_used"] = sum(job.get("filament_used", 0) for job in jobs)

                successful_jobs = [job for job in jobs if job.get("status") == "completed"]
                stats["successful_prints"] = len(successful_jobs)

                # Get the most recent job
                # For jobs with null end_time:
                # - If status is "in_progress", use current time
                # - Otherwise, use 0
                def get_effective_end_time(job):
                    end_time = job.get("end_time")
                    if end_time is not None:
                        return end_time
                    if job.get("status") == "in_progress":
                        return time.time()
                    return 0
                
                last_job = max(jobs, key=get_effective_end_time)
                stats["last_job"] = last_job

                # Calculate final statistics
                result[filename] = {
                    "print_count": stats["print_count"],
                    "total_print_time": stats["total_print_time"],
                    "total_filament_used": stats["total_filament_used"],
                    "success_rate": len(successful_jobs) / stats["print_count"]
                    if stats["print_count"] > 0
                    else 0.0,
                    "last_print_date": datetime.fromtimestamp(get_effective_end_time(last_job)),
                    "job_id": last_job.get("job_id"),
                    "last_status": last_job.get("status"),
                }

            return result

        except Exception as e:
            logger.error(f"Error fetching file statistics: {e}")
            return {}

    def update_all_file_stats(self, db_session: Session) -> Dict[str, int]:
        """Update statistics for all gcode files in the database."""
        try:
            # Fetch all statistics in one go
            all_stats = self.fetch_all_file_statistics()
            logger.debug(f"Fetched {len(all_stats)} files from Moonraker")

            gcode_files = db_session.query(GCodeFile).all()
            logger.debug(f"Found {len(gcode_files)} G-code files in database")
            updated_count = 0
            failed_count = 0

            for gcode_file in gcode_files:
                try:
                    stats_data = all_stats.get(gcode_file.file_name)
                    if not stats_data:
                        # No stats available for this file
                        logger.debug(f"No stats found for {gcode_file.file_name}")
                        continue

                    logger.debug(f"Updating stats for {gcode_file.file_name}: {stats_data}")

                    # Check if stats already exist
                    file_stats = (
                        db_session.query(GCodeFileStats)
                        .filter(GCodeFileStats.gcode_file_id == gcode_file.id)
                        .first()
                    )

                    if file_stats:
                        # Update existing stats
                        logger.debug(f"Updating existing stats for {gcode_file.file_name}")
                        file_stats.print_count = stats_data["print_count"]
                        file_stats.total_print_time = stats_data["total_print_time"]
                        file_stats.total_filament_used = stats_data["total_filament_used"]
                        file_stats.last_print_date = stats_data["last_print_date"]
                        file_stats.success_rate = stats_data["success_rate"]
                        file_stats.job_id = stats_data["job_id"]
                        file_stats.last_status = stats_data["last_status"]
                    else:
                        # Create new stats
                        logger.debug(f"Creating new stats for {gcode_file.file_name}")
                        file_stats = GCodeFileStats(
                            gcode_file_id=gcode_file.id,
                            print_count=stats_data["print_count"],
                            total_print_time=stats_data["total_print_time"],
                            total_filament_used=stats_data["total_filament_used"],
                            last_print_date=stats_data["last_print_date"],
                            success_rate=stats_data["success_rate"],
                            job_id=stats_data["job_id"],
                            last_status=stats_data["last_status"],
                        )
                        db_session.add(file_stats)

                    updated_count += 1

                except Exception as e:
                    logger.error(f"Error updating stats for {gcode_file.filename}: {e}")
                    failed_count += 1
                    db_session.rollback()

            db_session.commit()
            return {"updated": updated_count, "failed": failed_count}

        except Exception as e:
            logger.error(f"Error updating all file stats: {e}")
            db_session.rollback()
            return {"updated": 0, "failed": 0}

    def reload_moonraker_only(self, db_session: Session) -> Dict[str, int]:
        """Reload only moonraker statistics without touching files."""
        return self.update_all_file_stats(db_session)

    def get_file_with_stats(self, db_session: Session, file_id: int) -> Optional[GCodeFile]:
        """Get a gcode file with its statistics pre-loaded."""
        return db_session.query(GCodeFile).filter(GCodeFile.id == file_id).first()

    def get_files_with_stats(
        self, db_session: Session, folder: Optional[str] = None
    ) -> List[GCodeFile]:
        """Get gcode files with their statistics pre-loaded."""
        query = db_session.query(GCodeFile).outerjoin(
            GCodeFileStats, GCodeFile.id == GCodeFileStats.gcode_file_id
        )

        if folder:
            query = query.filter(GCodeFile.folder == folder)

        return query.all()
