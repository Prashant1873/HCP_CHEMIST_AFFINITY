# Main execution script for doctor-chemist mapping tool
import os
import sys
import time
import argparse
from datetime import datetime
import pandas as pd
import numpy as np

# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src import config
from src.data_loader import auto_detect_inputs, load_data_file
from src.column_detection import detect_coordinates, detect_identifiers
from src.data_cleaning import clean_and_validate_dataset
from src.spatial_index import build_ball_tree, find_nearest_chemists
from src.output_writer import write_results
from src.pincode_geocoder import load_pincode_lookup, recover_missing_coordinates

logger = setup_logger("main")

def main():
    parser = argparse.ArgumentParser(
        description="Scalable doctor-to-chemist nearest-neighbor air distance candidate generator."
    )
    parser.add_argument(
        "--doctor_file", 
        type=str, 
        default=None, 
        help="Path to doctor spreadsheet (CSV/Excel). If omitted, scans current directory."
    )
    parser.add_argument(
        "--chemist_file", 
        type=str, 
        default=None, 
        help="Path to chemist spreadsheet (CSV/Excel). If omitted, scans current directory."
    )
    parser.add_argument(
        "--candidate_k", 
        type=int, 
        default=config.DEFAULT_CANDIDATE_K, 
        help=f"Number of nearest air-distance chemists to shortlist per doctor (default: {config.DEFAULT_CANDIDATE_K})."
    )
    parser.add_argument(
        "--final_n", 
        type=int, 
        default=config.DEFAULT_FINAL_N, 
        help=f"Target final number of road-distance chemists to select (default: {config.DEFAULT_FINAL_N})."
    )
    parser.add_argument(
        "--output_dir", 
        type=str, 
        default="outputs", 
        help="Directory to save final output files (default: 'outputs')."
    )
    parser.add_argument(
        "--india_bbox_filter", 
        type=bool, 
        default=True, 
        help="Whether to flag and filter out coordinates outside the approximate India bounding box (default: True)."
    )
    parser.add_argument(
        "--city", 
        type=str, 
        default=None, 
        help="Filter dataset by first 3 digits of pincode or city prefix (e.g., '--city 400' for Mumbai pincodes starting with 400)."
    )
    parser.add_argument(
        "--pincode_fallback", 
        action="store_true", 
        help="Optional fallback logic to filter candidates that match same pincode (not active by default)."
    )
    parser.add_argument(
        "--use_pincode_centroids", 
        action="store_true", 
        default=False, 
        help="Optional fallback: approximate missing coordinates using pincode centroids (default: False, strict GPS only)."
    )
    
    args = parser.parse_args()
    
    start_time = time.time()
    run_timestamp = datetime.now().isoformat()
    warnings_list = []
    
    logger.info("Starting doctor-chemist spatial matching pipeline execution...")
    
    # 1. Auto-detect input files if not provided
    doctor_path = args.doctor_file
    chemist_path = args.chemist_file
    
    if not doctor_path or not chemist_path:
        logger.info("Scanning workspace directory for input files...")
        detected_doc, detected_chem = auto_detect_inputs(".")
        
        if not doctor_path and detected_doc:
            doctor_path = detected_doc
            logger.info(f"Auto-detected doctor file: {doctor_path}")
        elif not doctor_path:
            logger.error("Could not auto-detect doctor file. Please specify --doctor_file.")
            sys.exit(1)
            
        if not chemist_path and detected_chem:
            chemist_path = detected_chem
            logger.info(f"Auto-detected chemist file: {chemist_path}")
        elif not chemist_path:
            logger.error("Could not auto-detect chemist file. Please specify --chemist_file.")
            sys.exit(1)
            
    # 2. Load input datasets
    try:
        df_doctor_raw = load_data_file(doctor_path)
        df_chemist_raw = load_data_file(chemist_path)
    except Exception as e:
        logger.exception(f"Error loading files: {str(e)}")
        sys.exit(1)
        
    doc_loaded_count = len(df_doctor_raw)
    chem_loaded_count = len(df_chemist_raw)
    
    # 3. Detect coordinate & identifier columns
    try:
        # Doctor column detection
        doc_lat_col, doc_lon_col = detect_coordinates(df_doctor_raw, "doctor")
        doc_id_col, doc_name_col, doc_pin_col = detect_identifiers(df_doctor_raw, "doctor")
        
        # Chemist column detection
        chem_lat_col, chem_lon_col = detect_coordinates(df_chemist_raw, "chemist")
        chem_id_col, chem_name_col, chem_pin_col = detect_identifiers(df_chemist_raw, "chemist")
    except ValueError as ve:
        logger.error(f"Column detection failed: {str(ve)}")
        sys.exit(1)
        
    # 4. Save record index inside raw dataframes before cleaning
    df_doctor_raw["doctor_record_index"] = df_doctor_raw.index
    df_chemist_raw["chemist_record_index"] = df_chemist_raw.index
    
    # 5. Clean & Validate datasets
    valid_doc_df, invalid_doc_df = clean_and_validate_dataset(
        df=df_doctor_raw,
        lat_col=doc_lat_col,
        lon_col=doc_lon_col,
        id_col=doc_id_col,
        name_col=doc_name_col,
        pin_col=doc_pin_col,
        role="doctor"
    )
    
    valid_chem_df, invalid_chem_df = clean_and_validate_dataset(
        df=df_chemist_raw,
        lat_col=chem_lat_col,
        lon_col=chem_lon_col,
        id_col=chem_id_col,
        name_col=chem_name_col,
        pin_col=chem_pin_col,
        role="chemist"
    )
    
    # 5a. Log auto-corrected inversions (now in valid set with coordinate_corrected flag)
    if "coordinate_corrected" in valid_doc_df.columns:
        doc_corrected = valid_doc_df[valid_doc_df["coordinate_corrected"] == "lat_lon_swapped"]
    else:
        doc_corrected = pd.DataFrame()
    if "coordinate_corrected" in valid_chem_df.columns:
        chem_corrected = valid_chem_df[valid_chem_df["coordinate_corrected"] == "lat_lon_swapped"]
    else:
        chem_corrected = pd.DataFrame()
    
    if len(doc_corrected) > 0:
        msg = f"Auto-corrected {len(doc_corrected)} doctor records with inverted lat/lon coordinates (swapped and retained)."
        warnings_list.append(msg)
        logger.info(msg)
        
    if len(chem_corrected) > 0:
        msg = f"Auto-corrected {len(chem_corrected)} chemist records with inverted lat/lon coordinates (swapped and retained)."
        warnings_list.append(msg)
        logger.info(msg)
    
    # 5b. Optional pincode geocoding recovery (disabled by default to maintain strict GPS precision)
    if args.use_pincode_centroids:
        pincode_lookup = load_pincode_lookup()
        
        if pincode_lookup:
            recovered_doc, invalid_doc_df = recover_missing_coordinates(invalid_doc_df, "doctor", pincode_lookup)
            recovered_chem, invalid_chem_df = recover_missing_coordinates(invalid_chem_df, "chemist", pincode_lookup)
            
            if len(recovered_doc) > 0:
                valid_doc_df = pd.concat([valid_doc_df, recovered_doc], ignore_index=True)
                msg = f"Recovered {len(recovered_doc)} doctor records via pincode centroid approximation."
                warnings_list.append(msg)
                logger.info(msg)
                
            if len(recovered_chem) > 0:
                valid_chem_df = pd.concat([valid_chem_df, recovered_chem], ignore_index=True)
                msg = f"Recovered {len(recovered_chem)} chemist records via pincode centroid approximation."
                warnings_list.append(msg)
                logger.info(msg)
    else:
        logger.info("Strict GPS mode enabled: records without verified GPS coordinates are excluded from matching.")
    
    # 5c. Optional city / pincode prefix filtering
    if args.city:
        city_filters = [c.strip() for c in str(args.city).split(",") if c.strip()]
        logger.info(f"Applying city/pincode prefix filter: {city_filters}")
        
        doc_mask = pd.Series(False, index=valid_doc_df.index)
        chem_mask = pd.Series(False, index=valid_chem_df.index)
        
        for filt in city_filters:
            if filt.isdigit():
                # Match pincode starting with digits (e.g. '400')
                doc_mask |= valid_doc_df["doctor_pincode"].astype(str).str.startswith(filt)
                chem_mask |= valid_chem_df["chemist_pincode"].astype(str).str.startswith(filt)
            else:
                # Textual city name matching fallback
                filt_clean = "".join(c for c in filt.lower() if c.isalnum())
                for col in valid_doc_df.columns:
                    if "city" in col.lower():
                        doc_mask |= valid_doc_df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
                for col in valid_chem_df.columns:
                    if "city" in col.lower():
                        chem_mask |= valid_chem_df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
                        
        valid_doc_df = valid_doc_df[doc_mask].reset_index(drop=True)
        valid_chem_df = valid_chem_df[chem_mask].reset_index(drop=True)
        
        logger.info(
            f"Filtered records for city/pincode filter '{args.city}': "
            f"{len(valid_doc_df)} doctors and {len(valid_chem_df)} chemists retained."
        )
        
        if len(valid_doc_df) == 0:
            logger.error(f"No doctor records matched city/pincode filter '{args.city}'. Matching pipeline terminated.")
            sys.exit(1)
        if len(valid_chem_df) == 0:
            logger.error(f"No chemist records matched city/pincode filter '{args.city}'. Matching pipeline terminated.")
            sys.exit(1)

    doc_valid_count = len(valid_doc_df)
    doc_invalid_count = len(invalid_doc_df)
    chem_valid_count = len(valid_chem_df)
    chem_invalid_count = len(invalid_chem_df)
    
    if doc_invalid_count > 0:
        msg = f"Flagged {doc_invalid_count} invalid doctor records (written to invalid_doctor_records.csv)"
        warnings_list.append(msg)
        logger.warning(msg)
        
    if chem_invalid_count > 0:
        msg = f"Excluded {chem_invalid_count} chemist records without verified GPS coordinates (written to invalid_chemist_records.csv)"
        warnings_list.append(msg)
        logger.info(msg)
        
    # 6. Build Spatial Index & Query Nearest Neighbors
    try:
        tree, _ = build_ball_tree(valid_chem_df)
        candidates_df = find_nearest_chemists(
            doctor_df=valid_doc_df,
            chemist_df=valid_chem_df,
            tree=tree,
            candidate_k=args.candidate_k
        )
    except Exception as e:
        logger.exception(f"Error during spatial querying: {str(e)}")
        sys.exit(1)
        
    # 7. Optional pincode filtering (for demonstration / fallback logic)
    if args.pincode_fallback:
        logger.info("Applying optional pincode match ranking fallback...")
        # Add a column indicating if pincode matches
        candidates_df["pincode_match"] = (
            candidates_df["doctor_pincode"] == candidates_df["chemist_chemist_pincode"]
        )
        # Note: In real life, we can filter or re-rank. But here we just flag.
        
    # 8. Verification checks
    expected_rows = doc_valid_count * min(args.candidate_k, chem_valid_count)
    if len(candidates_df) != expected_rows:
        msg = f"Output row count mismatch. Expected: {expected_rows}, Generated: {len(candidates_df)}"
        warnings_list.append(msg)
        logger.warning(msg)
        
    # 9. Format output summaries and configs
    runtime_sec = time.time() - start_time
    logger.info(f"Pipeline executed in {runtime_sec:.3f} seconds.")
    
    summary_data = {
        "timestamp": run_timestamp,
        "runtime_sec": runtime_sec,
        "city_filter": args.city,
        "doctor_file": doctor_path,
        "chemist_file": chemist_path,
        "doctor_lat_col": doc_lat_col,
        "doctor_lon_col": doc_lon_col,
        "chemist_lat_col": chem_lat_col,
        "chemist_lon_col": chem_lon_col,
        "doctor_id_col": doc_id_col,
        "doctor_name_col": doc_name_col,
        "chemist_id_col": chem_id_col,
        "chemist_name_col": chem_name_col,
        "doctor_loaded_count": doc_loaded_count,
        "chemist_loaded_count": chem_loaded_count,
        "doctor_valid_count": doc_valid_count,
        "chemist_valid_count": chem_valid_count,
        "doctor_invalid_count": doc_invalid_count,
        "chemist_invalid_count": chem_invalid_count,
        "candidate_k": args.candidate_k,
        "final_n": args.final_n,
        "earth_radius_km": config.EARTH_RADIUS_KM,
        "india_bbox_filter": args.india_bbox_filter,
        "total_pairs_generated": len(candidates_df),
        "warnings": "\n".join(warnings_list) if warnings_list else "None."
    }
    
    config_used = {
        "doctor_file": doctor_path,
        "chemist_file": chemist_path,
        "doctor_lat_col": doc_lat_col,
        "doctor_lon_col": doc_lon_col,
        "chemist_lat_col": chem_lat_col,
        "chemist_lon_col": chem_lon_col,
        "doctor_id_col": doc_id_col,
        "chemist_id_col": chem_id_col,
        "candidate_k": args.candidate_k,
        "final_n": args.final_n,
        "earth_radius_km": config.EARTH_RADIUS_KM,
        "india_bbox_filter": args.india_bbox_filter,
        "road_distance_calculated": False
    }
    
    # 10. Write outputs
    try:
        write_results(
            output_dir=args.output_dir,
            candidates_df=candidates_df,
            invalid_doctor_df=invalid_doc_df,
            invalid_chemist_df=invalid_chem_df,
            summary_data=summary_data,
            config_data=config_used
        )
    except Exception as e:
        logger.exception(f"Error saving outputs: {str(e)}")
        sys.exit(1)
        
    logger.info("Doctor-Chemist Matching Pipeline execution completed successfully.")

if __name__ == "__main__":
    main()
