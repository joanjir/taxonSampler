# Create your views here.
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render
from django.db.models import Count, F, Q

from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from apps.taxonomy.utils import sampling_to_tree_artifacts


def home(request):
    """Main dashboard with statistics and genome listing."""
    
    # Genome statistics using col_match_status (consistent with the listing)
    total_genomes = NCBIGenome.objects.count()
    matched_genomes = NCBIGenome.objects.filter(col_match_status="matched").count()
    unmatched_genomes = NCBIGenome.objects.filter(col_match_status="unmatched").count()
    not_in_col_count = NCBIGenome.objects.filter(col_match_status="not_in_col").count()
    manual_count = NCBIGenome.objects.filter(col_match_status="manual").count()
    
    # Statistics by genome level
    genome_levels = list(
        NCBIGenome.objects
        .values("genome_level")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    
    # Statistics by kingdom (via classification JSON on linked ExternalTaxon)
    kingdom_stats = list(
        NCBIGenome.objects
        .filter(external_taxon__isnull=False)
        .exclude(external_taxon__classification__kingdom__isnull=True)
        .exclude(external_taxon__classification__kingdom="")
        .values(
            kingdom=F("external_taxon__classification__kingdom"),
            superkingdom=F("external_taxon__classification__superkingdom")
        )
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Some classification records don't include 'superkingdom' (domain). Try to fill
    # missing values by looking up any ExternalTaxon that contains the kingdom and
    # reading its classification, or use a small heuristic fallback.
    if kingdom_stats:
        for entry in kingdom_stats:
            if entry.get("superkingdom"):
                continue
            kname = entry.get("kingdom")
            sk = None
            try:
                ext = ExternalTaxon.objects.filter(classification__kingdom=kname).first()
                if ext:
                    sk = ext.classification.get("superkingdom") or ext.classification.get("domain")
            except Exception:
                sk = None

            # Heuristic fallback for common kingdoms
            if not sk and kname:
                lname = kname.lower()
                if lname in ("animalia", "plantae", "fungi", "protozoa"):
                    sk = "Eukarya"
                elif "archaea" in lname or "thermoprote" in lname or "methan" in lname:
                    sk = "Archaea"
                else:
                    # default to Bacteria for most unknown microbial kingdoms
                    sk = "Bacteria"

            entry["superkingdom"] = sk
    
    # Taxonomy statistics
    total_ncbi_taxa = Taxon.objects.count()
    total_col_taxa = ExternalTaxon.objects.filter(system="col").count()
    total_col_species = ExternalTaxon.objects.filter(system="col", rank="species", status="accepted").count()
    total_crosswalks = TaxonCrosswalk.objects.filter(is_active=True).count()
    
    context = {
        # Genomes
        "total_genomes": total_genomes,
        "matched_genomes": matched_genomes,
        "unmatched_genomes": unmatched_genomes,
        "not_in_col_count": not_in_col_count,
        "manual_count": manual_count,
        "genome_levels": genome_levels,
        "kingdom_stats": kingdom_stats,
        # Taxonomy
        "total_ncbi_taxa": total_ncbi_taxa,
        "total_col_taxa": total_col_taxa,
        "total_col_species": total_col_species,
        "total_crosswalks": total_crosswalks,
        # Percentages
        "match_percent": round(matched_genomes / total_genomes * 100, 1) if total_genomes else 0,
    }
    
    return render(request, "taxonomy/pages/home.html", context)


@require_POST
def export_sampling(request, fmt: str):
    """
    fmt: "json" | "txt" | "newick" | "treejson"
    Body: JSON with the complete sampling result (what sampling:final emits)
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if fmt == "json":
        # Return the sampling as-is
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        resp = HttpResponse(data, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling.json"'
        return resp

    if fmt == "txt":
        ing = payload.get("ingroup", {}).get("picked", []) or []
        out = payload.get("outgroupPicked", []) or []
        # human-readable list (ingroup/outgroup)
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

    return JsonResponse({"error": "Unsupported format"}, status=400)


def report_issue(request):
    """Render the GitHub issue report form."""
    return render(request, "taxonomy/pages/report_issue.html")