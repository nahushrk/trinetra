"""
Database manager for Trinetra 3D model manager.
Handles all database operations and provides compatibility with existing app.py functions.
"""

import os
import logging
import re
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional, Iterable
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import and_, or_, text

from trinetra.models import (
    Base,
    Folder,
    STLFile,
    ThreeMFFile,
    ImageFile,
    PDFFile,
    GCodeFile,
    GCodeFileStats,
    ThreeMFProjectCache,
    ThreeMFPlateCache,
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
    THREE_MF_SUMMARY_VERSION = 1
    GCODE_HEADER_READ_LIMIT = 256 * 1024
    GCODE_TAIL_READ_LIMIT = 256 * 1024
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}

    def __init__(self, db_path="trinetra.db"):
        self.engine = create_database_engine(db_path)
        self.SessionFactory = create_session_factory(self.engine)
        init_database(self.engine)
        logger.info(f"Database initialized at {db_path}")
        self.stl_base_path = None
        self.gcode_base_path = None
        self._search_index_available = False
        self._ensure_search_index()
        self.rebuild_search_index()

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionFactory()

    @staticmethod
    def _file_times_from_stat(stat_result) -> Tuple[datetime, datetime]:
        created_at = datetime.fromtimestamp(stat_result.st_ctime)
        updated_at = datetime.fromtimestamp(stat_result.st_mtime)
        return created_at, updated_at

    @staticmethod
    def _is_supported_library_file(ext: str) -> bool:
        return ext in {".stl", ".3mf", ".pdf", ".gcode"} or ext in DatabaseManager.IMAGE_EXTENSIONS

    def _folder_file_scope_condition(self, folder_name: str):
        return or_(
            ThreeMFProjectCache.rel_path.like(f"{folder_name}/%"),
            ThreeMFProjectCache.rel_path == f"{folder_name}.3mf",
        )

    def _plate_cache_scope_condition(self, folder_name: str):
        return or_(
            ThreeMFPlateCache.rel_path.like(f"{folder_name}/%"),
            ThreeMFPlateCache.rel_path == f"{folder_name}.3mf",
        )

    def _three_mf_cache_scope_condition(self, folder_name: str):
        """Match cache rows belonging to a folder (real or virtual root-level folder)."""
        return self._folder_file_scope_condition(folder_name)

    def _prune_three_mf_cache_for_folder_locked(
        self, session: Session, folder_name: str, valid_rel_paths: set[str]
    ) -> int:
        removed = 0
        cached_rows = (
            session.query(ThreeMFProjectCache)
            .filter(self._three_mf_cache_scope_condition(folder_name))
            .all()
        )
        for cached_row in cached_rows:
            if cached_row.rel_path in valid_rel_paths:
                continue
            session.delete(cached_row)
            removed += 1
        return removed

    def _prune_three_mf_cache_for_folder(self, folder_name: str, valid_rel_paths: set[str]) -> int:
        with self.get_session() as session:
            removed = self._prune_three_mf_cache_for_folder_locked(
                session, folder_name, valid_rel_paths
            )
            if removed:
                session.commit()
            return removed

    def _prune_three_mf_plate_cache_for_folder_locked(
        self, session: Session, folder_name: str, valid_rel_paths: set[str]
    ) -> int:
        removed = 0
        cached_rows = (
            session.query(ThreeMFPlateCache)
            .filter(self._plate_cache_scope_condition(folder_name))
            .all()
        )
        for cached_row in cached_rows:
            if cached_row.rel_path in valid_rel_paths:
                continue
            session.delete(cached_row)
            removed += 1
        return removed

    def _prune_three_mf_plate_cache_for_folder(self, folder_name: str, valid_rel_paths: set[str]) -> int:
        with self.get_session() as session:
            removed = self._prune_three_mf_plate_cache_for_folder_locked(
                session, folder_name, valid_rel_paths
            )
            if removed:
                session.commit()
            return removed

    def _collect_all_three_mf_rel_paths(self) -> set[str]:
        with self.get_session() as session:
            return {rel_path for (rel_path,) in session.query(ThreeMFFile.rel_path).all()}

    def _prune_three_mf_cache_deleted_files(self, valid_rel_paths: set[str]) -> int:
        """Remove cached summaries for 3MF files that no longer exist."""
        with self.get_session() as session:
            removed = 0
            cached_rows = session.query(ThreeMFProjectCache).all()
            for cached_row in cached_rows:
                if cached_row.rel_path in valid_rel_paths:
                    continue
                session.delete(cached_row)
                removed += 1

            if removed:
                session.commit()
            return removed

    def _prune_three_mf_plate_cache_deleted_files(self, valid_rel_paths: set[str]) -> int:
        with self.get_session() as session:
            removed = 0
            cached_rows = session.query(ThreeMFPlateCache).all()
            for cached_row in cached_rows:
                if cached_row.rel_path in valid_rel_paths:
                    continue
                session.delete(cached_row)
                removed += 1
            if removed:
                session.commit()
            return removed

    def _ensure_search_index(self) -> None:
        """Initialize SQLite FTS5 search index for STL discovery."""
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS stl_search_index
                        USING fts5(
                            entity_type UNINDEXED,
                            folder_id UNINDEXED,
                            file_id UNINDEXED,
                            folder_name,
                            file_name,
                            rel_path,
                            tokenize='unicode61'
                        )
                        """
                    )
                )
            self._search_index_available = True
        except Exception as exc:
            self._search_index_available = False
            logger.warning("FTS5 index unavailable; search will use Python fallback: %s", exc)

    def rebuild_search_index(self) -> None:
        """Rebuild search index from current database rows."""
        if not self._search_index_available:
            return
        with self.get_session() as session:
            self._rebuild_search_index_locked(session)
            session.commit()

    def _rebuild_search_index_locked(self, session: Session) -> None:
        """Rebuild FTS table inside an existing session."""
        if not self._search_index_available:
            return
        session.execute(text("DELETE FROM stl_search_index"))
        session.execute(
            text(
                """
                INSERT INTO stl_search_index(
                    entity_type, folder_id, file_id, folder_name, file_name, rel_path
                )
                SELECT
                    'folder',
                    CAST(f.id AS TEXT),
                    '',
                    f.name,
                    '',
                    f.name
                FROM folders AS f
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO stl_search_index(
                    entity_type, folder_id, file_id, folder_name, file_name, rel_path
                )
                SELECT
                    'file',
                    CAST(f.id AS TEXT),
                    CAST(s.id AS TEXT),
                    f.name,
                    s.file_name,
                    s.rel_path
                FROM stl_files AS s
                INNER JOIN folders AS f ON f.id = s.folder_id
                """
            )
        )

    def _parse_int(self, value: Any) -> Optional[int]:
        try:
            if value in (None, "", "None"):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _filter_cutoff(self, filter_type: str) -> Optional[datetime]:
        if filter_type == "today":
            return datetime.utcnow() - timedelta(hours=24)
        if filter_type == "week":
            return datetime.utcnow() - timedelta(days=7)
        return None

    def _apply_stl_sorting(self, query, sort_by: str, sort_order: str):
        descending = sort_order.lower() == "desc"
        if sort_by == "file_name":
            order_column = STLFile.file_name
        elif sort_by == "created_at":
            order_column = STLFile.created_at
        elif sort_by == "updated_at":
            order_column = STLFile.updated_at
        else:
            order_column = STLFile.file_name
        return query.order_by(order_column.desc() if descending else order_column.asc())

    def _fetch_fts_candidates(self, session: Session, query_text: str, limit: int) -> List[Dict[str, Any]]:
        if not self._search_index_available:
            return []
        fts_query = search.build_fts_query(query_text)
        if not fts_query:
            return []

        try:
            rows = session.execute(
                text(
                    """
                    SELECT
                        entity_type,
                        folder_id,
                        file_id,
                        folder_name,
                        file_name,
                        rel_path,
                        bm25(stl_search_index) AS bm25
                    FROM stl_search_index
                    WHERE stl_search_index MATCH :fts_query
                    ORDER BY bm25(stl_search_index)
                    LIMIT :limit
                    """
                ),
                {"fts_query": fts_query, "limit": int(limit)},
            ).mappings()
            return [
                {
                    "entity_type": row.get("entity_type") or "",
                    "folder_id": self._parse_int(row.get("folder_id")),
                    "file_id": self._parse_int(row.get("file_id")),
                    "folder_name": row.get("folder_name") or "",
                    "file_name": row.get("file_name") or "",
                    "rel_path": row.get("rel_path") or "",
                    "bm25": float(row.get("bm25", 0.0)),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("FTS candidate query failed, using fallback: %s", exc)
            return []

    def _fetch_fallback_candidates(self, session: Session) -> List[Dict[str, Any]]:
        folders = session.query(Folder.id, Folder.name).all()
        files = (
            session.query(STLFile.id, STLFile.folder_id, STLFile.file_name, STLFile.rel_path, Folder.name)
            .join(Folder, Folder.id == STLFile.folder_id)
            .all()
        )

        candidates: List[Dict[str, Any]] = []
        for folder_id, folder_name in folders:
            candidates.append(
                {
                    "entity_type": "folder",
                    "folder_id": folder_id,
                    "file_id": None,
                    "folder_name": folder_name or "",
                    "file_name": "",
                    "rel_path": folder_name or "",
                }
            )

        for file_id, folder_id, file_name, rel_path, folder_name in files:
            candidates.append(
                {
                    "entity_type": "file",
                    "folder_id": folder_id,
                    "file_id": file_id,
                    "folder_name": folder_name or "",
                    "file_name": file_name or "",
                    "rel_path": rel_path or "",
                }
            )
        return candidates

    def _search_folder_matches(
        self,
        session: Session,
        query_text: str,
        filter_type: str,
        limit: int = 400,
    ) -> List[Dict[str, Any]]:
        candidates = self._fetch_fts_candidates(session, query_text, max(limit, 200))
        if len(candidates) < 40:
            fallback_candidates = self._fetch_fallback_candidates(session)
            seen = {
                (item.get("entity_type"), item.get("folder_id"), item.get("file_id"))
                for item in candidates
            }
            for candidate in fallback_candidates:
                key = (
                    candidate.get("entity_type"),
                    candidate.get("folder_id"),
                    candidate.get("file_id"),
                )
                if key not in seen:
                    candidates.append(candidate)
                    seen.add(key)

        ranked = search.rank_search_documents(query_text, candidates, limit=max(limit, 300))
        if not ranked:
            return []

        cutoff = self._filter_cutoff(filter_type)
        allowed_folder_ids = None
        allowed_file_ids = None
        if cutoff is not None:
            allowed_folder_ids = {
                folder_id
                for (folder_id,) in session.query(Folder.id).filter(Folder.created_at >= cutoff).all()
            }
            allowed_file_ids = {
                file_id
                for (file_id,) in session.query(STLFile.id).filter(STLFile.created_at >= cutoff).all()
            }

        folder_matches: Dict[int, Dict[str, Any]] = {}
        for match in ranked:
            folder_id = self._parse_int(match.get("folder_id"))
            if folder_id is None:
                continue

            entity_type = str(match.get("entity_type", ""))
            file_id = self._parse_int(match.get("file_id"))

            if cutoff is not None:
                if entity_type == "folder":
                    if folder_id not in allowed_folder_ids:
                        continue
                elif entity_type == "file":
                    if file_id is None or file_id not in allowed_file_ids:
                        continue

            bucket = folder_matches.setdefault(
                folder_id,
                {
                    "folder_id": folder_id,
                    "folder_name": match.get("folder_name", ""),
                    "score": 0,
                    "folder_name_matched": False,
                    "matched_file_ids": set(),
                },
            )
            score = int(match.get("score", 0))
            if score > bucket["score"]:
                bucket["score"] = score

            if entity_type == "folder":
                bucket["folder_name_matched"] = True
            elif entity_type == "file" and file_id is not None:
                bucket["matched_file_ids"].add(file_id)

        ordered = list(folder_matches.values())
        ordered.sort(key=lambda item: (item["score"], item["folder_name"]), reverse=True)
        return ordered

    def _scan_file_record(self, base_root: str, abs_path: str, stat_result) -> Dict[str, Any]:
        rel_path = os.path.relpath(abs_path, base_root)
        file_name = os.path.basename(abs_path)
        extension = os.path.splitext(file_name)[1].lower()
        created_at, updated_at = self._file_times_from_stat(stat_result)
        return {
            "file_name": file_name,
            "rel_path": rel_path,
            "abs_path": abs_path,
            "file_size": int(stat_result.st_size),
            "created_at": created_at,
            "updated_at": updated_at,
            "extension": extension,
        }

    def _scan_supported_tree(self, base_root: str, start_path: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        stack = [start_path]
        while stack:
            current_path = stack.pop()
            with os.scandir(current_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        extension = os.path.splitext(entry.name)[1].lower()
                        if not self._is_supported_library_file(extension):
                            continue
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        logger.warning("Skipping unreadable path %s: %s", entry.path, exc)
                        continue
                    records.append(self._scan_file_record(base_root, entry.path, stat_result))
        records.sort(key=lambda item: item["rel_path"])
        return records

    def _scan_folder_state(self, folder_name: str) -> Optional[Dict[str, Any]]:
        if not self.stl_base_path:
            return None

        folder_path = os.path.join(self.stl_base_path, folder_name)
        if os.path.isdir(folder_path):
            try:
                folder_stat = os.stat(folder_path)
            except OSError as exc:
                logger.warning("Skipping unreadable folder %s: %s", folder_path, exc)
                return None
            records = self._scan_supported_tree(self.stl_base_path, folder_path)
            if records:
                created_at = min(record["created_at"] for record in records)
                updated_at = max(record["updated_at"] for record in records)
            else:
                created_at, updated_at = self._file_times_from_stat(folder_stat)
            return {
                "folder_name": folder_name,
                "records": records,
                "created_at": created_at,
                "updated_at": updated_at,
            }

        root_three_mf = os.path.join(self.stl_base_path, f"{folder_name}.3mf")
        if not os.path.isfile(root_three_mf):
            return None

        try:
            stat_result = os.stat(root_three_mf)
        except OSError as exc:
            logger.warning("Skipping unreadable 3MF file %s: %s", root_three_mf, exc)
            return None

        record = self._scan_file_record(self.stl_base_path, root_three_mf, stat_result)
        if record["extension"] != ".3mf":
            return None
        return {
            "folder_name": folder_name,
            "records": [record],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def _iter_stl_folder_names(self) -> List[str]:
        if not self.stl_base_path or not os.path.isdir(self.stl_base_path):
            return []

        folder_names: List[str] = []
        real_dirs: set[str] = set()
        with os.scandir(self.stl_base_path) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        real_dirs.add(entry.name)
                        folder_names.append(entry.name)
                except OSError:
                    continue
        with os.scandir(self.stl_base_path) as entries:
            for entry in entries:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if not entry.name.lower().endswith(".3mf"):
                    continue
                virtual_folder_name = os.path.splitext(entry.name)[0]
                if virtual_folder_name in real_dirs:
                    continue
                folder_names.append(virtual_folder_name)
        folder_names.sort()
        return folder_names

    def _ensure_folder_locked(
        self, session: Session, folder_name: str, created_at: datetime, updated_at: datetime
    ) -> Tuple[Folder, bool]:
        folder = session.query(Folder).filter(Folder.name == folder_name).first()
        if folder is None:
            folder = Folder(name=folder_name, created_at=created_at, updated_at=updated_at)
            session.add(folder)
            session.flush()
            return folder, True

        folder.created_at = created_at
        folder.updated_at = updated_at
        return folder, False

    def _sync_basic_file_rows_locked(
        self,
        session: Session,
        folder: Folder,
        model_cls,
        records: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        existing_rows = {
            row.rel_path: row for row in session.query(model_cls).filter(model_cls.folder_id == folder.id).all()
        }
        counters = {"inserted": 0, "updated": 0, "deleted": 0}
        valid_rel_paths = {record["rel_path"] for record in records}

        for record in records:
            row = existing_rows.pop(record["rel_path"], None)
            if row is None:
                kwargs = {
                    "folder_id": folder.id,
                    "file_name": record["file_name"],
                    "rel_path": record["rel_path"],
                    "abs_path": record["abs_path"],
                    "file_size": record["file_size"],
                    "created_at": record["created_at"],
                    "updated_at": record["updated_at"],
                }
                if model_cls is ImageFile:
                    kwargs["extension"] = record["extension"]
                session.add(model_cls(**kwargs))
                counters["inserted"] += 1
                continue

            changed = False
            for key in ("file_name", "abs_path", "file_size", "created_at", "updated_at"):
                value = record[key]
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            if model_cls is ImageFile and row.extension != record["extension"]:
                row.extension = record["extension"]
                changed = True
            if changed:
                counters["updated"] += 1

        for row in existing_rows.values():
            if row.rel_path not in valid_rel_paths:
                session.delete(row)
                counters["deleted"] += 1

        return counters

    def _sync_stl_folder_gcode_rows_locked(
        self, session: Session, folder: Folder, records: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        existing_rows = {
            row.rel_path: row
            for row in session.query(GCodeFile)
            .filter(GCodeFile.folder_id == folder.id, GCodeFile.base_path == "STL_BASE_PATH")
            .all()
        }
        counters = {"inserted": 0, "updated": 0, "deleted": 0}
        valid_rel_paths = {record["rel_path"] for record in records}

        for record in records:
            metadata = self._extract_gcode_metadata(record["abs_path"])
            row = existing_rows.pop(record["rel_path"], None)
            if row is None:
                row = GCodeFile(
                    folder_id=folder.id,
                    stl_file_id=None,
                    file_name=record["file_name"],
                    rel_path=record["rel_path"],
                    abs_path=record["abs_path"],
                    file_size=record["file_size"],
                    base_path="STL_BASE_PATH",
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
                row.set_metadata(metadata)
                session.add(row)
                counters["inserted"] += 1
                continue

            changed = False
            for key in ("file_name", "abs_path", "file_size", "created_at", "updated_at"):
                value = record[key]
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            existing_metadata = row.get_metadata()
            if existing_metadata != metadata:
                row.set_metadata(metadata)
                changed = True
            if changed:
                counters["updated"] += 1

        for row in existing_rows.values():
            if row.rel_path not in valid_rel_paths:
                session.delete(row)
                counters["deleted"] += 1

        return counters

    def _sync_folder_state_locked(self, session: Session, folder_state: Dict[str, Any]) -> Dict[str, int]:
        folder, created = self._ensure_folder_locked(
            session,
            folder_state["folder_name"],
            folder_state["created_at"],
            folder_state["updated_at"],
        )
        records = folder_state["records"]

        stl_records = [record for record in records if record["extension"] == ".stl"]
        three_mf_records = [record for record in records if record["extension"] == ".3mf"]
        image_records = [
            record for record in records if record["extension"] in self.IMAGE_EXTENSIONS
        ]
        pdf_records = [record for record in records if record["extension"] == ".pdf"]
        gcode_records = [record for record in records if record["extension"] == ".gcode"]

        counters = {
            "folders": 1 if created else 0,
            "stl_files": 0,
            "three_mf_files": 0,
            "image_files": 0,
            "pdf_files": 0,
            "gcode_files": 0,
        }

        counters["stl_files"] = self._sync_basic_file_rows_locked(session, folder, STLFile, stl_records)["inserted"]
        counters["three_mf_files"] = self._sync_basic_file_rows_locked(
            session, folder, ThreeMFFile, three_mf_records
        )["inserted"]
        counters["image_files"] = self._sync_basic_file_rows_locked(
            session, folder, ImageFile, image_records
        )["inserted"]
        counters["pdf_files"] = self._sync_basic_file_rows_locked(session, folder, PDFFile, pdf_records)[
            "inserted"
        ]
        counters["gcode_files"] = self._sync_stl_folder_gcode_rows_locked(
            session, folder, gcode_records
        )["inserted"]

        valid_rel_paths = {record["rel_path"] for record in three_mf_records}
        self._prune_three_mf_cache_for_folder_locked(session, folder.name, valid_rel_paths)
        self._prune_three_mf_plate_cache_for_folder_locked(session, folder.name, valid_rel_paths)
        return counters

    def _delete_folder_locked(self, session: Session, folder: Folder) -> None:
        self._prune_three_mf_cache_for_folder_locked(session, folder.name, set())
        self._prune_three_mf_plate_cache_for_folder_locked(session, folder.name, set())
        session.delete(folder)

    def _build_stl_lookup_locked(self, session: Session) -> Dict[str, STLFile]:
        stl_lookup: Dict[str, STLFile] = {}
        for stl_file in session.query(STLFile).all():
            basename = os.path.splitext(stl_file.file_name)[0]
            stl_lookup[basename] = stl_file
        return stl_lookup

    def _find_best_matching_stl(self, gcode_base: str, stl_lookup: Dict[str, STLFile]) -> Optional[STLFile]:
        for end in range(len(gcode_base), 0, -1):
            candidate = gcode_base[:end]
            stl_file = stl_lookup.get(candidate)
            if stl_file is not None:
                return stl_file
        return None

    def _scan_gcode_root_records(self) -> List[Dict[str, Any]]:
        if not self.gcode_base_path or not os.path.isdir(self.gcode_base_path):
            return []
        records = []
        stack = [self.gcode_base_path]
        while stack:
            current_path = stack.pop()
            with os.scandir(current_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if not entry.name.lower().endswith(".gcode"):
                            continue
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        logger.warning("Skipping unreadable G-code path %s: %s", entry.path, exc)
                        continue
                    records.append(self._scan_file_record(self.gcode_base_path, entry.path, stat_result))
        records.sort(key=lambda item: item["rel_path"])
        return records

    def _sync_gcode_root_rows_locked(
        self,
        session: Session,
        records: List[Dict[str, Any]],
        stl_lookup: Dict[str, STLFile],
        *,
        limit_rel_paths: Optional[set[str]] = None,
    ) -> Dict[str, int]:
        existing_query = session.query(GCodeFile).filter(GCodeFile.base_path == "GCODE_BASE_PATH")
        if limit_rel_paths is not None:
            existing_query = existing_query.filter(GCodeFile.rel_path.in_(list(limit_rel_paths)))
            records = [record for record in records if record["rel_path"] in limit_rel_paths]
        existing_rows = {row.rel_path: row for row in existing_query.all()}
        counters = {"inserted": 0, "updated": 0, "deleted": 0}
        valid_rel_paths = {record["rel_path"] for record in records}

        for record in records:
            matching_stl = self._find_best_matching_stl(self._split_base(record["file_name"]), stl_lookup)
            matching_folder = matching_stl.folder if matching_stl is not None else None
            metadata = self._extract_gcode_metadata(record["abs_path"])

            row = existing_rows.pop(record["rel_path"], None)
            if row is None:
                row = GCodeFile(
                    folder_id=matching_folder.id if matching_folder else None,
                    stl_file_id=matching_stl.id if matching_stl else None,
                    file_name=record["file_name"],
                    rel_path=record["rel_path"],
                    abs_path=record["abs_path"],
                    file_size=record["file_size"],
                    base_path="GCODE_BASE_PATH",
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
                row.set_metadata(metadata)
                session.add(row)
                counters["inserted"] += 1
                continue

            changed = False
            for key in ("file_name", "abs_path", "file_size", "created_at", "updated_at"):
                value = record[key]
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            folder_id = matching_folder.id if matching_folder else None
            stl_file_id = matching_stl.id if matching_stl else None
            if row.folder_id != folder_id:
                row.folder_id = folder_id
                changed = True
            if row.stl_file_id != stl_file_id:
                row.stl_file_id = stl_file_id
                changed = True
            existing_metadata = row.get_metadata()
            if existing_metadata != metadata:
                row.set_metadata(metadata)
                changed = True
            if changed:
                counters["updated"] += 1

        for row in existing_rows.values():
            if row.rel_path not in valid_rel_paths:
                session.delete(row)
                counters["deleted"] += 1

        return counters

    def _relink_gcode_root_rows_locked(self, session: Session, stl_lookup: Dict[str, STLFile]) -> None:
        rows = session.query(GCodeFile).filter(GCodeFile.base_path == "GCODE_BASE_PATH").all()
        for row in rows:
            matching_stl = self._find_best_matching_stl(self._split_base(row.file_name), stl_lookup)
            matching_folder = matching_stl.folder if matching_stl is not None else None
            row.folder_id = matching_folder.id if matching_folder else None
            row.stl_file_id = matching_stl.id if matching_stl else None

    def _reconcile_stl_folders_locked(
        self, session: Session, folder_names: Optional[Iterable[str]] = None
    ) -> None:
        target_folder_names = set(folder_names or self._iter_stl_folder_names())
        existing_folders = {folder.name: folder for folder in session.query(Folder).all()}

        for folder_name in sorted(target_folder_names):
            folder_state = self._scan_folder_state(folder_name)
            if folder_state is None:
                existing_folder = existing_folders.pop(folder_name, None)
                if existing_folder is not None:
                    self._delete_folder_locked(session, existing_folder)
                continue
            self._sync_folder_state_locked(session, folder_state)
            existing_folders.pop(folder_name, None)

        if folder_names is None:
            for missing_folder in existing_folders.values():
                self._delete_folder_locked(session, missing_folder)

    def _reconcile_gcode_root_locked(
        self, session: Session, stl_lookup: Dict[str, STLFile], rel_paths: Optional[set[str]] = None
    ) -> None:
        records = self._scan_gcode_root_records()
        self._sync_gcode_root_rows_locked(session, records, stl_lookup, limit_rel_paths=rel_paths)

    def _current_index_counts_locked(self, session: Session) -> Dict[str, int]:
        return {
            "folders": session.query(Folder).count(),
            "stl_files": session.query(STLFile).count(),
            "three_mf_files": session.query(ThreeMFFile).count(),
            "image_files": session.query(ImageFile).count(),
            "pdf_files": session.query(PDFFile).count(),
            "gcode_files": session.query(GCodeFile).count(),
        }

    def refresh_changed_files(
        self,
        *,
        stl_folder_names: Optional[Iterable[str]] = None,
        gcode_rel_paths: Optional[Iterable[str]] = None,
    ) -> Dict[str, int]:
        with self.get_session() as session:
            try:
                if stl_folder_names is not None:
                    self._reconcile_stl_folders_locked(session, set(stl_folder_names))
                stl_lookup = self._build_stl_lookup_locked(session)
                if gcode_rel_paths is not None:
                    self._reconcile_gcode_root_locked(session, stl_lookup, set(gcode_rel_paths))
                if stl_folder_names is not None and gcode_rel_paths is None:
                    self._relink_gcode_root_rows_locked(session, stl_lookup)
                self._rebuild_search_index_locked(session)
                session.commit()
                return self._current_index_counts_locked(session)
            except Exception:
                session.rollback()
                logger.exception("Incremental file refresh failed")
                raise

    def reload_index(
        self,
        stl_base_path: str,
        gcode_base_path: str,
        moonraker_url: Optional[str] = None,
        moonraker_client: Optional[PrinterServiceClient] = None,
    ) -> Dict[str, int]:
        """Incrementally reconcile the entire index from filesystem."""
        self.stl_base_path = stl_base_path
        self.gcode_base_path = gcode_base_path
        logger.info(f"Starting full index reload - STL: {stl_base_path}, GCODE: {gcode_base_path}")
        with self.get_session() as session:
            try:
                self._reconcile_stl_folders_locked(session)
                stl_lookup = self._build_stl_lookup_locked(session)
                self._reconcile_gcode_root_locked(session, stl_lookup)
                self._rebuild_search_index_locked(session)
                session.commit()
                counts = self._current_index_counts_locked(session)
            except Exception:
                session.rollback()
                logger.exception("Index reload failed. Existing DB state has been preserved.")
                raise

        try:
            valid_three_mf_rel_paths = self._collect_all_three_mf_rel_paths()
            pruned_three_mf_cache = self._prune_three_mf_cache_deleted_files(valid_three_mf_rel_paths)
            if pruned_three_mf_cache:
                counts["three_mf_cache_pruned"] = pruned_three_mf_cache
            pruned_plate_cache = self._prune_three_mf_plate_cache_deleted_files(valid_three_mf_rel_paths)
            if pruned_plate_cache:
                counts["three_mf_plate_cache_pruned"] = pruned_plate_cache
        except Exception as exc:
            logger.warning("Failed to prune stale 3MF cache entries after reload: %s", exc)

        # Update Moonraker stats only after file/index transaction is committed.
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
            with open(file_path, "rb") as file:
                header_bytes = file.read(self.GCODE_HEADER_READ_LIMIT)
                try:
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    tail_size = min(file_size, self.GCODE_TAIL_READ_LIMIT)
                    file.seek(max(file_size - tail_size, 0))
                    tail_bytes = file.read(tail_size)
                except OSError:
                    tail_bytes = b""

            header_text = header_bytes.decode("utf-8", errors="ignore")
            tail_text = tail_bytes.decode("utf-8", errors="ignore")
            return gcode_handler.extract_gcode_metadata_from_parts(header_text, tail_text)
        except Exception as e:
            logger.error(f"Error reading G-code file {file_path}: {e}")
            return {}

    @staticmethod
    def _serialize_stl_file(stl_file: STLFile) -> Dict[str, Any]:
        return {"file_name": stl_file.file_name, "rel_path": stl_file.rel_path}

    @staticmethod
    def _serialize_gcode_stats(stats: Optional[GCodeFileStats]) -> Optional[Dict[str, Any]]:
        if not stats:
            return None

        avg_duration = 0
        if stats.print_count > 0 and stats.total_print_time > 0:
            avg_duration = stats.total_print_time / stats.print_count

        return {
            "print_count": stats.print_count,
            "total_prints": stats.print_count,
            "successful_prints": stats.successful_prints,
            "canceled_prints": stats.canceled_prints,
            "avg_duration": avg_duration,
            "total_print_time": stats.total_print_time,
            "total_filament_used": stats.total_filament_used,
            "last_print_date": stats.last_print_date.isoformat() if stats.last_print_date else None,
            "success_rate": stats.success_rate,
            "job_id": stats.job_id,
            "last_status": stats.last_status,
        }

    @staticmethod
    def _stats_row_from_gcode(gcode_file: GCodeFile) -> Optional[GCodeFileStats]:
        stats = getattr(gcode_file, "stats", None)
        if isinstance(stats, list):
            return stats[0] if stats else None
        return stats

    @staticmethod
    def _folder_name_for_gcode(gcode_file: GCodeFile) -> str:
        if gcode_file.folder:
            return gcode_file.folder.name
        if gcode_file.stl_file and gcode_file.stl_file.folder:
            return gcode_file.stl_file.folder.name
        return "Unknown"

    def _serialize_gcode_file(self, gcode_file: GCodeFile) -> Dict[str, Any]:
        return {
            "file_name": gcode_file.file_name,
            "rel_path": gcode_file.rel_path,
            "folder_name": self._folder_name_for_gcode(gcode_file),
            "metadata": gcode_file.get_metadata(),
            "base_path": gcode_file.base_path,
            "stats": self._serialize_gcode_stats(self._stats_row_from_gcode(gcode_file)),
        }

    def _apply_folder_sorting(self, query, sort_by: str, sort_order: str):
        descending = sort_order.lower() == "desc"
        if sort_by == "created_at":
            order_column = Folder.created_at
        elif sort_by == "updated_at":
            order_column = Folder.updated_at
        else:
            order_column = Folder.name
        return query.order_by(order_column.desc() if descending else order_column.asc())

    def _load_stl_rows_for_folders(
        self,
        session: Session,
        folder_ids: List[int],
        sort_by: str,
        sort_order: str,
        cutoff: Optional[datetime] = None,
    ) -> Dict[int, List[STLFile]]:
        if not folder_ids:
            return {}

        query = session.query(STLFile).filter(STLFile.folder_id.in_(folder_ids))
        if cutoff is not None:
            query = query.filter(STLFile.created_at >= cutoff)
        stl_rows = self._apply_stl_sorting(query, sort_by, sort_order).all()

        grouped: Dict[int, List[STLFile]] = defaultdict(list)
        for stl_row in stl_rows:
            grouped[stl_row.folder_id].append(stl_row)
        return grouped

    def _load_three_mf_projects_for_folders(
        self, session: Session, folders: List[Folder]
    ) -> Tuple[Dict[int, List[Dict[str, Any]]], bool]:
        if not folders:
            return {}, False

        folder_ids = [folder.id for folder in folders]
        folders_by_id = {folder.id: folder for folder in folders}
        three_mf_rows = (
            session.query(ThreeMFFile)
            .filter(ThreeMFFile.folder_id.in_(folder_ids))
            .order_by(ThreeMFFile.folder_id.asc(), ThreeMFFile.file_name.asc())
            .all()
        )

        candidate_records_by_folder: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        valid_rel_paths_by_folder: Dict[int, set[str]] = defaultdict(set)
        candidate_rel_paths: List[str] = []

        for three_mf_row in three_mf_rows:
            try:
                stat_result = os.stat(three_mf_row.abs_path)
            except OSError as exc:
                logger.warning("Skipping unreadable indexed 3MF file %s: %s", three_mf_row.abs_path, exc)
                continue

            candidate_records_by_folder[three_mf_row.folder_id].append(
                {
                    "abs_path": three_mf_row.abs_path,
                    "rel_path": three_mf_row.rel_path,
                    "file_name": three_mf_row.file_name,
                    "file_mtime_ns": int(stat_result.st_mtime_ns),
                    "file_size": int(stat_result.st_size),
                }
            )
            valid_rel_paths_by_folder[three_mf_row.folder_id].add(three_mf_row.rel_path)
            candidate_rel_paths.append(three_mf_row.rel_path)

        cache_by_rel_path: Dict[str, ThreeMFProjectCache] = {}
        if candidate_rel_paths:
            cache_rows = (
                session.query(ThreeMFProjectCache)
                .filter(ThreeMFProjectCache.rel_path.in_(candidate_rel_paths))
                .all()
            )
            cache_by_rel_path = {row.rel_path: row for row in cache_rows}

        existing_cache_rows_by_rel_path: Dict[str, ThreeMFProjectCache] = {}
        results_by_folder: Dict[int, List[Dict[str, Any]]] = {}
        cache_mutated = False

        for folder in folders:
            folder_results: List[Dict[str, Any]] = []
            for item in candidate_records_by_folder.get(folder.id, []):
                payload: Optional[Dict[str, Any]] = None
                cache_row = cache_by_rel_path.get(item["rel_path"])
                if (
                    cache_row
                    and cache_row.summary_version == self.THREE_MF_SUMMARY_VERSION
                    and cache_row.file_mtime_ns == item["file_mtime_ns"]
                    and cache_row.file_size == item["file_size"]
                ):
                    try:
                        decoded_payload = json.loads(cache_row.summary_json)
                        if isinstance(decoded_payload, dict):
                            payload = decoded_payload
                    except (TypeError, json.JSONDecodeError):
                        payload = None

                if payload is None:
                    payload = self._build_three_mf_summary_payload(item["abs_path"], item["rel_path"])
                    row = existing_cache_rows_by_rel_path.get(item["rel_path"])
                    if row is None:
                        row = cache_by_rel_path.get(item["rel_path"])
                    if row is None:
                        row = ThreeMFProjectCache(rel_path=item["rel_path"])
                        session.add(row)
                    row.file_mtime_ns = item["file_mtime_ns"]
                    row.file_size = item["file_size"]
                    row.summary_version = self.THREE_MF_SUMMARY_VERSION
                    row.summary_json = json.dumps(payload, ensure_ascii=True)
                    existing_cache_rows_by_rel_path[item["rel_path"]] = row
                    cache_mutated = True

                folder_results.append(payload)

            results_by_folder[folder.id] = folder_results
            if (
                self._prune_three_mf_cache_for_folder_locked(
                    session,
                    folder.name,
                    valid_rel_paths_by_folder.get(folder.id, set()),
                )
                > 0
            ):
                cache_mutated = True

        return results_by_folder, cache_mutated

    def _build_stl_folder_payloads(
        self,
        folders: List[Folder],
        stl_rows_by_folder: Dict[int, List[STLFile]],
        three_mf_projects_by_folder: Dict[int, List[Dict[str, Any]]],
        *,
        full_folder_ids: Optional[set[int]] = None,
        matched_file_ids_by_folder: Optional[Dict[int, set[int]]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        result: List[Dict[str, Any]] = []
        total_files = 0
        full_folder_ids = full_folder_ids or set()
        matched_file_ids_by_folder = matched_file_ids_by_folder or {}

        for folder in folders:
            stl_rows = stl_rows_by_folder.get(folder.id, [])
            if folder.id not in full_folder_ids:
                matched_ids = matched_file_ids_by_folder.get(folder.id)
                if matched_ids is not None:
                    stl_rows = [stl_row for stl_row in stl_rows if stl_row.id in matched_ids]

            folder_files = [self._serialize_stl_file(stl_row) for stl_row in stl_rows]
            three_mf_projects = three_mf_projects_by_folder.get(folder.id, [])
            if folder_files or three_mf_projects:
                total_files += len(folder_files)
                result.append(
                    {
                        "folder_name": folder.name,
                        "top_level_folder": folder.name,
                        "files": folder_files,
                        "three_mf_projects": three_mf_projects,
                    }
                )

        return result, total_files

    def get_stl_files(self) -> List[Dict[str, Any]]:
        """Get all STL files organized by folders (compatible with existing app.py)."""
        with self.get_session() as session:
            folders = session.query(Folder).order_by(Folder.name.asc()).all()
            folder_ids = [folder.id for folder in folders]
            stl_rows_by_folder = self._load_stl_rows_for_folders(
                session, folder_ids, sort_by="file_name", sort_order="asc"
            )
            three_mf_projects_by_folder, cache_mutated = self._load_three_mf_projects_for_folders(
                session, folders
            )
            if cache_mutated:
                session.commit()
            result, _total_files = self._build_stl_folder_payloads(
                folders, stl_rows_by_folder, three_mf_projects_by_folder
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
        page = max(1, int(page or 1))
        per_page = int(per_page or 15)
        if per_page <= 0:
            per_page = 15
        per_page = min(per_page, 200)

        with self.get_session() as session:
            cutoff = self._filter_cutoff(filter_type)
            if (filter_text or "").strip():
                folder_matches = self._search_folder_matches(
                    session,
                    query_text=filter_text,
                    filter_type=filter_type,
                    limit=max(500, per_page * 40),
                )
                total_folders = len(folder_matches)
                paged_matches = folder_matches[(page - 1) * per_page : page * per_page]
                folder_ids = [match["folder_id"] for match in paged_matches]
                folders_map: Dict[int, Folder] = {}
                if folder_ids:
                    folders = session.query(Folder).filter(Folder.id.in_(folder_ids)).all()
                    folders_map = {folder.id: folder for folder in folders}

                ordered_folders = [
                    folders_map[folder_id]
                    for folder_id in folder_ids
                    if folder_id in folders_map
                ]
                stl_rows_by_folder = self._load_stl_rows_for_folders(
                    session, [folder.id for folder in ordered_folders], sort_by, sort_order, cutoff
                )
                three_mf_projects_by_folder, cache_mutated = self._load_three_mf_projects_for_folders(
                    session, ordered_folders
                )

                full_folder_ids = {
                    match["folder_id"] for match in paged_matches if match.get("folder_name_matched")
                }
                matched_file_ids_by_folder = {
                    match["folder_id"]: set(match.get("matched_file_ids", set()))
                    for match in paged_matches
                    if not match.get("folder_name_matched")
                }
                result, total_files = self._build_stl_folder_payloads(
                    ordered_folders,
                    stl_rows_by_folder,
                    three_mf_projects_by_folder,
                    full_folder_ids=full_folder_ids,
                    matched_file_ids_by_folder=matched_file_ids_by_folder,
                )
                if cache_mutated:
                    session.commit()

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

            query = session.query(Folder)
            if cutoff is not None:
                query = query.filter(Folder.created_at >= cutoff)
            query = self._apply_folder_sorting(query, sort_by, sort_order)
            total_folders = query.count()
            folders = query.offset((page - 1) * per_page).limit(per_page).all()
            folder_ids = [folder.id for folder in folders]
            stl_rows_by_folder = self._load_stl_rows_for_folders(
                session, folder_ids, sort_by, sort_order, cutoff
            )
            three_mf_projects_by_folder, cache_mutated = self._load_three_mf_projects_for_folders(
                session, folders
            )
            result, total_files = self._build_stl_folder_payloads(
                folders, stl_rows_by_folder, three_mf_projects_by_folder
            )
            if cache_mutated:
                session.commit()

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
            folder = (
                session.query(Folder)
                .options(
                    selectinload(Folder.stl_files),
                    selectinload(Folder.image_files),
                    selectinload(Folder.pdf_files),
                    selectinload(Folder.gcode_files).selectinload(GCodeFile.stats),
                    selectinload(Folder.stl_files)
                    .selectinload(STLFile.gcode_files)
                    .selectinload(GCodeFile.stats),
                )
                .filter(Folder.name == folder_name)
                .first()
            )
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
                        "stats": self._serialize_gcode_stats(self._stats_row_from_gcode(gcode_file)),
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
                            "stats": self._serialize_gcode_stats(
                                self._stats_row_from_gcode(gcode_file)
                            ),
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

    def _build_three_mf_summary_payload(self, abs_path: str, rel_path: str) -> Dict[str, Any]:
        file_name = os.path.basename(abs_path)
        try:
            parsed = three_mf.load_3mf_project(abs_path)
            summary = three_mf.project_to_summary(parsed)
            settings = three_mf.summarize_settings(summary.get("project_settings", {}), max_items=10)
            model_metadata = three_mf.summarize_model_metadata(
                summary.get("model_metadata", {}), max_items=4
            )
            return {
                "file_name": file_name,
                "rel_path": rel_path,
                "model_metadata": model_metadata,
                "project_settings": settings,
                "plates": summary.get("plates", []),
            }
        except Exception as exc:
            logger.warning("Failed to parse 3MF project %s: %s", abs_path, exc)
            return {
                "file_name": file_name,
                "rel_path": rel_path,
                "model_metadata": {},
                "project_settings": {},
                "plates": [],
                "error": str(exc),
            }

    def get_folder_three_mf_projects(self, folder_name: str) -> List[Dict[str, Any]]:
        """Get parsed 3MF project data for a folder with persistent cache."""
        with self.get_session() as session:
            folder = session.query(Folder).filter(Folder.name == folder_name).first()
            if folder is None:
                return []

            projects_by_folder, cache_mutated = self._load_three_mf_projects_for_folders(
                session, [folder]
            )
            if cache_mutated:
                session.commit()
            return projects_by_folder.get(folder.id, [])

    def get_three_mf_plate_stl_bytes(self, rel_path: str, plate_index: int) -> Optional[bytes]:
        """Return cached/generated STL bytes for a 3MF plate preview."""
        with self.get_session() as session:
            three_mf_file = (
                session.query(ThreeMFFile).filter(ThreeMFFile.rel_path == rel_path).first()
            )
            if three_mf_file is None:
                return None

            try:
                stat_result = os.stat(three_mf_file.abs_path)
            except OSError as exc:
                logger.warning("Indexed 3MF file is unreadable %s: %s", three_mf_file.abs_path, exc)
                (
                    session.query(ThreeMFPlateCache)
                    .filter(ThreeMFPlateCache.rel_path == rel_path)
                    .delete(synchronize_session=False)
                )
                session.commit()
                return None

            file_mtime_ns = int(stat_result.st_mtime_ns)
            file_size = int(stat_result.st_size)
            cache_row = (
                session.query(ThreeMFPlateCache)
                .filter(
                    ThreeMFPlateCache.rel_path == rel_path,
                    ThreeMFPlateCache.plate_index == int(plate_index),
                )
                .first()
            )
            if (
                cache_row is not None
                and cache_row.summary_version == self.THREE_MF_SUMMARY_VERSION
                and cache_row.file_mtime_ns == file_mtime_ns
                and cache_row.file_size == file_size
            ):
                return bytes(cache_row.stl_blob)

            parsed = three_mf.load_3mf_project(three_mf_file.abs_path)
            triangles = three_mf.get_plate_triangles(parsed, plate_index)
            if not triangles:
                return None

            stl_bytes = three_mf.build_plate_stl_bytes(
                parsed,
                plate_index,
                header_text=f"{os.path.basename(rel_path)} plate {plate_index}",
            )
            if cache_row is None:
                cache_row = ThreeMFPlateCache(rel_path=rel_path, plate_index=int(plate_index))
                session.add(cache_row)
            cache_row.file_mtime_ns = file_mtime_ns
            cache_row.file_size = file_size
            cache_row.summary_version = self.THREE_MF_SUMMARY_VERSION
            cache_row.stl_blob = stl_bytes
            session.commit()
            return stl_bytes

    def get_all_gcode_files(self) -> List[Dict[str, Any]]:
        """Get all G-code files with folder associations and stats."""
        with self.get_session() as session:
            gcode_files = (
                session.query(GCodeFile)
                .options(
                    selectinload(GCodeFile.folder),
                    selectinload(GCodeFile.stl_file).selectinload(STLFile.folder),
                    selectinload(GCodeFile.stats),
                )
                .all()
            )
            result = [self._serialize_gcode_file(gcode_file) for gcode_file in gcode_files]
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
            page = max(1, int(page or 1))
            per_page = int(per_page or 15)
            if per_page <= 0:
                per_page = 15
            per_page = min(per_page, 200)

            query = (
                session.query(GCodeFile)
                .options(
                    selectinload(GCodeFile.folder),
                    selectinload(GCodeFile.stl_file).selectinload(STLFile.folder),
                    selectinload(GCodeFile.stats),
                )
                .outerjoin(GCodeFileStats, GCodeFileStats.gcode_file_id == GCodeFile.id)
                .outerjoin(Folder, GCodeFile.folder_id == Folder.id)
            )

            if filter_type == "today":
                twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
                query = query.filter(GCodeFile.created_at >= twenty_four_hours_ago)
            elif filter_type == "week":
                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                query = query.filter(GCodeFile.created_at >= seven_days_ago)
            elif filter_type == "successful":
                query = query.filter(
                    and_(
                        GCodeFileStats.successful_prints > 0,
                        GCodeFileStats.successful_prints.isnot(None),
                    )
                )
            elif filter_type == "failed":
                query = query.filter(
                    and_(
                        GCodeFileStats.successful_prints == 0,
                        GCodeFileStats.print_count > 0,
                        GCodeFileStats.successful_prints.isnot(None),
                        GCodeFileStats.print_count.isnot(None),
                    )
                )

            if filter_text:
                query = query.filter(
                    or_(
                        GCodeFile.file_name.contains(filter_text),
                        GCodeFile.rel_path.contains(filter_text),
                        Folder.name.contains(filter_text),
                    )
                )

            if sort_by == "file_name":
                order_column = GCodeFile.file_name
            elif sort_by == "folder_name":
                order_column = Folder.name
            elif sort_by == "print_count":
                order_column = GCodeFileStats.print_count
            elif sort_by == "last_print_date":
                order_column = GCodeFileStats.last_print_date
            elif sort_by == "created_at":
                order_column = GCodeFile.created_at
            elif sort_by == "updated_at":
                order_column = GCodeFile.updated_at
            else:
                order_column = Folder.name

            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc(), GCodeFile.file_name.desc())
            else:
                query = query.order_by(order_column.asc(), GCodeFile.file_name.asc())

            total_files = query.order_by(None).count()
            gcode_files = query.offset((page - 1) * per_page).limit(per_page).all()
            result = [self._serialize_gcode_file(gcode_file) for gcode_file in gcode_files]

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
        if not query.strip():
            return self.get_stl_files()

        with self.get_session() as session:
            folder_matches = self._search_folder_matches(
                session,
                query_text=query,
                filter_type="all",
                limit=max(200, limit * 20),
            )[:limit]
            if not folder_matches:
                return []

            folder_ids = [match["folder_id"] for match in folder_matches]
            folders = session.query(Folder).filter(Folder.id.in_(folder_ids)).all()
            folders_map = {folder.id: folder for folder in folders}
            ordered_folders = [
                folders_map[folder_id]
                for folder_id in folder_ids
                if folder_id in folders_map
            ]
            stl_rows_by_folder = self._load_stl_rows_for_folders(
                session, [folder.id for folder in ordered_folders], "file_name", "asc"
            )
            three_mf_projects_by_folder, cache_mutated = self._load_three_mf_projects_for_folders(
                session, ordered_folders
            )
            full_folder_ids = {
                match["folder_id"] for match in folder_matches if match.get("folder_name_matched")
            }
            matched_file_ids_by_folder = {
                match["folder_id"]: set(match.get("matched_file_ids", set()))
                for match in folder_matches
                if not match.get("folder_name_matched")
            }
            result, _total_files = self._build_stl_folder_payloads(
                ordered_folders,
                stl_rows_by_folder,
                three_mf_projects_by_folder,
                full_folder_ids=full_folder_ids,
                matched_file_ids_by_folder=matched_file_ids_by_folder,
            )
            if cache_mutated:
                session.commit()
            return result

    def search_gcode_files(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Search G-code files."""
        if not query.strip():
            return self.get_all_gcode_files()

        with self.get_session() as session:
            tokens = search.tokenize_text(query)[:6]
            candidate_clauses = []
            for token in tokens or [query.strip()]:
                pattern = f"%{token}%"
                candidate_clauses.extend(
                    [
                        GCodeFile.file_name.ilike(pattern),
                        GCodeFile.rel_path.ilike(pattern),
                        Folder.name.ilike(pattern),
                    ]
                )

            candidate_limit = max(limit * 20, 200)
            query_obj = (
                session.query(GCodeFile)
                .options(
                    selectinload(GCodeFile.folder),
                    selectinload(GCodeFile.stl_file).selectinload(STLFile.folder),
                    selectinload(GCodeFile.stats),
                )
                .outerjoin(Folder, GCodeFile.folder_id == Folder.id)
            )

            candidate_rows = []
            if candidate_clauses:
                candidate_rows = (
                    query_obj.filter(or_(*candidate_clauses))
                    .order_by(GCodeFile.updated_at.desc())
                    .limit(candidate_limit)
                    .all()
                )

            if not candidate_rows:
                candidate_rows = (
                    query_obj.order_by(GCodeFile.updated_at.desc()).limit(candidate_limit).all()
                )

            serialized_rows = [self._serialize_gcode_file(gcode_row) for gcode_row in candidate_rows]
            return search.search_gcode_files(query, serialized_rows, limit)

    def get_moonraker_stats_for_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get stats for a single file without scanning every G-code row."""
        with self.get_session() as session:
            gcode_file = (
                session.query(GCodeFile)
                .options(selectinload(GCodeFile.stats))
                .filter(GCodeFile.file_name == filename)
                .order_by(GCodeFile.updated_at.desc())
                .first()
            )
            if gcode_file is None:
                return None
            return self._serialize_gcode_stats(self._stats_row_from_gcode(gcode_file))

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
                self.rebuild_search_index()
                self._prune_three_mf_cache_for_folder(folder_name, valid_rel_paths=set())
                self._prune_three_mf_plate_cache_for_folder(folder_name, valid_rel_paths=set())
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
            self.rebuild_search_index()
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
            self.rebuild_search_index()
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
