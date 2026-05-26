"""
La Serena Digital — Pipeline de Ingesta de Documentos v0.1
Flujo: PDF → texto → chunks → embeddings (Qdrant) + entidades (Neo4j)
"""

import os
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

import pymupdf  # PyMuPDF
import tiktoken
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "earth_sciences")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

CHUNK_SIZE_TOKENS = int(os.getenv("CHUNK_SIZE_TOKENS", "512"))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "64"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ingest")


# ---------------------------------------------------------------------------
# Inicialización de clientes
# ---------------------------------------------------------------------------

def init_neo4j():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    log.info("Neo4j conectado")
    return driver


def init_qdrant():
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    # Crear colección si no existe
    collections = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in collections:
        # bge-m3 produce embeddings de 1024 dimensiones
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        log.info(f"Colección '{QDRANT_COLLECTION}' creada en Qdrant")
    else:
        log.info(f"Usando colección existente '{QDRANT_COLLECTION}'")
    return client


def init_embedder():
    log.info(f"Cargando modelo de embeddings: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    log.info(f"Modelo cargado (dim={model.get_sentence_embedding_dimension()})")
    return model


# ---------------------------------------------------------------------------
# Extracción de texto
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> Dict:
    """Extrae texto completo y metadatos de un PDF usando PyMuPDF."""
    doc = pymupdf.open(pdf_path)
    metadata = doc.metadata or {}

    full_text = []
    page_count = len(doc)
    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            full_text.append(text)

    text = "\n\n".join(full_text)
    doc.close()

    return {
        "text": text,
        "title": metadata.get("title", Path(pdf_path).stem),
        "author": metadata.get("author", "Desconocido"),
        "pages": page_count,
        "file_path": pdf_path,
        "file_hash": hashlib.sha256(open(pdf_path, "rb").read()).hexdigest(),
        "extraction_date": datetime.now(timezone.utc).isoformat(),
        "char_count": len(text),
    }


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, tokenizer_name: str = "cl100k_base") -> List[Dict]:
    """Divide texto en chunks de tamaño controlado por tokens con solapamiento."""
    tokenizer = tiktoken.get_encoding(tokenizer_name)
    tokens = tokenizer.encode(text)

    chunks = []
    start = 0
    idx = 0
    while start < len(tokens):
        end = min(start + CHUNK_SIZE_TOKENS, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens)

        chunks.append({
            "index": idx,
            "text": chunk_text,
            "token_count": len(chunk_tokens),
            "char_count": len(chunk_text),
        })

        idx += 1
        start += CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS

        # Evitar loop infinito con solapamiento excesivo
        if start >= len(tokens) or CHUNK_SIZE_TOKENS <= CHUNK_OVERLAP_TOKENS:
            break

    log.info(f"Texto dividido en {len(chunks)} chunks")
    return chunks


# ---------------------------------------------------------------------------
# Embeddings + Qdrant
# ---------------------------------------------------------------------------

def store_embeddings(
    client: QdrantClient,
    model: SentenceTransformer,
    document_id: str,
    chunks: List[Dict],
) -> List[str]:
    """Genera embeddings y almacena chunks en Qdrant."""
    texts = [c["text"] for c in chunks]
    log.info(f"Generando embeddings para {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=False)

    points = []
    qdrant_ids = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        point_id = uuid.uuid4()
        qdrant_ids.append(str(point_id))

        points.append(PointStruct(
            id=str(point_id),
            vector=emb.tolist(),
            payload={
                "document_id": document_id,
                "chunk_index": chunk["index"],
                "text": chunk["text"],
                "token_count": chunk["token_count"],
            },
        ))

    client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    log.info(f"{len(points)} puntos almacenados en Qdrant")
    return qdrant_ids


# ---------------------------------------------------------------------------
# Extracción de entidades (v0.1 - heurística básica)
# ---------------------------------------------------------------------------

def extract_basic_entities(text: str) -> Dict:
    """
    Extracción básica de entidades usando heurísticas.
    v0.2 reemplazará esto con GLiNER o modelo NER especializado.
    """
    import re

    entities = {
        "locations": [],
        "minerals": [],
        "organizations": [],
        "dates": [],
        "measurements": [],
    }

    # Fechas (YYYY, YYYY-MM-DD, etc.)
    date_patterns = [
        r'\b(19|20)\d{2}\b',
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
    ]
    for pat in date_patterns:
        entities["dates"].extend(list(set(re.findall(pat, text, re.IGNORECASE))))

    # Mediciones (número + unidad)
    meas_pattern = r'\b\d+\.?\d*\s*(?:km|m|cm|mm|kg|g|mg|Ma|Ga|°C|ppm|ppb|wt%|vol%)\b'
    entities["measurements"] = list(set(re.findall(meas_pattern, text, re.IGNORECASE)))

    # Minerales comunes (lista base, se expandirá)
    common_minerals = [
        "quartz", "feldspar", "calcite", "pyrite", "magnetite", "hematite",
        "chalcopyrite", "bornite", "galena", "sphalerite", "biotite", "muscovite",
        "olivine", "pyroxene", "amphibole", "garnet", "kaolinite", "montmorillonite",
        "dolomite", "aragonite", "barite", "fluorite", "apatite", "zircon",
        "rutile", "ilmenite", "chromite", "cassiterite", "wolframite",
        "gold", "silver", "copper", "platinum", "palladium",
    ]
    text_lower = text.lower()
    for mineral in common_minerals:
        if mineral in text_lower:
            entities["minerals"].append(mineral)

    return entities


def create_graph_nodes(
    driver,
    doc_info: Dict,
    chunks: List[Dict],
    qdrant_ids: List[str],
    entities: Dict,
):
    """Crea nodos Document y Chunk en Neo4j, con entidades básicas."""
    doc_id = str(uuid.uuid4())

    with driver.session() as session:
        # Crear nodo Document
        session.run(
            """
            MERGE (d:Document {id: $id})
            SET d.title = $title,
                d.file_path = $file_path,
                d.file_hash = $file_hash,
                d.author_name = $author,
                d.char_count = $char_count,
                d.chunk_count = $chunk_count,
                d.extraction_date = datetime($extraction_date),
                d.created_at = datetime()
            """,
            id=doc_id,
            title=doc_info["title"],
            file_path=doc_info["file_path"],
            file_hash=doc_info["file_hash"],
            author=doc_info["author"],
            char_count=doc_info["char_count"],
            chunk_count=len(chunks),
            extraction_date=doc_info["extraction_date"],
        )

        # Crear nodos Chunk y relaciones
        for chunk, qdrant_id in zip(chunks, qdrant_ids):
            chunk_id = str(uuid.uuid4())
            session.run(
                """
                CREATE (c:Chunk {
                    id: $id,
                    document_id: $doc_id,
                    chunk_index: $index,
                    qdrant_point_id: $qdrant_id,
                    token_count: $token_count,
                    char_count: $char_count,
                    text: $text
                })
                WITH c
                MATCH (d:Document {id: $doc_id})
                CREATE (d)-[:HAS_CHUNK]->(c)
                """,
                id=chunk_id,
                doc_id=doc_id,
                index=chunk["index"],
                qdrant_id=qdrant_id,
                token_count=chunk["token_count"],
                char_count=chunk["char_count"],
                text=chunk["text"][:10000],  # Limitar texto a 10K caracteres
            )

        # Crear nodos de minerales detectados
        for mineral_name in entities.get("minerals", [])[:20]:
            session.run(
                """
                MERGE (m:Mineral {name: $name})
                ON CREATE SET m.id = $id, m.created_at = datetime()
                WITH m
                MATCH (d:Document {id: $doc_id})
                MERGE (d)-[:MENTIONS_MINERAL]->(m)
                """,
                name=mineral_name,
                id=str(uuid.uuid4()),
                doc_id=doc_id,
            )

        log.info(f"Nodos creados: 1 Document + {len(chunks)} Chunks + {len(entities.get('minerals',[]))} Minerales")

    return doc_id


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

def ingest_pdf(pdf_path: str) -> str:
    """Pipeline completo de ingesta de un PDF."""

    # 1. Extraer texto
    log.info(f"Procesando: {pdf_path}")
    doc_info = extract_text_from_pdf(pdf_path)
    log.info(f"Texto extraído: {doc_info['char_count']} caracteres, título='{doc_info['title']}'")

    if doc_info["char_count"] < 100:
        log.warning("Documento con muy poco texto — omitiendo")
        return ""

    # 2. Chunking
    chunks = chunk_text(doc_info["text"])

    # 3. Embeddings + Qdrant
    qdrant = init_qdrant()
    model = init_embedder()
    qdrant_ids = store_embeddings(qdrant, model, doc_info["file_hash"], chunks)

    # 4. Extraer entidades
    entities = extract_basic_entities(doc_info["text"])
    log.info(f"Entidades detectadas: {', '.join(f'{k}: {len(v)}' for k, v in entities.items())}")

    # 5. Crear nodos en Neo4j
    driver = init_neo4j()
    doc_id = create_graph_nodes(driver, doc_info, chunks, qdrant_ids, entities)
    driver.close()

    log.info(f"Ingesta completada. Document ID: {doc_id}")
    return doc_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python ingest.py <ruta_pdf> [rutas adicionales...]")
        sys.exit(1)

    for pdf_path in sys.argv[1:]:
        if not os.path.exists(pdf_path):
            log.error(f"Archivo no encontrado: {pdf_path}")
            continue
        try:
            doc_id = ingest_pdf(pdf_path)
            print(f"✓ {pdf_path} → {doc_id}")
        except Exception as e:
            log.exception(f"Error procesando {pdf_path}: {e}")
