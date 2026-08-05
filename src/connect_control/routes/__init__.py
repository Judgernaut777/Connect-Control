"""The four R7 UI surfaces (S1–S4), server-rendered.

S1 (work requests) is the ONE mutation surface, and it mutates only through
``connect_governance.work_requests.create_work_request`` imported in-process
against the governance DB — the documented Option-B exception
(docs/ARCHITECTURE.md), never raw SQL. Every other surface is read-only.
"""
