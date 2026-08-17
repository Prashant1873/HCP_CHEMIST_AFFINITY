import os
import sys
import unittest
import pandas as pd

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.name_cleaner import is_generic_name, filter_generic_names


class TestNameCleaner(unittest.TestCase):
    def test_exact_generic_names(self):
        generic_samples = [
            "Chemist",
            "CHEMISTS",
            "Medical",
            "MEDICALS",
            "Pharmacy",
            "Pharmacies",
            "Drug Store",
            "DRUG STRORE",  # Typo variation
            "Drugstore",
            "Drug Stores",
            "Druggist",
            "Chemists & Druggists",
            "Chemist and Druggist",
            "Medical Store",
            "Medical Stores",
            "Medical Hall",
            "Medicine Shop",
            "Medicine Store",
            "Medicine Centre",
            "Medicine Corner",
            "The Pharmacy",
            "The Chemist",
            "The Medical",
            "A Pharmacy",
            "Retailer",
            "Jan Aushadhi",
            "Jan Aushadhi Kendra",
            "Jan Aushadhi Store",
            "Pradhan Mantri Jan Aushadhi Kendra",
            "PMBJP Kendra",
            "Generic Medicine Store",
            "Generic Pharmacy"
        ]
        for name in generic_samples:
            flag, reason = is_generic_name(name)
            self.assertTrue(flag, f"Expected '{name}' to be classified as generic, but got flag={flag} (reason={reason})")

    def test_placeholders_and_invalid_names(self):
        invalid_samples = [
            "No Details - Cust - 40002",
            "No Details - Cust - 800002",
            "NO DETAILS - CUST - 400067",
            "no details",
            "no data available",
            "not available",
            "Cust - 99912",
            "Unknown",
            "NA",
            "N/A",
            "None",
            "Null",
            "Test",
            "Sample",
            "Dummy",
            "",
            "   ",
            None,
            "...",
            "---",
            "12345",
            "C",  # Single letter
            "X"
        ]
        for name in invalid_samples:
            flag, reason = is_generic_name(name)
            self.assertTrue(flag, f"Expected placeholder '{name}' to be classified as generic, but got flag={flag}")

    def test_distinctive_branded_names_preserved(self):
        branded_samples = [
            "Apollo Pharmacy",
            "Parashar Medical Store",
            "Om Medicals",
            "MedPlus Pharmacy",
            "Wellness Forever",
            "R.K. Chemist",
            "Shree Sai Medical Store",
            "Frank Ross Pharmacy",
            "Fortis Healthworld",
            "Guardian Pharmacy",
            "LifeCare Medicals",
            "Bharat Medical Store"
        ]
        for name in branded_samples:
            flag, reason = is_generic_name(name)
            self.assertFalse(flag, f"Expected branded name '{name}' to be preserved as DISTINCTIVE, but got flagged as generic: {reason}")

    def test_dataframe_filtering(self):
        df = pd.DataFrame([
            {"id": "C1", "chem_name": "Apollo Pharmacy", "city": "Delhi"},
            {"id": "C2", "chem_name": "Chemist", "city": "Delhi"},
            {"id": "C3", "chem_name": "Medical Store", "city": "Mumbai"},
            {"id": "C4", "chem_name": "Parashar Medical Store", "city": "Agra"},
            {"id": "C5", "chem_name": "Drug Strore", "city": "Kolkata"},
            {"id": "C6", "chem_name": "NA", "city": "Pune"}
        ])

        clean_df, generic_df, summary = filter_generic_names(df, name_col="chem_name", role="chemist")
        
        self.assertEqual(len(clean_df), 2)
        self.assertListEqual(list(clean_df["id"]), ["C1", "C4"])
        self.assertEqual(len(generic_df), 4)
        self.assertEqual(summary["generic_excluded_records"], 4)
        self.assertEqual(summary["retained_records"], 2)


if __name__ == "__main__":
    unittest.main()
