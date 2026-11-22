#!/usr/bin/env python3
"""Selectable FaceTime TTS renderer: MiniMax Speech 2.8 (Turbo/HD) -> macOS say.

The single exit-success contract is a fully decoded, validated AIFF file;
rendering always happens before dialing. No secret is passed via CLI, logged,
copied into a repository or included in error text. Only well-known MiniMax
HTTPS endpoints are permitted.
"""
import argparse
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

DIR=pathlib.Path(__file__).resolve().parent
import facetime_runtime as runtime
import facetime_usage as usage
CONFIG=runtime.tts_config_file(DIR/"tts-config.json")
SECRETS=runtime.minimax_key_file()
FFMPEG=runtime.executable("ffmpeg")
FFPROBE=runtime.executable("ffprobe")
MINIMAX_MODELS=frozenset(("speech-2.8-turbo","speech-2.8-hd"))
ENDPOINTS=frozenset((
    "https://api.minimax.io/v1/t2a_v2",
    "https://api.minimaxi.com/v1/t2a_v2"
))

class TTSError(Exception):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def config_load(path):
    try:
        data=json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise TTSError("config_unavailable") from exc
    if not isinstance(data,dict):
        raise TTSError("config_not_object")
    if data.get("provider") not in ("minimax","macos"):
        raise TTSError("config_provider_invalid")
    if data.get("fallback_provider")!="macos":
        raise TTSError("config_fallback_invalid")
    mm=data.get("minimax")
    mac=data.get("macos")
    if not isinstance(mm,dict) or not isinstance(mac,dict):
        raise TTSError("config_sections_missing")
    if mm.get("endpoint") not in ENDPOINTS:
        raise TTSError("config_endpoint_not_allowlisted")
    if mm.get("model") not in MINIMAX_MODELS:
        raise TTSError("config_minimax_model_invalid")
    if not isinstance(mm.get("voice_id"),str) or not re.fullmatch(r"[A-Za-z0-9_() \-]{3,100}",mm["voice_id"]):
        raise TTSError("config_voice_invalid")
    if mm.get("language_boost") not in ("German","English","auto"):
        raise TTSError("config_language_invalid")
    for name,low,high in (("speed",.5,2.0),("volume",.01,10.0),("request_timeout_seconds",1,30)):
        if not isinstance(mm.get(name),(float,int)) or not low<=mm[name]<=high:
            raise TTSError("config_"+name+"_invalid")
    if not isinstance(mm.get("pitch"),int) or not -12<=mm["pitch"]<=12:
        raise TTSError("config_pitch_invalid")
    # Optional per-model/provider limits; absence means no model-specific
    # override beyond the renderer's global transport guard.
    caps=mm.get("max_characters_by_model",{})
    if not isinstance(caps,dict) or any(
            k not in MINIMAX_MODELS or type(v) is not int or not 1<=v<=10000
            for k,v in caps.items()):
        raise TTSError("config_max_characters_by_model_invalid")
    mcap=mac.get("max_characters")
    if mcap is not None and (type(mcap) is not int or not 1<=mcap<=100000):
        raise TTSError("config_macos_max_characters_invalid")
    if not isinstance(mac.get("voice"),str) or not re.fullmatch(r"[a-zA-Z0-9 _-]{2,30}",mac["voice"]):
        raise TTSError("config_macos_voice_invalid")
    if not isinstance(mac.get("rate"),int) or not 80<=mac["rate"]<=400:
        raise TTSError("config_macos_rate_invalid")
    return data

def read_key():
    source=pathlib.Path(os.environ.get("FACETIME_MINIMAX_KEY_FILE",str(SECRETS)))
    try:
        st=os.stat(source,follow_symlinks=False)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid()
                or (st.st_mode&0o077)!=0):
            raise TTSError("key_file_unsafe_permissions")
        value=json.loads(source.read_text(encoding="utf-8")).get("minimaxApiKey")
        if not isinstance(value,str) or len(value)<30 or "\n" in value or "\r" in value:
            raise TTSError("key_missing")
        return value
    except TTSError:raise
    except (OSError,ValueError,TypeError) as exc:
        raise TTSError("key_unavailable") from exc

def request_minimax(text,settings,target_mp3):
    """Capture an API attempt when issued, even if FaceTime is never dialed.

    The provider's reported usage_characters is recorded separately from the
    literal input length. Missing billing metadata stays unknown, not zero.
    """
    started=time.monotonic()
    sent=False
    result="local_error"
    charged=None
    try:
        payload={
            "model":settings["model"],"text":text,
            "stream":False,"output_format":"hex",
            "language_boost":settings["language_boost"],
            "voice_setting":{
                "voice_id":settings["voice_id"],"speed":settings["speed"],
                "vol":settings["volume"],"pitch":settings["pitch"]
            },
            "audio_setting":{
                "sample_rate":32000,"bitrate":128000,
                "format":"mp3","channel":1
            }
        }
        request=urllib.request.Request(
            settings["endpoint"],
            data=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8"),
            headers={"Authorization":"Bearer "+read_key(),"Content-Type":"application/json",
                     "Accept":"application/json"},
            method="POST")
        try:
            sent=True
            with urllib.request.urlopen(request,timeout=settings["request_timeout_seconds"]) as response:
                if response.status!=200:
                    result="api_error"
                    raise TTSError("http_"+str(response.status))
                raw=response.read(16_000_001)
                if len(raw)>16_000_000:
                    result="invalid_audio"
                    raise TTSError("response_too_large")
        except urllib.error.HTTPError as exc:
            result="api_error"
            raise TTSError("http_"+str(exc.code)) from None
        except (urllib.error.URLError,TimeoutError,OSError) as exc:
            result="network_error"
            raise TTSError("network_"+type(exc).__name__) from None
        result="invalid_audio"
        try:
            data=json.loads(raw)
            extra=data.get("extra_info") or {}
            count=extra.get("usage_characters")
            if type(count) is int and 0<=count<=10000000:
                charged=count
            status=(data.get("base_resp") or {}).get("status_code")
            if status!=0:
                result="api_error"
                raise TTSError("api_status_"+str(status)[:12])
            if (data.get("data") or {}).get("status") not in (None,2):
                raise TTSError("audio_not_complete")
            audio_hex=(data.get("data") or {}).get("audio")
            if not isinstance(audio_hex,str) or len(audio_hex)<2000:
                raise TTSError("audio_missing")
            audio=bytes.fromhex(audio_hex)
            if len(audio)<1000 or not (audio.startswith(b"ID3") or
                    (audio[0]==255 and (audio[1]&0xe0)==0xe0)):
                raise TTSError("audio_invalid_mp3")
        except (ValueError,TypeError,AttributeError,IndexError) as exc:
            raise TTSError("api_response_invalid") from exc
        target_mp3.write_bytes(audio)
        os.chmod(target_mp3,0o600)
        result="generated"
        return len(audio)
    finally:
        if sent:
            usage.record(
                "minimax_request",operation_id=usage.operation_id(),
                endpoint=settings["endpoint"].split("/")[2],model=settings["model"],
                input_characters=len(text),usage_characters=charged,
                result=result,elapsed_seconds=time.monotonic()-started)


def safe_run(args,seconds,code):
    try:
        result=subprocess.run(args,capture_output=True,timeout=seconds)
    except (subprocess.TimeoutExpired,OSError) as exc:
        raise TTSError(code+"_timeout_or_unavailable") from exc
    if result.returncode:
        raise TTSError(code+"_failed")
    return result

def verify_aiff(path):
    if not path.is_file() or path.stat().st_size<1500:
        raise TTSError("aiff_empty")
    with path.open("rb") as handle:
        if handle.read(4)!=b"FORM":
            raise TTSError("aiff_invalid_header")
    result=safe_run([FFPROBE,"-v","error","-show_entries",
                     "format=duration","-of","default=noprint_wrappers=1:nokey=1",
                     str(path)],8,"ffprobe")
    try:
        duration=float(result.stdout.decode().strip())
    except ValueError as exc:
        raise TTSError("aiff_invalid_duration") from exc
    if not .15<=duration<=1200:
        raise TTSError("aiff_duration_out_of_range")
    return round(duration,3)

def render_macos(text,mac,path):
    safe_run(["/usr/bin/say","-v",mac["voice"],"-r",str(mac["rate"]),
              "-o",str(path),"--",text],45,"macos_say")
    os.chmod(path,0o600)
    return verify_aiff(path)

def max_text_characters(config, selected):
    """Effective limit. None in macOS config means no model-specific cap."""
    if selected == "minimax":
        model=config["minimax"]["model"]
        model_cap=5000 if model=="speech-2.8-hd" else 10000
        return min(model_cap,config["minimax"].get("max_characters_by_model",{}).get(model,model_cap))
    if selected == "macos":
        return config["macos"].get("max_characters") or 100000
    raise TTSError("provider_invalid")

def validate_text_length(text,config,selected):
    if not isinstance(text,str) or not text.strip():
        raise TTSError("text_invalid")
    if len(text)>max_text_characters(config,selected):
        raise TTSError("text_exceeds_provider_model_limit")

def render(text,config,out,provider=None,speed=None,volume=None,pitch=None,voice=None):
    selected=provider or config["provider"]
    if selected not in ("macos","minimax"):
        raise TTSError("provider_invalid")
    validate_text_length(text,config,selected)
    mm=dict(config["minimax"])
    for name,val in (("speed",speed),("volume",volume),("pitch",pitch),("voice_id",voice)):
        if val is not None:mm[name]=val
    # Validate all explicit and inherited parameters before issuing a request.
    check=dict(config,provider=selected,minimax=mm)
    config_load_data(check)
    target=pathlib.Path(out)
    if target.suffix.lower() not in (".aiff",".aif"):
        raise TTSError("output_must_be_aiff")
    if target.is_symlink():
        raise TTSError("output_symlink_forbidden")
    target.parent.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix="facetime-tts-",dir=str(target.parent)) as private:
        folder=pathlib.Path(private)
        tmp_aiff=folder/"rendered.aiff"
        fallback_reason=None
        result_provider=selected
        if selected=="minimax":
            try:
                tmp_mp3=folder/"minimax.mp3"
                request_minimax(text,mm,tmp_mp3)
                safe_run([FFMPEG,"-hide_banner","-nostdin","-loglevel","error",
                          "-y","-i",str(tmp_mp3),"-ar","48000","-ac","2",
                          "-c:a","pcm_s16be","-f","aiff",str(tmp_aiff)],20,"audio_convert")
                duration=verify_aiff(tmp_aiff)
            except TTSError as error:
                fallback_reason=error.code
                tmp_aiff.unlink(missing_ok=True)
                result_provider="macos"
                validate_text_length(text,config,"macos")
                duration=render_macos(text,config["macos"],tmp_aiff)
        else:
            duration=render_macos(text,config["macos"],tmp_aiff)
        os.replace(tmp_aiff,target)
        os.chmod(target,0o600)
    elapsed=round(time.monotonic()-start,3)
    usage.record(
        "tts_render",operation_id=usage.operation_id(),
        requested_provider=selected,provider=result_provider,
        endpoint=mm["endpoint"].split("/")[2] if result_provider=="minimax" else "local_macos",
        model=mm["model"] if result_provider=="minimax" else "macos",
        input_characters=len(text),audio_seconds=duration,
        elapsed_seconds=elapsed,fallback=bool(fallback_reason))
    return {
        "provider":result_provider,"requested":selected,"fallback":bool(fallback_reason),
        "fallback_reason":fallback_reason or "none",
        "audio_seconds":duration,"elapsed_seconds":elapsed,
        "size_bytes":target.stat().st_size,
        "model":mm["model"] if result_provider=="minimax" else "macos",
        "voice":mm["voice_id"] if result_provider=="minimax" else config["macos"]["voice"],
        "speed":mm["speed"] if result_provider=="minimax" else config["macos"]["rate"]
    }

def config_load_data(data):
    # Use the same validation for effective in-memory CLI overrides.
    # These are safe to place in a private temporary JSON file.
    with tempfile.TemporaryDirectory(prefix="facetime-tts-settings-") as folder:
        p=pathlib.Path(folder)/"config.json"
        p.write_text(json.dumps(data))
        return config_load(p)

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default=os.environ.get("FACETIME_TTS_CONFIG",str(CONFIG)))
    parser.add_argument("--provider",choices=("minimax","macos"))
    parser.add_argument("--speed",type=float)
    parser.add_argument("--volume",type=float)
    parser.add_argument("--pitch",type=int)
    parser.add_argument("--voice")
    parser.add_argument("--output",required=True)
    parser.add_argument("--text",required=True)
    args=parser.parse_args(argv)
    try:
        config=config_load(args.config)
        result=render(args.text,config,args.output,args.provider,args.speed,
                      args.volume,args.pitch,args.voice)
    except TTSError as exc:
        print(json.dumps({"ok":False,"error":exc.code}),flush=True)
        return 75
    print(json.dumps({"ok":True,**result},sort_keys=True),flush=True)
    return 0

if __name__=="__main__":
    os.umask(0o077)
    sys.exit(main())
