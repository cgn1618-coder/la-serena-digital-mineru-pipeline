#!/usr/bin/env python3
"""
build_submission_zip.py — Ensambla el ZIP de entrega para AGI4S / MDIC2026 Pista 1 (Sci-Align).

Idempotente y reutilizable: regenera el staging y el ZIP desde las fuentes canónicas.
Verifica compliance (texto_fuente <=200 chars, sin patrones de bibliografía/copyright)
ANTES de empaquetar; aborta si algo viola la regla HermesGuard.

Salida: dataset/submission/GeoAI_SciAlign_AGI4S_<fecha>.zip
"""
import json, os, re, glob, shutil, zipfile, time, hashlib, sys

ROOT = "/opt/geoai"
REPO = "/root/competition_mdic2026/github_repo"
COMP = "/root/competition_mdic2026"
DATE = time.strftime("%Y%m%d")
STAGE = f"{ROOT}/dataset/submission/GeoAI_SciAlign_AGI4S_{DATE}"
ZIP_OUT = f"{ROOT}/dataset/submission/GeoAI_SciAlign_AGI4S_{DATE}.zip"

# Gate de registros del dataset (texto_fuente verbatim).
BIBLIO_RE = re.compile(r'\b(doi:|https?://doi|et al\.|©|copyright|all rights reserved|ISBN|ISSN)\b', re.I)

# Guard de archivos: rechaza material con copyright fuerte (libros pirateados, etc.).
# NO bloquea el dataset Sci-Align (excerpts <=200 chars sin estos marcadores) ni docs públicos SEIA.
COPYRIGHT_FILE_RE = re.compile(
    r'(\bISBN\b|\bISSN\b|doi:\s*10\.|©|all rights reserved|derechos reservados|'
    r'prohibida su reproducci|z-?library|\b1lib\b)', re.I)
TEXT_EXT = {".md", ".txt", ".json", ".jsonl", ".tex", ".csv", ".py"}


def copyright_safe(path):
    """True si el archivo NO contiene marcadores de copyright fuerte. Binarios pasan."""
    if os.path.splitext(path)[1].lower() not in TEXT_EXT:
        return True
    if COPYRIGHT_FILE_RE.search(os.path.basename(path)):
        return False
    try:
        txt = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return True
    return COPYRIGHT_FILE_RE.search(txt) is None


def safe_copy(src, dst):
    """Copia solo si pasa el guard de copyright. Devuelve True/False y loguea si rechaza."""
    if not os.path.exists(src):
        return False
    if not copyright_safe(src):
        log(f"EXCLUIDO por copyright: {src}")
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def log(m): print(f"[build] {m}")


def compliance_gate(jsonl_files):
    """Gate duro: aborta si hay texto verbatim >200 chars o patrones de copyright."""
    bad_len, bad_biblio, n = [], [], 0
    for f in jsonl_files:
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            n += 1
            r = json.loads(line)
            t = r.get("texto_fuente", "") or ""
            if len(t) > 200:
                bad_len.append((r.get("id"), len(t)))
            if BIBLIO_RE.search(json.dumps(r, ensure_ascii=False)):
                bad_biblio.append(r.get("id"))
    log(f"compliance: {n} registros | >200chars: {len(bad_len)} | biblio/copyright: {len(bad_biblio)}")
    if bad_len or bad_biblio:
        log(f"ABORTO — violaciones: len={bad_len[:5]} biblio={bad_biblio[:5]}")
        sys.exit(1)
    return n


def sample_records(jsonl, k=10):
    out = []
    for line in open(jsonl, encoding="utf-8"):
        if line.strip():
            out.append(line.rstrip("\n"))
        if len(out) >= k:
            break
    return out


def trim_raw_sample(src, dst, k=60):
    """Copia una muestra recortada (primeros k elementos) de un content_list MinerU."""
    data = json.load(open(src, encoding="utf-8"))
    if isinstance(data, list):
        data = data[:k]
    json.dump(data, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    for d in ("dataset/sci_align", "raw_sample", "code", "slides",
              "visualizations", "evaluations", "paper", "model"):
        os.makedirs(f"{STAGE}/{d}", exist_ok=True)

    jsonl_files = sorted(glob.glob(f"{ROOT}/dataset/sci_align/*.jsonl"))
    n_records = compliance_gate(jsonl_files)

    # 1) Dataset JSONL + status
    counts = {}
    for f in jsonl_files:
        shutil.copy2(f, f"{STAGE}/dataset/sci_align/")
        counts[os.path.basename(f)] = sum(1 for l in open(f, encoding="utf-8") if l.strip())
    if os.path.exists(f"{ROOT}/data/dataset_status.json"):
        shutil.copy2(f"{ROOT}/data/dataset_status.json", f"{STAGE}/dataset/sci_align/")

    # 2) 10 ejemplos completos (requisito explícito)
    main_jsonl = f"{ROOT}/dataset/sci_align/dominga_geo_align.jsonl"
    with open(f"{STAGE}/dataset/sci_align/SAMPLE_10_records.jsonl", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sample_records(main_jsonl, 10)) + "\n")

    # 3) Muestra de datos crudos (MinerU content_list recortado)
    raw_candidates = glob.glob(f"{ROOT}/output/mineru/**/auto/*content_list.json", recursive=True)
    if raw_candidates:
        src = sorted(raw_candidates, key=os.path.getsize)[0]  # el más liviano
        trim_raw_sample(src, f"{STAGE}/raw_sample/mineru_content_list_SAMPLE.json")
        log(f"raw sample desde {os.path.basename(src)} (recortado a 60 elementos)")

    # 4) Código de construcción (curado)
    code_from_scripts = [
        "pipeline.py", "extract_geo_entities_mineru.py", "export_sci_align_full.py",
        "ingest_sci_align_neo4j.py", "thesis_harvester.py", "build_ontology.py",
        "extract_kmz_points.py", "dataset_stats.py",
    ]
    for s in code_from_scripts:
        p = f"{ROOT}/scripts/{s}"
        if os.path.exists(p):
            shutil.copy2(p, f"{STAGE}/code/")
    # auth.py es obligatorio: los módulos del pipeline lo importan, así que sin
    # él el código entregado no arranca.
    repo_code = (
        glob.glob(f"{REPO}/mineru_*.py")
        + [f"{REPO}/auth.py", f"{REPO}/ingest.py"]
        + glob.glob(f"{REPO}/ingest_*.py")
    )
    for s in sorted(set(repo_code)):
        if os.path.exists(s):
            shutil.copy2(s, f"{STAGE}/code/")
        elif s.endswith("auth.py"):
            raise FileNotFoundError(
                f"Falta {s}: el código entregado importa auth.py y no arrancaría sin él."
            )
    shutil.copy2(__file__, f"{STAGE}/code/")

    # 5) Documentos y PPT
    for src, dst in [
        (f"{REPO}/TECHNICAL_REPORT.md", f"{STAGE}/TECHNICAL_REPORT.md"),
        (f"{REPO}/README.md", f"{STAGE}/README.md"),
        (f"{REPO}/requirements.txt", f"{STAGE}/requirements.txt"),
        (f"{REPO}/GeoAI_SciAlign_AGI4S.pptx", f"{STAGE}/slides/GeoAI_SciAlign_AGI4S.pptx"),
    ]:
        if os.path.exists(src):
            shutil.copy2(src, dst)

    # 5b) Material para que el ZIP sea AUTOCONTENIDO (todo adentro, sin depender de links)
    for src in glob.glob(f"{COMP}/visualizations/*.png"):
        safe_copy(src, f"{STAGE}/visualizations/{os.path.basename(src)}")
    for src in [f"{COMP}/quality_evaluation_summary.md", f"{COMP}/omnidocbench_results.md",
                f"{COMP}/SUBMISSION_CHECKLIST.md"]:
        safe_copy(src, f"{STAGE}/evaluations/{os.path.basename(src)}")
    safe_copy(f"{COMP}/paper/main.pdf", f"{STAGE}/paper/technical_paper.pdf")
    # Modelo fine-tuneado (adapter LoRA liviano) + su config
    for src in glob.glob("/root/pipeline/finetuned_model/*"):
        if os.path.isfile(src) and os.path.getsize(src) < 20*1024*1024:
            safe_copy(src, f"{STAGE}/model/{os.path.basename(src)}")
    with open(f"{STAGE}/model/MODEL_CARD.md", "w", encoding="utf-8") as fh:
        fh.write(
            "# MinerU2.5-Geologia-ES (adapter QLoRA)\n\n"
            "Adapter LoRA (~4 MB) sobre MinerU 2.5 (1.2B) afinado para parsing de geología en español.\n"
            "Publicado en HuggingFace: Karlangaz/MinerU2.5-Geologia-ES · Licencia: CC-BY-4.0.\n")

    # 6) LICENSE (datos CC-BY-4.0; código Apache-2.0)
    with open(f"{STAGE}/LICENSE.md", "w", encoding="utf-8") as fh:
        fh.write(
            "# Licencias\n\n"
            "- **Dataset (dataset/sci_align/):** CC-BY-4.0 "
            "(https://creativecommons.org/licenses/by/4.0/)\n"
            "- **Código (code/):** Apache-2.0\n\n"
            "Atribución: La Serena Digital / GeoAI — AGI4S MDIC2026 Track 1.\n"
        )

    # 7) MANIFEST con checklist de requisitos
    counts_str = " + ".join(f"{k}: {v}" for k, v in counts.items())
    manifest = f"""# MANIFEST — Entrega AGI4S / MDIC2026 · Pista 1 (Sci-Align)

Equipo: **La Serena Digital** · Generado: {time.strftime('%Y-%m-%d %H:%M UTC')}
Dataset: **{n_records} registros** ({counts_str}) · Licencia datos: CC-BY-4.0

## Mapa de requisitos del concurso → contenido del ZIP
| Requisito | Archivo(s) |
|-----------|-----------|
| Dataset (Sci-Align) | `dataset/sci_align/*.jsonl` |
| Link dataset open-source | HuggingFace: Karlangaz/la-serena-digital-geo-corpus (CC-BY-4.0) |
| ≥10 ejemplos completos | `dataset/sci_align/SAMPLE_10_records.jsonl` |
| Muestra de datos crudos | `raw_sample/mineru_content_list_SAMPLE.json` (salida MinerU) |
| Informe técnico | `TECHNICAL_REPORT.md` |
| Código de construcción | `code/` |
| MinerU documentado | `TECHNICAL_REPORT.md` + `code/mineru_*.py` |
| Link código (bonus) | github.com/cgn1618-coder/la-serena-digital-mineru-pipeline |
| PPT (bonus) | `slides/GeoAI_SciAlign_AGI4S.pptx` |
| Licencia | `LICENSE.md` |

## Compliance verificada
- texto_fuente ≤ 200 chars verbatim (regla HermesGuard) — OK
- Sin patrones de bibliografía/copyright (doi/ISBN/©/...) — OK
"""
    with open(f"{STAGE}/MANIFEST.md", "w", encoding="utf-8") as fh:
        fh.write(manifest)

    # 8) Comprimir
    os.makedirs(os.path.dirname(ZIP_OUT), exist_ok=True)
    if os.path.exists(ZIP_OUT):
        os.remove(ZIP_OUT)
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(STAGE):
            for fn in files:
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, os.path.dirname(STAGE)))

    size = os.path.getsize(ZIP_OUT)
    log(f"ZIP listo: {ZIP_OUT} ({size/1024:.1f} KB)")
    log(f"sha256: {sha256(ZIP_OUT)}")
    # listado
    with zipfile.ZipFile(ZIP_OUT) as z:
        for i in z.namelist():
            print("   ", i)


if __name__ == "__main__":
    main()
