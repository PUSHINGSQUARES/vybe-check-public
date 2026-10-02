"""Explicit allowlisted exports of one agreed prompt version."""
from .privacy import clean

def agreed_export(session, target='image', version=None):
    if session['brief_status'] != 'agreed':
        raise ValueError('an agreed brief is required')
    if not isinstance(target, str) or target not in {'image', 'video'}:
        raise ValueError('target must be image or video')
    if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
        raise ValueError('unknown agreed version')
    versions = session[target + '_versions']
    chosen = next((v for v in versions if v['version'] == version), None) if version else (versions[-1] if versions else None)
    if chosen is None:
        raise ValueError('unknown agreed version')
    result = {'schema_version': 1, 'target': target, 'version': chosen['version'],
            'prompt': chosen['prompt'], 'shots': chosen.get('shots', []),
            'settings': chosen.get('settings', {}), 'locks': chosen.get('locks', []),
            'source_image_version': chosen.get('source_image_version'),
            **({'mode': chosen['mode'], 'duration': chosen['duration']} if target == 'video' else {})}
    return clean(result)
