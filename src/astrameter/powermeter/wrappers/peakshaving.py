from astrameter.config.logger import logger
from astrameter.powermeter.base import Powermeter

from .base import PowermeterWrapper


class PeakshavingPowermeter(PowermeterWrapper):
    """
    A wrapper around a powermeter that reduces the reported TOTAL grid-import
    value, so the storage device only reacts (discharges) once real total
    import exceeds a configurable threshold ("peak shaving").

    Peakshaving operates on the sum across all phases, not per phase in
    isolation: clipping each phase independently would break the arithmetic
    relationship between phases (e.g. one exporting phase plus two importing
    phases could sum to a negative total after independent clipping, even
    though the household is a net importer). Instead, the shaved total is
    redistributed proportionally across the original phase values, preserving
    their relative contribution for downstream per-phase balancing logic.

    Convention: positive value = import from grid, negative value = export
    (PV surplus).

    Formula (on the summed total):
        total <= 0            ->  unchanged (net export/surplus: keep charging)
        0 < total <= threshold ->  target_total = 0
        total > threshold      ->  target_total = total - threshold

    Each phase is then scaled by (target_total / total) to reach the new sum
    while preserving relative phase distribution.
    """

    def __init__(
        self,
        wrapped_powermeter: Powermeter,
        thresholds: list[float],
    ) -> None:
        if not thresholds:
            raise ValueError("thresholds must be a non-empty list")
        super().__init__(wrapped_powermeter)
        # Peakshaving is a whole-household concept: use a single aggregate
        # threshold rather than per-phase values.
        self.threshold = thresholds[0]
        if len(thresholds) > 1 and len(set(thresholds)) > 1:
            logger.warning(
                "PEAKSHAVING_THRESHOLD has multiple differing values (%s); "
                "peakshaving applies to the household total, only the first "
                "value (%.1f) is used",
                thresholds,
                self.threshold,
            )

    def _apply_peakshaving(self, values: list[float]) -> list[float]:
        if self.threshold <= 0:
            return list(values)

        total = sum(values)

        if total <= 0:
            return list(values)  # net export/surplus: don't touch charging

        target_total = max(0.0, total - self.threshold)

        if total == 0:
            return list(values)

        scale = target_total / total
        return [value * scale for value in values]

    async def get_powermeter_watts(self) -> list[float]:
        values = await self.wrapped_powermeter.get_powermeter_watts()
        return self._apply_peakshaving(values)