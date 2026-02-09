# taxbridge/taxonomy/management/commands/match_ncbi_to_col.py
from __future__ import annotations

#from curses import raw
from os import system
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.taxonomy.models import ExternalTaxon, Taxon, TaxonCrosswalk
from apps.taxonomy.services.checklistbank import ChecklistBankClient, canonicalize_scientific_name


class Command(BaseCommand):
    help = "Machea Taxon (NCBI) a ExternalTaxon (CoL/ChecklistBank) y crea TaxonCrosswalk."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="COL25.12", help="Dataset ChecklistBank, ej: COL25.12 o 3LR")
        parser.add_argument("--system", default="col", help="Etiqueta de sistema para ExternalTaxon.system")
        parser.add_argument("--rank", default=None, help="Filtra Taxon.rank (ej: species)")
        parser.add_argument("--limit", type=int, default=0, help="Limitar cantidad de Taxon a procesar (0 = sin límite)")
        parser.add_argument("--taxids", nargs="*", type=int, default=None, help="Procesa solo estos taxids")
        parser.add_argument("--kingdom", default="Animalia", help="Filtro kingdom para match/nameusage")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en DB, solo muestra acciones")

    def handle(self, *args, **opts):
        dataset = opts["dataset"]
        system = opts["system"]
        rank_filter = opts["rank"]
        limit = opts["limit"]
        taxids = opts["taxids"] or []
        kingdom = opts["kingdom"]
        dry = opts["dry_run"]
        verbosity = int(opts.get("verbosity", 1))

        client = ChecklistBankClient()

        qs = Taxon.objects.all().order_by("taxid")
        if rank_filter:
            qs = qs.filter(rank__iexact=rank_filter)
        if taxids:
            qs = qs.filter(taxid__in=taxids)
        if limit and limit > 0:
            qs = qs[:limit]

        if not qs.exists():
            raise CommandError("No hay Taxon para procesar con esos filtros.")

        n_total = qs.count()
        n_high = n_review = n_nomatch = 0

        self.stdout.write(f"==> Dataset: {dataset}")
        self.stdout.write(f"==> Taxa   : {n_total}")
        self.stdout.write(f"==> DryRun : {dry}")

        for t in qs.iterator(chunk_size=500):
            qname = canonicalize_scientific_name(t.scientific_name)

            m = client.match_nameusage(
                dataset=dataset,
                scientific_name=qname,
                rank=t.rank,
                kingdom=kingdom,
            )

            # ------------------------------------------------------------
            # FIX CRÍTICO:
            # ChecklistBank puede responder "no match" pero tu client igual
            # construye un objeto m con external_id=None.
            # En ese caso NO se debe insertar ExternalTaxon.
            # ------------------------------------------------------------
            ext_id = getattr(m, "external_id", None) if m is not None else None
            if not m or not ext_id:
                n_nomatch += 1
                if verbosity >= 2:
                    # intenta dejar evidencia mínima sin romper si m.raw no existe
                    raw = getattr(m, "raw", None) if m is not None else None
                    hint = ""
                    if isinstance(raw, dict):
                        hint = f" type={raw.get('type')} match={raw.get('match')}"
                    self.stdout.write(f"[NO_MATCH] taxid={t.taxid} name={t.scientific_name}{hint}")
                continue

            # A partir de aquí ya hay external_id real
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
