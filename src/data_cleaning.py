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


def filter_suspicious_coordinate_centroids(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    name_col: str,
    max_unrelated_per_coord: int = config.MAX_UNRELATED_STORES_PER_CENTROID,
    role: str = "chemist"
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Identifies and purges synthetic centroid collisions (points where multiple unrelated 
    store names collapse onto the exact same city/pincode centroid coordinate).
    
    Returns:
        Tuple of:
            - clean_df: Records without centroid collisions
            - centroid_df: Flagged records sitting on synthetic centroids
            - summary: Metric summary
    """
    if df.empty or lat_col not in df.columns or lon_col not in df.columns:
        return df.copy(), pd.DataFrame(), {
            "total_records": len(df),
            "retained_records": len(df),
            "centroid_collision_records": 0
        }
        
    from src.entity_resolver import normalize_chemist_name
    
    df_work = df.copy()
    
    # Round coordinates to 6 decimals (~10cm precision)
    lats = pd.to_numeric(df_work[lat_col], errors='coerce').round(6)
    lons = pd.to_numeric(df_work[lon_col], errors='coerce').round(6)
    df_work["_coord_key"] = list(zip(lats, lons))
    
    # Group by coordinate key and count distinct normalized names
    coord_stats: Dict[Tuple[float, float], Set[str]] = {}
    for idx, r in df_work.iterrows():
        key = r["_coord_key"]
        if pd.isna(key[0]) or pd.isna(key[1]):
            continue
        nm = normalize_chemist_name(r.get(name_col, ""))
        if not nm:
            nm = str(r.get(name_col, "")).strip().upper()
        if key not in coord_stats:
            coord_stats[key] = set()
        if nm:
            coord_stats[key].add(nm)
            
    # Find coordinate keys that have >= max_unrelated_per_coord distinct unrelated stores
    # (plus at least 4 total records at that location)
    coord_counts = df_work["_coord_key"].value_counts().to_dict()
    centroid_keys = set()
    for key, distinct_names in coord_stats.items():
        total_at_coord = coord_counts.get(key, 0)
        if len(distinct_names) >= max_unrelated_per_coord and total_at_coord >= 4:
            centroid_keys.add(key)
            
    is_centroid = df_work["_coord_key"].isin(centroid_keys)
    df_work["centroid_collision_flag"] = is_centroid
    df_work["centroid_rejection_reason"] = np.where(
        is_centroid,
        f"Synthetic centroid collision (>= {max_unrelated_per_coord} unrelated stores at identical coordinates)",
        ""
    )
    
    centroid_df = df_work[is_centroid].copy().drop(columns=["_coord_key"]).reset_index(drop=True)
    clean_df = df_work[~is_centroid].copy().drop(columns=["_coord_key", "centroid_collision_flag", "centroid_rejection_reason"]).reset_index(drop=True)
    
    summary = {
        "role": role,
        "total_records": len(df),
        "retained_records": len(clean_df),
        "centroid_collision_records": len(centroid_df),
        "centroid_locations_count": len(centroid_keys)
    }
    
    if len(centroid_df) > 0:
        logger.warning(
            f"Centroid Filter ({role}): Flagged and removed {len(centroid_df)} records sitting on "
            f"{len(centroid_keys)} synthetic centroid/geocoder collision points."
        )
        
    return clean_df, centroid_df, summary


def filter_incomplete_addresses(
    df: pd.DataFrame,
    addr_col: Optional[str] = None,
    min_length: int = config.MIN_ADDRESS_LENGTH,
    role: str = "chemist"
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Filters out records with missing, placeholder, or uninformative addresses.
    """
    if df.empty:
        return df.copy(), pd.DataFrame(), {
            "total_records": 0,
            "retained_records": 0,
            "incomplete_address_records": 0
        }
        
    # Auto-detect address column
    if not addr_col or addr_col not in df.columns:
        for cand in config.ADDRESS_COLUMNS:
            if cand in df.columns:
                addr_col = cand
                break
                
    if not addr_col or addr_col not in df.columns:
        # If no address column in dataset, do not filter
        return df.copy(), pd.DataFrame(), {
            "total_records": len(df),
            "retained_records": len(df),
            "incomplete_address_records": 0
        }
        
    df_work = df.copy()
    
    def is_invalid_addr(val: Any) -> bool:
        if pd.isna(val) or val is None:
            return True
        s = str(val).strip().upper()
        if len(s) < min_length:
            return True
        if s in ["0", "NA", "N/A", "NULL", "NONE", "UNKNOWN", "NIL", "-", ".", "--", "---"]:
            return True
        # Purely numbers and symbols (e.g. "0000", "123")
        clean_text = "".join(c for c in s if c.isalpha())
        if len(clean_text) < 2:
            return True
        return False
        
    invalid_mask = df_work[addr_col].apply(is_invalid_addr)
    
    df_work["address_exclusion_reason"] = np.where(
        invalid_mask,
        "Missing, placeholder, or uninformative address",
        ""
    )
    
    incomplete_df = df_work[invalid_mask].copy().reset_index(drop=True)
    clean_df = df_work[~invalid_mask].copy().drop(columns=["address_exclusion_reason"]).reset_index(drop=True)
    
    summary = {
        "role": role,
        "address_column": addr_col,
        "total_records": len(df),
        "retained_records": len(clean_df),
        "incomplete_address_records": len(incomplete_df)
    }
    
    if len(incomplete_df) > 0:
        logger.info(
            f"Address Filter ({role}): Excluded {len(incomplete_df)}/{len(df)} records with missing/placeholder addresses."
        )
        
    return clean_df, incomplete_df, summary


