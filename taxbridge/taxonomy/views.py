from django.shortcuts import render
# Create your views here.
from django.http import JsonResponse

def health(request):
    return JsonResponse({"status": "Hola estoy vivo!"})

from django.shortcuts import render

def tree_page(request):
    # solo renderiza la página; el JSON lo pide el frontend
    return render(request, "taxonomy/tree/index.html", {})



def colnav_page(request):
    return render(request, "taxonomy/colnav/index.html")
