"""Bill generation engine with configurable denomination distribution."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .bill import Bill, VALID_DENOMINATIONS, BILL_VERSION
from .crypto_utils import generate_serial, compute_checksum, sign_checksum


DEFAULT_WEIGHTS: Dict[int, float] = {
    100: 0.10,
    50:  0.15,
    20:  0.25,
    10:  0.25,
    5:   0.15,
    1:   0.10,
}


class GenerationEngine:
    """Generates bills and writes them as individual JSON files under reserve_dir."""

    def __init__(
        self,
        reserve_dir: str,
        private_key=None,
        seed: Optional[str] = None,
        start_counter: int = 0,
    ):
        self.reserve_dir = Path(reserve_dir)
        self.private_key = private_key
        self.seed = seed
        self._counter = start_counter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        distribution: Dict[int, int],
        batch_id: Optional[str] = None,
    ) -> Tuple[str, List[Bill]]:
        """Generate bills per the given {denomination: count} mapping.

        Returns (batch_id, list_of_created_bills).
        """
        if batch_id is None:
            batch_id = str(uuid.uuid4())

        bills: List[Bill] = []
        for denomination in sorted(distribution):
            count = distribution[denomination]
            if denomination not in VALID_DENOMINATIONS:
                raise ValueError(f"Invalid denomination: {denomination}")
            denom_dir = self._denom_dir(denomination)
            denom_dir.mkdir(parents=True, exist_ok=True)
            for _ in range(count):
                bill = self._make_bill(denomination, batch_id)
                self._write_bill(bill, denom_dir)
                bills.append(bill)

        return batch_id, bills

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_distribution(spec: str) -> Dict[int, int]:
        """Parse 'denom:count[,denom:count,...]' into a {denom: count} dict."""
        result: Dict[int, int] = {}
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            denom_str, count_str = part.split(":")
            result[int(denom_str.strip())] = int(count_str.strip())
        return result

    @staticmethod
    def distribution_from_count(total: int, weights: Optional[Dict[int, float]] = None) -> Dict[int, int]:
        """Spread *total* bills across denominations according to *weights*."""
        weights = weights or DEFAULT_WEIGHTS
        result: Dict[int, int] = {}
        remaining = total
        items = sorted(weights.items())

        for i, (denom, weight) in enumerate(items):
            if i == len(items) - 1:
                result[denom] = max(1, remaining)
            else:
                count = max(1, round(total * weight))
                count = min(count, remaining - (len(items) - i - 1))
                result[denom] = count
                remaining -= count

        return {k: v for k, v in result.items() if v > 0}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _denom_dir(self, denomination: int) -> Path:
        return self.reserve_dir / f"{denomination}s"

    def _make_bill(self, denomination: int, batch_id: str) -> Bill:
        serial = generate_serial(self.seed, self._counter)
        self._counter += 1
        created_at = datetime.now(timezone.utc).isoformat()

        base = {
            "version": BILL_VERSION,
            "serial": serial,
            "denomination": denomination,
            "created_at": created_at,
            "batch_id": batch_id,
        }
        checksum = compute_checksum(base)
        signature = sign_checksum(checksum, self.private_key) if self.private_key else None

        return Bill(
            version=BILL_VERSION,
            serial=serial,
            denomination=denomination,
            created_at=created_at,
            batch_id=batch_id,
            checksum=checksum,
            signature=signature,
        )

    @staticmethod
    def _write_bill(bill: Bill, denom_dir: Path) -> Path:
        path = denom_dir / f"{bill.serial}.json"
        path.write_text(bill.to_json())
        return path
