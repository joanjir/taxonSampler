# taxonomy/models.py
from __future__ import annotations

from django.db import models
from django.db.models import Q


# ============================================================
# Taxon (NCBI mínimo, solo ID + nombre + rank)
# ============================================================
class Taxon(models.Model):
    """
    Taxón canónico NCBI (mínimo por ahora):
    - taxid: identificador
    - scientific_name: nombre científico
    - rank: rank (species, genus, etc.)

    Nota: la taxonomía completa se toma de CoL (ExternalTaxon.classification).
    """

    taxid = models.PositiveIntegerField(primary_key=True, help_text="NCBI Taxonomy ID")

    scientific_name = models.CharField(max_length=255, db_index=True)
    rank = models.CharField(max_length=64, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["scientific_name"]),
            models.Index(fields=["rank"]),
        ]

    def __str__(self) -> str:
        return f"{self.scientific_name} ({self.taxid})"


# ============================================================
# ExternalTaxon (CoL / ChecklistBank) = taxonomía completa
# ============================================================
class ExternalTaxon(models.Model):
    """
    Taxón externo desde CoL/ChecklistBank.
    Aquí sí guardas la taxonomía completa:
    - classification: dict rank->name
    - parent_external_id + parent FK para reconstruir árbol
    """

    system = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Fuente externa (ej. 'col')",
        default="col",
    )

    dataset_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Dataset real (ej. COL25.12, 3LR, ...)",
    )

    external_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="ID externo en la fuente",
    )

    name = models.CharField(max_length=255, db_index=True)
    rank = models.CharField(max_length=64, db_index=True)

    status = models.CharField(
        max_length=64,
        db_index=True,
        help_text="accepted / synonym / misapplied / unknown",
    )

    # Si es sinónimo, esto puede venir
    accepted_external_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="external_id aceptado (si este registro es sinónimo)",
    )

    accepted = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="synonyms",
        help_text="FK interna al taxón aceptado (si aplica y está importado)",
    )

    # parent para árbol
    parent_external_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="external_id del parent (para reconstruir árbol)",
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Parent taxon (FK interno) si ya fue importado",
    )

    classification = models.JSONField(
        default=dict,
        help_text="Clasificación jerárquica completa (rank -> name) desde CoL",
    )
    # models.py (ExternalTaxon)
    classification_path = models.JSONField(
        default=list,
        help_text="Clasificación ORDENADA root->leaf tal como viene de CoL (lista de {rank,name})."
    )
    raw = models.JSONField(default=dict, help_text="Payload original (auditoría)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
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
    Emparejamiento NCBI ↔ CoL.
    Regla: 1 mapping activo y high por cada taxid (si existe).
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

    def __str__(self) -> str:
        return f"Run {self.id} [{self.status}]"


# ============================================================
# ResolutionItem (por query dentro de un run)
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

    # Resultado NCBI mínimo
    taxon = models.ForeignKey(Taxon, null=True, blank=True, on_delete=models.SET_NULL)

    # Resultado CoL vía crosswalk (si aplica)
    crosswalk = models.ForeignKey(
        TaxonCrosswalk,
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
        indexes = [
            models.Index(fields=["process_status"]),
            models.Index(fields=["decision"]),
            models.Index(fields=["score"]),
        ]

    def __str__(self) -> str:
        return f"Item {self.id} [{self.process_status}/{self.decision}]"


# ============================================================
# TaxonNameIndex (si lo quieres mantener, déjalo regenerable)
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
        indexes = [
            models.Index(fields=["source", "rank"]),
            models.Index(fields=["source", "name_canonical"]),
            models.Index(fields=["source", "parent_source_id"]),
            models.Index(fields=["source", "normalization_version"]),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.name_raw}"


# ============================================================
# RunEvent (logging estructurado por corrida)
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

    run = models.ForeignKey(ResolutionRun, on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES, db_index=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    message = models.TextField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["level"]),
            models.Index(fields=["event"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"RunEvent {self.id} [{self.level}/{self.event}]"


class SamplingRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    scope_root_key = models.TextField(blank=True, default="")
    params = models.JSONField(default=dict)            # parámetros de sampling (K, allocation, etc.)
    sampling_payload = models.JSONField(default=dict)  # JSON completo del resultado

    tree_newick = models.TextField(blank=True, default="")
    tree_json = models.JSONField(default=dict)

    def __str__(self):
        return f"SamplingRun#{self.pk}"


# ============================================================
# NCBIGenome - Información de genomas NCBI (de traerNCBI)
# ============================================================
class NCBIGenome(models.Model):
    """
    Almacena información de genomas de NCBI asociados a un Taxon.
    Datos obtenidos desde la API de NCBI Datasets.
    """

    REFSEQ_CATEGORY_CHOICES = [
        ("reference genome", "Reference Genome"),
        ("representative genome", "Representative Genome"),
        ("na", "N/A"),
    ]

    GENOME_LEVEL_CHOICES = [
        ("Complete Genome", "Complete Genome"),
        ("Chromosome", "Chromosome"),
        ("Scaffold", "Scaffold"),
        ("Contig", "Contig"),
    ]

    # Relación con Taxon NCBI
    taxon = models.ForeignKey(
        Taxon,
        on_delete=models.CASCADE,
        related_name="genomes",
        help_text="Taxón NCBI asociado",
    )

    # Identificadores
    accession = models.CharField(
        max_length=64,
        db_index=True,
        unique=True,
        help_text="Accession del ensamblaje (ej: GCF_000001405.40)",
    )

    # Información básica
    organism_name = models.CharField(max_length=255, blank=True, default="")
    refseq_category = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="reference genome / representative genome / na",
    )
    genome_level = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Complete Genome / Chromosome / Scaffold / Contig",
    )

    # Métricas de calidad
    genome_coverage = models.FloatField(
        null=True,
        blank=True,
        help_text="Cobertura del genoma",
    )
    contig_n50_kb = models.FloatField(
        null=True,
        blank=True,
        help_text="Contig N50 en kilobases",
    )
    scaffold_n50_kb = models.FloatField(
        null=True,
        blank=True,
        help_text="Scaffold N50 en kilobases",
    )
    scaffold_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de scaffolds",
    )

    # Score calculado
    quality_score = models.FloatField(
        default=0.0,
        db_index=True,
        help_text="Score de calidad calculado",
    )

    # Proteoma
    has_proteome = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indica si tiene proteoma válido (.faa)",
    )
    proteome_quality = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Calidad del proteoma: good / poor / unknown",
    )

    # Selección para investigación
    is_selected = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Marcado como seleccionado para investigación",
    )
    is_best_for_taxon = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Es el mejor ensamblaje para este taxón",
    )

    # Metadatos
    raw = models.JSONField(
        default=dict,
        help_text="Payload original de la API NCBI",
    )
    fetched_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Fecha de obtención de datos",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "NCBI Genome"
        verbose_name_plural = "NCBI Genomes"
        ordering = ["-quality_score", "-is_best_for_taxon"]
        indexes = [
            models.Index(fields=["taxon", "is_best_for_taxon"]),
            models.Index(fields=["refseq_category"]),
            models.Index(fields=["genome_level"]),
            models.Index(fields=["quality_score"]),
            models.Index(fields=["has_proteome"]),
        ]

    def __str__(self) -> str:
        return f"{self.accession} ({self.organism_name})"

    @property
    def quality_tier(self) -> str:
        """Clasificación por tier de calidad."""
        if self.quality_score >= 0.8:
            return "high"
        elif self.quality_score >= 0.5:
            return "medium"
        return "low"