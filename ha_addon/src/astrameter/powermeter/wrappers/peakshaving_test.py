from unittest.mock import AsyncMock, Mock

import pytest

from .peakshaving import PeakshavingPowermeter


@pytest.fixture
def mock_powermeter():
    pm = Mock()
    pm.get_powermeter_watts = AsyncMock()
    pm.get_powermeter_watts_raw = AsyncMock()
    pm.wait_for_message = AsyncMock()
    pm.wait_for_next_message = AsyncMock()
    return pm


async def test_import_below_threshold_returns_zero(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [1500.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [0.0]


async def test_import_above_threshold_returns_difference(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [2800.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [800.0]


async def test_import_exactly_at_threshold_returns_zero(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [2000.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [0.0]


async def test_export_surplus_passes_through_unchanged(mock_powermeter):
    """Negative values (PV surplus) must be untouched, so charging keeps working."""
    mock_powermeter.get_powermeter_watts.return_value = [-1500.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [-1500.0]


async def test_zero_value_passes_through(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [0.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [0.0]


async def test_zero_threshold_disables_peakshaving(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [2800.0]
    t = PeakshavingPowermeter(mock_powermeter, [0.0])
    assert await t.get_powermeter_watts() == [2800.0]


async def test_per_phase_thresholds(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [1000.0, 2000.0, 3000.0]
    t = PeakshavingPowermeter(mock_powermeter, [500.0, 500.0, 500.0])
    assert await t.get_powermeter_watts() == [500.0, 1500.0, 2500.0]


async def test_mixed_import_and_export_phases(mock_powermeter):
    """One phase importing above threshold, one exporting: only the import phase is clipped."""
    mock_powermeter.get_powermeter_watts.return_value = [2800.0, -1500.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [800.0, -1500.0]


async def test_phase_count_mismatch_does_not_crash(mock_powermeter):
    """Per-phase count != returned value count should not raise; uses cyclic indexing."""
    mock_powermeter.get_powermeter_watts.return_value = [2800.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0, 100.0, 100.0])
    result = await t.get_powermeter_watts()
    assert result == [800.0]


async def test_int_values_from_powermeter(mock_powermeter):
    """Many powermeters return int values; peakshaving should handle them."""
    mock_powermeter.get_powermeter_watts.return_value = [2800]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [800.0]


async def test_wait_for_message_passthrough(mock_powermeter):
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    await t.wait_for_message(timeout=30)
    mock_powermeter.wait_for_message.assert_called_once_with(30)


async def test_wait_for_next_message_passthrough(mock_powermeter):
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    await t.wait_for_next_message(timeout=10)
    mock_powermeter.wait_for_next_message.assert_called_once_with(10)


def test_empty_thresholds_raises(mock_powermeter):
    with pytest.raises(ValueError, match="thresholds must be a non-empty list"):
        PeakshavingPowermeter(mock_powermeter, [])