import re

GENERIC_PHRASES = {
    "MAIN ROAD", "MARKET", "NEAR HOSPITAL", "BUS STAND", "STATION ROAD",
    "NEAR BUS STAND", "NEAR STATION", "NEAR RAILWAY STATION", "OPP BUS STAND",
    "OPPOSITE HOSPITAL", "OPPOSITE POLICE STATION", "NEAR POLICE STATION",
    "MARKET AREA", "TOWN HALL", "CITY CENTER", "MAIN MARKET"
}

LOCALITY_TOKENS = {
    "ROAD", "STREET", "ST", "MARKET", "MKT", "COLONY", "CLNY", "HOSPITAL", "HOSP",
    "CHOWK", "CHWK", "CROSSING", "XING", "BUILDING", "BLDG", "APARTMENT", "APPT",
    "FLAT", "FLT", "COMPLEX", "COMP", "LANDMARK", "LNM", "NEAR", "OPPOSITE", "OPP",
    "NAGAR", "GALI", "MOHALLA", "SECTOR", "PHASE", "SHOP", "BAZAR", "BAZAAR",
    "STATION", "STN", "BUS STAND", "STAND", "HIGHWAY", "HWY", "BYPASS", "BY-PASS",
    "SOCIETY", "SOC", "ENCLAVE", "VIHAR", "NIVAS", "NIWAS", "BHAWAN", "HOUSE",
    "COURT", "PLAZA", "MALL", "ARCADE", "TOWER", "TOWERS"
}

JUNK_TOKENS = {
    "A0001", "V0001", "UNITSD", "UNITKLS", "RETAIL SAL", "RETAIL SALE", "WHOLE SAL",
    "WHOLESALE", "DUMMY", "TEMP", "TEST", "TESTING", "UNKNOWN", "NOT AVAILABLE",
    "NIL", "NULL", "NONE", "Xxxxx"
}

def analyze_address_quality(original_address, cleaned_address, normalized_city, extracted_phones):
    """
    Analyzes address string, sets quality flags, and computes the address quality score.
    Returns: (address_quality_score, address_issue_flags)
    """
    flags = []
    score = 100
    
    addr_upper = cleaned_address.upper().strip()
    city_upper = normalized_city.upper().strip()
    
    # 1. ADDRESS_MISSING
    if not original_address.strip() or not addr_upper:
        flags.append("ADDRESS_MISSING")
        score -= 40
        score = max(0, score)
        return score, "ADDRESS_MISSING"
        
    # 2. ADDRESS_SAME_AS_CITY
    if addr_upper == city_upper:
        flags.append("ADDRESS_SAME_AS_CITY")
        score -= 20
        
    # 3. ADDRESS_TOO_SHORT (fewer than 20 characters)
    if len(original_address) < 20:
        flags.append("ADDRESS_TOO_SHORT")
        score -= 25
    # 4. ADDRESS_WEAK (fewer than 30 characters)
    elif len(original_address) < 30:
        flags.append("ADDRESS_WEAK")
        score -= 15
        
    # 5. ADDRESS_CITY_REPEATED
    # Count occurrences of the city name in the address
    if city_upper:
        # Match using word boundaries to avoid matching sub-strings (e.g. "Kolkata" in "Kolkata-700001")
        city_escaped = re.escape(city_upper)
        city_occurrences = len(re.findall(r'\b' + city_escaped + r'\b', addr_upper))
        if city_occurrences >= 3:
            flags.append("ADDRESS_CITY_REPEATED")
            score -= 10
            
    # 6. ADDRESS_HAS_PHONE_NUMBER
    if extracted_phones:
        flags.append("ADDRESS_HAS_PHONE_NUMBER")
        score -= 10
        
    # 7. ADDRESS_HAS_JUNK_TOKEN
    # Check for specific junk words or duplicate word repetitions
    has_junk = False
    for junk in JUNK_TOKENS:
        if re.search(r'\b' + re.escape(junk.upper()) + r'\b', addr_upper):
            has_junk = True
            break
            
    # Also check if any word is repeated 4+ times consecutively (e.g. AGRA AGRA AGRA AGRA)
    if not has_junk:
        dup_pattern = r'\b([A-Z0-9]+)\s+\1\s+\1\s+\1\b'
        if re.search(dup_pattern, addr_upper):
            has_junk = True
            
    if has_junk:
        flags.append("ADDRESS_HAS_JUNK_TOKEN")
        score -= 10
        
    # 8. ADDRESS_LOW_INFORMATION (no road/locality/landmark/building token)
    # Check if address contains any of the locality keywords
    addr_tokens = set(re.findall(r'\b[A-Z0-9]+\b', addr_upper))
    has_locality = any(token in LOCALITY_TOKENS for token in addr_tokens)
    if not has_locality:
        flags.append("ADDRESS_LOW_INFORMATION")
        score -= 10
        
    # 9. ADDRESS_GENERIC
    # Clean the address from city and punctuation to check if it's just a generic phrase
    clean_strip = re.sub(r'\b' + re.escape(city_upper) + r'\b', '', addr_upper)
    clean_strip = re.sub(r'[^A-Z0-9\s]', '', clean_strip)
    clean_strip = re.sub(r'\s+', ' ', clean_strip).strip()
    
    is_generic = clean_strip in GENERIC_PHRASES or addr_upper in GENERIC_PHRASES
    # Also, if after removing city, the remaining address is just numbers or pincodes or empty
    if not is_generic and city_upper:
        words_left = [w for w in re.findall(r'\b[A-Z]+\b', clean_strip) if w != city_upper]
        if len(words_left) == 0:
            is_generic = True
            
    if is_generic:
        flags.append("ADDRESS_GENERIC")
        score -= 20
        
    # 10. ADDRESS_NEEDS_STANDARDIZATION
    # If the clean expanded address differs from clean original address (ignoring multiple spaces)
    orig_clean = re.sub(r'\s+', ' ', original_address.upper()).strip()
    if addr_upper != orig_clean:
        flags.append("ADDRESS_NEEDS_STANDARDIZATION")
        # Note: no score deduction for needs_standardization as it has been corrected
        
    score = max(0, score)
    flags_str = ", ".join(flags) if flags else ""
    
    return score, flags_str
