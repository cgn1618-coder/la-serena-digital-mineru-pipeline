# La Serena Digital — MinerU Pipeline

**End-to-end document processing pipeline for the MDIC 2026 competition.**
Extracts, parses, and ingests geological and ecological PDFs into a knowledge graph (Neo4j) with vector embeddings (Qdrant).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PDF DOCUMENTS                                 │
│                  (~300 PDFs, geology + ecology)                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  1. mineru_split.py                                                  │
│     Split PDFs exceeding 200 pages into smaller chunks               │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  2. mineru_batch.py  /  mineru_poll.py                               │
│     Submit PDFs to MinerU API (batch), poll results, download ZIPs   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  3. mineru_ingest_neo4j.py                                           │
│     Extract MinerU output ZIPs → Document + Figure nodes in Neo4j    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  4. ingest.py                                                        │
│     PyMuPDF extraction → chunking → embeddings (Qdrant) + Neo4j      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  5. ingest_legal.py  +  ingest_seia_projects.py                      │
│     Chilean environmental law + SEIA mining projects → Neo4j graph   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     NEO4J KNOWLEDGE GRAPH                            │
│  Documents → Chunks → Figures | Projects → Locations → Institutions  │
│  Laws ↔ Decrees ↔ Zones | Mineral entities                           │
└──────────────────────────────────────────────────────────────────────┘
```

## Pipeline Components

| Script | Purpose | Dependencies |
|--------|---------|-------------|
| `mineru_split.py` | Split PDFs >200 pages and re-submit to MinerU API | `pymupdf`, `requests` |
| `mineru_batch.py` | Batch submit PDFs to MinerU API v4 | `requests` |
| `mineru_poll.py` | Poll MinerU tasks and download result ZIPs | `requests` |
| `mineru_ingest_neo4j.py` | Extract MinerU ZIPs into Neo4j (Document + Figure nodes) | `neo4j` |
| `ingest.py` | PDF → text → chunks → Qdrant embeddings + Neo4j entities | `pymupdf`, `tiktoken`, `neo4j`, `qdrant_client`, `sentence_transformers` |
| `ingest_legal.py` | Chilean environmental legal framework → Neo4j graph | `neo4j` |
| `ingest_seia_projects.py` | SEIA mining projects (Coquimbo) → Neo4j graph | `neo4j` |

## Prerequisites

- **Python 3.10+**
- **Neo4j** (5.x+) running with graph database
- **Qdrant** vector database (for `ingest.py`)
- **MinerU API token** (for `mineru_batch.py`, `mineru_poll.py`, `mineru_split.py`)
- **Web server** exposing PDFs via public URLs (for MinerU cloud processing)

## Environment Variables

All credentials are configured via environment variables — **no hardcoded secrets**:

```bash
# MinerU API
export MINERU_API_TOKEN="your-mineru-token"

# Neo4j
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"

# Qdrant
export QDRANT_URL="http://localhost:6333"
export QDRANT_API_KEY="your-qdrant-key"
export QDRANT_COLLECTION="earth_sciences"

# Embedding model
export EMBEDDING_MODEL="BAAI/bge-m3"

# Paths
export BASE_URL="https://your-server.com"
export PDF_DIR="/path/to/pdfs"
export OUTPUT_DIR="/path/to/output"
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### 1. Split large PDFs (optional)
```bash
python mineru_split.py
```

### 2. Process PDFs through MinerU API
```bash
# Submit all PDFs to MinerU batch API
python mineru_batch.py

# Or poll and download results from existing tasks
python mineru_poll.py
```

### 3. Ingest MinerU results into Neo4j
```bash
python mineru_ingest_neo4j.py
```

### 4. Direct PDF ingestion (PyMuPDF + embeddings)
```bash
python ingest.py /path/to/document.pdf
```

### 5. Ingest legal framework and SEIA projects
```bash
python ingest_legal.py
python ingest_seia_projects.py
```

## Data Categories

- **Geología**: Geology PDFs → classified based on filename keywords
- **Ecología**: Ecology/Environmental PDFs → classified based on filename keywords

## License

Apache 2.0 — See [LICENSE](LICENSE)

---

*Built for the MDIC 2026 competition — La Serena Digital*
