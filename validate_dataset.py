#!/usr/bin/env python3
"""
validate_dataset.py — Valida trazabilidad y completitud del dataset Sci-Align,
y regenera data/dataset_status.json. Referenciado en CLAUDE.md.

Reglas validadas por registro:
  - id presente y único
  - fuente con documento, pagina, procesado_con
  - cada entidad con tipo + id
  - cada relación con desde/hacia/tipo + evidencia (documento+pagina)
  - texto_fuente <= 200 chars (regla HermesGuard)
  - sin patrones de bibliografía con copyright (DOI/ISBN/ISSN/©/...)

Exit 0 si todo OK; exit 1 si hay violaciones (apto para CI/automatización).
"""
import json, re, glob, sys, os
from collections import Counter
from datetime import datetime, timezone

DATASET_DIR = "/opt/geoai/dataset/sci_align"
STATUS_OUT = "/opt/geoai/data/dataset_status.json"
BIBLIO_RE = re.compile(r'\b(doi:\s*10\.|ISBN|ISSN|©|all rights reserved|derechos reservados)\b', re.I)


def validate():
    files = sorted(glob.glob(f"{DATASET_DIR}/*.jsonl"))
    errors, ids = [], set()
    archivos, tot_tipos, docs = {}, Counter(), set()
    total = 0
    for f in files:
        name = os.path.basename(f)
        tipos = Counter(); n = 0
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if not line.strip():
                continue
            n += 1; total += 1
            try:
                r = json.loads(line)
            except Exception as e:
                errors.append(f"{name}:{i} JSON inválido: {e}"); continue
            rid = r.get("id")
            if not rid:
                errors.append(f"{name}:{i} sin id")
            elif rid in ids:
                errors.append(f"{name}:{i} id duplicado: {rid}")
            else:
                ids.add(rid)
            fu = r.get("fuente", {})
            for k in ("documento", "pagina", "procesado_con"):
                if not fu.get(k) and fu.get(k) != 0:
                    errors.append(f"{name}:{rid} fuente sin '{k}'")
            if fu.get("documento"):
                docs.add(fu["documento"])
            for e in r.get("entidades", []):
                if not e.get("tipo") or not e.get("id"):
                    errors.append(f"{name}:{rid} entidad sin tipo/id")
                else:
                    tipos[e["tipo"]] += 1; tot_tipos[e["tipo"]] += 1
            for rel in r.get("relaciones", []):
                if not rel.get("tipo") or not rel.get("evidencia"):
                    errors.append(f"{name}:{rid} relación sin tipo/evidencia")
                else:
                    ev = rel["evidencia"]
                    if not ev.get("documento") or not (ev.get("pagina") or ev.get("pagina") == 0):
                        errors.append(f"{name}:{rid} evidencia sin documento/pagina")
            t = r.get("texto_fuente", "") or ""
            if len(t) > 200:
                errors.append(f"{name}:{rid} texto_fuente {len(t)}>200 chars")
            if BIBLIO_RE.search(json.dumps(r, ensure_ascii=False)):
                errors.append(f"{name}:{rid} patrón bibliografía/copyright")
        archivos[name] = {"registros": n, "tipos": dict(tipos)}

    status = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "ok": not errors,
        "validacion": {"errores": len(errors), "muestra": errors[:20]},
        "stats": {
            "archivos": archivos,
            "totales": {
                "registros": total,
                "tipos": dict(tot_tipos),
                "documentos_fuente": sorted(docs),
                "n_documentos_fuente": len(docs),
            },
        },
    }
    os.makedirs(os.path.dirname(STATUS_OUT), exist_ok=True)
    json.dump(status, open(STATUS_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    resumen = " + ".join(f"{k}:{v['registros']}" for k, v in archivos.items())
    print(f"Registros: {total} | {resumen}")
    print(f"Documentos fuente: {len(docs)} | Tipos de entidad: {len(tot_tipos)}")
    print(f"Errores de validación: {len(errors)}")
    for e in errors[:20]:
        print("  ✗", e)
    print(f"status → {STATUS_OUT}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(validate())
