# Create your views here.
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render
from django.db.models import Count, Q

from .models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from .services.orthology_tree import sampling_to_tree_artifacts


def home(request):
    """Dashboard principal con estadísticas y lista de genomas."""
    
    # Estadísticas de genomas usando col_match_status (consistente con el listado)
    total_genomes = NCBIGenome.objects.count()
    matched_genomes = NCBIGenome.objects.filter(col_match_status="matched").count()
    unmatched_genomes = NCBIGenome.objects.filter(col_match_status="unmatched").count()
    # no_match (not found in COL) también cuenta como needs_review
    needs_review_count = NCBIGenome.objects.filter(
        Q(col_match_status="needs_review") | Q(col_match_status="no_match")
    ).count()
    
    # Estadísticas por nivel de genoma
    genome_levels = list(
        NCBIGenome.objects
        .values("genome_level")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    
    # Estadísticas por phylum (todos los phyla, no solo top 10)
    phylum_stats = list(
        NCBIGenome.objects
        .exclude(phylum="")
        .exclude(phylum__isnull=True)
        .values("phylum")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    
    # Estadísticas de taxonomía
    total_ncbi_taxa = Taxon.objects.count()
    total_col_taxa = ExternalTaxon.objects.filter(system="col").count()
    total_col_species = ExternalTaxon.objects.filter(system="col", rank="species", status="accepted").count()
    total_crosswalks = TaxonCrosswalk.objects.filter(is_active=True).count()
    
    context = {
        # Genomas
        "total_genomes": total_genomes,
        "matched_genomes": matched_genomes,
        "unmatched_genomes": unmatched_genomes,
        "needs_review": needs_review_count,
        "genome_levels": genome_levels,
        "phylum_stats": phylum_stats,
        # Taxonomía
        "total_ncbi_taxa": total_ncbi_taxa,
        "total_col_taxa": total_col_taxa,
        "total_col_species": total_col_species,
        "total_crosswalks": total_crosswalks,
        # Porcentajes
        "match_percent": round(matched_genomes / total_genomes * 100, 1) if total_genomes else 0,
    }
    
    return render(request, "taxonomy/pages/home.html", context)


@require_POST
def export_sampling(request, fmt: str):
    """
    fmt: "json" | "txt" | "newick" | "treejson"
    Body: JSON con el sampling result completo (lo que emite sampling:final)
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    if fmt == "json":
        # Devuelve el sampling tal cual
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        resp = HttpResponse(data, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling.json"'
        return resp

    if fmt == "txt":
        ing = payload.get("ingroup", {}).get("picked", []) or []
        out = payload.get("outgroupPicked", []) or []
        # lista legible (ingroup/outgroup)
        lines = []
        for x in out:
            lines.append(f"OUTGROUP\t{x.get('rank','')}\t{x.get('name','')}\t{x.get('key','')}")
        for x in ing:
            lines.append(f"INGROUP\t{x.get('rank','')}\t{x.get('name','')}\t{x.get('key','')}")
        data = "\n".join(lines) + ("\n" if lines else "")
        resp = HttpResponse(data, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling.txt"'
        return resp

    if fmt == "newick":
        newick, _tree_json = sampling_to_tree_artifacts(payload, include_outgroup=True)
        resp = HttpResponse(newick, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling_species.newick"'
        return resp

    if fmt == "treejson":
        _newick, tree_json = sampling_to_tree_artifacts(payload, include_outgroup=True)
        data = json.dumps(tree_json, ensure_ascii=False, indent=2)
        resp = HttpResponse(data, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling_tree.json"'
        return resp

    return JsonResponse({"error": "Formato no soportado"}, status=400)