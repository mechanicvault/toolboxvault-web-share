"""Sheet row 113: the shared storage clients carry short
timeouts. boto3's defaults (60s connect/read, up to 5
retries) let a storage outage hold a request hostage for
minutes — the outside audit watched the Dealers page hang
for over a minute when storage didn't answer. The clients
must fail in seconds so callers can show an error or fall
back instead."""

from app.core import storage as storage_module


def test_shared_storage_clients_have_short_timeouts():
    # A fresh instance, not the shared singleton: the suite
    # swaps the singleton's clients for an in-memory fake
    # (sheet row 118), so the construction contract — every
    # S3Storage carries the short-timeout config — is what is
    # under test here.
    instance = storage_module.S3Storage()
    for client in (
        instance._client,
        instance._public_client,
    ):
        config = client.meta.config
        assert config.connect_timeout == 3
        assert config.read_timeout == 5
        assert config.retries["total_max_attempts"] == 2
