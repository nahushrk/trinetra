#!/usr/bin/env python3
"""
Debug script to compare Moonraker API data with database data
"""

import json
import sys
import os
from datetime import datetime
from typing import Dict, Any

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trinetra.integrations.moonraker.api import MoonrakerAPI
from trinetra.database import DatabaseManager
from trinetra.logger import configure_logging


def load_config():
    """Load configuration from config.yaml"""
    import yaml

    config_path = "test/config.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            print(f"Loaded config from {config_path}: {config}")
            return config
    print(f"Config file {config_path} not found")
    return {}


def call_moonraker_api(moonraker_url: str) -> Dict[str, Any]:
    """Call Moonraker API directly and return raw data"""
    print(f"Calling Moonraker API at: {moonraker_url}")

    api = MoonrakerAPI(moonraker_url)
    history_response = api.get_history(limit=1000)

    if not history_response:
        print("❌ Failed to get history from Moonraker API")
        return {}

    print(f"✅ Got history response with {len(history_response.get('jobs', []))} jobs")
    return history_response


def analyze_moonraker_data(history_response: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze the raw Moonraker data"""
    jobs = history_response.get("jobs", [])

    # Group by filename
    file_stats = {}

    for job in jobs:
        filename = job.get("filename")
        if not filename:
            continue

        if filename not in file_stats:
            file_stats[filename] = {
                "jobs": [],
                "total_prints": 0,
                "successful_prints": 0,
                "canceled_prints": 0,
                "total_print_time": 0,
                "total_filament_used": 0,
                "print_durations": [],
                "total_durations": [],
            }

        file_stats[filename]["jobs"].append(job)
        file_stats[filename]["total_prints"] += 1

        status = job.get("status")
        if status == "completed":
            file_stats[filename]["successful_prints"] += 1
        elif status == "cancelled":
            file_stats[filename]["canceled_prints"] += 1

        print_duration = job.get("print_duration", 0)
        total_duration = job.get("total_duration", 0)
        filament_used = job.get("filament_used", 0)

        file_stats[filename]["total_print_time"] += print_duration
        file_stats[filename]["total_filament_used"] += filament_used
        file_stats[filename]["print_durations"].append(print_duration)
        file_stats[filename]["total_durations"].append(total_duration)

    return file_stats


def get_database_stats(db_path: str = "trinetra.db") -> Dict[str, Any]:
    """Get statistics from database"""
    print(f"Reading database from: {db_path}")

    db_manager = DatabaseManager(db_path)

    # Get all stats from database
    from trinetra.models import GCodeFileStats

    all_stats = db_manager.get_session().query(GCodeFileStats).all()

    db_stats = {}
    for stat in all_stats:
        if stat.gcode_file:
            filename = stat.gcode_file.file_name
            db_stats[filename] = {
                "print_count": stat.print_count,
                "successful_prints": stat.successful_prints,
                "canceled_prints": stat.canceled_prints,
                "total_print_time": stat.total_print_time,
                "total_filament_used": stat.total_filament_used,
                "last_print_date": stat.last_print_date,
                "success_rate": stat.success_rate,
                "job_id": stat.job_id,
                "last_status": stat.last_status,
            }

    print(f"✅ Found {len(db_stats)} files with stats in database")
    return db_stats


def compare_data(moonraker_stats: Dict[str, Any], db_stats: Dict[str, Any]):
    """Compare Moonraker data with database data"""
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    # Find files that exist in both
    moonraker_files = set(moonraker_stats.keys())
    db_files = set(db_stats.keys())

    common_files = moonraker_files & db_files
    only_moonraker = moonraker_files - db_files
    only_db = db_files - moonraker_files

    print(f"Files in Moonraker: {len(moonraker_files)}")
    print(f"Files in Database: {len(db_files)}")
    print(f"Common files: {len(common_files)}")
    print(f"Only in Moonraker: {len(only_moonraker)}")
    print(f"Only in Database: {len(only_db)}")

    # Compare common files
    print(f"\nComparing {len(common_files)} common files:")
    print("-" * 80)

    total_discrepancies = 0

    for filename in sorted(common_files):
        moonraker_data = moonraker_stats[filename]
        db_data = db_stats[filename]

        discrepancies = []

        # Compare key metrics
        if moonraker_data["total_prints"] != db_data["print_count"]:
            discrepancies.append(
                f"total_prints: Moonraker={moonraker_data['total_prints']}, DB={db_data['print_count']}"
            )

        if moonraker_data["successful_prints"] != db_data["successful_prints"]:
            discrepancies.append(
                f"successful_prints: Moonraker={moonraker_data['successful_prints']}, DB={db_data['successful_prints']}"
            )

        if moonraker_data["canceled_prints"] != db_data["canceled_prints"]:
            discrepancies.append(
                f"canceled_prints: Moonraker={moonraker_data['canceled_prints']}, DB={db_data['canceled_prints']}"
            )

        if abs(moonraker_data["total_print_time"] - db_data["total_print_time"]) > 1:
            discrepancies.append(
                f"total_print_time: Moonraker={moonraker_data['total_print_time']}, DB={db_data['total_print_time']}"
            )

        if abs(moonraker_data["total_filament_used"] - db_data["total_filament_used"]) > 1:
            discrepancies.append(
                f"total_filament_used: Moonraker={moonraker_data['total_filament_used']}, DB={db_data['total_filament_used']}"
            )

        if discrepancies:
            total_discrepancies += 1
            print(f"\n❌ {filename}:")
            for disc in discrepancies:
                print(f"   {disc}")
        else:
            print(f"✅ {filename}: No discrepancies")

    print(f"\nTotal files with discrepancies: {total_discrepancies}")

    # Show some examples of raw Moonraker data
    if common_files:
        example_file = list(common_files)[0]
        print(f"\nExample raw Moonraker data for '{example_file}':")
        print(json.dumps(moonraker_stats[example_file], indent=2, default=str))


def calculate_aggregated_stats(moonraker_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate aggregated statistics from Moonraker data"""
    total_prints = 0
    successful_prints = 0
    canceled_prints = 0
    total_print_time = 0
    total_filament = 0
    print_days = set()

    for filename, data in moonraker_stats.items():
        total_prints += data["total_prints"]
        successful_prints += data["successful_prints"]
        canceled_prints += data["canceled_prints"]
        total_print_time += data["total_print_time"]
        total_filament += data["total_filament_used"]

        # For print days, we'd need to analyze each job's end_time
        # For now, just count unique files as a proxy
        print_days.add(filename)

    avg_print_time_hours = (total_print_time / total_prints / 3600) if total_prints > 0 else 0
    total_filament_meters = total_filament / 1000 if total_filament > 0 else 0

    return {
        "total_prints": total_prints,
        "successful_prints": successful_prints,
        "canceled_prints": canceled_prints,
        "avg_print_time_hours": avg_print_time_hours,
        "total_filament_meters": total_filament_meters,
        "print_days": len(print_days),
    }


def main():
    """Main function"""
    config = load_config()
    moonraker_url = config.get("moonraker_url", "http://klipper.local:7125")

    # Configure logging
    configure_logging(config)

    print("🔍 Moonraker vs Database Debug Tool")
    print("=" * 50)

    # Call Moonraker API
    moonraker_response = call_moonraker_api(moonraker_url)
    if not moonraker_response:
        return 1

    # Analyze Moonraker data
    moonraker_stats = analyze_moonraker_data(moonraker_response)

    # Get database stats
    db_stats = get_database_stats()

    # Compare data
    compare_data(moonraker_stats, db_stats)

    # Show missing files
    print("\n" + "=" * 80)
    print("FILES MISSING FROM DATABASE")
    print("=" * 80)
    moonraker_files = set(moonraker_stats.keys())
    db_files = set(db_stats.keys())
    missing_files = moonraker_files - db_files

    if missing_files:
        print(f"Found {len(missing_files)} files in Moonraker that are not in the database:")
        for filename in sorted(missing_files):
            data = moonraker_stats[filename]
            print(
                f"  - {filename}: {data['total_prints']} prints, {data['successful_prints']} successful, {data['canceled_prints']} canceled"
            )
    else:
        print("No files missing from database")

    # Calculate aggregated stats from Moonraker data
    print("\n" + "=" * 80)
    print("AGGREGATED STATISTICS FROM MOONRAKER DATA")
    print("=" * 80)
    aggregated_stats = calculate_aggregated_stats(moonraker_stats)
    print(f"Total prints: {aggregated_stats['total_prints']}")
    print(f"Successful prints: {aggregated_stats['successful_prints']}")
    print(f"Canceled prints: {aggregated_stats['canceled_prints']}")
    print(f"Average print time: {aggregated_stats['avg_print_time_hours']:.2f} hours")
    print(f"Total filament: {aggregated_stats['total_filament_meters']:.2f} meters")
    print(f"Print days: {aggregated_stats['print_days']}")

    # Get aggregated stats from database
    print("\n" + "=" * 80)
    print("AGGREGATED STATISTICS FROM DATABASE")
    print("=" * 80)
    db_manager = DatabaseManager("trinetra.db")
    db_aggregated = db_manager.get_printing_stats()
    print(f"Total prints: {db_aggregated['total_prints']}")
    print(f"Successful prints: {db_aggregated['successful_prints']}")
    print(f"Canceled prints: {db_aggregated['canceled_prints']}")
    print(f"Average print time: {db_aggregated['avg_print_time_hours']:.2f} hours")
    print(f"Total filament: {db_aggregated['total_filament_meters']:.2f} meters")
    print(f"Print days: {db_aggregated['print_days']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
