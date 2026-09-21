"""Dagster orchestration of the daily pipeline (see ADR-002).

Kept in its own package behind the optional `orchestrator` extra: the pipeline
itself runs without Dagster, and nothing outside this package imports it.
"""
