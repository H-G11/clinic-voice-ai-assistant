"""Start and close this process's local demo; no GUI, external API or bookings."""
import os
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
import app

try:
    _, url, _ = app.demo.launch(server_name='127.0.0.1', share=False,
                                inbrowser=False, prevent_thread_lock=True, quiet=True)
    with urlopen(url, timeout=10) as response:
        assert response.status == 200
    with urlopen(url + 'config', timeout=10) as response:
        assert response.status == 200
    print('PASS: local HTTP UI and config; browser playback NOT RUN; no booking created')
finally:
    app.demo.close()
