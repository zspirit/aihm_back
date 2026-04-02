"""Tests for storage service (MinIO S3)."""
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


def test_ensure_bucket_creates():
    with patch("app.services.storage.s3_client") as mock_s3:
        mock_s3.head_bucket.side_effect = Exception("NoSuchBucket")
        mock_s3.create_bucket = MagicMock()
        from app.services.storage import ensure_bucket
        ensure_bucket("test-bucket")
        mock_s3.create_bucket.assert_called_once_with(Bucket="test-bucket")


def test_ensure_bucket_exists():
    with patch("app.services.storage.s3_client") as mock_s3:
        mock_s3.head_bucket.return_value = None  # Bucket exists
        mock_s3.create_bucket = MagicMock()
        from app.services.storage import ensure_bucket
        ensure_bucket("existing-bucket")
        mock_s3.create_bucket.assert_not_called()


def test_download_file():
    fake_bytes = b"%PDF-1.4 fake content"
    body_mock = MagicMock()
    body_mock.read.return_value = fake_bytes
    with patch("app.services.storage.s3_client") as mock_s3:
        mock_s3.get_object.return_value = {"Body": body_mock}
        from app.services.storage import download_file
        result = download_file("test-bucket", "path/to/file.pdf")
    assert result == fake_bytes
    mock_s3.get_object.assert_called_once_with(Bucket="test-bucket", Key="path/to/file.pdf")
