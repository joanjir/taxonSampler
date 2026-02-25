# taxbridge/taxonomy/management/commands/match_ncbi_to_col.py
from __future__ import annotations

#from curses import raw
from os import system
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.taxonomy.models import ExternalTaxon, NCBIGenome, Taxon, TaxonCrosswalk
from apps.taxonomy.ncbi.clients import ChecklistBankClient, canonicalize_scientific_name


class Command(BaseCommand):
    help = "Match Taxon (NCBI) to ExternalTaxon (CoL/ChecklistBank) and create TaxonCrosswalk. Optionally fetch NCBI genome data."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="COL25.12", help="ChecklistBank Dataset, e.g., COL25.12 or 3LR")
        parser.add_argument("--system", default="col", help="tag system for ExternalTaxon.system")
        parser.add_argument("--rank", default=None, help="Filter Taxon.rank (e.g., species)")
        parser.add_argument("--limit", type=int, default=0, help="Limit number of Taxon to process (0 = no limit)")
        parser.add_argument("--taxids", nargs="*", type=int, default=None, help="Process only these taxids")
        parser.add_argument("--kingdom", default="Animalia", help="Filter kingdom for match/nameusage")
        parser.add_argument("--dry-run", action="store_true", help="Do not write to DB, only show actions")
        # New arguments for NCBI genomes
        parser.add_argument("--fetch-genomes", action="store_true", help="Fetch NCBI genome information")
        parser.add_argument("--check-proteomes", action="store_true", help="Check proteomes (slower)")

    def handle(self, *args, **opts):
        dataset = opts["dataset"]
        system = opts["system"]
        rank_filter = opts["rank"]
        limit = opts["limit"]
        taxids = opts["taxids"] or []
        kingdom = opts["kingdom"]
        dry = opts["dry_run"]
        verbosity = int(opts.get("verbosity", 1))
        
        # Opciones de NCBI genomes
        fetch_genomes = opts["fetch_genomes"]
        check_proteomes = opts["check_proteomes"]

        client = ChecklistBankClient()

        qs = Taxon.objects.all().order_by("taxid")
        if rank_filter:
            qs = qs.filter(rank__iexact=rank_filter)
        if taxids:
            qs = qs.filter(taxid__in=taxids)
        if limit and limit > 0:
            qs = qs[:limit]

        if not qs.exists():
            raise CommandError("No Taxon to process with those filters.")

        n_total = qs.count()
        n_high = n_review = n_nomatch = 0
        n_genomes = 0  # Counter for genomes obtained

        self.stdout.write(f"==> Dataset: {dataset}")
        self.stdout.write(f"==> Taxa   : {n_total}")
        self.stdout.write(f"==> DryRun : {dry}")
        self.stdout.write(f"==> Fetch NCBI Genomes: {fetch_genomes}")
        if fetch_genomes:
            self.stdout.write(f"==> Check Proteomes: {check_proteomes}")

        for t in qs.iterator(chunk_size=500):
            qname = canonicalize_scientific_name(t.scientific_name)

            m = client.match_nameusage(
                dataset=dataset,
                scientific_name=qname,
                rank=t.rank,
                kingdom=kingdom,
            )

            # ------------------------------------------------------------
            # CRITICAL FIX:
            # ChecklistBank may respond "no match" but your client still
            # constructs an object m with external_id=None.
            # In that case, ExternalTaxon should NOT be inserted.
            # ------------------------------------------------------------
            ext_id = getattr(m, "external_id", None) if m is not None else None
            if not m or not ext_id:
                n_nomatch += 1
                if verbosity >= 2:
                    # attempt to leave minimal evidence without breaking if m.raw does not exist
                    raw = getattr(m, "raw", None) if m is not None else None
                    hint = ""
                    if isinstance(raw, dict):
                        hint = f" type={raw.get('type')} match={raw.get('match')}"
                    self.stdout.write(f"[NO_MATCH] taxid={t.taxid} name={t.scientific_name}{hint}")
                continue

            # From here on, there is a real external_id
            decision, method, score = self._decide(t_rank=t.rank, m_rank=m.rank, m_status=m.status)

            if dry:
                self.stdout.write(
                    f"[DRY] taxid={t.taxid} -> ext={m.external_id} ({m.name}) "
                    f"rank={m.rank} status={m.status} decision={decision}"
                )
                if decision == "high":
                    n_high += 1
                else:
                    n_review += 1
                continue

            with transaction.atomic():
                ext = self._upsert_external(system, dataset, m)
                if ext is None:
                    # Blindaje extra: si por alguna razón no se pudo upsert, cuenta como no_match
                    n_nomatch += 1
                    if verbosity >= 2:
                        self.stdout.write(f"[NO_MATCH] taxid={t.taxid} name={t.scientific_name} (upsert_external returned None)")
                    continue

                self._upsert_crosswalk(t, ext, qname, dataset, decision, method, score, m)

            # --- NEW: Fetch NCBI genomes ---
            if fetch_genomes:
                try:
                    genome_count = NCBIGenome.fetch_and_save(t, check_proteomes=check_proteomes)
                    n_genomes += genome_count
                    if verbosity >= 2 and genome_count > 0:
                        self.stdout.write(f"    [NCBI] {genome_count} genoma(s) guardado(s) para taxid={t.taxid}")
                except Exception as e:
                    if verbosity >= 1:
                        self.stdout.write(f"    [NCBI_ERROR] taxid={t.taxid}: {e}")

            if decision == "high":
                n_high += 1
            else:
                n_review += 1

            if verbosity >= 2:
                self.stdout.write(
                    f"[OK] taxid={t.taxid} -> {m.external_id} decision={decision} method={method} score={score}"
                )

        self.stdout.write("==> RESUMEN")
        self.stdout.write(f"  high        : {n_high}")
        self.stdout.write(f"  needs_review: {n_review}")
        self.stdout.write(f"  no_match    : {n_nomatch}")
        if fetch_genomes:
            self.stdout.write(f"  genomas NCBI: {n_genomes}")

    def _decide(self, t_rank: Optional[str], m_rank: Optional[str], m_status: str):
        tr = (t_rank or "").strip().lower()
        mr = (m_rank or "").strip().lower()
        st = (m_status or "").strip().lower()

        if st == "accepted" and tr and mr and tr == mr:
            return ("high", "exact_rank", 1.0)

        if st == "accepted":
            return ("needs_review", "exact", 0.75)

        return ("needs_review", "exact", 0.60)

    def _upsert_external(self, system: str, dataset: str, m):
        if m is None or not getattr(m, "external_id", None):
            return None

        raw = dict(getattr(m, "raw", {}) or {})
        raw["dataset"] = dataset

        ext, _ = ExternalTaxon.objects.update_or_create(
            system=system,
            dataset_code=dataset,
            external_id=str(m.external_id),
            defaults=dict(
            name=m.name or "",
            rank=m.rank or "",
            status=m.status or "",
            classification=getattr(m, "classification", {}) or {},  # dict derivado
            classification_path=getattr(m, "classification_path", []) or [],  # lista ordenada (la clave)
            parent_external_id=str(raw.get("usage", {}).get("parent") or ""),  # opcional (si quieres)
            raw=raw,
                ),
            )

        return ext

    def _upsert_crosswalk(
        self,
        t: Taxon,
        ext: ExternalTaxon,
        qname: str,
        dataset: str,
        decision: str,
        method: str,
        score: float,
        m,
    ):
        TaxonCrosswalk.objects.update_or_create(
            ncbi_taxon=t,
            external_taxon=ext,
            defaults=dict(
                score=score,
                decision=decision,
                method=method,
                is_active=True,
                curation_level="auto",
                evidence={
                    "query": qname,
                    "dataset": dataset,
                    "status": getattr(m, "status", None),
                    "rank_ncbi": (t.rank or ""),
                    "rank_col": (getattr(m, "rank", "") or ""),
                },
            ),
        )
