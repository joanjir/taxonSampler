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
    ncbi_skipped = models.PositiveIntegerField(
        default=0,
        help_text="Genomes skipped because they already exist in the database",
    )
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


# ============================================================
# DiscoveryRun - Weekly automatic species discovery
# ============================================================
class DiscoveryRun(models.Model):
    """
    Records each weekly discovery run that searches NCBI
    for new species with high-quality genomes not yet in our DB.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    TRIGGER_CHOICES = [
        ("scheduled", "Scheduled"),
        ("manual", "Manual"),
    ]

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    trigger = models.CharField(
        max_length=16, choices=TRIGGER_CHOICES, default="scheduled"
    )

    # Kingdoms searched
    kingdoms_searched = models.JSONField(
        default=list,
        help_text="List of kingdoms searched in this run",
    )

    # Results
    total_scanned = models.PositiveIntegerField(default=0)
    new_species_found = models.PositiveIntegerField(default=0)

    # Celery tracking
    celery_task_id = models.CharField(max_length=255, blank=True, default="", db_index=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Errors and log
    error_message = models.TextField(blank=True, default="")
    log = models.JSONField(default=list)

    class Meta:
        app_label = "taxonomy"
        verbose_name = "Discovery Run"
        verbose_name_plural = "Discovery Runs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Discovery #{self.pk} [{self.status}] - {self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else 'pending'}"

    @property
    def duration_seconds(self):
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return int((end - self.started_at).total_seconds())

    def add_log(self, level, message, **kwargs):
        entry = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        self.log.append(entry)
        self.save(update_fields=["log"])

    def mark_started(self):
        self.status = "running"
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self):
        self.status = "completed"
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])

    def mark_failed(self, error):
        self.status = "failed"
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "finished_at", "error_message"])


class DiscoveredSpecies(models.Model):
    """
    A new species found in NCBI that is not yet in the local database.
    Allows the admin to review and optionally import discoveries.
    """

    discovery_run = models.ForeignKey(
        DiscoveryRun,
        on_delete=models.CASCADE,
        related_name="discoveries",
    )

    # Species info from NCBI
    taxid = models.PositiveIntegerField(help_text="NCBI Taxonomy ID")
    scientific_name = models.CharField(max_length=255)
    common_name = models.CharField(max_length=255, blank=True, default="")
    kingdom = models.CharField(max_length=64, blank=True, default="")

    # Best genome info
    accession = models.CharField(max_length=64, help_text="Best genome accession")
    quality_score = models.FloatField(default=0.0)
    genome_level = models.CharField(max_length=64, blank=True, default="")
    refseq_category = models.CharField(max_length=64, blank=True, default="")
    protein_coding = models.PositiveIntegerField(null=True, blank=True)
    scaffold_n50_kb = models.FloatField(null=True, blank=True)
    genome_coverage = models.FloatField(null=True, blank=True)
    total_sequence_length = models.BigIntegerField(null=True, blank=True)

    # Admin action
    is_imported = models.BooleanField(
        default=False, db_index=True,
        help_text="Whether this species has been imported into the database",
    )
    is_dismissed = models.BooleanField(
        default=False, db_index=True,
        help_text="Marked as not interesting by admin",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        verbose_name = "Discovered Species"
        verbose_name_plural = "Discovered Species"
        ordering = ["-quality_score"]
        unique_together = [("discovery_run", "taxid")]
        indexes = [
            models.Index(fields=["taxid"]),
            models.Index(fields=["quality_score"]),
            models.Index(fields=["is_imported"]),
        ]

    def __str__(self):
        return f"{self.scientific_name} (taxid {self.taxid}) - Q:{self.quality_score}"
