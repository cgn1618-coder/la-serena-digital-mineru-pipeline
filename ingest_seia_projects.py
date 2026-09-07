"""
Ingest SEIA mining projects from Coquimbo Region into Neo4j.
Creates Project nodes linked to Location, Law, and Institution nodes.
"""
import json

from neo4j.exceptions import Neo4jError

from auth import neo4j_driver

def ingest():
    driver = neo4j_driver()  # exige y verifica NEO4J_PASSWORD
    
    with open("/root/pipeline/gov_data/seia_coquimbo_merged.json", encoding='utf-8') as f:
        projects = json.load(f)
    
    print(f"Loading {len(projects)} projects into Neo4j...")
    
    with driver.session() as session:
        # Create constraint
        try:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.seia_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE")
        except Neo4jError as exc:
            print(f"  ⚠️ Constraints no creadas: {exc}")
        
        count = 0
        eia_count = 0
        
        for p in projects:
            seia_id = p.get("EXPEDIENTE_ID", "")
            if not seia_id:
                continue
            
            name = p.get("EXPEDIENTE_NOMBRE", "Sin nombre")
            workflow = p.get("WORKFLOW_DESCRIPCION", "DIA")
            comuna = p.get("COMUNA_NOMBRE") or "Sin comuna"
            region = p.get("REGION_NOMBRE") or "Región de Coquimbo"
            titular = p.get("TITULAR") or ""
            investment = p.get("INVERSION_MM_FORMAT") or "0"
            status = p.get("ESTADO_PROYECTO") or ""
            tipo = p.get("DESCRIPCION_TIPOLOGIA") or ""
            fecha = p.get("FECHA_PRESENTACION_FORMAT") or ""
            
            # Create Project node
            session.run("""
                MERGE (p:Project {seia_id: $seia_id})
                SET p.name = $name,
                    p.workflow = $workflow,
                    p.titular = $titular,
                    p.investment_mmusd = $investment,
                    p.status = $status,
                    p.tipologia = $tipo,
                    p.fecha_presentacion = $fecha
            """, seia_id=seia_id, name=name, workflow=workflow,
                 titular=titular, investment=investment, status=status,
                 tipo=tipo, fecha=fecha)
            
            # Create/merge Location (Comuna)
            session.run("""
                MERGE (l:Location {name: $comuna})
                SET l.type = 'Comuna',
                    l.region = $region
                WITH l
                MATCH (p:Project {seia_id: $seia_id})
                MERGE (p)-[:LOCATED_IN]->(l)
            """, comuna=comuna, region=region, seia_id=seia_id)
            
            # Create/merge Location (Region)
            region_name = "Región de Coquimbo"
            session.run("""
                MERGE (r:Location {name: $region_name})
                SET r.type = 'Region'
                WITH r
                MATCH (p:Project {seia_id: $seia_id})
                MERGE (p)-[:LOCATED_IN]->(r)
            """, region_name=region_name, seia_id=seia_id)
            
            # Link to legal framework
            if workflow == "EIA":
                session.run("""
                    MATCH (p:Project {seia_id: $seia_id})
                    MATCH (d:Decree {name: 'DS 40/2012 MMA'})
                    MERGE (p)-[:REGULATED_BY]->(d)
                """, seia_id=seia_id)
                eia_count += 1
            
            # Link to SEIA
            session.run("""
                MATCH (p:Project {seia_id: $seia_id})
                MATCH (i:Institution {acronym: 'SEA'})
                MERGE (p)-[:EVALUATED_BY]->(i)
            """, seia_id=seia_id)
            
            count += 1
            if count % 50 == 0:
                print(f"  {count}/{len(projects)}...")
        
        print(f"  Done: {count} projects ({eia_count} EIA)")
        
        # Create Location hierarchy (Comuna → Region)
        session.run("""
            MATCH (c:Location {type: 'Comuna'})
            MATCH (r:Location {type: 'Region', name: 'Región de Coquimbo'})
            MERGE (c)-[:PART_OF]->(r)
        """)
        
        # Count
        result = session.run("""
            MATCH (p:Project)
            RETURN count(p) AS count
        """)
        print(f"  Total Projects in graph: {result.single()['count']}")
        
        result = session.run("""
            MATCH (l:Location)
            RETURN l.type AS type, count(l) AS count
            ORDER BY count DESC
        """)
        print("  Locations:")
        for r in result:
            print(f"    {r['type']}: {r['count']}")
    
    driver.close()
    print("✅ SEIA projects ingested to Neo4j")

if __name__ == "__main__":
    ingest()
