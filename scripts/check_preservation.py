"""Compare original user records to a snapshot without printing patient data."""
import argparse,json,sqlite3
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TABLES=('doctors','slots','calendar','unavailability','bookings','mock_mis','api_clients',
        'api_visits','api_escalations','synthetic_patients','patient_permissions')


def read(path):
    return closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backup',required=True,help='Snapshot directory within this project')
    parser.add_argument('--output',default='docs/preservation-evidence.json')
    args=parser.parse_args()
    backup=(ROOT/args.backup).resolve()
    if not backup.is_relative_to((ROOT/'backups').resolve()):parser.error('Expected project backups directory')
    report={}
    for name in ('demo.sqlite3','clinic_demo.sqlite3'):
        with read(backup/name) as old,read(ROOT/'data'/name) as current:
            before={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            after={r[0] for r in current.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            tables={}
            for table in TABLES:
                if table not in before:continue  # additive new tables are allowed
                previous=old.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                rows=current.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() if table in after else None
                tables[table]={'rows_before':len(previous),'rows_after':len(rows) if rows is not None else None,
                               'unchanged':previous==rows}
                if rows is not None and len(rows)==len(previous) and previous!=rows:
                    names=[d[0] for d in old.execute(f'SELECT * FROM {table} LIMIT 0').description]
                    tables[table]['changed_columns']=sorted({names[i] for a,b in zip(previous,rows) for i in range(min(len(a),len(b))) if a[i]!=b[i]})
                    if 'status' in names:
                        index=names.index('status')
                        tables[table]['status_transitions']=[{'before':a[index],'after':b[index]} for a,b in zip(previous,rows) if a[index]!=b[index]]
            report[name]=tables
    output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT):parser.error('Report must remain within project')
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not all(t['unchanged'] for tables in report.values() for t in tables.values()):
        raise SystemExit('Existing data differs; review locally. No restoration was attempted.')


if __name__=='__main__':main()
