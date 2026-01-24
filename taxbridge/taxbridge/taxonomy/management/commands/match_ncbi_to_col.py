# taxbridge/taxonomy/management/commands/match_ncbi_to_col.py
from __future__ import annotations

from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taxonomy.models import ExternalTaxon, Taxon, TaxonCrosswalk
from taxonomy.services.checklistbank import ChecklistBankClient, canonicalize_scientific_name


class Command(BaseCommand):
    help = "Machea Taxon (NCBI) a ExternalTaxon (CoL/ChecklistBank) y crea TaxonCrosswalk."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="COL25.12", help="Dataset ChecklistBank (ej: COL25.12, 3LR)")
        parser.add_argument("--system", default="col", help="Etiqueta ExternalTaxon.system")
        parser.add_argument("--rank", default=None, help="Filtra Taxon.rank (ej: species)")
        parser.add_argument("--limit", type=int, default=0, help="0 = sin límite")
        parser.add_argument("--taxids", nargs="*", type=int, default=None, help="Procesa solo estos taxids")
        parser.add_argument("--kingdom", default="Animalia", help="Filtro kingdom para desambiguar")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en DB")

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

            if not m.matched or not m.external_id:
                n_nomatch += 1
                if verbosity >= 2:
                    raw = m.raw if isinstance(m.raw, dict) else {}
                    self.stdout.write(
                        f"[NO_MATCH] taxid={t.taxid} name={t.scientific_name} "
                        f"type={raw.get('type')} match={raw.get('match')}"
                    )
                continue

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
                    n_nomatch += 1
                    if verbosity >= 2:
                        self.stdout.write(f"[NO_MATCH] taxid={t.taxid} name={t.scientific_name} (upsert_external=None)")
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

    def _decide(self, t_rank: Optional[str], m_rank: Optional[str], m_status: Optional[str]):
        tr = (t_rank or "").strip().lower()
        mr = (m_rank or "").strip().lower()
        st = (m_status or "").strip().lower()

        if st == "accepted" and tr and mr and tr == mr:
            return ("high", "exact_rank", 1.0)

        if st == "accepted":
            return ("needs_review", "exact", 0.75)

        return ("needs_review", "exact", 0.60)

    def _upsert_external(self, system: str, dataset: str, m):
        """
            Guarda el match CoL en ExternalTaxon.

            - dataset_code: COL25.12, 3LR, etc.
            - external_id: usage.id de ChecklistBank
        """
        if m is None or not getattr(m, "external_id", None):
            return None

        raw = dict(getattr(m, "raw", {}) or {})
        raw["dataset"] = dataset  # auditoría

        ext, _ = ExternalTaxon.objects.update_or_create(
            system=system,
            dataset_code=str(dataset),
            external_id=str(m.external_id),
            defaults=dict(
            name=m.name or "",
            rank=m.rank or "",
            status=m.status or "",
            classification=getattr(m, "classification", {}) or {},
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
                    "status": m.status,
                    "rank_ncbi": (t.rank or ""),
                    "rank_col": (m.rank or ""),
                },
            ),
        )
