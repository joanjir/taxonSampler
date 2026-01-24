from __future__ import annotations

from pathlib import Path
import openpyxl

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taxonomy.models import Taxon
from taxonomy.services.ncbi_taxonomy import resolve_name_to_taxon


class Command(BaseCommand):
    help = "Importa taxones NCBI desde un archivo XLSX (columna Organism)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=r"C:\Users\joanj\Documents\ProyectoNCBI_COL\taxbridge\data\metazoa_genomes_taxonomy.xlsx",
            help="Ruta al XLSX",
        )
        parser.add_argument("--sheet", default="Sheet1", help="Nombre de la hoja (default: Sheet1)")
        parser.add_argument("--name_col", default="Organism", help="Nombre de la columna con el organismo")

        # Límite de lectura (filas), útil para test.
        parser.add_argument("--limit", type=int, default=0, help="0 = sin límite (filas a leer)")

        # Límite de NUEVOS reales (no existentes en DB). Esto es lo que tú necesitas.
        parser.add_argument("--max-new", type=int, default=0, help="0 = sin límite (nuevos taxones a insertar)")

        # Por defecto NO actualiza registros existentes (conservador).
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Si se activa, actualiza registros existentes; si no, los omite (skip).",
        )

        parser.add_argument("--dry-run", action="store_true", help="No escribe en DB, solo reporta.")
        parser.add_argument("--log-file", default="", help="Opcional: ruta a archivo .log para guardar el reporte.")

    def handle(self, *args, **opts):
        xlsx = Path(opts["file"])
        if not xlsx.exists():
            raise CommandError(f"No existe el archivo: {xlsx}")

        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)

        sheet_name = opts["sheet"]
        if sheet_name not in wb.sheetnames:
            raise CommandError(f"La hoja '{sheet_name}' no existe. Disponibles: {wb.sheetnames}")

        ws = wb[sheet_name]

        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not header_row:
            raise CommandError("La hoja está vacía (no hay encabezado).")

        header = [str(x).strip() if x is not None else "" for x in header_row]
        col_name = opts["name_col"]
        if col_name not in header:
            raise CommandError(f"No encontré la columna '{col_name}'. Encabezados: {header}")

        idx = header.index(col_name)

        limit_rows = int(opts["limit"] or 0)
        max_new = int(opts["max_new"] or 0)
        dry = bool(opts["dry_run"])
        update_existing = bool(opts["update_existing"])
        log_path = (Path(opts["log_file"]) if opts["log_file"] else None)

        def log(line: str):
            self.stdout.write(line)
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")

        log(f"==> XLSX     : {xlsx}")
        log(f"==> Sheet    : {sheet_name}")
        log(f"==> Column   : {col_name}")
        log(f"==> limit    : {limit_rows} (filas leídas; 0=sin límite)")
        log(f"==> max-new  : {max_new} (nuevos reales; 0=sin límite)")
        log(f"==> update   : {update_existing}")
        log(f"==> dry-run  : {dry}")
        if log_path:
            log(f"==> log-file : {log_path}")

        # 1) leer nombres (mantener orden, evitando duplicados de archivo)
        seen = set()
        names = []

        read_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if limit_rows and read_rows >= limit_rows:
                break
            read_rows += 1

            cell = row[idx] if idx < len(row) else None
            if cell is None:
                continue
            name = str(cell).strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            names.append(name)

        log(f"==> Nombres únicos leídos: {len(names)}")

        # 2) procesar incrementalmente: resolver -> decidir acción -> escribir/contar
        created = updated = skipped = nomatch = 0
        inserted_new = 0

        # transacción única (más rápido y consistente)
        with transaction.atomic():
            for name in names:
                # stop si ya llegaste a los NUEVOS reales que querías
                if max_new and inserted_new >= max_new:
                    log(f"[STOP] alcanzado max-new={max_new}")
                    break

                # si ya existe y no quieres update, saltas sin llamar NCBI (optimiza)
                # OJO: esto solo funciona si el nombre en DB coincide; mejor check por taxid,
                # pero aún no lo tienes. Aquí hacemos check conservador por nombre exacto.
                # De todas formas resolver_name_to_taxon te dará taxid real.
                rec = resolve_name_to_taxon(name)
                if not rec:
                    nomatch += 1
                    log(f"[NO_MATCH] {name}")
                    continue

                taxid = int(rec.taxid)

                obj = Taxon.objects.filter(taxid=taxid).first()
                if obj and not update_existing:
                    skipped += 1
                    log(f"[SKIP_EXISTING] taxid={taxid} name='{rec.scientific_name}'")
                    continue

                defaults = dict(
                    scientific_name=rec.scientific_name,
                    rank=rec.rank,
                    parent_taxid=rec.parent_taxid,
                    lineage=rec.lineage,
                    raw=rec.raw,
                )

                if obj is None:
                    if dry:
                        created += 1
                        inserted_new += 1
                        log(f"[DRY CREATE] taxid={taxid} name='{rec.scientific_name}' rank={rec.rank}")
                    else:
                        Taxon.objects.create(taxid=taxid, **defaults)
                        created += 1
                        inserted_new += 1
                        log(f"[CREATE] taxid={taxid} name='{rec.scientific_name}' rank={rec.rank}")
                else:
                    if dry:
                        updated += 1
                        log(f"[DRY UPDATE] taxid={taxid} name='{rec.scientific_name}' rank={rec.rank}")
                    else:
                        Taxon.objects.filter(taxid=taxid).update(**defaults)
                        updated += 1
                        log(f"[UPDATE] taxid={taxid} name='{rec.scientific_name}' rank={rec.rank}")

        log("==> RESUMEN")
        log(f"  created        : {created}")
        log(f"  updated        : {updated}")
        log(f"  skipped        : {skipped}")
        log(f"  no_match       : {nomatch}")
        log(f"  inserted_new   : {inserted_new}")

        if dry:
            log("==> DRY-RUN: no se escribió nada.")
        else:
            log(self.style.SUCCESS("Importación completada."))
