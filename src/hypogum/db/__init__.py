"""Data layer for the standalone `hypogum db` service.

Only the lightweight abstract base classes are re-exported here so that importing a
db interface (e.g. from the agent) does not pull in the service's heavy backends
(SQLAlchemy / ChromaDB). Import the concrete impls from their submodules:

    from hypogum.db.relational.engine import SQLAlchemyDBStore
    from hypogum.db.vector.chroma import ChromaVectorStore
"""

from hypogum.db.relational.base import DBStore
from hypogum.db.vector.base import VectorStore

__all__ = ["DBStore", "VectorStore"]
