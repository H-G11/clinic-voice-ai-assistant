"""Produce a real synthetic Russian WAV for manual playback; no audio upload."""
import sys
import json
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.voice import synthesize

result=synthesize('Здравствуйте! Это локальная регистратура. Тестовая запись подтверждена только в демонстрации.')
if not result.path:
    print(json.dumps({'status':'FAIL','message':result.message},ensure_ascii=True));sys.exit(1)
with wave.open(result.path,'rb') as wav:
    print(json.dumps({'status':'PASS','wav':result.path,'seconds':result.seconds,
                      'audio_seconds':wav.getnframes()/wav.getframerate(),'rate':wav.getframerate(),'channels':wav.getnchannels(),
                      'manual_playback':'NOT RUN'},ensure_ascii=True))
