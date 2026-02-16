#!/usr/bin/env python
"""
Quick validation script for Phase 1.1: MongoDB Connection & Configuration

This script verifies that:
1. All required dependencies are installed
2. MongoDB is accessible
3. Connection pooling is working
4. Basic operations can be performed

Usage:
    python verify_phase_1_1.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_header(text):
    """Print colored header"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text.center(60)}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_success(text):
    """Print success message"""
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text):
    """Print error message"""
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text):
    """Print warning message"""
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_info(text):
    """Print info message"""
    print(f"{BLUE}ℹ {text}{RESET}")

def check_dependencies():
    """Check if all required dependencies are installed"""
    print_header("Checking Dependencies")
    
    required_packages = {
        "pymongo": "MongoDB Python Driver",
        "fastapi": "FastAPI Framework",
        "pydantic": "Data Validation",
        "dotenv": "Environment Configuration",
    }
    
    all_ok = True
    for package, description in required_packages.items():
        try:
            __import__(package)
            print_success(f"{description} ({package})")
        except ImportError:
            print_error(f"{description} ({package}) - NOT INSTALLED")
            all_ok = False
    
    return all_ok

def check_environment():
    """Check environment configuration"""
    print_header("Checking Environment Configuration")
    
    # Load .env file if it exists
    env_file = project_root / ".env"
    if env_file.exists():
        print_success(f".env file found at {env_file}")
        
        # Parse .env file
        with open(env_file) as f:
            env_vars = {}
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
        
        # Check key MongoDB variables
        mongodb_uri = env_vars.get("MONGODB_URI", os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
        mongodb_db = env_vars.get("MONGODB_DB", os.environ.get("MONGODB_DB", "voice_agent"))
        
        print_info(f"MongoDB URI: {mongodb_uri[:50]}...")
        print_info(f"Database: {mongodb_db}")
    else:
        print_warning(f".env file not found - using defaults")
        print_info("MongoDB URI: mongodb://localhost:27017")
        print_info("Database: voice_agent")

def check_mongodb_connection():
    """Test MongoDB connection"""
    print_header("Testing MongoDB Connection")
    
    try:
        from backend.database import mongo_client
        
        print_info("Attempting to connect to MongoDB...")
        mongo_client.connect()
        print_success("Connected to MongoDB")
        
        # Check connection status
        status = mongo_client.get_connection_status()
        if status["status"] == "connected":
            print_success(f"Connection verified - Version: {status.get('version', 'unknown')}")
        else:
            print_warning(f"Connection status: {status}")
        
        return True, mongo_client
        
    except ConnectionError as e:
        print_error(f"Connection failed: {str(e)}")
        print_warning("Make sure MongoDB is running on the configured address")
        return False, None
    except Exception as e:
        print_error(f"Unexpected error: {str(e)}")
        return False, None

def test_collection_access(mongo_client):
    """Test accessing a collection"""
    print_header("Testing Collection Access")
    
    try:
        collection = mongo_client.get_collection("_test")
        print_success(f"Successfully accessed collection: _test")
        
        # Try to count documents
        count = collection.count_documents({})
        print_info(f"Document count in test collection: {count}")
        
        return True
    except Exception as e:
        print_error(f"Collection access failed: {str(e)}")
        return False

def test_session_management(mongo_client):
    """Test session management"""
    print_header("Testing Session Management")
    
    try:
        with mongo_client.session() as session:
            print_success("Session created successfully")
            print_info(f"Session ID: {session.session_id}")
        
        print_success("Session closed successfully")
        return True
    except Exception as e:
        print_error(f"Session management failed: {str(e)}")
        return False

def test_connection_pool():
    """Test connection pool configuration"""
    print_header("Testing Connection Pool Configuration")
    
    try:
        from backend.database import mongo_client
        
        print_info(f"Min pool size: {mongo_client._min_pool_size}")
        print_info(f"Max pool size: {mongo_client._max_pool_size}")
        print_info(f"Connection timeout: {mongo_client._connection_timeout}ms")
        
        print_success("Connection pool configured")
        return True
    except Exception as e:
        print_error(f"Pool configuration check failed: {str(e)}")
        return False

def test_uri_masking(mongo_client):
    """Test URI masking for credential protection"""
    print_header("Testing URI Masking (Security Feature)")
    
    try:
        from backend.database import MongoDBClient
        
        test_uri = "mongodb://admin:secretpass@localhost:27017"
        masked = MongoDBClient._mask_uri(test_uri)
        
        if "admin" not in masked and "secretpass" not in masked and "***:***@" in masked:
            print_success("URI masking working correctly")
            print_info(f"Original: {test_uri}")
            print_info(f"Masked:   {masked}")
            return True
        else:
            print_warning("URI masking may not be working as expected")
            return False
    except Exception as e:
        print_error(f"URI masking test failed: {str(e)}")
        return False

def generate_report(results):
    """Generate final report"""
    print_header("Verification Report")
    
    total = len(results)
    passed = sum(1 for r in results.values() if r)
    
    print(f"Total checks: {total}")
    print(f"Passed: {GREEN}{passed}{RESET}")
    print(f"Failed: {RED}{total - passed}{RESET}")
    
    if passed == total:
        print_success("All checks passed! Phase 1.1 is ready.")
        return 0
    else:
        print_warning("Some checks failed. Please review the output above.")
        return 1

def main():
    """Run all verification checks"""
    print_header("Phase 1.1 MongoDB Connection Verification")
    print("This script verifies the implementation of Phase 1.1")
    
    results = {}
    
    # Check dependencies
    results["Dependencies"] = check_dependencies()
    
    if not results["Dependencies"]:
        print_error("\nPlease install required dependencies:")
        print("  pip install -r requirements.txt")
        return generate_report(results)
    
    # Check environment
    check_environment()
    results["Environment"] = True
    
    # Test MongoDB connection
    ok, mongo_client = check_mongodb_connection()
    results["MongoDB Connection"] = ok
    
    if not ok:
        return generate_report(results)
    
    # Run additional tests with active connection
    results["Collection Access"] = test_collection_access(mongo_client)
    results["Session Management"] = test_session_management(mongo_client)
    results["Connection Pool"] = test_connection_pool()
    results["URI Masking"] = test_uri_masking(mongo_client)
    
    # Cleanup
    mongo_client.disconnect()
    print_success("Disconnected from MongoDB")
    
    return generate_report(results)

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nVerification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nFatal error during verification: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
