# Create your views here.
import json
from django.http import JsonResponse,HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render

from .models import SamplingRun
from .services.orthology_tree import sampling_to_tree_artifacts

def health(request):
    return JsonResponse({"status": "Hola estoy vivo!"})

from django.shortcuts import render

def tree_page(request):
    # solo renderiza la página; el JSON lo pide el frontend
    return render(request, "taxonomy/pages/tree/index.html", {})


def colnav_page(request):
    return render(request, "taxonomy/colnav/index.html")


def base (request):
    return render(request, "taxonomy/layout/app_shell.html")

def scroll_test(request):
    return render(request, "taxonomy/pages/test.html")




@csrf_exempt
@require_POST
def sampling_create(request):
    payload = json.loads(request.body.decode("utf-8"))

    newick, tree_json = sampling_to_tree_artifacts(payload, include_outgroup=False)

    run = SamplingRun.objects.create(
        scope_root_key=payload.get("scopeRootKey", ""),
        params={
            "K": payload.get("K"),
            "allocation": payload.get("allocation"),
            "allocationRank": payload.get("allocationRank"),
            "targetRank": payload.get("targetRank"),
            "minOnePerClade": payload.get("minOnePerClade"),
            "outgroup": payload.get("outgroup"),
            "refinement": payload.get("refinement"),
        },
        sampling_payload=payload,
        tree_newick=newick,
        tree_json=tree_json,
    )

    return JsonResponse({
        "id": run.pk,
        "tree_url": f"/taxonomy/sampling/{run.pk}/tree/",
        "newick_url": f"/taxonomy/sampling/{run.pk}/tree.nwk",
    })


def sampling_tree_page(request, pk: int):
    run = get_object_or_404(SamplingRun, pk=pk)
    return render(request, "taxonomy/sampling_tree.html", {"run": run})


def sampling_tree_newick(request, pk: int):
    run = get_object_or_404(SamplingRun, pk=pk)
    return HttpResponse(run.tree_newick, content_type="text/plain; charset=utf-8")
