import os
import sys
import unittest
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.entity_resolver import (
    normalize_chemist_name,
    calculate_name_similarity,
    resolve_and_deduplicate_chemists
)
from src.data_cleaning import (
    filter_suspicious_coordinate_centroids,
    filter_incomplete_addresses
)


class TestEntityResolver(unittest.TestCase):
    def test_name_normalization(self):
        cases = [
            ("BHATIYA MEDICAL", "BHATIA"),
            ("BHATIA MEDICAL STORES", "BHATIA"),
            ("BHATIA MEDICAL&SUPER STORES", "BHATIA"),
            ("BON BON MEDICAL & GENERAL STORE", "BON BON"),
            ("BON BON MEDICAL AND GENERAL STORE", "BON BON"),
            ("GEMINI MEDICO", "GEMINI"),
            ("SHREE SAI MEDICAL STORE", "SHRI SAI"),
            ("SHRI SAI CHEMIST & DRUGGIST", "SHRI SAI"),
            ("MAHALAXMI MEDICAL & GEN STORES", "MAHALAKSHMI"),
            ("M/S NOBLE CHEMIST", "NOBLE"),
            ("APOLLO PHARMACY PVT LTD", "APOLLO"),
        ]
        for raw, expected in cases:
            norm = normalize_chemist_name(raw)
            self.assertEqual(
                norm, expected,
                f"Failed for '{raw}': expected '{expected}', got '{norm}'"
            )

    def test_similarity_scoring(self):
        # Similar / Same store variations
        self.assertGreaterEqual(
            calculate_name_similarity("BHATIA MEDICAL", "BHATIYA MEDICAL STORES"), 0.90
        )
        self.assertGreaterEqual(
            calculate_name_similarity("BON BON MEDICAL & GENERAL STORE", "BON BON MEDICAL AND GENERAL STORE"), 0.95
        )
        self.assertGreaterEqual(
            calculate_name_similarity("GEMINI MEDICO", "GEMINI MEDICAL STORE"), 0.90
        )
        self.assertGreaterEqual(
            calculate_name_similarity("KISHOR CHEMIST", "KISHORE MEDICAL"), 0.85
        )
        # Dissimilar stores
        self.assertLess(
            calculate_name_similarity("OM SAI MEDICAL", "SHREE GANESH MEDICAL"), 0.40
        )
        self.assertLess(
            calculate_name_similarity("APOLLO PHARMACY", "WELLNESS FOREVER"), 0.35
        )

    def test_multi_iqvia_deduplication_exact_coords(self):
        # 3 IQVIA IDs for the exact same store at same coordinates
        df = pd.DataFrame([
            {
                "chemist_id": "MUM001172",
                "chemist_name": "BHATIYA MEDICAL",
                "chemist_latitude": 19.0797533,
                "chemist_longitude": 72.8536251,
                "chemist_pincode": "400055",
                "chem_address": "Shop 4, Vakul Chawl, N.M. Joshi Marg"
            },
            {
                "chemist_id": "MUM008316",
                "chemist_name": "BHATIA MEDICAL STORES",
                "chemist_latitude": 19.0797533,
                "chemist_longitude": 72.8536251,
                "chemist_pincode": "400055",
                "chem_address": "4 Vakul Chawl, NM Joshi Marg"
            },
            {
                "chemist_id": "MUM007631",
                "chemist_name": "BHATIA MEDICAL&SUPER STORES",
                "chemist_latitude": 19.0797533,
                "chemist_longitude": 72.8536251,
                "chemist_pincode": "400055",
                "chem_address": "Shop 4, Vakul Chawl, NM Joshi Marg"
            },
            # Distinct other pharmacy
            {
                "chemist_id": "MUM008927",
                "chemist_name": "MAHAVIR MEDICAL",
                "chemist_latitude": 19.080874,
                "chemist_longitude": 72.852598,
                "chemist_pincode": "400055",
                "chem_address": "Station Road, Santacruz East"
            }
        ])

        canonical_df, merged_df, summary = resolve_and_deduplicate_chemists(df)

        self.assertEqual(len(canonical_df), 2, "Expected 2 canonical physical pharmacies")
        self.assertEqual(len(merged_df), 2, "Expected 2 secondary records merged")
        
        # Check alias tracking on Bhatia medical
        bhatia_row = canonical_df[canonical_df["chemist_name"].str.contains("BHATIA")].iloc[0]
        self.assertEqual(bhatia_row["alias_count"], 3)
        self.assertIn("MUM001172", bhatia_row["aliased_iqvia_ids"])
        self.assertIn("MUM008316", bhatia_row["aliased_iqvia_ids"])
        self.assertIn("MUM007631", bhatia_row["aliased_iqvia_ids"])

    def test_gps_jitter_deduplication(self):
        # Same pharmacy mapped ~15 meters apart with slight coordinate rounding
        df = pd.DataFrame([
            {
                "chemist_id": "C_JITTER_1",
                "chemist_name": "Shree Ganesh Medical Store",
                "chemist_latitude": 19.050000,
                "chemist_longitude": 72.850000,
                "chemist_pincode": "400050",
                "chem_address": "12 Hill Road, Bandra West"
            },
            {
                "chemist_id": "C_JITTER_2",
                "chemist_name": "Shree Ganesh Med & Gen Store",
                "chemist_latitude": 19.050100,  # ~11 meters away
                "chemist_longitude": 72.850050,
                "chemist_pincode": "400050",
                "chem_address": "Shop 12, Hill Road, Bandra"
            }
        ])

        canonical_df, merged_df, summary = resolve_and_deduplicate_chemists(
            df, spatial_proximity_m=30.0
        )
        self.assertEqual(len(canonical_df), 1)
        self.assertEqual(len(merged_df), 1)
        self.assertEqual(canonical_df.iloc[0]["alias_count"], 2)

    def test_centroid_collision_filter(self):
        # 5 distinct unrelated stores sharing the exact same coordinate (synthetic centroid)
        centroid_records = [
            {"id": f"ID_{i}", "name": name, "lat": 26.912433, "lon": 75.787270}
            for i, name in enumerate([
                "Rajdhani Chemist", "Jiwan Medical Store", "Balaji Medicos",
                "Pink City Pharmacy", "Life Care Medical Store"
            ])
        ]
        # 1 valid standalone store
        valid_records = [
            {"id": "VALID_1", "name": "Apollo Pharmacy", "lat": 26.920000, "lon": 75.800000}
        ]
        df = pd.DataFrame(centroid_records + valid_records)

        clean_df, centroid_df, summary = filter_suspicious_coordinate_centroids(
            df, lat_col="lat", lon_col="lon", name_col="name", max_unrelated_per_coord=3
        )

        self.assertEqual(len(clean_df), 1)
        self.assertEqual(clean_df.iloc[0]["id"], "VALID_1")
        self.assertEqual(len(centroid_df), 5)
        self.assertEqual(summary["centroid_collision_records"], 5)

    def test_incomplete_address_filter(self):
        df = pd.DataFrame([
            {"id": "A1", "chem_name": "Apollo", "chem_address": "123 Main Road, Dadar"},
            {"id": "A2", "chem_name": "MedPlus", "chem_address": "0"},
            {"id": "A3", "chem_name": "Noble", "chem_address": "NA"},
            {"id": "A4", "chem_name": "Care", "chem_address": "   "},
            {"id": "A5", "chem_name": "Life", "chem_address": None},
        ])

        clean_df, inc_df, summary = filter_incomplete_addresses(df, addr_col="chem_address", min_length=5)
        self.assertEqual(len(clean_df), 1)
        self.assertEqual(clean_df.iloc[0]["id"], "A1")
        self.assertEqual(len(inc_df), 4)


if __name__ == "__main__":
    unittest.main()
