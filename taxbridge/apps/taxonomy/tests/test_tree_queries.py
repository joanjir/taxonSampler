"""Regression coverage for tree query cost and taxon metadata."""

from django.test import TestCase

from apps.taxonomy.models import ExternalTaxon, NCBIGenome, Taxon


class TreeQueryTestCase(TestCase):
    lineage = [
        {"rank": "domain", "name": "Eukaryota"},
        {"rank": "kingdom", "name": "Animalia"},
        {"rank": "phylum", "name": "Chordata"},
        {"rank": "class", "name": "Mammalia"},
        {"rank": "family", "name": "Felidae"},
        {"rank": "genus", "name": "Panthera"},
    ]
    genus_key = (
        "dataset:Root|domain:Eukaryota|kingdom:Animalia|phylum:Chordata"
        "|class:Mammalia|family:Felidae|genus:Panthera"
    )

    @classmethod
    def setUpTestData(cls):
        cls.species = {}
        for taxid, (name, system, status, match_status) in enumerate(
            [
                ("Panthera leo", "col", "accepted", "matched"),
                ("Panthera tigris", "col", "synonym", "matched"),
                ("Panthera onca", "col", "accepted", "matched"),
                ("Panthera pardus", "manual", "accepted", "manual"),
                ("Panthera uncia", "col", "accepted", "unmatched"),
            ],
            start=1,
        ):
            classification = {part["rank"]: part["name"] for part in cls.lineage}
            path = cls.lineage + [{"rank": "species", "name": name}]
            if system == "manual":
                # Manual records have an abbreviated, unordered classification.
                classification = {
                    "genus": "Panthera",
                    "superkingdom": "Eukaryota",
                    "class": "Mammalia",
                }
                path = []
            external = ExternalTaxon.objects.create(
                system=system,
                dataset_code="test",
                external_id=f"species-{taxid}",
                name=name,
                rank="species",
                status=status,
                classification=classification,
                classification_path=path,
            )
            cls.species[name] = external
            taxon = Taxon.objects.create(
                taxid=taxid,
                scientific_name=name,
                rank="species",
            )
            # Multiple assemblies must not duplicate a species or its counts.
            for assembly in range(2 if name == "Panthera leo" else 1):
                NCBIGenome.objects.create(
                    taxon=taxon,
                    external_taxon=external,
                    accession=f"GCF_{taxid:09d}.{assembly + 1}",
                    col_match_status=match_status,
                )

    def test_two_queries_preserve_classification_counts_and_sources(self):
        # One COL query and one manual query, without per-species field fetches.
        with self.assertNumQueries(2):
            tree = ExternalTaxon.objects.build_tree()

        self.assertEqual(tree["key"], "dataset:Root")
        self.assertEqual(tree["species_count"], 4)
        parent = tree
        for part in self.lineage:
            self.assertEqual(len(parent["children"]), 1)
            parent = parent["children"][0]
            self.assertEqual((parent["rank"], parent["name"]), (part["rank"], part["name"]))
            self.assertEqual(parent["species_count"], 4)
            self.assertEqual(parent["superkingdom"], "Eukaryota")

        self.assertEqual(parent["key"], self.genus_key)
        leaves = {node["name"]: node for node in parent["children"]}
        self.assertEqual(len(parent["children"]), 4)
        self.assertEqual(
            {name: node["source"] for name, node in leaves.items()},
            {
                "Panthera leo": "accepted",
                "Panthera tigris": "synonym",
                "Panthera onca": "accepted",
                "Panthera pardus": "manual",
            },
        )
        for name, leaf in leaves.items():
            with self.subTest(species=name):
                self.assertEqual(leaf["id"], self.species[name].pk)
                self.assertEqual(leaf["external_id"], self.species[name].external_id)
                self.assertEqual(leaf["species_count"], 1)
                self.assertEqual(leaf["rank"], "species")
                self.assertEqual(leaf["key"], f"{self.genus_key}|species:{name}")

    def test_limit_keeps_manual_species_without_additional_queries(self):
        with self.assertNumQueries(2):
            tree = ExternalTaxon.objects.build_tree(limit=1, with_keys=False)

        self.assertEqual(tree["species_count"], 2)
        node = tree
        for _ in self.lineage:
            self.assertNotIn("key", node)
            self.assertEqual(len(node["children"]), 1)
            node = node["children"][0]
            self.assertEqual(node["species_count"], 2)

        self.assertNotIn("key", node)
        self.assertEqual(
            [(leaf["name"], leaf["source"]) for leaf in node["children"]],
            [("Panthera leo", "accepted"), ("Panthera pardus", "manual")],
        )
        for leaf in node["children"]:
            self.assertNotIn("key", leaf)
