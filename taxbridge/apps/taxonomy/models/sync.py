# apps/taxonomy/models/sync.py
"""
Sync run models: NCBISyncRun, TaxonSyncRun.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


# ============================================================
# NCBISyncRun - NCBI synchronization log
# ============================================================
class NCBISyncRun(models.Model):
    """
    Records each NCBI synchronization run.
    Allows viewing the history, progress, and status of synchronizations.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    TRIGGER_CHOICES = [
        ("scheduled", "Scheduled"),
        ("manual", "Manual"),
        ("webhook", "Webhook"),
    ]

    # Status
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    trigger = models.CharField(
        max_length=16,
        choices=TRIGGER_CHOICES,
        default="manual",
    )

    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Celery task ID",
    )

    # Configuration used
    config = models.JSONField(
        default=dict,
        help_text="Configuration used for this synchronization",
    )

    # Progress
    total_taxa = models.PositiveIntegerField(default=0)
    processed_taxa = models.PositiveIntegerField(default=0)
    successful_taxa = models.PositiveIntegerField(default=0)
    failed_taxa = models.PositiveIntegerField(default=0)
    skipped_taxa = models.PositiveIntegerField(default=0)

    # Genomes
    genomes_created = models.PositiveIntegerField(default=0)
    genomes_updated = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Errors and logs
    error_message = models.TextField(blank=True, default="")
    log = models.JSONField(
        default=list,
        help_text="Detailed execution log",
    )

    class Meta:
        app_label = "taxonomy"
        verbose_name = "NCBI Sync Run"
        verbose_name_plural = "NCBI Sync Runs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["celery_task_id"]),
        ]

    def __str__(self) -> str:
        return f"Sync #{self.pk} [{self.status}] - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def progress_percent(self) -> float:
        """Progress percentage."""
        if self.total_taxa == 0:
            return 0.0
        return round((self.processed_taxa / self.total_taxa) * 100, 1)

    @property
    def duration_seconds(self) -> int | None:
        """Duration in seconds."""
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return int((end - self.started_at).total_seconds())

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def add_log(self, level: str, message: str, **kwargs):
        """Adds an entry to the log."""
        entry = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        self.log.append(entry)
        self.save(update_fields=["log"])

    def mark_started(self):
        """Marks as started."""
        self.status = "running"
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self):
        """Marks as completed."""
        self.status = "completed"
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])

    def mark_failed(self, error: str):
        """Marks as failed."""
        self.status = "failed"
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "finished_at", "error_message"])


# ============================================================
# TaxonSyncRun (NCBI ↔ COL Synchronization)
# ============================================================
class TaxonSyncRun(models.Model):
    """
    Records taxon synchronizations: NCBI download and COL matching.
    Similar to NCBISyncRun but for the complete taxon process.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("fetching_ncbi", "Fetching NCBI"),
        ("matching_col", "Matching COL"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    KINGDOM_CHOICES = [
        ("metazoa", "Metazoa"),
        ("fungi", "Fungi"),
        ("viridiplantae", "Viridiplantae"),
        ("bacteria", "Bacteria"),
        ("archaea", "Archaea"),
    ]

    # Status
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    
    # Kingdom/group to synchronize
    kingdom = models.CharField(
        max_length=32,
        choices=KINGDOM_CHOICES,
        default="metazoa",
        db_index=True,
    )

    # Configuration
    config = models.JSONField(
        default=dict,
        help_text="Synchronization configuration (limit, filters, etc.)",
    )

    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Celery task ID",
    )

    # NCBI Progress
    ncbi_total = models.PositiveIntegerField(default=0)
    ncbi_fetched = models.PositiveIntegerField(default=0)
    ncbi_filtered = models.PositiveIntegerField(default=0)
    taxa_created = models.PositiveIntegerField(default=0)
    genomes_created = models.PositiveIntegerField(default=0)

    # COL Progress
    col_total = models.PositiveIntegerField(default=0)
    col_matched = models.PositiveIntegerField(default=0)
    col_unmatched = models.PositiveIntegerField(default=0)
    external_taxa_created = models.PositiveIntegerField(default=0)
    crosswalks_created = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Errors and logs
    error_message = models.TextField(blank=True, default="")
    log = models.JSONField(
        default=list,
        help_text="Detailed execution log",
    )

    class Meta:
        app_label = "taxonomy"
        verbose_name = "Taxon Sync Run"
        verbose_name_plural = "Taxon Sync Runs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["kingdom"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"TaxonSync #{self.pk} [{self.kingdom}] [{self.status}]"

    @property
    def progress_percent(self) -> float:
        """Total progress percentage."""
        if self.status == "fetching_ncbi":
            if self.ncbi_total == 0:
                return 0.0
            return round((self.ncbi_fetched / max(self.ncbi_total, 1)) * 50, 1)
        elif self.status == "matching_col":
            if self.col_total == 0:
                return 50.0
            return round(50 + (self.col_matched + self.col_unmatched) / max(self.col_total, 1) * 50, 1)
        elif self.status == "completed":
            return 100.0
        return 0.0

    @property
    def duration_seconds(self) -> int | None:
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return int((end - self.started_at).total_seconds())

    @property
    def is_running(self) -> bool:
        return self.status in ("fetching_ncbi", "matching_col")

    def add_log(self, level: str, message: str, **kwargs):
        """Adds an entry to the log."""
        entry = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        self.log.append(entry)
        self.save(update_fields=["log"])

    def mark_started(self):
        self.status = "fetching_ncbi"
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_col_phase(self):
        self.status = "matching_col"
        self.save(update_fields=["status"])

    def mark_completed(self):
        self.status = "completed"
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])

    def mark_failed(self, error: str):
        self.status = "failed"
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "finished_at", "error_message"])
