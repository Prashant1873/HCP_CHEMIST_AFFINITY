import os
import sys
import unittest
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pincode_validator import PincodeSpatialValidator


class TestPincodeValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        geojson_path = "india_pincode.geojson"
        if not os.path.exists(geojson_path):
            raise unittest.SkipTest(f"'{geojson_path}' not found.")
        cls.validator = PincodeSpatialValidator(geojson_path=geojson_path)

    def test_validator_initialized(self):
        self.assertTrue(self.validator.is_ready)
        self.assertGreater(len(self.validator.pincodes), 15000)

    def test_exact_containment_connaught_place(self):
        # 110001 Connaught Place / New Delhi
        # Centroid of 110001 is approx (28.6234, 77.2187)
        res = self.validator.validate_coordinate(
            lat=28.6234,
            lon=77.2187,
            stated_pincode="110001",
            tolerance_km=0.5
        )
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["status"], "VALID_INSIDE")
        self.assertEqual(res["actual_pincode"], "110001")
        self.assertEqual(res["distance_km"], 0.0)

    def test_mismatch_delhi_coord_with_mumbai_pin(self):
        # Coordinates in New Delhi (110001), but stated pincode is Mumbai (400001)
        res = self.validator.validate_coordinate(
            lat=28.6234,
            lon=77.2187,
            stated_pincode="400001",
            tolerance_km=0.5
        )
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "MISMATCH_WRONG_PINCODE")
        self.assertEqual(res["actual_pincode"], "110001")
        self.assertGreater(res["distance_km"], 500.0)  # Over 500 km away!
        self.assertIn("400001", res["rejection_reason"])
        self.assertIn("110001", res["rejection_reason"])

    def test_invalid_coordinates(self):
        res = self.validator.validate_coordinate(
            lat="NaN",
            lon=None,
            stated_pincode="110001"
        )
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "MISSING_COORDINATES")

    def test_outside_india_bounds(self):
        res = self.validator.validate_coordinate(
            lat=51.5074,  # London
            lon=-0.1278,
            stated_pincode="110001"
        )
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["status"], "OUTSIDE_INDIA_BOUNDS")

    def test_dataframe_validation_splitting(self):
        test_df = pd.DataFrame([
            {"id": "D1", "name": "Delhi Doc", "lat": 28.6234, "lon": 77.2187, "pin": "110001"},
            {"id": "D2", "name": "Wrong Pin Doc", "lat": 28.6234, "lon": 77.2187, "pin": "400001"},
            {"id": "D3", "name": "Missing Coord", "lat": None, "lon": None, "pin": "110001"}
        ])

        verified_df, mismatched_df, summary = self.validator.validate_dataframe(
            df=test_df,
            lat_col="lat",
            lon_col="lon",
            pin_col="pin",
            role="doctor",
            tolerance_km=0.5
        )

        self.assertEqual(len(verified_df), 1)
        self.assertEqual(verified_df.iloc[0]["id"], "D1")
        self.assertEqual(len(mismatched_df), 2)
        self.assertEqual(summary["total_records"], 3)
        self.assertEqual(summary["verified_valid_records"], 1)
        self.assertEqual(summary["mismatched_removed_records"], 2)


if __name__ == "__main__":
    unittest.main()
