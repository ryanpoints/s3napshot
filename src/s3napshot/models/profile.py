from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Profile:
    name: str
    endpoint_url: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str
    region: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "bucket_name": self.bucket_name,
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "region": self.region,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Profile:
        return cls(
            name=name,
            endpoint_url=data["endpoint_url"],
            bucket_name=data["bucket_name"],
            access_key_id=data["access_key_id"],
            secret_access_key=data["secret_access_key"],
            region=data.get("region", ""),
        )

    def safe_display(self) -> dict[str, Any]:
        masked = self.access_key_id[:3] + "****" if len(self.access_key_id) > 3 else "****"
        return {
            "name": self.name,
            "endpoint_url": self.endpoint_url,
            "bucket_name": self.bucket_name,
            "access_key_id": masked,
            "secret_access_key": "********",
            "region": self.region,
        }
