#!/usr/bin/env python3
"""
Extract MinerU ZIPs and ingest into Neo4j.
Creates Document nodes with rich metadata + Figure nodes linked to them.
"""
import os, json, zipfile, hashlib, uuid, re
from datetime import datetime
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
ZIPS_DIR = "/root/pipeline/mineru_output"
FIGURES_DIR = "/root/portal/static/figures"
EXTRACT_DIR = "/tmp/mineru_ingest"

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

def extract_metadata(md_text):
    """Extract title and authors from markdown."""
    lines = md_text.strip().split('\n')
    title = ""
    authors = []
    
    # First # heading is title
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('# ') and not stripped.startswith('## '):
            title = stripped[2:].strip()
            break
    
    # Look for author patterns
    author_section = md_text[:2000]  # First 2000 chars
    # Common patterns: "By ...", "Author:", "NAME1, NAME2"
    for line in lines[:30]:
        if not line.startswith('#') and len(line) > 10 and len(line) < 200:
            # Look for university affiliations or author names
            if any(kw in line.lower() for kw in ['university', 'institute', 'college', 'laboratory', 'centre for']):
                authors.append(line.strip())
    
    if not title:
        title = "Untitled"
    
    return title, authors[:3]

def ingest_zip(zip_path, category):
    """Process one ZIP: extract, read metadata, create Neo4j nodes."""
    zip_name = os.path.basename(zip_path).replace('.zip', '')
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Find full.md
        md_files = [f for f in zf.namelist() if f.endswith('.md')]
        image_files = [f for f in zf.namelist() if f.startswith('images/') and f.endswith(('.jpg','.png','.jpeg'))]
        
        if not md_files:
            print(f"  ⚠️ No markdown in {zip_name}")
            return None
        
        md_text = zf.read(md_files[0]).decode('utf-8', errors='replace')
        
        # Extract metadata
        title, authors = extract_metadata(md_text)
        
        # Compute file hash for dedup
        file_hash = hashlib.sha256(md_text.encode()).hexdigest()[:16]
        doc_id = str(uuid.uuid4())
        
        # Extract first few paragraphs as abstract
        paragraphs = [p.strip() for p in md_text.split('\n\n') if len(p.strip()) > 50 and not p.startswith('#')]
        abstract = paragraphs[0][:500] if paragraphs else ""
        
        # Count figures and tables
        figure_count = len(image_files)
        table_count = len(re.findall(r'<table>', md_text))
        
        # Extract figure references with captions
        figures = []
        fig_pattern = re.findall(r'!\[(.*?)\]\((images/[^)]+)\)\s*\n(.*?)(?:\n\n|\n(?:#|!\[)|$)', md_text, re.DOTALL)
        for alt, img_path, caption in fig_pattern:
            figures.append({
                "alt": alt.strip(),
                "img_path": img_path.strip(),
                "caption": caption.strip()[:500]
            })
        
        # Create Document node
        with driver.session() as session:
            session.run("""
                MERGE (d:Document {file_hash: $hash})
                ON CREATE SET 
                    d.id = $id,
                    d.title = $title,
                    d.authors = $authors,
                    d.abstract = $abstract,
                    d.category = $category,
                    d.source = 'mineru',
                    d.source_file = $source_file,
                    d.figure_count = $figure_count,
                    d.table_count = $table_count,
                    d.char_count = $char_count,
                    d.ingested_at = datetime()
                ON MATCH SET
                    d.ingested_at = datetime()
                RETURN d.id AS doc_id
            """,
                hash=file_hash, id=doc_id, title=title, authors=authors,
                abstract=abstract, category=category, source_file=zip_name,
                figure_count=figure_count, table_count=table_count,
                char_count=len(md_text)
            )
            
            # Extract and ingest images
            for i, fig in enumerate(figures):
                try:
                    img_data = zf.read(fig['img_path'])
                    img_hash = hashlib.sha256(img_data).hexdigest()[:16]
                    
                    # Save image
                    ext = os.path.splitext(fig['img_path'])[1]
                    img_filename = f"{file_hash}_{i}{ext}"
                    img_dest = os.path.join(FIGURES_DIR, img_filename)
                    
                    with open(img_dest, 'wb') as f:
                        f.write(img_data)
                    
                    img_url = f"/static/figures/{img_filename}"
                    
                    # Create Figure node
                    session.run("""
                        MATCH (d:Document {file_hash: $doc_hash})
                        MERGE (f:Figure {img_hash: $img_hash})
                        ON CREATE SET
                            f.id = $fig_id,
                            f.url = $url,
                            f.alt = $alt,
                            f.caption = $caption,
                            f.category = $category,
                            f.ingested_at = datetime()
                        MERGE (f)-[:EXTRACTED_FROM]->(d)
                    """,
                        doc_hash=file_hash, img_hash=img_hash,
                        fig_id=str(uuid.uuid4()), url=img_url,
                        alt=fig['alt'], caption=fig['caption'],
                        category=category
                    )
                except Exception as e:
                    pass  # Skip broken images
        
        return {
            "title": title[:80],
            "figures": len(figures),
            "tables": table_count,
            "chars": len(md_text)
        }

def main():
    stats = {"geologia": [], "ecologia": []}
    
    for category in ["geologia", "ecologia"]:
        cat_dir = os.path.join(ZIPS_DIR, category)
        zips = sorted([f for f in os.listdir(cat_dir) if f.endswith('.zip')])
        print(f"\n=== {category.upper()} ({len(zips)} ZIPs) ===")
        
        for i, zf_name in enumerate(zips):
            zip_path = os.path.join(cat_dir, zf_name)
            result = ingest_zip(zip_path, category)
            if result:
                stats[category].append(result)
                print(f"  [{i+1}/{len(zips)}] {result['title']} | {result['figures']} figs, {result['tables']} tables, {result['chars']:,} chars")
            else:
                print(f"  [{i+1}/{len(zips)}] ⚠️ {zf_name[:60]} - SKIPPED")
    
    # Summary
    print("\n=== INGESTA COMPLETADA ===")
    for cat in ["geologia", "ecologia"]:
        items = stats[cat]
        total_figs = sum(s['figures'] for s in items)
        total_tables = sum(s['tables'] for s in items)
        print(f"{cat}: {len(items)} documentos, {total_figs} figuras, {total_tables} tablas")
    
    # Neo4j counts
    with driver.session() as session:
        docs = session.run("MATCH (d:Document {source:'mineru'}) RETURN count(d) AS c").single()['c']
        figs = session.run("MATCH (f:Figure) RETURN count(f) AS c").single()['c']
        print(f"\nNeo4j: {docs} Document nodes, {figs} Figure nodes")
    
    # Figures on disk
    fig_count = len(os.listdir(FIGURES_DIR))
    fig_size = sum(os.path.getsize(os.path.join(FIGURES_DIR, f)) for f in os.listdir(FIGURES_DIR))
    print(f"Figures on disk: {fig_count} files, {fig_size/(1024*1024):.1f} MB")

if __name__ == '__main__':
    main()
    driver.close()
