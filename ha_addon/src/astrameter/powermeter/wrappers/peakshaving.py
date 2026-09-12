from astrameter.config.logger import logger
from astrameter.powermeter.base import Powermeter

from .base import PowermeterWrapper


class PeakshavingPowermeter(PowermeterWrapper):
    """
    A wrapper around a powermeter that reports a reduced grid-import value
    to the storage device, so it only reacts (discharges) once real import
    exceeds a configurable threshold ("peak shaving").

    Convention: positive value = import from grid, negative value = export
    (PV surplus). Only positive (import) values are clipped; negative
    (export/surplus) values are passed through unchanged so charging
    behaviour is unaffected.

    Formula per value:
        value > 0  ->  max(0, value - threshold)
        value <= 0 ->  value

    Supports per-phase configuration, mirroring TransformedPowermeter: a
    single threshold applies to all phases, or one threshold per phase.
    """

    def __init__(
        self,
        wrapped_powermeter: Powermeter,
        thresholds: list[float],
    ) -> None:
        if not thresholds:
            raise ValueError("thresholds must be a non-empty list")
        super().__init__(wrapped_powermeter)
        self.thresholds = thresholds
        self._thresholds_mismatch_warned = False

    def _apply_peakshaving(self, values: list[float]) -> list[float]:
        result = []
        for i, value in enumerate(values):
            threshold = self.thresholds[i % len(self.thresholds)]
            if threshold <= 0:
                result.append(value)
            elif value > 0:
                result.append(max(0.0, value - threshold))
            else:
                result.append(value)

        if len(self.thresholds) > 1 and len(self.thresholds) != len(values):
            if not self._thresholds_mismatch_warned:
                logger.warning(
                    "PEAKSHAVING_THRESHOLD has %d values but powermeter returned %d phases",
                    len(self.thresholds),
                    len(values),
                )
                self._thresholds_mismatch_warned = True
        else:
            self._thresholds_mismatch_warned = False

        return result

    async def get_powermeter_watts(self) -> list[float]:
        values = await self.wrapped_powermeter.get_powermeter_watts()
        return self._apply_peakshaving(values)