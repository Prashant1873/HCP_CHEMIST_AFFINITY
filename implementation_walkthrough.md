# Implementation Walkthrough - Chemist Location-Quality Pipeline

This document walks through the technical implementation of the Chemist Location-Quality Pipeline and details the results of running the pipeline on the full dataset of 145,557 chemist records.

---

## 1. Modular Source Code Design

The pipeline is implemented as a modular Python package located in the `src/` directory, coordinated by the main entry script `main_chemist_quality.py`.

### 1.1 Folder Structure

```text
c:\Users\u1204874\Downloads\Chemist data-cleaning\
│
├── main_chemist_quality.py              # CLI entry point, schedules sub-modules and aggregates results
├── config.py                             # Settings, bounds, and thresholds
├── requirements.txt                      # PIP dependency list
├── README.md                             # Detailed project overview and installation guide
├── implementation_walkthrough.md         # Walkthrough of code and results (this file)
│
├── src/
│   ├── __init__.py
│   ├── data_loader.py                    # Loads inputs (Excel/CSV), handles NaN coordinate formatting
│   ├── text_standardization.py           # Address abbreviation expansion, capitalization, phone regex
│   ├── city_state_normalization.py       # City/State correction map
│   ├── address_quality.py                # Flags missing/generic/junk addresses and computes address score
│   ├── pincode_reference.py              # Downloads, caches, and indexes the India Pincode Master
│   ├── pincode_validation.py             # Validates column and address pincodes against reference master
│   ├── coordinate_validation.py          # Swapped check, city centroids, outlier calculation, duplicate clusters
│   ├── confidence_scoring.py             # Overall location confidence score and quality bucket mapping
│   ├── correction_engine.py              # Compiles final coords, source codes, recommended actions, routing flag
│   ├── geocoding_engine.py               # Pluggable geocoder with caching and query fallback
│   ├── reverse_geocoding.py              # Reverse geocoder to double-check coordinates
│   ├── output_writer.py                  # Writes Excel / CSV sheets, implements Openpyxl styling
│   └── utils.py                          # Vectorized Haversine distance calculator
│
├── reference_data/
│   ├── pincode_master.csv                # Cache of India Post post offices (automatically downloaded)
│   └── city_state_synonyms.json          # Spelling mapping synonyms database
│
└── outputs/                              # Directory for audit, clean master, routing-ready, and review files
```

---

## 2. Validation & Scoring Specifications

Each chemist record receives three separate quality scores, which are combined into an overall score:

1.  **Address Quality Score (25% weight)**: Starts at 100. Deductions for missing address (`-40`), short address $<20$ chars (`-25`), weak address $<30$ chars (`-15`), generic address (`-20`), same as city (`-20`), repeated city $\ge 3$ times (`-10`), contains phone number (`-10`), junk token (`-10`), no locality/road keyword (`-10`).
2.  **Pincode Quality Score (25% weight)**: Starts at 100. Deductions for invalid format (`-50`), not found in reference (`-40`), state mismatch (`-30`), city/district mismatch (`-20`), address contains different pincode (`-25`).
3.  **Coordinate Quality Score (45% weight)**: Starts at 100. Deductions for missing coordinates (`-50`), invalid format (`-50`), outside India bounding box (`-50`), city centroid outlier warning $>50$ km (`-25`), critical outlier $>100$ km (`-40`), pincode reference mismatch (`-30`), duplicate cluster size $\ge 5$ (`-15`), size $\ge 20$ (`-25`), size $\ge 100$ (`-40`), centroid fallback suspected (`-20`), lat-long swap corrected (`-15`).
4.  **Geocoding/Validation (5% weight)**: If geocoding is offline (default), this weight is redistributed: 45% Coordinates, 27.5% Pincode, 27.5% Address.

---

## 3. Results on the Full Dataset

The pipeline was executed against `Chemist_test_HCM.xlsx` containing **145,557 records** in `OFFLINE_ONLY` geocoding mode.

### 3.1 Geocoding Mode Confirmation
*   **Geocoding mode used**: `OFFLINE_ONLY`
*   **API calls**: 0
*   **Accurate coordinates generation statement**: Since `OFFLINE_ONLY` mode was used, the pipeline audited, corrected swapped lat-longs, and flagged problematic coordinates, but **did not fetch fresh geocoded coordinates from external web APIs**.
*   **Treatment of missing coordinates**: For records with missing or invalid coordinates, `final_lat` and `final_long` were **left blank (NaN)**, and `coordinate_source` was set to `NO_USABLE_COORDINATE`. They were **not** approximated using pincode/city centroids.

### 3.2 Quality Bucket Breakdown

| Quality Bucket | Confidence Score | Record Count | Percentage |
| :--- | :--- | :--- | :--- |
| **HIGH** | $\ge 85$ | 102,646 | 70.52% |
| **MEDIUM** | $65 - 84$ | 35,230 | 24.20% |
| **LOW** | $40 - 64$ | 7,656 | 5.26% |
| **CRITICAL** | $< 40$ | 25 | 0.02% |

### 3.3 Coordinate Source Breakdown

| Coordinate Source | Count | Percentage | Description |
| :--- | :--- | :--- | :--- |
| `ORIGINAL_ACCEPTED_HIGH_CONFIDENCE` | 97,182 | 66.77% | Good quality original coordinates |
| `ORIGINAL_ACCEPTED_WITH_FLAGS` | 30,625 | 21.04% | Usable original coordinates with minor quality warnings |
| `ORIGINAL_CORRECTED_LATLONG_SWAP` | 1 | 0.00% | Swap corrected coordinates |
| `NO_USABLE_COORDINATE` | 17,749 | 12.19% | Missing or completely invalid coordinates (left blank) |
| *Geocoded sources* | 0 | 0.00% | Offline mode was used |

### 3.4 Business Routing Reliability vs. Technical Eligibility

We distinguish between physical coordinate usability (technical eligibility) and spatial confidence (reliability):

-   **Technical Routing Eligibility** (`eligible_for_routing_flag` = `TRUE`): Indicates coordinates exist.
    *   **Eligible**: **127,808 records (87.81%)**
    *   **Ineligible**: **17,749 records (12.19%)**
-   **Business Routing Reliability** (`routing_reliability_bucket` and `routing_risk_flag`): Classified by quality scores and severe flags:

| Reliability Bucket | Risk Flag | Count | % | Description |
| :--- | :--- | :--- | :--- | :--- |
| **HIGH_RELIABILITY** | `USE` | 99,707 | 68.50% | HIGH confidence, no severe coordinate issues |
| **MODERATE_RELIABILITY** | `USE_WITH_CAUTION` | 14,203 | 9.76% | MEDIUM confidence, no severe coordinate issues |
| **LOW_RELIABILITY** | `REVIEW_BEFORE_USE` | 270 | 0.19% | LOW confidence, no severe coordinate issues |
| **HIGH_RISK** | `REVIEW_BEFORE_USE` | 31,377 | 21.56% | CRITICAL score, severe coordinate issues, or missing |

---

## 4. Output Files Description

We generated several files in the `outputs/` folder:

### 4.1 Routing Inputs
*   `outputs/chemist_master_routing_eligible_all.csv`: Contains all **127,808 eligible chemists** where final coordinates exist.
*   `outputs/chemist_master_routing_recommended.csv`: Contains **114,180 recommended chemists** (includes `HIGH_RELIABILITY`, `MODERATE_RELIABILITY`, and `LOW_RELIABILITY` records; strictly excludes the 31,377 `HIGH_RISK` records).

### 4.2 Enriched Validation Files
*   `outputs/score_distribution_by_issue_flag.csv`: Shows record counts and average scores for each issue flag.
*   `outputs/city_wise_location_risk_summary.csv`: Aggregated counts of reliability buckets and recommended records per city.
*   `outputs/pincode_issue_detail.csv`: List of unique pincodes, showing total chemists, status modes, and mismatches.
*   `outputs/coordinate_outlier_review.csv`: Lists all chemists with swapped coords, critical outliers, or duplicated clusters.

---

## 5. Phase 2: Targeted Address Enhancement & Re-Geocoding

Phase 2 builds a targeted query-level enrichment and geocoding strategy on top of the Phase 1 audited master.

### 5.1 Key Principles & Guidelines
1.  **Audit Trail and Integrity**:
    - The Phase 1 offline audit did **not** generate fresh coordinates; missing coordinates remained blank, and risky original locations were preserved with warnings.
    - Original input addresses and coordinate fields are never overwritten.
2.  **Targeted Selection**:
    - Only problematic records (e.g. missing coords, high-risk bucket, centroids, duplicates, city mismatches) are targeted. We do not geocode the full dataset blindly.
3.  **Address Standardization vs Rewriting**:
    - Address correction is restricted to standard abbreviation expansions, formatting, junk token extraction, and context enrichment (appending normalized city, state, validated pincode, and country tags).
    - Address meanings or localities are never blindly rewritten or invented.
4.  **Coordinate Validation Guards**:
    - Candidates are validated against bounding boxes, city medians, and known centroids.
    - Pincode and city centroids are flagged as approximate and must never be treated as exact shop coordinates.
5.  **Promotion Constraints**:
    - Final coordinates are updated only after validation and only when running the script with the `--apply_geocoding_updates TRUE` flag.
    - When updates are promoted, previous coordinates are backed up in `previous_final_lat`/`previous_final_long` along with timestamps and reasons.
6.  **Environments**:
    - Public APIs are rate-limited and capped. For bulk production runs, self-hosted geocoding engines are preferred.

### 5.2 Pilot/Sample Mode Selection
The pilot engine draws a stratified sample to evaluate geocoding performance across diverse issues:
- 30% Missing Coordinates (`COORD_MISSING`)
- 30% Critical City Outliers (`COORD_CITY_MISMATCH_CRITICAL`)
- 20% Duplicate centroid/high cluster records (duplicates $\ge 20$)
- 10% Pincode mismatch + coordinate issues
- 10% Random high-risk records

---

## 6. Doctor-Chemist Routing Consumption

Downstream mapping pipelines should consume:
1.  **Coordinates**: `final_lat` and `final_long` (original columns `chem_lat`/`chem_long` are kept strictly for audit).
2.  **Audit trail**: Mappings should carry `normalized_city`, `quality_bucket`, `overall_location_confidence_score`, `coordinate_source`, and `coordinate_issue_flags` directly into final mapping outputs, enabling business users to detect mapped chemists with location-risky coordinates.
