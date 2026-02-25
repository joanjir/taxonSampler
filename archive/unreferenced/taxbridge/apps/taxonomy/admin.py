from __future__ import annotations

import json
from django.contrib import admin
from django.db.models import JSONField
from django.forms import Textarea
from django.utils.html import format_html

from .models import (
    Taxon,
    ExternalTaxon,
    TaxonCrosswalk,
)


# ---------- Helpers ----------
class PrettyJSONWidget(Textarea):
    def format_value(self, value):
        if value is None or value == "":
            return ""
        try:
            if isinstance(value, str):
                obj = json.loads(value)
            else:
                obj = value
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)


@admin.register(Taxon)
class TaxonAdmin(admin.ModelAdmin):
    list_display = ("taxid", "scientific_name", "rank", "updated_at")
    list_filter = ("rank",)
    search_fields = ("scientific_name", "taxid")
    ordering = ("taxid",)
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 12, "style": "font-family: Consolas, monospace;"})}
    }


@admin.register(ExternalTaxon)
class ExternalTaxonAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "rank", "status", "system", "dataset_code", "external_id", "parent_external_id")
    list_filter = ("system", "dataset_code", "status", "rank")
    search_fields = ("name", "external_id", "parent_external_id")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    autocomplete_fields = ("accepted", "parent")
    formfield_overrides = {
        JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 14, "style": "font-family: Consolas, monospace;"})}
    }


@admin.register(TaxonCrosswalk)
class TaxonCrosswalkAdmin(admin.ModelAdmin):
    list_display = ("id", "ncbi_taxon_link", "external_taxon_link", "decision", "method", "score", "is_active", "curation_level", "created_at")
    list_filter = ("decision", "method", "is_active", "curation_level")
    search_fields = (
        "ncbi_taxon__scientific_name",
        "ncbi_taxon__taxid",
        "external_taxon__name",
        "external_taxon__external_id",
        "external_taxon__dataset_code",
    )
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    autocomplete_fields = ("ncbi_taxon", "external_taxon")
    formfield_overrides = {
        JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 12, "style": "font-family: Consolas, monospace;"})}
    }

    @admin.display(description="NCBI Taxon")
    def ncbi_taxon_link(self, obj: TaxonCrosswalk):
        t = obj.ncbi_taxon
        return format_html("<b>{}</b> ({})", t.scientific_name, t.taxid)

    @admin.display(description="CoL Taxon")
    def external_taxon_link(self, obj: TaxonCrosswalk):
        e = obj.external_taxon
        ds = e.dataset_code or "-"
        return format_html("<b>{}</b> [{}:{}:{}]", e.name, e.system, ds, e.external_id)
