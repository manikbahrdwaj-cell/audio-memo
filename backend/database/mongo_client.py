"""
MongoDB Connection & Configuration Module
Handles connection pooling, session management, and database initialization.
"""

from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure
import os
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class MongoDBClient:
    """
    Singleton MongoDB client with connection pooling.
    Manages database connections and session handling.
    """
    
    def __init__(self):
        """Initialize MongoDB client configuration"""
        self.uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = os.environ.get("MONGODB_DB", "voice_agent")
        self.client = None
        self.db = None
        self._connection_timeout = int(os.environ.get("MONGODB_TIMEOUT", "5000"))
        self._max_pool_size = int(os.environ.get("MONGODB_MAX_POOL_SIZE", "50"))
        self._min_pool_size = int(os.environ.get("MONGODB_MIN_POOL_SIZE", "10"))
    
    def connect(self):
        """
        Establish connection to MongoDB with connection pooling.
        
        Connection options:
        - serverSelectionTimeoutMS: Timeout for server selection
        - connectTimeoutMS: Timeout for initial connection
        - maxPoolSize: Maximum connections in pool
        - minPoolSize: Minimum connections in pool
        - retryWrites: Automatic retry on transient errors
        
        Raises:
            ConnectionError: If unable to connect to MongoDB
        """
        try:
            self.client = MongoClient(
                self.uri,
                serverSelectionTimeoutMS=self._connection_timeout,
                connectTimeoutMS=self._connection_timeout,
                maxPoolSize=self._max_pool_size,
                minPoolSize=self._min_pool_size,
                retryWrites=True,
                retryReads=True,
                # SSL/TLS (disabled for local development, enable in production)
                ssl=os.environ.get("MONGODB_SSL", "false").lower() == "true",
            )
            
            # Test connection
            self.client.admin.command("ping")
            
            # Select database
            self.db = self.client[self.db_name]
            
            logger.info(f"✓ MongoDB connected successfully to '{self.db_name}'")
            logger.info(f"  URI: {self._mask_uri(self.uri)}")
            logger.info(f"  Pool size: {self._min_pool_size}-{self._max_pool_size}")
            
        except ServerSelectionTimeoutError as e:
            logger.error(f"Failed to select MongoDB server: {str(e)}")
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")
        except OperationFailure as e:
            logger.error(f"MongoDB operation failed during startup: {str(e)}")
            raise ConnectionError(f"MongoDB operation failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {str(e)}")
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")
    
    def get_collection(self, collection_name: str):
        """
        Get a MongoDB collection handle.
        Auto-connects if not already connected.
        
        Args:
            collection_name (str): Name of the collection
            
        Returns:
            pymongo.collection.Collection: Collection handle
        """
        if self.db is None:
            self.connect()
        return self.db[collection_name]
    
    @contextmanager
    def session(self):
        """
        Context manager for MongoDB sessions.
        Useful for transaction support and session cleanup.
        
        Example:
            with mongo_client.session() as session:
                # Perform operations within session
                collection = self.db['users']
                collection.insert_one({...}, session=session)
        
        Yields:
            pymongo.client_session.ClientSession: MongoDB session
        """
        if self.client is None:
            self.connect()
        
        session = self.client.start_session()
        try:
            logger.debug(f"Session created: {session.session_id}")
            yield session
        finally:
            session.end_session()
            logger.debug(f"Session ended: {session.session_id}")
    
    def disconnect(self):
        """
        Close MongoDB connection and clean up resources.
        Should be called during application shutdown.
        """
        if self.client:
            self.client.close()
            self.db = None
            logger.info("✓ MongoDB disconnected")
    
    def get_database(self):
        """
        Get the database handle.
        Auto-connects if not already connected.
        
        Returns:
            pymongo.database.Database: Database handle
        """
        if self.db is None:
            self.connect()
        return self.db
    
    def get_connection_status(self) -> dict:
        """
        Get current connection status and statistics.
        
        Returns:
            dict: Connection status information
        """
        if self.client is None:
            return {"status": "disconnected", "db": self.db_name}
        
        try:
            # Ping to test connection
            self.client.admin.command("ping")
            
            # Get server info
            server_info = self.client.server_info()
            
            return {
                "status": "connected",
                "db": self.db_name,
                "version": server_info.get("version", "unknown"),
                "ok": server_info.get("ok", False)
            }
        except Exception as e:
            return {
                "status": "error",
                "db": self.db_name,
                "error": str(e)
            }
    
    @staticmethod
    def _mask_uri(uri: str) -> str:
        """
        Mask sensitive information in MongoDB URI for logging.
        
        Args:
            uri (str): MongoDB connection URI
            
        Returns:
            str: Masked URI with credentials hidden
        """
        import re
        # Match and hide credentials in format: mongodb://user:pass@host
        masked = re.sub(
            r'(mongodb(?:\+srv)?://)[^:]*:[^@]*@',
            r'\1***:***@',
            uri
        )
        return masked


# Global singleton instance
mongo_client = MongoDBClient()


# Dependency injection for FastAPI
async def get_mongodb() -> MongoClient:
    """
    FastAPI dependency for MongoDB client.
    
    Usage in route:
        from pymongo import MongoClient
        @app.get("/data")
        async def get_data(db: MongoClient = Depends(get_mongodb)):
            collection = db['users']
            ...
    
    Returns:
        MongoClient: MongoDB client instance
    """
    if mongo_client.client is None:
        mongo_client.connect()
    return mongo_client.client


# Lifespan context manager for FastAPI
async def lifespan_manager():
    """
    Context manager for application lifespan events.
    
    Usage in FastAPI:
        from contextlib import asynccontextmanager
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            mg.connect()
            yield
            # Shutdown
            mg.disconnect()
        
        app = FastAPI(lifespan=lifespan)
    """
    # Startup
    mongo_client.connect()
    yield
    # Shutdown
    mongo_client.disconnect()
