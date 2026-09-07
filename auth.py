"""
Puerta de credenciales del pipeline La Serena Digital.

Ningún módulo debe abrir una conexión a Neo4j, Qdrant o MinerU por su cuenta.
Todos pasan por aquí, y aquí se garantiza que:

  1. El archivo `.env` se carga (antes nadie lo leía, pese a que el README
     manda crearlo con `cp .env.example .env`).
  2. La credencial existe, no está vacía y no sigue siendo el valor de
     ejemplo de `.env.example` (`your_password_here`, etc.).
  3. El servicio *acepta* esa credencial — no basta con que la variable esté
     definida. Se comprueba con una llamada real antes de devolver el cliente.
  4. Un fallo de autenticación aborta con un mensaje accionable, en vez de
     degradarse en un error confuso a mitad de la ingesta.

Uso desde un módulo:

    from auth import neo4j_driver, qdrant_client, mineru_headers

    driver = neo4j_driver()        # ya verificado, o lanza CredentialError

Diagnóstico manual del operador:

    python auth.py                 # revisa las tres credenciales y sale 0/2
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("auth")

# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class CredentialError(RuntimeError):
    """Problema de credenciales que impide operar contra un servicio."""


class MissingCredential(CredentialError):
    """La credencial no está definida, está vacía o sigue siendo un placeholder."""


class AuthenticationFailed(CredentialError):
    """La credencial existe pero el servicio la rechazó."""


class ExpiredCredential(CredentialError):
    """La credencial es válida en forma pero ya caducó."""


# ---------------------------------------------------------------------------
# Carga de .env
# ---------------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _strip_value(raw: str) -> str:
    """Quita comentario final y comillas de un valor de .env."""
    value = raw.strip()
    if value[:1] in {"'", '"'} and value[-1:] == value[:1] and len(value) >= 2:
        return value[1:-1]
    # Comentario inline solo si no está entre comillas.
    return value.split(" #", 1)[0].strip()


def find_env_file() -> Optional[Path]:
    """Localiza el .env: junto a este módulo primero, luego el directorio actual."""
    for candidate in (Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            return candidate
    return None


def load_env(path: Optional[Path] = None, *, override: bool = False) -> Dict[str, str]:
    """
    Carga el .env en os.environ y devuelve lo que cargó.

    Las variables ya presentes en el entorno ganan salvo `override=True`: quien
    exporta una credencial en la shell manda sobre el archivo.
    """
    env_path = path or find_env_file()
    loaded: Dict[str, str] = {}
    if env_path is None or not env_path.is_file():
        return loaded

    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        if not override and key in os.environ:
            continue
        value = _strip_value(raw)
        os.environ[key] = value
        loaded[key] = value
    return loaded


def ensure_env_loaded() -> bool:
    """Garantiza que el .env está cargado. Idempotente y segura de llamar en import."""
    return _ensure_env_loaded()


@lru_cache(maxsize=1)
def _ensure_env_loaded() -> bool:
    """Carga el .env una sola vez por proceso."""
    env_path = find_env_file()
    if env_path is None:
        log.debug("Sin archivo .env; se usan solo variables del entorno")
        return False
    loaded = load_env(env_path)
    log.debug("Cargadas %d variables desde %s", len(loaded), env_path)
    return True


# ---------------------------------------------------------------------------
# Validación de secretos
# ---------------------------------------------------------------------------

# Los valores de .env.example: si llegan hasta aquí, nadie editó el archivo.
_PLACEHOLDER_PATTERN = re.compile(r"^your[_-].*[_-]here$", re.IGNORECASE)
_PLACEHOLDER_LITERALS = {
    "changeme",
    "change_me",
    "password",
    "secret",
    "todo",
    "xxx",
    "<none>",
    "none",
    "null",
}


def is_placeholder(value: str) -> bool:
    """¿Este valor es un marcador de ejemplo en vez de una credencial real?"""
    candidate = value.strip()
    return bool(_PLACEHOLDER_PATTERN.match(candidate)) or candidate.lower() in _PLACEHOLDER_LITERALS


def redact(secret: Optional[str]) -> str:
    """Representación segura de un secreto para logs y mensajes de error."""
    if not secret:
        return "<vacío>"
    if len(secret) <= 8:
        return f"<oculto, {len(secret)} chars>"
    return f"{secret[:4]}…{secret[-4:]} ({len(secret)} chars)"


def require_secret(name: str, *, service: str, hint: str = "") -> str:
    """
    Devuelve el secreto `name` o lanza MissingCredential explicando cómo arreglarlo.

    Es el único camino permitido para leer una credencial: centraliza la
    detección de valores vacíos y de placeholders sin editar.
    """
    _ensure_env_loaded()
    raw = os.environ.get(name)
    suffix = f"\n  {hint}" if hint else ""

    if raw is None or not raw.strip():
        raise MissingCredential(
            f"{service}: falta la credencial {name}.\n"
            f"  Defínela en el archivo .env (copia .env.example) o expórtala "
            f"en el entorno antes de ejecutar.{suffix}"
        )

    value = raw.strip()
    if is_placeholder(value):
        raise MissingCredential(
            f"{service}: {name} sigue con el valor de ejemplo ({value!r}).\n"
            f"  Edita el .env y pon la credencial real.{suffix}"
        )
    return value


def _env_flag(name: str, default: bool = False) -> bool:
    """Lee una variable booleana del entorno."""
    _ensure_env_loaded()
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "si", "sí"}


# ---------------------------------------------------------------------------
# MinerU
# ---------------------------------------------------------------------------


def jwt_expiry(token: str) -> Optional[datetime]:
    """
    Lee el `exp` de un JWT sin validar la firma.

    Solo sirve para avisar de un token caducado antes de gastar la cuota de la
    API; la validación real la hace MinerU.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def _validated_mineru_token() -> str:
    """Token de MinerU validado en forma y vigencia. Se valida una vez por proceso."""
    token = require_secret(
        "MINERU_TOKEN",
        service="MinerU",
        hint="Obtén el token en https://mineru.net (API v4, formato JWT).",
    )

    expiry = jwt_expiry(token)
    if expiry is not None:
        now = datetime.now(timezone.utc)
        if expiry <= now:
            raise ExpiredCredential(
                f"MinerU: el MINERU_TOKEN caducó el {expiry.isoformat()}.\n"
                f"  Genera uno nuevo en https://mineru.net y actualiza el .env."
            )
        if expiry - now < timedelta(hours=24):
            log.warning(
                "MINERU_TOKEN caduca en menos de 24 h (%s). Renuévalo antes de "
                "lanzar un lote largo.",
                expiry.isoformat(),
            )
    elif token.count(".") != 2:
        log.warning(
            "MINERU_TOKEN no tiene forma de JWT (%s). Se enviará igualmente, "
            "pero revisa que sea el token correcto.",
            redact(token),
        )
    return token


def mineru_headers(*, content_type: bool = True) -> Dict[str, str]:
    """
    Cabeceras autenticadas para la API v4 de MinerU.

    Antes cada script hacía `f"Bearer {os.getenv('MINERU_TOKEN')}"`, que con la
    variable sin definir mandaba literalmente `Bearer None` y provocaba un
    rechazo que el código confundía con un error por archivo.
    """
    headers = {"Authorization": f"Bearer {_validated_mineru_token()}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


# Códigos y textos con los que MinerU señala un problema de credenciales.
_MINERU_AUTH_HINTS = ("token", "unauthorized", "unauthenticated", "forbidden", "auth")


def raise_for_auth(response, *, service: str = "MinerU") -> None:
    """
    Aborta si la respuesta indica un fallo de credenciales.

    Un 401/403 afecta a todas las peticiones, no solo a esta: seguir iterando
    sobre los PDFs restantes solo gasta tiempo y ensucia el log.
    """
    if response.status_code in (401, 403):
        raise AuthenticationFailed(
            f"{service} rechazó las credenciales (HTTP {response.status_code}).\n"
            f"  Revisa MINERU_TOKEN en el .env: puede estar caducado o ser de otra cuenta."
        )

    try:
        payload = response.json()
    except ValueError:
        return
    if not isinstance(payload, dict) or payload.get("code") in (0, None):
        return

    message = str(payload.get("msg", ""))
    if any(hint in message.lower() for hint in _MINERU_AUTH_HINTS):
        raise AuthenticationFailed(
            f"{service} rechazó las credenciales: {message}\n"
            f"  Revisa MINERU_TOKEN en el .env."
        )


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------


def neo4j_driver(*, verify: bool = True):
    """
    Driver de Neo4j con credenciales ya verificadas.

    `verify=True` comprueba que el servidor *acepta* usuario y contraseña; sin
    eso, un fallo de autenticación aparecía más tarde, dentro de la primera
    transacción y mezclado con errores de datos.
    """
    from neo4j import GraphDatabase
    from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

    _ensure_env_loaded()
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = require_secret(
        "NEO4J_PASSWORD",
        service="Neo4j",
        hint=f"Servidor configurado: {uri} (usuario {user!r}).",
    )

    driver = GraphDatabase.driver(uri, auth=(user, password))
    if not verify:
        return driver

    try:
        # verify_authentication comprueba las credenciales, no solo la ruta de red.
        verifier = getattr(driver, "verify_authentication", driver.verify_connectivity)
        verifier()
    except AuthError as exc:
        driver.close()
        raise AuthenticationFailed(
            f"Neo4j rechazó las credenciales de {user!r} en {uri}.\n"
            f"  Revisa NEO4J_USER y NEO4J_PASSWORD en el .env. Detalle: {exc}"
        ) from exc
    except (ServiceUnavailable, Neo4jError, OSError) as exc:
        driver.close()
        raise CredentialError(
            f"No se pudo contactar Neo4j en {uri}.\n"
            f"  Comprueba que el servicio está arriba y que NEO4J_URI es correcta. "
            f"Detalle: {exc}"
        ) from exc

    log.info("Neo4j autenticado: %s como %s", uri, user)
    return driver


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def qdrant_client(*, verify: bool = True):
    """
    Cliente de Qdrant con API key obligatoria.

    Antes se hacía `QdrantClient(url=..., api_key=None)`: si el servidor permitía
    acceso anónimo, el pipeline escribía vectores sin autenticarse y sin avisar.
    Ahora la API key es obligatoria salvo que se pida acceso anónimo de forma
    explícita con QDRANT_ALLOW_ANONYMOUS=true.
    """
    from qdrant_client import QdrantClient

    _ensure_env_loaded()
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")

    if _env_flag("QDRANT_ALLOW_ANONYMOUS"):
        log.warning(
            "QDRANT_ALLOW_ANONYMOUS=true: conectando a %s SIN autenticación. "
            "Solo apto para una instancia local de desarrollo.",
            url,
        )
        api_key = None
    else:
        api_key = require_secret(
            "QDRANT_API_KEY",
            service="Qdrant",
            hint=(
                f"Servidor configurado: {url}. Si es una instancia local sin "
                f"autenticación, define QDRANT_ALLOW_ANONYMOUS=true de forma explícita."
            ),
        )

    client = QdrantClient(url=url, api_key=api_key)
    if not verify:
        return client

    try:
        client.get_collections()
    except Exception as exc:  # el SDK envuelve los errores HTTP en varios tipos
        status = getattr(exc, "status_code", None)
        if status in (401, 403) or "401" in str(exc) or "403" in str(exc):
            client.close()
            raise AuthenticationFailed(
                f"Qdrant rechazó la API key en {url}.\n"
                f"  Revisa QDRANT_API_KEY en el .env. Detalle: {exc}"
            ) from exc
        client.close()
        raise CredentialError(
            f"No se pudo contactar Qdrant en {url}.\n"
            f"  Comprueba que el servicio está arriba y que QDRANT_URL es correcta. "
            f"Detalle: {exc}"
        ) from exc

    log.info("Qdrant autenticado: %s", url)
    return client


# ---------------------------------------------------------------------------
# Diagnóstico para el operador
# ---------------------------------------------------------------------------

SERVICES = ("neo4j", "qdrant", "mineru")


def check_service(service: str) -> Dict[str, str]:
    """Comprueba una credencial y devuelve un registro apto para imprimir."""
    result = {"service": service, "status": "ok", "detail": ""}
    try:
        if service == "neo4j":
            driver = neo4j_driver()
            driver.close()
            result["detail"] = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        elif service == "qdrant":
            client = qdrant_client()
            client.close()
            result["detail"] = os.environ.get("QDRANT_URL", "http://localhost:6333")
        elif service == "mineru":
            token = _validated_mineru_token()
            expiry = jwt_expiry(token)
            result["detail"] = (
                f"token {redact(token)}"
                + (f", caduca {expiry.isoformat()}" if expiry else "")
            )
        else:
            raise ValueError(f"Servicio desconocido: {service}")
    except CredentialError as exc:
        result["status"] = "FALLO"
        result["detail"] = str(exc)
    except ImportError as exc:
        result["status"] = "omitido"
        result["detail"] = f"dependencia no instalada: {exc}"
    return result


def preflight(services: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Comprueba las credenciales de los servicios indicados (por defecto, todos)."""
    return [check_service(name) for name in (services or list(SERVICES))]


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    requested = [a.lower() for a in (argv if argv is not None else sys.argv[1:])]
    unknown = [a for a in requested if a not in SERVICES]
    if unknown:
        print(f"Servicio desconocido: {', '.join(unknown)}", file=sys.stderr)
        print(f"Disponibles: {', '.join(SERVICES)}", file=sys.stderr)
        return 2

    env_path = find_env_file()
    print(f"Archivo .env: {env_path or 'no encontrado (se usan variables del entorno)'}\n")

    failures = 0
    for report in preflight(requested or None):
        marker = {"ok": "✅", "omitido": "⏭️ "}.get(report["status"], "❌")
        print(f"{marker} {report['service']}: {report['status']}")
        if report["detail"]:
            for line in report["detail"].splitlines():
                print(f"     {line}")
        if report["status"] == "FALLO":
            failures += 1
        print()

    if failures:
        print(f"{failures} servicio(s) sin credenciales válidas. Corrige el .env antes de ejecutar el pipeline.")
        return 2
    print("Todas las credenciales comprobadas son válidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
