# Module for building spatial index and querying nearest-neighbors
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from typing import Tuple, Dict, List, Optional, Any, Set
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
    candidate_k: int = config.DEFAULT_CANDIDATE_K,
    final_n: int = config.DEFAULT_FINAL_N,
    max_distance_km: Optional[float] = config.DEFAULT_MAX_DISTANCE_KM
) -> pd.DataFrame:
    """
    For each doctor, queries the BallTree to find the top nearest unique chemist candidates
    within a maximum distance threshold (default: 1.0 km), ensuring no duplicate chemists per doctor.
    
    Args:
        doctor_df: Validated DataFrame of doctors
        chemist_df: Validated DataFrame of chemists
        tree: Fitted BallTree on chemist coordinates
        candidate_k: Initial query pool size per doctor
        final_n: Maximum number of closest unique chemists to rank per doctor (default: 5)
        max_distance_km: Hard maximum distance threshold in km (default: 1.0 km)
        
    Returns:
        DataFrame containing deduplicated doctor-chemist pairs strictly within max_distance_km,
        ranked 1 to final_n per doctor.
    """
    n_chemists = len(chemist_df)
    if n_chemists == 0 or len(doctor_df) == 0:
        logger.warning("Empty doctor or chemist dataset provided for spatial querying.")
        return pd.DataFrame()
        
    # Query pool size should be large enough to allow deduplication and distance filtering
    query_k = min(n_chemists, max(candidate_k, final_n * 5, 20))
    
    doc_lats = doctor_df["doctor_latitude"].values
    doc_lons = doctor_df["doctor_longitude"].values
    doc_coords_rad = np.deg2rad(np.vstack((doc_lats, doc_lons)).T)
    
    logger.info(
        f"Querying BallTree for up to {final_n} unique chemists within {max_distance_km} km "
        f"for {len(doctor_df)} doctors (query pool k={query_k})..."
    )
    
    # Query tree: returns shape (n_doctors, query_k) sorted by distance ascending
    distances_rad, indices = tree.query(doc_coords_rad, k=query_k)
    distances_km = distances_rad * config.EARTH_RADIUS_KM
    
    results_rows = []
    doctors_with_matches = 0
    total_matches = 0
    
    for i, (_, doc_row) in enumerate(doctor_df.iterrows()):
        doc_dict = doc_row.to_dict()
        seen_chemist_keys = set()
        rank = 1
        
        for chem_idx, d_km in zip(indices[i], distances_km[i]):
            # Hard filter: exclude if greater than max_distance_km
            if max_distance_km is not None and d_km > max_distance_km:
                # Since distances are in ascending order, no subsequent candidate is closer
                break
                
            c_row = chemist_df.iloc[chem_idx]
            
            # Safeguard: Unique chemist identification key to prevent ranking same chemist multiple times
            cid = str(c_row.get("chemist_id", "")).strip()
            cname = str(c_row.get("chemist_name", "")).strip()
            clat = round(float(c_row.get("chemist_latitude", 0.0)), 6)
            clon = round(float(c_row.get("chemist_longitude", 0.0)), 6)
            unique_key = cid if cid and cid != "Unknown" else f"{cname}_{clat}_{clon}"
            
            if unique_key in seen_chemist_keys:
                continue  # Skip duplicate chemist for this doctor
            seen_chemist_keys.add(unique_key)
            
            # Assemble mapped pair
            pair = {**doc_dict}
            for col, val in c_row.items():
                key = col if col.startswith("chemist_") else f"chemist_{col}"
                pair[key] = val
                
            pair["air_distance_km"] = round(float(d_km), 4)
            pair["air_distance_rank"] = rank
            pair["candidate_k_used"] = candidate_k
            pair["max_distance_km_threshold"] = max_distance_km
            
            # Road distance placeholders
            pair["road_distance_km"] = np.nan
            pair["road_distance_rank"] = np.nan
            pair["road_distance_status"] = "not_calculated"
            pair["routing_engine"] = np.nan
            pair["routing_error_message"] = np.nan
            
            results_rows.append(pair)
            rank += 1
            if rank > final_n:
                break
                
        if rank > 1:
            doctors_with_matches += 1
            total_matches += (rank - 1)
            
    results_df = pd.DataFrame(results_rows)
    
    if not results_df.empty:
        results_df = results_df.sort_values(by=["doctor_id", "air_distance_rank"]).reset_index(drop=True)
        
    logger.info(
        f"Spatial mapping complete: matched {doctors_with_matches}/{len(doctor_df)} doctors "
        f"with {total_matches} total unique chemist pairs strictly within {max_distance_km} km."
    )
    return results_df

