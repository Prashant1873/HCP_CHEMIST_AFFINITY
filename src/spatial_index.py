# Module for building spatial index and querying nearest-neighbors
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from typing import Tuple, Dict, List
from src.utils import setup_logger
from src import config

logger = setup_logger("spatial_index")

def build_ball_tree(chemist_df: pd.DataFrame) -> Tuple[BallTree, np.ndarray]:
    """
    Builds a BallTree on chemist coordinates using the Haversine metric.
    Coordinates must be converted from degrees to radians.
    Returns:
        tree: The fitted BallTree instance
        chemist_coords_rad: The numpy array of chemist coordinates in radians [lat, lon]
    """
    # Exclude invalid coordinate entries (which shouldn't be here, but just in case)
    lats = chemist_df["chemist_latitude"].values
    lons = chemist_df["chemist_longitude"].values
    
    # Haversine metric in sklearn expects coordinates in radians in format [latitude, longitude]
    chemist_coords_rad = np.deg2rad(np.vstack((lats, lons)).T)
    
    logger.info(f"Building BallTree spatial index on {len(chemist_df)} chemist coordinates...")
    tree = BallTree(chemist_coords_rad, metric='haversine')
    logger.info("BallTree index built successfully.")
    
    return tree, chemist_coords_rad

def find_nearest_chemists(
    doctor_df: pd.DataFrame,
    chemist_df: pd.DataFrame,
    tree: BallTree,
    candidate_k: int
) -> pd.DataFrame:
    """
    For each doctor, queries the BallTree to find the top K nearest chemist candidates.
    Returns a DataFrame containing doctor-chemist pairs with air distances.
    """
    n_chemists = len(chemist_df)
    k = min(candidate_k, n_chemists)
    
    if k != candidate_k:
        logger.warning(
            f"Requested candidate_k ({candidate_k}) is greater than number of valid chemists ({n_chemists}). "
            f"Adjusting K to {k}."
        )
        
    doc_lats = doctor_df["doctor_latitude"].values
    doc_lons = doctor_df["doctor_longitude"].values
    doc_coords_rad = np.deg2rad(np.vstack((doc_lats, doc_lons)).T)
    
    logger.info(f"Querying BallTree for top {k} nearest chemists for {len(doctor_df)} doctors...")
    
    # Query tree: returns shape (n_doctors, k)
    distances_rad, indices = tree.query(doc_coords_rad, k=k)
    
    logger.info("Query complete. Vectorizing results...")
    
    # Calculate distances in kilometers
    distances_km = distances_rad * config.EARTH_RADIUS_KM
    
    # Vectorized generation of pairs
    n_docs = len(doctor_df)
    
    # Replicate doctor row indices k times
    doc_indices_rep = np.repeat(np.arange(n_docs), k)
    # Flatten queried chemist indices
    chem_indices_flat = indices.flatten()
    # Flatten distances
    distances_km_flat = distances_km.flatten()
    # Rank is [1, 2, ..., k] repeated for each doctor
    ranks_flat = np.tile(np.arange(1, k + 1), n_docs)
    
    # Extract the target subsets
    doc_sub = doctor_df.iloc[doc_indices_rep].reset_index(drop=True)
    chem_sub = chemist_df.iloc[chem_indices_flat].reset_index(drop=True)
    
    # Merge doctor and chemist records side-by-side
    # Combine original columns
    # We prefix chemist columns to avoid collisions
    chem_sub_cols = {col: f"chemist_{col}" if not col.startswith("chemist_") else col for col in chem_sub.columns}
    chem_sub = chem_sub.rename(columns=chem_sub_cols)
    
    # Assemble final output
    results_df = pd.concat([doc_sub, chem_sub], axis=1)
    
    # Add distance fields
    results_df["air_distance_rank"] = ranks_flat
    results_df["air_distance_km"] = distances_km_flat
    results_df["candidate_k_used"] = candidate_k
    
    # Add road distance placeholder fields
    results_df["road_distance_km"] = np.nan
    results_df["road_distance_rank"] = np.nan
    results_df["road_distance_status"] = "not_calculated"
    results_df["routing_engine"] = np.nan
    results_df["routing_error_message"] = np.nan
    
    # Sort output to make sure it's strictly ordered by doctor and distance rank
    results_df = results_df.sort_values(by=[f"doctor_id", "air_distance_rank"]).reset_index(drop=True)
    
    logger.info(f"Generated {len(results_df)} doctor-chemist candidate pairs.")
    return results_df
