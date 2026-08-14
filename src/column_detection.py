# Module for auto-detecting columns (coordinates, IDs, Names, Pincodes)
import pandas as pd
from typing import List, Optional, Tuple
from src.utils import setup_logger
from src import config

logger = setup_logger("column_detection")

def clean_col_name(name: str) -> str:
    """
    Strips spaces, underscores, dashes, and converts to lowercase for robust matching.
    """
    return "".join(c for c in str(name).lower() if c.isalnum())

def detect_column(df: pd.DataFrame, candidates: List[str], label: str) -> Optional[str]:
    """
    Detects a column in the DataFrame that matches one of the candidate names.
    Applies exact matching first, followed by cleaned alphanumeric matching.
    """
    columns = df.columns.tolist()
    
    # Cleaned candidates
    cleaned_candidates = {clean_col_name(c): c for c in candidates}
    
    # 1. Look for exact matches (case-insensitive)
    for col in columns:
        if col.lower() in [c.lower() for c in candidates]:
            return col
            
    # 2. Look for alphanumeric match (stripping spaces, symbols, etc.)
    for col in columns:
        cleaned_col = clean_col_name(col)
        if cleaned_col in cleaned_candidates:
            return col
            
    # 3. Look for partial substring match
    for col in columns:
        cleaned_col = clean_col_name(col)
        for cand in candidates:
            cleaned_cand = clean_col_name(cand)
            if cleaned_cand in cleaned_col or cleaned_col in cleaned_cand:
                return col
                
    return None

def detect_coordinates(df: pd.DataFrame, role: str) -> Tuple[str, str]:
    """
    Detects latitude and longitude columns. Raises ValueError if they cannot be determined.
    """
    lat_col = detect_column(df, config.LATITUDE_COLUMNS, f"{role}_latitude")
    lon_col = detect_column(df, config.LONGITUDE_COLUMNS, f"{role}_longitude")
    
    if not lat_col or not lon_col:
        logger.error(f"Failed to detect coordinate columns for {role}.")
        logger.error(f"Available columns: {df.columns.tolist()}")
        raise ValueError(
            f"Could not automatically detect coordinate columns for {role}.\n"
            f"Available columns: {df.columns.tolist()}\n"
            f"Please specify column names using the command-line parameters or config."
        )
        
    logger.info(f"Detected coordinates for {role}: Lat -> '{lat_col}', Lon -> '{lon_col}'")
    return lat_col, lon_col

def detect_identifiers(df: pd.DataFrame, role: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Detects identifier, name, and pincode columns.
    Returns Tuple of (id_col, name_col, pincode_col).
    Returns None for columns that aren't found.
    """
    if role == "doctor":
        id_candidates = config.DOCTOR_ID_COLUMNS
        name_candidates = config.DOCTOR_NAME_COLUMNS
    else:
        id_candidates = config.CHEMIST_ID_COLUMNS
        name_candidates = config.CHEMIST_NAME_COLUMNS
        
    id_col = detect_column(df, id_candidates, f"{role}_id")
    name_col = detect_column(df, name_candidates, f"{role}_name")
    pincode_col = detect_column(df, config.PINCODE_COLUMNS, f"{role}_pincode")
    
    logger.info(
        f"Detected identifiers for {role}: ID -> '{id_col}', "
        f"Name -> '{name_col}', Pincode -> '{pincode_col}'"
    )
    return id_col, name_col, pincode_col
