# apps/taxonomy/management/commands/warmup_cache.py
"""
Management command to pre-warm the tree cache.

Run after data imports or server restarts for instant tree loading.
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from apps.taxonomy.models import ExternalTaxon
from apps.taxonomy.tree.views import _get_tree_cache_key, TREE_CACHE_TIMEOUT


class Command(BaseCommand):
    help = "Pre-warm the tree cache for instant loading"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing cache before warming",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing existing tree cache...")
            for limit in [None, 1000, 5000, 10000, 15000]:
                for rank_cut in [None, "phylum", "class", "order", "family"]:
                    key = _get_tree_cache_key(limit, rank_cut)
                    cache.delete(key)
            self.stdout.write(self.style.WARNING("Cache cleared"))

        self.stdout.write("Building taxonomy tree...")
        
        # Build the default tree (no limit, no rank cut)
        tree = ExternalTaxon.objects.build_tree(
            limit=None,
            system="col",
            rank_cut=None,
            with_keys=True,
        )
        
        # Cache it
        cache_key = _get_tree_cache_key(None, None)
        cache.set(cache_key, tree, TREE_CACHE_TIMEOUT)
        
        # Count species
        def count_species(node):
            if not node:
                return 0
            children = node.get("children") or node.get("_children") or []
            if not children:
                return 1 if node.get("rank") in ("species", "subspecies") else 0
            return sum(count_species(c) for c in children)
        
        species_count = count_species(tree)
        
        self.stdout.write(self.style.SUCCESS(
            f"✓ Tree cached ({species_count} species) for {TREE_CACHE_TIMEOUT}s"
        ))
        self.stdout.write(f"  Cache key: {cache_key}")
