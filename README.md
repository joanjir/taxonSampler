# TaxonSampler

**TaxonSampler** is a Django-based web application for taxonomic sampling and genome data management. It bridges species data from the [Catalogue of Life (COL)](https://www.catalogueoflife.org/) and the [NCBI Datasets API](https://www.ncbi.nlm.nih.gov/datasets/) into a unified platform where researchers can explore, filter, and sample species across the tree of life.

---

## What does it do?

| Capability | Description |
|---|---|
| **COL Integration** | Imports accepted species from the Catalogue of Life / ChecklistBank, storing their full classification path (from domain to species). |
| **NCBI Genome Sync** | Fetches genome assembly metadata from NCBI Datasets (assembly level, contig N50, scaffold count, genome size, annotation status, etc.) and links each genome to its COL counterpart via a crosswalk table. |
| **Taxonomy Visualization** | Interactive D3.js-powered hierarchical visualization of the taxonomy with collapsible nodes, breadcrumb navigation, and search. |
| **Sampling Wizard** | A 3-step wizard that lets users define a sampling scope (entire taxonomy or a specific clade), configure genome-quality filters (assembly level ranges, contig N50 thresholds, etc.), and execute the sampling. |
| **Manual Taxonomy Editing** | Users can manually add or edit species and their classification when COL data is incomplete or incorrect. Manual entries are automatically merged into the existing COL hierarchy. |
| **Export** | Export results to JSON, TXT, Newick, or Excel (XLSX). |
| **Dashboard** | Overview of species counts, genome coverage, sync status, and recent activity. |
| **Background Tasks** | Celery-powered async tasks for NCBI synchronization, species discovery, and genome resolution — with scheduled jobs via Celery Beat. |

---

## Tech Stack

- **Backend:** Django 6.0, Django REST Framework, Python 3.13
- **Task Queue:** Celery 5.4 + Redis (broker & result backend)
- **Database:** PostgreSQL (via `psycopg2-binary`)
- **Frontend:** Bootstrap 5 (Tabler theme), D3.js v5, ES Modules
- **Phylogenetics:** ETE3 (Newick generation)
- **Spreadsheets:** openpyxl (XLSX import/export)

---

## Project Structure

```
taxbridge/                      # Django project root
├── manage.py
├── config/                     # Project configuration
│   ├── settings/
│   │   ├── base.py             # Shared settings (DB, Celery, APIs)
│   │   ├── local.py            # Local development overrides
│   │   └── prod.py             # Production settings
│   ├── celery.py               # Celery app configuration
│   ├── urls.py                 # Root URL routing
│   └── wsgi.py / asgi.py
├── apps/
│   └── taxonomy/               # Main application
│       ├── models/             # Django models
│       │   ├── core.py         # Taxon, ExternalTaxon, TaxonCrosswalk, RunEvent
│       │   ├── genome.py       # NCBIGenome
│       │   ├── sync.py         # NCBISyncRun, TaxonSyncRun, DiscoveryRun
│       │   └── sampling.py     # ResolutionRun, ResolutionItem, SamplingRun
│       ├── managers.py         # Tree builder (trie-based)
│       ├── ncbi/               # NCBI integration
│       │   ├── service.py      # API client & sync logic
│       │   ├── tasks.py        # Celery tasks (sync, discovery)
│       │   └── views.py        # NCBI-related endpoints
│       ├── sampling/           # Sampling engine
│       │   ├── service.py      # Sampling orchestration
│       │   ├── assembly_engine.py
│       │   └── db_engine.py
│       ├── api/                # REST API endpoints
│       ├── dashboard/          # Dashboard views
│       ├── tree/               # Taxonomy visualization logic
│       ├── management/commands/ # Django management commands
│       ├── templates/          # HTML templates (Tabler/Bootstrap)
│       └── static/taxonomy/    # CSS, JS, images
└── requirements.txt
```

---

## Data Model Overview

```
Taxon (NCBI)  ──┐
                 ├──  TaxonCrosswalk  ──  ExternalTaxon (COL / manual)
NCBIGenome   ───┘
                          │
                   classification_path (COL)
                   classification dict  (manual)
                          │
                     build_tree() ── trie → D3.js hierarchy
```

- **Taxon**: NCBI taxon record (taxid, scientific name, rank).
- **ExternalTaxon**: COL or manually-entered species with full classification.
- **TaxonCrosswalk**: Links an NCBI Taxon to its COL ExternalTaxon match.
- **NCBIGenome**: Genome assembly metadata from NCBI Datasets.
- **SamplingRun / ResolutionRun**: Records of sampling operations and their results.

---

## Getting Started

### Prerequisites

- Python 3.13+
- PostgreSQL
- Redis (for Celery)

### 1. Clone & activate virtual environment

```bash
git clone <repository-url>
cd ProyectoNCBI_COL
```

```powershell
# Windows PowerShell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS / Git Bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the `taxbridge/` directory:

```env
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://user:password@localhost:5432/taxonsampler
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
NCBI_API_KEY=your-ncbi-api-key
```

### 4. Run migrations

```bash
cd taxbridge
python manage.py migrate
python manage.py createsuperuser
```

### 5. Collect static files

```bash
python manage.py collectstatic --noinput
```

### 6. Start the development server

```bash
python manage.py runserver 0.0.0.0:8000
```

Open [http://localhost:8000/taxonomy/](http://localhost:8000/taxonomy/) in your browser.

---

## Celery (Background Tasks)

TaxonSampler uses **Celery** with **Redis** as the message broker for long-running operations like NCBI genome synchronization, species discovery, and batch sampling.

### Start the Celery worker

```bash
cd taxbridge
celery -A config worker -l info
```

To also process the dedicated NCBI sync queue:

```bash
celery -A config worker -l info -Q default,ncbi_sync
```

### Start the Celery Beat scheduler

Beat triggers scheduled tasks automatically (daily NCBI sync, weekly discovery, etc.):

```bash
celery -A config beat -l info
```

### Run worker + beat together (development only)

```bash
celery -A config worker -B -l info -Q default,ncbi_sync
```

### Monitor tasks (optional)

```bash
# Install Flower for a web-based monitor
pip install flower
celery -A config flower --port=5555
```

Then open [http://localhost:5555](http://localhost:5555) to monitor task queues.

### Scheduled Tasks

| Task | Schedule | Queue | Description |
|---|---|---|---|
| `sync_ncbi_genomes` | Daily at 3:00 AM | `ncbi_sync` | Sync genome metadata from NCBI Datasets API |
| `cleanup_old_sync_runs` | Weekly (Sun 4:00 AM) | `default` | Remove old synchronization records |
| `discover_new_species` | Weekly (Mon 5:00 AM) | `ncbi_sync` | Discover new species in NCBI not yet in the database |

### Celery configuration reference

All Celery settings are in `config/settings/base.py`:

| Setting | Default | Description |
|---|---|---|
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis broker URL |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Where task results are stored |
| `CELERY_TASK_TIME_LIMIT` | `3600` (1 hour) | Max execution time per task |
| `CELERY_TASK_DEFAULT_QUEUE` | `default` | Default queue name |

---

## Management Commands

Custom Django commands for data import and synchronization:

```bash
cd taxbridge

# Sync genomes from NCBI Datasets API
python manage.py sync_ncbi

# Match NCBI taxa to COL and create crosswalk entries
python manage.py match_ncbi_to_col

# Sync NCBI taxa with Catalogue of Life
python manage.py sync_col_matches

# Import NCBI taxa from an XLSX file
python manage.py import_ncbi_from_xlsx <file.xlsx>

# Import genome data from XLSX
python manage.py import_genomes_from_xlsx <file.xlsx>

# Import genome data from research XLSX files and match with COL
python manage.py import_research_genomes <file.xlsx>

# Count species in both NCBI and COL databases
python manage.py count_species
```

---

## Useful Development Commands

```bash
cd taxbridge

# Django shell (interactive Python with project context)
python manage.py shell

# Run tests
python manage.py test

# Create new migrations after model changes
python manage.py makemigrations

# Apply pending migrations
python manage.py migrate

# Check for deployment issues
python manage.py check --deploy
```

---

## Git Workflow

```bash
# Check current branch
git rev-parse --abbrev-ref HEAD

# View changed files
git status --short

# Stage all changes
git add -A

# Commit
git commit -m "Short description of the change"

# Push current branch
git push origin HEAD

# Create a new feature branch
git checkout -b feature/branch-name
```

---

## Frontend Notes

- Static assets live in `taxbridge/apps/taxonomy/static/taxonomy/` (CSS, JS, images).
- JavaScript uses **ES Modules** — files are in `static/taxonomy/js/`.
- After modifying JS/CSS, run `python manage.py collectstatic --noinput` before deploying.
- Hard-refresh the browser with **Ctrl+Shift+R** to bypass cache during development.

---

## License

This project is developed as part of academic research. Contact the repository maintainers for usage terms.
