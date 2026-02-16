"""
Tests for MongoDB Connection & Configuration (Phase 1.1)
"""

import pytest
import os
from unittest.mock import patch, MagicMock
import logging

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


class TestMongoDBClient:
    """Test suite for MongoDBClient"""
    
    @pytest.fixture
    def client(self):
        """Create a fresh MongoDB client for each test"""
        from backend.database.mongo_client import MongoDBClient
        return MongoDBClient()
    
    def test_client_initialization(self, client):
        """Test client initializes with correct configuration"""
        assert client.uri == "mongodb://localhost:27017"
        assert client.db_name == "voice_agent"
        assert client.client is None
        assert client.db is None
    
    def test_uri_from_environment(self):
        """Test URI is read from environment variable"""
        test_uri = "mongodb+srv://user:pass@cluster.mongodb.net"
        with patch.dict(os.environ, {"MONGODB_URI": test_uri}):
            from backend.database.mongo_client import MongoDBClient
            client = MongoDBClient()
            assert client.uri == test_uri
    
    def test_db_name_from_environment(self):
        """Test database name is read from environment variable"""
        test_db = "custom_db"
        with patch.dict(os.environ, {"MONGODB_DB": test_db}):
            from backend.database.mongo_client import MongoDBClient
            client = MongoDBClient()
            assert client.db_name == test_db
    
    def test_pool_size_from_environment(self):
        """Test connection pool sizes are read from environment"""
        with patch.dict(os.environ, {
            "MONGODB_MAX_POOL_SIZE": "100",
            "MONGODB_MIN_POOL_SIZE": "20"
        }):
            from backend.database.mongo_client import MongoDBClient
            client = MongoDBClient()
            assert client._max_pool_size == 100
            assert client._min_pool_size == 20
    
    def test_timeout_from_environment(self):
        """Test connection timeout is read from environment"""
        with patch.dict(os.environ, {"MONGODB_TIMEOUT": "10000"}):
            from backend.database.mongo_client import MongoDBClient
            client = MongoDBClient()
            assert client._connection_timeout == 10000
    
    def test_mask_uri_hides_credentials(self):
        """Test that URI masking hides credentials in logs"""
        from backend.database.mongo_client import MongoDBClient
        
        uri = "mongodb://admin:secretpass123@localhost:27017"
        masked = MongoDBClient._mask_uri(uri)
        
        assert "admin" not in masked
        assert "secretpass123" not in masked
        assert "***:***@" in masked
    
    def test_mask_uri_with_srv(self):
        """Test URI masking with SRV connection strings"""
        from backend.database.mongo_client import MongoDBClient
        
        uri = "mongodb+srv://user:password@cluster.mongodb.net"
        masked = MongoDBClient._mask_uri(uri)
        
        assert "user" not in masked
        assert "password" not in masked
        assert "***:***@" in masked
    
    def test_get_collection_without_connection(self, client):
        """Test get_collection auto-connects if needed"""
        with patch.object(client, 'connect') as mock_connect:
            with patch.object(client, 'db', MagicMock()):
                client.get_collection("users")
                mock_connect.assert_called_once()
    
    def test_get_collection_with_existing_connection(self, client):
        """Test get_collection uses existing connection"""
        mock_db = MagicMock()
        client.db = mock_db
        
        result = client.get_collection("users")
        
        # Should call db['users']
        mock_db.__getitem__.assert_called_once_with("users")
    
    def test_session_context_manager(self, client):
        """Test session context manager creates and closes sessions"""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.start_session.return_value = mock_session
        client.client = mock_client
        
        with client.session() as session:
            assert session == mock_session
        
        mock_session.end_session.assert_called_once()
    
    def test_disconnect_closes_client(self, client):
        """Test disconnect closes the client"""
        mock_client = MagicMock()
        client.client = mock_client
        client.db = MagicMock()
        
        client.disconnect()
        
        mock_client.close.assert_called_once()
        assert client.db is None
    
    def test_get_database_auto_connects(self, client):
        """Test get_database auto-connects if needed"""
        with patch.object(client, 'connect') as mock_connect:
            with patch.object(client, 'db', MagicMock()):
                client.get_database()
                mock_connect.assert_called_once()


class TestMongoDBConnectionStatus:
    """Test connection status reporting"""
    
    def test_connection_status_disconnected(self):
        """Test status when disconnected"""
        from backend.database.mongo_client import MongoDBClient
        client = MongoDBClient()
        
        status = client.get_connection_status()
        
        assert status["status"] == "disconnected"
        assert status["db"] == "voice_agent"
    
    def test_connection_status_connected(self):
        """Test status when connected (mocked)"""
        from backend.database.mongo_client import MongoDBClient
        client = MongoDBClient()
        
        mock_client = MagicMock()
        mock_result = {"version": "5.0.0", "ok": 1}
        mock_client.server_info.return_value = mock_result
        client.client = mock_client
        client.db = MagicMock()
        
        status = client.get_connection_status()
        
        assert status["status"] == "connected"
        assert status["version"] == "5.0.0"
        assert status["db"] == "voice_agent"


class TestGlobalSingleton:
    """Test global singleton instance"""
    
    def test_global_mongo_client_exists(self):
        """Test that global mongo_client singleton is created"""
        from backend.database.mongo_client import mongo_client
        
        assert mongo_client is not None
        assert hasattr(mongo_client, 'connect')
        assert hasattr(mongo_client, 'disconnect')
        assert hasattr(mongo_client, 'get_collection')
    
    def test_global_mongo_client_is_singleton(self):
        """Test that mongo_client is a singleton"""
        from backend.database import mongo_client as mongo_1
        from backend.database.mongo_client import mongo_client as mongo_2
        
        assert mongo_1 is mongo_2


class TestDependencyInjection:
    """Test FastAPI dependency injection"""
    
    def test_get_mongodb_function_exists(self):
        """Test get_mongodb dependency function"""
        from backend.database.mongo_client import get_mongodb
        
        assert callable(get_mongodb)
    
    def test_lifespan_manager_exists(self):
        """Test lifespan manager for FastAPI integration"""
        from backend.database.mongo_client import lifespan_manager
        
        assert callable(lifespan_manager)


# Integration Tests (require actual MongoDB)
class TestMongoDBIntegration:
    """Integration tests with real MongoDB (optional)"""
    
    @pytest.mark.integration
    def test_connection_to_local_mongodb(self):
        """Test actual connection to local MongoDB"""
        from backend.database.mongo_client import MongoDBClient
        
        client = MongoDBClient()
        try:
            client.connect()
            assert client.client is not None
            assert client.db is not None
            
            status = client.get_connection_status()
            assert status["status"] == "connected"
            
            client.disconnect()
        except ConnectionError:
            pytest.skip("MongoDB not available on localhost:27017")
    
    @pytest.mark.integration
    def test_session_creation(self):
        """Test session creation with real MongoDB"""
        from backend.database.mongo_client import MongoDBClient
        
        client = MongoDBClient()
        try:
            client.connect()
            
            with client.session() as session:
                assert session is not None
                assert hasattr(session, 'session_id')
            
            client.disconnect()
        except ConnectionError:
            pytest.skip("MongoDB not available on localhost:27017")
    
    @pytest.mark.integration
    def test_collection_access(self):
        """Test getting collection from real MongoDB"""
        from backend.database.mongo_client import MongoDBClient
        
        client = MongoDBClient()
        try:
            client.connect()
            
            collection = client.get_collection("test_collection")
            assert collection is not None
            assert hasattr(collection, 'insert_one')
            assert hasattr(collection, 'find_one')
            
            client.disconnect()
        except ConnectionError:
            pytest.skip("MongoDB not available on localhost:27017")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
