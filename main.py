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
from src.output_writer import write_results, publish_to_results
from src.pincode_geocoder import load_pincode_lookup, recover_missing_coordinates
from src.pincode_validator import PincodeSpatialValidator
from src.name_cleaner import filter_generic_names

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
        help="Filter dataset by city name (e.g., '--city Mumbai' or '--city Mumbai,Pune'). Supports comma-separated city names."
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
    parser.add_argument(
        "--geocoded_chemist_file",
        type=str,
        default=None,
        help="Path to address-geocoded chemist CSV (default: auto-detects outputs/geocoded_chemist_records.csv if present)."
    )
    parser.add_argument(
        "--verify_pincodes",
        action="store_true",
        default=config.VERIFY_PINCODES_DEFAULT,
        help="Verify doctor and chemist coordinates against GeoJSON pincode boundaries and filter out mismatches (default: True)."
    )
    parser.add_argument(
        "--no_pincode_verification",
        dest="verify_pincodes",
        action="store_false",
        help="Disable GeoJSON pincode boundary verification."
    )
    parser.add_argument(
        "--pincode_tolerance_km",
        type=float,
        default=config.DEFAULT_PINCODE_TOLERANCE_KM,
        help=f"Allowed distance (km) outside pincode polygon for border leniency (default: {config.DEFAULT_PINCODE_TOLERANCE_KM} km)."
    )
    parser.add_argument(
        "--pincode_geojson",
        type=str,
        default=config.DEFAULT_PINCODE_GEOJSON,
        help=f"Path to pincode GeoJSON boundary file (default: '{config.DEFAULT_PINCODE_GEOJSON}')."
    )
    parser.add_argument(
        "--exclude_generic_names",
        action="store_true",
        default=config.EXCLUDE_GENERIC_CHEMIST_NAMES,
        help="Exclude generic placeholder store names like 'Chemist', 'Medical', 'Pharmacy', 'Drug Store' (default: True)."
    )
    parser.add_argument(
        "--no_generic_filter",
        dest="exclude_generic_names",
        action="store_false",
        help="Disable filtering of generic chemist store names."
    )
    parser.add_argument(
        "--max_distance_km",
        type=float,
        default=config.DEFAULT_MAX_DISTANCE_KM,
        help=f"Hard distance filter: exclude any chemist candidate farther than this distance (default: {config.DEFAULT_MAX_DISTANCE_KM} km)."
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
    
    # 5b. Auto-integrate previously geocoded addresses if available
    geocoded_file = args.geocoded_chemist_file or os.path.join(args.output_dir, "geocoded_chemist_records.csv")
    if os.path.exists(geocoded_file):
        try:
            geo_df = pd.read_csv(geocoded_file, dtype=str)
            if "geocoded_status" in geo_df.columns:
                success_geo = geo_df[geo_df["geocoded_status"] == "success"].copy()
                if len(success_geo) > 0 and not invalid_chem_df.empty:
                    id_col_cand = [c for c in ["IQVIA ID", "chemist_id", "original_id"] if c in success_geo.columns]
                    if id_col_cand:
                        id_col_key = id_col_cand[0]
                        geo_map = {}
                        for _, g_row in success_geo.iterrows():
                            cid = str(g_row[id_col_key]).strip()
                            try:
                                glat = float(g_row["geocoded_latitude"])
                                glon = float(g_row["geocoded_longitude"])
                                geo_map[cid] = (glat, glon)
                            except (ValueError, TypeError):
                                continue
                                
                        recovered_rows = []
                        still_invalid_indices = []
                        
                        for idx, row in invalid_chem_df.iterrows():
                            cid = str(row.get("chemist_id", row.get("IQVIA ID", ""))).strip()
                            orig_id = str(row.get("original_id", "")).strip()
                            match_key = cid if cid in geo_map else (orig_id if orig_id in geo_map else None)
                            
                            if match_key:
                                row_copy = row.copy()
                                row_copy["chemist_latitude"] = geo_map[match_key][0]
                                row_copy["chemist_longitude"] = geo_map[match_key][1]
                                row_copy["coordinate_source"] = "address_geocoded"
                                if "rejection_reason" in row_copy:
                                    row_copy = row_copy.drop(labels=["rejection_reason"])
                                recovered_rows.append(row_copy)
                            else:
                                still_invalid_indices.append(idx)
                                
                        if recovered_rows:
                            rec_df = pd.DataFrame(recovered_rows)
                            valid_chem_df = pd.concat([valid_chem_df, rec_df], ignore_index=True)
                            invalid_chem_df = invalid_chem_df.loc[still_invalid_indices].reset_index(drop=True)
                            msg = f"Auto-loaded and recovered {len(recovered_rows)} chemist records with verified GPS coordinates from '{geocoded_file}'."
                            warnings_list.append(msg)
                            logger.info(msg)
        except Exception as e:
            logger.warning(f"Could not auto-integrate geocoded file '{geocoded_file}': {e}")
    
    # 5c. Optional pincode geocoding recovery (disabled by default to maintain strict GPS precision)
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
    
    # 5c. Optional city filtering by city name
    if args.city:
        city_filters = [c.strip() for c in str(args.city).split(",") if c.strip()]
        logger.info(f"Applying city filter: {city_filters}")
        
        doc_mask = pd.Series(False, index=valid_doc_df.index)
        chem_mask = pd.Series(False, index=valid_chem_df.index)
        
        for filt in city_filters:
            filt_clean = "".join(c for c in filt.lower() if c.isalnum())
            if not filt_clean:
                continue
                
            filt_doc_mask = pd.Series(False, index=valid_doc_df.index)
            filt_chem_mask = pd.Series(False, index=valid_chem_df.index)
            
            # Match doctor city columns
            for col in valid_doc_df.columns:
                if "city" in col.lower():
                    filt_doc_mask |= valid_doc_df[col].astype(str).apply(
                        lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                    )
            # Address fallback if no match in city column
            if not filt_doc_mask.any():
                for col in valid_doc_df.columns:
                    if any(k in col.lower() for k in ["addr", "location"]):
                        filt_doc_mask |= valid_doc_df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
                        
            # Match chemist city columns
            for col in valid_chem_df.columns:
                if "city" in col.lower():
                    filt_chem_mask |= valid_chem_df[col].astype(str).apply(
                        lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                    )
            # Address fallback if no match in city column
            if not filt_chem_mask.any():
                for col in valid_chem_df.columns:
                    if any(k in col.lower() for k in ["addr", "location"]):
                        filt_chem_mask |= valid_chem_df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
                        
            # Numeric pincode prefix fallback if digits are provided
            if filt.isdigit():
                if "doctor_pincode" in valid_doc_df.columns:
                    filt_doc_mask |= valid_doc_df["doctor_pincode"].astype(str).str.startswith(filt)
                if "chemist_pincode" in valid_chem_df.columns:
                    filt_chem_mask |= valid_chem_df["chemist_pincode"].astype(str).str.startswith(filt)
                    
            doc_mask |= filt_doc_mask
            chem_mask |= filt_chem_mask
                        
        valid_doc_df = valid_doc_df[doc_mask].reset_index(drop=True)
        valid_chem_df = valid_chem_df[chem_mask].reset_index(drop=True)
        
        logger.info(
            f"Filtered records for city filter '{args.city}': "
            f"{len(valid_doc_df)} doctors and {len(valid_chem_df)} chemists retained."
        )
        
        if len(valid_doc_df) == 0:
            logger.error(f"No doctor records matched city filter '{args.city}'. Matching pipeline terminated.")
            sys.exit(1)
        if len(valid_chem_df) == 0:
            logger.error(f"No chemist records matched city filter '{args.city}'. Matching pipeline terminated.")
            sys.exit(1)

    # 5d. Optional GeoJSON Pincode Boundary Validation
    pincode_mismatched_docs = pd.DataFrame()
    pincode_mismatched_chems = pd.DataFrame()
    if args.verify_pincodes:
        logger.info(f"Running GeoJSON pincode boundary validation (tolerance: {args.pincode_tolerance_km} km)...")
        validator = PincodeSpatialValidator(geojson_path=args.pincode_geojson)
        if validator.is_ready:
            valid_doc_df, pincode_mismatched_docs, doc_pin_summary = validator.validate_dataframe(
                df=valid_doc_df,
                lat_col="doctor_latitude",
                lon_col="doctor_longitude",
                pin_col="doctor_pincode",
                role="doctor",
                tolerance_km=args.pincode_tolerance_km
            )
            valid_chem_df, pincode_mismatched_chems, chem_pin_summary = validator.validate_dataframe(
                df=valid_chem_df,
                lat_col="chemist_latitude",
                lon_col="chemist_longitude",
                pin_col="chemist_pincode",
                role="chemist",
                tolerance_km=args.pincode_tolerance_km
            )
            
            if len(pincode_mismatched_docs) > 0:
                msg = f"GeoJSON Pincode Validation flagged and removed {len(pincode_mismatched_docs)} doctor records with mismatched coordinates."
                warnings_list.append(msg)
                logger.warning(msg)
                os.makedirs(args.output_dir, exist_ok=True)
                pincode_mismatched_docs.to_csv(os.path.join(args.output_dir, "pincode_mismatched_doctor_records.csv"), index=False)
                
            if len(pincode_mismatched_chems) > 0:
                msg = f"GeoJSON Pincode Validation flagged and removed {len(pincode_mismatched_chems)} chemist records with mismatched coordinates."
                warnings_list.append(msg)
                logger.warning(msg)
                os.makedirs(args.output_dir, exist_ok=True)
                pincode_mismatched_chems.to_csv(os.path.join(args.output_dir, "pincode_mismatched_chemist_records.csv"), index=False)

    # 5e. Generic Name Filtering (exclude pure placeholders like 'Chemist', 'Medical', 'Pharmacy', 'Drug Store')
    excluded_generic_chems = pd.DataFrame()
    if args.exclude_generic_names:
        valid_chem_df, excluded_generic_chems, generic_summary = filter_generic_names(
            df=valid_chem_df,
            name_col="chemist_name",
            role="chemist",
            additional_keywords=config.ADDITIONAL_GENERIC_KEYWORDS
        )
        if len(excluded_generic_chems) > 0:
            msg = f"Excluded {len(excluded_generic_chems)} chemist records with generic/placeholder names (e.g. 'Chemist', 'Medical', 'Pharmacy', 'Drug Store')."
            warnings_list.append(msg)
            logger.info(msg)
            os.makedirs(args.output_dir, exist_ok=True)
            excluded_generic_chems.to_csv(
                os.path.join(args.output_dir, "excluded_generic_chemist_records.csv"),
                index=False
            )

    # Consolidate ALL excluded chemists across all exclusion stages
    excluded_chemists_list = []
    
    if len(invalid_chem_df) > 0:
        df_inv = invalid_chem_df.copy()
        df_inv["exclusion_stage"] = "GPS_COORDINATE_ERROR"
        df_inv["exclusion_reason"] = df_inv["rejection_reason"] if "rejection_reason" in df_inv.columns else "Invalid or missing GPS coordinates"
        excluded_chemists_list.append(df_inv)
        
    if len(pincode_mismatched_chems) > 0:
        df_pin = pincode_mismatched_chems.copy()
        df_pin["exclusion_stage"] = "PINCODE_BOUNDARY_MISMATCH"
        df_pin["exclusion_reason"] = df_pin["pincode_rejection_reason"] if "pincode_rejection_reason" in df_pin.columns else "Coordinates outside stated pincode boundary"
        excluded_chemists_list.append(df_pin)
        
    if len(excluded_generic_chems) > 0:
        df_gen = excluded_generic_chems.copy()
        df_gen["exclusion_stage"] = "GENERIC_NAME_EXCLUSION"
        df_gen["exclusion_reason"] = df_gen["generic_exclusion_reason"] if "generic_exclusion_reason" in df_gen.columns else "Generic placeholder store name"
        excluded_chemists_list.append(df_gen)
        
    if excluded_chemists_list:
        excluded_chemists_master = pd.concat(excluded_chemists_list, ignore_index=True)
    else:
        excluded_chemists_master = pd.DataFrame()

    doc_valid_count = len(valid_doc_df)
    doc_invalid_count = len(invalid_doc_df) + len(pincode_mismatched_docs)
    chem_valid_count = len(valid_chem_df)
    chem_invalid_count = len(excluded_chemists_master)
    
    if doc_invalid_count > 0:
        msg = f"Flagged {doc_invalid_count} invalid doctor records (written to invalid_doctor_records.csv)"
        warnings_list.append(msg)
        logger.warning(msg)
        
    if chem_invalid_count > 0:
        msg = f"Excluded {chem_invalid_count} chemist records across GPS, Pincode, and Generic Name tests (written to excluded_chemists.csv)"
        warnings_list.append(msg)
        logger.info(msg)

    # 5f. Deduplication safeguard on chemist dataset before building spatial index
    initial_chem_pool = len(valid_chem_df)
    if "chemist_id" in valid_chem_df.columns and valid_chem_df["chemist_id"].notna().any():
        valid_chem_df = valid_chem_df.drop_duplicates(subset=["chemist_id"]).reset_index(drop=True)
    else:
        valid_chem_df = valid_chem_df.drop_duplicates(subset=["chemist_name", "chemist_latitude", "chemist_longitude"]).reset_index(drop=True)
        
    dedup_removed = initial_chem_pool - len(valid_chem_df)
    if dedup_removed > 0:
        logger.info(f"Deduplication safeguard: removed {dedup_removed} duplicate chemist records before spatial indexing.")
        
    # 6. Build Spatial Index & Query Nearest Neighbors (Hard filtered to <= 1.0 km)
    try:
        tree, _ = build_ball_tree(valid_chem_df)
        candidates_df = find_nearest_chemists(
            doctor_df=valid_doc_df,
            chemist_df=valid_chem_df,
            tree=tree,
            candidate_k=args.candidate_k,
            final_n=args.final_n,
            max_distance_km=args.max_distance_km
        )
    except Exception as e:
        logger.exception(f"Error during spatial querying: {str(e)}")
        sys.exit(1)
        
    # 7. Optional pincode filtering (for demonstration / fallback logic)
    if args.pincode_fallback and not candidates_df.empty:
        logger.info("Applying optional pincode match ranking fallback...")
        candidates_df["pincode_match"] = (
            candidates_df["doctor_pincode"] == candidates_df["chemist_chemist_pincode"]
        )
        
    # 8. Format output summaries and configs
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
        "chemist_gps_invalid_count": len(invalid_chem_df),
        "chemist_pincode_mismatched_count": len(pincode_mismatched_chems),
        "chemist_generic_excluded_count": len(excluded_generic_chems),
        "candidate_k": args.candidate_k,
        "final_n": args.final_n,
        "max_distance_km": args.max_distance_km,
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
        "max_distance_km": args.max_distance_km,
        "earth_radius_km": config.EARTH_RADIUS_KM,
        "india_bbox_filter": args.india_bbox_filter,
        "road_distance_calculated": False
    }
    
    # 9. Write outputs
    try:
        write_results(
            output_dir=args.output_dir,
            candidates_df=candidates_df,
            invalid_doctor_df=invalid_doc_df,
            excluded_chemists_df=excluded_chemists_master,
            summary_data=summary_data,
            config_data=config_used
        )
    except Exception as e:
        logger.exception(f"Error saving outputs: {str(e)}")
        sys.exit(1)
        
    # 10. Move key deliverables to results folder (exactly 2 sheets)
    try:
        publish_to_results(source_dir=args.output_dir, results_dir="results")
    except Exception as e:
        logger.warning(f"Could not publish outputs to results folder: {e}")
        
    logger.info("Doctor-Chemist Matching Pipeline execution completed successfully.")

if __name__ == "__main__":
    main()

