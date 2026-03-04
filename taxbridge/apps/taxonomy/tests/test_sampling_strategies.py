"""
Tests for taxonomic sampling strategies.

Validates all 4 sampling strategies:
- natural: Natural order (by accession)
- quality_random: Random within balanced quotas, prioritizing quality
- stratified_proportional: Quota proportional to clade size
- balanced_hierarchical: Equal quota per clade
"""

from django.test import TestCase

from apps.taxonomy.models import (
    Taxon,
    ExternalTaxon,
    TaxonCrosswalk,
    NCBIGenome,
)
from apps.taxonomy.sampling.db_engine import (
    run_db_sampling,
    compute_species_score,
    _allocate_none,
    _allocate_proportional,
    _allocate_balanced,
    CladeAllocation,
)


class SamplingStrategyTestCase(TestCase):
    """
    Test suite for sampling strategies.
    
    Creates a synthetic dataset:
    - 2 clades (phyla): Chordata (10 species), Arthropoda (20 species)
    - Total: 30 species
    - Sampling: 12 species (40%)
    """

    @classmethod
    def setUpTestData(cls):
        """Create test data once for all tests."""
        # Create taxa (NCBI side)
        cls.chordata_taxon = Taxon.objects.create(
            taxid=7711, scientific_name="Chordata", rank="phylum"
        )
        cls.arthropoda_taxon = Taxon.objects.create(
            taxid=6656, scientific_name="Arthropoda", rank="phylum"
        )

        # Create external taxa (COL side)
        cls.chordata_col = ExternalTaxon.objects.create(
            external_id="col_chordata",
            name="Chordata",
            rank="phylum",
            system="col",
            classification_path=["Animalia", "Chordata"],
        )
        cls.arthropoda_col = ExternalTaxon.objects.create(
            external_id="col_arthropoda",
            name="Arthropoda",
            rank="phylum",
            system="col",
            classification_path=["Animalia", "Arthropoda"],
        )

        # Create crosswalks
        TaxonCrosswalk.objects.create(
            taxon=cls.chordata_taxon,
            external_taxon=cls.chordata_col,
            match_method="auto",
            confidence=0.95,
        )
        TaxonCrosswalk.objects.create(
            taxon=cls.arthropoda_taxon,
            external_taxon=cls.arthropoda_col,
            match_method="auto",
            confidence=0.95,
        )

        # Create genomes for Chordata (10 species, varied quality)
        cls.chordata_genomes = []
        for i in range(10):
            taxon = Taxon.objects.create(
                taxid=10000 + i,
                scientific_name=f"Chordata_sp_{i:02d}",
                rank="species",
            )
            col = ExternalTaxon.objects.create(
                external_id=f"col_chordata_sp_{i:02d}",
                name=f"Chordata_sp_{i:02d}",
                rank="species",
                system="col",
                classification={
                    "phylum": "Chordata",
                    "class": f"Class_{i % 3}",  # 3 different classes
                },
            )
            TaxonCrosswalk.objects.create(
                taxon=taxon, external_taxon=col, match_method="auto"
            )
            genome = NCBIGenome.objects.create(
                taxon=taxon,
                external_taxon=col,
                accession=f"GCA_CHORD_{i:03d}",
                organism_name=f"Chordata_sp_{i:02d}",
                col_match_status="matched",
                genome_level="chromosome" if i % 2 == 0 else "scaffold",
                quality_score=0.9 - (i * 0.05),  # Decreasing quality (0.9 → 0.45)
                contig_n50_kb=100 + (i * 10),
            )
            cls.chordata_genomes.append(genome)

        # Create genomes for Arthropoda (20 species, varied quality)
        cls.arthropoda_genomes = []
        for i in range(20):
            taxon = Taxon.objects.create(
                taxid=20000 + i,
                scientific_name=f"Arthropoda_sp_{i:02d}",
                rank="species",
                lineage="",
            )
            col = ExternalTaxon.objects.create(
                external_id=f"col_arthropoda_sp_{i:02d}",
                name=f"Arthropoda_sp_{i:02d}",
                rank="species",
                system="col",
                classification={
                    "phylum": "Arthropoda",
                    "class": f"Insecta" if i < 12 else f"Arachnida",
                },
            )
            TaxonCrosswalk.objects.create(
                taxon=taxon, external_taxon=col, match_method="auto"
            )
            genome = NCBIGenome.objects.create(
                taxon=taxon,
                external_taxon=col,
                accession=f"GCA_ARTH_{i:03d}",
                organism_name=f"Arthropoda_sp_{i:02d}",
                col_match_status="matched",
                genome_level="chromosome" if i % 3 == 0 else "scaffold",
                quality_score=0.85 - (i * 0.02),  # Decreasing quality (0.85 → 0.45)
                contig_n50_kb=80 + (i * 5),
            )
            cls.arthropoda_genomes.append(genome)

    def test_natural_order_strategy(self):
        """
        Test NATURAL strategy (order by accession up to max).
        
        Expectation:
        - Takes first K species by accession across all clades
        - No balance consideration
        - Deterministic (same result every time)
        """
        result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="natural",
        )

        self.assertEqual(result.total_selected, 12, "Should select exactly 12 species")
        self.assertEqual(result.strategy, "natural")

        # Check determinism: run twice
        result2 = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="natural",
        )
        species_set1 = {s["accession"] for s in result.species}
        species_set2 = {s["accession"] for s in result2.species}
        self.assertEqual(
            species_set1, species_set2, "Natural strategy should be deterministic"
        )

        print("\n✓ NATURAL STRATEGY")
        print(f"  Selected: {result.total_selected} / {result.total_available}")
        for clade in result.clades:
            print(
                f"    {clade['name']}: {clade['selected']} / {clade['species_available']}"
            )

    def test_quality_random_strategy(self):
        """
        Test QUALITY_RANDOM strategy (random within balanced quotas, prioritizing quality).
        
        Expectation:
        - Calculates balanced quotas (K / num_clades)
        - Within each clade, prioritizes high-quality genomes
        - Randomly samples from top-quality set
        - Average quality score should be high
        """
        result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="quality_random",
        )

        self.assertEqual(result.total_selected, 12, "Should select exactly 12 species")
        self.assertEqual(result.strategy, "quality_random")

        # Check quality score is reasonably high
        avg_quality = sum(s.get("quality_score", 0) for s in result.species) / len(
            result.species
        )
        self.assertGreater(
            avg_quality,
            0.6,
            f"Quality Random should prioritize quality (avg: {avg_quality:.2f})",
        )

        # Check balance: each clade should get ~equal representation
        clade_quotas = [clade["quota"] for clade in result.clades]
        quota_variance = max(clade_quotas) - min(clade_quotas)
        self.assertLessEqual(
            quota_variance,
            2,
            f"Quality Random should maintain balance (variance: {quota_variance})",
        )

        print("\n✓ QUALITY_RANDOM STRATEGY")
        print(f"  Selected: {result.total_selected} / {result.total_available}")
        print(f"  Avg Quality Score: {avg_quality:.3f}")
        for clade in result.clades:
            print(
                f"    {clade['name']}: {clade['selected']} / {clade['species_available']} "
                f"(quota: {clade['quota']})"
            )

    def test_stratified_proportional_strategy(self):
        """
        Test STRATIFIED_PROPORTIONAL strategy (quota ∝ clade size).
        
        Expectation:
        - Chordata (10/30 = 33%) → ~4 species
        - Arthropoda (20/30 = 67%) → ~8 species
        - Total: 12 species
        - Reflects natural distribution
        """
        result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="stratified_proportional",
        )

        self.assertEqual(result.total_selected, 12, "Should select exactly 12 species")
        self.assertEqual(result.strategy, "stratified_proportional")

        # Check proportional quotas
        clades_by_name = {c["name"]: c for c in result.clades}
        chordata_quota = clades_by_name.get("Chordata", {}).get("quota", 0)
        arthropoda_quota = clades_by_name.get("Arthropoda", {}).get("quota", 0)

        # Expected: Chordata ~4, Arthropoda ~8
        self.assertGreaterEqual(
            chordata_quota, 3, "Chordata should get ~4 species (proportional)"
        )
        self.assertLessEqual(
            chordata_quota, 5, "Chordata should get ~4 species (proportional)"
        )
        self.assertGreaterEqual(
            arthropoda_quota, 7, "Arthropoda should get ~8 species (proportional)"
        )
        self.assertLessEqual(
            arthropoda_quota, 9, "Arthropoda should get ~8 species (proportional)"
        )

        print("\n✓ STRATIFIED_PROPORTIONAL STRATEGY")
        print(f"  Selected: {result.total_selected} / {result.total_available}")
        print(f"  Proportions:")
        for clade in result.clades:
            pct = (clade["quota"] / result.total_selected) * 100
            print(
                f"    {clade['name']}: {clade['quota']} ({pct:.1f}%) "
                f"[available: {clade['species_available']}]"
            )

    def test_balanced_hierarchical_strategy(self):
        """
        Test BALANCED_HIERARCHICAL strategy (equal quota per clade).
        
        Expectation:
        - Each clade gets ~K/k = 12/2 = 6 species
        - Ignores natural abundance
        - Maximum balance
        """
        result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="balanced_hierarchical",
        )

        self.assertEqual(result.total_selected, 12, "Should select exactly 12 species")
        self.assertEqual(result.strategy, "balanced_hierarchical")

        # Check equal quotas
        clades_by_name = {c["name"]: c for c in result.clades}
        chordata_quota = clades_by_name.get("Chordata", {}).get("quota", 0)
        arthropoda_quota = clades_by_name.get("Arthropoda", {}).get("quota", 0)

        # Expected: exactly 6 each
        self.assertEqual(
            chordata_quota, 6, "Chordata should get exactly 6 species (balanced)"
        )
        self.assertEqual(
            arthropoda_quota, 6, "Arthropoda should get exactly 6 species (balanced)"
        )

        print("\n✓ BALANCED_HIERARCHICAL STRATEGY")
        print(f"  Selected: {result.total_selected} / {result.total_available}")
        print(f"  Quotas (equal per clade):")
        for clade in result.clades:
            print(
                f"    {clade['name']}: {clade['quota']} "
                f"[available: {clade['species_available']}]"
            )

    def test_max_sample_size_respected(self):
        """
        Test that max_sample_size is respected across all strategies.
        """
        for strategy in [
            "natural",
            "quality_random",
            "stratified_proportional",
            "balanced_hierarchical",
        ]:
            result = run_db_sampling(
                max_sample_size=8,
                start_rank="phylum",
                end_rank="species",
                strategy=strategy,
            )
            self.assertEqual(
                result.total_selected,
                8,
                f"Strategy '{strategy}' should respect max_sample_size=8",
            )

        print("\n✓ MAX_SAMPLE_SIZE RESPECTED")
        print("  All 4 strategies correctly limit to max_sample_size")

    def test_quality_random_vs_balanced_distribution(self):
        """
        Compare QUALITY_RANDOM vs BALANCED_HIERARCHICAL.
        
        Quality Random: emphasizes best genomes within quotas
        Balanced: pure equal distribution
        
        Expectation: Quality Random avg quality > Balanced avg quality
        """
        qr_result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="quality_random",
        )
        bal_result = run_db_sampling(
            max_sample_size=12,
            start_rank="phylum",
            end_rank="species",
            strategy="balanced_hierarchical",
        )

        qr_avg_quality = sum(s.get("quality_score", 0) for s in qr_result.species) / len(
            qr_result.species
        )
        bal_avg_quality = sum(
            s.get("quality_score", 0) for s in bal_result.species
        ) / len(bal_result.species)

        self.assertGreater(
            qr_avg_quality,
            bal_avg_quality,
            "Quality Random should select higher-quality genomes than Balanced",
        )

        print("\n✓ QUALITY_RANDOM vs BALANCED_HIERARCHICAL")
        print(f"  Quality Random avg quality:    {qr_avg_quality:.3f}")
        print(f"  Balanced Hierarchical quality: {bal_avg_quality:.3f}")
        print(f"  Difference: {(qr_avg_quality - bal_avg_quality):.3f}")

    def test_all_zero_max_sample_size(self):
        """
        Test behavior when max_sample_size=0 (should use all available).
        """
        result = run_db_sampling(
            max_sample_size=0,  # 0 = all
            start_rank="phylum",
            end_rank="species",
            strategy="natural",
        )

        self.assertEqual(
            result.total_selected,
            30,
            "max_sample_size=0 should select all 30 species",
        )

        print("\n✓ MAX_SAMPLE_SIZE=0 (USE ALL)")
        print(f"  Selected: {result.total_selected} / {result.total_available}")


class CladeAllocationTestCase(TestCase):
    """
    Direct unit tests for allocation functions.
    """

    def test_allocate_none(self):
        """Test _allocate_none: simple first-K allocation."""
        clades = [
            CladeAllocation(rank="phylum", name="Chordata", species_count=10),
            CladeAllocation(rank="phylum", name="Arthropoda", species_count=20),
        ]
        _allocate_none(clades, k=12)

        # Should allocate first K across clades in order
        self.assertEqual(clades[0].quota, 10)
        self.assertEqual(clades[1].quota, 2)
        self.assertEqual(sum(c.quota for c in clades), 12)

        print("\n✓ _allocate_none")
        print(f"  Clades[0] (Chordata): {clades[0].quota}")
        print(f"  Clades[1] (Arthropoda): {clades[1].quota}")

    def test_allocate_proportional(self):
        """Test _allocate_proportional: quota ∝ clade size."""
        clades = [
            CladeAllocation(rank="phylum", name="Chordata", species_count=10),
            CladeAllocation(rank="phylum", name="Arthropoda", species_count=20),
        ]
        _allocate_proportional(clades, k=12)

        total = sum(c.quota for c in clades)
        self.assertEqual(total, 12)

        # Chordata: 12 * (10/30) = 4
        # Arthropoda: 12 * (20/30) = 8
        self.assertAlmostEqual(clades[0].quota, 4, delta=1)
        self.assertAlmostEqual(clades[1].quota, 8, delta=1)

        print("\n✓ _allocate_proportional")
        print(f"  Clades[0] (Chordata): {clades[0].quota} (expect ~4)")
        print(f"  Clades[1] (Arthropoda): {clades[1].quota} (expect ~8)")

    def test_allocate_balanced(self):
        """Test _allocate_balanced: equal quota per clade."""
        clades = [
            CladeAllocation(rank="phylum", name="Chordata", species_count=10),
            CladeAllocation(rank="phylum", name="Arthropoda", species_count=20),
        ]
        _allocate_balanced(clades, k=12)

        # Should be equal: 12 / 2 = 6 each
        self.assertEqual(clades[0].quota, 6)
        self.assertEqual(clades[1].quota, 6)
        self.assertEqual(sum(c.quota for c in clades), 12)

        print("\n✓ _allocate_balanced")
        print(f"  Clades[0] (Chordata): {clades[0].quota} (expect 6)")
        print(f"  Clades[1] (Arthropoda): {clades[1].quota} (expect 6)")


if __name__ == "__main__":
    import unittest
    unittest.main()
