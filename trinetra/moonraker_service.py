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
        logger.debug("Starting fetch_all_file_statistics")
        try:
            logger.debug("Fetching history from Moonraker")
            # Query moonraker history for all files with high limit
            history_response = self.client.get_history(limit=1000)
            logger.debug(f"History response type: {type(history_response)}")
            logger.debug(
                f"History response keys: {history_response.keys() if isinstance(history_response, dict) else 'Not a dict'}"
            )
            logger.debug(f"History response: {history_response}")

            if not history_response:
                logger.debug("No history response")
                return {}

            # The get_history method returns the result directly, not wrapped in a result key
            # Check if response has the expected structure
            if "jobs" not in history_response:
                logger.error(f"Unexpected response format: {history_response}")
                return {}

            jobs = history_response.get("jobs", [])
            logger.debug(f"Found {len(jobs)} jobs in history response")

            # Group jobs by filename for efficient processing
            file_stats_map = {}
            logger.debug("Starting to group jobs by filename")

            for i, job in enumerate(jobs):
                try:
                    filename = job.get("filename")
                    logger.debug(f"Processing job {i}, filename: {filename}")
                    if not filename:
                        logger.debug(f"Skipping job {i} with no filename")
                        continue

                    if filename not in file_stats_map:
                        file_stats_map[filename] = {
                            "jobs": [],
                            "print_count": 0,
                            "total_print_time": 0.0,
                            "total_filament_used": 0.0,
                            "successful_prints": 0,
                            "canceled_prints": 0,
                            "last_job": None,
                        }

                    file_stats_map[filename]["jobs"].append(job)
                    logger.debug(f"Added job {i} to file {filename}")
                except Exception as job_e:
                    logger.error(f"Error processing job {i}: {job_e}")
                    continue

            logger.debug(f"Grouped jobs into {len(file_stats_map)} files")

            # Calculate statistics for each file
            result = {}
            logger.debug("Starting to calculate statistics for each file")

            for filename, stats in file_stats_map.items():
                try:
                    logger.debug(f"Processing file: {filename}")
                    jobs = stats["jobs"]
                    logger.debug(f"File {filename} has {len(jobs)} jobs")

                    stats["print_count"] = len(jobs)
                    logger.debug(f"Set print_count for {filename}: {stats['print_count']}")

                    stats["total_print_time"] = sum(job.get("print_duration", 0) for job in jobs)
                    logger.debug(
                        f"Set total_print_time for {filename}: {stats['total_print_time']}"
                    )

                    stats["total_filament_used"] = sum(job.get("filament_used", 0) for job in jobs)
                    logger.debug(
                        f"Set total_filament_used for {filename}: {stats['total_filament_used']}"
                    )

                    successful_jobs = [job for job in jobs if job.get("status") == "completed"]
                    stats["successful_prints"] = len(successful_jobs)
                    logger.debug(
                        f"File {filename} has {stats['successful_prints']} successful prints out of {stats['print_count']} total"
                    )

                    # Calculate canceled prints
                    canceled_jobs = [job for job in jobs if job.get("status") == "cancelled"]
                    stats["canceled_prints"] = len(canceled_jobs)
                    logger.debug(
                        f"File {filename} has {stats['canceled_prints']} canceled prints out of {stats['print_count']} total"
                    )

                    # Get the most recent job
                    # For jobs with null end_time:
                    # - If status is "in_progress", use current time
                    # - Otherwise, use 0
                    def get_effective_end_time(job):
                        end_time = job.get("end_time")
                        logger.debug(
                            f"Job {job.get('job_id')} end_time: {end_time}, status: {job.get('status')}"
                        )
                        # Handle various null representations
                        if end_time is None or end_time == "null" or end_time == "":
                            if job.get("status") == "in_progress":
                                current_time = time.time()
                                logger.debug(
                                    f"Job {job.get('job_id')} is in progress, using current time: {current_time}"
                                )
                                return current_time
                            logger.debug(
                                f"Job {job.get('job_id')} has null end_time and is not in progress, using 0"
                            )
                            return 0

                        # Handle string representations of numbers
                        if isinstance(end_time, str):
                            try:
                                end_time = float(end_time)
                                logger.debug(f"Converted string end_time to float: {end_time}")
                            except ValueError:
                                logger.error(
                                    f"Invalid end_time string for job {job.get('job_id')}: {end_time}"
                                )
                                return 0

                        # Ensure end_time is a valid number
                        if not isinstance(end_time, (int, float)):
                            logger.error(
                                f"Invalid end_time type for job {job.get('job_id')}: {type(end_time)}"
                            )
                            return 0

                        logger.debug(f"Job {job.get('job_id')} has end_time: {end_time}")
                        return end_time

                    # Log all effective end times before finding max
                    logger.debug(
                        f"Calculating effective end times for {len(jobs)} jobs in file {filename}"
                    )
                    effective_end_times = []
                    for job in jobs:
                        try:
                            end_time = get_effective_end_time(job)
                            effective_end_times.append((job.get("job_id", "unknown"), end_time))
                            logger.debug(
                                f"Job {job.get('job_id', 'unknown')} effective end time: {end_time}"
                            )
                        except Exception as time_e:
                            logger.error(
                                f"Error calculating effective end time for job {job.get('job_id', 'unknown')}: {time_e}"
                            )
                            logger.error(f"Job details: {job}")

                    logger.debug(f"Effective end times for {filename}: {effective_end_times}")

                    try:
                        last_job = max(jobs, key=get_effective_end_time)
                        stats["last_job"] = last_job
                        logger.debug(f"Last job for {filename}: {last_job.get('job_id')}")
                    except Exception as max_e:
                        logger.error(f"Error finding max job for {filename}: {max_e}")
                        logger.error(f"Jobs for {filename}: {jobs}")
                        # Use the first job as fallback
                        if jobs:
                            last_job = jobs[0]
                            stats["last_job"] = last_job
                            logger.debug(
                                f"Using first job as fallback for {filename}: {last_job.get('job_id')}"
                            )
                        else:
                            logger.error(f"No jobs found for {filename}")
                            continue

                    # Calculate final statistics
                    effective_end_time = get_effective_end_time(last_job)
                    logger.debug(
                        f"Processing file {filename}, effective_end_time: {effective_end_time}"
                    )

                    # Check if effective_end_time is valid for datetime conversion
                    if not isinstance(effective_end_time, (int, float)) or effective_end_time < 0:
                        logger.error(
                            f"Invalid effective_end_time for {filename}: {effective_end_time}"
                        )
                        logger.error(f"Last job details: {last_job}")
                        continue

                    try:
                        last_print_date = datetime.fromtimestamp(effective_end_time)
                        logger.debug(f"Last print date for {filename}: {last_print_date}")
                    except Exception as date_e:
                        logger.error(
                            f"Error converting effective_end_time to datetime for {filename}: {date_e}"
                        )
                        logger.error(f"Effective end time value: {effective_end_time}")
                        logger.error(f"Last job details: {last_job}")
                        continue

                    # Calculate success rate
                    success_rate = (
                        len(successful_jobs) / stats["print_count"]
                        if stats["print_count"] > 0
                        else 0.0
                    )
                    logger.debug(f"Calculated success_rate for {filename}: {success_rate}")

                    result[filename] = {
                        "print_count": stats["print_count"],
                        "successful_prints": stats["successful_prints"],
                        "canceled_prints": stats["canceled_prints"],
                        "total_print_time": stats["total_print_time"],
                        "total_filament_used": stats["total_filament_used"],
                        "success_rate": success_rate,
                        "last_print_date": last_print_date,
                        "job_id": last_job.get("job_id"),
                        "last_status": last_job.get("status"),
                    }
                    logger.debug(f"Successfully processed file {filename}")
                except Exception as file_e:
                    logger.error(f"Error processing file {filename}: {file_e}")
                    logger.error(f"File stats: {stats}", exc_info=True)
                    continue

            logger.debug(f"Processed {len(result)} files successfully")
            logger.debug(f"Returning result with {len(result)} entries: {list(result.keys())}")
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
                        file_stats.successful_prints = stats_data["successful_prints"]
                        file_stats.canceled_prints = stats_data["canceled_prints"]
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
                            successful_prints=stats_data["successful_prints"],
                            canceled_prints=stats_data["canceled_prints"],
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
