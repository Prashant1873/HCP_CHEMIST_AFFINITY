import os
import sys
import time
import argparse
import json
import logging
from datetime import datetime
import pandas as pd
import numpy as np
from tqdm import tqdm

# Import modules from src
from config import Config
from src.data_loader import load_chemist_data
from src.text_standardization import process_address, standardize_chemist_name
from src.city_state_normalization import CityStateNormalizer
from src.address_quality import analyze_address_quality
from src.pincode_reference import load_pincode_reference
from src.pincode_validation import validate_pincode_record, extract_pincodes_from_str
from src.coordinate_validation import validate_coordinates
from src.geocoding_engine import GeocodingEngine
from src.reverse_geocoding import ReverseGeocodingEngine
from src.confidence_scoring import calculate_confidence_scores
from src.correction_engine import apply_safe_corrections
from src.output_writer import write_dataframes_to_outputs, write_quality_dashboard

def parse_args():
    parser = argparse.ArgumentParser(description="Chemist Master Location-Quality Cleansing Pipeline")
    parser.add_argument("--input_file", type=str, default="Chemist_test_HCM.xlsx", help="Input excel or csv file path")
    parser.add_argument("--sheet_name", type=str, default="Chemist", help="Excel sheet name to load")
    parser.add_argument("--geocoding_mode", type=str, default="OFFLINE_ONLY", 
                        choices=["OFFLINE_ONLY", "PUBLIC_NOMINATIM_SAMPLE_ONLY", "SELF_HOSTED_NOMINATIM", "CUSTOM_API"],
                        help="Geocoding lookup mode")
    parser.add_argument("--city_outlier_warning_km", type=float, default=50.0, help="City distance outlier warning threshold in km")
    parser.add_argument("--city_outlier_critical_km", type=float, default=100.0, help="City distance outlier critical threshold in km")
    return parser.parse_args()

def setup_logger(outputs_dir):
    os.makedirs(outputs_dir, exist_ok=True)
    log_file = os.path.join(outputs_dir, "run_log.txt")
    
    # Configure logging to write to both stdout and run_log.txt
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("ChemistQualityPipeline")

def main():
    start_time = time.time()
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    args = parse_args()
    outputs_dir = "outputs"
    logger = setup_logger(outputs_dir)
    
    logger.info("Initializing Chemist Location-Quality Pipeline...")
    
    # 1. Load Configurations
    config_overrides = {
        "input_file": args.input_file,
        "sheet_name": args.sheet_name,
        "geocoding_mode": args.geocoding_mode,
        "city_outlier_warning_km": args.city_outlier_warning_km,
        "city_outlier_critical_km": args.city_outlier_critical_km
    }
    config = Config(config_overrides)
    
    # Save the config used
    config.save_to_file(os.path.join(outputs_dir, "config_used.json"))
    logger.info(f"Loaded configurations. Saved config to outputs/config_used.json")
    
    # 2. Load Pincode Reference Data
    ref_dir = "reference_data"
    os.makedirs(ref_dir, exist_ok=True)
    pincode_ref_path = os.path.join(ref_dir, "pincode_master.csv")
    pincode_ref = load_pincode_reference(pincode_ref_path)
    
    # 3. Load input chemist data
    logger.info(f"Scanning for chemist input master: {config.input_file}")
    try:
        df = load_chemist_data(config.input_file, config.sheet_name, config)
        logger.info(f"Successfully loaded chemist master file. Total records: {len(df)}")
    except Exception as e:
        logger.error(f"Failed to load chemist input master file: {e}")
        sys.exit(1)
        
    # Initialize and clean text columns
    logger.info("Step 1: Standardizing address texts and expanding abbreviations...")
    cleaned_addrs = []
    tokens = []
    phones = []
    
    # Enable pandas progress bar
    tqdm.pandas(desc="Address Standardizing")
    addr_processed = df['original_address'].progress_apply(process_address)
    
    df['cleaned_address'] = [item['cleaned_address'] for item in addr_processed]
    df['address_tokens'] = [item['address_tokens'] for item in addr_processed]
    df['extracted_phone_numbers'] = [item['extracted_phone_numbers'] for item in addr_processed]
    
    tqdm.pandas(desc="Chemist Name Normalizing")
    df['chemist_name_original'] = df[config.name_col].fillna('').astype(str)
    # Generate uppercase name column
    df['chemist_name'] = df['chemist_name_original'].progress_apply(standardize_chemist_name)
    
    # 4. City and State Normalization
    logger.info("Step 2: Normalizing city and state names...")
    synonyms_path = os.path.join(ref_dir, "city_state_synonyms.json")
    city_state_normalizer = CityStateNormalizer(synonyms_path)
    
    tqdm.pandas(desc="City/State Normalizing")
    city_state_results = df.progress_apply(
        lambda r: city_state_normalizer.normalize(r['original_city'], r['original_state']), axis=1
    )
    
    df['normalized_city'] = [item[0] for item in city_state_results]
    df['normalized_state'] = [item[1] for item in city_state_results]
    df['city_state_normalization_flags'] = [item[2] for item in city_state_results]
    
    # 5. Address Quality checks
    logger.info("Step 3: Evaluating address quality checks and scores...")
    tqdm.pandas(desc="Address Auditing")
    address_quality_results = df.progress_apply(
        lambda r: analyze_address_quality(
            r['original_address'], r['cleaned_address'], r['normalized_city'], r['extracted_phone_numbers']
        ), axis=1
    )
    df['address_quality_score'] = [item[0] for item in address_quality_results]
    df['address_issue_flags'] = [item[1] for item in address_quality_results]
    
    # 6. Pincode Validation
    logger.info("Step 4: Validating pincodes and comparing with address-extracted codes...")
    tqdm.pandas(desc="Pincode Auditing")
    pincode_results = df.progress_apply(
        lambda r: validate_pincode_record(
            r['original_pincode'], r['cleaned_address'], r['normalized_city'], r['normalized_state'], pincode_ref
        ), axis=1
    )
    
    df['validated_pincode'] = [item['validated_pincode'] for item in pincode_results]
    df['suggested_pincode'] = [item['suggested_pincode'] for item in pincode_results]
    df['pincode_reference_state'] = [item['pincode_reference_state'] for item in pincode_results]
    df['pincode_reference_district'] = [item['pincode_reference_district'] for item in pincode_results]
    df['pincode_reference_post_offices'] = [item['pincode_reference_post_offices'] for item in pincode_results]
    df['pincode_status'] = [item['pincode_status'] for item in pincode_results]
    df['pincode_quality_score'] = [item['pincode_quality_score'] for item in pincode_results]
    df['pincode_issue_flags'] = [item['pincode_issue_flags'] for item in pincode_results]
    
    # Extra columns asked in Section 5
    df['extracted_pincode_from_column'] = df['validated_pincode']
    df['extracted_pincode_from_address'] = df['cleaned_address'].apply(
        lambda x: extract_pincodes_from_str(x)[0] if extract_pincodes_from_str(x) else ""
    )
    
    # 7. Coordinate Validation
    logger.info("Step 5: Validating coordinates and mapping city outliers / duplicate clusters...")
    df = validate_coordinates(df, config, pincode_ref)
    
    # 8. Geocoding / Reverse Geocoding Engine
    logger.info(f"Step 6: Executing Geocoding Strategy (Mode: {config.geocoding_mode})...")
    
    # Geocoding fields initialization
    df['geocoding_required_flag'] = df['coordinate_issue_flags'].str.contains('REGEOCODE_REQUIRED').fillna(False)
    df['geocoding_attempted_flag'] = False
    df['geocoding_provider'] = "NONE"
    df['geocoding_query_used'] = ""
    df['geocoding_result_lat'] = np.nan
    df['geocoding_result_long'] = np.nan
    df['geocoding_confidence_score'] = np.nan
    df['geocoding_result_type'] = "NONE"
    df['geocoding_error_message'] = ""
    
    df['reverse_geocode_attempted_flag'] = False
    df['reverse_city'] = ""
    df['reverse_state'] = ""
    df['reverse_pincode'] = ""
    df['reverse_geocode_match_score'] = np.nan
    df['reverse_geocode_issue_flags'] = ""
    
    geocoder = GeocodingEngine(config.geocoding_mode, os.path.join(ref_dir, "geocoding_cache.json"))
    reverse_geocoder = ReverseGeocodingEngine(config.geocoding_mode, os.path.join(ref_dir, "reverse_geocoding_cache.json"))
    
    # Determine rows to geocode
    to_geocode_mask = df['geocoding_required_flag'] == True
    geocode_count = to_geocode_mask.sum()
    logger.info(f"Records flagging for geocoding review: {geocode_count}")
    
    if config.geocoding_mode != "OFFLINE_ONLY" and geocode_count > 0:
        # Loop and geocode
        api_count = 0
        pbar = tqdm(total=geocode_count, desc="Geocoding Records")
        
        for idx, row in df[to_geocode_mask].iterrows():
            # Apply limit if Nominatim sample mode is on
            if config.geocoding_mode == "PUBLIC_NOMINATIM_SAMPLE_ONLY" and api_count >= 50:
                logger.info("Nominatim public API sample limit of 50 calls reached. Bypassing subsequent calls.")
                pbar.update(geocode_count - api_count)
                break
                
            res_lat, res_long, q_used, provider, conf_score, q_type, err_msg = geocoder.geocode_record(
                row['chemist_name_original'], row['cleaned_address'],
                row['normalized_city'], row['normalized_state'], row['validated_pincode']
            )
            
            df.at[idx, 'geocoding_attempted_flag'] = True
            df.at[idx, 'geocoding_provider'] = provider
            df.at[idx, 'geocoding_query_used'] = q_used
            df.at[idx, 'geocoding_result_lat'] = res_lat
            df.at[idx, 'geocoding_result_long'] = res_long
            df.at[idx, 'geocoding_confidence_score'] = conf_score
            df.at[idx, 'geocoding_result_type'] = q_type
            df.at[idx, 'geocoding_error_message'] = err_msg
            
            api_count += 1
            pbar.update(1)
            
            # Optional: Attempt reverse geocode verification on success
            if res_lat is not None and not pd.isna(res_lat):
                rev_city, rev_state, rev_pin, rev_ok, rev_err = reverse_geocoder.reverse_geocode(res_lat, res_long)
                if rev_ok:
                    m_score, m_flags = reverse_geocoder.validate_match(
                        row['normalized_city'], row['normalized_state'], row['validated_pincode'],
                        rev_city, rev_state, rev_pin
                    )
                    df.at[idx, 'reverse_geocode_attempted_flag'] = True
                    df.at[idx, 'reverse_city'] = rev_city
                    df.at[idx, 'reverse_state'] = rev_state
                    df.at[idx, 'reverse_pincode'] = rev_pin
                    df.at[idx, 'reverse_geocode_match_score'] = m_score
                    df.at[idx, 'reverse_geocode_issue_flags'] = m_flags
        pbar.close()
        
    logger.info(f"Geocoding complete. Cache hits: {geocoder.cache_hit_count}, API calls: {geocoder.api_call_count}")
    
    # 9. Compute Overall Location Confidence Score and Quality Buckets
    logger.info("Step 7: Compiling final confidence scores and quality buckets...")
    df = calculate_confidence_scores(df)
    
    # 10. Execute safe corrections and recommended action logic
    logger.info("Step 8: Applying correction engine and recommended action rules...")
    df = apply_safe_corrections(df)
    
    # 11. Write Output Files
    logger.info("Step 9: Writing output Excel spreadsheets and CSV sheets...")
    write_dataframes_to_outputs(df, outputs_dir)
    write_quality_dashboard(df, outputs_dir, run_timestamp, config.input_file)
    
    # 12. Generate text summary report
    elapsed_time = time.time() - start_time
    logger.info("Generating text summary report outputs/chemist_data_quality_summary.txt...")
    write_text_summary(df, config, elapsed_time, run_timestamp, outputs_dir, geocoder)
    
    logger.info(f"Chemist location pipeline completed successfully in {elapsed_time:.2f} seconds!")

def write_text_summary(df, config, elapsed_time, run_timestamp, outputs_dir, geocoder):
    """
    Assembles a thorough text report detailing all metrics, counts, issues, and assumptions.
    """
    total_records = len(df)
    high_count = (df['quality_bucket'] == "HIGH").sum()
    med_count = (df['quality_bucket'] == "MEDIUM").sum()
    low_count = (df['quality_bucket'] == "LOW").sum()
    crit_count = (df['quality_bucket'] == "CRITICAL").sum()
    
    summary_path = os.path.join(outputs_dir, "chemist_data_quality_summary.txt")
    
    # Calculate flag counts
    addr_short = df['address_issue_flags'].str.contains('ADDRESS_TOO_SHORT', na=False).sum()
    addr_generic = df['address_issue_flags'].str.contains('ADDRESS_GENERIC', na=False).sum()
    addr_phone = df['address_issue_flags'].str.contains('ADDRESS_HAS_PHONE_NUMBER', na=False).sum()
    addr_repeated = df['address_issue_flags'].str.contains('ADDRESS_CITY_REPEATED', na=False).sum()
    
    pin_valid = (df['pincode_status'] == "VALID_HIGH_CONFIDENCE").sum()
    pin_not_found = df['pincode_issue_flags'].str.contains('PINCODE_NOT_FOUND_IN_REFERENCE', na=False).sum()
    pin_state_mismatch = df['pincode_issue_flags'].str.contains('PINCODE_STATE_MISMATCH', na=False).sum()
    pin_addr_mismatch = df['pincode_issue_flags'].str.contains('ADDRESS_DIFFERS_FROM_COLUMN', na=False).sum()
    
    coord_missing = df['COORD_MISSING'].sum()
    coord_invalid = df['COORD_INVALID_FORMAT'].sum()
    coord_outside_in = df['COORD_OUTSIDE_INDIA'].sum()
    coord_inverted = df['COORD_LAT_LONG_INVERTED'].sum()
    coord_city_warn = df['COORD_CITY_MISMATCH_WARNING'].sum()
    coord_city_crit = df['COORD_CITY_MISMATCH_CRITICAL'].sum()
    coord_duplicate = (df['duplicate_coordinate_count'] >= 5).sum()
    coord_centroid = df['COORD_CENTROID_SUSPECTED'].sum()
    
    eligible_count = df['eligible_for_routing_flag'].sum()
    ineligible_count = (df['eligible_for_routing_flag'] == False).sum()
    
    # Coordinate source counts breakdown
    src_accepted_hc = (df['coordinate_source'] == "ORIGINAL_ACCEPTED_HIGH_CONFIDENCE").sum()
    src_accepted_flags = (df['coordinate_source'] == "ORIGINAL_ACCEPTED_WITH_FLAGS").sum()
    src_swap = (df['coordinate_source'] == "ORIGINAL_CORRECTED_LATLONG_SWAP").sum()
    src_rg_full = (df['coordinate_source'] == "REGEOCODED_FULL_ADDRESS").sum()
    src_rg_clean = (df['coordinate_source'] == "REGEOCODED_CLEAN_ADDRESS").sum()
    src_rg_loc = (df['coordinate_source'] == "REGEOCODED_LOCALITY_CITY_PINCODE").sum()
    src_pin_centroid = (df['coordinate_source'] == "PINCODE_CENTROID_FALLBACK").sum()
    src_none = (df['coordinate_source'] == "NO_USABLE_COORDINATE").sum()
    
    # Routing reliability counts breakdown
    rel_high = (df['routing_reliability_bucket'] == "HIGH_RELIABILITY").sum()
    rel_mod = (df['routing_reliability_bucket'] == "MODERATE_RELIABILITY").sum()
    rel_low = (df['routing_reliability_bucket'] == "LOW_RELIABILITY").sum()
    rel_risk = (df['routing_reliability_bucket'] == "HIGH_RISK").sum()
    
    # Routing risk counts breakdown
    risk_use = (df['routing_risk_flag'] == "USE").sum()
    risk_caution = (df['routing_risk_flag'] == "USE_WITH_CAUTION").sum()
    risk_review = (df['routing_risk_flag'] == "REVIEW_BEFORE_USE").sum()
    
    # Top problematic cities
    city_scores = df.groupby('normalized_city')['overall_location_confidence_score'].mean()
    city_counts = df['normalized_city'].value_counts()
    major_cities = city_counts[city_counts >= 100].index
    problematic_cities_list = []
    if len(major_cities) > 0:
        worst_cities = city_scores[major_cities].sort_values().head(5)
        for city, score in worst_cities.items():
            problematic_cities_list.append(f"  - {city}: Avg Score {score:.2f} ({city_counts[city]} chemists)")
    else:
        worst_cities = city_scores.sort_values().head(5)
        for city, score in worst_cities.items():
            problematic_cities_list.append(f"  - {city}: Avg Score {score:.2f} ({city_counts[city]} chemists)")
            
    problematic_cities = "\n".join(problematic_cities_list)
    
    geocoding_note = ""
    if config.geocoding_mode == "OFFLINE_ONLY":
        geocoding_note = "NO REAL GEOCODING PROVIDER WAS USED. The pipeline audited, corrected swapped lat-longs, and flagged problematic coordinates, but did not fetch fresh geocoded coordinates from external web APIs."
    else:
        geocoding_note = f"REAL GEOCODING PROVIDER USED: {config.geocoding_mode}. Fresh coordinates were retrieved and cached for records matching geocoding criteria."

    report = f"""================================================================================
CHEMIST LOCATION DATA QUALITY AUDIT SUMMARY
================================================================================
Run Timestamp:       {run_timestamp}
Input File Name:     {config.input_file}
Total Records Loaded: {total_records}
Total Records Processed: {total_records}
Pipeline Runtime:    {elapsed_time:.2f} seconds

RECORDS BY QUALITY BUCKET:
--------------------------------------------------------------------------------
- HIGH (Score >= 85):        {high_count} ({(high_count/total_records*100):.2f}%)
- MEDIUM (Score 65 - 84):    {med_count} ({(med_count/total_records*100):.2f}%)
- LOW (Score 40 - 64):       {low_count} ({(low_count/total_records*100):.2f}%)
- CRITICAL (Score < 40):     {crit_count} ({(crit_count/total_records*100):.2f}%)

COORDINATE SOURCE BREAKDOWN:
--------------------------------------------------------------------------------
- ORIGINAL_ACCEPTED_HIGH_CONFIDENCE: {src_accepted_hc} ({(src_accepted_hc/total_records*100):.2f}%)
- ORIGINAL_ACCEPTED_WITH_FLAGS:      {src_accepted_flags} ({(src_accepted_flags/total_records*100):.2f}%)
- ORIGINAL_CORRECTED_LATLONG_SWAP:   {src_swap} ({(src_swap/total_records*100):.6f}%)
- REGEOCODED_FULL_ADDRESS:           {src_rg_full} ({(src_rg_full/total_records*100):.2f}%)
- REGEOCODED_CLEAN_ADDRESS:          {src_rg_clean} ({(src_rg_clean/total_records*100):.2f}%)
- REGEOCODED_LOCALITY_CITY_PINCODE:  {src_rg_loc} ({(src_rg_loc/total_records*100):.2f}%)
- PINCODE_CENTROID_FALLBACK:         {src_pin_centroid} ({(src_pin_centroid/total_records*100):.2f}%)
- NO_USABLE_COORDINATE:              {src_none} ({(src_none/total_records*100):.2f}%)

BUSINESS ROUTING RELIABILITY BUCKET:
--------------------------------------------------------------------------------
- HIGH_RELIABILITY:        {rel_high} ({(rel_high/total_records*100):.2f}%)
- MODERATE_RELIABILITY:    {rel_mod} ({(rel_mod/total_records*100):.2f}%)
- LOW_RELIABILITY:         {rel_low} ({(rel_low/total_records*100):.2f}%)
- HIGH_RISK:               {rel_risk} ({(rel_risk/total_records*100):.2f}%)

BUSINESS ROUTING RISK FLAG (RECOMMENDED ACTION):
--------------------------------------------------------------------------------
- USE (Trustworthy coordinates):                 {risk_use} ({(risk_use/total_records*100):.2f}%)
- USE_WITH_CAUTION (Minor flags present):        {risk_caution} ({(risk_caution/total_records*100):.2f}%)
- REVIEW_BEFORE_USE (Low confidence/severe flag): {risk_review} ({(risk_review/total_records*100):.2f}%)

ADDRESS QUALITY SUMMARY:
--------------------------------------------------------------------------------
- Address Too Short (<20 chars): {addr_short}
- Address Generic Phrase:       {addr_generic}
- Address Contains Phone:       {addr_phone}
- Address City Repeated (3x+):  {addr_repeated}

PINCODE SUMMARY:
--------------------------------------------------------------------------------
- Valid High Confidence Pin:    {pin_valid}
- Pincode Not Found in Ref:     {pin_not_found}
- State Mismatch (Pin vs Chem): {pin_state_mismatch}
- Address contains diff Pin:    {pin_addr_mismatch}

COORDINATE SUMMARY:
--------------------------------------------------------------------------------
- Missing Coordinates:          {coord_missing}
- Invalid Format Coordinates:   {coord_invalid}
- Outside India Bounding Box:   {coord_outside_in}
- Lat-Long Inversions Swapped:   {coord_inverted}
- City Outlier Distance Warning (>50km): {coord_city_warn}
- City Outlier Distance Critical (>100km): {coord_city_crit}
- Duplicate Coordinate Clusters (>=5):   {coord_duplicate}
- Centroid Fallbacks Suspected:          {coord_centroid}

ROUTING ELIGIBILITY SUMMARY (TECHNICAL ROUTING USABILITY):
--------------------------------------------------------------------------------
- Eligible for Routing (TRUE):  {eligible_count} ({(eligible_count/total_records*100):.2f}%)
- Ineligible for Routing (FALSE): {ineligible_count} ({(ineligible_count/total_records*100):.2f}%)

GEOCODING SUMMARY:
--------------------------------------------------------------------------------
- Geocoding Mode Used:          {config.geocoding_mode}
- Records Requiring Geocoding:  {df['geocoding_required_flag'].sum()}
- Records Geocoded:             {df['geocoding_attempted_flag'].sum()}
- Geocoding Successes:          {df['geocoding_result_lat'].notna().sum() - (df['coordinate_source'] == "PINCODE_CENTROID_FALLBACK").sum()}
- Pincode Centroid Fallbacks:    {(df['coordinate_source'] == "PINCODE_CENTROID_FALLBACK").sum()}
- Cache Hits:                   {geocoder.cache_hit_count}

GEOCODING PROVIDER INTEGRATION NOTE:
--------------------------------------------------------------------------------
{geocoding_note}

TOP PROBLEMATIC CITIES (WITH >= 100 RECORDS):
--------------------------------------------------------------------------------
{problematic_cities}

TOP ISSUE FLAGS OCCURRING:
--------------------------------------------------------------------------------
- COORD_MISSING: {(df['COORD_MISSING'] == True).sum()}
- COORD_CITY_MISMATCH_CRITICAL: {coord_city_crit}
- ADDRESS_TOO_SHORT: {addr_short}
- PINCODE_NOT_FOUND_IN_REFERENCE: {pin_not_found}
- COORD_CENTROID_SUSPECTED: {coord_centroid}

WARNINGS & PIPELINE ASSUMPTIONS:
--------------------------------------------------------------------------------
1. Pincodes are validated against the DROPDEVRAHUL open pincode database.
2. Coordinates outside India box [Lat {config.india_bbox['lat_min']}-{config.india_bbox['lat_max']}, Long {config.india_bbox['long_min']}-{config.india_bbox['long_max']}] are treated as outliers.
3. City centroids are computed using the median latitude and longitude of chemists in that city. Cities with fewer than 5 valid chemists are not analyzed for city outlier flags.
4. Low confidence chemists (bucket LOW/CRITICAL) are retained and marked eligible for routing if coordinates are present, to prevent loss of customer records, but flags remain visible.
================================================================================
"""
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(report)

if __name__ == "__main__":
    main()
