"""Master ledger: tracks total supply, issuance batches, and file references."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

LEDGER_VERSION = "1.0"


class Ledger:
    """Append-only log of every bill generation event."""

    def __init__(self, ledger_path: str):
        self.path = Path(ledger_path)
        self._data = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_batch(
        self,
        batch_id: str,
        distribution: Dict[int, int],
        seed: Optional[str],
        signed: bool,
    ) -> None:
        """Append a batch record and persist."""
        bill_count = sum(distribution.values())
        total_value = sum(d * c for d, c in distribution.items())

        self._data["batches"].append({
            "batch_id": batch_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "signed": signed,
            "bills_generated": bill_count,
            "total_value": total_value,
            "denomination_distribution": {str(k): v for k, v in sorted(distribution.items())},
            "status": "committed",
        })
        self._data["total_value"] += total_value
        self._data["bill_count"] += bill_count
        self._save()

    @property
    def total_value(self) -> int:
        return self._data["total_value"]

    @property
    def bill_count(self) -> int:
        return self._data["bill_count"]

    @property
    def batches(self) -> List[dict]:
        return self._data["batches"]

    def to_dict(self) -> dict:
        return dict(self._data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {
            "version": LEDGER_VERSION,
            "total_value": 0,
            "bill_count": 0,
            "batches": [],
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
