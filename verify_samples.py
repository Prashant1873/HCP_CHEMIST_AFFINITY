import pandas as pd
import requests
import random
import time
import os
import sys

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def verify_samples(csv_path="results/final_doctor_nearest_5_chemists_by_real_road_distance.csv", num_samples=10):
    if not os.path.exists(csv_path):
        print(f"Error: File not found at {csv_path}")
        return

    df = pd.read_csv(csv_path)
    print(f"Loaded dataset: {len(df)} total pairs across {df['doctor_id'].nunique()} unique doctors.")
    print(f"Testing {num_samples} random samples against live online routing (OSRM) & Google Maps...\n")
    print("=" * 90)

    unique_doctors = df['doctor_id'].unique()
    selected_docs = random.sample(list(unique_doctors), min(num_samples, len(unique_doctors)))

    sampled_rows = []
    for doc in selected_docs:
        doc_sub = df[df['doctor_id'] == doc]
        sampled_rows.append(doc_sub.sample(n=1).iloc[0])

    sampled = pd.DataFrame(sampled_rows)

    count = 1
    for idx, row in sampled.iterrows():
        lat1, lon1 = float(row['doctor_latitude']), float(row['doctor_longitude'])
        lat2, lon2 = float(row['chemist_latitude']), float(row['chemist_longitude'])
        local_road_km = float(row['road_distance_km']) if pd.notnull(row['road_distance_km']) else None
        air_km = float(row['air_distance_km'])
        
        # Query public OSRM API
        osrm_url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        osrm_dist_km = None
        try:
            resp = requests.get(osrm_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'routes' in data and len(data['routes']) > 0:
                    osrm_dist_km = round(data['routes'][0]['distance'] / 1000.0, 3)
                else:
                    osrm_dist_km = "No route"
            else:
                osrm_dist_km = f"HTTP {resp.status_code}"
        except Exception as e:
            osrm_dist_km = f"Err: {e}"
            
        gmaps_url = f"https://www.google.com/maps/dir/?api=1&origin={lat1},{lon1}&destination={lat2},{lon2}&travelmode=driving"
        
        if isinstance(osrm_dist_km, (int, float)) and local_road_km is not None:
            diff_m = round(abs(local_road_km - osrm_dist_km) * 1000, 1)
            diff_str = f"{diff_m} meters"
        else:
            diff_str = "N/A"

        print(f"Sample #{count}")
        print(f"  [Doctor] : {row['doctor_name']} (ID: {row['doctor_id']}, Pincode: {row['doctor_pincode']})")
        print(f"  [Chemist]: {row['chemist_name']} (ID: {row['chemist_id']}, Pincode: {row['chemist_pincode']})")
        print(f"  Coordinates      : Doctor ({lat1:.6f}, {lon1:.6f}) -> Chemist ({lat2:.6f}, {lon2:.6f})")
        print(f"  Air Distance     : {air_km:.3f} km")
        print(f"  Local GraphHopper: {local_road_km:.3f} km (Rank: #{int(row['road_distance_rank']) if pd.notnull(row['road_distance_rank']) else 'N/A'})")
        print(f"  Online OSRM      : {osrm_dist_km} km")
        print(f"  Difference       : {diff_str}")
        print(f"  Google Maps Link : {gmaps_url}")
        print("-" * 90)
        
        count += 1
        time.sleep(0.3)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    verify_samples(num_samples=n)
