"""
Database module for Voice Agent
Handles MongoDB connection, CRUD operations, and schema validation.
"""

from .mongo_client import mongo_client, MongoDBClient, get_mongodb, lifespan_manager

__all__ = ["mongo_client", "MongoDBClient", "get_mongodb", "lifespan_manager"]
