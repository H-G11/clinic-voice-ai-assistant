"""Validate showcase paths, accessible safe SVGs and provenance-bound recorded outputs."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SVG='{http://www.w3.org/2000/svg}'


def main():
    assets=list((ROOT/'docs/assets').glob('*.svg'))
    for path in assets:
        tree=ET.parse(path).getroot()
        if tree.tag!=SVG+'svg' or not tree.get('viewBox') or tree.find(SVG+'title') is None or tree.find(SVG+'desc') is None:
            raise ValueError(f'Missing accessible SVG metadata: {path.name}')
        for element in tree.iter():
            if element.tag.rsplit('}',1)[-1] in ('script','foreignObject','image'):
                raise ValueError(f'Executable/external SVG content is prohibited: {path.name}')
            for key,value in element.attrib.items():
                if key.lower().startswith('on') or (key.rsplit('}',1)[-1] in ('href','src') and not value.startswith('#')):
                    raise ValueError(f'External/executable SVG attribute: {path.name}')
        if path.stat().st_size>100_000:
            raise ValueError(f'Unexpected oversized SVG: {path.name}')
    trace=ROOT/'docs/assets/service-trace.txt'
    if trace.exists():
        rendered=[element.text for element in ET.parse(ROOT/'docs/assets/service-demo.svg').getroot().iter(SVG+'text')]
        if not all(line in rendered for line in trace.read_text().splitlines()):
            raise ValueError('Execution SVG diverged from captured stdout')
        report=json.loads((ROOT/'docs/assets/service-benchmark.json').read_text())
        text=(ROOT/'docs/assets/service-results.svg').read_text()
        for key in ('create_after_reviewed_summary','confirmed_move','confirmed_cancel','status'):
            for field in ('median_ms','p95_ms'):
                if f"{report['operations'][key][field]:.3f} ms" not in text:
                    raise ValueError('Timing SVG diverged from measurement JSON')
        gif=ROOT/'docs/assets/service-replay.gif'
        if not gif.read_bytes().startswith((b'GIF87a',b'GIF89a')) or gif.stat().st_size>1_000_000:
            raise ValueError('Replay is not a compact GIF')
    archived=ROOT/'docs/demo/validation-predictions.jpg'
    if archived.exists() and archived.read_bytes()!=(ROOT/'results/trash_detector-4/val_batch0_pred.jpg').read_bytes():
        raise ValueError('Archive copy changed; source prediction provenance no longer matches')
    print(f'PASS: {len(assets)} safe accessible SVGs; recorded asset provenance')


if __name__=='__main__':
    main()
