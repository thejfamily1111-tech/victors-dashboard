"""Independent Beta RPCs; cannot overwrite QQQ telemetry or access a broker."""
import json
import re
import ssl
from urllib import request, error
from .snapshot import MAX_BYTES, SnapshotError, validate


class LinkError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def rpc(url, key, token, *, snapshot=None):
    if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', url or ''):
        raise LinkError('Set TELEMETRY_URL to the existing HTTPS Supabase project URL.')
    if not isinstance(key, str) or not key.startswith('sb_publishable_'):
        raise LinkError('Use the existing Supabase publishable key.')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise LinkError('Beta telemetry access token is missing or invalid.')
    operation = 'vt_beta_write' if snapshot is not None else 'vt_beta_read'
    body = dict(p_token=token)
    if snapshot is not None:
        body['p_snapshot'] = validate(snapshot, secrets=(key, token))
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_BYTES + 1000:
        raise LinkError('Beta report exceeds transport size limit')
    req = request.Request(url + '/rest/v1/rpc/' + operation, data=encoded, method='POST',
                          headers={'apikey': key, 'Content-Type': 'application/json',
                                   'User-Agent': 'VictorBetaTelemetry/1'})
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        opener = request.build_opener(NoRedirect(), request.HTTPSHandler(context=context))
        with opener.open(req, timeout=15) as response:
            data = response.read(MAX_BYTES + 1001)
        if len(data) > MAX_BYTES + 1000:
            raise LinkError('Beta response exceeds transport size limit')
        result = json.loads(data)
        if snapshot is not None:
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise LinkError('Beta telemetry did not acknowledge the update')
            return result
        if result is None:
            return None
        if not isinstance(result, dict):
            raise LinkError('Invalid Beta telemetry envelope')
        return validate(result.get('snapshot'))
    except error.HTTPError as exc:
        raise LinkError(f'Beta telemetry returned HTTP {exc.code}. Check the Beta SQL setup and access settings.', exc.code) from None
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        if isinstance(exc, LinkError):
            raise
        raise LinkError('Beta telemetry unavailable or its report is invalid.') from None
