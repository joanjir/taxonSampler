# Create your views here.
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Count, F, Q

from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from apps.taxonomy.utils import sampling_to_tree_artifacts
from .dashboard import get_home_context, DASHBOARD_CACHE_KEY, DASHBOARD_CACHE_TTL

@ensure_csrf_cookie
def home(request):
    context = get_home_context()
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