"""Verifica JWT firmados de verdad y cache JWKS sin tráfico externo."""

import time
import unittest
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from app.core.security import jwt_handler as jwt


class JWTValidationTests(unittest.TestCase):
    def claims(self):
        return {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 60,
                "iss": "https://example.supabase.co/auth/v1", "aud": "authenticated"}

    def sign(self, claims, secret=None):
        return JsonWebToken(["HS256"]).encode({"alg": "HS256"}, claims,
            secret or jwt.settings.SUPABASE_JWT_SECRET.encode()).decode()

    def test_valid_supabase_token_and_long_literal_secret(self):
        secret = "a/long+literal-secret-that-looks-like-base64-but-is-not-decoded=="
        with patch.object(jwt.settings, "SUPABASE_JWT_SECRET", secret):
            claims = self.claims()
            self.assertEqual(jwt.decode_supabase_token(self.sign(claims)), claims)

    def test_supabase_requires_exp_subject_issuer_and_authenticated_audience(self):
        for field in ("exp", "sub", "iss", "aud"):
            claims = self.claims()
            claims.pop(field)
            with self.subTest(field=field):
                self.assertIsNone(jwt.decode_supabase_token(self.sign(claims)))
        for field, value in (("iss", "https://other-project.test/auth/v1"), ("aud", "service_role"),
                              ("exp", int(time.time()) - 5)):
            claims = {**self.claims(), field: value}
            self.assertIsNone(jwt.decode_supabase_token(self.sign(claims)))

    def test_local_tokens_require_exp_and_reject_supabase_issuer_even_with_same_secret(self):
        secret = jwt.settings.SECRET_KEY.encode()
        self.assertIsNone(jwt.decode_token(self.sign({"sub": str(uuid.uuid4())}, secret)))
        self.assertIsNone(jwt.decode_token(self.sign(self.claims(), secret)))
        legacy = {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 60}
        self.assertEqual(jwt.decode_token(self.sign(legacy, secret)), legacy)

    def test_new_local_tokens_include_issuer_and_zero_lifetime_is_preserved(self):
        token = jwt.create_access_token({"sub": str(uuid.uuid4())}, timedelta(0))
        claims = JsonWebToken(["HS256"]).decode(token, jwt.settings.SECRET_KEY.encode())
        self.assertEqual(claims["iss"], "geomaps")
        self.assertEqual(claims["exp"], claims["iat"])

    def test_malformed_tokens_do_not_fetch_keys(self):
        with patch.object(jwt, "_get_supabase_public_key") as fetch:
            for token in ("", "not.jwt", "not.a.jwt", "x" * (jwt.MAX_TOKEN_LENGTH + 1)):
                self.assertIsNone(jwt.decode_supabase_token(token))
            fetch.assert_not_called()

    def test_asymmetric_es256_and_rs256_signatures_are_verified(self):
        for alg, kty, size in (("ES256", "EC", "P-256"), ("RS256", "RSA", 2048)):
            with self.subTest(alg=alg):
                key = JsonWebKey.generate_key(kty, size, is_private=True)
                public = key.as_dict(is_private=False)
                public["alg"] = alg
                token = JsonWebToken([alg]).encode({"alg": alg, "kid": "test-key"}, self.claims(), key).decode()
                with patch.object(jwt, "_get_supabase_public_key", return_value=public):
                    self.assertIsNotNone(jwt.decode_supabase_token(token))
                public["alg"] = "HS256"
                with patch.object(jwt, "_get_supabase_public_key", return_value=public):
                    self.assertIsNone(jwt.decode_supabase_token(token))


class JWKSCacheTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("_supabase_jwks", {}), ("_last_jwks_fetch", None), ("_last_jwks_attempt", None)):
            patcher = patch.object(jwt, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unknown_kids_do_not_trigger_unbounded_downloads(self):
        response = Mock()
        response.json.return_value = {"keys": [{"kid": "known", "kty": "EC"}]}
        with patch.object(jwt.httpx, "get", return_value=response) as get, patch.object(jwt.time, "monotonic", return_value=100):
            self.assertIsNotNone(jwt._get_supabase_public_key("known"))
            for kid in ("unknown-1", "unknown-2", "unknown-3"):
                self.assertIsNone(jwt._get_supabase_public_key(kid))
            get.assert_called_once()

    def test_expired_keys_are_not_reused_on_network_failure(self):
        jwt._supabase_jwks = {"known": {"kid": "known", "kty": "EC"}}
        jwt._last_jwks_fetch = 0
        with patch.object(jwt.httpx, "get", side_effect=httpx.ConnectError("offline")) as get, patch.object(
            jwt.time, "monotonic", return_value=jwt.JWKS_TTL_SECONDS + 1
        ), self.assertLogs(jwt.logger, level="WARNING"):
            self.assertIsNone(jwt._get_supabase_public_key("known"))
            self.assertIsNone(jwt._get_supabase_public_key("known"))
            get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
