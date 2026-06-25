"""Data layer for the standalone `hypogum db` service.

Only the lightweight abstract base class is re-exported here so that importing a
db interface (e.g. from the agent) does not pull in the service's heavy backend
(SQLAlchemy). Import the concrete impl from its submodule:

    from hypogum.db.relational.engine import SQLAlchemyDBStore
"""

from hypogum.db.relational.base import DBStore

__all__ = ["DBStore"]
