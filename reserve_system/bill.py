"""Bill data model and serialization."""

from dataclasses import dataclass, asdict
from typing import Optional
import json


VALID_DENOMINATIONS = frozenset({1, 5, 10, 20, 50, 100})
BILL_VERSION = "1.0"


@dataclass
class Bill:
    version: str
    serial: str
    denomination: int
    created_at: str
    batch_id: str
    checksum: str
    signature: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["signature"] is None:
            del d["signature"]
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict) -> "Bill":
        return cls(
            version=data["version"],
            serial=data["serial"],
            denomination=data["denomination"],
            created_at=data["created_at"],
            batch_id=data["batch_id"],
            checksum=data["checksum"],
            signature=data.get("signature"),
        )

    @classmethod
    def from_json(cls, text: str) -> "Bill":
        return cls.from_dict(json.loads(text))
