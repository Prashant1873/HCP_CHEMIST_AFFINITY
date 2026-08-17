# Standalone CLI tool to validate doctor and chemist GPS coordinates against GeoJSON pincode polygons
import os
import sys
import argparse
import json
import time
from datetime import datetime
import pandas as pd

# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src import config
from src.data_loader import auto_detect_inputs, load_data_file
from src.column_detection import detect_coordinates, detect_identifiers
from src.pincode_validator import PincodeSpatialValidator

logger = setup_logger("pincode_cli")


def process_dataset(
    file_path: str,
    role: str,
    validator: PincodeSpatialValidator,
    output_dir: str,
    tolerance_km: float,
    allow_unmapped: bool
) -> dict:
    """Processes, validates, and exports verified and mismatched subsets for a given dataset."""
    logger.info(f"--- Processing {role.upper()} dataset from '{file_path}' ---")
    
    df_raw = load_data_file(file_path)
    total_raw = len(df_raw)
    
    # Detect columns
    lat_col, lon_col = detect_coordinates(df_raw, role)
    id_col, name_col, pin_col = detect_identifiers(df_raw, role)
    
    logger.info(f"Detected columns for {role}: Lat='{lat_col}', Lon='{lon_col}', Pin='{pin_col}', ID='{id_col}', Name='{name_col}'")
    
    # Run validation
    verified_df, mismatched_df, summary = validator.validate_dataframe(
        df=df_raw,
        lat_col=lat_col,
        lon_col=lon_col,
        pin_col=pin_col,
        id_col=id_col,
        name_col=name_col,
        role=role,
        tolerance_km=tolerance_km,
        allow_unmapped_pincodes=allow_unmapped
    )
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Export verified clean dataset
    verified_csv = os.path.join(output_dir, f"verified_{role}s.csv")
    verified_xlsx = os.path.join(output_dir, f"verified_{role}s.xlsx")
    verified_df.to_csv(verified_csv, index=False)
    try:
        verified_df.to_excel(verified_xlsx, index=False)
    except Exception as e:
        logger.warning(f"Could not save Excel format for verified {role}s: {e}")
        
    # Export flagged mismatched records
    mismatched_csv = os.path.join(output_dir, f"flagged_mismatched_{role}s.csv")
    mismatched_xlsx = os.path.join(output_dir, f"flagged_mismatched_{role}s.xlsx")
    mismatched_df.to_csv(mismatched_csv, index=False)
    try:
        mismatched_df.to_excel(mismatched_xlsx, index=False)
    except Exception as e:
        logger.warning(f"Could not save Excel format for mismatched {role}s: {e}")
        
    logger.info(f"Saved verified {role}s ({len(verified_df)} records) -> '{verified_csv}'")
    logger.info(f"Saved flagged {role}s ({len(mismatched_df)} records) -> '{mismatched_csv}'")
    
    summary["input_file"] = file_path
    summary["verified_file_csv"] = verified_csv
    summary["mismatched_file_csv"] = mismatched_csv
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Pincode Coordinate Validator: Check doctor & chemist coordinates against GeoJSON pincode polygons and remove mismatches."
    )
    parser.add_argument(
        "--doctor_file",
        type=str,
        default=None,
        help="Path to doctor spreadsheet/CSV. If omitted and --input_file is not set, auto-detects in workspace."
    )
    parser.add_argument(
        "--chemist_file",
        type=str,
        default=None,
        help="Path to chemist spreadsheet/CSV. If omitted and --input_file is not set, auto-detects in workspace."
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=None,
        help="Path to a single generic input file (CSV/Excel) to validate."
    )
    parser.add_argument(
        "--role",
        type=str,
        default=None,
        choices=["doctor", "chemist", "auto"],
        help="Entity role for single input file (default: auto-detect from filename/columns)."
    )
    parser.add_argument(
        "--geojson",
        type=str,
        default=None,
        help="Path to india_pincode.geojson file (default: 'india_pincode.geojson')."
    )
    parser.add_argument(
        "--tolerance_km",
        type=float,
        default=config.DEFAULT_PINCODE_TOLERANCE_KM,
        help=f"Allowed distance (km) outside polygon boundary for border GPS jitter (default: {config.DEFAULT_PINCODE_TOLERANCE_KM} km)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enforce strict containment (tolerance = 0.0 km)."
    )
    parser.add_argument(
        "--allow_unmapped",
        action="store_true",
        help="Keep records whose stated pincode is not present in GeoJSON (default: reject as unverified)."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="results/pincode_validation",
        help="Directory to save verified and mismatched output files (default: 'results/pincode_validation')."
    )
    
    args = parser.parse_args()
    
    tolerance = 0.0 if args.strict else args.tolerance_km
    start_time = time.time()
    
    logger.info("Initializing Pincode Spatial Validator mechanism...")
    geojson_path = args.geojson or config.DEFAULT_PINCODE_GEOJSON
    validator = PincodeSpatialValidator(geojson_path=geojson_path)
    
    if not validator.is_ready:
        logger.error(f"Validator failed to load GeoJSON from '{geojson_path}'. Terminating.")
        sys.exit(1)
        
    results_summary = {
        "execution_timestamp": datetime.now().isoformat(),
        "geojson_file": geojson_path,
        "tolerance_km": tolerance,
        "strict_mode": args.strict,
        "datasets": {}
    }
    
    # If single generic input file provided
    if args.input_file:
        role = args.role or ("doctor" if "doc" in args.input_file.lower() else "chemist")
        summary = process_dataset(
            file_path=args.input_file,
            role=role,
            validator=validator,
            output_dir=args.output_dir,
            tolerance_km=tolerance,
            allow_unmapped=args.allow_unmapped
        )
        results_summary["datasets"][role] = summary
    else:
        # Check doctor and chemist files
        doc_file = args.doctor_file
        chem_file = args.chemist_file
        
        if not doc_file and not chem_file:
            det_doc, det_chem = auto_detect_inputs(".")
            doc_file = det_doc
            chem_file = det_chem
            
        if doc_file and os.path.exists(doc_file):
            summary_doc = process_dataset(
                file_path=doc_file,
                role="doctor",
                validator=validator,
                output_dir=args.output_dir,
                tolerance_km=tolerance,
                allow_unmapped=args.allow_unmapped
            )
            results_summary["datasets"]["doctor"] = summary_doc
        else:
            logger.warning(f"No doctor file found or specified: '{doc_file}'")
            
        if chem_file and os.path.exists(chem_file):
            summary_chem = process_dataset(
                file_path=chem_file,
                role="chemist",
                validator=validator,
                output_dir=args.output_dir,
                tolerance_km=tolerance,
                allow_unmapped=args.allow_unmapped
            )
            results_summary["datasets"]["chemist"] = summary_chem
        else:
            logger.warning(f"No chemist file found or specified: '{chem_file}'")
            
    total_time = round(time.time() - start_time, 2)
    results_summary["total_runtime_seconds"] = total_time
    
    # Save JSON summary report
    summary_path = os.path.join(args.output_dir, "pincode_validation_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2)
        
    # Save Markdown summary report
    md_path = os.path.join(args.output_dir, "pincode_validation_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Pincode Boundary Validation Summary Report\n\n")
        f.write(f"- **Execution Timestamp**: `{results_summary['execution_timestamp']}`\n")
        f.write(f"- **GeoJSON Reference**: `{geojson_path}`\n")
        f.write(f"- **Distance Tolerance**: `{tolerance} km`\n")
        f.write(f"- **Total Runtime**: `{total_time}s`\n\n")
        
        for role, ds in results_summary["datasets"].items():
            f.write(f"## {role.capitalize()} Dataset Validation\n\n")
            f.write(f"- **Source File**: `{ds.get('input_file')}`\n")
            f.write(f"- **Total Records**: `{ds.get('total_records')}`\n")
            f.write(f"- **Verified Valid Records**: `{ds.get('verified_valid_records')}` ({ds.get('pass_rate_percentage')}%)\n")
            f.write(f"- **Mismatched / Removed Records**: `{ds.get('mismatched_removed_records')}`\n")
            f.write(f"- **Verified Output**: `{ds.get('verified_file_csv')}`\n")
            f.write(f"- **Flagged Mismatches Output**: `{ds.get('mismatched_file_csv')}`\n\n")
            f.write("### Status Breakdown\n\n")
            f.write("| Status Category | Count |\n|---|---|\n")
            for status_name, cnt in ds.get("status_breakdown", {}).items():
                f.write(f"| `{status_name}` | {cnt} |\n")
            f.write("\n---\n\n")
            
    logger.info(f"Audit reports written to:\n  - JSON: '{summary_path}'\n  - Markdown: '{md_path}'")
    logger.info("Pincode boundary validation finished successfully.")


if __name__ == "__main__":
    main()
