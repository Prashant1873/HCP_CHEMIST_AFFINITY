# Doctor-Chemist Matching Pipeline

This is a production-grade Python tool designed to map doctors to their nearest chemist candidates using a high-performance spatial nearest-neighbor search. 

It handles thousands of doctor records and lakhs of chemist records efficiently, validating geographic coordinates, detecting latitude-longitude column inversions, isolating corrupted records, and outputting candidate pairs. It is built to serve as the candidate generation step in a scalable two-stage geographic routing system.

---

## 1. System Overview & Core Objective

Calculating the exact road distance (via car routing engines) for every possible pair of doctors and chemists is computationally prohibitive at scale. 
For instance, with **10,000 doctors** and **500,000 chemists**, a brute-force approach requires computing **5 billion road distances**, which is impractical.

To solve this, this pipeline implements a **two-stage filtering architecture**:
1. **Stage 1 (This Tool)**: Find the top $K$ (e.g. 50) nearest chemists by straight-line (Haversine) air distance using a spatial index. This reduces the number of pairs from 5 billion to **500,000 pairs** (a 10,000x reduction).
2. **Stage 2 (Future)**: Calculate the actual road distance *only* for the shortlisted top $K$ candidate pairs using a routing engine (e.g., local OSRM, GraphHopper, or Valhalla), ranking them by road distance, and selecting the final nearest $N$ (e.g., 5).

---

## 2. Why BallTree with Haversine Metric?

* **Spherical Earth Geodesic**: Traditional Euclidean distance (e.g., KDTree) distort distances over the spherical surface of the earth, especially as latitude changes. The `Haversine` formula computes accurate great-circle (air) distances on a sphere.
* **Logarithmic Scaling**: Brute-force pairwise search scales at $\mathcal{O}(D \times C)$ (Doctors $\times$ Chemists). By constructing a `BallTree` on chemist coordinates, candidate query scaling is reduced to $\mathcal{O}(D \log C)$, allowing queries of lakhs of chemists in milliseconds.

---

## 3. Why Pincode is NOT the Default Method

* **Boundary Overlook**: Chemists located immediately across a pincode boundary may be the closest candidates for a doctor, but they would be ignored by strict pincode-only matching.
* **Data Quality Issues**: Pincodes in data files are often missing, typed incorrectly, or lose leading zeros when coerced into numerical formats.
* **Secondary Fallback**: In this codebase, coordinates are the primary source of truth, but we provide pincode cleaning and matching logic as an optional secondary filtering method (`--pincode_fallback`).

---

## 4. Input Files & Formatting Requirements

The pipeline expects two spreadsheets in the project directory (supporting `.csv`, `.xlsx`, and `.xls`):
1. **Doctor File** (e.g., `Doctor_test_HCM.xlsx`)
2. **Chemist File** (e.g., `Chemist_test_HCM.xlsx`)

### Auto-Detected Column Schemas
The application automatically scans the columns and resolves names matching the following patterns (case-insensitive, ignoring special characters):

| Field | Possible Candidate Names |
| :--- | :--- |
| **Latitude** | `latitude`, `lat`, `doctor_lat`, `dr_lat`, `chemist_lat`, `Latitude`, `LAT` |
| **Longitude** | `longitude`, `lon`, `lng`, `long`, `chemist_long`, `Longitude`, `LNG` |
| **Doctor ID** | `doctor_id`, `dr_id`, `hcp_id`, `Doc ID`, `doctor_code`, `dr_code` |
| **Chemist ID**| `chemist_id`, `retailer_id`, `account_id`, `IQVIA ID`, `chemist_code` |
| **Names** | `doctor_name`, `chem_name`, `outlet_name`, `store_name`, `Name` |
| **Pincodes** | `pincode`, `pin`, `pin_code`, `zip`, `chem_pincode` |

If no ID/name columns are detected, the tool creates sequential synthetic identifiers (e.g., `DOC_000001`, `CHEM_000001`) while preserving the raw rows for complete visibility.

---

## 5. Cleaning & Quality Edge Cases Handled

The pipeline implements rigorous validation rules to ensure downstream spatial operations do not crash on dirty data:
* **Global Boundary Check**: Coordinates must be numeric. Latitude must be in $[-90, 90]$ and Longitude in $[-180, 180]$.
* **India Bounding Box Bounding**: Latitude must be within $[6.0, 38.0]$ and Longitude within $[68.0, 98.0]$. Out-of-bounds records are flagged.
* **Coordinate Inversion Check**: If latitude falls in the range $[68.0, 98.0]$ and longitude in the range $[6.0, 38.0]$, the coordinates are likely inverted (common in manual entry). The program flags and isolates these into the rejected files.
* **Pincode Standardizer**: Standardizes pincodes into 6-digit text strings, restoring lost leading zeros (e.g., `40010` -> `040010`) and stripping floating-point decimals (e.g., `110001.0` -> `110001`).

---

## 6. How to Run the Pipeline

Execute the pipeline from the project root using the Python executable:

```bash
# Using Python absolute path:
C:\Users\u1204874\AppData\Local\Python\pythoncore-3.14-64\python.exe main.py
```

### Command-Line Customization
You can override file paths, candidate size $K$, final selection $N$, city filters, and output folders:

```bash
python main.py \
  --doctor_file "Doctor_test_HCM.xlsx" \
  --chemist_file "Chemist_test_HCM.xlsx" \
  --candidate_k 50 \
  --final_n 5 \
  --city "Mumbai" \
  --output_dir "outputs"
```

* **City Filter (`--city`)**:
  * Filter by city name (e.g. `--city "Mumbai"`). This accurately matches city names across metropolitan areas including suburbs/satellite regions (e.g., Kalyan, Dombivli, Thane) regardless of pincode prefix variations.
  * Supports multiple comma-separated cities (e.g. `--city "Mumbai,Pune,Delhi"`).
  * Also supports pincode prefix fallback (e.g. `--city 400`).
* To change candidate size $K$ to other limits, use `--candidate_k 10`, `--candidate_k 20`, `--candidate_k 30`, or `--candidate_k 100`.

---

### 7. Road-Distance Engine Integration & Ranking (Phase 2)

Once candidate pairs are generated by Phase 1, Phase 2 queries a local routing server (GraphHopper or OSRM) to calculate driving road distances, ranks candidates, and selects the final nearest chemists.

### Local GraphHopper Setup (Recommended)
GraphHopper is a Java-based routing engine that reads the OpenStreetMap PBF file and serves routes locally.
1. **Prerequisite**: Java JDK 17 or newer. (A portable JDK 17 can be downloaded from Amazon Corretto/Adoptium).
2. **Download JAR**: Download the standalone web server JAR (`graphhopper-web-10.0.jar`) from the GraphHopper GitHub releases page.
3. **Download Config**: Download the `config-example.yml` template, and disable Contraction Hierarchies (`profiles_ch: []`) to run in flexible memory mode.
4. **Start Server**: Run the server by passing the India OSM PBF file and config:
   ```bash
   .\jdk17\jdk17.0.19_10\bin\java.exe -Xmx8g -Ddw.graphhopper.datareader.file="india-latest.osm.pbf" -jar graphhopper-web-10.0.jar server config-example.yml
   ```
   This will start the routing service on `http://localhost:8989`.

### Execution
Execute Phase 2 using the routing coordinator script pointing to the local GraphHopper server:
```bash
python road_routing.py --routing_engine GraphHopper --osrm_endpoint http://localhost:8989 --city "Mumbai"
```

### CLI Customizations
* `--input_file`: Path to the air-distance candidates file (default: `outputs/doctor_chemist_candidates_air_distance.csv`).
* `--city`: Filter candidate pairs by city name (e.g. `--city "Mumbai"` or `--city "Mumbai,Pune"`).
* `--routing_engine`: Routing engine to use: `GraphHopper` or `OSRM` (default: `GraphHopper`).
* `--osrm_endpoint`: HTTP endpoint of the local instance. Defaults to `http://localhost:8989` for GraphHopper, `http://localhost:5000` for OSRM.
* `--final_n`: Target number of nearest chemists to select per doctor (default: `5`).
* `--simulate`: Flag to simulate driving distances for testing without a routing engine (uses circuity factor + noise).
* `--sleep`: Sleep interval (in seconds) between routing requests to limit load (default: `0.0`).
* `--checkpoint_interval`: Writes in-progress states to a checkpoint CSV every $C$ route calculations (default: `1000`).

### Mock Simulation Mode
To test the pipeline mechanics (retries, checkpoints, output structures) without a running routing server, activate mock simulation:
```bash
C:\Users\u1204874\AppData\Local\Python\bin\python3.exe road_routing.py --simulate
```
This generates simulated driving distances and outputs files with the `simulated_` prefix.

### Resiliency: Retries & Checkpoints
* **Retries**: If a route query fails due to timeout or network errors, it retries the calculation up to 2 times (3 attempts total) before flagging `road_distance_status = failed` and proceeding.
* **Checkpoint & Resume**: Progress is written to `outputs/road_distance_checkpoint.csv` every 1,000 route calculations. If execution is interrupted, restarting the script automatically reads the checkpoint, skips already computed rows, and resumes the remaining tasks. The checkpoint is deleted upon successful completion.

---

## 8. Output Files Inventory

The two-phase pipeline writes all deliverables into the `outputs/` folder:

### Phase 1 Outputs (Air Distance)
* **`doctor_chemist_candidates_air_distance.csv` / `.xlsx`**: Candidates (K=50) shortlisted per doctor by air distance.
* **`invalid_doctor_records.csv`**: Doctors excluded due to corrupted coordinates, annotated with reasons.
* **`invalid_chemist_records.csv`**: Chemists excluded due to corrupted coordinates, annotated with reasons.
* **`run_summary.txt`**: Count summaries and detected columns for Phase 1.
* **`config_used.json`**: Execution configuration parameters.

### Phase 2 Real Outputs (Real Road Distance & Validation)
* **`doctor_chemist_candidates_with_real_road_distance.csv` / `.xlsx`**: Full candidate dataset containing calculated actual road distances, routing engine tags, status flags, and error logs.
* **`final_doctor_nearest_5_chemists_by_real_road_distance.csv` / `.xlsx`**: The target business deliverable containing the final nearest 5 chemists ranked by actual driving distance.
* **`real_osrm_road_distance_run_summary.txt`**: Summarizes Phase 2 runtimes, success rates, and average/median road distances.
* **`real_air_rank_capture_analysis.csv`**: Detailed doctor-level validation matrix recording the maximum air distance rank needed to capture all top 5 road-distance chemists.
* **`real_osrm_candidate_k_capture_summary.csv`**: Aggregated capture rates across all doctors for different sizes of $K$:
  ```text
  candidate_k, doctors_fully_captured_count, doctors_total, capture_rate
  10,          215,                           299,           71.9%
  20,          284,                           299,           95.0%
  30,          290,                           299,           97.0%
  50,          299,                           299,           100.0%
  ```
  *Analysis Conclusion*: shortlisting $K=30$ candidates captures **97.0%** of the final actual road-distance top 5 chemists, allowing a 40% reduction in routing query volume for future production runs.
* **`city_wise_candidate_k_capture_summary.csv`**: Aggregated capture rates for $K=10, 20, 30, 50$ at a per-city level to highlight geographic variation in spatial density and routing efficiency.
* **`road_distance_gap_analysis.csv`**: Measures the distance gap (in km) between the 5th nearest road distance chemist and the 6th/10th nearest chemists for each doctor, along with `is_k30_missed` flags to evaluate choice of K.
* **`k30_missed_doctors_analysis.csv`**: Isolates the specific doctor-chemist candidate pairs where the chemist was in the top 5 by road distance but ranked > 30 in terms of air distance, and would therefore be missed under a $K=30$ threshold.

---

## 9. Batch Address Geocoding Tool

To recover GPS coordinates for chemist records with missing coordinates or to resolve written text addresses from `outputs/invalid_chemist_records.csv`:

```bash
# 1. Using Free OpenStreetMap Nominatim (Rate limited to 1 req/sec)
python geocode_addresses.py --city "Mumbai"

# 2. Using Google Maps Geocoding API (Fastest & most accurate for Indian addresses)
python geocode_addresses.py --provider google --api_key "YOUR_API_KEY"

# 3. Using LocationIQ API
python geocode_addresses.py --provider locationiq --api_key "YOUR_API_KEY"
```

### CLI Options:
* `--input_file`: Path to the file containing records to geocode (default: `outputs/invalid_chemist_records.csv`).
* `--provider`: `nominatim` (default, free), `google`, or `locationiq`.
* `--api_key`: API key for Google Maps or LocationIQ (can also use env vars `GOOGLE_MAPS_API_KEY` / `LOCATIONIQ_API_KEY`).
* `--city`: Filter records to geocode by city name (e.g. `--city "Mumbai"`). Supports comma-separated city names.
* `--limit`: Limit number of records to process in the run (useful for testing, e.g. `--limit 50`).
* `--output_file`: Destination path for geocoded records (default: `outputs/geocoded_chemist_records.csv`).

---

## 10. Known Limitations

* **Spherical Approximation**: Great-circle calculations assume a perfectly spherical Earth ($R = 6371.0088\text{ km}$), introducing minor errors (less than 0.5%) which are negligible for localized shortlisting.
* **Routing Server Required for Road Distances**: The script requires a routing engine (OSRM or GraphHopper) to perform path-finding algorithms against the OpenStreetMap data.
