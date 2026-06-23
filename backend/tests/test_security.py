from odin.security import generate_token, hash_token, verify_token


def test_generate_token_has_prefix_and_entropy():
    token = generate_token()
    assert token.startswith("odin_pat_")
    assert len(token) > len("odin_pat_") + 30
    assert generate_token() != generate_token()


def test_hash_is_deterministic_and_not_reversible():
    token = generate_token()
    digest = hash_token(token)
    assert digest == hash_token(token)
    assert token not in digest
    assert len(digest) == 64


def test_verify_token():
    token = generate_token()
    digest = hash_token(token)
    assert verify_token(token, digest) is True
    assert verify_token("odin_pat_wrong", digest) is False
