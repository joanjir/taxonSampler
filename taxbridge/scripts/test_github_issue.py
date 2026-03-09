import os
import sys
import django
# Ensure project package dir is on sys.path so 'config' can be imported when running the script
SCRIPT_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local')
django.setup()
from django.conf import settings
import json, urllib.request, urllib.error

token = settings.GITHUB_TOKEN
repo = settings.GITHUB_REPO
if not token:
    print('No GITHUB_TOKEN configured')
    raise SystemExit(1)

api_url = f'https://api.github.com/repos/{repo}/issues'
headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'TaxonSampler-Test'
}
body = json.dumps({'title':'PRUEBA desde script','body':'Prueba de creación de issue desde script'}).encode('utf-8')
req = urllib.request.Request(api_url, data=body, headers=headers, method='POST')
try:
    with urllib.request.urlopen(req) as resp:
        print('Status:', resp.status)
        print(resp.read().decode())
except urllib.error.HTTPError as e:
    print('HTTPError', e.code)
    print(e.read().decode())
except Exception as e:
    print('Error', str(e))
