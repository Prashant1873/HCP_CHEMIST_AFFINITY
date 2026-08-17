# Standalone CLI tool to identify, audit, and exclude generic/placeholder names from Chemist datasets
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
from src.data_loader import load_data_file, auto_detect_inputs
from src.column_detection import detect_identifiers
from src.name_cleaner import filter_generic_names, is_generic_name

logger = setup_logger("generic_filter_cli")


def main():
    parser = argparse.ArgumentParser(
        description="Filter Generic Chemist Names: Exclude unbranded placeholders like 'Chemist', 'Medical', 'Pharmacy', 'Drug Store'."
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=None,
        help="Path to chemist spreadsheet (Excel/CSV). If omitted, scans workspace for chemist file."
    )
    parser.add_argument(
        "--name_col",
        type=str,
        default=None,
        help="Column containing chemist/store names (default: auto-detected)."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="results/generic_name_audit",
        help="Directory to save clean and excluded output files (default: 'results/generic_name_audit')."
    )
    parser.add_argument(
        "--additional_keywords",
        type=str,
        default=None,
        help="Comma-separated list of additional custom keywords to flag as generic (e.g. 'Store,Shop,Dealer')."
    )
    
    args = parser.parse_args()
    
    input_file = args.input_file
    if not input_file:
        _, det_chem = auto_detect_inputs(".")
        input_file = det_chem
        if not input_file:
            logger.error("Could not auto-detect chemist file. Please provide --input_file.")
            sys.exit(1)
            
    logger.info(f"Loading chemist dataset from '{input_file}'...")
    df = load_data_file(input_file)
    
    # Detect name column if not specified
    name_col = args.name_col
    if not name_col or name_col not in df.columns:
        _, det_name_col, _ = detect_identifiers(df, "chemist")
        name_col = det_name_col
        if not name_col or name_col not in df.columns:
            logger.error(f"Could not auto-detect chemist name column in {list(df.columns)}. Use --name_col.")
            sys.exit(1)
            
    logger.info(f"Using chemist name column: '{name_col}'")
    
    # Parse custom keywords if provided
    custom_kws = None
    if args.additional_keywords:
        custom_kws = [k.strip() for k in args.additional_keywords.split(",") if k.strip()]
        logger.info(f"Applying custom generic keywords: {custom_kws}")
        
    start_time = time.time()
    clean_df, generic_df, summary = filter_generic_names(
        df=df,
        name_col=name_col,
        role="chemist",
        additional_keywords=custom_kws
    )
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Save outputs
    clean_csv = os.path.join(args.output_dir, "retained_distinctive_chemists.csv")
    clean_xlsx = os.path.join(args.output_dir, "retained_distinctive_chemists.xlsx")
    generic_csv = os.path.join(args.output_dir, "excluded_generic_chemists.csv")
    generic_xlsx = os.path.join(args.output_dir, "excluded_generic_chemists.xlsx")
    
    clean_df.to_csv(clean_csv, index=False)
    try:
        clean_df.to_excel(clean_xlsx, index=False)
    except Exception as e:
        logger.warning(f"Could not save Excel format for clean data: {e}")
        
    generic_df.to_csv(generic_csv, index=False)
    try:
        generic_df.to_excel(generic_xlsx, index=False)
    except Exception as e:
        logger.warning(f"Could not save Excel format for generic data: {e}")
        
    summary_path = os.path.join(args.output_dir, "generic_filter_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    # Save Markdown report
    md_path = os.path.join(args.output_dir, "generic_filter_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Generic Chemist Name Filtering Report\n\n")
        f.write(f"- **Input File**: `{input_file}`\n")
        f.write(f"- **Name Column**: `{name_col}`\n")
        f.write(f"- **Total Records**: `{summary['total_records']}`\n")
        f.write(f"- **Retained Distinctive Records**: `{summary['retained_records']}` ({100 - summary['generic_percentage']:.2f}%)\n")
        f.write(f"- **Excluded Generic Records**: `{summary['generic_excluded_records']}` ({summary['generic_percentage']}%)\n")
        f.write(f"- **Clean Output**: `{clean_csv}`\n")
        f.write(f"- **Excluded Generic Output**: `{generic_csv}`\n\n")
        f.write("### Top Excluded Generic Store Names\n\n")
        f.write("| Generic Store Name | Count |\n|---|---|\n")
        for g_name, cnt in summary.get("top_excluded_names", {}).items():
            f.write(f"| `{g_name}` | {cnt} |\n")
            
    logger.info(f"Clean records ({len(clean_df)}) saved -> '{clean_csv}'")
    logger.info(f"Excluded generic records ({len(generic_df)}) saved -> '{generic_csv}'")
    logger.info(f"Audit summary written -> '{summary_path}' and '{md_path}'")
    logger.info(f"Generic name filtering completed in {time.time() - start_time:.2f}s.")


if __name__ == "__main__":
    main()
