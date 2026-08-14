# Module for recovering missing coordinates via pincode-to-centroid geocoding lookup
import os
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict
from src.utils import setup_logger
from src import config

logger = setup_logger("pincode_geocoder")

# Default bundled lookup file path (relative to project root)
DEFAULT_PINCODE_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pincode_lat_lon.csv")


def load_pincode_lookup(csv_path: Optional[str] = None) -> Dict[str, Tuple[float, float]]:
    """
    Loads a pincode-to-centroid lookup table from a CSV file.
    
    Expected CSV format (auto-detected):
        - Must contain columns for pincode, latitude, and longitude.
        - Column names are auto-detected using common patterns.
    
    If csv_path is None, attempts to load the bundled default CSV.
    
    Returns:
        A dictionary mapping 6-digit pincode strings to (latitude, longitude) tuples.
    """
    path = csv_path or DEFAULT_PINCODE_CSV
    
    if not os.path.exists(path):
        logger.warning(
            f"Pincode lookup CSV not found at '{path}'. "
            f"Pincode geocoding fallback will be disabled. "
            f"To enable, place a CSV with columns [pincode, latitude, longitude] at '{path}'."
        )
        return {}
    
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception as e:
        logger.warning(f"Failed to read pincode lookup CSV '{path}': {e}")
        return {}
    
    # Auto-detect columns
    pin_col = _find_column(df, ["pincode", "pin", "pin_code", "zip", "key", "Pincode", "PINCODE"])
    lat_col = _find_column(df, ["latitude", "lat", "Latitude", "LAT"])
    lon_col = _find_column(df, ["longitude", "lon", "lng", "long", "Longitude", "LON", "LNG"])
    
    if not pin_col or not lat_col or not lon_col:
        logger.warning(
            f"Could not detect pincode/latitude/longitude columns in '{path}'. "
            f"Found columns: {list(df.columns)}. Pincode geocoding disabled."
        )
        return {}
    
    lookup = {}
    for _, row in df.iterrows():
        raw_pin = str(row[pin_col]).strip()
        
        # Handle formats like "IN/110001"
        if "/" in raw_pin:
            raw_pin = raw_pin.split("/")[-1]
        
        # Clean to 6-digit string
        pin_digits = "".join(c for c in raw_pin if c.isdigit())
        if not pin_digits:
            continue
        if len(pin_digits) < 6:
            pin_digits = pin_digits.zfill(6)
        elif len(pin_digits) > 6:
            pin_digits = pin_digits[:6]
        
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
        except (ValueError, TypeError):
            continue
        
        # Validate coordinates are within India bounds
        if (config.INDIA_LAT_MIN <= lat <= config.INDIA_LAT_MAX) and \
           (config.INDIA_LON_MIN <= lon <= config.INDIA_LON_MAX):
            # Store first occurrence per pincode (most entries are unique)
            if pin_digits not in lookup:
                lookup[pin_digits] = (lat, lon)
    
    logger.info(f"Loaded pincode geocoding lookup with {len(lookup)} unique pincodes from '{path}'.")
    return lookup


def recover_missing_coordinates(
    invalid_df: pd.DataFrame,
    role: str,
    pincode_lookup: Dict[str, Tuple[float, float]]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Attempts to recover records from the invalid set that have missing/non-numeric
    coordinates but have a valid pincode that exists in the lookup table.
    
    Args:
        invalid_df: DataFrame of rejected records (must have 'rejection_reason' column)
        role: 'doctor' or 'chemist'
        pincode_lookup: Dictionary mapping pincode -> (lat, lon)
        
    Returns:
        (recovered_df, still_invalid_df) — recovered records are moved to valid set
    """
    if invalid_df.empty or not pincode_lookup:
        return pd.DataFrame(), invalid_df
    
    # Only attempt recovery for records rejected due to missing coordinates
    missing_mask = invalid_df["rejection_reason"].str.contains(
        "missing_or_non_numeric_coordinates", na=False
    )
    candidates = invalid_df[missing_mask].copy()
    not_candidates = invalid_df[~missing_mask].copy()
    
    if candidates.empty:
        return pd.DataFrame(), invalid_df
    
    recovered_indices = []
    pin_col = f"{role}_pincode"
    
    for idx, row in candidates.iterrows():
        pincode = str(row.get(pin_col, "")).strip()
        
        if pincode and pincode in pincode_lookup:
            lat, lon = pincode_lookup[pincode]
            candidates.at[idx, f"{role}_latitude"] = lat
            candidates.at[idx, f"{role}_longitude"] = lon
            candidates.at[idx, "coordinate_source"] = "pincode_centroid"
            recovered_indices.append(idx)
    
    if not recovered_indices:
        return pd.DataFrame(), invalid_df
    
    recovered_df = candidates.loc[recovered_indices].copy()
    still_missing = candidates.drop(index=recovered_indices)
    
    # Drop rejection_reason from recovered records (they are now valid)
    if "rejection_reason" in recovered_df.columns:
        recovered_df = recovered_df.drop(columns=["rejection_reason"])
    
    # Re-combine the records that were not candidates for recovery with those still missing
    still_invalid_df = pd.concat([not_candidates, still_missing], ignore_index=True)
    
    logger.info(
        f"Pincode geocoding recovered {len(recovered_df)} {role} records "
        f"({len(candidates) - len(recovered_df)} still invalid due to missing/unknown pincode)."
    )
    
    return recovered_df, still_invalid_df


def _find_column(df: pd.DataFrame, candidates: list) -> Optional[str]:
    """Finds the first matching column name from a list of candidates (case-insensitive)."""
    col_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in col_lower:
            return col_lower[cand.lower()]
    return None
