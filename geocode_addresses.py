# Module and standalone script for batch address geocoding using Nominatim, Google Maps, or LocationIQ
import os
import sys
import re
import time
import argparse
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src import config
from src.pincode_geocoder import load_pincode_lookup

logger = setup_logger("geocoder")


def create_resilient_session(pool_connections: int = 20, pool_maxsize: int = 20) -> requests.Session:
    """Creates a requests.Session with connection pooling and automated retries."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=pool_connections, pool_maxsize=pool_maxsize)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class BaseGeocoder:
    """Base class for geocoding providers with in-memory caching."""
    def __init__(self):
        self.cache: Dict[str, Optional[Tuple[float, float, str]]] = {}
        self.session = create_resilient_session()

    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        if not query:
            return None
        if query in self.cache:
            return self.cache[query]
        res = self._do_geocode(query)
        self.cache[query] = res
        return res

    def _do_geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        raise NotImplementedError


class NominatimGeocoder(BaseGeocoder):
    """
    OpenStreetMap Nominatim Geocoder (Free, rate limited to 1 request/sec).
    """
    def __init__(self, user_agent: str = "ChemistDoctorMatcher/2.0 (contact: support@hcp-affinity.internal)"):
        super().__init__()
        self.endpoint = "https://nominatim.openstreetmap.org/search"
        self.headers = {"User-Agent": user_agent}
        self.last_query_time = 0.0
        self.min_delay = 1.0  # 1 second delay between calls per OSM usage policy

    def _do_geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        # Enforce rate limit
        elapsed = time.time() - self.last_query_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

        params = {
            "q": query,
            "format": "json",
            "countrycodes": "in",
            "limit": 1,
            "addressdetails": 1
        }

        try:
            resp = self.session.get(self.endpoint, params=params, headers=self.headers, timeout=10)
            self.last_query_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", "")
                    return lat, lon, display_name
        except Exception as e:
            logger.debug(f"Nominatim query failed for '{query}': {e}")

        return None


class GoogleMapsGeocoder(BaseGeocoder):
    """
    Google Maps Geocoding API (Fast, industry-leading accuracy for Indian addresses).
    """
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.endpoint = "https://maps.googleapis.com/maps/api/geocode/json"

    def _do_geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        params = {
            "address": query,
            "components": "country:IN",
            "key": self.api_key
        }

        try:
            resp = self.session.get(self.endpoint, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK" and data.get("results"):
                    result = data["results"][0]
                    lat = float(result["geometry"]["location"]["lat"])
                    lon = float(result["geometry"]["location"]["lng"])
                    formatted_address = result.get("formatted_address", "")
                    return lat, lon, formatted_address
        except Exception as e:
            logger.debug(f"Google query failed for '{query}': {e}")

        return None


class LocationIQGeocoder(BaseGeocoder):
    """
    LocationIQ Geocoding API (Fast OSM-based API with free tier).
    """
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.endpoint = "https://us1.locationiq.com/v1/search"

    def _do_geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        params = {
            "key": self.api_key,
            "q": query,
            "countrycodes": "in",
            "format": "json",
            "limit": 1
        }

        try:
            resp = self.session.get(self.endpoint, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", "")
                    return lat, lon, display_name
        except Exception as e:
            logger.debug(f"LocationIQ query failed for '{query}': {e}")

        return None


def clean_address_string(raw_addr: Any) -> str:
    """
    Deep cleaning of Indian address strings to remove phone numbers, unit noise, 
    and landmark prefixes that break geocoding search engines.
    """
    if pd.isna(raw_addr):
        return ""
    addr = str(raw_addr).strip()
    
    # 1. Strip 10-digit phone numbers and sequences
    addr = re.sub(r'\b\d{10}\b', '', addr)
    addr = re.sub(r'\b\d{5}\s*\d{5}\b', '', addr)
    
    # 2. Normalize punctuation and characters
    addr = addr.replace('"', '').replace("'", "").replace("\n", ", ")
    addr = re.sub(r'[\(\)\[\]]', ' ', addr)
    
    # 3. Clean common noise words and unit descriptors
    noise_patterns = [
        r'\bshop\s*no[\.\s\-]*\w+',
        r'\bshop[\.\s\-]*\w+',
        r'\bgala\s*no[\.\s\-]*\w+',
        r'\bplot\s*no[\.\s\-]*\w+',
        r'\bflat\s*no[\.\s\-]*\w+',
        r'\bbldg\s*no[\.\s\-]*\w+',
        r'\bbuilding\s*no[\.\s\-]*\w+',
        r'\bsector\s*no[\.\s\-]*\w+',
        r'\bground\s*floor\b',
        r'\bgr[\.\s]*floor\b',
        r'\b1st\s*floor\b',
        r'\b2nd\s*floor\b',
        r'\be\s*wing\b',
        r'\ba\s*wing\b',
        r'\bb\s*wing\b',
        r'\bc\s*wing\b',
        r'\bd\s*wing\b',
        r'\brwg\s*\d+\b',
        r'\bco-?op\s*hsg\s*soc\b',
        r'\bchawl\b'
    ]
    for pattern in noise_patterns:
        addr = re.sub(pattern, '', addr, flags=re.IGNORECASE)
        
    # 4. Clean landmark prefixes
    landmark_prefixes = [
        r'\bnear\b', r'\bnr[\.\s]', r'\bopposite\b', r'\bopp[\.\s]', 
        r'\bbehind\b', r'\bb/h\b', r'\badjacent\b', r'\badj[\.\s]'
    ]
    for lp in landmark_prefixes:
        addr = re.sub(lp, '', addr, flags=re.IGNORECASE)
        
    # 5. Clean extra whitespace and commas
    addr = re.sub(r'\s+', ' ', addr)
    addr = re.sub(r',\s*,+', ',', addr)
    return addr.strip(" ,-")


def build_query_hierarchy(row: pd.Series) -> List[str]:
    """
    Constructs a tiered list of address queries from specific road/area to general locality.
    """
    queries = []
    
    name = str(row.get("chem_name", row.get("chemist_name", ""))).strip()
    raw_addr = str(row.get("chem_address", row.get("chemist_address", "")))
    cleaned_addr = clean_address_string(raw_addr)
    city = str(row.get("chem_city", row.get("chemist_city", ""))).strip()
    state = str(row.get("chem_state", row.get("chemist_state", ""))).strip()
    pin = str(row.get("chem_pincode", row.get("chemist_pincode", ""))).strip()
    
    if pin and "." in pin:
        pin = pin.split(".")[0]
    pin = "".join(c for c in pin if c.isdigit())
    if len(pin) == 6 and pin.startswith("0") and len(pin) > 6:
        pin = pin[:6]
    
    # 1. Cleaned address + City + Pincode
    if cleaned_addr:
        components_clean = [c for c in [cleaned_addr, city, state, pin, "India"] if c and c != "nan" and c != "Unknown"]
        queries.append(", ".join(components_clean))
        
    # 2. Store Name + Cleaned Address / Suburb + City
    if name and name not in ["nan", "Unknown", "-"]:
        parts = [p.strip() for p in cleaned_addr.split(",") if len(p.strip()) > 3]
        short_addr = ", ".join(parts[:2]) if parts else ""
        components_name = [c for c in [name, short_addr, city, pin, "India"] if c and c != "nan" and c != "Unknown"]
        queries.append(", ".join(components_name))
        
    # 3. Locality / Suburb extracted from address + City + Pincode
    if cleaned_addr:
        parts = [p.strip() for p in cleaned_addr.split(",") if len(p.strip()) > 3]
        if len(parts) >= 2:
            suburb_query = ", ".join([parts[-1], city, pin, "India"])
            queries.append(suburb_query)

    # 4. Fallback: City + Pincode
    if pin and len(pin) == 6:
        components_pin = [c for c in [city, pin, "India"] if c and c != "nan"]
        queries.append(", ".join(components_pin))

    # Deduplicate queries while preserving priority order
    unique_queries = []
    for q in queries:
        q_str = " ".join(q.split()).strip(" ,")
        if q_str and q_str not in unique_queries:
            unique_queries.append(q_str)
            
    return unique_queries


from src.pincode_validator import PincodeSpatialValidator

def geocode_single_record(
    row: pd.Series,
    geocoder: BaseGeocoder,
    pincode_lookup: Dict[str, Tuple[float, float]],
    validator: Optional[PincodeSpatialValidator] = None
) -> Dict[str, Any]:
    """
    Geocodes an individual chemist record using the query hierarchy with 
    strict GeoJSON spatial validation and automated offline pincode centroid fallback.
    """
    raw_pin = str(row.get("chem_pincode", row.get("chemist_pincode", ""))).strip()
    if raw_pin and "." in raw_pin:
        raw_pin = raw_pin.split(".")[0]
    pin_digits = "".join(c for c in raw_pin if c.isdigit())
    if len(pin_digits) > 6:
        pin_digits = pin_digits[:6]

    queries = build_query_hierarchy(row)
    
    # Try online geocoding queries with strict spatial bounding verification
    for q in queries:
        res = geocoder.geocode(q)
        if res:
            lat, lon, disp = res
            if (config.INDIA_LAT_MIN <= lat <= config.INDIA_LAT_MAX) and \
               (config.INDIA_LON_MIN <= lon <= config.INDIA_LON_MAX):
                
                # Spatial Boundary Gate: Check if coordinate falls inside stated pincode
                if validator and validator.is_ready and pin_digits and (pin_digits in validator.pin_to_geom):
                    val_res = validator.validate_coordinate(
                        lat=lat,
                        lon=lon,
                        stated_pincode=pin_digits,
                        tolerance_km=config.DEFAULT_PINCODE_TOLERANCE_KM
                    )
                    if not val_res["is_valid"]:
                        # Geocoder returned an out-of-pincode false match (e.g. Nagpur instead of Mumbai); reject it!
                        logger.debug(f"Discarding out-of-pincode geocoder result for '{q}' -> ({lat}, {lon}) vs stated pin {pin_digits}")
                        continue
                
                return {
                    "geocoded_latitude": str(lat),
                    "geocoded_longitude": str(lon),
                    "geocoded_address": str(disp),
                    "geocoded_status": "success",
                    "coordinate_source": "online_geocoder"
                }
                
    # Offline Fallback: Pincode Centroid Lookup
    if len(pin_digits) == 6 and pin_digits in pincode_lookup:
        c_lat, c_lon = pincode_lookup[pin_digits]
        return {
            "geocoded_latitude": str(c_lat),
            "geocoded_longitude": str(c_lon),
            "geocoded_address": f"Pincode Centroid ({pin_digits})",
            "geocoded_status": "success",
            "coordinate_source": "pincode_centroid_fallback"
        }
        
    return {
        "geocoded_latitude": "",
        "geocoded_longitude": "",
        "geocoded_address": "",
        "geocoded_status": "not_found",
        "coordinate_source": "none"
    }



def load_existing_geocoded_map(filepaths: List[str]) -> Dict[str, Dict[str, str]]:
    """
    Loads all previous geocoding results from output/checkpoint CSV files.
    Returns a unified lookup map indexed by ID keys and clean address strings.
    """
    lookup = {}
    for path in filepaths:
        if not os.path.exists(path):
            continue
        try:
            prev_df = pd.read_csv(path, dtype=str)
            if "geocoded_status" not in prev_df.columns:
                continue
            success_rows = prev_df[prev_df["geocoded_status"] == "success"]
            for _, r in success_rows.iterrows():
                entry = {
                    "geocoded_latitude": str(r.get("geocoded_latitude", "")).strip(),
                    "geocoded_longitude": str(r.get("geocoded_longitude", "")).strip(),
                    "geocoded_address": str(r.get("geocoded_address", "")).strip(),
                    "geocoded_status": "success",
                    "coordinate_source": str(r.get("coordinate_source", "previous_run")).strip()
                }
                # Check valid coords
                if not entry["geocoded_latitude"] or not entry["geocoded_longitude"]:
                    continue
                
                # Map by available IDs
                for id_col in ["IQVIA ID", "chemist_id", "original_id", "chemist_record_index"]:
                    if id_col in r and pd.notna(r[id_col]):
                        id_val = str(r[id_col]).strip()
                        if id_val and id_val != "nan":
                            lookup[f"id:{id_val}"] = entry
                            
                # Map by cleaned address key
                raw_addr = r.get("chem_address", r.get("chemist_address", ""))
                clean_addr = clean_address_string(raw_addr)
                pin = str(r.get("chem_pincode", r.get("chemist_pincode", ""))).strip()
                if clean_addr and len(clean_addr) > 5:
                    lookup[f"addr:{clean_addr}_{pin}"] = entry
        except Exception as e:
            logger.warning(f"Could not load previous geocoded records from '{path}': {e}")
            
    return lookup


def main():
    parser = argparse.ArgumentParser(
        description="Optimized Batch Geocoding tool with intelligent pre-run cache checking."
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=os.path.join("outputs", "invalid_chemist_records.csv"),
        help="Input CSV file containing records to geocode (default: outputs/invalid_chemist_records.csv)"
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["nominatim", "google", "locationiq"],
        default="nominatim",
        help="Geocoding service provider to use (default: nominatim)"
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="API Key for Google Maps or LocationIQ"
    )
    parser.add_argument(
        "--city",
        type=str,
        default=None,
        help="Filter records to geocode by city name (e.g. '--city Mumbai'). Supports comma-separated city names."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of records to geocode in this run (useful for testing)"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Number of concurrent threads for Google/LocationIQ (default: 4)"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=os.path.join("outputs", "geocoded_chemist_records.csv"),
        help="Destination path for geocoded records (default: outputs/geocoded_chemist_records.csv)"
    )
    parser.add_argument(
        "--checkpoint_interval",
        type=int,
        default=50,
        help="Number of queries between checkpoint saves (default: 50)"
    )
    parser.add_argument(
        "--merge_into",
        type=str,
        default=None,
        help="Optional: path to raw chemist spreadsheet (CSV/Excel) to merge newly resolved coordinates back into directly."
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        logger.error(f"Input file '{args.input_file}' does not exist.")
        sys.exit(1)
        
    logger.info(f"Loading input file: {args.input_file}...")
    df = pd.read_csv(args.input_file, dtype=str)
    logger.info(f"Loaded {len(df)} total input records.")
    
    # Load offline pincode centroid lookup for zero-failure fallback
    pincode_lookup = load_pincode_lookup()
    logger.info(f"Loaded {len(pincode_lookup)} pincode centroids for instant offline fallback.")
    
    # Load GeoJSON spatial validator for bounding gate
    validator = PincodeSpatialValidator()
    if validator.is_ready:
        logger.info("Pincode GeoJSON boundary validator loaded for geocoding accuracy.")
    else:
        logger.warning("Pincode GeoJSON validator not active. Geocoding will run without polygon boundary gating.")
    
    # Filter by city name if provided
    if args.city:
        city_filters = [c.strip() for c in str(args.city).split(",") if c.strip()]
        logger.info(f"Applying city filter: {city_filters}")
        mask = pd.Series(False, index=df.index)
        for filt in city_filters:
            filt_clean = "".join(c for c in filt.lower() if c.isalnum())
            if not filt_clean:
                continue
            filt_mask = pd.Series(False, index=df.index)
            for col in df.columns:
                if "city" in col.lower():
                    filt_mask |= df[col].astype(str).apply(
                        lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                    )
            if not filt_mask.any():
                for col in df.columns:
                    if any(k in col.lower() for k in ["addr", "location"]):
                        filt_mask |= df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
            if filt.isdigit():
                for pin_col in ["chemist_pincode", "chem_pincode", "pincode", "doctor_pincode"]:
                    if pin_col in df.columns:
                        filt_mask |= df[pin_col].astype(str).str.startswith(filt)
            mask |= filt_mask
            
        df = df[mask].reset_index(drop=True)
        logger.info(f"Retained {len(df)} records matching city filter '{args.city}'.")
        
    if args.limit and args.limit > 0:
        df = df.head(args.limit).copy()
        logger.info(f"Limiting execution to first {len(df)} records.")
        
    if len(df) == 0:
        logger.warning("No records to geocode. Exiting.")
        sys.exit(0)
        
    # Prepare output fields
    for col in ["geocoded_latitude", "geocoded_longitude", "geocoded_address", "geocoded_status", "coordinate_source"]:
        if col not in df.columns:
            df[col] = ""
    df["geocoded_status"] = "pending"
    
    output_dir = os.path.dirname(args.output_file) or "outputs"
    os.makedirs(output_dir, exist_ok=True)
    checkpoint_file = os.path.join(output_dir, "geocoding_checkpoint.csv")
    
    # -------------------------------------------------------------
    # PRE-RUN CHECK: Inspect previous outputs and checkpoints to skip
    # records that have already been geocoded
    # -------------------------------------------------------------
    logger.info("Checking for previously geocoded records to prevent duplicate queries...")
    prior_map = load_existing_geocoded_map([args.output_file, checkpoint_file])
    
    pre_resolved_count = 0
    for idx, row in df.iterrows():
        entry = None
        # Check by ID candidates
        for id_col in ["IQVIA ID", "chemist_id", "original_id", "chemist_record_index"]:
            if id_col in row and pd.notna(row[id_col]):
                id_val = str(row[id_col]).strip()
                if f"id:{id_val}" in prior_map:
                    entry = prior_map[f"id:{id_val}"]
                    break
        # Check by address
        if not entry:
            clean_addr = clean_address_string(row.get("chem_address", row.get("chemist_address", "")))
            pin = str(row.get("chem_pincode", row.get("chemist_pincode", ""))).strip()
            if f"addr:{clean_addr}_{pin}" in prior_map:
                entry = prior_map[f"addr:{clean_addr}_{pin}"]
                
        if entry:
            df.at[idx, "geocoded_latitude"] = entry["geocoded_latitude"]
            df.at[idx, "geocoded_longitude"] = entry["geocoded_longitude"]
            df.at[idx, "geocoded_address"] = entry["geocoded_address"]
            df.at[idx, "geocoded_status"] = "success"
            df.at[idx, "coordinate_source"] = entry.get("coordinate_source", "previous_run")
            pre_resolved_count += 1
            
    logger.info(f"Pre-check complete: {pre_resolved_count}/{len(df)} records are already geocoded from previous runs.")
    
    pending_indices = df[df["geocoded_status"] != "success"].index.tolist()
    
    if len(pending_indices) == 0:
        logger.info("All records are already successfully geocoded! No new API queries needed.")
        # Ensure master output has these records
        _save_master_output(df, args.output_file)
        logger.info(f"Master output synchronized at '{args.output_file}'.")
        return
        
    logger.info(f"Need to geocode {len(pending_indices)} remaining pending records.")
    
    # Instantiate Geocoder Provider
    if args.provider == "google":
        key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        if not key:
            logger.error("Google Maps provider requires --api_key or GOOGLE_MAPS_API_KEY environment variable.")
            sys.exit(1)
        geocoder = GoogleMapsGeocoder(api_key=key)
        logger.info("Using Google Maps Geocoding API.")
    elif args.provider == "locationiq":
        key = args.api_key or os.environ.get("LOCATIONIQ_API_KEY")
        if not key:
            logger.error("LocationIQ provider requires --api_key or LOCATIONIQ_API_KEY environment variable.")
            sys.exit(1)
        geocoder = LocationIQGeocoder(api_key=key)
        logger.info("Using LocationIQ Geocoding API.")
    else:
        geocoder = NominatimGeocoder()
        logger.info("Using OpenStreetMap Nominatim (Free, rate-limited to 1 request/sec).")
        
    # Iterate and geocode pending records
    success_count = pre_resolved_count
    pbar = tqdm(total=len(df), initial=pre_resolved_count, desc="Geocoding Addresses")
    
    try:
        if args.provider in ["google", "locationiq"] and args.threads > 1:
            logger.info(f"Running multi-threaded geocoding with {args.threads} workers.")
            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                future_to_idx = {
                    executor.submit(geocode_single_record, df.loc[idx], geocoder, pincode_lookup, validator): idx
                    for idx in pending_indices
                }
                count = 0
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    res = future.result()
                    for k, v in res.items():
                        df.at[idx, k] = v
                    if res["geocoded_status"] == "success":
                        success_count += 1
                    pbar.update(1)
                    count += 1
                    if count % args.checkpoint_interval == 0:
                        df.to_csv(checkpoint_file, index=False)
        else:
            count = 0
            for idx in pending_indices:
                res = geocode_single_record(df.loc[idx], geocoder, pincode_lookup, validator)
                for k, v in res.items():
                    df.at[idx, k] = v
                if res["geocoded_status"] == "success":
                    success_count += 1
                pbar.update(1)
                count += 1
                if count % args.checkpoint_interval == 0:
                    df.to_csv(checkpoint_file, index=False)
                    
    except KeyboardInterrupt:
        logger.warning("Geocoding interrupted by user. Saving current progress...")
        df.to_csv(checkpoint_file, index=False)
        _save_master_output(df, args.output_file)
        logger.info(f"Progress saved to checkpoint and master output '{args.output_file}'.")
        sys.exit(0)
    finally:
        pbar.close()
        
    # Save final results to master output
    _save_master_output(df, args.output_file)
    if os.path.exists(checkpoint_file):
        try:
            os.remove(checkpoint_file)
        except OSError:
            pass
            
    logger.info(f"Geocoding completed! Resolved {success_count}/{len(df)} addresses.")
    logger.info(f"Saved results to '{args.output_file}'.")

    # Optional merge back into raw spreadsheet
    if args.merge_into and os.path.exists(args.merge_into):
        logger.info(f"Merging geocoded GPS coordinates back into '{args.merge_into}'...")
        try:
            from src.data_loader import load_data_file
            raw_df = load_data_file(args.merge_into)
            id_col_cand = [c for c in ["IQVIA ID", "chemist_id", "original_id"] if c in raw_df.columns]
            id_col = id_col_cand[0] if id_col_cand else raw_df.columns[0]
            lat_col = "chem_lat" if "chem_lat" in raw_df.columns else "latitude"
            lon_col = "chem_long" if "chem_long" in raw_df.columns else "longitude"
            
            success_records = df[df["geocoded_status"] == "success"]
            if not success_records.empty and id_col in success_records.columns:
                mapping = success_records.set_index(id_col)[["geocoded_latitude", "geocoded_longitude"]].to_dict(orient="index")
                merged_count = 0
                for idx, r in raw_df.iterrows():
                    rid = str(r[id_col]).strip()
                    if rid in mapping:
                        try:
                            raw_df.at[idx, lat_col] = float(mapping[rid]["geocoded_latitude"])
                            raw_df.at[idx, lon_col] = float(mapping[rid]["geocoded_longitude"])
                            merged_count += 1
                        except (ValueError, TypeError):
                            continue
                
                if args.merge_into.endswith(".xlsx") or args.merge_into.endswith(".xls"):
                    raw_df.to_excel(args.merge_into, index=False)
                else:
                    raw_df.to_csv(args.merge_into, index=False)
                logger.info(f"Successfully updated {merged_count} GPS coordinates in '{args.merge_into}'.")
        except Exception as e:
            logger.warning(f"Failed to merge back into raw file '{args.merge_into}': {e}")


def _save_master_output(current_df: pd.DataFrame, output_path: str):
    """Saves records to the master geocoded output, merging with any existing records."""
    if not os.path.exists(output_path):
        current_df.to_csv(output_path, index=False)
        return
        
    try:
        existing_df = pd.read_csv(output_path, dtype=str)
        id_col_cand = [c for c in ["IQVIA ID", "chemist_id", "original_id"] if c in current_df.columns]
        if id_col_cand:
            id_col = id_col_cand[0]
            # Exclude current IDs from existing, then concat to keep master updated
            curr_ids = set(current_df[id_col].dropna().astype(str))
            kept_existing = existing_df[~existing_df[id_col].astype(str).isin(curr_ids)]
            merged = pd.concat([kept_existing, current_df], ignore_index=True)
            merged.to_csv(output_path, index=False)
        else:
            current_df.to_csv(output_path, index=False)
    except Exception:
        current_df.to_csv(output_path, index=False)


if __name__ == "__main__":
    main()
