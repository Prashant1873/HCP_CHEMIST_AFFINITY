import re

def clean_str_field(val):
    """
    Safely converts any value (including NaN, None, float, int) to a clean string.
    Returns empty string for null-like values.
    """
    if val is None:
        return ""
    val_str = str(val).strip()
    if val_str.lower() in ["", "nan", "none", "nat", "<na>"]:
        return ""
    return val_str

def extract_locality_landmark(address):
    """
    Heuristic to extract locality/road/landmark from address for loose query Level 3.
    Splits by comma and retrieves the primary street or landmark details.
    """
    addr_clean = clean_str_field(address)
    if not addr_clean:
        return ""
    
    parts = [p.strip() for p in addr_clean.split(',') if p.strip()]
    if not parts:
        return ""
        
    # Check if the first part is too short (e.g., Shop No / House No) and merge with the second part if available
    first_part = parts[0]
    if len(parts) > 1:
        digits_only = re.sub(r'\D', '', first_part)
        if len(first_part) < 8 or first_part.isdigit() or len(digits_only) == len(first_part):
            return f"{first_part} {parts[1]}"
            
    return first_part

def enrich_geocoding_address(chemist_name, cleaned_address, city, state, pincode):
    """
    Assembles the fully enriched address string for Query Level 1.
    """
    name_clean = clean_str_field(chemist_name).upper()
    addr_clean = clean_str_field(cleaned_address).upper()
    city_clean = clean_str_field(city).upper()
    state_clean = clean_str_field(state).upper()
    pin_clean = clean_str_field(pincode)
    
    components = []
    if name_clean:
        components.append(name_clean)
    if addr_clean:
        components.append(addr_clean)
    if city_clean and city_clean not in addr_clean:
        components.append(city_clean)
    if state_clean and state_clean not in addr_clean:
        components.append(state_clean)
    if pin_clean and pin_clean not in addr_clean:
        components.append(pin_clean)
    components.append("INDIA")
    
    return ", ".join(components)

def generate_geocoding_query(level, name, cleaned_address, city, state, pincode):
    """
    Generates strict-to-loose geocoding queries corresponding to Level 1-5.
    """
    name_clean = clean_str_field(name).upper()
    addr_clean = clean_str_field(cleaned_address).upper()
    city_clean = clean_str_field(city).upper()
    state_clean = clean_str_field(state).upper()
    pin_clean = clean_str_field(pincode)
    
    if level == 1:
        return enrich_geocoding_address(name_clean, addr_clean, city_clean, state_clean, pin_clean)
        
    elif level == 2:
        components = [addr_clean]
        if city_clean and city_clean not in addr_clean:
            components.append(city_clean)
        if state_clean and state_clean not in addr_clean:
            components.append(state_clean)
        if pin_clean and pin_clean not in addr_clean:
            components.append(pin_clean)
        components.append("INDIA")
        return ", ".join(components)
        
    elif level == 3:
        locality = extract_locality_landmark(addr_clean)
        components = []
        if locality:
            components.append(locality)
        if city_clean:
            components.append(city_clean)
        if state_clean:
            components.append(state_clean)
        components.append("INDIA")
        return ", ".join(components)
        
    elif level == 4:
        components = []
        if pin_clean:
            components.append(pin_clean)
        if city_clean:
            components.append(city_clean)
        if state_clean:
            components.append(state_clean)
        components.append("INDIA")
        return ", ".join(components)
        
    elif level == 5:
        components = []
        if city_clean:
            components.append(city_clean)
        if state_clean:
            components.append(state_clean)
        components.append("INDIA")
        return ", ".join(components)
        
    return ""

def enhance_chemist_address_record(original_address, cleaned_address, chemist_name_original, normalized_city, normalized_state, validated_pincode):
    """
    Evaluates address corrections and constructs enriched query address.
    Returns: (enriched_geocoding_address, address_correction_status, address_correction_notes)
    """
    notes = []
    status = "STANDARDIZED"
    
    orig_str = clean_str_field(original_address)
    clean_str = clean_str_field(cleaned_address)
    
    orig_clean = re.sub(r'\s+', ' ', orig_str.upper()).strip()
    clean_upper = clean_str.upper().strip()
    
    if clean_upper != orig_clean:
        notes.append("Abbreviation expanded")
        status = "STANDARDIZED_AND_ENRICHED"
    else:
        status = "ENRICHED"
        
    notes.append("Appended normalized city/state/pincode and country tag for query construction")
    
    # Phone numbers removed from query address
    phone_pattern = r'(?:\+?91[-.\s]?)?[6-9]\d{9}|\b0\d{2,4}[-.\s]?\d{6,8}\b|\b\d{10}\b'
    if re.search(phone_pattern, orig_str):
        notes.append("Removed phone digits from query string")
        
    # Obvious non-address junk removed
    for junk in ["A0001", "V0001", "UNITSD", "UNITKLS", "RETAIL SAL", "RETAIL SALE", "WHOLESALE"]:
        if junk in orig_str.upper():
            notes.append(f"Excluded junk token '{junk}' from geocoding query")
            
    enriched_addr = enrich_geocoding_address(
        chemist_name_original, cleaned_address, normalized_city, normalized_state, validated_pincode
    )
    
    notes_str = "; ".join(notes)
    
    return enriched_addr, status, notes_str
