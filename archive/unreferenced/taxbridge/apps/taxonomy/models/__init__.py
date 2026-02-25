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
from .sync import NCBISyncRun, TaxonSyncRun, DiscoveryRun, DiscoveredSpecies
from .sampling import ResolutionRun, ResolutionItem, SamplingRun, SamplingConfiguration

__all__ = [
    "Taxon",
    "ExternalTaxon",
    "TaxonCrosswalk",
    "TaxonNameIndex",
    "RunEvent",
    "NCBIGenome",
    "NCBISyncRun",
    "TaxonSyncRun",
    "DiscoveryRun",
    "DiscoveredSpecies",
    "ResolutionRun",
    "ResolutionItem",
    "SamplingRun",
    "SamplingConfiguration",
]
