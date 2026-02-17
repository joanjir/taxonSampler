# apps/taxonomy/models/sampling.py
"""
Sampling-related models: SamplingRun, ResolutionRun, ResolutionItem.
"""
from __future__ import annotations

from django.db import models


# ============================================================
# ResolutionRun (Batch)
# ============================================================
class ResolutionRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("finished", "Finished"),
        ("failed", "Failed"),
        ("partial", "Partial"),
        ("cancelled", "Cancelled"),
    ]

    INPUT_TYPE_CHOICES = [
        ("taxid", "NCBI taxid"),
        ("name", "Scientific name"),
    ]

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued", db_index=True)
    input_type = models.CharField(max_length=16, choices=INPUT_TYPE_CHOICES)

    schema_version = models.PositiveSmallIntegerField(default=1)
    parameters = models.JSONField(default=dict)
    input_payload = models.JSONField(default=list)
    stats = models.JSONField(default=dict)

    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "taxonomy"

    def __str__(self) -> str:
        return f"Run {self.id} [{self.status}]"


# ============================================================
# ResolutionItem (per query within a run)
# ============================================================
class ResolutionItem(models.Model):
    PROCESS_STATUS_CHOICES = [
        ("queued", "Queued"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("error", "Error"),
    ]

    DECISION_CHOICES = [
        ("high", "High confidence"),
        ("needs_review", "Needs review"),
        ("no_match", "No match"),
    ]

    run = models.ForeignKey(ResolutionRun, on_delete=models.CASCADE, related_name="items")

    query = models.CharField(max_length=255, db_index=True)

    # Minimum NCBI result
    taxon = models.ForeignKey(
        "taxonomy.Taxon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # CoL result via crosswalk (if applicable)
    crosswalk = models.ForeignKey(
        "taxonomy.TaxonCrosswalk",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolution_items",
    )

    process_status = models.CharField(max_length=16, choices=PROCESS_STATUS_CHOICES, default="queued", db_index=True)
    decision = models.CharField(max_length=32, choices=DECISION_CHOICES, null=True, blank=True, db_index=True)

    score = models.FloatField(default=0.0)
    evidence = models.JSONField(default=dict)
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "taxonomy"
        indexes = [
            models.Index(fields=["process_status"]),
            models.Index(fields=["decision"]),
            models.Index(fields=["score"]),
        ]

    def __str__(self) -> str:
        return f"Item {self.id} [{self.process_status}/{self.decision}]"


# ============================================================
# SamplingRun
# ============================================================
class SamplingRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    scope_root_key = models.TextField(blank=True, default="")
    params = models.JSONField(default=dict)            # sampling parameters (K, allocation, etc.)
    sampling_payload = models.JSONField(default=dict)  # Complete JSON of the result

    tree_newick = models.TextField(blank=True, default="")
    tree_json = models.JSONField(default=dict)

    class Meta:
        app_label = "taxonomy"

    def __str__(self):
        return f"SamplingRun#{self.pk}"


# ============================================================
# SamplingConfiguration — DB-based sampling config (Step 2)
# ============================================================
class SamplingConfiguration(models.Model):
    """
    Stores a sampling configuration and its results.
    Works on the local NCBIGenome database, grouping species
    by their COL classification hierarchy.
    """

    STRATEGY_CHOICES = [
        ("none", "None (natural order)"),
        ("random", "Random"),
        ("proportional", "Proportional"),
        ("balanced", "Balanced"),
    ]

    RANK_CHOICES = [
        ("kingdom", "Kingdom"),
        ("phylum", "Phylum"),
        ("class", "Class"),
        ("order", "Order"),
        ("family", "Family"),
        ("genus", "Genus"),
        ("species", "Species"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("executed", "Executed"),
        ("failed", "Failed"),
    ]

    name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Optional name for this configuration",
    )

    # Sampling parameters
    max_sample_size = models.PositiveIntegerField(
        help_text="Maximum number of species to select",
    )
    start_rank = models.CharField(
        max_length=32,
        choices=RANK_CHOICES,
        default="phylum",
        help_text="Start rank for taxonomic grouping (how species are grouped)",
    )
    end_rank = models.CharField(
        max_length=32,
        choices=RANK_CHOICES,
        default="species",
        help_text="End rank — distribution resolves down to this level before selecting species",
    )
    strategy = models.CharField(
        max_length=32,
        choices=STRATEGY_CHOICES,
        default="proportional",
        help_text="Sampling strategy",
    )

    # Optional scope filter
    scope_kingdom = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Restrict to a specific kingdom (e.g. Animalia)",
    )
    scope_phylum = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Restrict to a specific phylum (e.g. Chordata)",
    )

    # Execution state
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="draft",
        db_index=True,
    )
    result = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sampling result payload",
    )
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "taxonomy"
        ordering = ["-created_at"]

    def __str__(self):
        return f"SamplingConfig#{self.pk} ({self.strategy}, K={self.max_sample_size})"
