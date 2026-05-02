"""Aggregate index file: reconstructs totals and Merkle roots from the file system."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .merkle import compute_merkle_root

INDEX_FILENAME = "index.json"


class IndexManager:
    """Reads/writes reserve/index.json from the file hierarchy."""

    def __init__(self, reserve_dir: str):
        self.reserve_dir = Path(reserve_dir)
        self.index_path = self.reserve_dir / INDEX_FILENAME

    def rebuild(self) -> dict:
        """Walk the denomination folders and rebuild index.json from scratch."""
        self.reserve_dir.mkdir(parents=True, exist_ok=True)

        index: dict = {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_value": 0,
            "bill_count": 0,
            "denominations": {},
            "entries": [],
            "global_merkle_root": "",
        }

        all_checksums: List[str] = []

        for denom_dir in sorted(self.reserve_dir.iterdir()):
            if not denom_dir.is_dir() or not denom_dir.name.endswith("s"):
                continue
            try:
                denomination = int(denom_dir.name[:-1])
            except ValueError:
                continue

            denom_checksums: List[str] = []
            denom_entries: List[dict] = []

            for bill_file in sorted(denom_dir.glob("*.json")):
                try:
                    data = json.loads(bill_file.read_text())
                except Exception:
                    continue

                rel_path = str(bill_file.relative_to(self.reserve_dir.parent))
                denom_entries.append({
                    "serial":      data.get("serial", ""),
                    "denomination": data.get("denomination", denomination),
                    "file":        rel_path,
                    "checksum":    data.get("checksum", ""),
                    "batch_id":    data.get("batch_id", ""),
                    "created_at":  data.get("created_at", ""),
                })
                denom_checksums.append(data.get("checksum", ""))

            if not denom_entries:
                continue

            merkle_root = compute_merkle_root(denom_checksums)
            all_checksums.extend(denom_checksums)

            count = len(denom_entries)
            total_value = count * denomination
            index["denominations"][str(denomination)] = {
                "count":        count,
                "total_value":  total_value,
                "merkle_root":  merkle_root,
            }
            index["entries"].extend(denom_entries)
            index["total_value"] += total_value
            index["bill_count"] += count

        index["global_merkle_root"] = compute_merkle_root(all_checksums)

        with open(self.index_path, "w") as f:
            json.dump(index, f, indent=2, sort_keys=True)

        return index

    def load(self) -> Optional[dict]:
        if not self.index_path.exists():
            return None
        with open(self.index_path) as f:
            return json.load(f)
