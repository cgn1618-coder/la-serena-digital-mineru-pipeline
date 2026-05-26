"""
Ingest the Chilean environmental legal framework into Neo4j.
Creates nodes: LegalFramework, Law, Decree, Institution, Regulation
and relationships between them.
"""
import os
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

# Legal framework structure based on marco_legal_ambiental_chile.md
FRAMEWORK = {
    "institutions": [
        {"name": "Ministerio del Medio Ambiente", "acronym": "MMA", "created_by": "Ley 20.417", "year": 2010, "role": "Normativo y de políticas"},
        {"name": "Servicio de Evaluación Ambiental", "acronym": "SEA", "created_by": "Ley 20.417", "year": 2010, "role": "Evaluación de impacto ambiental"},
        {"name": "Superintendencia del Medio Ambiente", "acronym": "SMA", "created_by": "Ley 20.417", "year": 2010, "role": "Fiscalización y sanción"},
        {"name": "Tribunales Ambientales", "acronym": "TA", "created_by": "Ley 20.600", "year": 2012, "role": "Justicia ambiental"},
    ],
    "laws": [
        {"number": "19.300", "name": "Ley de Bases Generales del Medio Ambiente", "year": 1994, "summary": "Principios e instrumentos de gestión ambiental"},
        {"number": "20.417", "name": "Crea MMA, SEA y SMA", "year": 2010, "summary": "Reforma institucional ambiental"},
        {"number": "20.600", "name": "Crea Tribunales Ambientales", "year": 2012, "summary": "Jurisdicción especializada ambiental"},
        {"number": "20.551", "name": "Regula cierre de faenas mineras", "year": 2011, "summary": "Obligación de plan de cierre y garantía financiera"},
        {"number": "20.920", "name": "Responsabilidad Extendida del Productor (REP)", "year": 2016, "summary": "Gestión de residuos"},
        {"number": "21.455", "name": "Ley Marco de Cambio Climático", "year": 2022, "summary": "Metas de mitigación y adaptación"},
        {"number": "21.600", "name": "Acuerdo de Escazú", "year": 2024, "summary": "Participación, acceso a información y justicia ambiental"},
    ],
    "decrees": [
        {"number": "DS 40/2012 MMA", "name": "Reglamento del SEIA", "summary": "Tipologías de ingreso, contenidos de DIA y EIA"},
        {"number": "DS 59/1998 MINSEGPRES", "name": "Norma primaria MP10", "summary": "Concentraciones máximas diarias 150 µg/m³N, anuales 50 µg/m³N"},
        {"number": "DS 12/2011 MMA", "name": "Norma primaria MP2.5", "summary": "Concentraciones máximas diarias 50 µg/m³N, anuales 20 µg/m³N"},
        {"number": "DS 113/2002 MINSEGPRES", "name": "Norma primaria SO2", "summary": "Concentraciones máximas diarias 250 µg/m³N, anuales 80 µg/m³N"},
        {"number": "DS 138/2005 MINSEGPRES", "name": "Norma de emisión fundiciones de cobre", "summary": "Límites de emisión para arsénico, SO2 y MP en fundiciones"},
        {"number": "DS 28/2013 MMA", "name": "Norma de emisión termoeléctricas", "summary": "Límites de emisión para MP, SO2, NOx y Hg"},
    ],
    "zones": [
        {"name": "Andacollo", "status": "saturada", "pollutant": "MP10", "decree": "DS 4/2010 MMA"},
        {"name": "La Serena-Coquimbo", "status": "latente", "pollutant": "MP10", "decree": "DS 4/2010 MMA"},
    ],
    "international": [
        {"name": "Acuerdo de París", "type": "Tratado", "ratified": 2017, "summary": "NDC: metas de reducción de emisiones"},
        {"name": "Convenio de Minamata", "type": "Tratado", "ratified": "DS 51/2018", "summary": "Reducción de mercurio"},
        {"name": "Convenio 169 OIT", "type": "Tratado", "ratified": "Ley 21.358", "summary": "Consulta indígena"},
    ],
    "sanctions": {
        "types": ["Amonestación por escrito", "Multa de 1 a 10,000 UTA", "Clausura temporal o definitiva", "Revocación de RCA"],
        "law": "Ley 20.417 (art. 38 y ss.)"
    }
}

def ingest():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    with driver.session() as session:
        # Create constraints
        for label in ["Institution", "Law", "Decree", "Regulation", "Zone", "InternationalTreaty"]:
            try:
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.name IS UNIQUE")
            except:
                pass
        
        # Create institutions
        for inst in FRAMEWORK["institutions"]:
            session.run("""
                MERGE (i:Institution {name: $name})
                SET i.acronym = $acronym,
                    i.created_by = $created_by,
                    i.year = $year,
                    i.role = $role
            """, inst)
        print(f"  Institutions: {len(FRAMEWORK['institutions'])}")
        
        # Create laws
        for law in FRAMEWORK["laws"]:
            session.run("""
                MERGE (l:Law {name: $number})
                SET l.full_name = $name,
                    l.year = $year,
                    l.summary = $summary
            """, law)
        print(f"  Laws: {len(FRAMEWORK['laws'])}")
        
        # Create decrees
        for dec in FRAMEWORK["decrees"]:
            session.run("""
                MERGE (d:Decree {name: $number})
                SET d.full_name = $name,
                    d.summary = $summary
            """, dec)
        print(f"  Decrees: {len(FRAMEWORK['decrees'])}")
        
        # Create zones
        for zone in FRAMEWORK["zones"]:
            session.run("""
                MERGE (z:Zone {name: $name})
                SET z.status = $status,
                    z.pollutant = $pollutant,
                    z.decree = $decree
            """, zone)
        print(f"  Zones: {len(FRAMEWORK['zones'])}")
        
        # Create international treaties
        for treaty in FRAMEWORK["international"]:
            session.run("""
                MERGE (t:InternationalTreaty {name: $name})
                SET t.type = $type,
                    t.ratified = $ratified,
                    t.summary = $summary
            """, {**treaty, "ratified": str(treaty["ratified"])})
        print(f"  Treaties: {len(FRAMEWORK['international'])}")
        
        # Create SanctionType nodes (needed for HAS_POWER relationships)
        sanction_types = [
            {"name": "Amonestación por escrito"},
            {"name": "Multa de 1 a 10,000 UTA"},
            {"name": "Clausura temporal o definitiva"},
            {"name": "Revocación de RCA"},
            {"name": "Normativa ambiental"},
            {"name": "Fiscalización ambiental"},
            {"name": "Evaluación de impacto ambiental"},
            {"name": "Justicia ambiental"},
        ]
        for st in sanction_types:
            session.run("MERGE (s:SanctionType {name: $name})", st)
        print(f"  SanctionTypes: {len(sanction_types)}")

        # Create Location nodes needed for Zone relationships
        locations = ["Región de Coquimbo", "Región de Atacama"]
        for loc in locations:
            session.run("MERGE (l:Location {name: $name})", name=loc)
        print(f"  Locations ensured: {len(locations)}")

        # Create relationships
        relationships = [
            # ESTABLISHES: Law → Institution
            ("19.300", "ESTABLISHES", "Servicio de Evaluación Ambiental", "Law", "Institution"),
            # CREATES: Law → Institution (Ley 20.417 crea MMA, SEA, SMA)
            ("20.417", "CREATES", "Ministerio del Medio Ambiente", "Law", "Institution"),
            ("20.417", "CREATES", "Servicio de Evaluación Ambiental", "Law", "Institution"),
            ("20.417", "CREATES", "Superintendencia del Medio Ambiente", "Law", "Institution"),
            ("20.600", "CREATES", "Tribunales Ambientales", "Law", "Institution"),
            # IMPLEMENTS: Decree → Law
            ("DS 40/2012 MMA", "IMPLEMENTS", "19.300", "Decree", "Law"),
            # Zones → Location
            ("Andacollo", "LOCATED_IN", "Región de Coquimbo", "Zone", "Location"),
            ("La Serena-Coquimbo", "LOCATED_IN", "Región de Coquimbo", "Zone", "Location"),
            # HAS_POWER: Institution → SanctionType
            ("Superintendencia del Medio Ambiente", "HAS_POWER", "Multa de 1 a 10,000 UTA", "Institution", "SanctionType"),
            ("Superintendencia del Medio Ambiente", "HAS_POWER", "Revocación de RCA", "Institution", "SanctionType"),
            ("Superintendencia del Medio Ambiente", "HAS_POWER", "Fiscalización ambiental", "Institution", "SanctionType"),
            ("Ministerio del Medio Ambiente", "HAS_POWER", "Normativa ambiental", "Institution", "SanctionType"),
            ("Servicio de Evaluación Ambiental", "HAS_POWER", "Evaluación de impacto ambiental", "Institution", "SanctionType"),
            ("Tribunales Ambientales", "HAS_POWER", "Justicia ambiental", "Institution", "SanctionType"),
            # IMPLEMENTS: Institution → Law (each institution implements its founding law)
            ("Ministerio del Medio Ambiente", "IMPLEMENTS", "20.417", "Institution", "Law"),
            ("Servicio de Evaluación Ambiental", "IMPLEMENTS", "19.300", "Institution", "Law"),
            ("Servicio de Evaluación Ambiental", "IMPLEMENTS", "20.417", "Institution", "Law"),
            ("Superintendencia del Medio Ambiente", "IMPLEMENTS", "20.417", "Institution", "Law"),
            ("Tribunales Ambientales", "IMPLEMENTS", "20.600", "Institution", "Law"),
            # ESTABLISHES: Law → Institution (additional)
            ("20.417", "ESTABLISHES", "Ministerio del Medio Ambiente", "Law", "Institution"),
            ("20.417", "ESTABLISHES", "Superintendencia del Medio Ambiente", "Law", "Institution"),
            ("20.600", "ESTABLISHES", "Tribunales Ambientales", "Law", "Institution"),
        ]
        
        created = 0
        failed = 0
        for src, rel, tgt, src_type, tgt_type in relationships:
            query = f"""
                MATCH (a:{src_type} {{name: $src}})
                MATCH (b:{tgt_type} {{name: $tgt}})
                MERGE (a)-[:{rel}]->(b)
                RETURN a.name AS src_name, b.name AS tgt_name
            """
            try:
                result = session.run(query, src=src, tgt=tgt)
                record = result.single()
                if record:
                    created += 1
                    print(f"    {src_type} [{record['src_name']}] -[{rel}]-> {tgt_type} [{record['tgt_name']}]")
                else:
                    failed += 1
                    print(f"    ⚠ FALLÓ: {src_type}:{src} -[{rel}]-> {tgt_type}:{tgt} (nodo no encontrado)")
            except Exception as e:
                failed += 1
                print(f"    ✗ ERROR: {src} -[{rel}]-> {tgt}: {e}")
        
        print(f"  Relaciones creadas: {created}, fallidas: {failed}")
        
        # Count everything
        result = session.run("""
            MATCH (n)
            WHERE n:Institution OR n:Law OR n:Decree OR n:Zone OR n:InternationalTreaty OR n:SanctionType
            RETURN labels(n)[0] AS type, count(n) AS count
            ORDER BY count DESC
        """)
        print("\n  Legal graph summary:")
        for r in result:
            print(f"    {r['type']}: {r['count']}")
    
    driver.close()
    print("\n✅ Legal framework ingested to Neo4j")

if __name__ == "__main__":
    ingest()
