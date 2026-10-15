"""Optional local ASR (faster-whisper) and Windows SAPI TTS."""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import json
import wave
import time
import threading
import re
from dataclasses import dataclass,field
from pathlib import Path
from .metrics import timing

_model = None
_model_key = None
_asr_lock = threading.Lock()
_piper_voice = None
_piper_lock = threading.Lock()


@dataclass
class Transcription:
    text: str
    load_seconds: float
    asr_seconds: float
    device: str
    warning: str = ''
    model: str = ''
    beam_size: int = 1
    vad_filter: bool = True
    audio: dict = field(default_factory=dict)
    decode_seconds: float = 0.0
    needs_review: bool = False
    confidence: dict = field(default_factory=dict)


def prepare_audio(path):
    """Inspect source, decode/downmix/resample once to 16k mono. Never trim speech."""
    started=time.perf_counter()
    try:
        import av
        import numpy as np
        from faster_whisper.audio import decode_audio
        with av.open(path) as container:
            stream=next(s for s in container.streams if s.type=='audio')
            rate=stream.codec_context.sample_rate
            channels=stream.codec_context.channels
        samples=decode_audio(path,sampling_rate=16000)
        frame=320
        energies=np.array([np.sqrt(np.mean(samples[i:i+frame]**2)) for i in range(0,len(samples),frame)])
        speech=np.where(energies>.006)[0]
        metadata={'source_rate':rate,'source_channels':channels,'decoded_rate':16000,'decoded_channels':1,
                  'duration_seconds':len(samples)/16000,'peak':float(np.max(np.abs(samples))) if len(samples) else 0,
                  'rms':float(np.sqrt(np.mean(samples**2))) if len(samples) else 0,
                  'dc_offset':float(np.mean(samples)) if len(samples) else 0,
                  'near_start':bool(len(speech) and speech[0]<4),'near_end':bool(len(speech) and speech[-1]>=len(energies)-4),
                  'clipped_fraction':float(np.mean(np.abs(samples)>=.995)) if len(samples) else 0}
        return samples,metadata,time.perf_counter()-started
    except (ImportError,OSError,ValueError,StopIteration):
        return path,{},time.perf_counter()-started


@dataclass
class SpeechResult:
    path: str | None
    message: str
    seconds: float = 0.0


def _powershell(script: str, timeout: int = 25) -> str:
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        check=True, timeout=timeout, capture_output=True, creationflags=0x08000000,
    )
    return result.stdout.decode('utf-8-sig').strip()


def voice_diagnostics() -> dict:
    """List local SAPI COM voices; never download or install voices."""
    if os.name != 'nt':
        return {'voices': [], 'message': 'Windows SAPI доступен только в Windows.'}
    script = """
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
    $v = New-Object -ComObject SAPI.SpVoice
    $items = @($v.GetVoices() | ForEach-Object {
        @{name=$_.GetDescription(); language=$_.GetAttribute('Language')}
    })
    ConvertTo-Json -InputObject $items -Compress
    """
    try:
        voices = json.loads(_powershell(script, 10))
        return {'voices': voices, 'message': 'Локальные голоса: ' + ', '.join(v['name'] for v in voices)}
    except (subprocess.SubprocessError, OSError, ValueError):
        return {'voices': [], 'message': 'SAPI недоступен. Проверьте установленные речевые голоса Windows; текст работает.'}


def transcribe_detailed(path: str, *, model_name=None,device=None,beam_size=None,vad_filter=None,legacy_decode=False,initial_prompt=None) -> Transcription:
    global _model,_model_key
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Распознавание не установлено. Запустите install_voice_windows.bat") from exc
    with _asr_lock:
        started = time.perf_counter()
        device = device or os.environ.get('ASR_DEVICE', 'cpu')
        model_name = model_name or os.environ.get('ASR_MODEL', 'base')
        warning = ''
        if device not in ('cpu', 'cuda'):
            raise RuntimeError('ASR_DEVICE должен быть cpu или cuda.')
        beam = int(beam_size if beam_size is not None else os.getenv('ASR_BEAM_SIZE', '1'))
        vad = vad_filter if vad_filter is not None else os.getenv('ASR_VAD','1')=='1'
        if not 1 <= beam <= 5:
            raise RuntimeError('ASR_BEAM_SIZE должен быть от 1 до 5.')
        def load(target, cached=False):
            return WhisperModel(model_name, device=target,
                                compute_type='float16' if target == 'cuda' else 'int8',
                                local_files_only=cached or os.getenv('ASR_LOCAL_ONLY', '0') == '1')
        key=(str(model_name),device,os.getenv('ASR_LOCAL_ONLY','0'))
        if _model is None or _model_key!=key:
            _model=None  # release the old model before loading another one
            try:
                _model = load(device)
            except Exception:
                if device != 'cuda':
                    raise RuntimeError('Не удалось загрузить локальную ASR-модель. Проверьте кэш и настройки.') from None
                _model = load('cpu', cached=True)
                device = 'cpu'
                warning = 'CUDA недоступна; используется CPU int8.'
            _model_key=key
        remembered=getattr(_model,'_clinic_device',None)
        if isinstance(remembered,str) and remembered in ('cpu','cuda'):
            device=remembered
        load_seconds = time.perf_counter() - started
        audio_input,audio_info,decode_seconds=prepare_audio(path)
        if audio_info and (audio_info['duration_seconds']<.15 or audio_info['peak']<.0001):
            return Transcription('',load_seconds,0,device,'Запись слишком короткая или почти без звука.',str(model_name),beam,vad,audio_info,decode_seconds,True)
        started = time.perf_counter()
        confidence={}
        def decode():
            options=dict(language='ru',beam_size=beam,best_of=1,vad_filter=vad,
                condition_on_previous_text=False,
                initial_prompt='Регистратура. Фамилия, имя, отчество. Дата рождения, врач, дата и время приёма.')
            if legacy_decode:
                options['initial_prompt']='Регистратура. Запись к терапевту, неврологу, хирургу. Дата и время приёма.'
            elif vad:
                options['vad_parameters']={'speech_pad_ms':500,'min_silence_duration_ms':700}
            if initial_prompt is not None:options['initial_prompt']=initial_prompt
            segments, _ = _model.transcribe(
                audio_input, **options,
            )
            segments=list(segments)
            logs=[x.avg_logprob for x in segments if isinstance(getattr(x,'avg_logprob',None),(int,float))]
            silence=[x.no_speech_prob for x in segments if isinstance(getattr(x,'no_speech_prob',None),(int,float))]
            confidence.update(avg_logprob=sum(logs)/len(logs) if logs else None,max_no_speech_prob=max(silence) if silence else None)
            return ' '.join(x.text.strip() for x in segments).strip()
        try:
            text = decode()
        except Exception:
            if device != 'cuda':
                raise RuntimeError('ASR не смогла обработать аудио. Проверьте запись и повторите короткую фразу.') from None
            _model = load('cpu', cached=True)
            device = 'cpu'
            warning = 'Ошибка CUDA; используется CPU int8.'
            text = decode()
        _model._clinic_device = 'cpu' if warning else device
        seconds=time.perf_counter()-started
        timing('asr',device=_model._clinic_device,load_seconds=load_seconds,seconds=seconds,success=True)
        if audio_info.get('near_start') or audio_info.get('near_end'):
            warning+=' Речь близко к краю записи: проверьте начало и окончание; это признак риска, не доказательство обрезания.'
        review=(not text or (confidence.get('avg_logprob') is not None and confidence['avg_logprob'] < -1)
                or (confidence.get('max_no_speech_prob') is not None and confidence['max_no_speech_prob']>.6))
        return Transcription(text, load_seconds, seconds, _model._clinic_device, warning,str(model_name),beam,vad,audio_info,decode_seconds,review,confidence)


def transcribe(path: str) -> str:
    return transcribe_detailed(path).text


def synthesize(text: str) -> SpeechResult:
    """Create a validated PCM WAV using System.Speech, then local SAPI COM."""
    started = time.perf_counter()
    if os.name != "nt" or os.getenv("DISABLE_TTS", "0") == "1":
        return SpeechResult(None, 'Озвучивание отключено или Windows SAPI недоступен.')
    audio_dir = Path(__file__).resolve().parent.parent / 'data' / 'tts'
    audio_dir.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='response_', suffix='.wav', dir=audio_dir)
    os.close(fd)
    temp_path = Path(filename)
    engine=os.getenv('TTS_ENGINE','auto').casefold()
    model=Path(os.getenv('PIPER_MODEL',str(audio_dir.parent/'models/ru_RU-irina-medium.onnx')))
    if engine in ('auto','piper') and model.is_file():
        try:
            from piper import PiperVoice
            global _piper_voice
            with _piper_lock:
                if _piper_voice is None:
                    _piper_voice=PiperVoice.load(str(model),use_cuda=False)
                with wave.open(str(temp_path),'wb') as wav:
                    _piper_voice.synthesize_wav(text,wav)
            with wave.open(str(temp_path),'rb') as wav:
                if wav.getnframes()<1 or wav.getcomptype()!='NONE': raise ValueError('Invalid WAV')
            elapsed=time.perf_counter()-started
            timing('tts',engine='piper',seconds=elapsed,success=True)
            return SpeechResult(str(temp_path),f'Piper CPU: WAV готов ({elapsed:.1f} с). Нажмите ▶ для воспроизведения.',elapsed)
        except (ImportError,OSError,ValueError,RuntimeError,wave.Error):
            if engine=='piper':
                temp_path.unlink(missing_ok=True)
                timing('tts',engine='piper',seconds=time.perf_counter()-started,success=False)
                return SpeechResult(None,'Piper не создал WAV. Проверьте модель и конфигурацию; текстовый режим работает.')
    elif engine=='piper':
        temp_path.unlink(missing_ok=True)
        return SpeechResult(None,'Русская модель Piper не найдена локально. Загрузка при ответе не выполняется.')
    safe_path = str(temp_path).replace("'", "''")
    # The spoken text is injected as BASE64 to avoid PowerShell quoting issues.
    speech = base64.b64encode(text.encode("utf-8")).decode("ascii")
    preamble = f"""
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
    $text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{speech}'))
    """
    system_speech = preamble + f"""
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $voice = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'ru-*' }} | Select-Object -First 1
    if (-not $voice) {{ $s.Dispose(); throw 'No Russian voice' }}
    $s.SelectVoice($voice.VoiceInfo.Name)
    try {{ $s.SetOutputToWaveFile('{safe_path}'); $s.Speak($text); Write-Output $voice.VoiceInfo.Name }} finally {{ $s.Dispose() }}
    """
    sapi_com = preamble + f"""
    $v = New-Object -ComObject SAPI.SpVoice
    $voices = $v.GetVoices()
    $ru = $null
    foreach ($token in $voices) {{
        if ($token.GetAttribute('Language') -match '(^|;)0?419(;|$)') {{ $ru = $token; break }}
    }}
    if (-not $ru) {{ throw 'No Russian voice' }}
    $v.Voice = $ru
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Format.Type = 22
    try {{
        $stream.Open('{safe_path}', 3, $false)
        $v.AudioOutputStream = $stream
        [void]$v.Speak($text, 0)
        Write-Output $ru.GetDescription()
    }} finally {{ $stream.Close() }}
    """
    failures = []
    for engine, script in [('System.Speech', system_speech), ('SAPI COM', sapi_com)]:
        try:
            voice = _powershell(script)
            with wave.open(str(temp_path), 'rb') as wav:
                if wav.getnframes() < 1 or wav.getcomptype() != 'NONE':
                    raise ValueError('Empty or non-PCM WAV')
            elapsed = time.perf_counter() - started
            timing('tts',engine=engine,seconds=elapsed,success=True)
            return SpeechResult(str(temp_path), f'{engine}: {voice}. WAV готов ({elapsed:.1f} с). Если тишина, нажмите ▶ в плеере.', elapsed)
        except (subprocess.SubprocessError, OSError, ValueError, EOFError, wave.Error) as exc:
            # Only stable error identifiers, never raw scripts, speech or paths.
            raw = getattr(exc, 'stderr', b'') or b''
            code = re.search(rb'0x[0-9A-Fa-f]{8}|NullReferenceException', raw)
            detail = code.group().decode('ascii') if code else type(exc).__name__
            failures.append(f'{engine}: {detail}')
            continue
    temp_path.unlink(missing_ok=True)
    timing('tts',engine='sapi',seconds=time.perf_counter()-started,success=False)
    return SpeechResult(None, 'Не удалось создать речь. ' + '; '.join(failures) + '. Проверьте русский голос Windows и нажмите «Проверить голос». Текстовый сценарий доступен.', time.perf_counter() - started)


def speak(text: str) -> str | None:
    """Compatibility wrapper; UI uses synthesize() to display diagnostics."""
    return synthesize(text).path
