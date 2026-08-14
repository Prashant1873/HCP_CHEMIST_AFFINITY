# Phase 2 entrypoint: road-distance calculations, checkpoints, ranking, and validation reports.
import os
import sys
import time
import argparse
from datetime import datetime
import pandas as pd
import numpy as np
from tqdm import tqdm

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src.routing_engine import query_osrm_road_distance, query_graphhopper_road_distance, simulate_road_distance
from src.checkpoint_manager import load_checkpoint_or_source, save_checkpoint, get_remaining_count
from src.analysis import calculate_capture_rate_analysis

logger = setup_logger("road_routing")

# Expanded Indian city name synonyms — maps alternate/historical names to a canonical form
CITY_SYNONYMS = {
    # Historical / alternate names
    "calcutta": "kolkata",
    "bombay": "mumbai",
    "madras": "chennai",
    "bengaluru": "bangalore",
    "secunderabad": "hyderabad",
    "vijaywada": "vijayawada",
    "poona": "pune",
    "banaras": "varanasi",
    "benares": "varanasi",
    "kashi": "varanasi",
    "trivandrum": "thiruvananthapuram",
    "cochin": "kochi",
    "pondicherry": "puducherry",
    "baroda": "vadodara",
    "mangalore": "mangaluru",
    "mysore": "mysuru",
    "simla": "shimla",
    "ooty": "udhagamandalam",
    "panjim": "panaji",
    "cawnpore": "kanpur",
    "vizag": "visakhapatnam",
    "vishakhapatnam": "visakhapatnam",
    "allahabad": "prayagraj",
    "gurgaon": "gurugram",
    "noida": "gautambuddhanagar",
    "newdelhi": "delhi",
}

def normalize_city(city):
    """Normalizes a city name by lowering, stripping punctuation, and resolving synonyms."""
    if not isinstance(city, str):
        return ""
    c = city.lower().strip()
    c = c.replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
    for old, new in CITY_SYNONYMS.items():
        if old in c or new in c:
            return new
    return c


def fuzzy_city_match(city_a: str, city_b: str, threshold: float = 0.80) -> bool:
    """
    Returns True if two normalized city strings are similar enough.
    Uses SequenceMatcher (stdlib) for a lightweight edit-distance ratio.
    Exact matches and substring containment are checked first for speed.
    """
    if not city_a or not city_b:
        return False
    if city_a == city_b:
        return True
    # Check if one is a substring of the other (handles "mumbai" in "navimumbai" etc.)
    if city_a in city_b or city_b in city_a:
        return True
    # Fallback to sequence similarity
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(None, city_a, city_b).ratio()
    return ratio >= threshold


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 road-distance ranker and candidate validation."
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=os.path.join("outputs", "doctor_chemist_candidates_air_distance.csv"),
        help="Path to Phase 1 air-distance candidates CSV (default: outputs/doctor_chemist_candidates_air_distance.csv)"
    )
    parser.add_argument(
        "--routing_engine",
        type=str,
        choices=["OSRM", "GraphHopper"],
        default="GraphHopper",
        help="Routing engine to use (default: GraphHopper)"
    )
    parser.add_argument(
        "--osrm_endpoint",
        type=str,
        default=None,
        help="Endpoint for local routing instance. Defaults to http://localhost:8989 for GraphHopper, http://localhost:5000 for OSRM"
    )
    parser.add_argument(
        "--final_n",
        type=int,
        default=5,
        help="Number of nearest road-distance chemists to select per doctor (default: 5)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate driving road distances for testing/validation (default: False)"
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Rate-limiting sleep interval in seconds between queries (default: 0.0)"
    )
    parser.add_argument(
        "--checkpoint_interval",
        type=int,
        default=1000,
        help="Number of routing queries between checkpoint updates (default: 1000)"
    )
    
    args = parser.parse_args()
    
    # Dynamically assign default endpoint if not specified
    if args.osrm_endpoint is None:
        if args.routing_engine == "GraphHopper":
            args.osrm_endpoint = "http://localhost:8989"
        else:
            args.osrm_endpoint = "http://localhost:5000"

    
    start_time = time.time()
    run_timestamp = datetime.now().isoformat()
    
    logger.info("Initializing Phase 2: Road Distance Calculation...")
    if args.simulate:
        logger.info("Simulation mode is enabled. Using simulated driving road distances.")
    else:
        logger.info(f"Targeting local {args.routing_engine} endpoint: {args.osrm_endpoint}")
        
    output_dir = os.path.dirname(args.input_file) or "outputs"
    checkpoint_path = os.path.join(output_dir, "road_distance_checkpoint.csv")
    
    # 1. Load data from checkpoint or source
    try:
        df = load_checkpoint_or_source(checkpoint_path, args.input_file)
    except Exception as e:
        logger.exception(f"Error loading inputs: {str(e)}")
        sys.exit(1)
        
    # Enforce city compatibility filter to eliminate coordinate anomalies
    logger.info("Enforcing city consistency filter between doctor and chemist locations...")
    
    def check_city_match(row):
        doc_city = normalize_city(row.get("Doctor City", row.get("doctor_city", "")))
        chem_city = normalize_city(row.get("chemist_chem_city", row.get("chemist_city", "")))
        if doc_city == chem_city:
            return "exact"
        if fuzzy_city_match(doc_city, chem_city):
            return "fuzzy"
        return "mismatch"
        
    df["city_match_type"] = df.apply(check_city_match, axis=1)
    
    initial_count = len(df)
    fuzzy_count = int((df["city_match_type"] == "fuzzy").sum())
    df = df[df["city_match_type"] != "mismatch"].reset_index(drop=True)
    filtered_count = initial_count - len(df)
    
    if fuzzy_count > 0:
        logger.info(
            f"Retained {fuzzy_count} candidate pairs via fuzzy city-name matching "
            f"(similar but not identical city names). These are flagged for review."
        )
    
    if filtered_count > 0:
        logger.warning(
            f"Filtered out {filtered_count} candidate pairs due to city coordinate mismatches "
            f"(e.g., doctor and chemist coordinates are close but they are in different textual cities)."
        )
        
    total_pairs = len(df)
    remaining_pairs = get_remaining_count(df)
    completed_pairs = total_pairs - remaining_pairs
    
    logger.info(f"Total candidate pairs: {total_pairs}")
    logger.info(f"Calculated pairs: {completed_pairs}")
    logger.info(f"Remaining pairs to compute: {remaining_pairs}")
    
    # 2. Iterate and compute road distances
    if remaining_pairs > 0:
        logger.info("Starting road distance calculations...")
        count = 0
        
        # Iterate over records needing calculation
        indices_to_compute = df[df["road_distance_status"] == "not_calculated"].index.tolist()
        
        for idx in tqdm(indices_to_compute, desc="Calculating road distances", unit="pair"):
            row = df.loc[idx]
            
            # Extract coordinates
            doc_lat = float(row["doctor_latitude"])
            doc_lon = float(row["doctor_longitude"])
            chem_lat = float(row["chemist_latitude"])
            chem_lon = float(row["chemist_longitude"])
            air_dist = float(row["air_distance_km"])
            
            if args.simulate:
                # Simulating road distance
                road_dist = simulate_road_distance(air_dist)
                status = "success"
                error_msg = None
                engine = "simulator"
            else:
                if args.routing_engine == "GraphHopper":
                    road_dist, status, error_msg = query_graphhopper_road_distance(
                        lat1=doc_lat,
                        lon1=doc_lon,
                        lat2=chem_lat,
                        lon2=chem_lon,
                        endpoint=args.osrm_endpoint
                    )
                else:
                    road_dist, status, error_msg = query_osrm_road_distance(
                        lat1=doc_lat,
                        lon1=doc_lon,
                        lat2=chem_lat,
                        lon2=chem_lon,
                        endpoint=args.osrm_endpoint
                    )
                engine = args.routing_engine
                
            # Update dataframe in place
            df.at[idx, "road_distance_km"] = road_dist if road_dist is not None else np.nan
            df.at[idx, "road_distance_status"] = status
            df.at[idx, "routing_engine"] = engine
            df.at[idx, "routing_error_message"] = error_msg if error_msg else np.nan
            
            count += 1
            
            # Optional sleep interval
            if args.sleep > 0:
                time.sleep(args.sleep)
                
            # Periodically write checkpoint
            if count % args.checkpoint_interval == 0:
                save_checkpoint(df, checkpoint_path)
                logger.info(f"Checkpoint saved at {count} calculated pairs.")
                
        # Final save of the checkpoint
        save_checkpoint(df, checkpoint_path)
        logger.info("All road distance calculations completed. Final checkpoint saved.")
    else:
        logger.info("No calculations remaining. Proceeding straight to ranking and reports.")
        
    # 3. Export complete candidate dataset
    prefix = "simulated" if args.simulate else "real"
    
    road_candidates_csv = os.path.join(output_dir, f"doctor_chemist_candidates_with_{prefix}_road_distance.csv")
    road_candidates_xlsx = os.path.join(output_dir, f"doctor_chemist_candidates_with_{prefix}_road_distance.xlsx")
    
    logger.info(f"Saving full candidate pairs with road distances to {road_candidates_csv}...")
    df.to_csv(road_candidates_csv, index=False)
    
    logger.info(f"Saving full candidate pairs with road distances to {road_candidates_xlsx}...")
    df.to_excel(road_candidates_xlsx, index=False, sheet_name="All Candidates")
    
    # 4. Rank chemists by road distance within each doctor
    logger.info("Ranking chemist candidates by road distance for each doctor...")
    
    # Calculate road_distance_rank
    df["road_distance_rank"] = df.groupby("doctor_id")["road_distance_km"].rank(
        method="first", 
        na_option="bottom"
    )
    
    # 5. Extract top N chemists per doctor
    top_n_mask = (df["road_distance_rank"] <= args.final_n) & (df["road_distance_status"] == "success")
    df_top_n = df[top_n_mask].copy()
    
    # Sort final output by doctor_id and road_distance_rank
    df_top_n = df_top_n.sort_values(by=["doctor_id", "road_distance_rank"]).reset_index(drop=True)
    
    # Columns to include in final output
    final_columns = [
        "doctor_id",
        "doctor_name",
        "doctor_latitude",
        "doctor_longitude",
        "doctor_pincode",
        "chemist_id",
        "chemist_name",
        "chemist_latitude",
        "chemist_longitude",
        "chemist_pincode",
        "air_distance_rank",
        "air_distance_km",
        "road_distance_rank",
        "road_distance_km",
        "road_distance_status",
        "routing_engine"
    ]
    
    df_top_n_clean = df_top_n[final_columns]
    
    top_n_csv = os.path.join(output_dir, f"final_doctor_nearest_{args.final_n}_chemists_by_{prefix}_road_distance.csv")
    top_n_xlsx = os.path.join(output_dir, f"final_doctor_nearest_{args.final_n}_chemists_by_{prefix}_road_distance.xlsx")
    
    logger.info(f"Saving final nearest {args.final_n} chemists to {top_n_csv}...")
    df_top_n_clean.to_csv(top_n_csv, index=False)
    
    logger.info(f"Saving final nearest {args.final_n} chemists to {top_n_xlsx}...")
    df_top_n_clean.to_excel(top_n_xlsx, index=False, sheet_name=f"Top {args.final_n} Chemists")
    
    # 6. Generate validation report and aggregate capture summary
    df_detail, df_summary = calculate_capture_rate_analysis(df, final_n=args.final_n)
    
    detail_path = os.path.join(output_dir, f"{prefix}_air_rank_capture_analysis.csv")
    
    if args.simulate:
        summary_path = os.path.join(output_dir, "simulated_candidate_k_capture_summary.csv")
        summary_path_txt = os.path.join(output_dir, "simulated_road_distance_run_summary.txt")
    else:
        summary_path = os.path.join(output_dir, "real_osrm_candidate_k_capture_summary.csv")
        summary_path_txt = os.path.join(output_dir, "real_osrm_road_distance_run_summary.txt")
    
    logger.info(f"Saving detailed capture rate analysis to {detail_path}...")
    df_detail.to_csv(detail_path, index=False)
    
    logger.info(f"Saving aggregate capture summary to {summary_path}...")
    df_summary.to_csv(summary_path, index=False)
    
    # 7. Clean up checkpoint file
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
        logger.info("Calculations completed successfully. Temporary checkpoint file removed.")
        
    # 8. Compile run summary
    runtime_sec = time.time() - start_time
    success_count = int((df["road_distance_status"] == "success").sum())
    failed_count = int((df["road_distance_status"] == "failed").sum())
    
    valid_road_distances = df[df["road_distance_status"] == "success"]["road_distance_km"]
    avg_road_dist = float(valid_road_distances.mean()) if not valid_road_distances.empty else 0.0
    median_road_dist = float(valid_road_distances.median()) if not valid_road_distances.empty else 0.0
    
    summary_txt = f"""==================================================
ROAD DISTANCE CALCULATIONS RUN SUMMARY
==================================================
Run Timestamp:              {run_timestamp}
Total Runtime:              {runtime_sec:.3f} seconds

INPUT INFORMATION:
- Input Candidate File:     {args.input_file}
- Total Candidate Pairs:    {total_pairs}

ROUTING OPERATIONS STATS:
- Routing Engine:           {args.routing_engine if not args.simulate else 'N/A (Simulated)'}
- Endpoint Target:          {args.osrm_endpoint if not args.simulate else 'N/A (Simulated)'}
- Successful Routes:        {success_count}
- Failed Routes:            {failed_count}

ROAD DISTANCE METRICS (SUCCESSFUL ONLY):
- Average Road Distance:    {avg_road_dist:.3f} km
- Median Road Distance:     {median_road_dist:.3f} km

FINAL RANKING PARAMETERS:
- Final N Chemists:         {args.final_n}
- Output Nearest {args.final_n} CSV:  {top_n_csv}
- Output Nearest {args.final_n} XLSX: {top_n_xlsx}

VALIDATION SUMMARY OUTPUTS:
- Detailed Capture File:    {detail_path}
- Aggregate Summary File:   {summary_path}
==================================================
"""
    with open(summary_path_txt, 'w') as f:
        f.write(summary_txt)
        
    logger.info(f"Saved run summary to {summary_path_txt}")
    logger.info("Phase 2 pipeline execution completed successfully.")

if __name__ == "__main__":
    main()

