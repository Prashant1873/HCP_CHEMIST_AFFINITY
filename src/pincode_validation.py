import re

def extract_pincodes_from_str(text):
    """
    Finds all 6-digit sequences in a string that resemble Indian pincodes.
    """
    if not text:
        return []
    # Avoid matches surrounded by other digits (e.g. a phone number)
    return re.findall(r'\b\d{6}\b', text)

def validate_pincode_record(original_pincode, cleaned_address, normalized_city, normalized_state, pincode_ref_data):
    """
    Validates a chemist record's pincode, comparing it to the address pincode and the pincode master.
    Returns a dictionary of pincode quality outputs.
    """
    flags = []
    score = 100
    status = "REVIEW_REQUIRED"
    
    # Pad input pincode to 6 digits if it's numeric and less than 6 digits
    col_pin = original_pincode.strip()
    if col_pin.isdigit():
        col_pin = col_pin.zfill(6)
        
    extracted_pincode_col = col_pin
    
    # 1. Format check
    is_valid_format = len(col_pin) == 6 and col_pin.isdigit() and not col_pin.startswith('0')
    if not is_valid_format:
        flags.append("PINCODE_INVALID_FORMAT")
        score -= 50
        status = "INVALID_OR_NOT_FOUND"
        
    # 2. Extract pincode from address
    addr_pins = extract_pincodes_from_str(cleaned_address)
    extracted_pincode_addr = addr_pins[0] if addr_pins else ""
    
    # Check if address pincode differs from column pincode
    addr_differs = False
    addr_has_diff_pin = False
    
    if extracted_pincode_addr:
        if is_valid_format and extracted_pincode_col != extracted_pincode_addr:
            addr_differs = True
            flags.append("PINCODE_ADDRESS_DIFFERS_FROM_COLUMN")
            # If address contains a pincode different from the column, check if multiple pins exist
            # or if it's just a direct mismatch.
            addr_has_diff_pin = True
            flags.append("PINCODE_ADDRESS_CONTAINS_DIFFERENT_PIN")
            score -= 25
            
    # 3. Lookup in reference database
    ref_state = ""
    ref_district = ""
    ref_post_offices = ""
    found_in_ref = False
    
    if is_valid_format and pincode_ref_data:
        ref_entry = pincode_ref_data.get(extracted_pincode_col)
        if ref_entry:
            found_in_ref = True
            ref_state = ref_entry['state']
            ref_district = ref_entry['district']
            ref_post_offices = ref_entry['post_offices']
        else:
            flags.append("PINCODE_NOT_FOUND_IN_REFERENCE")
            score -= 40
            status = "INVALID_OR_NOT_FOUND"
    else:
        if is_valid_format:  # format valid but database empty/missing
            flags.append("PINCODE_NOT_FOUND_IN_REFERENCE")
            score -= 40
            status = "INVALID_OR_NOT_FOUND"

    suggested_pin = extracted_pincode_col
    
    # 4. Compare locations if found in reference
    if found_in_ref:
        # State mismatch
        state_match = normalized_state.upper() == ref_state.upper()
        if not state_match:
            # Maybe one is blank, but if both present and differ
            if normalized_state and ref_state:
                flags.append("PINCODE_STATE_MISMATCH")
                score -= 30
                
        # City/District mismatch
        # Check if normalized city matches the reference district or is present in post offices/district
        city_match = False
        city_upper = normalized_city.upper()
        
        if city_upper:
            # check direct equality
            if city_upper == ref_district.upper():
                city_match = True
            # check substring
            elif city_upper in ref_district.upper() or ref_district.upper() in city_upper:
                city_match = True
            # check post offices list
            elif city_upper in ref_post_offices.upper():
                city_match = True
                
        if not city_match and normalized_city:
            flags.append("PINCODE_CITY_DISTRICT_MISMATCH")
            score -= 20
            # City mismatch warning (uncertain)
            score -= 10
            
        # Determine status
        if "PINCODE_STATE_MISMATCH" in flags:
            status = "REVIEW_REQUIRED"
        elif "PINCODE_CITY_DISTRICT_MISMATCH" in flags:
            status = "VALID_STATE_MATCH_CITY_UNCERTAIN"
        elif addr_differs:
            status = "COLUMN_ADDRESS_PIN_MISMATCH"
            # Suggest the address pincode if it's found in reference and state matches
            if extracted_pincode_addr in pincode_ref_data:
                addr_ref = pincode_ref_data[extracted_pincode_addr]
                if addr_ref['state'].upper() == normalized_state.upper():
                    suggested_pin = extracted_pincode_addr
                    status = "VALID_BUT_ADDRESS_MISMATCH"
        else:
            status = "VALID_HIGH_CONFIDENCE"
    else:
        # If not found, check if address pincode is found in reference
        if extracted_pincode_addr and extracted_pincode_addr in pincode_ref_data:
            addr_ref = pincode_ref_data[extracted_pincode_addr]
            if addr_ref['state'].upper() == normalized_state.upper():
                suggested_pin = extracted_pincode_addr
                flags.append("PINCODE_REVIEW_REQUIRED")
                status = "COLUMN_ADDRESS_PIN_MISMATCH"
        else:
            status = "INVALID_OR_NOT_FOUND"

    # Add review flag if any major flags present
    major_pincode_flags = {"PINCODE_INVALID_FORMAT", "PINCODE_NOT_FOUND_IN_REFERENCE", "PINCODE_STATE_MISMATCH"}
    if any(f in flags for f in major_pincode_flags):
        flags.append("PINCODE_REVIEW_REQUIRED")
        
    # De-duplicate flags
    flags = list(dict.fromkeys(flags))
    
    score = max(0, score)
    flags_str = ", ".join(flags) if flags else ""
    
    return {
        'validated_pincode': extracted_pincode_col,
        'suggested_pincode': suggested_pin,
        'pincode_reference_state': ref_state,
        'pincode_reference_district': ref_district,
        'pincode_reference_post_offices': ref_post_offices,
        'pincode_status': status,
        'pincode_quality_score': score,
        'pincode_issue_flags': flags_str
    }
