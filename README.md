# TaxonSampler

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Django 6.0](https://img.shields.io/badge/django-6.0-green.svg)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-336791.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

**TaxonSampler** is an open-source web platform that integrates taxonomic classifications from the [Catalogue of Life (COL)](https://www.catalogueoflife.org/) with genome assembly metadata from the [NCBI Datasets API](https://www.ncbi.nlm.nih.gov/datasets/).

---

## Features

| Feature | Description |
|---------|-------------|
| **Taxonomic Integration** | Imports and reconciles species from COL/ChecklistBank with NCBI taxonomy (26+ ranks) |
| **Genome Metadata** | Assembly level, contig N50, scaffold count, genome size, GC content, annotation status |
| **Interactive Visualization** | D3.js hierarchical tree with breadcrumb navigation, search, and zoom/pan |
| **Sampling Wizard** | Three-step workflow: scope selection → quality filters → export |
| **Multi-format Export** | JSON, TXT, Newick (ETE3), or XLSX with genome metadata |
| **Background Processing** | Celery + Redis for async NCBI sync and batch sampling |

---

## Documentation & Tutorials

📚 **Tutorials available at:** `/taxonomy/tutorials/`

The application includes built-in documentation accessible from the **About & Tutorials** link in the sidebar:

| Tutorial | Description | Level |
|----------|-------------|-------|
| Getting Started | Navigation basics and interface overview | Beginner |
| Basic Quality Filtering | Filter genomes by assembly level and N50 | Beginner |
| Representative Sampling | Select N species per taxonomic group | Intermediate |
| Quality-First Strategy | Rank genomes by weighted quality score | Intermediate |
| Broad Coverage | Maximize phylogenetic diversity | Advanced |
| Research Workflow | Complete use case example (Coleoptera) | Advanced |

### File Locations

- **Templates:** `taxbridge/apps/taxonomy/templates/taxonomy/pages/`
  - `about.html` — Software information and methodology
  - `tutorials.html` — Step-by-step sampling guides (accordion layout)
  - `report_issue.html` — GitHub issue wizard
- **CSS:** `taxbridge/apps/taxonomy/static/taxonomy/css/`
  - `about.css` — About and tutorials styles
  - `report-issue.css` — Issue wizard styles
  - `tree.css` — Taxonomy tree visualization

---

## Quick Start

### Prerequisites

- Python ≥ 3.13
- PostgreSQL ≥ 14
- Redis ≥ 7.0

### Installation

```bash
# Clone and setup
git clone https://github.com/joanjir/taxonSampler.git
cd taxonSampler

# Virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate      # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create `taxbridge/.env`:

```env
DJANGO_SECRET_KEY=<secret-key>
DJANGO_DEBUG=True
DATABASE_URL=postgres://user:pass@localhost:5432/taxonsampler
CELERY_BROKER_URL=redis://localhost:6379/0
NCBI_API_KEY=<your-ncbi-api-key>
```

> Get a free NCBI API key at [ncbi.nlm.nih.gov/account/settings](https://www.ncbi.nlm.nih.gov/account/settings/)

### Database Setup

```bash
cd taxbridge
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

### Run

```bash
python manage.py runserver 0.0.0.0:8000
```

Open `http://localhost:8000/taxonomy/`

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Django 6.0, Django REST Framework |
| Language | Python 3.13 |
| Task Queue | Celery 5.4 + Redis |
| Database | PostgreSQL |
| Frontend | Tabler (Bootstrap 5), D3.js v5 |
| Phylogenetics | ETE3 |
| Spreadsheet | openpyxl |
| Markdown | Markdown 3.7 + bleach 6.3 |

---

## Project Structure

```
taxbridge/
├── apps/taxonomy/           # Core application
│   ├── models/              # Taxon, ExternalTaxon, NCBIGenome
│   ├── ncbi/                # NCBI API integration
│   ├── sampling/            # Sampling engine
│   ├── tree/                # Visualization logic
│   ├── api/                 # REST endpoints
│   ├── templates/           # HTML templates
│   └── static/taxonomy/     # CSS, JS, images
├── config/                  # Django settings
└── requirements.txt
```

---

## Data Import

```bash
cd taxbridge

# Import NCBI taxa and genomes
python manage.py import_ncbi_from_xlsx <file>
python manage.py import_genomes_from_xlsx <file>

# Match with COL
python manage.py match_ncbi_to_col

# Sync genome metadata
python manage.py sync_ncbi
```

---

## Celery Workers

```bash
cd taxbridge

# Start worker
celery -A config worker -l info -Q default,ncbi_sync

# Start scheduler (periodic tasks)
celery -A config beat -l info
```

---

## Citation

```bibtex
@software{taxonsampler2026,
  author  = {Izquerdo, Joan},
  title   = {{TaxonSampler}: A web platform for taxonomic sampling
             and genome data integration},
  year    = {2026},
  url     = {https://github.com/joanjir/taxonSampler}
}
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
