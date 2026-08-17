# Module for writing results and summary files
import os
import json
import shutil
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional, List
from src.utils import setup_logger

logger = setup_logger("output_writer")

def write_results(
    output_dir: str,
    candidates_df: pd.DataFrame,
    invalid_doctor_df: pd.DataFrame,
    excluded_chemists_df: pd.DataFrame,
    summary_data: Dict[str, Any],
    config_data: Dict[str, Any]
) -> None:
    """
    Saves final doctor-chemist mappings, consolidated excluded chemists, invalid doctors,
    summary, and config to the outputs folder.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Save final doctor-chemist candidates (up to 5 closest chemists within 1.0 km)
    final_csv_path = os.path.join(output_dir, "final_doctor_nearest_5_chemists.csv")
    final_xlsx_path = os.path.join(output_dir, "final_doctor_nearest_5_chemists.xlsx")
    
    logger.info(f"Saving final doctor-chemist mappings ({len(candidates_df)} rows) to {final_csv_path}...")
    candidates_df.to_csv(final_csv_path, index=False)
    
    try:
        candidates_df.to_excel(final_xlsx_path, index=False, sheet_name="Top5_Chemists_Within_1KM")
        logger.info(f"Saved Excel format -> {final_xlsx_path}")
    except Exception as e:
        logger.warning(f"Could not save Excel format for candidates: {e}")
        
    # Also save legacy candidate name for compatibility if needed
    legacy_csv = os.path.join(output_dir, "doctor_chemist_candidates_air_distance.csv")
    candidates_df.to_csv(legacy_csv, index=False)
    
    # 2. Save consolidated excluded chemists with exclusion reason and stage
    excluded_chem_csv = os.path.join(output_dir, "excluded_chemists.csv")
    excluded_chem_xlsx = os.path.join(output_dir, "excluded_chemists.xlsx")
    
    logger.info(f"Saving consolidated excluded chemists ({len(excluded_chemists_df)} rows) to {excluded_chem_csv}...")
    excluded_chemists_df.to_csv(excluded_chem_csv, index=False)
    
    try:
        excluded_chemists_df.to_excel(excluded_chem_xlsx, index=False, sheet_name="Excluded_Chemists")
        logger.info(f"Saved Excel format -> {excluded_chem_xlsx}")
    except Exception as e:
        logger.warning(f"Could not save Excel format for excluded chemists: {e}")
        
    # 3. Save invalid doctor records
    invalid_doc_path = os.path.join(output_dir, "invalid_doctor_records.csv")
    logger.info(f"Saving invalid doctor records to {invalid_doc_path}...")
    invalid_doctor_df.to_csv(invalid_doc_path, index=False)
    
    # 4. Save config file
    config_path = os.path.join(output_dir, "config_used.json")
    logger.info(f"Saving configuration log to {config_path}...")
    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=2)
        
    # 5. Save run summary
    summary_path = os.path.join(output_dir, "run_summary.txt")
    logger.info(f"Saving run summary to {summary_path}...")
    
    summary_txt = f"""==================================================
DOCTOR-CHEMIST SPATIAL MATCHING RUN SUMMARY
==================================================
Run Timestamp:              {summary_data.get('timestamp', datetime.now().isoformat())}
Approximate Runtime:        {summary_data.get('runtime_sec', 0.0):.3f} seconds

INPUT FILES:
- Doctor Input File:        {summary_data.get('doctor_file', 'Unknown')}
- Chemist Input File:       {summary_data.get('chemist_file', 'Unknown')}

COLUMNS DETECTED:
- Doctor Coords (Lat/Lon):  {summary_data.get('doctor_lat_col', 'N/A')} / {summary_data.get('doctor_lon_col', 'N/A')}
- Chemist Coords (Lat/Lon): {summary_data.get('chemist_lat_col', 'N/A')} / {summary_data.get('chemist_lon_col', 'N/A')}
- Doctor ID / Name Col:     {summary_data.get('doctor_id_col', 'N/A')} / {summary_data.get('doctor_name_col', 'N/A')}
- Chemist ID / Name Col:    {summary_data.get('chemist_id_col', 'N/A')} / {summary_data.get('chemist_name_col', 'N/A')}

RECORD COUNTS:
- Doctors Loaded:           {summary_data.get('doctor_loaded_count', 0)}
- Chemists Loaded:          {summary_data.get('chemist_loaded_count', 0)}
- Valid Doctors:            {summary_data.get('doctor_valid_count', 0)}
- Valid Chemists:           {summary_data.get('chemist_valid_count', 0)}
- Invalid Doctors:          {summary_data.get('doctor_invalid_count', 0)}
- Total Excluded Chemists:  {len(excluded_chemists_df)}

EXCLUSION BREAKDOWN:
- GPS / Coordinate Errors:  {summary_data.get('chemist_gps_invalid_count', 0)}
- Pincode Boundary Mismatch:{summary_data.get('chemist_pincode_mismatched_count', 0)}
- Generic / Placeholder:    {summary_data.get('chemist_generic_excluded_count', 0)}

SPATIAL MATCHING SETTINGS:
- Max Distance Filter (KM): {summary_data.get('max_distance_km', 1.0)} km
- Final N Closest Chemists: {summary_data.get('final_n', 5)}
- Earth Radius (KM):        {summary_data.get('earth_radius_km', 6371.0088)}
- Deduplication Safeguard:  Enforced (no duplicate chemists ranked per doctor)

OUTPUT DELIVERABLES:
- Total Mapped Pairs:       {len(candidates_df)}
- Final Doctor Sheet:       final_doctor_nearest_5_chemists.xlsx (.csv)
- Excluded Chemists Sheet:  excluded_chemists.xlsx (.csv)

WARNINGS/REMARKS:
{summary_data.get('warnings', 'None.')}
==================================================
"""
    with open(summary_path, 'w') as f:
        f.write(summary_txt)
        
    logger.info("Output writer completed operations successfully.")


def publish_to_results(
    source_dir: str = "outputs",
    results_dir: str = "results"
) -> None:
    """
    Cleans the results directory (preserving .gitkeep) and copies the deliverable sheets
    and run summary text file:
    1. final_doctor_nearest_5_chemists (Excel & CSV)
    2. excluded_chemists (Excel & CSV)
    3. run_summary.txt (Detailed execution summary)
    """
    os.makedirs(results_dir, exist_ok=True)
    
    # 1. Clean existing files in results directory (preserving .gitkeep)
    for fname in os.listdir(results_dir):
        if fname == ".gitkeep":
            continue
        fpath = os.path.join(results_dir, fname)
        try:
            if os.path.isfile(fpath) or os.path.islink(fpath):
                os.unlink(fpath)
            elif os.path.isdir(fpath):
                shutil.rmtree(fpath)
        except Exception as e:
            logger.warning(f"Could not clean old results file '{fpath}': {e}")
            
    logger.info(f"Cleaned '{results_dir}' folder.")
    
    # 2. Copy the deliverable sheets and summary text file
    target_files = [
        "final_doctor_nearest_5_chemists.xlsx",
        "final_doctor_nearest_5_chemists.csv",
        "excluded_chemists.xlsx",
        "excluded_chemists.csv",
        "run_summary.txt",
        "real_osrm_road_distance_run_summary.txt"
    ]
    
    copied_count = 0
    for fname in target_files:
        src_path = os.path.join(source_dir, fname)
        if os.path.exists(src_path) and os.path.isfile(src_path):
            dst_path = os.path.join(results_dir, fname)
            shutil.copy2(src_path, dst_path)
            logger.info(f"Published to results: {fname}")
            copied_count += 1
            
    logger.info(f"Published {copied_count} deliverable files to '{results_dir}' folder (final candidates, excluded chemists, and run summary).")


