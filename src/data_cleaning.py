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
    Cleans and validates the dataset using high-performance vectorized operations.
    Returns a tuple: (valid_df, invalid_df)
    
    Validation conditions for invalid_df:
    - Coordinates are missing or non-numeric.
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
    lat_series = pd.to_numeric(df_clean[lat_col], errors='coerce')
    lon_series = pd.to_numeric(df_clean[lon_col], errors='coerce')
    
    df_clean[f"{role}_latitude"] = lat_series
    df_clean[f"{role}_longitude"] = lon_series
    
    df_clean["rejection_reason"] = ""
    df_clean["coordinate_corrected"] = ""
    df_clean["coordinate_source"] = "original"
    
    # Missing or NaN mask
    missing_mask = lat_series.isna() | lon_series.isna()
    
    # Global bounds mask
    lat_global_invalid = (~missing_mask) & ((lat_series < -90.0) | (lat_series > 90.0))
    lon_global_invalid = (~missing_mask) & ((lon_series < -180.0) | (lon_series > 180.0))
    
    # Inversion candidate mask: lat in India lon range and lon in India lat range
    invert_cand_mask = (
        (~missing_mask) & (~lat_global_invalid) & (~lon_global_invalid) &
        (lat_series >= config.INVERT_LAT_MIN) & (lat_series <= config.INVERT_LAT_MAX) &
        (lon_series >= config.INVERT_LON_MIN) & (lon_series <= config.INVERT_LON_MAX)
    )
    
    # Check if swap produces valid India coordinates
    swap_valid_mask = (
        invert_cand_mask &
        (lon_series >= config.INDIA_LAT_MIN) & (lon_series <= config.INDIA_LAT_MAX) &
        (lat_series >= config.INDIA_LON_MIN) & (lat_series <= config.INDIA_LON_MAX)
    )
    swap_failed_mask = invert_cand_mask & (~swap_valid_mask)
    
    # Apply coordinate swapping for valid inverted coords
    corrected_count = int(swap_valid_mask.sum())
    if corrected_count > 0:
        swapped_lats = lon_series[swap_valid_mask]
        swapped_lons = lat_series[swap_valid_mask]
        df_clean.loc[swap_valid_mask, f"{role}_latitude"] = swapped_lats
        df_clean.loc[swap_valid_mask, f"{role}_longitude"] = swapped_lons
        df_clean.loc[swap_valid_mask, "coordinate_corrected"] = "lat_lon_swapped"
        df_clean.loc[swap_valid_mask, "coordinate_source"] = "lat_lon_swapped"
        logger.info(f"Auto-corrected {corrected_count} {role} records with inverted lat/lon coordinates.")
        
    # Re-fetch updated lat/lon series for remaining checks
    curr_lat = df_clean[f"{role}_latitude"]
    curr_lon = df_clean[f"{role}_longitude"]
    
    # Outside India bounding box check (excluding already swapped records)
    outside_india_mask = (
        (~missing_mask) & (~lat_global_invalid) & (~lon_global_invalid) & (~swap_valid_mask) & (~swap_failed_mask) &
        ((curr_lat < config.INDIA_LAT_MIN) | (curr_lat > config.INDIA_LAT_MAX) |
         (curr_lon < config.INDIA_LON_MIN) | (curr_lon > config.INDIA_LON_MAX))
    )
    
    # Assign rejection reasons
    rejection_reasons = pd.Series("", index=df_clean.index)
    rejection_reasons[missing_mask] = "missing_or_non_numeric_coordinates"
    rejection_reasons[lat_global_invalid] = "latitude_out_of_global_bounds_90"
    rejection_reasons[lon_global_invalid] = "longitude_out_of_global_bounds_180"
    rejection_reasons[swap_failed_mask] = "possible_lat_lon_inversion_swap_failed"
    rejection_reasons[outside_india_mask] = "outside_india_bounding_box"
    
    df_clean["rejection_reason"] = rejection_reasons
    
    # Split into valid and invalid
    invalid_mask = rejection_reasons != ""
    invalid_df = df_clean[invalid_mask].copy().reset_index(drop=True)
    valid_df = df_clean[~invalid_mask].copy().drop(columns=["rejection_reason"]).reset_index(drop=True)
    
    logger.info(f"{role.capitalize()} dataset cleaning complete: {len(valid_df)} valid, {len(invalid_df)} invalid.")
    return valid_df, invalid_df

