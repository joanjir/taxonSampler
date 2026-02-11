# apps/taxonomy/models/__init__.py
"""
Re-export all models so Django autodiscovery works seamlessly.

Usage remains the same:
    from apps.taxonomy.models import Taxon, NCBIGenome, ...
"""
from .core import (
    Taxon,
    ExternalTaxon,
    TaxonCrosswalk,
    TaxonNameIndex,
    RunEvent,
)
from .genome import NCBIGenome
from .sync import NCBISyncRun, TaxonSyncRun
from .sampling import ResolutionRun, ResolutionItem, SamplingRun

__all__ = [
    "Taxon",
    "ExternalTaxon",
    "TaxonCrosswalk",
    "TaxonNameIndex",
    "RunEvent",
    "NCBIGenome",
    "NCBISyncRun",
    "TaxonSyncRun",
    "ResolutionRun",
    "ResolutionItem",
    "SamplingRun",
]
