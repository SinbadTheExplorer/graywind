"""Long-lived ChatterboxVC process. RUNS UNDER PYTHON 3.12, NOT 3.14.

ChatterboxVC needs torch, which lives in bullion-live-map's .venv-narration
(py3.12); Panda3D needs py3.14. The two cannot share a process, so voice
conversion happens here, behind a pipe.

This process stays alive for the whole MAVIS session on purpose. Model load is
~15s and embedding the reference clip ~1s; paying that once at startup is the
difference between a ~12-15s reply and a ~30s one. Anything that restarts this
per request has broken the design.

**stdout is reserved for the protocol and nothing else.** torch, chatterbox and
their dependencies print progress bars and warnings on import and during
inference. A single stray line on stdout would be read by the client as a
response and desynchronise every reply after it. So the real stdout is
duplicated to a private handle before anything else is imported, and `sys.stdout`
is then pointed at stderr -- any library that prints lands harmlessly in the
client's stderr tail, which is surfaced in error messages.

Protocol: one JSON object per line, both directions.
  in :  {"id": 1, "op": "convert", "input": "/tmp/a.wav", "output": "/tmp/b.wav",
         "gain": 6.1}                          (gain optional: omit to normalise)
  in :  {"id": 2, "op": "ping"}
  in :  {"op": "shutdown"}
  out:  {"ready": true, "device": "mps", "calibration": [[1, 2.1], [4, 4.0]]}
                                              (once, after load + prewarm)
  out:  {"id": 1, "ok": true, "seconds": 9.2, "gain": 6.1,
         "audio_seconds": 6.4, "cold": false}
  out:  {"id": 1, "ok": false, "error": "..."}
"""
import json
import os
import sys
import time

# Peak level converted speech is scaled to. Just under full scale to leave
# headroom for playback resampling without clipping.
TARGET_PEAK = 0.89
# A shared gain is never allowed to push a louder chunk past this.
CLIP_PEAK = 0.99

# How much of the reference clip ChatterboxVC re-reads on every call, and how
# many flow-matching steps it takes. Both are latency levers found 2026-09-28:
# the model prepends the reference prompt's mel to every conversion, so the
# stock 10s prompt made even a two-word clip cost ~6s -- a fixed cost that
# chunked answers pay once per chunk. The speaker embedding still comes from
# the full reference; only the in-context prompt is shortened. PROMPT_START is
# where in the (first 10s of the) reference that prompt window begins.
PROMPT_SECONDS = float(os.environ.get("MAVIS_VC_PROMPT_SECONDS", "5"))
PROMPT_START = float(os.environ.get("MAVIS_VC_PROMPT_START", "5"))
CFM_STEPS = int(os.environ.get("MAVIS_VC_STEPS", "10"))
# S3 speech tokens per second; the prompt mel runs at twice this.
TOKENS_PER_SECOND = 25
# Inputs are padded with silence up to the next of these lengths, and the
# output cut back to the real length. PyTorch on MPS compiles and KEEPS a graph
# for every input shape it sees, and no two answer chunks are the same length:
# unbucketed, the worker grew ~180MB per conversion (2.3GB -> 4.3GB over 12
# calls, 2026-09-28) and paid the compile on every call. Measured with 1s
# buckets, memory then only grew on a bucket's first use. Geometric steps cap
# it at a handful of shapes while keeping padding small for the short first
# chunk, which is the one on the latency path.
BUCKETS = (1, 2, 3, 4, 6, 8, 12, 16)

# Claim stdout before any noisy import can write to it.
_PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
sys.stdout = sys.stderr

import torch  # noqa: E402
import torchaudio  # noqa: E402
import librosa  # noqa: E402
import numpy as np  # noqa: E402
from chatterbox.models.s3tokenizer import S3_SR  # noqa: E402
from chatterbox.vc import ChatterboxVC  # noqa: E402


def _emit(obj):
    _PROTOCOL.write(json.dumps(obj) + "\n")
    _PROTOCOL.flush()


def _normalise(wav, gain=None):
    """Bring the clip up to a consistent speaking level.

    ChatterboxVC's output tracks the reference clip's level, which for the
    actor sample lands around 0.135 peak -- roughly 17dB down, quiet enough
    that it could not be judged against room noise. Normalising per clip also
    keeps replies at an even volume instead of varying with whatever the
    scaffold happened to produce.

    Near-silence is left alone: scaling it to the target would only amplify
    the noise floor into an audible hiss.

    With `gain` given, that gain is applied instead of normalising, so the
    chunks of one answer stay at one level rather than each jumping to the
    same peak. Returns (wav, gain); the gain returned is the one to reuse,
    even when this chunk had to be turned down to stay under CLIP_PEAK.
    """
    peak = float(wav.abs().max())
    if peak < 1e-4:
        return wav, gain
    if gain is None:
        gain = TARGET_PEAK / peak
    return wav * min(gain, CLIP_PEAK / peak), gain


def _trim_prompt(ref_dict, start=PROMPT_START, seconds=PROMPT_SECONDS):
    """The reference conditioning with a shorter in-context prompt.

    `embedding` (the speaker identity) is left as computed from the full clip.
    """
    first = int(start * TOKENS_PER_SECOND)
    count = int(seconds * TOKENS_PER_SECOND)
    tokens = ref_dict["prompt_token"][:, first:first + count]
    if tokens.shape[1] == ref_dict["prompt_token"].shape[1]:
        return ref_dict
    trimmed = dict(ref_dict)
    trimmed["prompt_token"] = tokens
    trimmed["prompt_token_len"] = torch.tensor(
        [tokens.shape[1]], device=ref_dict["prompt_token_len"].device)
    trimmed["prompt_feat"] = ref_dict["prompt_feat"][:, 2 * first:2 * (first + count)]
    trimmed["prompt_feat_len"] = None
    return trimmed


def _bucket_samples(length, rate, buckets=BUCKETS):
    """The padded length for `length` samples: the next bucket, or past the
    last one, the next whole multiple of it."""
    for seconds in buckets:
        if length <= seconds * rate:
            return int(seconds * rate)
    step = int(buckets[-1] * rate)
    return -(-length // step) * step


def _pad_to_bucket(audio, rate):
    return np.pad(audio, (0, _bucket_samples(len(audio), rate) - len(audio)))


# Bucket lengths (in 16kHz samples) already compiled in this process.
_WARM = set()
# Every bucket is compiled before `ready` is sent. A cold bucket cost ~7s
# against ~2.5s warm for the same 2.5s clip, and a cold 6s bucket added ~10s
# to a later chunk -- a 10s gap mid-answer the planner could not foresee
# (2026-09-28). Paying it once at login is the cheaper place.
PREWARM_SECONDS = BUCKETS


def _generate(model, audio):
    """`ChatterboxVC.generate` on 16kHz samples, with CFM_STEPS and bucketing.

    Returns (wav, cold) -- cold when this call compiled a new bucket, so its
    time says nothing about steady-state speed.
    """
    with torch.inference_mode():
        real_seconds = len(audio) / S3_SR
        audio = _pad_to_bucket(audio, S3_SR)
        cold = len(audio) not in _WARM
        _WARM.add(len(audio))
        audio = torch.from_numpy(audio).float().to(model.device)[None, ]
        tokens, _ = model.s3gen.tokenizer(audio)
        wav, _ = model.s3gen.inference(speech_tokens=tokens, ref_dict=model.ref_dict,
                                       n_cfm_timesteps=CFM_STEPS)
        wav = wav.squeeze(0).detach().cpu().numpy()
        wav = wav[:int(round(real_seconds * model.sr))]
        wav = model.watermarker.apply_watermark(wav, sample_rate=model.sr)
    if model.device == "mps":
        # Release the allocator's cached activations between calls; what
        # stays resident is the compiled graph per bucket, which is the point.
        torch.mps.empty_cache()
    return torch.from_numpy(wav).unsqueeze(0), cold


def _convert(model, request):
    started = time.monotonic()
    audio, _ = librosa.load(request["input"], sr=S3_SR)
    wav, cold = _generate(model, audio)
    wav, gain = _normalise(wav, request.get("gain"))
    torchaudio.save(request["output"], wav, model.sr)
    return {"seconds": round(time.monotonic() - started, 2), "gain": gain,
            "audio_seconds": round(wav.shape[-1] / model.sr, 2), "cold": cold}


def _prewarm(model):
    """Compile every bucket, then time three of them warm.

    Silence has the same shapes as speech of the same length, which is all
    the compile depends on. The warm timings are (audio seconds, conversion
    seconds) pairs that seed the client's cost model, so the first answer is
    planned from how fast this machine is *now* -- Low Power Mode alone moves
    it about 3x.
    """
    for seconds in PREWARM_SECONDS:
        _generate(model, np.zeros(seconds * S3_SR, dtype=np.float32))
    pairs = []
    for seconds in (1, 4, 8):
        started = time.monotonic()
        _generate(model, np.zeros(seconds * S3_SR, dtype=np.float32))
        pairs.append([seconds, round(time.monotonic() - started, 2)])
    return pairs


def main():
    if len(sys.argv) < 2:
        _emit({"ready": False, "error": "usage: voice_worker.py <reference.wav>"})
        return 2

    reference = sys.argv[1]
    try:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model = ChatterboxVC.from_pretrained(device=device)
        model.set_target_voice(reference)
        model.ref_dict = _trim_prompt(model.ref_dict)
        calibration = _prewarm(model)
    except Exception as exc:  # noqa: BLE001 - report, never crash silently
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _emit({"ready": True, "device": device, "sample_rate": model.sr,
           "calibration": calibration})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue

        op = request.get("op")
        if op == "shutdown":
            return 0
        if op == "ping":
            _emit({"id": request.get("id"), "ok": True})
            continue
        if op != "convert":
            _emit({"id": request.get("id"), "ok": False,
                   "error": f"unknown op {op!r}"})
            continue

        try:
            _emit({"id": request.get("id"), "ok": True, **_convert(model, request)})
        except Exception as exc:  # noqa: BLE001 - one bad clip must not kill the worker
            _emit({"id": request.get("id"), "ok": False,
                   "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
