"""
Database manager for Trinetra 3D model manager.
Handles all database operations and provides compatibility with existing app.py functions.
"""

import os
import logging
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from trinetra.models import (
    Base,
    Folder,
    STLFile,
    ImageFile,
    PDFFile,
    GCodeFile,
    GCodeFileStats,
    PrintHistoryEvent,
    IntegrationSyncState,
    create_database_engine,
    init_database,
    create_session_factory,
)
from trinetra import gcode_handler, search, three_mf
from trinetra.config_paths import resolve_storage_paths
from trinetra.integrations.moonraker.service import MoonrakerService
from trinetra.integrations.protocol import PrinterServiceClient
from trinetra.integrations.registry import get_printer_integration
from trinetra.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Manages database operations for Trinetra."""

    def __init__(self, db_path="trinetra.db"):
        self.engine = create_database_engine(db_path)
        self.SessionFactory = create_session_factory(self.engine)
        init_database(self.engine)
        logger.info(f"Database initialized at {db_path}")
        self.stl_base_path = None
        self.gcode_base_path = None

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionFactory()

    def reload_index(
        self,
        stl_base_path: str,
        gcode_base_path: str,
        moonraker_url: Optional[str] = None,
        moonraker_client: Optional[PrinterServiceClient] = None,
    ) -> Dict[str, int]:
        """
        Reload the entire index from filesystem.
        This replaces all existing data with fresh filesystem scan.

        Args:
            stl_base_path: Path to STL files base directory
            gcode_base_path: Path to G-code files base directory
            moonraker_url: Optional Moonraker URL to fetch statistics
        """
        # Store base paths for use in other methods
        self.stl_base_path = stl_base_path
        self.gcode_base_path = gcode_base_path
        """
        # Store base paths for use in other methods
        self.stl_base_path = stl_base_path
        self.gcode_base_path = gcode_base_path

        Returns:
            Dict with counts of processed items
        """
        logger.info(f"Starting full index reload - STL: {stl_base_path}, GCODE: {gcode_base_path}")

        with self.get_session() as session:
            # Clear all existing data
            session.query(GCodeFile).delete()
            session.query(PDFFile).delete()
            session.query(ImageFile).delete()
            session.query(STLFile).delete()
            session.query(Folder).delete()
            session.commit()

            counts = {
                "folders": 0,
                "stl_files": 0,
                "image_files": 0,
                "pdf_files": 0,
                "gcode_files": 0,
            }

            # Process STL base path
            if os.path.exists(stl_base_path):
                stl_counts = self._process_stl_base_path(session, stl_base_path)
                # Add STL base path counts to total counts
                for key, value in stl_counts.items():
                    if key in counts:
                        counts[key] += value
                    else:
                        counts[key] = value

            # Process GCODE base path
            if os.path.exists(gcode_base_path):
                gcode_counts = self._process_gcode_base_path(
                    session, gcode_base_path, stl_base_path
                )
                # Add GCODE base path counts to total counts
                for key, value in gcode_counts.items():
                    if key in counts:
                        counts[key] += value
                    else:
                        counts[key] = value

            session.commit()

            # Update Moonraker stats if URL is provided
            if moonraker_url:
                logger.debug(f"Updating Moonraker stats from URL: {moonraker_url}")
                stats_result = self.update_moonraker_stats(moonraker_url, moonraker_client)
                logger.debug(f"Moonraker stats update result: {stats_result}")
                counts["moonraker_stats_updated"] = stats_result["updated"]
                counts["moonraker_stats_failed"] = stats_result["failed"]

            logger.info(f"Index reload completed: {counts}")
            return counts

    def _process_stl_base_path(self, session: Session, stl_base_path: str) -> Dict[str, int]:
        """Process STL base path and extract all files."""
        counts = {"folders": 0, "stl_files": 0, "image_files": 0, "pdf_files": 0}

        # Only process top-level folders
        for entry in os.scandir(stl_base_path):
            if entry.is_dir():
                folder_name = entry.name
                folder_path = entry.path

                # Create or get folder
                folder = session.query(Folder).filter(Folder.name == folder_name).first()
                if not folder:
                    # Get folder timestamps
                    try:
                        ctime = os.path.getctime(folder_path)
                        mtime = os.path.getmtime(folder_path)
                        created_at = datetime.fromtimestamp(ctime)
                        updated_at = datetime.fromtimestamp(mtime)
                    except OSError:
                        # Fallback to current time if we can't get folder timestamps
                        created_at = datetime.utcnow()
                        updated_at = datetime.utcnow()

                    folder = Folder(name=folder_name, created_at=created_at, updated_at=updated_at)
                    session.add(folder)
                    session.flush()  # Get the ID
                    counts["folders"] += 1

                # Process all files in this folder recursively
                folder_created_at = None
                folder_updated_at = None

                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, stl_base_path)
                        ext = os.path.splitext(file)[1].lower()

                        try:
                            file_size = os.path.getsize(abs_path)
                        except OSError:
                            file_size = 0

                        # Get file timestamps
                        try:
                            ctime = os.path.getctime(abs_path)
                            mtime = os.path.getmtime(abs_path)
                            file_created_at = datetime.fromtimestamp(ctime)
                            file_updated_at = datetime.fromtimestamp(mtime)
                        except OSError:
                            # Fallback to current time if we can't get file timestamps
                            file_created_at = datetime.utcnow()
                            file_updated_at = datetime.utcnow()

                        # Update folder timestamps if this file is newer
                        if folder_created_at is None or file_created_at < folder_created_at:
                            folder_created_at = file_created_at
                        if folder_updated_at is None or file_updated_at > folder_updated_at:
                            folder_updated_at = file_updated_at

                        if ext == ".stl":
                            # Check if STL file already exists
                            existing = (
                                session.query(STLFile)
                                .filter(
                                    and_(
                                        STLFile.folder_id == folder.id, STLFile.rel_path == rel_path
                                    )
                                )
                                .first()
                            )
                            if not existing:
                                stl_file = STLFile(
                                    folder_id=folder.id,
                                    file_name=file,
                                    rel_path=rel_path,
                                    abs_path=abs_path,
                                    file_size=file_size,
                                    created_at=file_created_at,
                                    updated_at=file_updated_at,
                                )
                                session.add(stl_file)
                                counts["stl_files"] += 1

                        elif ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
                            existing = (
                                session.query(ImageFile)
                                .filter(
                                    and_(
                                        ImageFile.folder_id == folder.id,
                                        ImageFile.rel_path == rel_path,
                                    )
                                )
                                .first()
                            )
                            if not existing:
                                image_file = ImageFile(
                                    folder_id=folder.id,
                                    file_name=file,
                                    rel_path=rel_path,
                                    abs_path=abs_path,
                                    file_size=file_size,
                                    extension=ext,
                                    created_at=file_created_at,
                                    updated_at=file_updated_at,
                                )
                                session.add(image_file)
                                counts["image_files"] += 1

                        elif ext == ".pdf":
                            existing = (
                                session.query(PDFFile)
                                .filter(
                                    and_(
                                        PDFFile.folder_id == folder.id, PDFFile.rel_path == rel_path
                                    )
                                )
                                .first()
                            )
                            if not existing:
                                pdf_file = PDFFile(
                                    folder_id=folder.id,
                                    file_name=file,
                                    rel_path=rel_path,
                                    abs_path=abs_path,
                                    file_size=file_size,
                                    created_at=file_created_at,
                                    updated_at=file_updated_at,
                                )
                                session.add(pdf_file)
                                counts["pdf_files"] += 1

                        elif ext == ".gcode":
                            # Process G-code files in STL base path
                            metadata = self._extract_gcode_metadata(abs_path)
                            existing = (
                                session.query(GCodeFile)
                                .filter(
                                    and_(
                                        GCodeFile.folder_id == folder.id,
                                        GCodeFile.rel_path == rel_path,
                                    )
                                )
                                .first()
                            )
                            if not existing:
                                gcode_file = GCodeFile(
                                    folder_id=folder.id,
                                    file_name=file,
                                    rel_path=rel_path,
                                    abs_path=abs_path,
                                    file_size=file_size,
                                    base_path="STL_BASE_PATH",
                                    created_at=file_created_at,
                                    updated_at=file_updated_at,
                                )
                                gcode_file.set_metadata(metadata)
                                session.add(gcode_file)
                                counts["gcode_files"] = counts.get("gcode_files", 0) + 1
                                logger.debug(
                                    f"Processed G-code file in STL base path: {file} (rel_path: {rel_path})"
                                )

                # Update folder timestamps to reflect the most recent file timestamps
                if folder_created_at is not None:
                    folder.created_at = folder_created_at
                if folder_updated_at is not None:
                    folder.updated_at = folder_updated_at

        # Also support standalone top-level 3MF files as virtual projects.
        # Example: <base>/swirl_lamp.3mf -> folder entry "swirl_lamp"
        for entry in os.scandir(stl_base_path):
            if not entry.is_file():
                continue
            if not entry.name.lower().endswith(".3mf"):
                continue

            virtual_folder_name = os.path.splitext(entry.name)[0]
            colliding_dir = os.path.join(stl_base_path, virtual_folder_name)
            if os.path.isdir(colliding_dir):
                # Real folder of same name takes precedence.
                continue

            existing_folder = (
                session.query(Folder).filter(Folder.name == virtual_folder_name).first()
            )
            if existing_folder:
                continue

            try:
                ctime = os.path.getctime(entry.path)
                mtime = os.path.getmtime(entry.path)
                created_at = datetime.fromtimestamp(ctime)
                updated_at = datetime.fromtimestamp(mtime)
            except OSError:
                created_at = datetime.utcnow()
                updated_at = datetime.utcnow()

            session.add(
                Folder(name=virtual_folder_name, created_at=created_at, updated_at=updated_at)
            )
            counts["folders"] += 1

        logger.debug(
            f"Total G-code files processed in _process_stl_base_path: {counts.get('gcode_files', 0)}"
        )
        print(
            f"DEBUG: Total G-code files processed in _process_stl_base_path: {counts.get('gcode_files', 0)}"
        )
        return counts

    def _process_gcode_base_path(
        self, session: Session, gcode_base_path: str, stl_base_path: str
    ) -> Dict[str, int]:
        """Process GCODE base path and link with STL files."""
        counts = {"gcode_files": 0}

        # Get all STL files for matching
        stl_files = session.query(STLFile).all()

        # Create a mapping of STL filenames (without extension) to STL files
        stl_bases = {}
        for stl_file in stl_files:
            stl_filename = os.path.splitext(stl_file.file_name)[0]
            stl_bases[stl_filename] = stl_file

        # Process all G-code files
        folder_timestamps = {}  # Track timestamps for each folder

        for root, dirs, files in os.walk(gcode_base_path):
            for file in files:
                if file.lower().endswith(".gcode"):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, gcode_base_path)

                    try:
                        file_size = os.path.getsize(abs_path)
                    except OSError:
                        file_size = 0

                    # Get file timestamps
                    try:
                        ctime = os.path.getctime(abs_path)
                        mtime = os.path.getmtime(abs_path)
                        file_created_at = datetime.fromtimestamp(ctime)
                        file_updated_at = datetime.fromtimestamp(mtime)
                    except OSError:
                        # Fallback to current time if we can't get file timestamps
                        file_created_at = datetime.utcnow()
                        file_updated_at = datetime.utcnow()

                    # Try to find matching STL file
                    gcode_base = self._split_base(file)
                    matching_stl = None
                    matching_folder = None

                    # Find STL filename that is prefix of gcode base (most specific/longest match)
                    matching_stl_filename = None
                    max_match_len = 0
                    for stl_filename in stl_bases:
                        if gcode_base.startswith(stl_filename):
                            # Prefer the longest matching prefix
                            if len(stl_filename) > max_match_len:
                                matching_stl_filename = stl_filename
                                max_match_len = len(stl_filename)

                    if matching_stl_filename:
                        matching_stl = stl_bases[matching_stl_filename]
                        matching_folder = matching_stl.folder

                    # Update folder timestamps if this file is newer
                    if matching_folder is not None:
                        folder_id = matching_folder.id
                        if folder_id not in folder_timestamps:
                            folder_timestamps[folder_id] = {
                                "created_at": file_created_at,
                                "updated_at": file_updated_at,
                            }
                        else:
                            if file_created_at < folder_timestamps[folder_id]["created_at"]:
                                folder_timestamps[folder_id]["created_at"] = file_created_at
                            if file_updated_at > folder_timestamps[folder_id]["updated_at"]:
                                folder_timestamps[folder_id]["updated_at"] = file_updated_at

                    # Check if G-code file already exists
                    existing = (
                        session.query(GCodeFile)
                        .filter(
                            and_(
                                GCodeFile.rel_path == rel_path,
                                GCodeFile.base_path == "GCODE_BASE_PATH",
                            )
                        )
                        .first()
                    )

                    if not existing:
                        metadata = self._extract_gcode_metadata(abs_path)
                        gcode_file = GCodeFile(
                            folder_id=matching_folder.id if matching_folder else None,
                            stl_file_id=matching_stl.id if matching_stl else None,
                            file_name=file,
                            rel_path=rel_path,
                            abs_path=abs_path,
                            file_size=file_size,
                            base_path="GCODE_BASE_PATH",
                            created_at=file_created_at,
                            updated_at=file_updated_at,
                        )
                        gcode_file.set_metadata(metadata)
                        session.add(gcode_file)
                        counts["gcode_files"] += 1
                        logger.debug(f"Processed G-code file: {file} (rel_path: {rel_path})")

        # Update folder timestamps to reflect the most recent file timestamps
        for folder_id, timestamps in folder_timestamps.items():
            folder = session.query(Folder).filter(Folder.id == folder_id).first()
            if folder:
                folder.created_at = timestamps["created_at"]
                folder.updated_at = timestamps["updated_at"]

        logger.debug(
            f"Total G-code files processed in _process_gcode_base_path: {counts['gcode_files']}"
        )
        print(
            f"DEBUG: Total G-code files processed in _process_gcode_base_path: {counts['gcode_files']}"
        )
        return counts

    def _split_base(self, filename):
        """Get base name from filename (without extension)."""
        return os.path.splitext(filename)[0]

    def _extract_gcode_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract metadata from G-code file."""
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as file:
                return gcode_handler.extract_gcode_metadata(file)
        except Exception as e:
            logger.error(f"Error reading G-code file {file_path}: {e}")
            return {}

    def get_stl_files(self) -> List[Dict[str, Any]]:
        """Get all STL files organized by folders (compatible with existing app.py)."""
        with self.get_session() as session:
            folders = session.query(Folder).all()
            result = []

            for folder in folders:
                stl_files = session.query(STLFile).filter(STLFile.folder_id == folder.id).all()
                three_mf_projects = self.get_folder_three_mf_projects(folder.name)
                folder_files = []
                for stl_file in stl_files:
                    folder_files.append(
                        {"file_name": stl_file.file_name, "rel_path": stl_file.rel_path}
                    )

                has_three_mf = bool(three_mf_projects)
                if folder_files or has_three_mf:
                    result.append(
                        {
                            "folder_name": folder.name,
                            "top_level_folder": folder.name,
                            "files": folder_files,
                            "three_mf_projects": three_mf_projects,
                        }
                    )

            return result

    def get_stl_files_paginated(
        self,
        page: int = 1,
        per_page: int = 15,
        sort_by: str = "folder_name",
        sort_order: str = "asc",
        filter_text: str = "",
        filter_type: str = "all",
    ) -> Dict[str, Any]:
        """Get STL files with pagination, sorting, and filtering.

        Args:
            page: Page number (1-based)
            per_page: Number of items per page
            sort_by: Field to sort by ('folder_name', 'file_name', 'created_at', 'updated_at')
            sort_order: Sort order ('asc' or 'desc')
            filter_text: Text to filter folders/files by
            filter_type: Type of filter to apply ('all', 'today')
        """
        with self.get_session() as session:
            # Base query for folders
            query = session.query(Folder)

            # Apply filter type
            if filter_type == "today":
                # Filter folders created within the last 24 hours
                from datetime import datetime, timedelta

                twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                query = query.filter(Folder.created_at >= twenty_four_hours_ago)
            elif filter_type == "week":
                # Filter folders created within the last 7 days
                from datetime import datetime, timedelta

                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                query = query.filter(Folder.created_at >= seven_days_ago)

            # Apply text filtering if provided
            if filter_text:
                query = query.filter(Folder.name.contains(filter_text))

            # Apply sorting
            if sort_by == "folder_name":
                order_column = Folder.name
            elif sort_by == "created_at":
                order_column = Folder.created_at
            elif sort_by == "updated_at":
                order_column = Folder.updated_at
            else:
                order_column = Folder.name  # Default sorting

            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())

            # Get total count for pagination
            total_folders = query.count()

            # Apply pagination
            folders = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            total_files = 0

            for folder in folders:
                # Query STL files for this folder
                stl_query = session.query(STLFile).filter(STLFile.folder_id == folder.id)

                # Apply filter type to files
                if filter_type == "today":
                    # Filter files created within the last 24 hours
                    from datetime import datetime, timedelta

                    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                    stl_query = stl_query.filter(STLFile.created_at >= twenty_four_hours_ago)
                elif filter_type == "week":
                    # Filter files created within the last 7 days
                    from datetime import datetime, timedelta

                    seven_days_ago = datetime.utcnow() - timedelta(days=7)
                    stl_query = stl_query.filter(STLFile.created_at >= seven_days_ago)

                # Apply file-level filtering if provided
                if filter_text:
                    stl_query = stl_query.filter(STLFile.file_name.contains(filter_text))

                # Apply sorting to files
                if sort_by == "file_name":
                    if sort_order.lower() == "desc":
                        stl_query = stl_query.order_by(STLFile.file_name.desc())
                    else:
                        stl_query = stl_query.order_by(STLFile.file_name.asc())
                elif sort_by == "created_at":
                    if sort_order.lower() == "desc":
                        stl_query = stl_query.order_by(STLFile.created_at.desc())
                    else:
                        stl_query = stl_query.order_by(STLFile.created_at.asc())
                elif sort_by == "updated_at":
                    if sort_order.lower() == "desc":
                        stl_query = stl_query.order_by(STLFile.updated_at.desc())
                    else:
                        stl_query = stl_query.order_by(STLFile.updated_at.asc())

                stl_files = stl_query.all()
                three_mf_projects = self.get_folder_three_mf_projects(folder.name)

                folder_files = []
                for stl_file in stl_files:
                    folder_files.append(
                        {"file_name": stl_file.file_name, "rel_path": stl_file.rel_path}
                    )

                has_three_mf = bool(three_mf_projects)
                if folder_files or has_three_mf:
                    total_files += len(folder_files)
                    result.append(
                        {
                            "folder_name": folder.name,
                            "top_level_folder": folder.name,
                            "files": folder_files,
                            "three_mf_projects": three_mf_projects,
                        }
                    )

            return {
                "folders": result,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_folders": total_folders,
                    "total_files": total_files,
                    "total_pages": (total_folders + per_page - 1) // per_page,
                },
                "filter": {
                    "text": filter_text,
                    "type": filter_type,
                    "sort_by": sort_by,
                    "sort_order": sort_order,
                },
            }

    def get_folder_contents(self, folder_name: str) -> Tuple[List, List, List, List]:
        """Get contents of a specific folder (compatible with existing app.py)."""
        with self.get_session() as session:
            folder = session.query(Folder).filter(Folder.name == folder_name).first()
            if not folder:
                return [], [], [], []

            # Get STL files
            stl_files = []
            for stl_file in folder.stl_files:
                stl_files.append(
                    {
                        "file_name": stl_file.file_name,
                        "path": "STL_BASE_PATH",
                        "rel_path": stl_file.rel_path,
                    }
                )

            # Get image files
            image_files = []
            for image_file in folder.image_files:
                image_files.append(
                    {
                        "file_name": image_file.file_name,
                        "path": "STL_BASE_PATH",
                        "rel_path": image_file.rel_path,
                        "ext": image_file.extension,
                    }
                )

            # Get PDF files
            pdf_files = []
            for pdf_file in folder.pdf_files:
                pdf_files.append(
                    {
                        "file_name": pdf_file.file_name,
                        "path": "STL_BASE_PATH",
                        "rel_path": pdf_file.rel_path,
                        "ext": ".pdf",
                    }
                )

            # Get G-code files (both from STL and GCODE base paths)
            gcode_files = []
            for gcode_file in folder.gcode_files:
                # Get stats data if available
                stats_data = None
                if gcode_file.stats:
                    stats = (
                        gcode_file.stats[0]
                        if isinstance(gcode_file.stats, list)
                        else gcode_file.stats
                    )
                    # Calculate average duration in seconds
                    avg_duration = 0
                    if stats.print_count > 0 and stats.total_print_time > 0:
                        avg_duration = stats.total_print_time / stats.print_count

                    stats_data = {
                        "print_count": stats.print_count,
                        "successful_prints": stats.successful_prints,
                        "canceled_prints": stats.canceled_prints,
                        "avg_duration": avg_duration,
                        "total_print_time": stats.total_print_time,
                        "total_filament_used": stats.total_filament_used,
                        "last_print_date": stats.last_print_date.isoformat()
                        if stats.last_print_date
                        else None,
                        "success_rate": stats.success_rate,
                        "job_id": stats.job_id,
                        "last_status": stats.last_status,
                    }

                gcode_files.append(
                    {
                        "file_name": gcode_file.file_name,
                        "path": gcode_file.base_path,
                        "rel_path": gcode_file.rel_path,
                        "metadata": gcode_file.get_metadata(),
                        "stats": stats_data,
                    }
                )

            # Also get G-code files that are associated with STL files in this folder
            for stl_file in folder.stl_files:
                for gcode_file in stl_file.gcode_files:
                    # Get stats data if available
                    stats_data = None
                    if gcode_file.stats:
                        stats = (
                            gcode_file.stats[0]
                            if isinstance(gcode_file.stats, list)
                            else gcode_file.stats
                        )
                        # Calculate average duration in seconds
                        avg_duration = 0
                        if stats.print_count > 0 and stats.total_print_time > 0:
                            avg_duration = stats.total_print_time / stats.print_count

                        stats_data = {
                            "print_count": stats.print_count,
                            "successful_prints": stats.successful_prints,
                            "canceled_prints": stats.canceled_prints,
                            "avg_duration": avg_duration,
                            "total_print_time": stats.total_print_time,
                            "total_filament_used": stats.total_filament_used,
                            "last_print_date": stats.last_print_date.isoformat()
                            if stats.last_print_date
                            else None,
                            "success_rate": stats.success_rate,
                            "job_id": stats.job_id,
                            "last_status": stats.last_status,
                        }

                    gcode_files.append(
                        {
                            "file_name": gcode_file.file_name,
                            "path": gcode_file.base_path,
                            "rel_path": gcode_file.rel_path,
                            "metadata": gcode_file.get_metadata(),
                            "stats": stats_data,
                        }
                    )

            # Deduplicate gcode_files by (file_name, rel_path)
            seen = set()
            deduped_gcode_files = []
            for gfile in gcode_files:
                key = (gfile["file_name"], gfile["rel_path"])
                if key not in seen:
                    deduped_gcode_files.append(gfile)
                    seen.add(key)

            return stl_files, image_files, pdf_files, deduped_gcode_files

    def get_folder_three_mf_projects(self, folder_name: str) -> List[Dict[str, Any]]:
        """Get parsed 3MF project data for a folder."""
        if not self.stl_base_path:
            return []

        folder_path = os.path.join(self.stl_base_path, folder_name)

        results: List[Dict[str, Any]] = []
        candidate_paths: List[str] = []

        if os.path.isdir(folder_path):
            for root, _dirs, files in os.walk(folder_path):
                for file_name in files:
                    if file_name.lower().endswith(".3mf"):
                        candidate_paths.append(os.path.join(root, file_name))
        else:
            # Virtual folder support for top-level 3MF files:
            # <base>/<folder_name>.3mf
            root_three_mf = os.path.join(self.stl_base_path, f"{folder_name}.3mf")
            if os.path.isfile(root_three_mf):
                candidate_paths.append(root_three_mf)

        for abs_path in candidate_paths:
            file_name = os.path.basename(abs_path)
            rel_path = os.path.relpath(abs_path, self.stl_base_path)

            try:
                parsed = three_mf.load_3mf_project(abs_path)
                summary = three_mf.project_to_summary(parsed)
                settings = three_mf.summarize_settings(
                    summary.get("project_settings", {}), max_items=10
                )
                model_metadata = three_mf.summarize_model_metadata(
                    summary.get("model_metadata", {}), max_items=4
                )

                results.append(
                    {
                        "file_name": file_name,
                        "rel_path": rel_path,
                        "model_metadata": model_metadata,
                        "project_settings": settings,
                        "plates": summary.get("plates", []),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to parse 3MF project {abs_path}: {e}")
                results.append(
                    {
                        "file_name": file_name,
                        "rel_path": rel_path,
                        "model_metadata": {},
                        "project_settings": {},
                        "plates": [],
                        "error": str(e),
                    }
                )

        results.sort(key=lambda project: project["rel_path"])
        return results

    def get_all_gcode_files(self) -> List[Dict[str, Any]]:
        """Get all G-code files with folder associations and stats."""
        with self.get_session() as session:
            # Join GCodeFile with GCodeFileStats to get stats data
            gcode_files = session.query(GCodeFile).outerjoin(GCodeFileStats).all()
            result = []

            for gcode_file in gcode_files:
                folder_name = "Unknown"
                if gcode_file.folder:
                    folder_name = gcode_file.folder.name
                elif gcode_file.stl_file and gcode_file.stl_file.folder:
                    folder_name = gcode_file.stl_file.folder.name

                # Get stats data if available
                stats_data = None
                if gcode_file.stats:
                    stats = (
                        gcode_file.stats[0]
                        if isinstance(gcode_file.stats, list)
                        else gcode_file.stats
                    )
                    # Calculate average duration in seconds
                    avg_duration = 0
                    if stats.print_count > 0 and stats.total_print_time > 0:
                        avg_duration = stats.total_print_time / stats.print_count

                    stats_data = {
                        "print_count": stats.print_count,
                        "successful_prints": stats.successful_prints,
                        "canceled_prints": stats.canceled_prints,
                        "avg_duration": avg_duration,
                        "total_print_time": stats.total_print_time,
                        "total_filament_used": stats.total_filament_used,
                        "last_print_date": stats.last_print_date.isoformat()
                        if stats.last_print_date
                        else None,
                        "success_rate": stats.success_rate,
                        "job_id": stats.job_id,
                        "last_status": stats.last_status,
                    }

                result.append(
                    {
                        "file_name": gcode_file.file_name,
                        "rel_path": gcode_file.rel_path,
                        "folder_name": folder_name,
                        "metadata": gcode_file.get_metadata(),
                        "base_path": gcode_file.base_path,
                        "stats": stats_data,
                    }
                )

            # Sort by folder name, then by file name
            result.sort(key=lambda x: (x["folder_name"], x["file_name"]))
            return result

    def get_gcode_files_paginated(
        self,
        page: int = 1,
        per_page: int = 15,
        sort_by: str = "folder_name",
        sort_order: str = "asc",
        filter_text: str = "",
        filter_type: str = "all",
    ) -> Dict[str, Any]:
        """Get G-code files with pagination, sorting, and filtering.

        Args:
            page: Page number (1-based)
            per_page: Number of items per page
            sort_by: Field to sort by ('folder_name', 'file_name', 'print_count', 'last_print_date', 'created_at', 'updated_at')
            sort_order: Sort order ('asc' or 'desc')
            filter_text: Text to filter files by
            filter_type: Type of filter to apply ('all', 'today', 'successful', 'failed')
        """
        with self.get_session() as session:
            # Base query for G-code files
            query = session.query(GCodeFile).outerjoin(GCodeFileStats)

            # Apply filter type
            if filter_type == "today":
                # Filter files created within the last 24 hours
                from datetime import datetime, timedelta

                twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                query = query.filter(GCodeFile.created_at >= twenty_four_hours_ago)
            elif filter_type == "week":
                # Filter files created within the last 7 days
                from datetime import datetime, timedelta

                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                query = query.filter(GCodeFile.created_at >= seven_days_ago)
            elif filter_type == "successful":
                # Filter files with successful prints
                query = query.filter(
                    and_(
                        GCodeFileStats.successful_prints > 0,
                        GCodeFileStats.successful_prints.isnot(None),
                    )
                )  # At least one successful print
            elif filter_type == "failed":
                # Filter files with failed prints (no successful prints but have print history)
                query = query.filter(
                    and_(
                        GCodeFileStats.successful_prints == 0,
                        GCodeFileStats.print_count > 0,
                        GCodeFileStats.successful_prints.isnot(None),
                        GCodeFileStats.print_count.isnot(None),
                    )
                )

            # Apply text filtering if provided
            if filter_text:
                query = query.filter(
                    or_(
                        GCodeFile.file_name.contains(filter_text),
                        GCodeFile.folder.has(Folder.name.contains(filter_text)),
                    )
                )

            # Apply sorting
            if sort_by == "file_name":
                order_column = GCodeFile.file_name
            elif sort_by == "folder_name":
                # Join with Folder table for folder-based sorting
                query = query.join(Folder, GCodeFile.folder_id == Folder.id, isouter=True)
                order_column = Folder.name
            elif sort_by == "print_count" and GCodeFileStats.print_count is not None:
                order_column = GCodeFileStats.print_count
            elif sort_by == "last_print_date" and GCodeFileStats.last_print_date is not None:
                order_column = GCodeFileStats.last_print_date
            elif sort_by == "created_at":
                order_column = GCodeFile.created_at
            elif sort_by == "updated_at":
                order_column = GCodeFile.updated_at
            else:
                # Join with Folder table for default sorting
                query = query.join(Folder, GCodeFile.folder_id == Folder.id, isouter=True)
                order_column = Folder.name  # Default sorting

            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())

            # Get total count for pagination
            total_files = query.count()

            # Apply pagination
            gcode_files = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []

            for gcode_file in gcode_files:
                folder_name = "Unknown"
                if gcode_file.folder:
                    folder_name = gcode_file.folder.name
                elif gcode_file.stl_file and gcode_file.stl_file.folder:
                    folder_name = gcode_file.stl_file.folder.name

                # Get stats data if available
                stats_data = None
                if gcode_file.stats:
                    stats = (
                        gcode_file.stats[0]
                        if isinstance(gcode_file.stats, list)
                        else gcode_file.stats
                    )
                    # Calculate average duration in seconds
                    avg_duration = 0
                    if stats.print_count > 0 and stats.total_print_time > 0:
                        avg_duration = stats.total_print_time / stats.print_count

                    stats_data = {
                        "print_count": stats.print_count,
                        "successful_prints": stats.successful_prints,
                        "canceled_prints": stats.canceled_prints,
                        "avg_duration": avg_duration,
                        "total_print_time": stats.total_print_time,
                        "total_filament_used": stats.total_filament_used,
                        "last_print_date": stats.last_print_date.isoformat()
                        if stats.last_print_date
                        else None,
                        "success_rate": stats.success_rate,
                        "job_id": stats.job_id,
                        "last_status": stats.last_status,
                    }

                result.append(
                    {
                        "file_name": gcode_file.file_name,
                        "rel_path": gcode_file.rel_path,
                        "folder_name": folder_name,
                        "metadata": gcode_file.get_metadata(),
                        "base_path": gcode_file.base_path,
                        "stats": stats_data,
                    }
                )

            return {
                "files": result,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_files": total_files,
                    "total_pages": (total_files + per_page - 1) // per_page,
                },
                "filter": {
                    "text": filter_text,
                    "type": filter_type,
                    "sort_by": sort_by,
                    "sort_order": sort_order,
                },
            }

    def search_stl_files(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Search STL files and folders."""
        stl_folders = self.get_stl_files()
        return search.search_files_and_folders(query, stl_folders, limit)

    def search_gcode_files(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Search G-code files."""
        gcode_files = self.get_all_gcode_files()
        return search.search_gcode_files(query, gcode_files, limit)

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        with self.get_session() as session:
            total_folders = session.query(Folder).count()
            total_stl_files = session.query(STLFile).count()
            total_gcode_files = session.query(GCodeFile).count()
            total_image_files = session.query(ImageFile).count()
            total_pdf_files = session.query(PDFFile).count()

            # Count folders with G-code files
            folders_with_gcode = session.query(Folder).join(GCodeFile).distinct().count()

            return {
                "total_folders": total_folders,
                "total_stl_files": total_stl_files,
                "total_gcode_files": total_gcode_files,
                "total_image_files": total_image_files,
                "total_pdf_files": total_pdf_files,
                "folders_with_gcode": folders_with_gcode,
            }

    def delete_folder(self, folder_name: str) -> bool:
        """Delete a folder and all its contents."""
        with self.get_session() as session:
            folder = session.query(Folder).filter(Folder.name == folder_name).first()
            if folder:
                session.delete(folder)
                session.commit()
                return True
            return False

    def add_folder(self, folder_name: str) -> Folder:
        """Add a new folder."""
        # Get folder path to extract timestamps
        folder_path = os.path.join(self.stl_base_path or "stl_files", folder_name)

        # Get folder timestamps
        try:
            ctime = os.path.getctime(folder_path)
            mtime = os.path.getmtime(folder_path)
            folder_created_at = datetime.fromtimestamp(ctime)
            folder_updated_at = datetime.fromtimestamp(mtime)
        except OSError:
            # Fallback to current time if we can't get folder timestamps
            folder_created_at = datetime.utcnow()
            folder_updated_at = datetime.utcnow()

        with self.get_session() as session:
            folder = Folder(
                name=folder_name,
                created_at=folder_created_at,
                updated_at=folder_updated_at,
            )
            session.add(folder)
            session.commit()
            return folder

    def add_stl_file(
        self, folder_name: str, file_name: str, rel_path: str, abs_path: str
    ) -> STLFile:
        """Add a new STL file to a folder."""
        with self.get_session() as session:
            folder = session.query(Folder).filter(Folder.name == folder_name).first()
            if not folder:
                folder = self.add_folder(folder_name)
                session.refresh(folder)

            # Get file timestamps
            try:
                ctime = os.path.getctime(abs_path)
                mtime = os.path.getmtime(abs_path)
                file_created_at = datetime.fromtimestamp(ctime)
                file_updated_at = datetime.fromtimestamp(mtime)
            except OSError:
                # Fallback to current time if we can't get file timestamps
                file_created_at = datetime.utcnow()
                file_updated_at = datetime.utcnow()

            stl_file = STLFile(
                folder_id=folder.id,
                file_name=file_name,
                rel_path=rel_path,
                abs_path=abs_path,
                created_at=file_created_at,
                updated_at=file_updated_at,
            )
            session.add(stl_file)

            # Update folder timestamps if this file is newer
            if folder.created_at is None or file_created_at < folder.created_at:
                folder.created_at = file_created_at
            if folder.updated_at is None or file_updated_at > folder.updated_at:
                folder.updated_at = file_updated_at

            session.commit()
            return stl_file

    def update_moonraker_stats(
        self, moonraker_url: str, moonraker_client: Optional[PrinterServiceClient] = None
    ) -> Dict[str, int]:
        """Update Moonraker statistics for all G-code files."""
        try:
            # Build a client through the integration protocol when a client was not injected.
            if moonraker_client is None:
                integration = get_printer_integration("moonraker")
                if integration is not None:
                    runtime_config = {
                        "integrations": {"moonraker": {"enabled": True, "base_url": moonraker_url}},
                        "moonraker_url": moonraker_url,
                    }
                    moonraker_client = integration.create_client(runtime_config)

            if moonraker_client is None:
                logger.warning("Skipping Moonraker stats update: integration client unavailable")
                return {"updated": 0, "failed": 0}

            moonraker_service = MoonrakerService(moonraker_client)

            # Update stats
            with self.get_session() as session:
                result = moonraker_service.update_all_file_stats(session)
                return result
        except Exception as e:
            logger.error(f"Error updating Moonraker stats: {e}")
            return {"updated": 0, "failed": 0}

    def reload_moonraker_only(
        self, moonraker_url: str, moonraker_client: Optional[PrinterServiceClient] = None
    ) -> Dict[str, int]:
        """Reload only Moonraker statistics without touching files."""
        return self.update_moonraker_stats(moonraker_url, moonraker_client)

    def sync_print_history_events(
        self,
        integration_id: str,
        events: List[Dict[str, Any]],
        *,
        integration_mode: Optional[str] = None,
        ttl_days: Optional[int] = 180,
        cleanup_expired: bool = False,
    ) -> Dict[str, int]:
        """
        Persist normalized integration history events with id-based dedup.

        Args:
            integration_id: Integration identifier, e.g. 'bambu'
            events: Normalized event dictionaries
            integration_mode: Optional provider mode, e.g. 'cloud'
            ttl_days: Retention in days; ignored when cleanup_expired is False
            cleanup_expired: Whether to delete expired events in this run
        """
        counters = {
            "fetched": len(events),
            "inserted": 0,
            "updated": 0,
            "matched": 0,
            "ambiguous": 0,
            "unmatched": 0,
            "skipped_missing_event_id": 0,
            "expired_deleted": 0,
        }
        now = datetime.utcnow()
        affected_gcode_file_ids: set[int] = set()

        with self.get_session() as session:
            try:
                basename_to_ids: Dict[str, List[int]] = {}
                for gcode_file in session.query(GCodeFile.id, GCodeFile.file_name).all():
                    basename = self._normalize_basename(gcode_file.file_name)
                    if basename:
                        basename_to_ids.setdefault(basename, []).append(gcode_file.id)

                for event in events:
                    event_uid = str(event.get("event_uid") or "").strip()
                    if not event_uid:
                        counters["skipped_missing_event_id"] += 1
                        continue

                    printer_uid = str(event.get("printer_uid") or "").strip()
                    file_name = str(event.get("file_name") or "").strip()
                    file_path = str(event.get("file_path") or "").strip()
                    normalized_basename = self._normalize_basename(file_name or file_path)

                    gcode_file_id = None
                    match_state = "unmatched"
                    if normalized_basename:
                        matching_ids = basename_to_ids.get(normalized_basename, [])
                        if len(matching_ids) == 1:
                            gcode_file_id = matching_ids[0]
                            match_state = "matched"
                            counters["matched"] += 1
                            affected_gcode_file_ids.add(gcode_file_id)
                        elif len(matching_ids) > 1:
                            match_state = "ambiguous"
                            counters["ambiguous"] += 1
                        else:
                            counters["unmatched"] += 1
                    else:
                        counters["unmatched"] += 1

                    status = str(event.get("status") or "unknown").strip().lower()
                    started_at = self._coerce_datetime(event.get("started_at"))
                    ended_at = self._coerce_datetime(event.get("ended_at"))
                    event_at = self._coerce_datetime(event.get("event_at")) or ended_at or started_at
                    duration_seconds = self._coerce_float(event.get("duration_seconds"))
                    filament_used_mm = self._coerce_float(event.get("filament_used_mm"))
                    raw_payload = event.get("raw_payload") or event
                    raw_payload_json = self._serialize_payload(raw_payload)
                    job_uid = str(event.get("job_uid") or "").strip() or None

                    existing = (
                        session.query(PrintHistoryEvent)
                        .filter(
                            PrintHistoryEvent.integration_id == integration_id,
                            PrintHistoryEvent.printer_uid == printer_uid,
                            PrintHistoryEvent.event_uid == event_uid,
                        )
                        .first()
                    )

                    if existing:
                        existing.integration_mode = integration_mode
                        existing.job_uid = job_uid
                        existing.file_name = file_name
                        existing.file_path = file_path
                        existing.normalized_basename = normalized_basename
                        existing.status = status
                        existing.started_at = started_at
                        existing.ended_at = ended_at
                        existing.event_at = event_at
                        existing.duration_seconds = duration_seconds
                        existing.filament_used_mm = filament_used_mm
                        existing.gcode_file_id = gcode_file_id
                        existing.match_state = match_state
                        existing.raw_payload_json = raw_payload_json
                        existing.last_seen_at = now
                        counters["updated"] += 1
                    else:
                        session.add(
                            PrintHistoryEvent(
                                integration_id=integration_id,
                                integration_mode=integration_mode,
                                printer_uid=printer_uid,
                                event_uid=event_uid,
                                job_uid=job_uid,
                                file_name=file_name,
                                file_path=file_path,
                                normalized_basename=normalized_basename,
                                status=status,
                                started_at=started_at,
                                ended_at=ended_at,
                                event_at=event_at,
                                duration_seconds=duration_seconds,
                                filament_used_mm=filament_used_mm,
                                gcode_file_id=gcode_file_id,
                                match_state=match_state,
                                raw_payload_json=raw_payload_json,
                                first_seen_at=now,
                                last_seen_at=now,
                            )
                        )
                        counters["inserted"] += 1

                if cleanup_expired and ttl_days is not None and ttl_days > 0:
                    from datetime import timedelta

                    cutoff = now - timedelta(days=ttl_days)
                    expired_rows = (
                        session.query(PrintHistoryEvent.id, PrintHistoryEvent.gcode_file_id)
                        .filter(PrintHistoryEvent.event_at.isnot(None), PrintHistoryEvent.event_at < cutoff)
                        .all()
                    )
                    if expired_rows:
                        for row in expired_rows:
                            if row.gcode_file_id:
                                affected_gcode_file_ids.add(row.gcode_file_id)
                        expired_ids = [row.id for row in expired_rows]
                        counters["expired_deleted"] = (
                            session.query(PrintHistoryEvent)
                            .filter(PrintHistoryEvent.id.in_(expired_ids))
                            .delete(synchronize_session=False)
                        )

                self._rebuild_gcode_stats_from_history(session, affected_gcode_file_ids)
                self._record_sync_success(
                    session,
                    integration_id=integration_id,
                    integration_mode=integration_mode,
                    synced_at=now,
                )
                session.commit()
                return counters
            except Exception as exc:
                session.rollback()
                logger.error("Error syncing history events for %s: %s", integration_id, exc)
                self._record_sync_failure(
                    integration_id=integration_id,
                    integration_mode=integration_mode,
                    error=str(exc),
                    failed_at=now,
                )
                return counters

    def _rebuild_gcode_stats_from_history(
        self, session: Session, gcode_file_ids: set[int]
    ) -> None:
        """Recompute aggregated stats for a set of gcode file ids from history events."""
        if not gcode_file_ids:
            return

        for gcode_file_id in gcode_file_ids:
            events = (
                session.query(PrintHistoryEvent)
                .filter(
                    PrintHistoryEvent.gcode_file_id == gcode_file_id,
                    PrintHistoryEvent.match_state == "matched",
                )
                .all()
            )

            stats = (
                session.query(GCodeFileStats)
                .filter(GCodeFileStats.gcode_file_id == gcode_file_id)
                .first()
            )

            if not events:
                if stats:
                    session.delete(stats)
                continue

            print_count = len(events)
            successful_prints = sum(1 for event in events if event.status == "completed")
            canceled_prints = sum(1 for event in events if event.status == "cancelled")
            total_print_time = int(sum(event.duration_seconds or 0 for event in events))
            total_filament_used = int(sum(event.filament_used_mm or 0 for event in events))

            latest_event = max(
                events,
                key=lambda event: event.event_at
                or event.ended_at
                or event.started_at
                or datetime.min,
            )
            last_print_date = latest_event.event_at or latest_event.ended_at or latest_event.started_at
            success_rate = successful_prints / print_count if print_count > 0 else 0

            if stats is None:
                stats = GCodeFileStats(gcode_file_id=gcode_file_id)
                session.add(stats)

            stats.print_count = print_count
            stats.successful_prints = successful_prints
            stats.canceled_prints = canceled_prints
            stats.total_print_time = total_print_time
            stats.total_filament_used = total_filament_used
            stats.last_print_date = last_print_date
            stats.success_rate = success_rate
            stats.job_id = latest_event.job_uid or latest_event.event_uid
            stats.last_status = latest_event.status

    def _record_sync_success(
        self,
        session: Session,
        *,
        integration_id: str,
        integration_mode: Optional[str],
        synced_at: datetime,
    ) -> None:
        state = (
            session.query(IntegrationSyncState)
            .filter(
                IntegrationSyncState.integration_id == integration_id,
                IntegrationSyncState.integration_mode == integration_mode,
                IntegrationSyncState.printer_uid == "",
            )
            .first()
        )
        if state is None:
            state = IntegrationSyncState(
                integration_id=integration_id,
                integration_mode=integration_mode,
                printer_uid="",
            )
            session.add(state)

        state.last_synced_at = synced_at
        state.last_success_at = synced_at
        state.last_error = None
        state.last_error_at = None

    def _record_sync_failure(
        self,
        *,
        integration_id: str,
        integration_mode: Optional[str],
        error: str,
        failed_at: datetime,
    ) -> None:
        with self.get_session() as session:
            state = (
                session.query(IntegrationSyncState)
                .filter(
                    IntegrationSyncState.integration_id == integration_id,
                    IntegrationSyncState.integration_mode == integration_mode,
                    IntegrationSyncState.printer_uid == "",
                )
                .first()
            )
            if state is None:
                state = IntegrationSyncState(
                    integration_id=integration_id,
                    integration_mode=integration_mode,
                    printer_uid="",
                )
                session.add(state)

            state.last_synced_at = failed_at
            state.last_error = error
            state.last_error_at = failed_at
            session.commit()

    @staticmethod
    def _normalize_basename(value: Optional[str]) -> str:
        if not value:
            return ""
        basename = os.path.basename(str(value).strip().replace("\\", "/"))
        return basename.lower()

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            numeric = float(value)
            if abs(numeric) > 1e11:
                numeric /= 1000.0
            try:
                return datetime.utcfromtimestamp(numeric)
            except (TypeError, ValueError, OSError):
                return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                numeric = float(raw)
                if abs(numeric) > 1e11:
                    numeric /= 1000.0
                return datetime.utcfromtimestamp(numeric)
            except (TypeError, ValueError, OSError):
                pass
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(raw)
                if parsed.tzinfo:
                    return parsed.astimezone(tz=None).replace(tzinfo=None)
                return parsed
            except ValueError:
                return None
        return None

    @staticmethod
    def _serialize_payload(value: Any) -> str:
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except TypeError:
            return json.dumps({"payload_repr": str(value)}, ensure_ascii=False)

    @staticmethod
    def _is_success_status(value: Any) -> bool:
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {
            "2",
            "completed",
            "complete",
            "finished",
            "success",
            "succeeded",
            "done",
        }

    @staticmethod
    def _is_canceled_status(value: Any) -> bool:
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {
            "3",
            "4",
            "cancelled",
            "canceled",
            "failed",
            "failure",
            "aborted",
            "error",
        }

    @staticmethod
    def _resolve_event_datetime(
        event_at: Optional[datetime],
        ended_at: Optional[datetime],
        started_at: Optional[datetime],
    ) -> Optional[datetime]:
        return event_at or ended_at or started_at

    @classmethod
    def _extract_event_datetime_from_payload(cls, raw_payload_json: Optional[str]) -> Optional[datetime]:
        if not raw_payload_json:
            return None
        try:
            payload = json.loads(raw_payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        for key in ("endTime", "end_time", "eventTime", "event_time", "startTime", "start_time"):
            if key in payload:
                parsed = cls._coerce_datetime(payload.get(key))
                if parsed:
                    return parsed
        return None

    def get_printing_stats(self) -> Dict[str, Any]:
        """Get aggregated printing statistics from database."""
        with self.get_session() as session:
            try:
                # Prefer normalized integration history as the primary source of truth.
                history_rows = (
                    session.query(
                        PrintHistoryEvent.status,
                        PrintHistoryEvent.duration_seconds,
                        PrintHistoryEvent.filament_used_mm,
                        PrintHistoryEvent.event_at,
                        PrintHistoryEvent.ended_at,
                        PrintHistoryEvent.started_at,
                        PrintHistoryEvent.raw_payload_json,
                    )
                    .order_by(PrintHistoryEvent.id.asc())
                    .all()
                )

                if history_rows:
                    total_prints = len(history_rows)
                    successful_prints = 0
                    canceled_prints = 0
                    total_print_time = 0.0
                    total_filament = 0.0
                    print_days = set()

                    for row in history_rows:
                        if self._is_success_status(row.status):
                            successful_prints += 1
                        elif self._is_canceled_status(row.status):
                            canceled_prints += 1

                        total_print_time += self._coerce_float(row.duration_seconds)
                        total_filament += self._coerce_float(row.filament_used_mm)

                        event_dt = self._resolve_event_datetime(
                            row.event_at, row.ended_at, row.started_at
                        )
                        if not event_dt:
                            event_dt = self._extract_event_datetime_from_payload(row.raw_payload_json)
                        if event_dt:
                            print_days.add(event_dt.strftime("%Y-%m-%d"))

                    avg_print_time_hours = total_print_time / total_prints / 3600
                    total_filament_meters = total_filament / 1000

                    return {
                        "total_prints": total_prints,
                        "successful_prints": successful_prints,
                        "canceled_prints": canceled_prints,
                        "avg_print_time_hours": avg_print_time_hours,
                        "total_filament_meters": total_filament_meters,
                        "print_days": len(print_days),
                    }

                # Backward-compatible fallback for legacy datasets.
                all_stats = session.query(GCodeFileStats).all()
                if not all_stats:
                    return {
                        "total_prints": 0,
                        "successful_prints": 0,
                        "canceled_prints": 0,
                        "avg_print_time_hours": 0,
                        "total_filament_meters": 0,
                        "print_days": 0,
                    }

                total_prints = 0
                successful_prints = 0
                canceled_prints = 0
                total_print_time = 0
                total_filament = 0
                print_days = set()

                for stat in all_stats:
                    total_prints += stat.print_count

                    # For successful/canceled prints, we need to look at the last status
                    if stat.last_status == "completed":
                        successful_prints += 1
                    elif stat.last_status == "cancelled":
                        canceled_prints += 1

                    total_print_time += stat.total_print_time
                    total_filament += stat.total_filament_used

                    if stat.last_print_date:
                        print_days.add(stat.last_print_date.strftime("%Y-%m-%d"))

                avg_print_time_hours = total_print_time / total_prints if total_prints > 0 else 0
                total_filament_meters = (
                    total_filament / 1000 if total_filament > 0 else 0
                )  # Convert mm to meters

                return {
                    "total_prints": total_prints,
                    "successful_prints": successful_prints,
                    "canceled_prints": canceled_prints,
                    "avg_print_time_hours": avg_print_time_hours / 3600,  # Convert seconds to hours
                    "total_filament_meters": total_filament_meters,
                    "print_days": len(print_days),
                }
            except Exception as e:
                logger.error(f"Error getting printing stats from database: {e}")
                return {
                    "total_prints": 0,
                    "successful_prints": 0,
                    "canceled_prints": 0,
                    "avg_print_time_hours": 0,
                    "total_filament_meters": 0,
                    "print_days": 0,
                }

    def get_activity_calendar(self) -> Dict[str, int]:
        """Get activity calendar data from database."""
        with self.get_session() as session:
            try:
                history_rows = (
                    session.query(
                        PrintHistoryEvent.event_at,
                        PrintHistoryEvent.ended_at,
                        PrintHistoryEvent.started_at,
                        PrintHistoryEvent.raw_payload_json,
                    )
                    .order_by(PrintHistoryEvent.id.asc())
                    .all()
                )

                activity_calendar: Dict[str, int] = {}
                if history_rows:
                    for row in history_rows:
                        event_dt = self._resolve_event_datetime(
                            row.event_at, row.ended_at, row.started_at
                        )
                        if not event_dt:
                            event_dt = self._extract_event_datetime_from_payload(row.raw_payload_json)
                        if not event_dt:
                            continue
                        date_str = event_dt.strftime("%Y-%m-%d")
                        activity_calendar[date_str] = activity_calendar.get(date_str, 0) + 1
                    return activity_calendar

                # Backward-compatible fallback for legacy datasets.
                stats_with_dates = (
                    session.query(GCodeFileStats)
                    .filter(GCodeFileStats.last_print_date.isnot(None))
                    .all()
                )

                for stat in stats_with_dates:
                    date_str = stat.last_print_date.strftime("%Y-%m-%d")
                    activity_calendar[date_str] = activity_calendar.get(date_str, 0) + stat.print_count

                return activity_calendar
            except Exception as e:
                logger.error(f"Error getting activity calendar from database: {e}")
                return {}


def main():
    """CLI entry point for database generation process."""
    import argparse
    import yaml

    parser = argparse.ArgumentParser(
        description="Generate Trinetra database from filesystem and optional connectors"
    )
    parser.add_argument("config", help="Path to config file")
    parser.add_argument("db_path", help="Path to database file")

    args = parser.parse_args()

    # Load config
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Configure logging
    from trinetra.logger import configure_logging

    configure_logging(config)

    # Resolve storage paths from config (legacy + single-root mode)
    stl_base_path, gcode_base_path, _ = resolve_storage_paths(config)
    moonraker_url = config.get("moonraker_url")

    # Create database manager
    db_manager = DatabaseManager(args.db_path)

    # Reload index
    counts = db_manager.reload_index(stl_base_path, gcode_base_path, moonraker_url)

    print(f"Database generation completed:")
    for key, value in counts.items():
        print(f"  {key}: {value}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
