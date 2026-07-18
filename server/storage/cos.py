from pathlib import Path
from typing import Any, BinaryIO, Optional

from qcloud_cos import CosConfig, CosS3Client

from ..settings import StorageSettings


class CosStorage:
    def __init__(self, settings: StorageSettings, client: Optional[Any] = None) -> None:
        self.settings = settings
        if client is None:
            config = CosConfig(
                Region=settings.cos_region,
                SecretId=settings.cos_secret_id,
                SecretKey=settings.cos_secret_key,
            )
            client = CosS3Client(config)
        self.client = client

    def put(self, key: str, stream: BinaryIO, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.settings.cos_bucket,
            Key=key,
            Body=stream,
            ContentType=content_type,
            ACL="private",
        )

    def download_to(self, key: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            Bucket=self.settings.cos_bucket,
            Key=key,
            DestFilePath=str(target),
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.settings.cos_bucket, Key=key)

    def move(self, source_key: str, target_key: str) -> None:
        self.client.copy_object(
            Bucket=self.settings.cos_bucket,
            Key=target_key,
            CopySource={
                "Bucket": self.settings.cos_bucket,
                "Key": source_key,
                "Region": self.settings.cos_region,
            },
            ACL="private",
        )
        self.delete(source_key)

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        return self.client.get_presigned_url(
            Bucket=self.settings.cos_bucket,
            Key=key,
            Method="GET",
            Expired=expires_seconds,
        )
