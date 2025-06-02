#!/usr/bin/env python3
"""Test Redis connection with various configurations"""

import redis
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_redis_connection():
    """Test different Redis connection configurations"""
    
    # Get credentials from environment
    redis_host = "redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com"
    redis_port = 12696
    redis_password = os.getenv("REDIS_PW", "BHMbnJHyf&9!4TT")
    redis_username = os.getenv("REDIS_USERNAME", "joe_ott")
    
    print(f"Testing Redis connection to {redis_host}:{redis_port}")
    print(f"Username: {redis_username}")
    print(f"Password: {'*' * len(redis_password) if redis_password else 'None'}")
    
    # Test 1: With username
    print("\n1. Testing with username and password...")
    try:
        r1 = redis.Redis(
            host=redis_host,
            port=redis_port,
            username=redis_username,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5
        )
        r1.ping()
        print("✅ SUCCESS: Connected with username and password")
        return r1
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 2: Without username (some Redis instances don't use username)
    print("\n2. Testing with password only (no username)...")
    try:
        r2 = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5
        )
        r2.ping()
        print("✅ SUCCESS: Connected with password only")
        return r2
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 3: Try default username
    print("\n3. Testing with 'default' username...")
    try:
        r3 = redis.Redis(
            host=redis_host,
            port=redis_port,
            username="default",
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5
        )
        r3.ping()
        print("✅ SUCCESS: Connected with 'default' username")
        return r3
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 4: Try with SSL
    print("\n4. Testing with SSL enabled...")
    try:
        r4 = redis.Redis(
            host=redis_host,
            port=redis_port,
            username=redis_username,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5,
            ssl=True,
            ssl_cert_reqs="none"
        )
        r4.ping()
        print("✅ SUCCESS: Connected with SSL")
        return r4
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    return None

if __name__ == "__main__":
    redis_client = test_redis_connection()
    
    if redis_client:
        print("\n✅ Redis connection successful!")
        print("Testing basic operations...")
        
        # Test set/get
        test_key = "test:connection"
        test_value = "Hello Redis!"
        
        redis_client.setex(test_key, 60, test_value)  # Expires in 60 seconds
        retrieved = redis_client.get(test_key)
        
        if retrieved == test_value:
            print(f"✅ Set/Get test passed: '{retrieved}'")
        else:
            print(f"❌ Set/Get test failed")
        
        # Clean up
        redis_client.delete(test_key)
        
        # Get server info
        try:
            info = redis_client.info("server")
            print(f"\nRedis Server Info:")
            print(f"- Version: {info.get('redis_version', 'Unknown')}")
            print(f"- Mode: {info.get('redis_mode', 'Unknown')}")
        except:
            print("\nCould not retrieve server info (may be restricted)")
    else:
        print("\n❌ All Redis connection attempts failed!")
        print("\nPlease check:")
        print("1. Redis Cloud credentials are correct")
        print("2. Redis Cloud instance is running")
        print("3. Network connectivity to Redis Cloud")