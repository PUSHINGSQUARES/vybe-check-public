"""Copy explicitly inventoried, invented resources to a new user folder."""
from importlib.resources import files
import json
from pathlib import Path

EXAMPLE_FILES = ('ceramic-image.json', 'kite-image.json', 'kite-preserve.json',
                 'kite-evolve.json', 'kite-multishot.json', 'comfy-core.json',
                 'ceramic-reference.png', 'kite-reference.png')


def copy_examples(destination):
    target = Path(destination).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Example destination exists; choose a new folder')
    resources = files('vybe_check').joinpath('examples')
    members = list(resources.iterdir())
    if set(p.name for p in members) != set(EXAMPLE_FILES) or any(not p.is_file() for p in members):
        raise ValueError('Unknown or incomplete packaged example inventory')
    payloads = {}
    for name in EXAMPLE_FILES:
        raw = resources.joinpath(name).read_bytes()
        if name.endswith('.json'):
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Malformed packaged example')
        else:
            from io import BytesIO
            from PIL import Image
            try:
                with Image.open(BytesIO(raw)) as image:
                    if image.format != 'PNG' or image.size != (32, 24):
                        raise ValueError('Malformed programmatic reference')
                    image.verify()
            except (OSError, SyntaxError) as exc:
                raise ValueError('Malformed programmatic reference') from exc
        payloads[name] = raw
    target.mkdir(exist_ok=False)
    copied = []
    try:
        for name, raw in payloads.items():
            with (target / name).open('xb') as stream:
                stream.write(raw)
            copied.append(name)
    except OSError as exc:
        raise ValueError('Example copy incomplete; retained partial output for review') from exc
    return {'status': 'copied', 'destination': str(target.resolve()), 'files': copied}
