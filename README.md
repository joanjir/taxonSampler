# TaxonSampler

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Django 6.0](https://img.shields.io/badge/django-6.0-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

## Overview

**TaxonSampler** is an open-source web-based platform for integrating, exploring, and sampling taxonomic and genomic data across the tree of life. It reconciles species records from the [Catalogue of Life (COL)](https://www.catalogueoflife.org/) with genome assembly metadata from the [NCBI Datasets API](https://www.ncbi.nlm.nih.gov/datasets/), enabling researchers to systematically select representative species for comparative genomics, phylogenomics, and biodiversity studies.

The tool addresses a common bottleneck in large-scale genomic analyses: the manual and error-prone process of selecting species with available genome assemblies that meet specific quality criteria, while ensuring taxonomic representativeness across clades of interest.

## Motivation

Comparative genomic studies often require selecting a representative subset of species from large taxonomic groups. This selection must balance two objectives: (1) adequate genome quality (assembly level, contiguity, annotation status) and (2) broad taxonomic coverage. TaxonSampler automates this process by providing an interactive interface where researchers can:

- Navigate the taxonomic hierarchy and select clades of interest.
- Define genome-quality filters (e.g., minimum assembly level, contig N50 thresholds).
- Execute sampling strategies that maximize taxonomic diversity within the selected scope.
- Export curated species lists in multiple formats for downstream analyses.

## Features

- **Taxonomic integration.** Imports and reconciles species records from COL/ChecklistBank with NCBI taxonomy, maintaining full classification paths from domain to species level.
- **Genome metadata synchronization.** Automated retrieval of genome assembly metadata from the NCBI Datasets API, including assembly level, contig N50, scaffold count, genome size, and annotation status.
- **Interactive taxonomy visualization.** D3.js-powered hierarchical display with collapsible nodes, breadcrumb navigation, clade search, and real-time species counts.
- **Configurable sampling wizard.** Three-step wizard that allows scope selection (full taxonomy or specific clade), genome-quality filtering with dual-range sliders, and sampling execution.
- **Manual taxonomy curation.** Supports manual addition and editing of species records when COL data is incomplete, with automatic merging into the existing taxonomic hierarchy.
- **Multi-format export.** Results can be exported as JSON, plain text, Newick (via ETE3), or Excel (XLSX).
- **Asynchronous task processing.** Long-running operations (NCBI sync, batch sampling, species discovery) are executed via Celery workers with Redis as the message broker.
- **Dashboard.** Summary view of species counts, genome coverage statistics, synchronization status, and recent activity.

## System Architecture

### Technology stack

| Component | Technology | Version |
|---|---|---|
| Backend framework | Django, Django REST Framework | 6.0, 3.16 |
| Language | Python | 3.13 |
| Task queue | Celery + Redis | 5.4 |
| Database | PostgreSQL | — |
| Frontend | Bootstrap 5 (Tabler), D3.js, ES Modules | 5.x, 5 |
| Phylogenetics | ETE3 | 3.1 |
| Spreadsheet I/O | openpyxl | 3.1 |

### Data model

The core data model centers on the reconciliation between NCBI and COL taxonomies:

```
┌──────────────┐        ┌──────────────────┐        ┌─────────────────────┐
│   Taxon      │        │  TaxonCrosswalk  │        │   ExternalTaxon     │
│   (NCBI)     │───────▶│                  │◀───────│   (COL / manual)    │
│              │        │  taxon_id (FK)   │        │                     │
│  taxid       │        │  external_id(FK) │        │  classification_path│
│  sci. name   │        │  match_method    │        │  classification     │
│  rank        │        │  confidence      │        │  system (col|manual)│
└──────┬───────┘        └──────────────────┘        └─────────────────────┘
       │
       ▼
┌──────────────┐
│  NCBIGenome  │
│              │
│  assembly_acc│
│  asm_level   │
│  contig_n50  │
│  genome_size │
│  annotation  │
└──────────────┘
```

Additional models:

- **`NCBISyncRun`**, **`TaxonSyncRun`**, **`DiscoveryRun`**: audit trail for synchronization and discovery operations.
- **`SamplingRun`**, **`ResolutionRun`**, **`ResolutionItem`**: records of sampling operations, parameters, and results.
- **`SamplingConfiguration`**: saved presets for reusable sampling configurations.

### Taxonomy tree construction

The taxonomic hierarchy is built using a **trie-based algorithm** (`ExternalTaxonManager.build_tree()`). COL species are inserted first using their leaf-to-root classification paths; manual species are then merged by resolving intermediate nodes against the existing trie, preventing duplicate branches when the manual classification omits ranks present in the COL hierarchy (e.g., `infraphylum`, `parvphylum`, `megaclass`).

### Directory structure

```
taxbridge/                         # Django project root
├── manage.py
├── config/
│   ├── settings/
│   │   ├── base.py                # Shared settings (DB, Celery, APIs)
│   │   ├── local.py               # Development overrides
│   │   └── prod.py                # Production settings
│   ├── celery.py                  # Celery application configuration
│   ├── urls.py                    # Root URL routing
│   └── wsgi.py / asgi.py
├── apps/
│   └── taxonomy/                  # Core application
│       ├── models/
│       │   ├── core.py            # Taxon, ExternalTaxon, TaxonCrosswalk
│       │   ├── genome.py          # NCBIGenome
│       │   ├── sync.py            # Sync and discovery run models
│       │   └── sampling.py        # Sampling models
│       ├── managers.py            # Trie-based tree builder
│       ├── ncbi/
│       │   ├── service.py         # NCBI Datasets API client
│       │   ├── tasks.py           # Celery tasks
│       │   └── views.py           # NCBI-related endpoints
│       ├── sampling/
│       │   ├── service.py         # Sampling orchestration
│       │   ├── assembly_engine.py # Assembly-level filtering
│       │   └── db_engine.py       # Database-level sampling
│       ├── api/                   # REST API
│       ├── dashboard/             # Dashboard views
│       ├── tree/                  # Visualization logic & filters
│       ├── management/commands/   # CLI commands
│       ├── templates/             # HTML (Tabler/Bootstrap)
│       └── static/taxonomy/       # CSS, JS, images
└── requirements.txt
```

## Installation

### Prerequisites

- Python ≥ 3.13
- PostgreSQL ≥ 14
- Redis ≥ 7.0

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd ProyectoNCBI_COL

# Create and activate a virtual environment
python -m venv .venv
# Windows PowerShell:
& .\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the `taxbridge/` directory with the following variables:

```env
DJANGO_SECRET_KEY=<secret-key>
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://<user>:<password>@localhost:5432/taxonsampler
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
NCBI_API_KEY=<your-ncbi-api-key>
```

An NCBI API key can be obtained at [https://www.ncbi.nlm.nih.gov/account/settings/](https://www.ncbi.nlm.nih.gov/account/settings/).

### Database initialization

```bash
cd taxbridge
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

### Running the application

```bash
python manage.py runserver 0.0.0.0:8000
```

The application will be available at `http://localhost:8000/taxonomy/`.

## Usage

### Data import and synchronization

TaxonSampler provides management commands for populating the database:

| Command | Description |
|---|---|
| `python manage.py sync_ncbi` | Sync genome assemblies from the NCBI Datasets API |
| `python manage.py match_ncbi_to_col` | Match NCBI taxa to COL records and create crosswalk entries |
| `python manage.py sync_col_matches` | Synchronize NCBI taxa with the Catalogue of Life |
| `python manage.py import_ncbi_from_xlsx <file>` | Import NCBI taxa from an XLSX spreadsheet |
| `python manage.py import_genomes_from_xlsx <file>` | Import genome records from an XLSX file |
| `python manage.py import_research_genomes <file>` | Import research genome data and match with COL |
| `python manage.py count_species` | Report species counts in both NCBI and COL databases |

### Celery task queue

Long-running operations are processed asynchronously via Celery. A Redis instance must be running.

```bash
# Start the Celery worker (processes both default and NCBI sync queues)
celery -A config worker -l info -Q default,ncbi_sync

# Start the Celery Beat scheduler (triggers periodic tasks)
celery -A config beat -l info

# Combined worker + scheduler (development only)
celery -A config worker -B -l info -Q default,ncbi_sync
```

**Scheduled tasks:**

| Task | Schedule | Queue | Description |
|---|---|---|---|
| `sync_ncbi_genomes` | Daily, 03:00 | `ncbi_sync` | Fetch updated genome metadata from NCBI |
| `cleanup_old_sync_runs` | Weekly, Sun 04:00 | `default` | Purge old synchronization records |
| `discover_new_species` | Weekly, Mon 05:00 | `ncbi_sync` | Discover species in NCBI absent from the local database |

**Task monitoring (optional):**

```bash
pip install flower
celery -A config flower --port=5555
# Open http://localhost:5555
```

### Sampling workflow

1. **Select scope.** Choose the entire taxonomy or click a specific clade node in the visualization.
2. **Configure filters.** Adjust genome-quality thresholds using dual-range sliders (assembly level, contig N50, genome size, etc.).
3. **Execute sampling.** Run the sampling engine. Results are displayed in the selection panel and can be exported.

### Export formats

Sampled species lists can be exported as:

- **JSON** — structured data with full metadata.
- **TXT** — plain-text species list.
- **Newick** — phylogenetic tree format (generated via ETE3).
- **XLSX** — Excel spreadsheet with genome metadata columns.

## Development

```bash
cd taxbridge

# Run the test suite
python manage.py test

# Open an interactive Django shell
python manage.py shell

# Create migrations after model changes
python manage.py makemigrations

# Apply pending migrations
python manage.py migrate

# Validate deployment readiness
python manage.py check --deploy
```

### Git workflow

```bash
git checkout -b feature/<name>    # Create a feature branch
git add -A                        # Stage changes
git commit -m "<message>"         # Commit
git push origin HEAD              # Push to remote
```

### Frontend development

- Static assets are located in `taxbridge/apps/taxonomy/static/taxonomy/`.
- JavaScript files use ES Modules (`import`/`export`).
- After modifying static files, run `python manage.py collectstatic --noinput`.
- Use `Ctrl+Shift+R` in the browser to bypass cache during development.

## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request. Ensure that all tests pass and that new functionality includes appropriate test coverage.

## License

This project is released under the [MIT License](LICENSE).

## Citation

If you use TaxonSampler in your research, please cite:

```bibtex
@software{taxonsampler2026,
  author       = {Joan Jiménez},
  title        = {{TaxonSampler}: A web platform for taxonomic sampling
                  and genome data integration},
  year         = {2026},
  url          = {https://github.com/<user>/TaxonSampler}
}
```

## Contact

For questions, bug reports, or feature requests, please open an issue on the repository or contact the maintainers directly.
