# Module for finding and loading input datasets
import os
import glob
import pandas as pd
from typing import Tuple, Optional
from src.utils import setup_logger

logger = setup_logger("data_loader")

def find_file_by_pattern(pattern: str, search_dir: str = ".") -> Optional[str]:
    """
    Search a directory for files matching a case-insensitive pattern.
    Example: "*doctor*" or "*chemist*"
    """
    search_path = os.path.join(search_dir, "*")
    files = glob.glob(search_path)
    
    matched_files = []
    for f in files:
        # Get the base name in lowercase
        base = os.path.basename(f).lower()
        # Exclude temporary Excel files starting with ~$
        if base.startswith("~$"):
            continue
        # Also check the pattern matches
        if pattern.lower().replace("*", "") in base:
            # Check if it has a valid spreadsheet extension
            if f.endswith(('.csv', '.xlsx', '.xls')):
                matched_files.append(f)
                
    if len(matched_files) == 1:
        return matched_files[0]
    elif len(matched_files) > 1:
        logger.warning(f"Multiple files matched pattern '{pattern}': {matched_files}. Choosing the first one: {matched_files[0]}")
        return matched_files[0]
    return None

def auto_detect_inputs(search_dir: str = ".") -> Tuple[Optional[str], Optional[str]]:
    """
    Scan folder and detect candidate doctor and chemist files.
    """
    doc_file = find_file_by_pattern("doctor", search_dir)
    chem_file = find_file_by_pattern("chemist", search_dir)
    
    # Try singular/plural and synonyms if nothing matches
    if not doc_file:
        doc_file = find_file_by_pattern("hcp", search_dir)
    if not chem_file:
        chem_file = find_file_by_pattern("retailer", search_dir) or find_file_by_pattern("store", search_dir)
        
    return doc_file, chem_file

def load_data_file(filepath: str) -> pd.DataFrame:
    """
    Loads an Excel (.xlsx, .xls) or CSV file.
    Handles multiple sheets in Excel files and raises errors for empty files.
    Preserves original columns.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
        
    ext = os.path.splitext(filepath)[1].lower()
    
    if ext == '.csv':
        df = pd.read_csv(filepath)
    elif ext in ['.xlsx', '.xls']:
        excel_file = pd.ExcelFile(filepath)
        sheets = excel_file.sheet_names
        if len(sheets) > 1:
            logger.warning(
                f"File '{filepath}' has multiple sheets: {sheets}. "
                f"Defaulting to the first sheet: '{sheets[0]}'."
            )
        df = pd.read_excel(filepath, sheet_name=sheets[0])
    else:
        raise ValueError(f"Unsupported file format: {ext}. Only .csv, .xlsx, and .xls are supported.")
        
    if df.empty:
        raise ValueError(f"The loaded file is empty: {filepath}")
        
    logger.info(f"Successfully loaded '{filepath}' with shape {df.shape}")
    return df
