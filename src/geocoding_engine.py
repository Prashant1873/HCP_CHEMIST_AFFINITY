import os
import json
import time
import urllib.request
import urllib.parse

class GeocodingEngine:
    def __init__(self, mode="OFFLINE_ONLY", cache_filepath="reference_data/geocoding_cache.json"):
        self.mode = mode
        self.cache_filepath = cache_filepath
        self.cache = {}
        self.api_call_count = 0
        self.cache_hit_count = 0
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.cache_filepath):
            try:
                with open(self.cache_filepath, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                print(f"Loaded {len(self.cache)} entries from geocoding cache.")
            except Exception as e:
                print(f"Error loading geocoding cache: {e}. Starting fresh.")
                self.cache = {}
        else:
            # Ensure directory exists
            dir_name = os.path.dirname(self.cache_filepath)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            self.cache = {}

    def save_cache(self):
        try:
            with open(self.cache_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
            # print("Saved geocoding cache locally.")
        except Exception as e:
            print(f"Error saving geocoding cache: {e}")

    def geocode_record(self, name, address, city, state, pincode):
        """
        Geocodes a record using strict-to-loose query fallbacks.
        Returns: (result_lat, result_long, query_used, provider, confidence_score, type_match, error_msg)
        """
        # 1. Build queries
        queries = []
        
        # Query 1: Strict (Full Info)
        q1 = f"{name}, {address}, {city}, {state}, {pincode}, India"
        queries.append((q1, "full_address_name"))
        
        # Query 2: Standard Address
        q2 = f"{address}, {city}, {state}, {pincode}, India"
        queries.append((q2, "full_address"))
        
        # Query 3: Locality/Road extracted from Address (take first part of address before first comma)
        locality = address.split(',')[0].strip() if ',' in address else address
        if locality and len(locality) > 5:
            q3 = f"{locality}, {city}, {state}, India"
            queries.append((q3, "locality_city"))
            
        # Query 4: Loose (Pincode & City)
        if pincode:
            q4 = f"{pincode}, {city}, {state}, India"
            queries.append((q4, "pincode_centroid"))
        else:
            q4 = f"{city}, {state}, India"
            queries.append((q4, "city_centroid"))
            
        # 2. Process queries strict-to-loose
        for query, query_type in queries:
            query_clean = " ".join(query.split()).upper()
            
            # Check cache first
            if query_clean in self.cache:
                self.cache_hit_count += 1
                cached_res = self.cache[query_clean]
                if cached_res.get('success', False):
                    return (
                        cached_res['lat'], 
                        cached_res['lon'], 
                        query, 
                        "CACHED_" + cached_res.get('provider', self.mode),
                        cached_res.get('confidence_score', 1.0),
                        query_type,
                        ""
                    )
                else:
                    # Previous cache record represents a known failure, skip to next query
                    continue

            # Cache miss - if OFFLINE_ONLY, do not hit external APIs
            if self.mode == "OFFLINE_ONLY":
                continue
                
            # If PUBLIC_NOMINATIM_SAMPLE_ONLY, limit to 50 API calls to protect IP/rate limits
            if self.mode == "PUBLIC_NOMINATIM_SAMPLE_ONLY" and self.api_call_count >= 50:
                continue

            # Execute external API call
            lat, lon, success, error_msg = self._call_external_api(query)
            self.api_call_count += 1
            
            # Store in cache
            if success:
                # Deduce confidence score based on the query level
                conf = 0.95 if query_type == "full_address_name" else (
                       0.85 if query_type == "full_address" else (
                       0.60 if query_type == "locality_city" else 0.30))
                       
                self.cache[query_clean] = {
                    'success': True,
                    'lat': lat,
                    'lon': lon,
                    'provider': self.mode,
                    'confidence_score': conf,
                    'query_type': query_type,
                    'timestamp': time.time()
                }
                self.save_cache()
                return (lat, lon, query, self.mode, conf, query_type, "")
            else:
                self.cache[query_clean] = {
                    'success': False,
                    'error': error_msg,
                    'timestamp': time.time()
                }
                # Save cache on failures too to avoid repeated useless calls
                self.save_cache()
                # Try next query in loop
                
        # Return fallback if no query succeeded
        return (None, None, "", "NONE", 0.0, "NONE", "All geocoding queries failed or geocoding is offline")

    def _call_external_api(self, query):
        """
        Calls Nominatim API or a custom API.
        Respects the 1-second rate limit.
        """
        # Nominatim rate limit: 1 request per second
        time.sleep(1.1)
        
        provider_url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        
        url_parts = urllib.parse.urlencode(params)
        full_url = f"{provider_url}?{url_parts}"
        
        try:
            req = urllib.request.Request(
                full_url, 
                headers={
                    'User-Agent': 'ChemistQualityPipeline/1.0 (chemist_cleansing_agent; contact: analyst@chemistmaster.local)',
                    'Accept-Language': 'en'
                }
            )
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data:
                        lat = float(data[0]['lat'])
                        lon = float(data[0]['lon'])
                        return lat, lon, True, ""
                    else:
                        return None, None, False, "No results found"
                else:
                    return None, None, False, f"HTTP Error {response.status}"
        except Exception as e:
            return None, None, False, str(e)
