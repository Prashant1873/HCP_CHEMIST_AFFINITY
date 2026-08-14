# Module for managing checkpoints to support process resume
import os
import pandas as pd
from src.utils import setup_logger

logger = setup_logger("checkpoint_manager")

def _enforce_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensures that the road distance and routing columns exist and have the correct
    datatypes (object/string) to avoid TypeErrors when modifying empty columns.
    """
    for col in ["road_distance_status", "routing_engine", "routing_error_message"]:
        if col not in df.columns:
            df[col] = "not_calculated" if col == "road_distance_status" else None
        df[col] = df[col].astype(object)
        
    for col in ["road_distance_km", "road_distance_rank"]:
        if col not in df.columns:
            df[col] = pd.Series(dtype=float)
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    return df

def load_checkpoint_or_source(checkpoint_path: str, source_path: str) -> pd.DataFrame:
    """
    Checks if a checkpoint file exists. If it does, load and return it.
    Otherwise, load the source file, save it as the initial checkpoint, and return it.
    """
    if os.path.exists(checkpoint_path):
        try:
            df = pd.read_csv(checkpoint_path)
            df = _enforce_types(df)
            logger.info(f"Loaded existing checkpoint file '{checkpoint_path}' with {len(df)} records.")
            return df
        except Exception as e:
            logger.error(f"Error loading checkpoint file '{checkpoint_path}': {str(e)}. Starting from source.")
            
    # Load source if checkpoint doesn't exist or failed to load
    logger.info(f"No valid checkpoint found. Loading source file '{source_path}'...")
    df = pd.read_csv(source_path)
    df = _enforce_types(df)
        
    # Save as initial checkpoint
    save_checkpoint(df, checkpoint_path)
    return df

def save_checkpoint(df: pd.DataFrame, checkpoint_path: str) -> None:
    """
    Saves the current dataframe state to the checkpoint file path.
    """
    # Write to a temporary file first, then rename, to prevent file corruption during writes
    temp_path = checkpoint_path + ".tmp"
    df.to_csv(temp_path, index=False)
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    os.rename(temp_path, checkpoint_path)

def get_remaining_count(df: pd.DataFrame) -> int:
    """
    Returns the number of rows that still need OSRM route calculation.
    """
    # Count rows where status is 'not_calculated'
    return int((df["road_distance_status"] == "not_calculated").sum())
