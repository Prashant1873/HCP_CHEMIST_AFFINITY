# Module for cleaning and validating data records
import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any, List, Optional
from src.utils import setup_logger
from src import config

logger = setup_logger("data_cleaning")

def clean_pincode(pin: Any) -> str:
    """
    Standardizes pincode as a 6-digit string.
    Removes floating-point decimals, non-digit characters, and pads with leading zeros.
    """
    if pd.isna(pin):
        return ""
        
    # Convert to string, strip whitespace
    pin_str = str(pin).strip()
    
    # Handle float conversion representation like '400001.0'
    if '.' in pin_str:
        pin_str = pin_str.split('.')[0]
        
    # Keep only digits
    pin_digits = "".join(c for c in pin_str if c.isdigit())
    
    if not pin_digits:
        return ""
        
    # Pad to 6 digits if shorter, or slice to 6 if longer
    if len(pin_digits) < 6:
        pin_digits = pin_digits.zfill(6)
    elif len(pin_digits) > 6:
        # Keep first 6 or last 6? Usually first 6 in India.
        pin_digits = pin_digits[:6]
        
    return pin_digits

def clean_and_validate_dataset(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    id_col: Optional[str],
    name_col: Optional[str],
    pin_col: Optional[str],
    role: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Cleans and validates the dataset.
    Returns a tuple: (valid_df, invalid_df)
    
    Validation conditions for invalid_df:
    - Coordinates are missing.
    - Coordinates are non-numeric.
    - Coordinates are out of global bounds (-90 to 90 for lat, -180 to 180 for lon).
    - Coordinates are outside India's bounding box.
    - Coordinates are inverted (lat in India lon range, and lon in India lat range).
    """
    df_clean = df.copy()
    
    # 1. Create synthetic ID if none exists, and standard identifier columns
    if not id_col or id_col not in df_clean.columns:
        prefix = "DOC_" if role == "doctor" else "CHEM_"
        df_clean[f"{role}_id"] = [f"{prefix}{i+1:06d}" for i in range(len(df_clean))]
        df_clean["original_id"] = np.nan
    else:
        df_clean[f"{role}_id"] = df_clean[id_col].astype(str)
        df_clean["original_id"] = df_clean[id_col]
        
    if name_col and name_col in df_clean.columns:
        df_clean[f"{role}_name"] = df_clean[name_col].astype(str)
    else:
        df_clean[f"{role}_name"] = "Unknown"
        
    if pin_col and pin_col in df_clean.columns:
        df_clean[f"{role}_pincode"] = df_clean[pin_col].apply(clean_pincode)
    else:
        df_clean[f"{role}_pincode"] = ""
        
    # Keep track of original coordinates
    df_clean[f"{role}_latitude_original"] = df_clean[lat_col]
    df_clean[f"{role}_longitude_original"] = df_clean[lon_col]
    
    # 2. Coerce coordinates to float
    df_clean[f"{role}_latitude"] = pd.to_numeric(df_clean[lat_col], errors='coerce')
    df_clean[f"{role}_longitude"] = pd.to_numeric(df_clean[lon_col], errors='coerce')
    
    # Add tracking fields
    df_clean["rejection_reason"] = ""
    df_clean["coordinate_corrected"] = ""
    df_clean["coordinate_source"] = "original"
    
    invalid_rows = []
    corrected_count = 0
    
    for idx, row in df_clean.iterrows():
        lat = row[f"{role}_latitude"]
        lon = row[f"{role}_longitude"]
        reasons = []
        
        # Check missing or non-numeric
        if pd.isna(lat) or pd.isna(lon):
            reasons.append("missing_or_non_numeric_coordinates")
        else:
            # Check global bounds
            if not (-90.0 <= lat <= 90.0):
                reasons.append("latitude_out_of_global_bounds_90")
            if not (-180.0 <= lon <= 180.0):
                reasons.append("longitude_out_of_global_bounds_180")
                
            # If coordinates are globally valid, check for inversion and India bounds
            if not reasons:
                # Check possible inversion: lat in India's longitude range, lon in India's latitude range
                if (config.INVERT_LAT_MIN <= lat <= config.INVERT_LAT_MAX) and \
                   (config.INVERT_LON_MIN <= lon <= config.INVERT_LON_MAX):
                    # Auto-correct by swapping lat and lon
                    swapped_lat = lon
                    swapped_lon = lat
                    # Verify the swapped values fall within India's bounding box
                    if (config.INDIA_LAT_MIN <= swapped_lat <= config.INDIA_LAT_MAX) and \
                       (config.INDIA_LON_MIN <= swapped_lon <= config.INDIA_LON_MAX):
                        df_clean.at[idx, f"{role}_latitude"] = swapped_lat
                        df_clean.at[idx, f"{role}_longitude"] = swapped_lon
                        df_clean.at[idx, "coordinate_corrected"] = "lat_lon_swapped"
                        df_clean.at[idx, "coordinate_source"] = "lat_lon_swapped"
                        corrected_count += 1
                        # Record is now valid — skip adding to invalid_rows
                    else:
                        # Swap didn't produce valid India coords — still reject
                        reasons.append("possible_lat_lon_inversion_swap_failed")
                else:
                    # Check India bounding box
                    in_india = (config.INDIA_LAT_MIN <= lat <= config.INDIA_LAT_MAX) and \
                               (config.INDIA_LON_MIN <= lon <= config.INDIA_LON_MAX)
                    if not in_india:
                        reasons.append("outside_india_bounding_box")
                    
        if reasons:
            df_clean.at[idx, "rejection_reason"] = "; ".join(reasons)
            invalid_rows.append(idx)
            
    if corrected_count > 0:
        logger.info(f"Auto-corrected {corrected_count} {role} records with inverted lat/lon coordinates.")
    
    # Split into valid and invalid
    invalid_df = df_clean.loc[invalid_rows].copy()
    valid_df = df_clean.drop(index=invalid_rows).copy()
    
    # Drop rejection reason column from valid dataset
    valid_df = valid_df.drop(columns=["rejection_reason"])
    
    logger.info(f"{role.capitalize()} dataset cleaning complete: {len(valid_df)} valid, {len(invalid_df)} invalid.")
    return valid_df, invalid_df
