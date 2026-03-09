import os
import sys
import django
SCRIPT_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local')
django.setup()
from django.test import Client
import json

c = Client()
payload = {
    'title': 'Test report from test client',
    'body': 'This is a test body',
    'labels': ['bug']
}
resp = c.post('/taxonomy/report-issue/create/', json.dumps(payload), content_type='application/json')
print('Status code:', resp.status_code)
try:
    print('JSON:', resp.json())
except Exception:
    print('Response body:', resp.content.decode())
