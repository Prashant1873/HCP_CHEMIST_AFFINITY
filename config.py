import os
import json

# Default configuration settings
DEFAULT_CONFIG = {
    "input_file": "Chemist_test_HCM.xlsx",
    "sheet_name": "Chemist",
    "id_col": "IQVIA ID",
    "city_col": "chem_city",
    "state_col": "chem_state",
    "pincode_col": "chem_pincode",
    "name_col": "chem_name",
    "address_col": "chem_address",
    "lat_col": "chem_lat",
    "long_col": "chem_long",
    "india_bbox": {
        "lat_min": 6.0,
        "lat_max": 38.0,
        "long_min": 68.0,
        "long_max": 98.0
    },
    "address_short_threshold": 20,
    "address_weak_threshold": 30,
    "duplicate_coordinate_threshold": 5,
    "duplicate_coordinate_high_threshold": 20,
    "duplicate_coordinate_centroid_threshold": 100,
    "city_outlier_warning_km": 50.0,
    "city_outlier_critical_km": 100.0,
    "geocoding_mode": "OFFLINE_ONLY",
    "preserve_original_columns": True,
    "create_final_lat_long": True,
    "include_low_confidence_in_master": True,
    "allow_low_confidence_in_routing_if_coordinates_exist": True
}

class Config:
    def __init__(self, override_dict=None):
        # Initialize defaults
        for k, v in DEFAULT_CONFIG.items():
            setattr(self, k, v)
        
        # Apply overrides
        if override_dict:
            for k, v in override_dict.items():
                setattr(self, k, v)

    def to_dict(self):
        return {k: getattr(self, k) for k in DEFAULT_CONFIG.keys()}

    def save_to_file(self, filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
