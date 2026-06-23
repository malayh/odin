import pytest
from odin.services import blobs

pytestmark = pytest.mark.live


async def test_put_get_roundtrip_is_content_addressed():
    data = b"hello blob world"
    uri = await blobs.put(data)
    assert uri == await blobs.put(data)
    assert await blobs.get(uri) == data
    assert await blobs.exists(uri) is True


async def test_missing_blob_does_not_exist():
    missing = "s3://odin/" + "0" * 64
    assert await blobs.exists(missing) is False
