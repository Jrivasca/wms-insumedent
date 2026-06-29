"""Audit log documents are plain dicts written by audit_service.

Schema (collection ``audit_logs``):
    tenant_id, user_id, action, entity_type, entity_id,
    before, after, metadata, ip, user_agent, created_at
"""
