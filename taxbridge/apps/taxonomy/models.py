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

    # Anotación de genes
    genes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número total de genes",
    )
    protein_coding = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de genes codificantes de proteínas",
    )
    non_coding_genes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de genes no codificantes",
    )
    pseudogenes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de pseudogenes",
    )

    # Extended genome metrics
    total_sequence_length = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Tamaño total del genoma en bp",
    )
    gc_percent = models.FloatField(
        null=True,
        blank=True,
        help_text="Porcentaje de GC del genoma",
    )
    chromosome_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número total de cromosomas",
    )
    contig_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de contigs",
    )

    # Sequencing and assembly info
    sequencing_tech = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Tecnología de secuenciación",
    )
    assembly_method = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Método de ensamblaje",
    )
    release_date = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        help_text="Fecha de liberación del ensamblaje",
    )
    source_database = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="refseq o genbank",
    )

    # Annotation info
    annotation_provider = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="Proveedor de anotación (NCBI RefSeq, WormBase, etc.)",
    )
    annotation_status = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Estado de anotación (Full annotation, etc.)",
    )

    # BUSCO completeness scores
    busco_complete = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % genes completos",
    )
    busco_single_copy = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % single copy",
    )
    busco_duplicated = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % duplicados",
    )
    busco_fragmented = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % fragmentados",
    )
    busco_missing = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % faltantes",
    )
    busco_lineage = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Linaje BUSCO usado (ej: actinopterygii_odb10)",
    )

    # Strain/isolate info
    strain = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Cepa/strain del organismo",
    )
    ecotype = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Ecotipo del organismo",
    )

    # Nombres adicionales
    common_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Nombre común del organismo",
    )
    directory_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Nombre de directorio en NCBI",
    )

    # Clasificación taxonómica (cacheada del xlsx o taxon)
    phylum = models.CharField(max_length=128, db_index=True, blank=True, default="")
    class_name = models.CharField(max_length=128, db_index=True, blank=True, default="")

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

    # Vinculación con CoL
    external_taxon = models.ForeignKey(
        ExternalTaxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ncbi_genomes",
        help_text="Taxón CoL vinculado (via matching)",
    )
    
    COL_MATCH_STATUS_CHOICES = [
        ("unmatched", "Sin vincular"),
        ("matched", "Vinculado"),
        ("needs_review", "Requiere revisión"),
        ("no_match", "Sin coincidencia en CoL"),
    ]
    col_match_status = models.CharField(
        max_length=32,
        choices=COL_MATCH_STATUS_CHOICES,
        default="unmatched",
        db_index=True,
        help_text="Estado de vinculación con CoL",
    )
    col_match_notes = models.TextField(
        blank=True,
        default="",
        help_text="Notas sobre el matching con CoL",
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
            models.Index(fields=["phylum"]),
            models.Index(fields=["class_name"]),
            models.Index(fields=["col_match_status"]),
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


# ============================================================
# NCBISyncRun - Registro de sincronizaciones NCBI
# ============================================================
class NCBISyncRun(models.Model):
    """
    Registra cada ejecución de sincronización con NCBI.
    Permite ver el historial, progreso y estado de las sincronizaciones.
    """

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("running", "En ejecución"),
        ("completed", "Completado"),
        ("failed", "Fallido"),
        ("cancelled", "Cancelado"),
    ]

    TRIGGER_CHOICES = [
        ("scheduled", "Programado"),
        ("manual", "Manual"),
        ("webhook", "Webhook"),
    ]

    # Estado
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
        help_text="ID de la tarea Celery",
    )

    # Configuración usada
    config = models.JSONField(
        default=dict,
        help_text="Configuración usada para esta sincronización",
    )

    # Progreso
    total_taxa = models.PositiveIntegerField(default=0)
    processed_taxa = models.PositiveIntegerField(default=0)
    successful_taxa = models.PositiveIntegerField(default=0)
    failed_taxa = models.PositiveIntegerField(default=0)
    skipped_taxa = models.PositiveIntegerField(default=0)

    # Genomas
    genomes_created = models.PositiveIntegerField(default=0)
    genomes_updated = models.PositiveIntegerField(default=0)

    # Tiempos
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Errores y logs
    error_message = models.TextField(blank=True, default="")
    log = models.JSONField(
        default=list,
        help_text="Log detallado de la ejecución",
    )

    class Meta:
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
        """Porcentaje de progreso."""
        if self.total_taxa == 0:
            return 0.0
        return round((self.processed_taxa / self.total_taxa) * 100, 1)

    @property
    def duration_seconds(self) -> int | None:
        """Duración en segundos."""
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return int((end - self.started_at).total_seconds())

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def add_log(self, level: str, message: str, **kwargs):
        """Añade entrada al log."""
        from django.utils import timezone
        entry = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        self.log.append(entry)
        self.save(update_fields=["log"])

    def mark_started(self):
        """Marca como iniciado."""
        from django.utils import timezone
        self.status = "running"
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self):
        """Marca como completado."""
        from django.utils import timezone
        self.status = "completed"
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])

    def mark_failed(self, error: str):
        """Marca como fallido."""
        from django.utils import timezone
        self.status = "failed"
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "finished_at", "error_message"])


# ============================================================
# TaxonSyncRun (Sincronización NCBI ↔ COL)
# ============================================================
class TaxonSyncRun(models.Model):
    """
    Registra sincronizaciones de taxones: descarga de NCBI y matching con COL.
    Similar a NCBISyncRun pero para el proceso completo de taxones.
    """

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("fetching_ncbi", "Descargando NCBI"),
        ("matching_col", "Sincronizando COL"),
        ("completed", "Completado"),
        ("failed", "Fallido"),
        ("cancelled", "Cancelado"),
    ]

    KINGDOM_CHOICES = [
        ("metazoa", "Metazoa"),
        ("fungi", "Fungi"),
        ("viridiplantae", "Viridiplantae"),
        ("bacteria", "Bacteria"),
        ("archaea", "Archaea"),
    ]

    # Estado
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    
    # Reino/grupo a sincronizar
    kingdom = models.CharField(
        max_length=32,
        choices=KINGDOM_CHOICES,
        default="metazoa",
        db_index=True,
    )

    # Configuración
    config = models.JSONField(
        default=dict,
        help_text="Configuración de la sincronización (límite, filtros, etc.)",
    )

    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="ID de la tarea Celery",
    )

    # Progreso NCBI
    ncbi_total = models.PositiveIntegerField(default=0)
    ncbi_fetched = models.PositiveIntegerField(default=0)
    ncbi_filtered = models.PositiveIntegerField(default=0)
    taxa_created = models.PositiveIntegerField(default=0)
    genomes_created = models.PositiveIntegerField(default=0)

    # Progreso COL
    col_total = models.PositiveIntegerField(default=0)
    col_matched = models.PositiveIntegerField(default=0)
    col_unmatched = models.PositiveIntegerField(default=0)
    external_taxa_created = models.PositiveIntegerField(default=0)
    crosswalks_created = models.PositiveIntegerField(default=0)

    # Tiempos
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Errores y logs
    error_message = models.TextField(blank=True, default="")
    log = models.JSONField(
        default=list,
        help_text="Log detallado de la ejecución",
    )

    class Meta:
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
        """Porcentaje de progreso total."""
        # Fase 1: NCBI (50%), Fase 2: COL (50%)
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
        """Añade entrada al log."""
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


# Import timezone at module level for the model
from django.utils import timezone