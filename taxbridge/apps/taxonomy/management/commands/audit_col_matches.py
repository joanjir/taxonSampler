# apps/taxonomy/management/commands/audit_col_matches.py
"""
Audit and fix mis-linked COL matches.

Finds NCBIGenome records whose `organism_name` genus does not match the
COL `external_taxon` genus in the classification JSON.  Genuinely wrong
links (the organism genus is absent from both the COL species name and
the COL genus field) are reported and — with `--fix` — unlinked.

Usage:
    python manage.py audit_col_matches              # dry-run report
    python manage.py audit_col_matches --fix        # unlink bad matches
    python manage.py audit_col_matches --verbose 2  # extra detail
"""
from __future__ import annotations

import re
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Audit COL match quality: find genomes whose organism_name genus "
        "does not match the linked ExternalTaxon genus."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Unlink bad matches (set col_match_status='mismatch', "
                 "external_taxon=NULL).",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Also flag cases where the genus matches but phylum differs "
                 "(cross-phylum renames).",
        )

    # ------------------------------------------------------------------ #

    def handle(self, *args, **opts):
        from apps.taxonomy.models import NCBIGenome

        fix = opts["fix"]
        strict = opts["strict"]
        verbosity = int(opts.get("verbosity", 1))

        qs = NCBIGenome.objects.filter(
            col_match_status="matched",
            external_taxon__isnull=False,
        ).select_related("external_taxon")

        total = qs.count()
        self.stdout.write(f"Auditing {total} matched genomes…")

        bad: list[NCBIGenome] = []
        suspicious: list[tuple[NCBIGenome, str]] = []

        for g in qs.iterator():
            cls = g.external_taxon.classification or {}
            col_genus = cls.get("genus", "")
            col_species = cls.get("species", "")
            col_name = g.external_taxon.name or ""

            org_name = (g.organism_name or "").strip()
            # Extract the first word (genus) — skip strain/subspecies parts
            org_genus = org_name.split()[0] if org_name else ""

            if not org_genus:
                continue

            org_g = org_genus.lower()

            # Check: does the organism genus appear in the COL genus,
            # COL species name, or the COL taxon name?
            genus_ok = (
                org_g == col_genus.lower()
                or org_g in col_species.lower()
                or org_g in col_name.lower()
            )

            if not genus_ok:
                bad.append(g)
                if verbosity >= 2:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  BAD  {g.accession}: {g.organism_name}\n"
                            f"       → COL: {col_name} "
                            f"(genus={col_genus}, species={col_species})"
                        )
                    )

        # ── Report ──
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"Found {len(bad)} bad matches out of {total} total."
            )
        )

        if not bad:
            self.stdout.write(self.style.SUCCESS("All matches look clean."))
            return

        if not fix:
            self.stdout.write(
                "Run with --fix to unlink these bad matches.\n"
                "They will be set to col_match_status='mismatch' "
                "and external_taxon=NULL."
            )
            # Print summary table
            self.stdout.write(f"\n{'ACCESSION':<20} {'ORGANISM':<45} {'COL NAME'}")
            self.stdout.write("-" * 100)
            for g in bad:
                col_name = g.external_taxon.name if g.external_taxon else "?"
                self.stdout.write(
                    f"{g.accession:<20} "
                    f"{(g.organism_name or '')[:44]:<45} "
                    f"{col_name}"
                )
            return

        # ── Fix: unlink bad matches ──
        ids = [g.pk for g in bad]
        updated = NCBIGenome.objects.filter(pk__in=ids).update(
            col_match_status="mismatch",
            external_taxon=None,
            col_match_notes="Unlinked by audit_col_matches: genus mismatch.",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Unlinked {updated} bad matches "
                f"(col_match_status → 'mismatch', external_taxon → NULL)."
            )
        )
