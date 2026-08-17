import os
import json
import re

def clean_and_upper(text):
    """
    Cleans spacing and returns uppercase text.
    """
    if not isinstance(text, str):
        return ""
    # Remove non-breaking spaces and collapse spaces
    text = text.replace('\xa0', ' ').replace('\u200b', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip().upper()

class CityStateNormalizer:
    def __init__(self, synonyms_filepath=None):
        self.cities_map = {}
        self.states_map = {}
        
        # Load synonym mappings from JSON or use defaults
        self._load_synonyms(synonyms_filepath)
        
    def _load_synonyms(self, filepath):
        # Fallback dictionary if JSON loading fails
        default_cities = {
            "CALCUTTA": "KOLKATA",
            "BANGALORE": "BENGALURU",
            "BENGLURU": "BENGALURU",
            "BOMBAY": "MUMBAI",
            "AMDAVAD": "AHMEDABAD",
            "AHD": "AHMEDABAD",
            "HYD": "HYDERABAD",
            "SECUNDERABAD": "HYDERABAD",
            "GURGAON": "GURUGRAM"
        }
        default_states = {
            "GUJRAT": "GUJARAT",
            "TAMILNADU": "TAMIL NADU",
            "UTTARPRADESH": "UTTAR PRADESH",
            "MADHYAPRADESH": "MADHYA PRADESH",
            "MAHARASTRA": "MAHARASHTRA",
            "TELENAGANA": "TELANGANA"
        }
        
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cities_map = {clean_and_upper(k): clean_and_upper(v) for k, v in data.get('cities', {}).items()}
                    self.states_map = {clean_and_upper(k): clean_and_upper(v) for k, v in data.get('states', {}).items()}
                    return
            except Exception:
                # Fall back to defaults on parse/read error
                pass
                
        # Set defaults if file is missing or failed to parse
        self.cities_map = {k: v for k, v in default_cities.items()}
        self.states_map = {k: v for k, v in default_states.items()}

    def normalize(self, city, state):
        """
        Normalizes city and state names using the synonyms map and flags alterations.
        Returns: (normalized_city, normalized_state, city_state_normalization_flags)
        """
        city_orig = clean_and_upper(city)
        state_orig = clean_and_upper(state)
        
        flags = []
        
        # 1. Normalize City
        if not city_orig:
            norm_city = ""
            flags.append("CITY_MISSING")
        else:
            norm_city = self.cities_map.get(city_orig, city_orig)
            if norm_city != city_orig:
                flags.append("CITY_NORMALIZED")
                
        # 2. Normalize State
        if not state_orig:
            norm_state = ""
            flags.append("STATE_MISSING")
        else:
            norm_state = self.states_map.get(state_orig, state_orig)
            if norm_state != state_orig:
                flags.append("STATE_NORMALIZED")
                
        flags_str = ", ".join(flags) if flags else ""
        return norm_city, norm_state, flags_str
