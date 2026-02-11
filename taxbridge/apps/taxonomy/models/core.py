# apps/taxonomy/models/core.py
"""
Core taxonomy models: Taxon, ExternalTaxon, TaxonCrosswalk, TaxonNameIndex, RunEvent.
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.taxonomy.managers import ExternalTaxonManager


# ============================================================
# Taxon (minimal NCBI record: ID + name + rank)
# ============================================================
class Taxon(models.Model):
    """
    Canonical NCBI taxon (minimal for now):
    - taxid: identifier
    - scientific_name: scientific name
    - rank: rank (species, genus, etc.)

    Note: full taxonomy is taken from CoL (ExternalTaxon.classification).
    """

    taxid = models.PositiveIntegerField(primary_key=True, help_text="NCBI Taxonomy ID")

    scientific_name = models.CharField(max_length=255, db_index=True)
    rank = models.CharField(max_length=64, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "taxonomy"
        indexes = [
            models.Index(fields=["scientific_name"]),
            models.Index(fields=["rank"]),
        ]

    def __str__(self) -> str:
        return f"{self.scientific_name} ({self.taxid})"


# ============================================================
# ExternalTaxon (CoL / ChecklistBank) = full taxonomy
# ============================================================
class ExternalTaxon(models.Model):
    """
    External taxon from CoL/ChecklistBank.
    Stores the full taxonomy here:
    - classification: dict rank->name
    - parent_external_id + parent FK to reconstruct tree
    """
    
    # Custom manager with tree methods
    objects = ExternalTaxonManager()

    system = models.CharField(
        max_length=32,
        db_index=True,
        help_text="External source (e.g. 'col')",
        default="col",
    )

    dataset_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Actual dataset (e.g. COL25.12, 3LR, ...)",
    )

    external_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="External ID in the source",
    )

    name = models.CharField(max_length=255, db_index=True)
    rank = models.CharField(max_length=64, db_index=True)

    status = models.CharField(
        max_length=64,
        db_index=True,
        help_text="accepted / synonym / misapplied / unknown",
    )

    # If it is a synonym, this may be populated
    accepted_external_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="Accepted external_id (if this record is a synonym)",
    )

    accepted = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="synonyms",
        help_text="Internal FK to the accepted taxon (if applicable and already imported)",
    )

    # parent for tree
    parent_external_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="Parent external_id (to reconstruct tree)",
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Parent taxon (internal FK) if already imported",
    )

    classification = models.JSONField(
        default=dict,
        help_text="Full hierarchical classification (rank -> name) from CoL",
    )
    classification_path = models.JSONField(
        default=list,
        help_text="ORDERED classification root->leaf as provided by CoL (list of {rank,name})."
    )
    raw = models.JSONField(default=dict, help_text="Original payload (audit)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        constraints = [
            models.UniqueConstraint(
                fields=["system", "dataset_code", "external_id"],
                name="uq_external_taxon_source",
            ),
        ]
        indexes = [
            models.Index(fields=["system", "dataset_code"]),
            models.Index(fields=["name"]),
            models.Index(fields=["rank"]),
            models.Index(fields=["status"]),
            models.Index(fields=["parent_external_id"]),
            models.Index(fields=["accepted_external_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.system}:{self.dataset_code}:{self.external_id}]"


# ============================================================
# TaxonCrosswalk (NCBI ↔ CoL)
# ============================================================
class TaxonCrosswalk(models.Model):
    """
    NCBI ↔ CoL matching.
    Rule: 1 active high-confidence mapping per taxid (if it exists).
    """

    DECISION_CHOICES = [
        ("high", "High confidence"),
        ("needs_review", "Needs review"),
        ("no_match", "No match"),
    ]

    METHOD_CHOICES = [
        ("exact", "Exact name match"),
        ("exact_rank", "Exact name + rank"),
        ("trigram", "Trigram similarity"),
        ("lineage", "Lineage constrained"),
        ("manual", "Manual curation"),
    ]

    CURATION_LEVEL_CHOICES = [
        ("auto", "Auto"),
        ("manual", "Manual"),
        ("reviewed", "Reviewed"),
    ]

    ncbi_taxon = models.ForeignKey(
        Taxon,
        on_delete=models.CASCADE,
        related_name="crosswalks",
    )

    external_taxon = models.ForeignKey(
        ExternalTaxon,
        on_delete=models.CASCADE,
        related_name="crosswalks",
    )

    score = models.FloatField(default=0.0)

    decision = models.CharField(
        max_length=32,
        choices=DECISION_CHOICES,
        db_index=True,
    )

    method = models.CharField(
        max_length=32,
        choices=METHOD_CHOICES,
        db_index=True,
    )

    is_active = models.BooleanField(default=True, db_index=True)

    curation_level = models.CharField(
        max_length=16,
        choices=CURATION_LEVEL_CHOICES,
        default="auto",
        db_index=True,
    )

    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        constraints = [
            models.UniqueConstraint(
                fields=["ncbi_taxon", "external_taxon"],
                name="uq_ncbi_col_pair",
            ),
            models.UniqueConstraint(
                fields=["ncbi_taxon"],
                condition=Q(is_active=True, decision="high"),
                name="uq_active_high_crosswalk_per_ncbi_taxon",
            ),
        ]
        indexes = [
            models.Index(fields=["decision"]),
            models.Index(fields=["score"]),
            models.Index(fields=["method"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.ncbi_taxon_id} ↔ {self.external_taxon_id}"


# ============================================================
# TaxonNameIndex (regenerable)
# ============================================================
class TaxonNameIndex(models.Model):
    SOURCE_CHOICES = [
        ("ncbi", "NCBI"),
        ("col", "Catalogue of Life"),
    ]

    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, db_index=True)
    source_id = models.CharField(max_length=128, db_index=True)

    name_raw = models.CharField(max_length=255)
    name_canonical = models.CharField(max_length=255, db_index=True)

    rank = models.CharField(max_length=64, db_index=True)

    parent_source_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    is_accepted = models.BooleanField(default=True)

    lineage = models.JSONField(default=dict)

    normalization_version = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        indexes = [
            models.Index(fields=["source", "rank"]),
            models.Index(fields=["source", "name_canonical"]),
            models.Index(fields=["source", "parent_source_id"]),
            models.Index(fields=["source", "normalization_version"]),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.name_raw}"


# ============================================================
# RunEvent (structured logging per run)
# ============================================================
class RunEvent(models.Model):
    LEVEL_CHOICES = [("info", "INFO"), ("warn", "WARN"), ("error", "ERROR")]
    EVENT_CHOICES = [
        ("ncbi_query", "NCBI_QUERY"),
        ("col_query", "COL_QUERY"),
        ("mapping", "MAPPING"),
        ("tree_build", "TREE_BUILD"),
        ("selection", "SELECTION"),
        ("io", "IO"),
        ("other", "OTHER"),
    ]

    run = models.ForeignKey("ResolutionRun", on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES, db_index=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    message = models.TextField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        indexes = [
            models.Index(fields=["level"]),
            models.Index(fields=["event"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"RunEvent {self.id} [{self.level}/{self.event}]"
