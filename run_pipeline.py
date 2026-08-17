# Unified End-to-End Pipeline Execution Script
"""
Doctor-to-Chemist Nearest Neighbor Matching Pipeline (Unified Runner)
Executes:
1. Phase 1: Ingestion, GPS verification, GeoJSON Pincode boundary validation,
   Generic name filtering, Chemist deduplication, and 1.0 km Hard Filter candidate generation.
2. Phase 2: Turn-by-turn road distance calculations (GraphHopper / OSRM / Simulation),
   Road distance re-ranking, and Publishing of clean deliverables to 'results/'.
"""
import os
import sys
import time
import argparse
import subprocess
import requests

# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils import setup_logger
from src import config

logger = setup_logger("run_pipeline")


def is_service_reachable(endpoint: str, timeout_sec: float = 1.5) -> bool:
    """Checks if a local routing server (GraphHopper or OSRM) is responding."""
    try:
        r = requests.get(endpoint, timeout=timeout_sec)
        return r.status_code < 500
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Unified End-to-End Doctor-Chemist Spatial & Road Distance Pipeline."
    )
    parser.add_argument(
        "--doctor_file",
        type=str,
        default=None,
        help="Path to doctor input Excel/CSV file (default: auto-detected in workspace)."
    )
    parser.add_argument(
        "--chemist_file",
        type=str,
        default=None,
        help="Path to chemist input Excel/CSV file (default: auto-detected in workspace)."
    )
    parser.add_argument(
        "--city",
        type=str,
        default=None,
        help="Optional city filter (e.g. '--city Mumbai' or '--city Mumbai,Pune')."
    )
    parser.add_argument(
        "--routing_engine",
        type=str,
        choices=["GraphHopper", "OSRM"],
        default="GraphHopper",
        help="Routing engine for Phase 2 (default: GraphHopper)."
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Custom routing endpoint (default: http://localhost:8989 for GraphHopper, http://localhost:5000 for OSRM)."
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        help="Number of concurrent worker threads for routing queries (default: 8)."
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate road distances without requiring a live routing server."
    )
    parser.add_argument(
        "--max_distance_km",
        type=float,
        default=config.DEFAULT_MAX_DISTANCE_KM,
        help=f"Hard distance filter: exclude chemists farther than this distance (default: {config.DEFAULT_MAX_DISTANCE_KM} km)."
    )
    parser.add_argument(
        "--final_n",
        type=int,
        default=config.DEFAULT_FINAL_N,
        help=f"Number of nearest chemists to select per doctor (default: {config.DEFAULT_FINAL_N})."
    )
    parser.add_argument(
        "--no_pincode_verification",
        dest="verify_pincodes",
        action="store_false",
        help="Disable GeoJSON pincode boundary verification."
    )
    parser.add_argument(
        "--no_generic_filter",
        dest="exclude_generic_names",
        action="store_false",
        help="Disable filtering of generic chemist store names."
    )
    
    args = parser.parse_args()
    
    start_time = time.time()
    logger.info("=================================================================")
    logger.info("STARTING UNIFIED DOCTOR-CHEMIST SPATIAL MATCHING PIPELINE")
    logger.info("=================================================================")
    
    # -------------------------------------------------------------------------
    # STEP 1: Execute Phase 1 (main.py)
    # -------------------------------------------------------------------------
    logger.info("\n>>> EXECUTING PHASE 1: Spatial Ingestion, Exclusions & Candidate Generation...")
    
    cmd_phase1 = [
        sys.executable, "main.py",
        "--max_distance_km", str(args.max_distance_km),
        "--final_n", str(args.final_n)
    ]
    if args.doctor_file:
        cmd_phase1.extend(["--doctor_file", args.doctor_file])
    if args.chemist_file:
        cmd_phase1.extend(["--chemist_file", args.chemist_file])
    if args.city:
        cmd_phase1.extend(["--city", args.city])
    if hasattr(args, "verify_pincodes") and not args.verify_pincodes:
        cmd_phase1.append("--no_pincode_verification")
    if hasattr(args, "exclude_generic_names") and not args.exclude_generic_names:
        cmd_phase1.append("--no_generic_filter")
        
    res_phase1 = subprocess.run(cmd_phase1)
    if res_phase1.returncode != 0:
        logger.error(f"Phase 1 terminated with error (exit code {res_phase1.returncode}). Aborting pipeline.")
        sys.exit(res_phase1.returncode)
        
    logger.info("Phase 1 finished successfully.")
    
    # -------------------------------------------------------------------------
    # STEP 2: Pre-check Routing Service Availability for Phase 2
    # -------------------------------------------------------------------------
    routing_engine = args.routing_engine
    simulate = args.simulate
    
    default_endpoint = "http://localhost:8989" if routing_engine == "GraphHopper" else "http://localhost:5000"
    target_endpoint = args.endpoint or default_endpoint
    
    if not simulate:
        logger.info(f"Checking availability of {routing_engine} routing server at {target_endpoint}...")
        if not is_service_reachable(target_endpoint):
            logger.warning(
                f"\n[WARNING] {routing_engine} server is not responding at {target_endpoint}!\n"
                f"Please start GraphHopper using 'start_graphhopper.bat' or run with '--simulate'.\n"
            )
            logger.info("Phase 1 candidate outputs are ready in 'outputs/'.")
            sys.exit(1)
        else:
            logger.info(f"{routing_engine} server is live and responsive.")
            
    # -------------------------------------------------------------------------
    # STEP 3: Execute Phase 2 (road_routing.py)
    # -------------------------------------------------------------------------
    logger.info("\n>>> EXECUTING PHASE 2: Road Distance Calculations & Final Publishing...")
    
    cmd_phase2 = [
        sys.executable, "road_routing.py",
        "--routing_engine", routing_engine,
        "--threads", str(args.threads),
        "--final_n", str(args.final_n)
    ]
    if args.endpoint:
        cmd_phase2.extend(["--osrm_endpoint", args.endpoint])
    if simulate:
        cmd_phase2.append("--simulate")
    if args.city:
        cmd_phase2.extend(["--city", args.city])
        
    res_phase2 = subprocess.run(cmd_phase2)
    if res_phase2.returncode != 0:
        logger.error(f"Phase 2 terminated with error (exit code {res_phase2.returncode}).")
        sys.exit(res_phase2.returncode)
        
    total_sec = time.time() - start_time
    logger.info("=================================================================")
    logger.info(f"UNIFIED PIPELINE COMPLETED SUCCESSFULLY IN {total_sec:.2f} SECONDS!")
    logger.info("Final deliverable sheets and summary are published in 'results/' folder:")
    logger.info("  1. results/final_doctor_nearest_5_chemists.xlsx (.csv)")
    logger.info("  2. results/excluded_chemists.xlsx (.csv)")
    logger.info("  3. results/run_summary.txt")
    logger.info("=================================================================")


if __name__ == "__main__":
    main()
