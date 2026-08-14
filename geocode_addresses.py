# Module and standalone script for batch address geocoding using Nominatim, Google Maps, or LocationIQ
import os
import sys
import time
import argparse
from typing import Optional, Tuple, Dict, Any
import pandas as pd
import requests
from tqdm import tqdm

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src import config

logger = setup_logger("geocoder")


class BaseGeocoder:
    """Base class for geocoding providers."""
    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        raise NotImplementedError


class NominatimGeocoder(BaseGeocoder):
    """
    OpenStreetMap Nominatim Geocoder (Free, rate limited to 1 request/sec).
    """
    def __init__(self, user_agent: str = "ChemistDoctorMatcher/2.0 (contact: support@hcp-affinity.internal)"):
        self.endpoint = "https://nominatim.openstreetmap.org/search"
        self.headers = {"User-Agent": user_agent}
        self.last_query_time = 0.0
        self.min_delay = 1.0  # 1 second delay between calls per OSM usage policy

    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
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
            resp = requests.get(self.endpoint, params=params, headers=self.headers, timeout=10)
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
        self.api_key = api_key
        self.endpoint = "https://maps.googleapis.com/maps/api/geocode/json"

    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        params = {
            "address": query,
            "components": "country:IN",
            "key": self.api_key
        }

        try:
            resp = requests.get(self.endpoint, params=params, timeout=10)
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
        self.api_key = api_key
        self.endpoint = "https://us1.locationiq.com/v1/search"

    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        params = {
            "key": self.api_key,
            "q": query,
            "countrycodes": "in",
            "format": "json",
            "limit": 1
        }

        try:
            resp = requests.get(self.endpoint, params=params, timeout=10)
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
    """Cleans common noise from Indian address strings."""
    if pd.isna(raw_addr):
        return ""
    addr = str(raw_addr).strip()
    # Remove excessive commas, quotes, hyphens
    addr = addr.replace('"', '').replace("'", "").replace("\n", ", ")
    while ",," in addr:
        addr = addr.replace(",,", ",")
    return addr.strip(" ,-")


def build_query_hierarchy(row: pd.Series) -> list:
    """
    Constructs a tiered list of address queries from most specific to broader area.
    """
    queries = []
    
    name = str(row.get("chem_name", row.get("chemist_name", ""))).strip()
    addr = clean_address_string(row.get("chem_address", row.get("chemist_address", "")))
    city = str(row.get("chem_city", row.get("chemist_city", ""))).strip()
    state = str(row.get("chem_state", row.get("chemist_state", ""))).strip()
    pin = str(row.get("chem_pincode", row.get("chemist_pincode", ""))).strip()
    
    if pin and "." in pin:
        pin = pin.split(".")[0]
    pin = "".join(c for c in pin if c.isdigit())
    
    # 1. Full address with city & pincode
    components_full = [c for c in [addr, city, state, pin, "India"] if c and c != "nan"]
    if components_full:
        queries.append(", ".join(components_full))
        
    # 2. Name + Address + City
    if name and name != "nan" and name != "Unknown":
        components_name = [c for c in [name, addr, city, pin, "India"] if c and c != "nan"]
        queries.append(", ".join(components_name))
        
    # 3. Cleaned road/area + city + pin (stripping shop/flat numbers and landmark prefixes)
    if addr:
        parts = [p.strip() for p in addr.split(",") if p.strip()]
        meaningful_parts = []
        for p in parts:
            p_lower = p.lower()
            # Filter out pure shop numbers or unit designations
            if any(kw in p_lower for kw in ["shop no", "shop-", "gala no", "plot no", "flat no", "g.f", "ground floor", "1st fl", "2nd fl"]):
                continue
            meaningful_parts.append(p)
            
        if meaningful_parts:
            cleaned_area = ", ".join(meaningful_parts)
            components_area = [c for c in [cleaned_area, city, pin, "India"] if c and c != "nan"]
            queries.append(", ".join(components_area))
            
            # Also try without "NEAR / OPP / BEHIND" prefixes
            stripped_parts = []
            for p in meaningful_parts:
                p_clean = p
                for prefix in ["nr.", "nr ", "near ", "opp.", "opp ", "opposite ", "behind ", "b/h ", "adj."]:
                    if p_clean.lower().startswith(prefix):
                        p_clean = p_clean[len(prefix):].strip()
                stripped_parts.append(p_clean)
            if stripped_parts != meaningful_parts:
                queries.append(", ".join([c for c in [", ".join(stripped_parts), city, pin, "India"] if c and c != "nan"]))

    # Remove duplicates while preserving order
    unique_queries = []
    for q in queries:
        if q and q not in unique_queries:
            unique_queries.append(q)
            
    return unique_queries


def main():
    parser = argparse.ArgumentParser(
        description="Batch Geocoding tool to resolve GPS coordinates for invalid/missing chemist records."
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
        help="API Key for Google Maps or LocationIQ (can also use env vars GOOGLE_MAPS_API_KEY / LOCATIONIQ_API_KEY)"
    )
    parser.add_argument(
        "--city",
        type=str,
        default=None,
        help="Filter records to geocode by 3-digit pincode prefix or city (e.g. '--city 400')"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of records to geocode in this run (useful for testing)"
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
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        logger.error(f"Input file '{args.input_file}' does not exist.")
        sys.exit(1)
        
    logger.info(f"Loading input file: {args.input_file}...")
    df = pd.read_csv(args.input_file, dtype=str)
    logger.info(f"Loaded {len(df)} records.")
    
    # Filter by city/pincode prefix if provided
    if args.city:
        city_filters = [c.strip() for c in str(args.city).split(",") if c.strip()]
        logger.info(f"Applying city filter: {city_filters}")
        mask = pd.Series(False, index=df.index)
        for filt in city_filters:
            if filt.isdigit():
                pin_col = "chemist_pincode" if "chemist_pincode" in df.columns else "chem_pincode"
                if pin_col in df.columns:
                    mask |= df[pin_col].astype(str).str.startswith(filt)
            else:
                filt_clean = "".join(c for c in filt.lower() if c.isalnum())
                for col in ["chem_city", "chemist_city"]:
                    if col in df.columns:
                        mask |= df[col].astype(str).apply(
                            lambda x: filt_clean in "".join(c for c in str(x).lower() if c.isalnum())
                        )
        df = df[mask].reset_index(drop=True)
        logger.info(f"Retained {len(df)} records matching city filter '{args.city}'.")
        
    if args.limit and args.limit > 0:
        df = df.head(args.limit).copy()
        logger.info(f"Limiting execution to first {len(df)} records.")
        
    if len(df) == 0:
        logger.warning("No records to geocode. Exiting.")
        sys.exit(0)
        
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
        
    # Prepare output fields
    if "geocoded_latitude" not in df.columns:
        df["geocoded_latitude"] = ""
    if "geocoded_longitude" not in df.columns:
        df["geocoded_longitude"] = ""
    if "geocoded_address" not in df.columns:
        df["geocoded_address"] = ""
    if "geocoded_status" not in df.columns:
        df["geocoded_status"] = "pending"
        
    output_dir = os.path.dirname(args.output_file) or "outputs"
    os.makedirs(output_dir, exist_ok=True)
    checkpoint_file = os.path.join(output_dir, "geocoding_checkpoint.csv")
    
    # Load existing checkpoint if available
    if os.path.exists(checkpoint_file):
        try:
            ckpt_df = pd.read_csv(checkpoint_file, dtype=str)
            id_col = "IQVIA ID" if "IQVIA ID" in df.columns else df.columns[0]
            if id_col in ckpt_df.columns:
                ckpt_dict = ckpt_df.set_index(id_col).to_dict(orient="index")
                for idx, row in df.iterrows():
                    rec_id = row[id_col]
                    if rec_id in ckpt_dict and ckpt_dict[rec_id].get("geocoded_status") == "success":
                        df.at[idx, "geocoded_latitude"] = ckpt_dict[rec_id].get("geocoded_latitude", "")
                        df.at[idx, "geocoded_longitude"] = ckpt_dict[rec_id].get("geocoded_longitude", "")
                        df.at[idx, "geocoded_address"] = ckpt_dict[rec_id].get("geocoded_address", "")
                        df.at[idx, "geocoded_status"] = "success"
                logger.info(f"Loaded existing progress from checkpoint: {(df['geocoded_status'] == 'success').sum()} already resolved.")
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")
            
    # Iterate and geocode
    success_count = (df["geocoded_status"] == "success").sum()
    logger.info("Starting batch geocoding...")
    
    pbar = tqdm(total=len(df), initial=success_count, desc="Geocoding Addresses")
    
    try:
        for idx, row in df.iterrows():
            if df.at[idx, "geocoded_status"] == "success":
                continue
                
            queries = build_query_hierarchy(row)
            found = False
            
            for q in queries:
                res = geocoder.geocode(q)
                if res:
                    lat, lon, disp = res
                    # Validate within India bounding box
                    if (config.INDIA_LAT_MIN <= lat <= config.INDIA_LAT_MAX) and \
                       (config.INDIA_LON_MIN <= lon <= config.INDIA_LON_MAX):
                        df.at[idx, "geocoded_latitude"] = str(lat)
                        df.at[idx, "geocoded_longitude"] = str(lon)
                        df.at[idx, "geocoded_address"] = str(disp)
                        df.at[idx, "geocoded_status"] = "success"
                        found = True
                        success_count += 1
                        break
                        
            if not found:
                df.at[idx, "geocoded_status"] = "not_found"
                
            pbar.update(1)
            
            if (idx + 1) % args.checkpoint_interval == 0:
                df.to_csv(checkpoint_file, index=False)
                
    except KeyboardInterrupt:
        logger.warning("Geocoding interrupted by user. Saving current progress...")
        df.to_csv(checkpoint_file, index=False)
        sys.exit(0)
    finally:
        pbar.close()
        
    # Save final results
    df.to_csv(args.output_file, index=False)
    if os.path.exists(checkpoint_file):
        try:
            os.remove(checkpoint_file)
        except OSError:
            pass
            
    logger.info(f"Geocoding completed! Resolved {success_count}/{len(df)} addresses.")
    logger.info(f"Saved results to '{args.output_file}'.")


if __name__ == "__main__":
    main()
