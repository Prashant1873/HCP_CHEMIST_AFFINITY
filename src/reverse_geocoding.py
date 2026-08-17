import os
import json
import time
import urllib.request
import urllib.parse
from rapidfuzz import fuzz

class ReverseGeocodingEngine:
    def __init__(self, mode="OFFLINE_ONLY", cache_filepath="reference_data/reverse_geocoding_cache.json"):
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
                print(f"Loaded {len(self.cache)} entries from reverse geocoding cache.")
            except Exception as e:
                print(f"Error loading reverse geocoding cache: {e}. Starting fresh.")
                self.cache = {}
        else:
            dir_name = os.path.dirname(self.cache_filepath)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            self.cache = {}

    def save_cache(self):
        try:
            with open(self.cache_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"Error saving reverse geocoding cache: {e}")

    def reverse_geocode(self, lat, lon):
        """
        Reverse geocodes coordinate.
        Returns: (reverse_city, reverse_state, reverse_pincode, success, error_msg)
        """
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            return "", "", "", False, "Coordinates missing"
            
        key = f"{round(lat, 5)},{round(lon, 5)}"
        
        # Check cache
        if key in self.cache:
            self.cache_hit_count += 1
            cached = self.cache[key]
            if cached.get('success', False):
                return cached['city'], cached['state'], cached['pincode'], True, ""
            else:
                return "", "", "", False, cached.get('error', "Cached failure")
                
        if self.mode == "OFFLINE_ONLY":
            return "", "", "", False, "Reverse geocoding is offline"
            
        if self.mode == "PUBLIC_NOMINATIM_SAMPLE_ONLY" and self.api_call_count >= 50:
            return "", "", "", False, "Reverse geocoding sample limit reached"
            
        # Execute external API call
        city, state, pincode, success, error_msg = self._call_external_api(lat, lon)
        self.api_call_count += 1
        
        if success:
            self.cache[key] = {
                'success': True,
                'city': city,
                'state': state,
                'pincode': pincode,
                'timestamp': time.time()
            }
            self.save_cache()
            return city, state, pincode, True, ""
        else:
            self.cache[key] = {
                'success': False,
                'error': error_msg,
                'timestamp': time.time()
            }
            self.save_cache()
            return "", "", "", False, error_msg

    def _call_external_api(self, lat, lon):
        time.sleep(1.1)
        
        provider_url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'format': 'json',
            'zoom': 18,
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
                    if data and 'address' in data:
                        addr = data['address']
                        
                        # Extract city, state, pincode
                        # Nominatim uses various tags for cities: 'city', 'town', 'village', 'suburb', 'municipality', etc.
                        city = addr.get('city', addr.get('town', addr.get('village', addr.get('suburb', addr.get('county', '')))))
                        state = addr.get('state', '')
                        pincode = addr.get('postcode', '')
                        
                        return city.upper(), state.upper(), pincode.strip(), True, ""
                    else:
                        return "", "", "", False, "Empty address dictionary"
                else:
                    return "", "", "", False, f"HTTP Error {response.status}"
        except Exception as e:
            return "", "", "", False, str(e)

    def validate_match(self, ref_city, ref_state, ref_pincode, rev_city, rev_state, rev_pincode):
        """
        Validates reverse geocoded details against record's normalized city/state/pincode.
        Returns: (reverse_geocode_match_score, reverse_geocode_issue_flags)
        """
        if not rev_city and not rev_state:
            return 0.0, ""
            
        score = 100
        flags = []
        
        # Compare State (simple exact or substring)
        state_match = False
        if ref_state and rev_state:
            if ref_state.upper() == rev_state.upper() or ref_state.upper() in rev_state.upper() or rev_state.upper() in ref_state.upper():
                state_match = True
                
        if not state_match:
            flags.append("REV_STATE_MISMATCH")
            score -= 30
            
        # Compare City (fuzzy or substring)
        city_match = False
        if ref_city and rev_city:
            ratio = fuzz.ratio(ref_city.upper(), rev_city.upper())
            if ratio >= 70 or ref_city.upper() in rev_city.upper() or rev_city.upper() in ref_city.upper():
                city_match = True
                
        if not city_match:
            flags.append("REV_CITY_MISMATCH")
            score -= 30
            
        # Compare Pincode
        pin_match = False
        if ref_pincode and rev_pincode:
            # strip space or dashes
            ref_p = re.sub(r'\D', '', ref_pincode)
            rev_p = re.sub(r'\D', '', rev_pincode)
            if ref_p == rev_p:
                pin_match = True
                
        if not pin_match:
            flags.append("REV_PINCODE_MISMATCH")
            score -= 40
            
        score = max(0, score)
        flags_str = ", ".join(flags) if flags else ""
        return score, flags_str

# Hack to avoid import error in this file
import pandas as pd
