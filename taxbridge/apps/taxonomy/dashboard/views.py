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
    

    # Estadísticas de genomas
    total_genomes = NCBIGenome.objects.count()
    matched_genomes = NCBIGenome.objects.filter(col_match_status="matched").count()
    manual_genomes = NCBIGenome.objects.filter(col_match_status="manual").count()
    linked_genomes = matched_genomes + manual_genomes
    not_in_col_genomes = NCBIGenome.objects.filter(col_match_status="not_in_col").count()

    # Samplable Species: especies únicas (ExternalTaxon) con al menos un genoma matched o manual
    samplable_species = ExternalTaxon.objects.filter(
        rank__in=["species", "subspecies", "variety", "form"],
        system__in=["col", "manual"],
        ncbi_genomes__col_match_status__in=["matched", "manual"]
    ).distinct().count()

    # Excluded: especies únicas (Taxon) con al menos un genoma not_in_col o mismatch
    excluded_species = Taxon.objects.filter(
        genomes__col_match_status="not_in_col"
    ).distinct().count()

    # COL Taxonomy: especies aceptadas en ExternalTaxon con system="col"
    total_col_species = ExternalTaxon.objects.filter(system="col", rank="species", status="accepted").count()

    # Estadísticas por nivel de genoma (sin cambios)
    genome_levels = list(
        NCBIGenome.objects
        .values("genome_level")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Estadísticas por reino (sin cambios)
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

    # Rellenar superkingdom si falta (sin cambios)
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
            if not sk and kname:
                lname = kname.lower()
                if lname in ("animalia", "plantae", "fungi", "protozoa"):
                    sk = "Eukarya"
                elif "archaea" in lname or "thermoprote" in lname or "methan" in lname:
                    sk = "Archaea"
                else:
                    sk = "Bacteria"
            entry["superkingdom"] = sk

    # Estadísticas de taxonomía
    total_ncbi_taxa = Taxon.objects.count()
    total_col_taxa = ExternalTaxon.objects.filter(system="col").count()
    total_crosswalks = TaxonCrosswalk.objects.filter(is_active=True).count()

    # COL status breakdown (especies vinculadas con genomas)
    col_status_qs = (
        ExternalTaxon.objects
        .filter(system="col", ncbi_genomes__isnull=False)
        .values("status")
        .annotate(count=Count("id", distinct=True))
    )
    col_status_map = {s["status"]: s["count"] for s in col_status_qs}
    accepted_count = col_status_map.get("accepted", 0)
    synonym_count = col_status_map.get("synonym", 0) + col_status_map.get("ambiguous synonym", 0)
    provisional_count = col_status_map.get("provisionally accepted", 0)

    # COL coverage: solo auto-matched (manual NO son de COL)
    col_matched_taxa = Taxon.objects.filter(genomes__col_match_status="matched").distinct().count()
    col_coverage_pct = round(col_matched_taxa / total_genomes * 100) if total_genomes else 0

    # Not in COL: taxa with not_in_col or manual status
    not_in_col_taxa = Taxon.objects.filter(genomes__col_match_status="not_in_col").distinct().count()
    manual_taxa = Taxon.objects.filter(genomes__col_match_status="manual").distinct().count()
    not_in_col_total = not_in_col_taxa + manual_taxa
    pending_review = not_in_col_taxa

    # Contexto para el template
    context = {
        # Genomas
        "total_genomes": total_genomes,
        "matched_genomes": matched_genomes,
        "manual_genomes": manual_genomes,
        "linked_genomes": linked_genomes,
        "not_in_col_genomes": not_in_col_genomes,
        # Especies
        "samplable_species": samplable_species,
        "excluded_species": excluded_species,
        # COL Coverage
        "col_matched_taxa": col_matched_taxa,
        "col_coverage_pct": col_coverage_pct,
        # Not in COL
        "not_in_col_total": not_in_col_total,
        "manual_taxa": manual_taxa,
        "pending_review": pending_review,
        # COL Status
        "accepted_count": accepted_count,
        "synonym_count": synonym_count,
        "provisional_count": provisional_count,
        # Taxonomía
        "total_ncbi_taxa": total_ncbi_taxa,
        "total_col_taxa": total_col_taxa,
        "total_col_species": total_col_species,
        "total_crosswalks": total_crosswalks,
        # Otros
        "genome_levels": genome_levels,
        "kingdom_stats": kingdom_stats,
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


@require_POST
def create_github_issue(request):
    """
    Create an issue directly on GitHub via API.
    Requires GITHUB_TOKEN in settings/env.
    Falls back to opening GitHub in a new tab if token not configured.
    """
    import urllib.request
    import urllib.error
    import logging
    from django.conf import settings
    logger = logging.getLogger(__name__)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    title = payload.get("title", "").strip()
    body = payload.get("body", "").strip()
    labels = payload.get("labels", [])

    if not title or not body:
        return JsonResponse({"error": "Title and body are required"}, status=400)

    token = getattr(settings, "GITHUB_TOKEN", "") or ""
    repo = getattr(settings, "GITHUB_REPO", "joanjir/taxonSampler")

    if not token:
        # Log masked token state for debugging (do not log actual token)
        logger.debug("create_github_issue invoked but no GITHUB_TOKEN present (REPORT_ALWAYS_GITHUB=%s)", getattr(settings, 'REPORT_ALWAYS_GITHUB', True))
        # Respect REPORT_ALWAYS_GITHUB: if True, require GITHUB_TOKEN and do not fallback to email
        always_github = getattr(settings, "REPORT_ALWAYS_GITHUB", True)
        if always_github:
            return JsonResponse({
                "error": "GITHUB_TOKEN not configured",
                "detail": "Server requires a GITHUB_TOKEN to create issues. Configure GITHUB_TOKEN in settings/.env.",
                "report_always_github": True,
                "token_present": False,
            }, status=503)

        # Otherwise allow email fallback if configured
        report_email = getattr(settings, "REPORT_EMAIL", "") or ""
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")
        if report_email:
            try:
                from django.core.mail import send_mail

                subject = f"[Report Issue] {title}"
                # Use the same body content as would be sent to GitHub
                message = body
                send_mail(subject, message, from_email, [report_email], fail_silently=False)
                return JsonResponse({
                    "success": True,
                    "emailed": True,
                    "recipient": report_email,
                    "token_present": False,
                })
            except Exception as e:
                logger.exception("Failed to send report email")
                return JsonResponse({
                    "error": "Failed to send report email",
                    "detail": str(e),
                    "token_present": False,
                }, status=502)

        # No token and no report email configured: instruct frontend to fallback
        return JsonResponse({
            "error": "GITHUB_TOKEN not configured",
            "fallback": True,
            "token_present": False,
        }, status=503)

    # Build GitHub API request
    api_url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps({
        "title": title,
        "body": body,
        "labels": labels if isinstance(labels, list) else [labels],
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "TaxonSampler-App",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return JsonResponse({
                "success": True,
                "issue_url": result.get("html_url", ""),
                "issue_number": result.get("number", 0),
            })
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return JsonResponse({
            "error": f"GitHub API error ({e.code})",
            "detail": error_body,
        }, status=502)
    except Exception as e:
        return JsonResponse({
            "error": f"Request failed: {str(e)}",
        }, status=502)


# ─────────────────────────────────────────
# Static Pages
# ─────────────────────────────────────────

def about(request):
    """About page with software information and methodology."""
    return render(request, "taxonomy/pages/about.html")


def tutorials(request):
    """Tutorials page with step-by-step guides for sampling strategies."""
    return render(request, "taxonomy/pages/tutorials.html")