# Technical Report — GeoAI Sci-Align Dataset
## AGI4S Competition · Track 1: Corpus Creation

**Team:** GeoAI  
**Submission date:** May 2026  
**License:** CC-BY-4.0  
**Repository:** github.com/cgn1618-coder/la-serena-digital-mineru-pipeline

---

## 1. Overview

This report describes the construction of **Sci-Align**, a structured scientific dataset
of Chilean environmental geology built for the AGI4S competition (Track 1 — Corpus
Creation, sh_AI Lab / Heywhale). The dataset transforms publicly available Environmental
Impact Assessment (EIA) documents from Chile's SEIA system into traceable, structured
knowledge aligned with a five-layer geological-environmental ontology.

The source corpus is the **Dominga EIA** (SEIA expedient ID 9810), a large-scale mining
project located in the Coquimbo Region, northern Chile. This document provides one of the
most comprehensive geological and ecological baselines publicly available for the Chilean
semi-arid coast, covering geology, hydrology, flora, fauna, marine ecosystems, and
regulatory frameworks.

Dominga is located within the Coastal Iron Belt (Franja Ferrífera Costera),
a Cretaceous metallogenic province hosting world-class Fe-Cu-Au deposits
controlled by the Atacama Fault System — making it one of the most
scientifically and socio-environmentally significant mining projects in Chile.

---

## 2. Primary Tool: MinerU

Following the competition requirement, **MinerU v3.1.15** is the primary PDF processing
pipeline. It was applied to the main baseline document
(`EIA_Dominga_Cap2_LineaBase.pdf`, 933 pages) via the `mineru_batch.py` script:

```bash
python mineru_batch.py --input data/raw_pdfs/ --output output/mineru/
```

MinerU extracts structured text, tables, and figures while preserving document hierarchy,
enabling precise alignment between content and scientific metadata. All JSONL records
include the `procesado_con: "mineru-3.1.15"` provenance field.

**Processing statistics from MinerU output (`geo_entities.json`):**

| Metric | Value |
|--------|-------|
| Document pages processed | 933 |
| Text segments extracted | 5,507 |
| Tables processed | 585 |
| Raw entity mentions identified | 1,253 |

Secondary tools (`PyMuPDF`, `pdfplumber`) were used for fallback page-level extraction
and table parsing. All dependencies are versioned in `requirements.txt`.

---

## 3. Dataset Construction

### 3.1 Source Document

| Field | Value |
|-------|-------|
| Document | EIA Dominga — Cap. 2 Línea de Base Ambiental |
| Source system | SEIA Chile (seia.sea.gob.cl) |
| Access | Public — expedient ID 9810 |
| Pages | 933 |
| Domain | Geology, hydrology, ecology, marine biology |
| Spatial coverage | Coquimbo Region, Chile (UTM Zone 19S / WGS84) |

### 3.2 Five-Layer Geological-Environmental Ontology

Entities are organized into five semantic layers with incremental relationships:

| Layer | Entity Types |
|-------|-------------|
| Physical territory | `UnidadLitologica`, `FallaEstructura`, `CuencaHidrologica`, `Acuifero` |
| Project components | `Proyecto`, `ComponenteProyecto`, `AreaInfluencia` |
| Scientific baseline | `EstacionMuestreo`, `ParametroMedido`, `ResultadoAnalitico`, `Especie` |
| Methodological traceability | `Metodologia`, `Laboratorio`, `DocumentoFuente` |
| Regulatory context | `NormaAmbiental`, `AreaProtegida`, `RegionComuna` |

Every entity carries a mandatory `id` and `source` (document + page). Every relation is
backed by documentary evidence.

### 3.3 Entity Extraction and Filtering

Entities were extracted from MinerU output via dedicated scripts:

- **Geological units and structures** — pattern matching on formation names, fault
  system identifiers, and hydrological basin codes from the geology chapter.
- **Sampling stations** — parsed from structured tables (208 records), retaining only
  entries with valid UTM easting/northing coordinates.
- **Biological species** — filtered from 951 candidate two-word phrases using a curated
  genus list of 150+ known taxa from the Coquimbo Region (mammals, birds, fish,
  reptiles, marine invertebrates, vascular flora, macroalgae). Strict binomial pattern
  (`Genus epithet`) and confirmed source page required. Duplicates removed.

---

## 4. Dataset Statistics

**Final dataset: `dataset/sci_align/dominga_geo_align.jsonl`**

### 4.1 Summary

| Metric | Value |
|--------|-------|
| **Total records** | **402** |
| Records with UTM coordinates | 200 |
| Records with explicit relations | 209 |
| Source document pages covered | 933 |
| Processing tool | MinerU v3.1.15 |
| Output format | JSONL (Sci-Align) |

### 4.2 Entity Type Distribution

| Entity Type | Records | Notes |
|-------------|---------|-------|
| `EstacionMuestreo` | 212 | 200 with UTM 19S / WGS84 coordinates |
| `Especie` | 102 | 83 Animalia · 19 Plantae |
| `CuencaHidrologica` | 55 | Coquimbo region drainage basins |
| `UnidadLitologica` | 22 | Geological formations + plutonic complexes |
| `Acuifero` | 6 | Free/phreatic aquifer systems |
| `FallaEstructura` | 5 | Fault systems incl. SFET and SFA |
| **Total** | **402** | |

### 4.3 Relation Types Present

| Relation | Count | Semantics |
|----------|-------|-----------|
| `EN_CUENCA` | 209 | Station / aquifer located within drainage basin |
| `INFLUENCIA_HIDROLOGICA` | 2 | Fault influence on aquifer or lithounit |

### 4.4 Species Breakdown

| Kingdom | Count | Representative taxa |
|---------|-------|---------------------|
| Animalia | 83 | *Spheniscus humboldti*, *Lontra felina*, *Concholepas concholepas*, *Puma concolor* |
| Plantae | 19 | *Eulychnia acida*, *Lessonia nigrescens*, *Flourensia thurifera* |

---

## 5. Output Format (Sci-Align JSONL)

Each record integrates text, spatial data, entities, and relations in a single JSON
object, following the Sci-Align paradigm:

```json
{
  "id": "dominga_geo_0022",
  "paradigma": "Sci-Align",
  "dominio": "geologia_ambiental",
  "fuente": {
    "documento": "EIA_Dominga_Cap2_LineaBase.pdf",
    "pagina": 437,
    "procesado_con": "mineru-3.1.15",
    "url_seia": "https://seia.sea.gob.cl/expediente/expediente.php?id_expediente=9810"
  },
  "entidades": [{
    "tipo": "Especie",
    "id": "dominga_sp_calyptraea_trochiformis",
    "propiedades": {
      "nombre_cientifico": "Calyptraea trochiformis",
      "reino": "Animalia",
      "menciones_documento": 3
    }
  }],
  "relaciones": [],
  "texto_fuente": "Especie registrada en línea de base: Calyptraea trochiformis.",
  "multimodal": {}
}
```

All text excerpts are limited to ≤200 characters per record (HermesGuard content
governance policy). No copyrighted bibliographic material is included in the dataset.

---

## 6. Reproducibility

The full pipeline is open source and reproducible:

```bash
# 1. Extract entities with MinerU
python mineru_batch.py --input data/raw_pdfs/ --output output/mineru/

# 2. Export all geological entities to Sci-Align JSONL
python scripts/export_sci_align_full.py

# 3. Append confirmed biological species
python scripts/append_species_sci_align.py

# Final output: dataset/sci_align/dominga_geo_align.jsonl (402 records)
```

Source PDFs are publicly available via SEIA Chile. The derived dataset is published
under **CC-BY-4.0**. Raw PDFs are not redistributed.

---

## 7. Data Quality

- Every record cites document title, page number, and MinerU version (`procesado_con`).
- UTM coordinates validated against Zone 19S bounds for the Coquimbo Region.
- Species filtered against a curated genus list; duplicates removed before export.
- No synthetic or AI-hallucinated entity values — all properties are extracted from
  source document text or tables.
- SEIA URL included per record for independent verification.

---

*Dataset constructed with MinerU v3.1.15 · PyMuPDF · Neo4j · Python 3.11*  
*Coquimbo Region, Chile · UTM Zone 19S / WGS84*
