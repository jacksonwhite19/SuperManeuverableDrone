"""
Check if optimizer is still running
Non-intrusive - only reads files, never modifies anything
"""

import json
import os
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "optimizer_status.json")
OUTPUT_LOG = os.path.join(SCRIPT_DIR, "optimizer_output.log")

def check_alive():
    """Check if optimizer is still running."""
    
    print("="*80)
    print("OPTIMIZER HEALTH CHECK")
    print("="*80)
    print()
    
    # Check status file exists
    if not os.path.exists(STATUS_FILE):
        print("[STATUS] Status file not found")
        print("  -> Optimizer may not be running")
        return False
    
    # Read status
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            status = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not read status file: {e}")
        return False
    
    # Check status
    opt_status = status.get('status', 'unknown')
    timestamp_str = status.get('timestamp', '')
    iteration = status.get('iteration', 0)
    
    print(f"[STATUS] {opt_status.upper()}")
    print(f"[ITERATION] {iteration}")
    
    if timestamp_str:
        try:
            # Parse timestamp
            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            age_seconds = (now - timestamp).total_seconds()
            age_minutes = age_seconds / 60.0
            
            print(f"[LAST UPDATE] {timestamp_str} ({age_minutes:.1f} minutes ago)")
            
            # Check if stale
            if opt_status == 'running':
                if age_minutes > 15:
                    print()
                    print("[WARNING] Status file hasn't updated in >15 minutes!")
                    print("  -> Optimizer may be stuck or crashed")
                    print("  -> Check optimizer_output.log for errors")
                    return False
                elif age_minutes > 10:
                    print()
                    print("[CAUTION] Status file hasn't updated in >10 minutes")
                    print("  -> VSPAero may be running a long analysis")
                    return True
                else:
                    print()
                    print("[OK] Status file is recent - optimizer appears active")
                    return True
            else:
                print()
                print(f"[INFO] Optimizer status: {opt_status}")
                return True
                
        except Exception as e:
            print(f"[WARNING] Could not parse timestamp: {e}")
            return True  # Assume OK if we can't parse
    
    # Check output log for recent activity
    if os.path.exists(OUTPUT_LOG):
        try:
            # Check file modification time
            mod_time = os.path.getmtime(OUTPUT_LOG)
            mod_datetime = datetime.fromtimestamp(mod_time)
            age_seconds = (datetime.now() - mod_datetime).total_seconds()
            age_minutes = age_seconds / 60.0
            
            print(f"[LOG FILE] Last modified: {age_minutes:.1f} minutes ago")
            
            if age_minutes > 20 and opt_status == 'running':
                print()
                print("[WARNING] Output log hasn't been updated recently")
                print("  -> Optimizer may have crashed")
        except:
            pass
    
    print()
    print("="*80)
    return True

if __name__ == "__main__":
    is_alive = check_alive()
    exit(0 if is_alive else 1)

