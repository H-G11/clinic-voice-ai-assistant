"""Read-only release gate. Findings contain locations, never secret values."""
from __future__ import annotations
import argparse,json,re,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIXTURES={'tests/asr_eval_20.csv','tests/asr_phrases.csv','tests/handoff_phrases.csv','tests/regulation_phrases.csv'}
PUBLIC_DATA={'data/analysis/report.py','data/analysis/summary.json','data/analysis/calls_by_hour.png','data/analysis/visit_statuses.png'}
PRIVATE_DIRS={'.venv','__pycache__','.pytest_cache','.git','.codex','.agents','.aws','.ssh','.idea','.vscode','backups','logs'}
DATA_DIRS={'source','private','models','asr_models','asr_eval','asr_benchmark','audio_cache','tts'}
SUFFIXES={'.xlsx','.xls','.xlsm','.docx','.db','.sqlite','.sqlite3','.wav','.mp3','.flac','.ogg','.webm','.m4a',
          '.mp4','.onnx','.pt','.pth','.bin','.gguf','.safetensors','.ckpt','.pem','.key','.p12','.pfx','.log','.jsonl',
          '.zip','.7z','.rar','.tar','.gz'}
PATTERNS={
    'github_token':r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})',
    'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'aws_key':r'AKIA[0-9A-Z]{16}',
    'api_key':r'sk-[A-Za-z0-9_-]{24,}',
    'credential_assignment':r'''(?im)\b(?:api_key|api_token|access_token|password|secret)\s*[:=]\s*["']([^"'\r\n]{8,})["']''',
    'email':r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'phone':r'(?<![\w.])(?:\+7|8)[ (\-]*\d{3}[ )\-]*\d{3}[ \-]*\d{2}[ \-]*\d{2}(?![\w.])',
}


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def forbidden(name):
    path=Path(name);parts=set(path.parts)
    return (bool(parts & PRIVATE_DIRS) or (path.parts[0]=='data' and name not in PUBLIC_DATA)
            or (path.name.startswith('.env') and name!='.env.example')
            or path.suffix.lower() in SUFFIXES or bool(re.search(r'\.(?:sqlite3?|db)(?:-|\.)',path.name))
            or (path.suffix.lower()=='.csv' and name not in FIXTURES)
            or path.name in ('.git-credentials','.netrc','.npmrc','.pypirc'))


def audit(staged=False):
    args=['ls-files','-z'] if staged else ['ls-files','--cached','--others','--exclude-standard','-z']
    names=sorted(set(n.decode('utf-8') for n in git(*args).split(b'\0') if n))
    files=[];findings=[]
    for name in names:
        path=ROOT/name
        if forbidden(name):findings.append({'file':name,'kind':'forbidden_path'});continue
        if path.is_symlink():findings.append({'file':name,'kind':'symlink'});continue
        blob=git('show',':'+name) if staged else path.read_bytes()
        files.append({'file':name,'bytes':len(blob)})
        if len(blob)>5*1024*1024:findings.append({'file':name,'kind':'oversized_file'})
        if blob.startswith(b'SQLite format 3'):findings.append({'file':name,'kind':'database_content'})
        if name in ('data/analysis/calls_by_hour.png','data/analysis/visit_statuses.png'):
            if not blob.startswith(b'\x89PNG\r\n\x1a\n'):findings.append({'file':name,'kind':'unexpected_binary'})
            continue  # reviewed aggregate-only plots; original source rows excluded
        try:text=blob.decode('utf-8-sig')
        except UnicodeDecodeError:
            findings.append({'file':name,'kind':'unexpected_binary'});continue
        for kind,pattern in PATTERNS.items():
            for match in re.finditer(pattern,text):
                value=match.group()
                if kind=='email' and value.lower().endswith(('.invalid','@users.noreply.github.com')):continue
                if kind=='credential_assignment' and match.group(1) in ('synthetic','local-demo-token'):continue
                findings.append({'file':name,'line':text.count('\n',0,match.start())+1,'kind':kind})
    return {'scope':'staged blobs' if staged else 'tracked and untracked candidates','files':files,
            'file_count':len(files),'total_bytes':sum(f['bytes'] for f in files),'findings':findings}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    report=audit(args.staged)
    output=ROOT/'data'/('github-staged-audit.json' if args.staged else 'github-candidate-audit.json')
    output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
    if report['findings']:raise SystemExit('STOP: review findings before committing/publishing; values intentionally hidden.')


if __name__=='__main__':main()
