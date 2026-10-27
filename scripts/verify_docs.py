"""Validate public Markdown links and the supplied README illustration offline."""
from __future__ import annotations

import json
import re
import secrets
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md',
    'docs/USAGE.md', 'docs/DESIGN.md', 'docs/EVALUATION.md', 'docs/LIMITATIONS.md',
    'docs/REFERENCES.md', 'docs/STABILITY.md', 'docs/RELEASING.md',
    'docs/VALIDATION.md',
)


def verify():
    local_links = illustrations = 0
    for name in PUBLIC_DOCS:
        document = ROOT / name
        text = document.read_text(encoding='utf-8')
        for match in re.finditer(r'(!?)\[([^\]]*)\]\(([^)\s]+)\)', text):
            image, label, href = match.groups()
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                continue
            target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            if not target.is_relative_to(ROOT) or not target.is_file():
                raise ValueError(f'Missing local target in {name}: {href}')
            if parsed.fragment:
                headings = re.findall(r'^#+\s+(.+)$', target.read_text(encoding='utf-8'), re.MULTILINE)
                anchors = {re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
                           for heading in headings}
                if unquote(parsed.fragment) not in anchors:
                    raise ValueError(f'Missing heading in {name}: {href}')
            if image:
                if not label.strip():
                    raise ValueError(f'Illustration needs alt text in {name}')
                root = ET.parse(target).getroot()
                namespace = {'svg': 'http://www.w3.org/2000/svg'}
                if root.tag != '{http://www.w3.org/2000/svg}svg' or any(
                    root.find('svg:' + element, namespace) is None
                    for element in ('title', 'desc')
                ):
                    raise ValueError(f'Illustration needs SVG title and description: {href}')
                illustrations += 1
            local_links += 1
    if not illustrations:
        raise ValueError('README needs a useful illustrated asset')
    return {'status': 'PASS', 'local_links': local_links, 'illustrations': illustrations,
            'external_link_liveness': 'NOT RUN'}


def main():
    try:
        result = verify()
    except (OSError, ValueError, ET.ParseError) as error:
        sys.stderr.write(json.dumps({'status': 'FAIL', 'error': str(error),
                                     'request_id': secrets.token_hex(8)}) + '\n')
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
