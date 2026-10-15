"""Local structural inspection; never prints caller or patient CSV rows."""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import json
import sqlite3
from contextlib import closing
from openpyxl import load_workbook

root = Path(__file__).resolve().parents[1]
source = root / 'data/source'
backup = sorted((root/'backups').glob('no-api-baseline-*'))[-1]
if not (backup/'demo.sqlite3').exists():
    with closing(sqlite3.connect(f'file:{root / "data/demo.sqlite3"}?mode=ro', uri=True)) as src, closing(sqlite3.connect(backup/'demo.sqlite3')) as dst:
        src.backup(dst)
with ZipFile(next(source.glob('*.docx'))) as archive:
    xml = ET.fromstring(archive.read('word/document.xml'))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in xml.findall('.//w:p', ns)]
(source/'regulation-extracted.txt').write_text('\n'.join(paragraphs), encoding='utf-8')
wb = load_workbook(next(source.glob('*.xlsx')), read_only=True, data_only=True)
for ws in wb:
    print(ws.title, ws.max_row, ws.max_column)
    for row in list(ws.iter_rows(min_row=1, max_row=4, values_only=True)):
        print(json.dumps(row[:22] if ws.max_column < 30 else row[:10], ensure_ascii=False, default=str))
wb.close()
print('Regulation extracted locally; SQLite snapshot saved.')
