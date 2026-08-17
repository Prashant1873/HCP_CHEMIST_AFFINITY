import os
import pandas as pd
import subprocess

def run_test():
    # 1. Load full file first few rows
    input_file = "Chemist_test_HCM.xlsx"
    sample_file = "Chemist_test_HCM_sample.xlsx"
    
    print(f"Reading sample from {input_file}...")
    df = pd.read_excel(input_file, sheet_name="Chemist", nrows=100)
    
    # Save as sample Excel
    print(f"Writing sample to {sample_file}...")
    df.to_excel(sample_file, sheet_name="Chemist", index=False)
    
    # Run main script using Python executable
    python_exe = r"C:\Users\u1204874\AppData\Local\Python\pythoncore-3.14-64\python.exe"
    cmd = [python_exe, "main_chemist_quality.py", "--input_file", sample_file]
    
    print(f"Running pipeline on sample: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("\n--- Pipeline STDOUT ---")
    print(result.stdout)
    
    print("\n--- Pipeline STDERR ---")
    print(result.stderr)
    
    if result.returncode == 0:
        print("\nPipeline executed successfully on sample data!")
        # Check if outputs exist
        outputs = [
            "outputs/chemist_location_quality_audit.csv",
            "outputs/chemist_location_quality_audit.xlsx",
            "outputs/chemist_master_cleaned_enriched.csv",
            "outputs/chemist_master_cleaned_enriched.xlsx",
            "outputs/chemist_master_routing_eligible.csv",
            "outputs/chemist_master_routing_eligible.xlsx",
            "outputs/chemist_data_quality_summary.txt",
            "outputs/chemist_quality_dashboard.xlsx",
            "outputs/config_used.json"
        ]
        
        missing = [o for o in outputs if not os.path.exists(o)]
        if missing:
            print("ERROR: The following output files are missing:")
            for m in missing:
                print(f"  - {m}")
        else:
            print("All required output files were generated successfully!")
            
            # Print contents of summary report
            print("\n--- Summary Report Content ---")
            with open("outputs/chemist_data_quality_summary.txt", "r") as f:
                print(f.read())
    else:
        print(f"\nPipeline failed with return code {result.returncode}")

if __name__ == "__main__":
    run_test()
