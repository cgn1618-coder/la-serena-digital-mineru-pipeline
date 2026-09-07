# GeoAI Sci-Align Dataset — AGI4S Competition (Pista 1)

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![Competition: AGI4S Heywhale](https://img.shields.io/badge/Competition-AGI4S%20Heywhale-blue)](https://www.heywhale.com)

Dataset científico **Sci-Align** de geología ambiental chilena construido para la
**Pista 1 — Creación de bases de corpus** del concurso AGI4S (sh_AI Lab / Heywhale).

---

## Descripción

Este repositorio contiene el pipeline de construcción de un dataset multimodal alineado
(**Sci-Align**) basado en el expediente de Evaluación de Impacto Ambiental (EIA) del
proyecto minero **Dominga** (SEIA, Región de Coquimbo, Chile).

El dataset transforma documentos científicos legales trazables en conocimiento estructurado
mediante una ontología geológico-ambiental de 5 capas, integrando:

- Geología base (litología, estructuras, hidrogeología)
- Línea de base ecológica (flora, fauna, ecosistemas marinos)
- Datos espaciales georreferenciados (UTM 19S / WGS84)
- Cadena de trazabilidad metodológica (normas NCh, DS, EPA)
- Contexto normativo ambiental chileno (RCA, áreas protegidas, comunidades)

---

## Herramienta principal: MinerU

Siguiendo el requisito del concurso, **MinerU** es la cadena de herramientas principal
para extracción de contenido de PDFs científicos:

```bash
# Pipeline MinerU sobre expediente Dominga
python mineru_batch.py --input data/raw_pdfs/ --output output/mineru/
```

MinerU extrae texto estructurado, tablas y figuras preservando la jerarquía del documento,
lo que permite alineación precisa entre contenido y metadatos científicos.

Otras herramientas open source utilizadas: `PyMuPDF`, `pdfplumber`, `Neo4j`, `Qdrant`.
Todas las dependencias y versiones están documentadas en `requirements.txt`.

---

## Estructura del repositorio

```
├── auth.py                  # Puerta de credenciales: todo acceso pasa por aquí
├── mineru_batch.py          # Pipeline principal MinerU → JSON estructurado
├── mineru_ingest_neo4j.py   # JSON MinerU → grafo Neo4j
├── ingest.py                # Ingesta general con embeddings Qdrant
├── ingest_legal.py          # Ingesta documentos normativos
├── ingest_seia_projects.py  # Ingesta metadatos proyectos SEIA
├── requirements.txt         # Dependencias y versiones
├── .env.example             # Variables de entorno requeridas (sin credenciales)
├── tests/                   # Tests de la puerta de credenciales
└── dataset/
    └── sci_align/           # Dataset final en formato JSONL
```

---

## Ontología geológico-ambiental

El grafo de conocimiento (Neo4j) implementa una ontología de 5 capas:

| Capa | Entidades principales |
|------|-----------------------|
| Territorio físico | UnidadLitologica, FallaEstructura, CuencaHidrologica, Acuifero |
| Proyecto | Proyecto, ComponenteProyecto, AreaInfluencia |
| Línea de base | EstacionMuestreo, ParametroMedido, ResultadoAnalitico, Especie |
| Trazabilidad | Metodologia, Laboratorio, DocumentoFuente |
| Contexto normativo | NormaAmbiental, AreaProtegida, RegionComuna |

Toda entidad requiere `id` y `source` (documento + página SEIA).
Toda relación es trazable a evidencia documental.

---

## Formato del dataset (Sci-Align JSONL)

Cada registro integra texto, coordenadas, entidades y relaciones alineadas:

```json
{
  "id": "dominga_geo_001",
  "paradigma": "Sci-Align",
  "dominio": "geologia_ambiental",
  "fuente": {
    "documento": "EIA_Dominga_Cap3_LineaBase_Geologia.pdf",
    "pagina": 45,
    "procesado_con": "mineru"
  },
  "entidades": [...],
  "relaciones": [...],
  "multimodal": {
    "coordenadas_wgs84": [-29.847, -71.123],
    "figura_referencia": "Fig_3_2_mapa_geologia.png"
  }
}
```

---

## Instalación

```bash
git clone https://github.com/cgn1618-coder/la-serena-digital-mineru-pipeline
cd la-serena-digital-mineru-pipeline
pip install -r requirements.txt
cp .env.example .env
$EDITOR .env          # sustituye todos los valores your_..._here
python auth.py        # verifica que los servicios aceptan las credenciales
```

---

## Credenciales

Todo acceso a Neo4j, Qdrant y MinerU pasa por `auth.py`. Ningún módulo lee una
credencial por su cuenta, de modo que no hay forma de ejecutar una parte del
pipeline sin autenticarse antes.

`auth.py` garantiza, en cada arranque:

| Comprobación | Qué evita |
|--------------|-----------|
| Carga `.env` automáticamente | Que el archivo que pide este README se ignore en silencio |
| Rechaza credenciales ausentes o vacías | Cabeceras `Bearer None` y conexiones sin contraseña |
| Rechaza los placeholders `your_..._here` | Ejecutar con un `.env` sin editar |
| Exige `QDRANT_API_KEY` | Escribir vectores de forma anónima sin darse cuenta |
| Verifica la credencial contra el servicio | Descubrir el fallo a mitad de la ingesta |
| Comprueba la caducidad del JWT de MinerU | Gastar cuota con un token vencido |
| Aborta el lote ante un 401/403 | Repetir el mismo rechazo en cada PDF |

Diagnóstico antes de una ejecución larga:

```bash
python auth.py                # revisa los tres servicios; sale 0 si todo va bien
python auth.py neo4j qdrant   # solo los indicados
```

Los secretos nunca se imprimen enteros: los mensajes de error los muestran
ocultos (`abcd…wxyz (128 chars)`).

El acceso anónimo a Qdrant existe solo como excepción explícita
(`QDRANT_ALLOW_ANONYMOUS=true`) y registra un aviso en cada conexión.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

Los tests de `auth.py` no necesitan red ni las dependencias pesadas del
pipeline: los SDK se importan dentro de cada función.

---

## Fuentes de datos

- **Expediente Dominga** — Sistema de Evaluación de Impacto Ambiental (SEIA), Chile
  https://seia.sea.gob.cl
- **SciVerse** — Datasets científicos de referencia del concurso
  https://sciverse.opendatalab.com/

Los documentos del SEIA son de acceso público. El dataset derivado se publica bajo
licencia **CC-BY-4.0** — los datos brutos (PDFs originales) no se redistribuyen.

---

## Licencia

- **Código**: Apache 2.0
- **Dataset**: Creative Commons Attribution 4.0 (CC-BY-4.0)

---

## Concurso

**AGI4S — Pista 1: Creación de bases de corpus**
Organizado por sh_AI Lab en Heywhale.
Fase 1: marzo–mayo 2026.