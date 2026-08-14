# Module for writing results and summary files
import os
import json
import pandas as pd
from datetime import datetime
from typing import Dict, Any
from src.utils import setup_logger

logger = setup_logger("output_writer")

def write_results(
    output_dir: str,
    candidates_df: pd.DataFrame,
    invalid_doctor_df: pd.DataFrame,
    invalid_chemist_df: pd.DataFrame,
    summary_data: Dict[str, Any],
    config_data: Dict[str, Any]
) -> None:
    """
    Saves candidate pairs, invalid files, summary, and config to the outputs folder.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Save candidates CSV & Excel
    csv_path = os.path.join(output_dir, "doctor_chemist_candidates_air_distance.csv")
    xlsx_path = os.path.join(output_dir, "doctor_chemist_candidates_air_distance.xlsx")
    
    logger.info(f"Saving candidates to {csv_path}...")
    candidates_df.to_csv(csv_path, index=False)
    
    logger.info(f"Saving candidates to {xlsx_path}...")
    # Using openpyxl to write Excel file
    candidates_df.to_excel(xlsx_path, index=False, sheet_name="Candidates")
    
    # 2. Save invalid files (only columns that were in the original dataframe + reason)
    invalid_doc_path = os.path.join(output_dir, "invalid_doctor_records.csv")
    invalid_chem_path = os.path.join(output_dir, "invalid_chemist_records.csv")
    
    logger.info(f"Saving invalid doctor records to {invalid_doc_path}...")
    invalid_doctor_df.to_csv(invalid_doc_path, index=False)
    
    logger.info(f"Saving invalid chemist records to {invalid_chem_path}...")
    invalid_chemist_df.to_csv(invalid_chem_path, index=False)
    
    # 3. Save config file
    config_path = os.path.join(output_dir, "config_used.json")
    logger.info(f"Saving configuration log to {config_path}...")
    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=2)
        
    # 4. Save run summary
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
- Invalid Chemists:         {summary_data.get('chemist_invalid_count', 0)}

SPATIAL MATCHING SETTINGS:
- Candidate K Shortlisted:  {summary_data.get('candidate_k', 50)}
- Final N Chemists:         {summary_data.get('final_n', 5)}
- Earth Radius (KM):        {summary_data.get('earth_radius_km', 6371.0088)}
- India Bounding Box Filter:{summary_data.get('india_bbox_filter', True)}

OUTPUT STATS:
- Total Candidate Pairs:    {summary_data.get('total_pairs_generated', 0)}

WARNINGS/REMARKS:
{summary_data.get('warnings', 'None.')}
==================================================
"""
    with open(summary_path, 'w') as f:
        f.write(summary_txt)
        
    logger.info("Output writer completed operations successfully.")


def publish_to_results(
    source_dir: str = "outputs",
    results_dir: str = "results",
    file_list: Any = None
) -> None:
    """
    Cleans the results directory (preserving .gitkeep) and copies ONLY the final
    real road distance sheets and summary text files from source_dir to results_dir.
    """
    import shutil
    
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
    
    # 2. Determine files to publish: ONLY real road distance sheets and real summary text files
    if file_list is None:
        file_list = []
        if os.path.exists(source_dir):
            for f in os.listdir(source_dir):
                # Strictly exclude simulated runs
                if "simulated" in f.lower():
                    continue
                    
                # 1. Final real road distance sheets (.csv and .xlsx)
                is_final_sheet = f.startswith("final_doctor_nearest_") and (f.endswith(".csv") or f.endswith(".xlsx"))
                # 2. Summary text files (.txt)
                is_summary_txt = f.endswith("_summary.txt") or f == "run_summary.txt"
                
                if is_final_sheet or is_summary_txt:
                    file_list.append(f)
        
    copied_count = 0
    for fname in sorted(file_list):
        src_path = os.path.join(source_dir, fname)
        if os.path.exists(src_path) and os.path.isfile(src_path):
            dst_path = os.path.join(results_dir, fname)
            shutil.copy2(src_path, dst_path)
            logger.info(f"Published to results: {fname}")
            copied_count += 1
            
    logger.info(f"Published {copied_count} final deliverable files to '{results_dir}' folder.")
