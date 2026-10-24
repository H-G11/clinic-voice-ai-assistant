"""Check whitespace formatting without rewriting historical documents or binaries."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {'.py', '.md', '.txt', '.toml', '.yml', '.yaml', '.bat'}


def main() -> int:
    files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    errors = []
    for name in sorted(set(files.decode().split('\0')) - {''}):
        path = ROOT / name
        if path.suffix not in SUFFIXES or name.startswith('docs/provenance/') or not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        if text and not text.endswith('\n'):
            errors.append(f'{name}: missing final newline')
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                errors.append(f'{name}:{number}: trailing whitespace')
    print('\n'.join(errors) if errors else 'Whitespace formatting: PASS')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
