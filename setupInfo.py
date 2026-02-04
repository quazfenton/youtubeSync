#!/usr/bin/env python3
"""
Test script to verify YouTube Monitor setup
"""

import os
import sys
from pathlib import Path

def test_setup():
    """Test if all required components are available"""
    print("Testing YouTube Monitor setup...")
    
    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # Test 1: Check if required files exist
    required_files = [
        'monitor.py',
        'config.py',
        'run_monitor.py'
    ]
    
    print("\n1. Checking required files...")
    for file in required_files:
        if (script_dir / file).exists():
            print(f"   ✓ {file} exists")
        else:
            print(f"   ✗ {file} missing")
            return False
    
    # Test 2: Check if data directory exists
    print("\n2. Checking data directory...")
    data_dir = script_dir / 'data'
    if data_dir.exists():
        print("   ✓ data directory exists")
    else:
        print("   ⚠ data directory missing, creating...")
        data_dir.mkdir(exist_ok=True)
        print("   ✓ data directory created")
    
    # Test 3: Check if .env file exists
    print("\n3. Checking environment file...")
    env_file = script_dir / '.env'
    if env_file.exists():
        print("   ✓ .env file exists")
    else:
        print("   ⚠ .env file missing")
        print("   Tip: Copy .env.example to .env and customize settings")
    
    # Test 4: Try importing required modules
    print("\n4. Testing Python imports...")
    required_imports = [
        'requests',
        'bs4',  # beautifulsoup4
        'selenium',
        'playwright',
        'google.auth',
        'google.oauth2',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'dotenv'
    ]
    
    failed_imports = []
    for module in required_imports:
        try:
            __import__(module.replace('.', '_').replace('-', '_')) if '-' in module or '.' in module else __import__(module)
            print(f"   ✓ {module}")
        except ImportError as e:
            print(f"   ✗ {module} - {e}")
            failed_imports.append(module)
    
    if failed_imports:
        print(f"\n⚠ Some imports failed. Install missing packages:")
        print(f"   pip install {' '.join(required_imports)}")
        return False
    
    # Test 5: Try importing the monitor module
    print("\n5. Testing monitor module import...")
    try:
        sys.path.insert(0, str(script_dir))
        import monitor
        print("   ✓ monitor module imported successfully")
    except Exception as e:
        print(f"   ✗ Failed to import monitor module: {e}")
        return False
    
    print("\n✓ All tests passed! The setup appears to be correct.")
    print("\nTo run the monitor in n8n, use:")
    print("   Command: python")
    print("   Arguments: /home/workspace/Automations/youtubeSync/monitor.py")
    print("   Working Directory: /home/workspace/Automations/youtubeSync")
    
    return True

if __name__ == "__main__":
    success = test_setup()
    sys.exit(0 if success else 1)