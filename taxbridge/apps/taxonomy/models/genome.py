# apps/taxonomy/models/genome.py
"""
NCBI Genome model.
"""
from __future__ import annotations

from django.db import models


class NCBIGenome(models.Model):
    """
    Stores NCBI genome information associated with a Taxon.
    Data obtained from the NCBI Datasets API.
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

    # Relationship with NCBI Taxon
    taxon = models.ForeignKey(
        "taxonomy.Taxon",
        on_delete=models.CASCADE,
        related_name="genomes",
        help_text="Associated NCBI taxon",
    )

    # Identifiers
    accession = models.CharField(
        max_length=64,
        db_index=True,
        unique=True,
        help_text="Assembly accession (e.g. GCF_000001405.40)",
    )

    # Basic information
    organism_name = models.TextField(blank=True, default="")
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

    # Quality metrics
    genome_coverage = models.FloatField(
        null=True,
        blank=True,
        help_text="Genome coverage",
    )
    contig_n50_kb = models.FloatField(
        null=True,
        blank=True,
        help_text="Contig N50 in kilobases",
    )
    scaffold_n50_kb = models.FloatField(
        null=True,
        blank=True,
        help_text="Scaffold N50 in kilobases",
    )
    scaffold_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of scaffolds",
    )

    # Computed score
    quality_score = models.FloatField(
        default=0.0,
        db_index=True,
        help_text="Computed quality score",
    )

    # Gene annotation
    genes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total number of genes",
    )
    protein_coding = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of protein-coding genes",
    )
    non_coding_genes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of non-coding genes",
    )
    pseudogenes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of pseudogenes",
    )

    # Extended genome metrics
    total_sequence_length = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Total genome size in bp",
    )
    gc_percent = models.FloatField(
        null=True,
        blank=True,
        help_text="Genome GC percentage",
    )
    chromosome_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total number of chromosomes",
    )
    contig_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of contigs",
    )

    # Sequencing and assembly info
    sequencing_tech = models.TextField(
        blank=True,
        default="",
        help_text="Sequencing technology",
    )
    assembly_method = models.TextField(
        blank=True,
        default="",
        help_text="Assembly method",
    )
    release_date = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        help_text="Assembly release date",
    )
    source_database = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="refseq or genbank",
    )

    # Annotation info
    annotation_provider = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="Annotation provider (NCBI RefSeq, WormBase, etc.)",
    )
    annotation_status = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Annotation status (Full annotation, etc.)",
    )

    # BUSCO completeness scores
    busco_complete = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % complete genes",
    )
    busco_single_copy = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % single copy",
    )
    busco_duplicated = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % duplicated",
    )
    busco_fragmented = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % fragmented",
    )
    busco_missing = models.FloatField(
        null=True,
        blank=True,
        help_text="BUSCO: % missing",
    )
    busco_lineage = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="BUSCO lineage used (e.g. actinopterygii_odb10)",
    )

    # Strain/isolate info
    strain = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Organism strain",
    )
    ecotype = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Organism ecotype",
    )

    # Additional names
    common_name = models.TextField(
        blank=True,
        default="",
        help_text="Organism common name",
    )
    directory_name = models.TextField(
        blank=True,
        default="",
        help_text="NCBI directory name",
    )

    # Taxonomic classification (cached from xlsx or taxon)
    phylum = models.CharField(max_length=128, db_index=True, blank=True, default="")
    class_name = models.CharField(max_length=128, db_index=True, blank=True, default="")

    # Proteome
    has_proteome = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indicates whether it has a valid proteome (.faa)",
    )
    proteome_quality = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Proteome quality: good / poor / unknown",
    )

    # Selection for research
    is_selected = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Marked as selected for research",
    )
    is_best_for_taxon = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Best assembly for this taxon",
    )

    # CoL linking
    external_taxon = models.ForeignKey(
        "taxonomy.ExternalTaxon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ncbi_genomes",
        help_text="Linked CoL taxon (via matching)",
    )
    
    COL_MATCH_STATUS_CHOICES = [
        ("unmatched", "Unmatched"),
        ("matched", "Matched"),
        ("not_in_col", "Not in COL"),
        ("manual", "Manual"),
        ("mismatch", "Mismatch – genus audit failed"),
    ]
    col_match_status = models.CharField(
        max_length=32,
        choices=COL_MATCH_STATUS_CHOICES,
        default="unmatched",
        db_index=True,
        help_text="CoL linking status",
    )
    col_match_notes = models.TextField(
        blank=True,
        default="",
        help_text="Notes about CoL matching",
    )

    # Metadata
    raw = models.JSONField(
        default=dict,
        help_text="Original NCBI API payload",
    )
    fetched_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Data fetch date",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "taxonomy"
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
        """Quality tier classification."""
        if self.quality_score >= 0.8:
            return "high"
        elif self.quality_score >= 0.5:
            return "medium"
        return "low"

    @classmethod
    def fetch_and_save(cls, taxon, check_proteomes: bool = True) -> int:
        """
        Fetch genomes from NCBI and save them to the database.

        Args:
            taxon: Taxon instance (NCBI)
            check_proteomes: Check proteome validity

        Returns:
            Number of genomes saved
        """
        import logging
        from apps.taxonomy.ncbi.clients import get_taxon_genomes

        logger = logging.getLogger(__name__)
        info = get_taxon_genomes(taxon.taxid, check_proteomes=check_proteomes)

        if not info.has_genome or not info.genomes:
            logger.info(f"Taxid {taxon.taxid} has no available genomes")
            return 0

        saved = 0
        for i, genome in enumerate(info.genomes):
            is_best = (i == 0)  # First is highest score
            has_prot = info.proteome_status.get(genome.accession, False)
            prot_quality = "good" if has_prot else "unknown"

            try:
                obj, created = cls.objects.update_or_create(
                    accession=genome.accession,
                    defaults={
                        "taxon": taxon,
                        "organism_name": genome.organism_name,
                        "refseq_category": genome.refseq_category,
                        "genome_level": genome.genome_level,
                        "genome_coverage": genome.genome_coverage,
                        "contig_n50_kb": genome.contig_n50_kb,
                        "scaffold_n50_kb": genome.scaffold_n50_kb,
                        "scaffold_count": genome.scaffold_count,
                        "quality_score": genome.quality_score,
                        "has_proteome": has_prot,
                        "proteome_quality": prot_quality,
                        "is_best_for_taxon": is_best,
                        "raw": genome.raw,
                    },
                )
                saved += 1
                action = "created" if created else "updated"
                logger.debug(f"NCBIGenome {genome.accession} {action}")
            except Exception as e:
                logger.error(f"Error saving genome {genome.accession}: {e}")

        # Unmark other genomes from the same taxon as "best"
        if saved > 0:
            best_acc = info.genomes[0].accession
            cls.objects.filter(taxon=taxon).exclude(accession=best_acc).update(
                is_best_for_taxon=False
            )

        return saved
