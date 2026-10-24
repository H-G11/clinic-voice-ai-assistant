"""Render real recorded stdout/measurements and implementation-grounded SVG diagrams."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from showcase_svg import MUTED, TEAL, arrow, panel, save, text

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'docs/assets'


def execution(lines, count=None):
    body = text(32, 69, 'Recorded service execution / synthetic fixture / no speech or real MIS', 15, MUTED)
    body += panel(24, 88, 992, 344)
    for i, line in enumerate(lines[:count]):
        color = TEAL if ' ok ' in line or line.startswith('VERIFIED') else '#17263c'
        body += text(40, 116 + 26 * i, line, 13, color, family='monospace')
    return body + text(32, 462, 'Source: scripts/demo_local.py --trace · actual stdout, rendered as a report', 14, MUTED)


def diagrams():
    body = text(32, 70, 'Implemented local components; current execution evidence covers the service + mock only.', 15, MUTED)
    nodes = [(32, 108, 'Gradio UI', 'Text + microphone'), (280, 108, 'Speech input', 'faster-whisper / local'),
             (528, 108, 'Dialogue controller', 'Rules + validated intent'), (776, 108, 'BookingService', 'Consent + reservations'),
             (32, 282, 'Speech output', 'Piper / Windows SAPI'), (280, 282, 'Reply / uncertainty', 'Verified result or review'),
             (528, 282, 'SQLite', 'WAL + unique indexes'), (776, 282, 'Mock MIS', 'In-process API simulator')]
    for x, y, title, subtitle in nodes:
        body += panel(x, y, 224, 92) + text(x + 16, y + 35, title, 19, weight=700) + text(x + 16, y + 63, subtitle, 14, MUTED)
    for coordinates in ((256,154,278,154),(504,154,526,154),(752,154,774,154),(888,200,888,280),
                        (776,328,754,328),(280,328,258,328),(800,200,660,280),(144,282,144,202)):
        body += arrow(*coordinates)
    body += '<path d="M144 108 L144 90 L640 90 L640 106" fill="none" stroke="#0f766e" stroke-width="2" marker-end="url(#arrow)"/>'
    body += text(360, 87, 'typed text', 12, MUTED)
    body += '<path d="M1000 200 L1000 245 L392 245 L392 280" fill="none" stroke="#0f766e" stroke-width="2" marker-end="url(#arrow)"/>'
    body += text(32, 438, 'UI consent gate → service mutations → committed reservation → adapter → verified result', 16, TEAL)
    save(ASSETS/'architecture.svg','Local speech-driven appointment workflow','Implementation map of app.py, dialog, service, Store and local MIS; optional speech is not validated in this environment.',body)


def benchmark_table(report):
    body = text(32, 72, 'Actual local service timings · SQLite + in-process mock API · 30 runs after 3 warmups', 15, MUTED)
    body += panel(24, 94, 992, 280)
    body += text(48, 132, 'OPERATION', 14, MUTED, 700) + text(540,132,'MEDIAN',14,MUTED,700) + text(760,132,'P95',14,MUTED,700)
    for i, (label, key) in enumerate([('Create after reviewed summary','create_after_reviewed_summary'),('Reschedule, same external ID','confirmed_move'),('Cancel, verified result','confirmed_cancel'),('Read appointment status','status')]):
        row = report['operations'][key]
        y = 182 + 52*i
        body += text(48,y,label,18) + text(540,y,f"{row['median_ms']:.3f} ms",22,TEAL,700) + text(760,y,f"{row['p95_ms']:.3f} ms",20)
    body += text(32,414,'Not ASR, TTS, HTTP, end-to-end response time or a production capacity benchmark.',15,MUTED)
    body += text(32,445,f"Python {report['hardware']['python']} · {report['hardware']['logical_cpus']} logical CPUs · full hardware and raw samples in JSON",14,MUTED)
    save(ASSETS/'service-results.svg','Measured service behavior',report['scope'],body)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gif',action='store_true',help='Render recorded stdout as a non-real-time replay using rsvg-convert and ffmpeg')
    args=parser.parse_args()
    lines=(ASSETS/'service-trace.txt').read_text().splitlines()
    report=json.loads((ASSETS/'service-benchmark.json').read_text())
    save(ASSETS/'service-demo.svg','Executed appointment service demo','Verbatim output captured from scripts/demo_local.py --trace; not a screenshot of Gradio.',execution(lines))
    diagrams()
    benchmark_table(report)
    if args.gif:
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory)
            for i in range(1,len(lines)+1):
                source=temp/f'{i:02d}.svg'
                save(source,'Recorded execution / playback, not real time','Progressive reveal of captured stdout, not a live UI or timing reproduction.',execution(lines,i))
                subprocess.run(['rsvg-convert','-o',str(temp/f'{i:02d}.png'),str(source)],check=True)
            subprocess.run(['ffmpeg','-v','error','-y','-framerate','1','-start_number','1','-i',str(temp/'%02d.png'),
                            '-filter_complex','[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse',
                            '-loop','0',str(ASSETS/'service-replay.gif')],check=True)
    print('Generated execution report, measured result table and architecture; no interface screenshot was fabricated.')


if __name__ == '__main__':
    main()
