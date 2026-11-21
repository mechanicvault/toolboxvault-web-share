"""Object-storage credentials (audit I5): the API must connect with the
least-privilege app user, and the settings must not even carry root
credentials anymore (the minio-init job owns those).
"""

import boto3

from app.core import storage as storage_module
from app.core.config import settings


def test_settings_have_no_root_credentials():
    assert not hasattr(settings, "minio_root_user")
    assert not hasattr(settings, "minio_root_password")


def test_storage_clients_use_the_app_user(monkeypatch):
    captured = []

    real_client = boto3.client

    def spy_client(*args, **kwargs):
        captured.append(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(storage_module.boto3, "client", spy_client)
    storage_module.S3Storage()

    assert len(captured) == 2  # internal + public signing client
    for kwargs in captured:
        assert kwargs["aws_access_key_id"] == settings.minio_app_user
        assert kwargs["aws_secret_access_key"] == settings.minio_app_password
