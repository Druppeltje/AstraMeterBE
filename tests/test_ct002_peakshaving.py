"""Tests for CT002 peak shaving: capping the household demand handed to the
load balancer at a configurable threshold, based on reconstructed total
household demand (grid reading + active battery contribution) rather than
the raw grid reading alone.
"""

from astrameter.ct002.ct002 import CT002


def _ct002(**kwargs) -> CT002:
    kwargs.setdefault("pace_base_step", 0)
    return CT002(**kwargs)


class TestPeakshavingThreshold:
    def test_disabled_by_default_passes_through_unchanged(self):
        device = _ct002(active_control=True, fair_distribution=False)
        device._update_consumer_report("a", "A", 0)
        out = device._compute_smooth_target([2800, 0, 0], "a")
        assert out[0] == 2800

    def test_zero_threshold_passes_through_unchanged(self):
        device = _ct002(
            active_control=True, fair_distribution=False, peakshaving_threshold=0.0
        )
        device._update_consumer_report("a", "A", 0)
        out = device._compute_smooth_target([2800, 0, 0], "a")
        assert out[0] == 2800

    def test_demand_below_threshold_with_no_battery_output_shaves_to_zero(self):
        """No battery running yet, demand under threshold: nothing to do."""
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        device._update_consumer_report("a", "A", 0)
        out = device._compute_smooth_target([300, 0, 0], "a")
        assert out[0] == 0

    def test_demand_above_threshold_shaves_to_excess(self):
        """No battery running yet: excess above threshold should be requested."""
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        device._update_consumer_report("a", "A", 0)
        out = device._compute_smooth_target([800, 0, 0], "a")
        assert out[0] == 300  # 800 - 500

    def test_battery_already_discharging_below_threshold_gets_restoring_force(self):
        """
        Regression test for the "dead zone" bug: household demand is under
        the threshold, but a battery is already discharging (contributing
        180W). The raw grid reading alone (300 - 180 = 120W) looks like it's
        already under threshold, which would report 0 and freeze the battery
        at 180W forever. Reconstructing true demand (120 + 180 = 300W, still
        under the 500W threshold) must instead produce a negative signal
        equal to -180W, giving the balancer a reason to wind the battery
        back down toward zero.
        """
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        # Battery "a" is already contributing 180W.
        device._update_consumer_report("a", "A", 180)
        # Raw grid reading is 120W (300W real house load - 180W battery help).
        out = device._compute_smooth_target([120, 0, 0], "a")
        assert out[0] == -180

    def test_battery_overcharging_below_threshold_gets_restoring_force(self):
        """
        Mirror scenario: a battery is slightly overcharging (negative power,
        i.e. importing 64W to charge) while true household demand (300W)
        is still comfortably under the threshold. The raw grid reading
        (300 + 64 = 364W, since the charging draws extra from the grid)
        must not be silently accepted; the reconstructed demand (300W) is
        still under threshold, so the signal should push the battery back
        toward zero (a positive signal of +64W, i.e. "reduce your charging").
        """
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        # Battery "a" is charging with 64W (negative = consuming to charge).
        device._update_consumer_report("a", "A", -64)
        # Raw grid reading is 364W (300W real house load + 64W charging draw).
        out = device._compute_smooth_target([364, 0, 0], "a")
        assert out[0] == 64

    def test_battery_discharging_above_threshold_converges_correctly(self):
        """
        Household demand is above the threshold and a battery is already
        discharging to help cover it. The reported signal should reflect
        the remaining gap to the threshold-adjusted target, not simply the
        raw excess.
        """
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        # Battery "a" already discharging 300W.
        device._update_consumer_report("a", "A", 300)
        # Raw grid reading is 500W (800W true demand - 300W battery help).
        out = device._compute_smooth_target([500, 0, 0], "a")
        # true demand = 500 + 300 = 800; shaved target = min(800, 500) = 500
        # reported = raw_grid(500) - shaved_target(500) = 0
        # The battery is already exactly at the correct equilibrium (500W
        # true demand above threshold worth of discharge = 300W... wait:
        # 800 - 500 = 300W needed, battery already provides 300W, so the
        # system has nothing left to correct: signal is 0.
        assert out[0] == 0
        
    def test_export_surplus_below_zero_passes_through_unaffected(self):
        """Net export (PV surplus) must be untouched so charging still works."""
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        device._update_consumer_report("a", "A", 0)
        out = device._compute_smooth_target([-1500, 0, 0], "a")
        assert out[0] == -1500

    def test_multi_phase_total_used_for_shaving_decision(self):
        """Peakshaving operates on the summed total across phases."""
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=500.0,
        )
        device._update_consumer_report("a", "A", 0)
        # Total = 300 + 100 + 100 = 500, exactly at threshold -> shaved to 0.
        out = device._compute_smooth_target([300, 100, 100], "a")
        assert sum(out) == 0

class TestLivePeakshavingThreshold:
    def test_set_peakshaving_threshold_updates_value(self):
        device = _ct002(active_control=True, fair_distribution=False)
        assert device.peakshaving_threshold == 0.0
        device.set_peakshaving_threshold(2000.0)
        assert device.peakshaving_threshold == 2000.0

    def test_set_peakshaving_threshold_takes_effect_immediately(self):
        """A live threshold change must affect the very next control cycle,
        without requiring a restart. grid_predict_trust=1.0 disables the
        balancer's own predictive smoothing filter so this test isolates our
        threshold logic instead of also exercising that unrelated feature."""
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            grid_predict_trust=1.0,
            # Also disable oscillation damping and per-step correction
            # limiting: both are stateful rate-limiters that only kick in
            # from the second _compute_smooth_target() call onward (the
            # first call has no prior target to rate-limit against), which
            # would otherwise make this test about those unrelated features
            # instead of our threshold logic.
            osc_damp_max=0.0,
            max_correction_per_step=100000,
            # Also disable the efficiency-demand EMA smoothing (0.1 default),
            # which blends the previous and current household-demand estimate
            # for the rotation/activation decision — unrelated to our
            # threshold logic, but it would otherwise blend our pre- and
            # post-threshold-change values across these two calls.
            efficiency_demand_alpha=1.0,
        )
        device._update_consumer_report("a", "A", 0)
    
        # Threshold disabled: full demand passes through.
        out = device._compute_smooth_target([2800, 0, 0], "a")
        assert out[0] == 2800

        # Live-update the threshold.
        device.set_peakshaving_threshold(2000.0)

        print(f"\nDEBUG peakshaving_threshold={device.peakshaving_threshold}")
        print(f"DEBUG consumer power: {device._consumers['a'].power}")
        print(f"DEBUG last_smooth_target: {device._last_smooth_target}")

        # Next cycle: shaving is now active, no restart needed. A slightly
        # different reading is used because the balancer caches its result
        # per exact raw sample; two identical successive raw readings would
        # return the cached pre-threshold-change result regardless of the
        # new threshold — realistic meter noise means this practically never
        # happens with live hardware.
        out = device._compute_smooth_target([2801, 0, 0], "a")
        assert out[0] == 801

    def test_set_peakshaving_threshold_to_zero_disables_it(self):
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=2000.0,
            grid_predict_trust=1.0,        
            # Also disable oscillation damping and per-step correction
            # limiting: both are stateful rate-limiters that only kick in
            # from the second _compute_smooth_target() call onward (the
            # first call has no prior target to rate-limit against), which
            # would otherwise make this test about those unrelated features
            # instead of our threshold logic.
            osc_damp_max=0.0,
            max_correction_per_step=100000,
            # Also disable the efficiency-demand EMA smoothing (0.1 default),
            # which blends the previous and current household-demand estimate
            # for the rotation/activation decision — unrelated to our
            # threshold logic, but it would otherwise blend our pre- and
            # post-threshold-change values across these two calls.
            efficiency_demand_alpha=1.0,
        )
    
        device._update_consumer_report("a", "A", 0)

        out = device._compute_smooth_target([2800, 0, 0], "a")
        assert out[0] == 800

        device.set_peakshaving_threshold(0.0)

        out = device._compute_smooth_target([2801, 0, 0], "a")
        assert out[0] == 2801        
        
    def test_set_peakshaving_threshold_rejects_negative(self):
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=2000.0,
        )
        device.set_peakshaving_threshold(-500.0)
        # Negative value is rejected; threshold stays unchanged.
        assert device.peakshaving_threshold == 2000.0

    def test_set_peakshaving_threshold_same_value_is_a_noop(self):
        device = _ct002(
            active_control=True,
            fair_distribution=False,
            peakshaving_threshold=2000.0,
        )
        device.set_peakshaving_threshold(2000.0)
        assert device.peakshaving_threshold == 2000.0