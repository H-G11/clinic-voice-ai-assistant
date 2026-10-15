"""One-time local import; legacy demo.sqlite3 is never opened."""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.store import Store
from core.schedule import import_clinic_excel
root = Path(__file__).resolve().parents[1]
result = import_clinic_excel(Store(root/'data/clinic_demo.sqlite3'), next((root/'data/source').glob('*.xlsx')))
print(json.dumps(result))
