# Phase 1.1: MongoDB Connection & Configuration - Implementation Guide

## Overview

Phase 1.1 establishes the MongoDB connection layer with robust connection pooling, session management, and production-ready configuration. This is the foundation for all database operations in the Voice Agent system.

## What Was Implemented

### 1. **MongoDBClient Class** (`backend/database/mongo_client.py`)

A production-grade MongoDB client with:

#### Key Features:
- **Connection Pooling**: Configurable min/max pool sizes for optimal resource usage
- **Auto-Connect**: Lazy initialization on first access
- **Session Management**: Context manager for transactional support
- **Error Handling**: Comprehensive exception handling with meaningful logging
- **URI Masking**: Sensitive credentials hidden in logs for security
- **Connection Status**: Real-time connection health monitoring
- **Dependency Injection**: FastAPI-ready integration

#### Core Methods:

```python
# Initialize and connect
client = MongoDBClient()
client.connect()

# Get a collection
collection = client.get_collection("users")

# Use sessions for transactions
with client.session() as session:
    # Perform operations
    pass

# Check connection status
status = client.get_connection_status()

# Cleanup
client.disconnect()
```

### 2. **Global Singleton Instance**

```python
from backend.database import mongo_client

# Use the global instance anywhere in your app
users_collection = mongo_client.get_collection("users")
```

### 3. **FastAPI Integration**

Dependency injection and lifespan management:

```python
from fastapi import FastAPI, Depends
from backend.database import get_mongodb, lifespan_manager

# Using lifespan (FastAPI 0.93+)
app = FastAPI(lifespan=lifespan_manager)

# Or manual startup/shutdown
@app.on_event("startup")
async def startup():
    from backend.database import mongo_client
    mongo_client.connect()

@app.on_event("shutdown")
async def shutdown():
    from backend.database import mongo_client
    mongo_client.disconnect()
```

### 4. **Environment Configuration**

`.env.example` contains all configurable parameters:

```bash
# MongoDB Connection
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=voice_agent
MONGODB_TIMEOUT=5000

# Connection Pool
MONGODB_MAX_POOL_SIZE=50
MONGODB_MIN_POOL_SIZE=10

# SSL/TLS (for production)
MONGODB_SSL=false
```

### 5. **Comprehensive Test Suite**

`tests/test_mongo_client.py` includes:
- Unit tests for configuration
- URI masking validation
- Session management tests
- Connection status tests
- Integration tests (with real MongoDB)

## Setup Instructions

### Prerequisites

- Python 3.9+
- MongoDB 4.4+ running locally or accessible via network
- git (for cloning)

### Step 1: Install Dependencies

```bash
# Navigate to project directory
cd c:\Users\manik.bhardwaj\.vscode\voice\reactapp

# Create virtual environment (recommended)
python -m venv venv
source venv/Scripts/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit .env with your MongoDB settings
# For local development, defaults should work fine
```

### Step 3: Verify MongoDB Connection

Create a simple test script:

```python
# test_connection.py
from backend.database import mongo_client

try:
    mongo_client.connect()
    status = mongo_client.get_connection_status()
    print("✓ Connection Status:", status)
    
    # Try to access a collection
    collection = mongo_client.get_collection("_test")
    print("✓ Collection access successful")
    
    mongo_client.disconnect()
    print("✓ Disconnected")
    
except Exception as e:
    print("✗ Connection failed:", e)
```

Run it:
```bash
python test_connection.py
```

### Step 4: Run Tests

```bash
# Run unit tests (no MongoDB required)
pytest tests/test_mongo_client.py -v

# Run all tests including integration tests
pytest tests/ -v -m integration

# With coverage
pytest tests/ --cov=backend/database --cov-report=html
```

## Configuration Options

### Connection Settings

| Environment Variable | Default | Description |
|---|---|---|
| `MONGODB_URI` | `mongodb://localhost:27017` | Connection string |
| `MONGODB_DB` | `voice_agent` | Database name |
| `MONGODB_TIMEOUT` | `5000` | Server selection timeout (ms) |
| `MONGODB_SSL` | `false` | Use SSL/TLS (enable for production) |

### Connection Pool

| Environment Variable | Default | Description |
|---|---|---|
| `MONGODB_MAX_POOL_SIZE` | `50` | Maximum connections |
| `MONGODB_MIN_POOL_SIZE` | `10` | Minimum connections |

### Recommended Settings by Environment

#### Development
```bash
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=voice_agent
MONGODB_MAX_POOL_SIZE=10
MONGODB_MIN_POOL_SIZE=2
MONGODB_SSL=false
```

#### Production
```bash
MONGODB_URI=mongodb+srv://user:password@cluster.mongodb.net
MONGODB_DB=voice_agent_prod
MONGODB_MAX_POOL_SIZE=100
MONGODB_MIN_POOL_SIZE=20
MONGODB_SSL=true
```

## Usage Examples

### Basic Collection Operations

```python
from backend.database import mongo_client

# Connect
mongo_client.connect()

# Get collection
users = mongo_client.get_collection("users")

# Insert document
user_doc = {
    "user_id": "user_123",
    "name": "John Doe",
    "email": "john@example.com"
}
result = users.insert_one(user_doc)
print(f"Inserted: {result.inserted_id}")

# Find document
user = users.find_one({"user_id": "user_123"})
print(f"Found: {user}")
```

### Using Sessions for Transactions

```python
from backend.database import mongo_client

mongo_client.connect()

# Within a transaction session
with mongo_client.session() as session:
    users = mongo_client.get_collection("users")
    
    # All operations within this context share the session
    users.insert_one({"name": "Alice"}, session=session)
    users.insert_one({"name": "Bob"}, session=session)
    # Automatic cleanup on exit

mongo_client.disconnect()
```

### FastAPI Integration Example

```python
from fastapi import FastAPI, Depends, HTTPException
from backend.database import mongo_client, get_mongodb
from pymongo import MongoClient

app = FastAPI()

@app.on_event("startup")
async def startup():
    mongo_client.connect()

@app.on_event("shutdown")
async def shutdown():
    mongo_client.disconnect()

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    try:
        collection = mongo_client.get_collection("users")
        user = collection.find_one({"user_id": user_id})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"user": user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Connection Status Monitoring

Check connection health:

```python
from backend.database import mongo_client

status = mongo_client.get_connection_status()
print(status)

# Output when connected:
# {
#   'status': 'connected',
#   'db': 'voice_agent',
#   'version': '5.0.0',
#   'ok': 1
# }
```

## Troubleshooting

### Connection Refused

**Problem**: `ConnectionError: Failed to connect to MongoDB`

**Solutions**:
1. Check MongoDB is running: `mongosh` or `mongo`
2. Verify URI in `.env`: Should match your MongoDB setup
3. Check firewall/network if using remote MongoDB

### Connection Timeout

**Problem**: `ServerSelectionTimeoutError`

**Solutions**:
1. Increase `MONGODB_TIMEOUT` in `.env` (default 5000ms)
2. Check network connectivity to MongoDB server
3. Verify MongoDB credentials if using authentication

### Pool Size Issues

**Problem**: Too many connections or connection exhaustion

**Solutions**:
1. Ensure `disconnect()` is called in shutdown handlers
2. Reduce `MONGODB_MAX_POOL_SIZE` if memory-constrained
3. Check application logs for connection leaks

## Next Steps

With Phase 1.1 complete, you're ready for:

1. **Phase 1.2**: Pydantic Schema Validation - Define user and query models
2. **Phase 1.3**: CRUD Operations Helper - Build reusable database operations
3. **Phase 1.4**: Index Strategy - Optimize query performance

## Additional Resources

- [PyMongo Documentation](https://pymongo.readthedocs.io/)
- [MongoDB Connection String Reference](https://docs.mongodb.com/manual/reference/connection-string/)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [MongoDB Best Practices](https://docs.mongodb.com/manual/administration/server-side-optimization/)

## File Structure

```
backend/
├── __init__.py
└── database/
    ├── __init__.py
    └── mongo_client.py          # MongoDBClient implementation
tests/
├── __init__.py
└── test_mongo_client.py         # Comprehensive test suite
.env.example                     # Environment template
requirements.txt                 # Python dependencies
```

## Summary

Phase 1.1 provides:
✅ Production-ready MongoDB client with connection pooling
✅ Comprehensive error handling and logging
✅ FastAPI integration support
✅ Security features (credential masking)
✅ Full test coverage with both unit and integration tests
✅ Environment-based configuration
✅ Session management for transactions

The implementation is ready for integration with Phase 1.2 (Schema Validation).
