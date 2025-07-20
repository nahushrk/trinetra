"""
Database manager for Trinetra 3D printing catalog
Handles all database operations and provides compatibility with existing app.py functions
"""

import os
import logging
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
    create_database_engine,
    init_database,
    create_session_factory,
)
from trinetra import gcode_handler, search
from trinetra.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Manages database operations for Trinetra."""

    def __init__(self, db_path="trinetra.db"):
        self.engine = create_database_engine(db_path)
        self.SessionFactory = create_session_factory(self.engine)
        init_database(self.engine)
        logger.info(f"Database initialized at {db_path}")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionFactory()

    def reload_index(self, stl_base_path: str, gcode_base_path: str) -> Dict[str, int]:
        """
        Reload the entire index from filesystem.
        This replaces all existing data with fresh filesystem scan.

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
                counts.update(self._process_stl_base_path(session, stl_base_path))

            # Process GCODE base path
            if os.path.exists(gcode_base_path):
                counts.update(
                    self._process_gcode_base_path(session, gcode_base_path, stl_base_path)
                )

            session.commit()
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
                    folder = Folder(name=folder_name)
                    session.add(folder)
                    session.flush()  # Get the ID
                    counts["folders"] += 1

                # Process all files in this folder recursively
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, stl_base_path)
                        ext = os.path.splitext(file)[1].lower()

                        try:
                            file_size = os.path.getsize(abs_path)
                        except OSError:
                            file_size = 0

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
                                )
                                gcode_file.set_metadata(metadata)
                                session.add(gcode_file)
                                counts["gcode_files"] = counts.get("gcode_files", 0) + 1

        return counts

    def _process_gcode_base_path(
        self, session: Session, gcode_base_path: str, stl_base_path: str
    ) -> Dict[str, int]:
        """Process GCODE base path and link with STL files."""
        counts = {"gcode_files": 0}

        # Get all STL files for matching
        stl_files = session.query(STLFile).all()
        stl_name_map = {}  # Map STL file names to their folders

        for stl_file in stl_files:
            stl_name = os.path.splitext(stl_file.file_name)[0].lower()
            stl_name_map[stl_name] = stl_file

        # Process all G-code files
        for root, dirs, files in os.walk(gcode_base_path):
            for file in files:
                if file.lower().endswith(".gcode"):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, gcode_base_path)

                    try:
                        file_size = os.path.getsize(abs_path)
                    except OSError:
                        file_size = 0

                    # Try to find matching STL file
                    gcode_name = os.path.splitext(file)[0].lower()
                    matching_stl = None
                    matching_folder = None

                    for stl_name, stl_file in stl_name_map.items():
                        if search.search_tokens_all_match(
                            search.tokenize(stl_name), search.tokenize(gcode_name)
                        ):
                            matching_stl = stl_file
                            matching_folder = stl_file.folder
                            break

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
                        )
                        gcode_file.set_metadata(metadata)
                        session.add(gcode_file)
                        counts["gcode_files"] += 1

        return counts

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
                if stl_files:
                    folder_files = []
                    for stl_file in stl_files:
                        folder_files.append(
                            {"file_name": stl_file.file_name, "rel_path": stl_file.rel_path}
                        )

                    result.append(
                        {
                            "folder_name": folder.name,
                            "top_level_folder": folder.name,
                            "files": folder_files,
                        }
                    )

            return result

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
                gcode_files.append(
                    {
                        "file_name": gcode_file.file_name,
                        "path": gcode_file.base_path,
                        "rel_path": gcode_file.rel_path,
                        "metadata": gcode_file.get_metadata(),
                    }
                )

            # Also get G-code files that are associated with STL files in this folder
            for stl_file in folder.stl_files:
                for gcode_file in stl_file.gcode_files:
                    gcode_files.append(
                        {
                            "file_name": gcode_file.file_name,
                            "path": gcode_file.base_path,
                            "rel_path": gcode_file.rel_path,
                            "metadata": gcode_file.get_metadata(),
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

    def get_all_gcode_files(self) -> List[Dict[str, Any]]:
        """Get all G-code files with folder associations."""
        with self.get_session() as session:
            gcode_files = session.query(GCodeFile).all()
            result = []

            for gcode_file in gcode_files:
                folder_name = "Unknown"
                if gcode_file.folder:
                    folder_name = gcode_file.folder.name
                elif gcode_file.stl_file and gcode_file.stl_file.folder:
                    folder_name = gcode_file.stl_file.folder.name

                result.append(
                    {
                        "file_name": gcode_file.file_name,
                        "rel_path": gcode_file.rel_path,
                        "folder_name": folder_name,
                        "metadata": gcode_file.get_metadata(),
                        "base_path": gcode_file.base_path,
                    }
                )

            # Sort by folder name, then by file name
            result.sort(key=lambda x: (x["folder_name"], x["file_name"]))
            return result

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
        with self.get_session() as session:
            folder = Folder(name=folder_name)
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

            stl_file = STLFile(
                folder_id=folder.id, file_name=file_name, rel_path=rel_path, abs_path=abs_path
            )
            session.add(stl_file)
            session.commit()
            return stl_file
