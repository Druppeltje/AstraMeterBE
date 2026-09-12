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


async def test_single_phase_import_below_threshold_returns_zero(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [1500.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [0.0]


async def test_single_phase_import_above_threshold_returns_difference(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [2800.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [800.0]


async def test_single_phase_export_passes_through_unchanged(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [-1500.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [-1500.0]


async def test_zero_threshold_disables_peakshaving(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [2800.0, -500.0, 100.0]
    t = PeakshavingPowermeter(mock_powermeter, [0.0])
    assert await t.get_powermeter_watts() == [2800.0, -500.0, 100.0]


async def test_three_phase_total_below_threshold_scales_to_zero(mock_powermeter):
    """Total demand (600+500+400=1500) is under the 2000W threshold: all phases -> 0."""
    mock_powermeter.get_powermeter_watts.return_value = [600.0, 500.0, 400.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    result = await t.get_powermeter_watts()
    assert result == pytest.approx([0.0, 0.0, 0.0])


async def test_three_phase_total_above_threshold_scales_proportionally(mock_powermeter):
    """Total = 3000W, threshold = 2000W -> target total = 1000W (1/3 of original)."""
    mock_powermeter.get_powermeter_watts.return_value = [1500.0, 900.0, 600.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    result = await t.get_powermeter_watts()
    assert sum(result) == pytest.approx(1000.0)
    assert result == pytest.approx([500.0, 300.0, 200.0])


async def test_mixed_import_export_net_importer_stays_a_net_importer(mock_powermeter):
    """
    Regression test for the original bug: one exporting phase plus two
    importing phases must not sum to a negative (apparent export) total
    after shaving, when the household is actually a net importer.
    """
    # -1800 (export on phase 1) + 2000 + 2050 = 2250 total (net import)
    mock_powermeter.get_powermeter_watts.return_value = [-1800.0, 2000.0, 2050.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    result = await t.get_powermeter_watts()
    # target_total = 2250 - 2000 = 250; scale = 250/2250
    assert sum(result) == pytest.approx(250.0)
    assert sum(result) >= 0  # must never flip a net importer into apparent export


async def test_net_export_total_passes_through_unchanged(mock_powermeter):
    """If the household is a net exporter overall, peakshaving must not interfere with charging."""
    mock_powermeter.get_powermeter_watts.return_value = [-2000.0, 300.0, 200.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    result = await t.get_powermeter_watts()
    assert result == [-2000.0, 300.0, 200.0]


async def test_zero_total_passes_through(mock_powermeter):
    mock_powermeter.get_powermeter_watts.return_value = [0.0, 0.0, 0.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    assert await t.get_powermeter_watts() == [0.0, 0.0, 0.0]


async def test_int_values_from_powermeter(mock_powermeter):
    """Many powermeters return int values; peakshaving should handle them."""
    mock_powermeter.get_powermeter_watts.return_value = [2800, 0, 0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0])
    result = await t.get_powermeter_watts()
    assert result == pytest.approx([800.0, 0.0, 0.0])


async def test_multiple_differing_thresholds_uses_first_and_warns(mock_powermeter, caplog):
    """Per-phase thresholds don't make sense for a household concept; only the first is used."""
    mock_powermeter.get_powermeter_watts.return_value = [2800.0]
    t = PeakshavingPowermeter(mock_powermeter, [2000.0, 500.0])
    result = await t.get_powermeter_watts()
    assert result == pytest.approx([800.0])
    assert "only the first value" in caplog.text


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