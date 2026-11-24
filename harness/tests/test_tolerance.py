"""The tolerance decision, which must come out the same whoever asks."""

import unittest

from harness import checks, tolerance


def record(day, seconds, run_id=None, ci=False):
    return {
        "run_id": run_id or f"{day.replace('-', '')}T000000+0000",
        "started_at": f"{day}T00:00:00+00:00",
        "ci": ci,
        "measurements": {} if seconds is None else {"redrive_seconds": seconds},
    }


def spread_of(values):
    """A set of records on distinct days holding these timings."""
    return [record(f"2026-12-{i + 1:02d}", v, run_id=f"r{i}")
            for i, v in enumerate(values)]


class TestObservations(unittest.TestCase):
    def test_skips_runs_that_never_got_that_far(self):
        # A run that aborts before the redrive records no timing, which is
        # why the criterion counts observations rather than nights.
        records = [record("2026-12-01", None), record("2026-12-02", 120.0)]
        found = tolerance.observations(records)
        self.assertEqual([o.seconds for o in found], [120.0])

    def test_reads_the_day_and_the_origin(self):
        found = tolerance.observations([record("2026-12-01", 120.0, ci=True)])
        self.assertEqual(found[0].day, "2026-12-01")
        self.assertTrue(found[0].ci)

    def test_counts_distinct_days_not_runs(self):
        records = [record("2026-12-01", 120.0, run_id="a"),
                   record("2026-12-01", 130.0, run_id="b")]
        self.assertEqual(tolerance.assess(records).days, 1)


class TestVerdict(unittest.TestCase):
    def test_too_few_observations_waits(self):
        assessment = tolerance.assess(spread_of([120.0, 130.0, 125.0]))
        self.assertEqual(assessment.verdict, tolerance.WAIT)
        self.assertTrue(any("observations" in r for r in assessment.reasons))

    def test_enough_observations_on_too_few_days_waits(self):
        # Ten runs in one afternoon are still one afternoon, which is exactly
        # the flaw in the first three real observations.
        records = [record("2026-12-01", 120.0 + i, run_id=f"r{i}")
                   for i in range(12)]
        assessment = tolerance.assess(records)
        self.assertEqual(assessment.verdict, tolerance.WAIT)
        # Matched on "distinct" rather than "distinct days": the reason
        # pluralises, and the first version of this assertion broke on the
        # singular. Tests should match the thing, not its spelling.
        self.assertTrue(any("distinct" in r for r in assessment.reasons))

    def test_a_tight_spread_over_enough_days_promotes(self):
        values = [120.0, 130.0, 125.0, 118.0, 135.0, 128.0, 122.0,
                  131.0, 126.0, 124.0]
        assessment = tolerance.assess(spread_of(values))
        self.assertEqual(assessment.verdict, tolerance.PROMOTE)
        self.assertIsNotNone(assessment.band)

    def test_a_wide_spread_retires_rather_than_promoting(self):
        # The outcome the receive count got. A band wide enough to absorb this
        # would accept a lab whose retry behaviour had changed.
        values = [90.0, 300.0, 120.0, 280.0, 100.0, 260.0, 110.0,
                  240.0, 130.0, 250.0]
        assessment = tolerance.assess(spread_of(values))
        self.assertEqual(assessment.verdict, tolerance.RETIRE)
        self.assertIsNone(assessment.band)
        self.assertTrue(any("not determinate" in r for r in assessment.reasons))

    def test_the_proposed_band_contains_every_observation(self):
        values = [120.0, 130.0, 125.0, 118.0, 135.0, 128.0, 122.0,
                  131.0, 126.0, 124.0]
        assessment = tolerance.assess(spread_of(values))
        low, high = assessment.band
        for observation in assessment.observations:
            self.assertGreaterEqual(observation.seconds, low)
            self.assertLessEqual(observation.seconds, high)

    def test_the_band_comes_from_the_record_not_the_nominal(self):
        values = [200.0] * 10
        assessment = tolerance.assess(spread_of(values))
        low, high = assessment.band
        criterion = checks.REDRIVE_PROMOTION
        self.assertAlmostEqual(low, 200.0 * criterion["band_low_factor"])
        self.assertAlmostEqual(high, 200.0 * criterion["band_high_factor"])


class TestItReadsTheOneCriterion(unittest.TestCase):
    def test_the_default_is_the_criterion_in_checks(self):
        # No local copy of the thresholds: a threshold kept in two places
        # disagreed with itself within three runs when it was the redrive
        # observations.
        records = spread_of([120.0, 130.0, 125.0])
        loose = dict(checks.REDRIVE_PROMOTION,
                     min_observations=3, min_distinct_days=3)
        self.assertEqual(tolerance.assess(records).verdict, tolerance.WAIT)
        self.assertEqual(tolerance.assess(records, loose).verdict,
                         tolerance.PROMOTE)

    def test_the_module_hardcodes_no_thresholds(self):
        source = (tolerance.__file__)
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        for key in ("min_observations", "min_distinct_days",
                    "max_relative_spread", "band_low_factor"):
            self.assertNotIn(f'"{key}": ', text,
                             f"{key} is redefined here instead of read from checks")


class TestRender(unittest.TestCase):
    def test_prints_every_observation_for_a_person_to_look_at(self):
        text = tolerance.render(tolerance.assess(spread_of([120.0, 145.0])))
        self.assertIn("120.0s", text)
        self.assertIn("145.0s", text)

    def test_names_what_it_does_not_decide(self):
        # Claiming to settle bimodality from ten points would be the same
        # mistake as writing one observation down as a fact.
        text = tolerance.render(tolerance.assess(spread_of([120.0])))
        self.assertIn("bimodal", text)
        self.assertIn("weekday", text)

    def test_says_how_to_promote_when_it_says_promote(self):
        values = [120.0, 130.0, 125.0, 118.0, 135.0, 128.0, 122.0,
                  131.0, 126.0, 124.0]
        text = tolerance.render(tolerance.assess(spread_of(values)))
        self.assertIn("gating=True", text)
        self.assertIn("harness/checks.py", text)

    def test_compares_the_proposed_band_with_the_current_one(self):
        values = [120.0, 130.0, 125.0, 118.0, 135.0, 128.0, 122.0,
                  131.0, 126.0, 124.0]
        text = tolerance.render(tolerance.assess(spread_of(values)),
                                nominal=105)
        self.assertIn("current band", text)
        self.assertIn("wider", text)


class TestAgainstTheRealRecord(unittest.TestCase):
    def test_the_real_record_says_wait(self):
        from harness.report import load_records
        records = load_records(tolerance.ROOT / "health" / "health.jsonl")
        assessment = tolerance.assess(records)
        self.assertEqual(assessment.verdict, tolerance.WAIT)
        # Three observations, all from one day, which is the honest state.
        self.assertLess(assessment.days, 7)


if __name__ == "__main__":
    unittest.main()
