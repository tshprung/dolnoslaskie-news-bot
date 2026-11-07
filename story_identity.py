"""Publisher identifiers that remain stable when an outlet rewrites its URL slug."""
import re
from urllib.parse import parse_qs, urlsplit


def story_identity(url):
    parsed = urlsplit(str(url or '').strip())
    host = (parsed.hostname or '').lower().removeprefix('www.')
    patterns = {
        'portalsamorzadowy.pl': r',([0-9]+)\.html$',
        'radiowroclaw.pl': r'/articles/view/([0-9]+)(?:/|$)',
        'jelonka.com': r'-([0-9]+)/?$',
    }
    pattern = patterns.get(host)
    if pattern and (match := re.search(pattern, parsed.path)):
        return f'{host}:article:{match[1]}'
    # WordPress GUIDs may use ?p=; never collapse different post IDs to '/'.
    post = parse_qs(parsed.query).get('p', [])
    if post and post[0].isdigit():
        return f'{host}:post:{post[0]}'
    return host + parsed.path.rstrip('/')
