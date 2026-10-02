"""Clean nested creative strings without claiming to identify every name."""
import re
from typing import Any

_PATH_STOP = r"(?:[.,;!?:]\s|\s*\(?https?://)"
_LOCAL_FILE_PATH = re.compile(
    rf"(?<![A-Za-z0-9/:])/(?:(?:(?!{_PATH_STOP}|://)[^/\r\n<>\"])+/)+"
    rf"(?:(?!{_PATH_STOP}|://)[^/\r\n<>\"])+?\.[A-Za-z0-9]{{1,8}}(?=$|[\s),;!?])",
    re.IGNORECASE,
)
_LOCAL_PATH_START = re.compile(
    r"(?<![A-Za-z0-9/:])/(?:[^/\s<>\"']+/)+"
    r"|(?<![A-Za-z0-9/:])/(?:Users|Volumes|tmp|private|var|home|mnt|media|opt|Library)\b",
    re.IGNORECASE,
)
_RELATIVE_SEGMENT = re.compile(r"[^/\s<>\"']+")
_RELATIVE_START_BLOCKED = re.compile(r"[A-Za-z0-9/:.]", re.IGNORECASE)
_RELATIVE_START_ALLOWED = re.compile(r"[^A-Za-z0-9/:.]", re.IGNORECASE)
_RELATIVE_EXTENSION = re.compile(r"\.(?:jpe?g|png|webp|mp4|mov|txt|md)\b", re.IGNORECASE)
_IDENTITY_PACK_PATH = re.compile(r"\bidentity(?:[-_ ]context)?[-_ ]pack[/\\]", re.IGNORECASE)
_FILE_URI = re.compile(
    rf"\bfile://(?:(?!{_PATH_STOP})[^\r\n<>\"])+?\.[A-Za-z0-9]{{1,8}}(?=$|[\s),;!?])",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"\b(?:sk|hf|or)-[A-Za-z0-9_-]{12,}\b"
    r"|\b(?=[A-Za-z0-9_-]{16,}\b)(?=[A-Za-z0-9_-]*(?:secret|token|api[_-]?key|private[_-]?key|credential|password))[A-Za-z0-9_-]+\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(r"\b(?:api[_-]?key|secret|token|password|credential)\s*[:=]\s*[^\s,;]+", re.IGNORECASE)

_WINDOWS_FILE = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\)[^\r\n<>\"]*?\.[A-Za-z0-9]{1,8}(?=$|[\s),;!?])")
_WINDOWS_START = re.compile(r"\b[A-Za-z]:[\\/]|\\\\[^\s]+")


def _has_relative_file_path(text: str) -> bool:
    """Recognise the relative-file pattern without retrying overlapping prefixes."""
    previous_end = -2
    prefix = False
    for segment in _RELATIVE_SEGMENT.finditer(text):
        start, end = segment.span()
        # A prefix continues only across exactly one slash and a nonempty segment.
        prefix = prefix and start == previous_end + 1 and text[previous_end] == "/"
        if prefix and _RELATIVE_EXTENSION.search(text, start + 1, end):
            return True
        # The original lookbehind permits starts within a segment after a
        # non-ASCII character or punctuation. Keep its IGNORECASE behaviour.
        eligible = (start == 0 or not _RELATIVE_START_BLOCKED.fullmatch(text[start - 1])
                    or _RELATIVE_START_ALLOWED.search(text, start, end - 1) is not None)
        prefix = (prefix or eligible) and end < len(text) and text[end] == "/"
        previous_end = end
    return False


def clean(value: Any) -> Any:
    """Keep private paths and token-shaped strings out of public records."""
    if isinstance(value, str):
        value = _WINDOWS_FILE.sub("[local reference]", value)
        if _WINDOWS_START.search(value):
            raise ValueError("ambiguous local path: register reference files privately and use labels in public text")
        without_file_uris = _FILE_URI.sub("[local reference]", value)
        if re.search(r"\bfile://", without_file_uris, re.IGNORECASE):
            raise ValueError("ambiguous local path: register reference files privately and use labels in public text")
        without_files = _LOCAL_FILE_PATH.sub("[local reference]", without_file_uris)
        if (_LOCAL_PATH_START.search(without_files) or _has_relative_file_path(without_files)
                or _IDENTITY_PACK_PATH.search(without_files)):
            raise ValueError("ambiguous local path: register reference files privately and use labels in public text")
        return _SECRET.sub("[credential]", _SECRET_ASSIGNMENT.sub("[credential]", without_files))
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {clean(str(key)): clean(item) for key, item in value.items() if key != "path"}
    return value


