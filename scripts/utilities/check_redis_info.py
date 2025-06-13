#!/usr/bin/env python3
"""Check Redis server configuration and available databases."""

import redis
from scripts.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_USERNAME

def check_redis_info():
    """Check Redis server information."""
    print("Redis Server Information")
    print("=" * 50)
    
    # Connect to default database
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=0,
        password=REDIS_PASSWORD,
        username=REDIS_USERNAME,
        decode_responses=True
    )
    
    try:
        # Get server info
        info = client.info('server')
        print(f"Redis Version: {info.get('redis_version', 'Unknown')}")
        print(f"Mode: {info.get('redis_mode', 'Unknown')}")
        
        # Get config
        try:
            databases = client.config_get('databases')
            if databases:
                print(f"Number of databases: {databases.get('databases', 'Unknown')}")
            else:
                print("Unable to get database count (CONFIG command may be disabled)")
        except Exception as e:
            print(f"CONFIG GET failed: {e}")
            print("(This is common in Redis Cloud)")
        
        # Try to access different databases
        print("\nTesting database access:")
        for db_num in range(16):  # Try first 16 databases
            try:
                test_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=db_num,
                    password=REDIS_PASSWORD,
                    username=REDIS_USERNAME
                )
                test_client.ping()
                print(f"✅ DB {db_num}: Accessible")
            except Exception as e:
                print(f"❌ DB {db_num}: {str(e)[:50]}...")
                break
        
        # Check keyspace info
        print("\nKeyspace Information:")
        keyspace = client.info('keyspace')
        if keyspace:
            for key, value in keyspace.items():
                if key.startswith('db'):
                    print(f"{key}: {value}")
        else:
            print("No keyspace information available")
            
    except Exception as e:
        print(f"Error connecting to Redis: {e}")


if __name__ == "__main__":
    check_redis_info()