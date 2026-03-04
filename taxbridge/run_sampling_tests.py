#!/usr/bin/env python
"""
Test runner for sampling strategies with comprehensive reporting.

Usage:
    python manage.py test apps.taxonomy.tests.test_sampling_strategies -v 2
    
Or with pytest:
    pytest apps/taxonomy/tests/test_sampling_strategies.py -v -s
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from django.test.utils import get_runner
from django.conf import settings

if __name__ == "__main__":
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False, keepdb=False)
    
    # Run the specific test module
    failures = test_runner.run_tests([
        "apps.taxonomy.tests.test_sampling_strategies"
    ])
    
    sys.exit(bool(failures))
