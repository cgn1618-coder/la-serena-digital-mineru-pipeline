"""
Tests de la puerta de credenciales (auth.py).

No requieren red ni las dependencias pesadas del pipeline (neo4j, qdrant,
sentence-transformers): auth.py importa esos SDK dentro de cada función, así
que la lógica de validación se puede probar aislada.

    python3 -m unittest discover -s tests -v
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402


def make_jwt(**claims) -> str:
    """Construye un JWT sintético (firma irrelevante: solo se leen los claims)."""
    def segment(obj) -> str:
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{segment({'alg': 'HS256', 'typ': 'JWT'})}.{segment(claims)}.firma-no-verificada"


def epoch(delta: timedelta) -> int:
    return int((datetime.now(timezone.utc) + delta).timestamp())


class AuthTestCase(unittest.TestCase):
    """Base que aísla el entorno: sin .env del disco y sin cachés heredadas."""

    def setUp(self):
        self._clear_caches()
        self.addCleanup(self._clear_caches)
        patcher = mock.patch.object(auth, "find_env_file", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _clear_caches():
        auth._ensure_env_loaded.cache_clear()
        auth._validated_mineru_token.cache_clear()

    def env(self, **values):
        """Reemplaza el entorno por completo y limpia cachés dependientes."""
        patcher = mock.patch.dict(os.environ, values, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._clear_caches()


# ---------------------------------------------------------------------------
# Carga de .env
# ---------------------------------------------------------------------------


class TestLoadEnv(AuthTestCase):
    def write_env(self, content: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / ".env"
        tmp.write_text(content, encoding="utf-8")
        return tmp

    def test_parses_plain_quoted_and_exported_values(self):
        path = self.write_env(
            "# comentario\n"
            "\n"
            "NEO4J_PASSWORD=s3cr3t\n"
            'QDRANT_API_KEY="con espacios"\n'
            "export MINERU_TOKEN='tok-123'\n"
            "NEO4J_URI=bolt://db:7687 # servidor interno\n"
            "linea basura sin igual\n"
        )
        self.env()
        loaded = auth.load_env(path)

        self.assertEqual(loaded["NEO4J_PASSWORD"], "s3cr3t")
        self.assertEqual(loaded["QDRANT_API_KEY"], "con espacios")
        self.assertEqual(loaded["MINERU_TOKEN"], "tok-123")
        self.assertEqual(loaded["NEO4J_URI"], "bolt://db:7687")
        self.assertNotIn("linea", loaded)
        self.assertEqual(os.environ["NEO4J_PASSWORD"], "s3cr3t")

    def test_environment_wins_over_file_by_default(self):
        """Quien exporta una credencial en la shell manda sobre el .env."""
        path = self.write_env("NEO4J_PASSWORD=del-archivo\n")
        self.env(NEO4J_PASSWORD="de-la-shell")

        auth.load_env(path)
        self.assertEqual(os.environ["NEO4J_PASSWORD"], "de-la-shell")

        auth.load_env(path, override=True)
        self.assertEqual(os.environ["NEO4J_PASSWORD"], "del-archivo")

    def test_missing_file_is_not_an_error(self):
        self.env()
        self.assertEqual(auth.load_env(Path("/no/existe/.env")), {})


# ---------------------------------------------------------------------------
# Detección de placeholders y ocultación de secretos
# ---------------------------------------------------------------------------


class TestPlaceholders(AuthTestCase):
    def test_detects_env_example_defaults(self):
        # Los tres valores literales que trae .env.example.
        for value in ("your_password_here", "your_qdrant_key_here", "your_mineru_jwt_here"):
            self.assertTrue(auth.is_placeholder(value), value)

    def test_detects_common_stand_ins(self):
        for value in ("changeme", "TODO", "none", "  password  "):
            self.assertTrue(auth.is_placeholder(value), value)

    def test_accepts_real_looking_secrets(self):
        for value in ("s3cr3t-real", "yourAppKey", "here_we_go"):
            self.assertFalse(auth.is_placeholder(value), value)


class TestRedact(AuthTestCase):
    def test_never_reveals_the_full_secret(self):
        secret = "abcdefghijklmnopqrstuvwxyz"
        masked = auth.redact(secret)
        self.assertNotIn(secret, masked)
        self.assertIn("abcd", masked)
        self.assertIn("wxyz", masked)

    def test_short_secrets_are_fully_hidden(self):
        self.assertNotIn("corto", auth.redact("corto"))
        self.assertEqual(auth.redact(""), "<vacío>")
        self.assertEqual(auth.redact(None), "<vacío>")


# ---------------------------------------------------------------------------
# require_secret
# ---------------------------------------------------------------------------


class TestRequireSecret(AuthTestCase):
    def test_missing_variable_names_itself_in_the_message(self):
        self.env()
        with self.assertRaises(auth.MissingCredential) as ctx:
            auth.require_secret("NEO4J_PASSWORD", service="Neo4j")
        self.assertIn("NEO4J_PASSWORD", str(ctx.exception))
        self.assertIn(".env", str(ctx.exception))

    def test_whitespace_only_is_treated_as_missing(self):
        self.env(NEO4J_PASSWORD="   ")
        with self.assertRaises(auth.MissingCredential):
            auth.require_secret("NEO4J_PASSWORD", service="Neo4j")

    def test_unedited_placeholder_is_rejected(self):
        self.env(QDRANT_API_KEY="your_qdrant_key_here")
        with self.assertRaises(auth.MissingCredential) as ctx:
            auth.require_secret("QDRANT_API_KEY", service="Qdrant")
        self.assertIn("ejemplo", str(ctx.exception))

    def test_hint_is_included_when_given(self):
        self.env()
        with self.assertRaises(auth.MissingCredential) as ctx:
            auth.require_secret("NEO4J_PASSWORD", service="Neo4j", hint="pista-concreta")
        self.assertIn("pista-concreta", str(ctx.exception))

    def test_returns_stripped_value(self):
        self.env(NEO4J_PASSWORD="  s3cr3t  ")
        self.assertEqual(auth.require_secret("NEO4J_PASSWORD", service="Neo4j"), "s3cr3t")


class TestEnvFlag(AuthTestCase):
    def test_truthy_and_falsy_values(self):
        for raw in ("1", "true", "TRUE", "yes", "on", "si", "sí"):
            self.env(QDRANT_ALLOW_ANONYMOUS=raw)
            self.assertTrue(auth._env_flag("QDRANT_ALLOW_ANONYMOUS"), raw)
        for raw in ("0", "false", "no", ""):
            self.env(QDRANT_ALLOW_ANONYMOUS=raw)
            self.assertFalse(auth._env_flag("QDRANT_ALLOW_ANONYMOUS"), raw)

    def test_absent_uses_default(self):
        self.env()
        self.assertFalse(auth._env_flag("QDRANT_ALLOW_ANONYMOUS"))
        self.assertTrue(auth._env_flag("QDRANT_ALLOW_ANONYMOUS", default=True))


# ---------------------------------------------------------------------------
# MinerU
# ---------------------------------------------------------------------------


class TestJwtExpiry(AuthTestCase):
    def test_reads_exp_claim(self):
        expiry = auth.jwt_expiry(make_jwt(exp=epoch(timedelta(days=3))))
        self.assertIsNotNone(expiry)
        self.assertGreater(expiry, datetime.now(timezone.utc))

    def test_returns_none_for_opaque_or_malformed_tokens(self):
        for token in ("no-es-un-jwt", "a.b", "a.@@@.c", make_jwt(sub="sin-exp")):
            self.assertIsNone(auth.jwt_expiry(token), token)


class TestMineruHeaders(AuthTestCase):
    def test_missing_token_aborts_instead_of_sending_bearer_none(self):
        """El bug original: sin token se mandaba literalmente 'Bearer None'."""
        self.env()
        with self.assertRaises(auth.MissingCredential):
            auth.mineru_headers()

    def test_placeholder_token_is_rejected(self):
        self.env(MINERU_TOKEN="your_mineru_jwt_here")
        with self.assertRaises(auth.MissingCredential):
            auth.mineru_headers()

    def test_expired_token_aborts_before_spending_quota(self):
        self.env(MINERU_TOKEN=make_jwt(exp=epoch(timedelta(days=-1))))
        with self.assertRaises(auth.ExpiredCredential) as ctx:
            auth.mineru_headers()
        self.assertIn("caduc", str(ctx.exception).lower())

    def test_valid_token_produces_bearer_header(self):
        token = make_jwt(exp=epoch(timedelta(days=30)))
        self.env(MINERU_TOKEN=token)
        headers = auth.mineru_headers()
        self.assertEqual(headers["Authorization"], f"Bearer {token}")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_content_type_can_be_omitted_for_get_requests(self):
        self.env(MINERU_TOKEN=make_jwt(exp=epoch(timedelta(days=30))))
        self.assertNotIn("Content-Type", auth.mineru_headers(content_type=False))

    def test_returned_dict_is_a_fresh_copy(self):
        self.env(MINERU_TOKEN=make_jwt(exp=epoch(timedelta(days=30))))
        first = auth.mineru_headers()
        first["Authorization"] = "manipulado"
        self.assertNotEqual(auth.mineru_headers()["Authorization"], "manipulado")

    def test_opaque_non_jwt_token_is_accepted_with_warning(self):
        self.env(MINERU_TOKEN="token-opaco-valido")
        with self.assertLogs(auth.log, level="WARNING"):
            headers = auth.mineru_headers()
        self.assertEqual(headers["Authorization"], "Bearer token-opaco-valido")


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("respuesta sin JSON")
        return self._payload


class TestRaiseForAuth(AuthTestCase):
    def test_http_401_and_403_abort(self):
        for status in (401, 403):
            with self.assertRaises(auth.AuthenticationFailed):
                auth.raise_for_auth(FakeResponse(status_code=status))

    def test_auth_error_in_body_aborts(self):
        resp = FakeResponse(payload={"code": "A0211", "msg": "token expired"})
        with self.assertRaises(auth.AuthenticationFailed):
            auth.raise_for_auth(resp)

    def test_per_file_error_does_not_abort_the_batch(self):
        """Un PDF demasiado grande es un error de ese archivo, no de credenciales."""
        resp = FakeResponse(payload={"code": 1001, "msg": "file exceeds page limit"})
        auth.raise_for_auth(resp)  # no debe lanzar

    def test_success_and_non_json_pass_through(self):
        auth.raise_for_auth(FakeResponse(payload={"code": 0, "data": {}}))
        auth.raise_for_auth(FakeResponse(payload=None))


# ---------------------------------------------------------------------------
# Qdrant: la regresión que motivó todo esto
# ---------------------------------------------------------------------------


class TestQdrantRequiresCredentials(AuthTestCase):
    def test_missing_api_key_aborts_instead_of_connecting_anonymously(self):
        """Antes: QdrantClient(api_key=None) escribía sin autenticarse y sin avisar."""
        self.env(QDRANT_URL="http://localhost:6333")
        fake_sdk = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"qdrant_client": fake_sdk}):
            with self.assertRaises(auth.MissingCredential) as ctx:
                auth.qdrant_client()
        fake_sdk.QdrantClient.assert_not_called()
        self.assertIn("QDRANT_ALLOW_ANONYMOUS", str(ctx.exception))

    def test_anonymous_access_requires_an_explicit_opt_in(self):
        self.env(QDRANT_URL="http://localhost:6333", QDRANT_ALLOW_ANONYMOUS="true")
        fake_sdk = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"qdrant_client": fake_sdk}):
            with self.assertLogs(auth.log, level="WARNING") as logs:
                auth.qdrant_client(verify=False)
        fake_sdk.QdrantClient.assert_called_once_with(
            url="http://localhost:6333", api_key=None
        )
        self.assertIn("SIN autenticación", "\n".join(logs.output))

    def test_api_key_is_passed_to_the_client(self):
        self.env(QDRANT_URL="http://qdrant:6333", QDRANT_API_KEY="clave-real")
        fake_sdk = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"qdrant_client": fake_sdk}):
            auth.qdrant_client(verify=False)
        fake_sdk.QdrantClient.assert_called_once_with(
            url="http://qdrant:6333", api_key="clave-real"
        )


class TestNeo4jRequiresCredentials(AuthTestCase):
    def test_missing_password_aborts_before_opening_a_driver(self):
        self.env(NEO4J_URI="bolt://db:7687", NEO4J_USER="neo4j")
        fake_sdk = mock.MagicMock()
        modules = {"neo4j": fake_sdk, "neo4j.exceptions": mock.MagicMock()}
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(auth.MissingCredential) as ctx:
                auth.neo4j_driver()
        fake_sdk.GraphDatabase.driver.assert_not_called()
        # El mensaje debe orientar al operador sobre qué servidor falló.
        self.assertIn("bolt://db:7687", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
