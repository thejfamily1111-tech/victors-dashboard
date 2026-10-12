"""Explicit worker-only AI configuration; never return or print a credential."""
import os
from pathlib import Path
from dotenv import dotenv_values, load_dotenv


def configure_environment(root):
    path=Path(root)/'.env'
    values=dotenv_values(path,interpolate=False) if path.exists() else {}
    inherited=os.environ.get('OPENAI_API_KEY')
    stored=values.get('OPENAI_API_KEY')
    # The private local selector is written only by explicit configuration.
    source=values.get('OVERNIGHT_AI_CREDENTIAL_SOURCE') or os.environ.get('OVERNIGHT_AI_CREDENTIAL_SOURCE','auto')
    conflict=bool(inherited and stored and inherited!=stored)
    load_dotenv(path,override=False,interpolate=False)
    if source not in ('auto','dotenv','environment'):
        os.environ.pop('OPENAI_API_KEY',None)
        return dict(status='INVALID_SOURCE',credential_source='unresolved',inherited_conflict=conflict,model_configured=False)
    if source=='auto' and conflict:
        os.environ.pop('OPENAI_API_KEY',None)
        return dict(status='CONFLICT_REQUIRES_SELECTION',credential_source='unresolved',inherited_conflict=True,model_configured=False)
    if source=='auto':source='environment' if inherited else 'dotenv'
    key=inherited if source=='environment' else stored
    if key:os.environ['OPENAI_API_KEY']=key
    else:os.environ.pop('OPENAI_API_KEY',None)
    if source=='dotenv':
        model=values.get('OVERNIGHT_AI_MODEL') or values.get('SUPERVISOR_AI_MODEL')
        # Model selection follows the same explicit source; unrelated environment
        # settings (broker, GitHub, telemetry) retain their original precedence.
        os.environ.pop('OVERNIGHT_AI_MODEL',None)
        os.environ.pop('SUPERVISOR_AI_MODEL',None)
        if model:os.environ['OVERNIGHT_AI_MODEL']=model
    model=os.environ.get('OVERNIGHT_AI_MODEL') or os.environ.get('SUPERVISOR_AI_MODEL')
    return dict(status='CONFIGURED_NOT_AUTHENTICATED' if key and model else 'NOT_CONFIGURED',
                credential_source=source,inherited_conflict=conflict,model_configured=bool(model))


def compact_configuration(raw):
    raw=raw if isinstance(raw,dict) else {}
    statuses={'CONFIGURED_NOT_AUTHENTICATED','NOT_CONFIGURED','CONFLICT_REQUIRES_SELECTION','INVALID_SOURCE'}
    sources={'dotenv','environment','unresolved'}
    return dict(status=raw.get('status') if isinstance(raw.get('status'),str) and raw['status'] in statuses else 'NOT_CONFIGURED',
        credential_source=raw.get('credential_source') if isinstance(raw.get('credential_source'),str) and raw['credential_source'] in sources else 'unresolved',
        inherited_conflict=raw.get('inherited_conflict') is True,model_configured=raw.get('model_configured') is True)
