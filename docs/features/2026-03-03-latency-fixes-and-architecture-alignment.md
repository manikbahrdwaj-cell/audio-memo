# Latency Fixes & Architecture Alignment

**Date**: 2026-03-03  
**Author**: Engineering  
**Status**: Planned

---

## Feature Summary

The current voice-agent pipeline has measurably higher end-to-end latency than the reference
full-duplex architecture described in the design spec. The root causes fall into two categories:

1. **Implementation bugs** — audio is silently dropped before it ever reaches the Realtime API
   (raw PCM16 bytes fed to `soundfile.read()` which expects a WAV container), the stream buffer
   threshold is 1 second instead of 100 ms, and the server VAD silence window is 1200 ms instead
   of 800 ms. These three issues alone make the agent unresponsive or add >1.3 s per turn.

2. **Missing architecture components** — the reference design uses a single full-duplex OpenAI
   Realtime session as both STT and response generator (streaming PCM16 audio back to the browser
   directly). The current system uses the Realtime API for STT only, then serially runs three
   LangGraph / LLM calls, then a blocking TTS HTTP call that waits for the full MP3 before sending
   anything to the client. The reference also has a `playbackTimeRef` audio scheduling cursor for
   gapless playback, a client-side VAD hook, a frontend silence-nudge system, and a `tts_done`
   feedback signal — none of which are implemented.

This document tracks every fix from quick patches (~1 min each) to the full-duplex refactor.

---

## Architecture

### Affected Layers

| Layer | Change |
|---|---|
| `frontend` | `audioRecorder.js` flush threshold, buffer size, binary frames, base64 helper, playback scheduler, VAD hook, `tts_done` message |
| `service` | `voice_agent.py` — remove time-based echo suppression, add `tts_done` handler |
| `agent` | `realtime_stt.py` — fix PCM16 ingestion, lower `silence_duration_ms`, module-level WS client |
| `agent/tts.py` | singleton client, streaming TTS |
| `api/routes` | `verification.py` — remove duplicate Whisper call, wire `tts_done` |
| `core/config.py` | expose `VAD_SILENCE_DURATION_MS` used by the STT session |

### New Files

None required by the incremental fixes. The full-duplex refactor (T13–T16) will add:

- `backend/app/agent/realtime_proxy.py` — full-duplex Realtime API proxy session
- `backend/app/api/routes/realtime.py` — `/ws/agent/{session_id}` endpoint
- `frontend/src/hooks/useVoiceAgent.js` — unified mic + playback + VAD hook

### Modified Files

| File | Why |
|---|---|
| `frontend/src/utils/audioRecorder.js` | Fix flush threshold, buffer size, binary send, fast base64 |
| `frontend/src/services/realtimeVerificationService.js` | Remove full-payload console.log, add `tts_done` send |
| `backend/app/agent/realtime_stt.py` | Fix audio ingestion, lower silence_duration_ms, singleton WS |
| `backend/app/agent/tts.py` | Singleton client, optional streaming TTS |
| `backend/app/services/voice_agent.py` | Remove time-estimated echo window, handle `tts_done` |
| `backend/app/api/routes/verification.py` | Remove redundant Whisper call, route `tts_done` |
| `backend/app/core/config.py` | Add `STT_SILENCE_DURATION_MS` setting |

---

## API Contract

### New WebSocket message (client → server)

```json
{ "type": "tts_done" }
```

Sent by the frontend immediately when `audio.onended` fires after agent TTS playback. The backend
clears `tts_playing` immediately on receipt, enabling the next user utterance without waiting for
the server-side sleep timer to expire.

### New WebSocket message (server → client) — streaming TTS (T09)

```json
{ "type": "agent_audio_chunk", "data": "<base64 raw PCM16 bytes>" }
{ "type": "agent_audio_done" }
```

Replaces the single `agent_audio` message (full MP3 blob) with a stream of small PCM16 frames so
the browser can begin playing the first frame ~100 ms into generation.

---

## Dependencies

No new packages. All changes use libraries already in `requirements.txt`:
`openai`, `numpy`, `websockets`, `fastapi`.

---

## Test Plan

1. **T01–T03 (audio path)**: Open browser devtools Network tab. After fix, first WebSocket binary
   frame from mic must appear within 150 ms of speech onset (previously >1 s).
2. **T04 (silence_duration_ms)**: Record a 1-sentence utterance and time from end-of-speech to
   `agent_thinking` event in browser. Must be ≤900 ms (previously ≥1300 ms).
3. **T05 (PCM16 format fix)**: Add a `logger.info` in `send_audio()` confirming non-empty bytes.
   Verify it fires on every audio chunk in agent mode (previously never fired).
4. **T06 (echo suppression)**: Send `tts_done` from browser; confirm `tts_playing=False` is set
   within 50 ms in server logs, not after the old `playback_seconds` sleep.
5. **T07 (TTS client)**: Instrument `synthesise_speech` and confirm the same `AsyncOpenAI` object
   is reused across calls (Python `id()` never changes after first call).
6. **T08 (duplicate Whisper)**: Verify no `[STT] Sending … bytes to Whisper` log line is emitted
   in agent mode when biometric verification completes.
7. **T09 (streaming TTS)**: Browser devtools → WS messages. First `agent_audio_chunk` must arrive
   within 400 ms of `agent_thinking`; full audio must not be required before playback starts.
8. **T10–T12 (frontend scheduler + VAD hook)**: Manual conversation test — no audio gap between
   consecutive agent sentences; `response.create` fires ~800 ms after user stops speaking.

---

## Task List

```json
{
  "id": "T01",
  "title": "Reduce audio batch flush threshold to 100 ms",
  "type": "bug_fix",
  "priority": "high",
  "layer": "frontend",
  "file": "frontend/src/utils/audioRecorder.js",
  "function_or_class": "streamAudioChunk",
  "description": "STREAM_BUFFER_THRESHOLD is currently 16000 samples. At 16 kHz this means the browser accumulates 1 full second of audio before sending the first WebSocket frame. The reference architecture flushes every 100 ms (1600 samples at 16 kHz). Change the constant from 16000 to 1600. This is the single largest per-turn latency improvement available in the frontend. No other logic changes are needed — the threshold comparison on line ~105 already uses this constant.",
  "depends_on": [],
  "context_files": [
    "frontend/src/utils/audioRecorder.js"
  ],
  "acceptance_criteria": [
    "STREAM_BUFFER_THRESHOLD === 1600",
    "First WebSocket binary frame arrives at server within 150 ms of speech onset"
  ],
  "estimated_lines_changed": 1
}
```

```json
{
  "id": "T02",
  "title": "Halve ScriptProcessor buffer size to 2048",
  "type": "bug_fix",
  "priority": "medium",
  "layer": "frontend",
  "file": "frontend/src/utils/audioRecorder.js",
  "function_or_class": "start",
  "description": "STREAM_CHUNK_SIZE is 4096 samples. At a 48 kHz native AudioContext rate this produces onaudioprocess events every ~85 ms (4096/48000). The reference uses 2048 samples for ~42 ms frame granularity. Change STREAM_CHUNK_SIZE from 4096 to 2048. This halves mic capture latency per frame. Note: the AudioContext sample rate is set dynamically from the mediaStream track settings so no change to sampleRate is needed here — that is addressed separately in T10.",
  "depends_on": [],
  "context_files": [
    "frontend/src/utils/audioRecorder.js"
  ],
  "acceptance_criteria": [
    "STREAM_CHUNK_SIZE === 2048",
    "onaudioprocess fires every ~42 ms at 48 kHz or ~85 ms at 24 kHz"
  ],
  "estimated_lines_changed": 1
}
```

```json
{
  "id": "T03",
  "title": "Replace per-byte base64 loop with chunked apply",
  "type": "refactor",
  "priority": "medium",
  "layer": "frontend",
  "file": "frontend/src/utils/audioRecorder.js",
  "function_or_class": "arrayBufferToBase64",
  "description": "arrayBufferToBase64 currently builds a string by concatenating one character per byte in a for-loop. At 100 ms batches this is ~3200 string allocations; at the current 1-second batches it is ~32000. This creates GC pressure that can stall the main thread and delay onaudioprocess. Replace the body with a chunked String.fromCharCode.apply approach that processes 8192 bytes at a time, then call btoa on the result. The function signature does not change. This is the same pattern used by every high-performance audio web app.",
  "depends_on": [],
  "context_files": [
    "frontend/src/utils/audioRecorder.js"
  ],
  "acceptance_criteria": [
    "No character-by-character loop remains in arrayBufferToBase64",
    "Output of btoa(chunked) matches btoa(character loop) for any ArrayBuffer input"
  ],
  "estimated_lines_changed": 8
}
```

```json
{
  "id": "T04",
  "title": "Lower STT VAD silence_duration_ms from 1200 to 800",
  "type": "bug_fix",
  "priority": "high",
  "layer": "agent",
  "file": "backend/app/agent/realtime_stt.py",
  "function_or_class": "_SESSION_UPDATE",
  "description": "The _SESSION_UPDATE dict configures the OpenAI server_vad with silence_duration_ms=1200. This means OpenAI waits 1.2 seconds of silence after the user stops speaking before committing the audio buffer and firing the transcription.completed event. The reference uses 800 ms. Change the value from 1200 to 800. This shaves 400 ms off every single turn in the conversation, compounding with every other fix. Also update settings.VAD_SILENCE_DURATION_MS in config.py from 2000 to 800 and reference it here so the value is configurable via .env.",
  "depends_on": ["T12"],
  "context_files": [
    "backend/app/agent/realtime_stt.py",
    "backend/app/core/config.py"
  ],
  "acceptance_criteria": [
    "silence_duration_ms reads from settings.STT_SILENCE_DURATION_MS",
    "Default value in config.py is 800",
    "Time from end-of-speech to agent_thinking log line is ≤900 ms"
  ],
  "estimated_lines_changed": 4
}
```

```json
{
  "id": "T05",
  "title": "Fix raw PCM16 silently dropped in send_audio",
  "type": "bug_fix",
  "priority": "high",
  "layer": "agent",
  "file": "backend/app/agent/realtime_stt.py",
  "function_or_class": "_wav_bytes_to_realtime_pcm / send_audio",
  "description": "The frontend sends raw PCM16 bytes (no RIFF/WAV header) as the audio payload. _wav_bytes_to_realtime_pcm passes these to soundfile.read() which requires a WAV container. soundfile raises an exception, it is caught silently, and b'' is returned. send_audio then early-exits on empty bytes. The result: no audio ever reaches the Realtime API in agent mode, so transcription.completed never fires and the agent never responds. Fix: add a _raw_pcm16_to_24k(pcm16_bytes, source_sr=16000) helper that uses numpy to resample without soundfile. In send_audio, try _wav_bytes_to_realtime_pcm first; if it returns b'' fall back to _raw_pcm16_to_24k. Add a logger.info confirming non-empty bytes are forwarded so the fix can be verified in logs. The helper signature: def _raw_pcm16_to_24k(pcm16_bytes: bytes, source_sr: int = 16_000) -> bytes.",
  "depends_on": [],
  "context_files": [
    "backend/app/agent/realtime_stt.py"
  ],
  "acceptance_criteria": [
    "_raw_pcm16_to_24k exists and correctly resamples int16-LE bytes from 16 kHz to 24 kHz",
    "send_audio logs a non-empty byte count when raw PCM16 is received",
    "transcription.completed callback fires during an agent-mode conversation"
  ],
  "estimated_lines_changed": 25
}
```

```json
{
  "id": "T06",
  "title": "Send audio as binary WebSocket frames, not base64 JSON",
  "type": "refactor",
  "priority": "medium",
  "layer": "frontend",
  "file": "frontend/src/utils/audioRecorder.js",
  "function_or_class": "sendStreamChunk",
  "description": "sendStreamChunk currently calls websocket.send(JSON.stringify({type:'audio', data: base64String, ...})). This adds 33% size overhead from base64 encoding plus JSON serialisation overhead. The backend WebSocket handler in verification.py already handles binary frames via message.get('bytes'). Change sendStreamChunk to call websocket.send(pcmData) where pcmData is the raw ArrayBuffer returned by convertToPCM16. Remove the arrayBufferToBase64 call and JSON wrapper from the send path (keep arrayBufferToBase64 if it is used elsewhere). The sequence and timestamp metadata are not needed at runtime — remove them. Do NOT change the audio_complete final message which is still a JSON text frame.",
  "depends_on": ["T03"],
  "context_files": [
    "frontend/src/utils/audioRecorder.js",
    "backend/app/api/routes/verification.py"
  ],
  "acceptance_criteria": [
    "websocket.send receives an ArrayBuffer, not a JSON string for audio chunks",
    "No base64 encoding in the hot-path send flow",
    "Backend message.get('bytes') branch handles the frame (verify with a log line)"
  ],
  "estimated_lines_changed": 12
}
```

```json
{
  "id": "T07",
  "title": "Create singleton AsyncOpenAI client in tts.py",
  "type": "bug_fix",
  "priority": "medium",
  "layer": "agent",
  "file": "backend/app/agent/tts.py",
  "function_or_class": "synthesise_speech",
  "description": "synthesise_speech creates a new AsyncOpenAI(api_key=...) on every call. AsyncOpenAI internally creates an httpx.AsyncClient with its own connection pool. On every TTS call the pool starts cold, requiring a TCP + TLS handshake to api.openai.com which adds 20–150 ms. Create a module-level _tts_client: AsyncOpenAI | None = None variable and a _get_tts_client() function that instantiates it once and returns the singleton on subsequent calls. Replace the local client = AsyncOpenAI(...) in synthesise_speech with client = _get_tts_client(). Do the same for the STT client in stt.py in the same PR.",
  "depends_on": [],
  "context_files": [
    "backend/app/agent/tts.py",
    "backend/app/agent/stt.py"
  ],
  "acceptance_criteria": [
    "_tts_client is None before first call and non-None after",
    "id(_get_tts_client()) returns the same value on consecutive calls",
    "No AsyncOpenAI() constructor call inside synthesise_speech body"
  ],
  "estimated_lines_changed": 10
}
```

```json
{
  "id": "T08",
  "title": "Remove duplicate Whisper call on verified chunk transition",
  "type": "bug_fix",
  "priority": "medium",
  "layer": "route",
  "file": "backend/app/api/routes/verification.py",
  "function_or_class": "websocket_verify_endpoint",
  "description": "When final_status=='verified', the route calls transcribe_audio(verified_audio) — a separate HTTP call to whisper-1 — to get a transcript of the audio that was already being streamed to the RealtimeSTTSession. This is redundant: the RealtimeSTTSession will fire the on_transcript callback with the same text moments later via the transcription.completed event. Remove the entire block starting at 'from app.agent.stt import transcribe_audio' through 'await process_verified_utterance(...)' inside the final_status=='verified' branch. Replace it with: set in_agent_mode = True immediately and let the first on_transcript callback from the already-running RealtimeSTTSession handle the first agent turn naturally. Add a logger.info confirming the transition.",
  "depends_on": ["T05"],
  "context_files": [
    "backend/app/api/routes/verification.py",
    "backend/app/services/voice_agent.py",
    "backend/app/agent/realtime_stt.py"
  ],
  "acceptance_criteria": [
    "No 'from app.agent.stt import transcribe_audio' import inside the verified branch",
    "No transcribe_audio() call in websocket_verify_endpoint",
    "Agent responds to first utterance after biometric verification via the on_transcript callback",
    "[STT] Sending … bytes to Whisper log line does NOT appear in agent mode"
  ],
  "estimated_lines_changed": 20
}
```

```json
{
  "id": "T09",
  "title": "Replace blocking TTS blob with streaming PCM16 chunks",
  "type": "feature",
  "priority": "high",
  "layer": "agent",
  "file": "backend/app/agent/tts.py",
  "function_or_class": "synthesise_speech",
  "description": "synthesise_speech currently calls response.aread() which waits for the entire MP3 file (typically 500 ms–2 s) before returning. Add a new async generator function stream_speech(text, voice='alloy') that uses client.audio.speech.with_streaming_response.create(..., response_format='pcm') and yields raw PCM16 chunks as they arrive. The caller (voice_agent.py _handle_transcript) should be updated to call stream_speech and send each chunk as {type:'agent_audio_chunk', data:<base64>} followed by {type:'agent_audio_done'} when the generator is exhausted. The existing synthesise_speech function stays for use during the biometric phase (greeting, retry prompts) where streaming is not needed. response_format='pcm' returns raw 24 kHz int16-LE bytes — no MP3 decode on the client.",
  "depends_on": ["T07"],
  "context_files": [
    "backend/app/agent/tts.py",
    "backend/app/services/voice_agent.py"
  ],
  "acceptance_criteria": [
    "stream_speech is an async generator yielding bytes chunks",
    "First agent_audio_chunk message arrives at browser within 400 ms of agent_thinking",
    "agent_audio_done is sent after the last chunk",
    "Frontend receives and can decode raw PCM16 frames from stream"
  ],
  "estimated_lines_changed": 35
}
```

```json
{
  "id": "T10",
  "title": "Replace time-based echo suppression with tts_done signal",
  "type": "feature",
  "priority": "medium",
  "layer": "service",
  "file": "backend/app/services/voice_agent.py",
  "function_or_class": "_handle_transcript / process_audio_chunk",
  "description": "The current echo suppression blocks audio forwarding for max(3.0, wordCount/2.5 + 1.0) seconds after TTS is sent. For a 10-word reply this is 5 seconds of mic suppression even though actual playback may end in 3 seconds — a 2-second dead window. Replace this with an event-driven approach: keep tts_playing=True when TTS starts, but clear it immediately when the backend receives a {type:'tts_done'} message from the client (sent by the frontend when audio.onended fires). In process_audio_chunk, add a branch: if the incoming JSON text message has type=='tts_done', call session_cache.update(client_id, tts_playing=False) and return. Remove the asyncio.sleep-based _clear_tts_playing coroutine entirely. Keep the playback_seconds estimate as a safety fallback timeout only (use asyncio.create_task with a much longer timeout e.g. 30s) in case tts_done is never received.",
  "depends_on": ["T09"],
  "context_files": [
    "backend/app/services/voice_agent.py",
    "backend/app/agent/session_cache.py",
    "backend/app/api/routes/verification.py"
  ],
  "acceptance_criteria": [
    "tts_playing is cleared within 50 ms of receiving the tts_done message",
    "No asyncio.sleep used for the normal playback suppression window",
    "A 30s fallback asyncio.create_task still clears tts_playing if tts_done is never sent"
  ],
  "estimated_lines_changed": 28
}
```

```json
{
  "id": "T11",
  "title": "Route tts_done text frame in WS verify endpoint",
  "type": "feature",
  "priority": "medium",
  "layer": "route",
  "file": "backend/app/api/routes/verification.py",
  "function_or_class": "websocket_verify_endpoint",
  "description": "The agent-mode branch in websocket_verify_endpoint currently handles incoming text frames only for the cancel message. Extend the text-frame handler to also recognise {type:'tts_done'} and forward it to the VoiceAgentOrchestrator. Specifically: inside the 'if in_agent_mode' block, after parsing ctrl = json.loads(message['text']), add an elif branch for ctrl.get('type') == 'tts_done' that calls get_voice_agent().handle_tts_done(client_id=session.session_id). Add handle_tts_done(client_id) to VoiceAgentOrchestrator in voice_agent.py — it should simply call session_cache.update(client_id, tts_playing=False) and cancel the fallback timeout task if one exists.",
  "depends_on": ["T10"],
  "context_files": [
    "backend/app/api/routes/verification.py",
    "backend/app/services/voice_agent.py"
  ],
  "acceptance_criteria": [
    "handle_tts_done method exists on VoiceAgentOrchestrator",
    "Receiving {type:'tts_done'} over WS sets session tts_playing=False immediately",
    "cancel message still works"
  ],
  "estimated_lines_changed": 18
}
```

```json
{
  "id": "T12",
  "title": "Add STT_SILENCE_DURATION_MS to config and settings",
  "type": "config",
  "priority": "medium",
  "layer": "config",
  "file": "backend/app/core/config.py",
  "function_or_class": "Settings",
  "description": "The Realtime STT session silence_duration_ms value is hardcoded to 1200 in realtime_stt.py. Add a new field STT_SILENCE_DURATION_MS: int = 800 to the Settings class in config.py. This allows operators to tune the VAD commit window via the .env file without a code change. T04 depends on this task to update realtime_stt.py to reference settings.STT_SILENCE_DURATION_MS instead of the literal 1200.",
  "depends_on": [],
  "context_files": [
    "backend/app/core/config.py",
    "backend/app/agent/realtime_stt.py"
  ],
  "acceptance_criteria": [
    "Settings.STT_SILENCE_DURATION_MS exists with default 800",
    "Setting can be overridden via STT_SILENCE_DURATION_MS=<value> in .env"
  ],
  "estimated_lines_changed": 2
}
```

```json
{
  "id": "T13",
  "title": "Remove full-payload console.log in _handleMessage",
  "type": "bug_fix",
  "priority": "low",
  "layer": "frontend",
  "file": "frontend/src/services/realtimeVerificationService.js",
  "function_or_class": "_handleMessage",
  "description": "The first line of _handleMessage calls console.log with the full message object. For agent_audio messages this includes the entire base64 MP3 blob (50-200 KB). Serialising a 200 KB string on the main thread in console.log blocks the message handler and delays the start of audio playback. Replace the blanket log with a selective one that only logs metadata for audio messages: const logSafe = (type === 'agent_audio' || type === 'agent_audio_chunk') ? {type, dataLength: message.data?.length} : message; console.log('[RealTimeVerification] Message:', logSafe);",
  "depends_on": [],
  "context_files": [
    "frontend/src/services/realtimeVerificationService.js"
  ],
  "acceptance_criteria": [
    "console.log in _handleMessage never serialises the full base64 data field",
    "Log still prints type and dataLength for audio messages"
  ],
  "estimated_lines_changed": 4
}
```

```json
{
  "id": "T14",
  "title": "Add send_only_once guard for session_cache send_ws update",
  "type": "refactor",
  "priority": "low",
  "layer": "service",
  "file": "backend/app/services/voice_agent.py",
  "function_or_class": "process_audio_chunk",
  "description": "process_audio_chunk calls session_cache.update(client_id, send_ws=send_ws) on every single 100 ms audio chunk, unconditionally. Since send_ws is the same websocket.send_json bound method for the entire connection lifetime, this is 10 unnecessary dict writes per second. Add an identity check before updating: only call session_cache.update when the stored send_ws is not the same object as the incoming one. Use 'if session.get(\"send_ws\") is not send_ws:' to guard the update call.",
  "depends_on": [],
  "context_files": [
    "backend/app/services/voice_agent.py",
    "backend/app/agent/session_cache.py"
  ],
  "acceptance_criteria": [
    "session_cache.update for send_ws is called at most once per connection",
    "Subsequent chunks with the same send_ws skip the update"
  ],
  "estimated_lines_changed": 5
}
```

```json
{
  "id": "T15",
  "title": "Add gapless PCM16 playback scheduler on frontend",
  "type": "feature",
  "priority": "high",
  "layer": "frontend",
  "file": "frontend/src/services/realtimeVerificationService.js",
  "function_or_class": "_handleMessage",
  "description": "The reference architecture schedules agent audio using a playbackTimeRef cursor so consecutive PCM16 frames are played back-to-back with zero gap. Currently the frontend receives the agent_audio message containing a full MP3 blob and plays it directly via an Audio element. After T09 lands, the frontend will receive a stream of agent_audio_chunk messages (raw PCM16 bytes, 24 kHz mono). Add a playbackTimeRef variable (initialised to 0) and an AudioContext at 24000 Hz to the message handler. For each agent_audio_chunk: decode the base64 PCM16 bytes, convert Int16 → Float32 (divide by 32768), create an AudioBuffer, schedule it at max(playbackTimeRef, audioContext.currentTime), then advance playbackTimeRef by buffer.duration. Set isAgentSpeaking=true on the first chunk. On agent_audio_done, schedule a setTimeout to clear isAgentSpeaking after (playbackTimeRef - audioContext.currentTime)*1000 + 300 ms. Send the tts_done message at that point.",
  "depends_on": ["T09", "T13"],
  "context_files": [
    "frontend/src/services/realtimeVerificationService.js",
    "frontend/src/hooks/useRealtimeVerification.js"
  ],
  "acceptance_criteria": [
    "playbackTimeRef advances monotonically across consecutive agent_audio_chunk messages",
    "No audible gap between consecutive TTS sentence fragments",
    "isAgentSpeaking flag is false only after the last scheduled frame finishes playing",
    "tts_done message is sent to the backend at the same time isAgentSpeaking clears"
  ],
  "estimated_lines_changed": 55
}
```

```json
{
  "id": "T16",
  "title": "Add client-side VAD hook with filler-word tolerance",
  "type": "feature",
  "priority": "medium",
  "layer": "frontend",
  "file": "frontend/src/hooks/useRealtimeVerification.js",
  "function_or_class": "useRealtimeVerification",
  "description": "The reference architecture has a client-side VAD that tracks silence duration (ms) and sends response.create when the user has been silent for BASE_SILENCE_MS (800) + INTERRUPT_BUFFER_MS (400) = 1200 ms, with an extra 700 ms delay if the last word is a filler word (um, uh, hmm, so, like, well). This is in addition to server_vad — the client VAD drives UI state (isUserSpeaking, silenceMs) while server_vad drives actual transcription commit. Add a useEffect in useRealtimeVerification that runs a 100 ms interval timer. Derive isUserSpeaking from an RMS computation on the most recent audio frame (rms > 0.02 = speaking). Track silenceMs by incrementing a counter when !isUserSpeaking. When silenceMs >= 1200 and the last transcript role was 'user' and the last transcribed word is not a filler, send {type: 'response.create'} over the WebSocket (this is a no-op with server_vad but future-proofs for manual-commit mode). Expose isUserSpeaking and silenceMs as hook return values for UI rendering.",
  "depends_on": ["T15"],
  "context_files": [
    "frontend/src/hooks/useRealtimeVerification.js",
    "frontend/src/services/realtimeVerificationService.js"
  ],
  "acceptance_criteria": [
    "isUserSpeaking updates at ≤100 ms granularity",
    "silenceMs resets to 0 whenever isSpeaking becomes true",
    "response.create is NOT sent while isAgentSpeaking is true",
    "response.create is NOT sent if last word is in the filler list",
    "Both isUserSpeaking and silenceMs are exposed from the hook"
  ],
  "estimated_lines_changed": 60
}
```

```json
{
  "id": "T17",
  "title": "Implement silence nudge system (client + backend)",
  "type": "feature",
  "priority": "low",
  "layer": "service",
  "file": "backend/app/services/voice_agent.py",
  "function_or_class": "VoiceAgentOrchestrator",
  "description": "The reference architecture has a nudge system: if the user is silent for 15 seconds after the agent finishes speaking, an instructions-only response.create is injected telling the model to 'gently check in'. Implement this in two parts. Backend: add a per-session asyncio.Queue nudge_queue to the session cache. Add a nudge_watcher(client_id) async coroutine on VoiceAgentOrchestrator that blocks on nudge_queue.get() and, when a nudge message arrives, sends {type:'response.create', response:{instructions: message}} upstream to the Realtime API (only applicable after T13 full-duplex refactor; for now log the nudge and skip). Add a POST /session/{session_id}/nudge FastAPI endpoint in verification.py that accepts a body {message: str} and puts it on the queue. Client: in useRealtimeVerification, add a 15-second silence timer that fires only when latestTranscriptRole==='assistant' and the user has not spoken since. On trigger, POST to /session/{sessionId}/nudge with a standard message, with a 15-second cooldown between nudges.",
  "depends_on": ["T16"],
  "context_files": [
    "backend/app/services/voice_agent.py",
    "backend/app/agent/session_cache.py",
    "backend/app/api/routes/verification.py",
    "frontend/src/hooks/useRealtimeVerification.js"
  ],
  "acceptance_criteria": [
    "POST /session/{id}/nudge returns 200 and puts message on the queue",
    "nudge_watcher logs the nudge message when dequeued",
    "Frontend fires at most one nudge per 15-second cooldown period",
    "Nudge does not fire while isUserSpeaking or isAgentSpeaking is true"
  ],
  "estimated_lines_changed": 70
}
```

---

## Execution Order

Apply tasks in this sequence to ensure each fix is verifiable before the next builds on it:

```
Phase 1 — Unbreak agent mode (minutes, no dependencies between tasks):
  T12 → T04   (config then STT silence window)
  T05         (PCM16 format fix — unblocks all agent-mode testing)
  T07         (singleton TTS client)
  T13         (remove noisy console.log)
  T14         (guard send_ws update)

Phase 2 — Latency quick wins:
  T01         (flush threshold 1 s → 100 ms)
  T02         (buffer size 4096 → 2048)
  T03 → T06   (fast base64 then binary frames)
  T08         (remove duplicate Whisper call)

Phase 3 — Echo suppression overhaul:
  T09         (streaming TTS)
  T10         (event-driven tts_done suppression)
  T11         (route tts_done in WS endpoint)

Phase 4 — Missing reference features:
  T15         (gapless playback scheduler)
  T16         (VAD hook)
  T17         (silence nudge)
```

**Expected latency reduction after Phase 1 + Phase 2 (all tasks ≤30 min each)**:
- Turn-start latency: −900 ms (T01) − 400 ms (T04) = **−1.3 s per turn**
- Agent now responds at all in agent mode (T05 unblocks this entirely)

**After Phase 3**:
- First audio byte to browser: −500 ms to −2 s (streaming TTS vs full-MP3 wait)
- Dead window between agent finishes and user can speak: −0 to −3 s (T10)

**After Phase 4**:
- Gapless agent audio, proper echo suppression, full VAD hook, nudge system — feature-complete with reference architecture
