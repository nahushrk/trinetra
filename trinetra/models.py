"""
Database models for Trinetra 3D model manager.
"""

import json
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class Folder(Base):
    """Represents a project folder containing STL files and related content."""

    __tablename__ = "folders"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stl_files = relationship("STLFile", back_populates="folder", cascade="all, delete-orphan")
    image_files = relationship("ImageFile", back_populates="folder", cascade="all, delete-orphan")
    pdf_files = relationship("PDFFile", back_populates="folder", cascade="all, delete-orphan")
    gcode_files = relationship("GCodeFile", back_populates="folder", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Folder(name='{self.name}')>"


class STLFile(Base):
    """Represents an STL file within a folder."""

    __tablename__ = "stl_files"

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    rel_path = Column(String(500), nullable=False)  # Relative path from base
    abs_path = Column(String(500), nullable=False)  # Absolute path
    file_size = Column(Integer)  # File size in bytes
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    folder = relationship("Folder", back_populates="stl_files")
    gcode_files = relationship("GCodeFile", back_populates="stl_file")

    # Indexes for performance
    __table_args__ = (
        Index("idx_stl_folder_name", "folder_id", "file_name"),
        Index("idx_stl_rel_path", "rel_path"),
    )

    def __repr__(self):
        return f"<STLFile(file_name='{self.file_name}', folder_id={self.folder_id})>"


class ImageFile(Base):
    """Represents an image file within a folder."""

    __tablename__ = "image_files"

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    rel_path = Column(String(500), nullable=False)
    abs_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    extension = Column(String(10), nullable=False)  # .png, .jpg, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    folder = relationship("Folder", back_populates="image_files")

    # Indexes
    __table_args__ = (
        Index("idx_image_folder_name", "folder_id", "file_name"),
        Index("idx_image_rel_path", "rel_path"),
    )

    def __repr__(self):
        return f"<ImageFile(file_name='{self.file_name}', folder_id={self.folder_id})>"


class PDFFile(Base):
    """Represents a PDF file within a folder."""

    __tablename__ = "pdf_files"

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    rel_path = Column(String(500), nullable=False)
    abs_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    folder = relationship("Folder", back_populates="pdf_files")

    # Indexes
    __table_args__ = (
        Index("idx_pdf_folder_name", "folder_id", "file_name"),
        Index("idx_pdf_rel_path", "rel_path"),
    )

    def __repr__(self):
        return f"<PDFFile(file_name='{self.file_name}', folder_id={self.folder_id})>"


class GCodeFile(Base):
    """Represents a G-code file, which can be associated with an STL file."""

    __tablename__ = "gcode_files"

    id = Column(Integer, primary_key=True)
    folder_id = Column(
        Integer, ForeignKey("folders.id"), nullable=True
    )  # Can be null for orphaned gcode
    stl_file_id = Column(Integer, ForeignKey("stl_files.id"), nullable=True)  # Associated STL file
    file_name = Column(String(255), nullable=False)
    rel_path = Column(String(500), nullable=False)
    abs_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    base_path = Column(String(50), nullable=False)  # 'STL_BASE_PATH' or 'GCODE_BASE_PATH'
    metadata_json = Column(Text)  # JSON string of extracted metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    folder = relationship("Folder", back_populates="gcode_files")
    stl_file = relationship("STLFile", back_populates="gcode_files")

    # Indexes
    __table_args__ = (
        Index("idx_gcode_folder_name", "folder_id", "file_name"),
        Index("idx_gcode_rel_path", "rel_path"),
        Index("idx_gcode_base_path", "base_path"),
        Index("idx_gcode_stl_file", "stl_file_id"),
    )

    def __repr__(self):
        return f"<GCodeFile(file_name='{self.file_name}', base_path='{self.base_path}')>"

    def get_metadata(self):
        """Return metadata as dictionary."""
        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except json.JSONDecodeError:
                return {}
        return {}

    def set_metadata(self, value):
        """Set metadata as JSON string."""
        if value:
            self.metadata_json = json.dumps(value)
        else:
            self.metadata_json = None


class GCodeFileStats(Base):
    """Statistics for G-code files from Moonraker."""

    __tablename__ = "gcode_file_stats"

    id = Column(Integer, primary_key=True)
    gcode_file_id = Column(Integer, ForeignKey("gcode_files.id"), nullable=False, unique=True)
    print_count = Column(Integer, default=0)
    successful_prints = Column(Integer, default=0)  # Number of successful prints
    canceled_prints = Column(Integer, default=0)  # Number of canceled prints
    total_print_time = Column(Integer, default=0)  # in seconds
    total_filament_used = Column(Integer, default=0)  # in mm
    last_print_date = Column(DateTime, nullable=True)
    success_rate = Column(Integer, default=0)  # percentage * 100 (stored as integer)
    job_id = Column(String(255), nullable=True)
    last_status = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    gcode_file = relationship("GCodeFile", backref="stats")

    # Indexes
    __table_args__ = (Index("idx_gcode_stats_file_id", "gcode_file_id"),)

    def __repr__(self):
        return f"<GCodeFileStats(file_id={self.gcode_file_id}, prints={self.print_count})>"


class PrintHistoryEvent(Base):
    """Normalized print history events synchronized from integrations."""

    __tablename__ = "print_history_events"

    id = Column(Integer, primary_key=True)
    integration_id = Column(String(64), nullable=False)
    integration_mode = Column(String(32), nullable=True)
    printer_uid = Column(String(255), nullable=False, default="")
    event_uid = Column(String(255), nullable=False)
    job_uid = Column(String(255), nullable=True)

    file_name = Column(String(500), nullable=True)
    file_path = Column(String(1000), nullable=True)
    normalized_basename = Column(String(255), nullable=True)

    status = Column(String(64), nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    event_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    filament_used_mm = Column(Float, nullable=True)

    gcode_file_id = Column(Integer, ForeignKey("gcode_files.id"), nullable=True)
    match_state = Column(String(32), nullable=False, default="unmatched")
    raw_payload_json = Column(Text, nullable=True)

    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gcode_file = relationship("GCodeFile")

    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "printer_uid",
            "event_uid",
            name="uq_history_event_provider_printer_event",
        ),
        Index("idx_history_event_event_at", "event_at"),
        Index("idx_history_event_file_id", "gcode_file_id"),
        Index("idx_history_event_basename", "normalized_basename"),
    )

    def __repr__(self):
        return f"<PrintHistoryEvent(provider='{self.integration_id}', event_uid='{self.event_uid}')>"


class IntegrationSyncState(Base):
    """Persisted synchronization state per integration scope."""

    __tablename__ = "integration_sync_state"

    id = Column(Integer, primary_key=True)
    integration_id = Column(String(64), nullable=False)
    integration_mode = Column(String(32), nullable=True)
    printer_uid = Column(String(255), nullable=False, default="")
    cursor = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_event_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "integration_mode",
            "printer_uid",
            name="uq_sync_state_provider_mode_printer",
        ),
        Index("idx_sync_state_provider", "integration_id"),
    )

    def __repr__(self):
        return f"<IntegrationSyncState(provider='{self.integration_id}', printer='{self.printer_uid}')>"


def create_database_engine(db_path="trinetra.db"):
    """Create SQLAlchemy engine for the database."""
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )


def init_database(engine):
    """Initialize the database with all tables."""
    Base.metadata.create_all(engine)


def create_session_factory(engine):
    """Create a session factory for database operations."""
    return sessionmaker(bind=engine)
