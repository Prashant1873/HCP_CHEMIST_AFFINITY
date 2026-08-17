import pandas as pd
import numpy as np
from src.utils import haversine_distance_vectorized

def calculate_haversine_single(lat1, lon1, lat2, lon2):
    """
    Computes haversine distance between two points in km.
    """
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return np.nan
    # Convert degrees to radians
    la1, lo1, la2, lo2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dla = la2 - la1
    dlo = lo2 - lo1
    a = np.sin(dla/2.0)**2 + np.cos(la1) * np.cos(la2) * np.sin(dlo/2.0)**2
    c = 2.0 * np.arcsin(np.sqrt(a))
    km = 6367.0 * c
    return km

def evaluate_geocoding_acceptance(row, cand_lat, cand_long, cand_precision, config, pincode_ref, city_medians):
    """
    Validates a candidate coordinate and assigns an acceptance decision:
    ACCEPT_REPLACE_FINAL_COORDS, ACCEPT_WITH_CAUTION, PINCODE_CENTROID_ONLY,
    KEEP_ORIGINAL_WITH_FLAGS, REJECT_LOW_CONFIDENCE, MANUAL_REVIEW_REQUIRED, GEOCODING_FAILED
    """
    if pd.isna(cand_lat) or pd.isna(cand_long) or cand_lat is None or cand_long is None:
        return "GEOCODING_FAILED", "No coordinate returned by the geocoder"
        
    # 1. Bounding Box check
    in_india = (
        config.india_bbox['lat_min'] <= cand_lat <= config.india_bbox['lat_max'] and
        config.india_bbox['long_min'] <= cand_long <= config.india_bbox['long_max']
    )
    if not in_india:
        return "REJECT_LOW_CONFIDENCE", "Candidate coordinate outside India bounds"
        
    # 2. City Median distance check
    city = row['normalized_city']
    dist_to_city_med = np.nan
    if city in city_medians:
        med_lat, med_long = city_medians[city]
        dist_to_city_med = calculate_haversine_single(cand_lat, cand_long, med_lat, med_long)
        
    # Check if city centroid mismatch is critical
    if not pd.isna(dist_to_city_med) and dist_to_city_med > config.city_outlier_critical_km:
        return "REJECT_LOW_CONFIDENCE", f"Coordinate is too far from city median ({dist_to_city_med:.2f} km > {config.city_outlier_critical_km} km)"
        
    # 3. Centroid Fallback checks
    # Check pincode centroid
    is_pin_centroid = False
    pin = row['validated_pincode']
    if pin and pincode_ref and pin in pincode_ref:
        pin_meta = pincode_ref[pin]
        p_lat = pin_meta.get('lat')
        p_long = pin_meta.get('long')
        if p_lat and p_long:
            dist_to_pin_med = calculate_haversine_single(cand_lat, cand_long, p_lat, p_long)
            if not pd.isna(dist_to_pin_med) and dist_to_pin_med < 0.01:
                is_pin_centroid = True
                
    # Check city centroid
    is_city_centroid = False
    if not pd.isna(dist_to_city_med) and dist_to_city_med < 0.01:
        is_city_centroid = True
        
    # Check precision limits
    if cand_precision in ["CITY_LEVEL", "STATE_LEVEL"] or is_city_centroid:
        return "REJECT_LOW_CONFIDENCE", "Geocoded coordinates resolved only to city/state centroid"
        
    if cand_precision == "PINCODE_LEVEL" or is_pin_centroid:
        # Pincode level is accepted ONLY with caution if original was missing/critical mismatch
        orig_missing = row['COORD_MISSING'] or row['coordinate_source'] == "NO_USABLE_COORDINATE"
        orig_crit = "COORD_CITY_MISMATCH_CRITICAL" in str(row['coordinate_issue_flags'])
        
        if orig_missing or orig_crit:
            return "PINCODE_CENTROID_ONLY", "Only pincode-level centroid match found. Accepted as low-reliability approximate fallback."
        else:
            return "KEEP_ORIGINAL_WITH_FLAGS", "Geocoded result is pincode-level centroid, keeping existing coordinates with warnings"
            
    # 4. Compare with original coordinate (if existed)
    orig_lat = row['numeric_original_lat']
    orig_long = row['numeric_original_long']
    has_orig = not pd.isna(orig_lat) and not pd.isna(orig_long)
    
    if has_orig:
        dist_orig_to_new = calculate_haversine_single(orig_lat, orig_long, cand_lat, cand_long)
        
        # If original has high score (>85) and new coordinate is far (>2 km)
        if row['coordinate_quality_score'] >= 85 and dist_orig_to_new > 2.0:
            return "KEEP_ORIGINAL_WITH_FLAGS", f"Original coordinate is high quality; keeping original over geocoded which is {dist_orig_to_new:.2f} km away"
            
        # If new coordinate is street/building/shop level and original has critical city mismatch
        if cand_precision in ["SHOP_LEVEL", "BUILDING_LEVEL", "STREET_LEVEL", "LOCALITY_LEVEL"]:
            orig_city_crit = "COORD_CITY_MISMATCH_CRITICAL" in str(row['coordinate_issue_flags'])
            if orig_city_crit:
                return "ACCEPT_REPLACE_FINAL_COORDS", f"Replacing critical city mismatch original with geocoded {cand_precision} match"
            
            # General improvement check: if new coordinate is closer to expected pincode/city median
            orig_dist_to_city = row.get('dist_to_city_median', np.nan)
            if not pd.isna(dist_to_city_med) and not pd.isna(orig_dist_to_city):
                if dist_to_city_med < orig_dist_to_city - 5.0:
                    return "ACCEPT_REPLACE_FINAL_COORDS", f"Geocoded coordinate closer to city center (New: {dist_to_city_med:.2f} km, Old: {orig_dist_to_city:.2f} km)"
                    
        return "KEEP_ORIGINAL_WITH_FLAGS", "Geocoded result is not clearly superior to existing coordinate"
        
    else:
        # Original coordinates were missing - accept candidate!
        if cand_precision in ["SHOP_LEVEL", "BUILDING_LEVEL", "STREET_LEVEL"]:
            return "ACCEPT_REPLACE_FINAL_COORDS", f"Accepted geocoded {cand_precision} coordinate for previously missing location"
        elif cand_precision == "LOCALITY_LEVEL":
            return "ACCEPT_WITH_CAUTION", "Accepted geocoded LOCALITY_LEVEL coordinate with caution"
            
    return "MANUAL_REVIEW_REQUIRED", "Signal combinations are ambiguous, requiring manual review"
