"""
Phase 5 ML layer.

Layering rule (same as app/analytics): everything here except `service.py`
is pure -- plain Python/numpy/sklearn over plain data, no FastAPI, no
SQLAlchemy sessions -- so it can be unit-tested without a database and
Phase 8's agent can wrap it as tools. `service.py` is the only module that
touches the DB.
"""
