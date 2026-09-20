import pytest
from app.services.feishu.crypto import derive_token_key, encrypt_token, decrypt_token


class TestTokenCrypto:
    def test_round_trip(self):
        key = derive_token_key("test-secret")
        ct = encrypt_token("access-token-abc", key)
        assert decrypt_token(ct, key) == "access-token-abc"

    def test_different_ciphertexts_same_plaintext(self):
        key = derive_token_key("test-secret")
        ct1 = encrypt_token("same", key)
        ct2 = encrypt_token("same", key)
        assert ct1 != ct2  # random nonce

    def test_wrong_key_fails(self):
        key1 = derive_token_key("secret-a")
        key2 = derive_token_key("secret-b")
        ct = encrypt_token("data", key1)
        with pytest.raises(Exception):
            decrypt_token(ct, key2)

    def test_derived_key_stable(self):
        assert derive_token_key("s") == derive_token_key("s")
