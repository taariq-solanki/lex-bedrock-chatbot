# Design Document: Lex Polly Voice

## Overview

This feature adds bidirectional voice interaction to the existing Lex V2 Bedrock chatbot. It enables the Lex bot locale to synthesize speech via Amazon Polly (server-side configuration) and extends the browser-based Web UI to capture microphone input, send audio to Lex via the RecognizeUtterance API, and play back spoken responses.

The design keeps changes minimal and targeted:
- **SAM template**: Add `VoiceSettings` to the existing `en_US` BotLocale + a `PollyVoiceId` parameter
- **Web UI**: Add microphone button, audio recording via MediaRecorder + AudioContext, RecognizeUtterance API integration, and audio playback via HTMLAudioElement
- **Lambda**: No changes — it already returns `PlainText` messages that Lex pipes to Polly automatically
- **Cognito**: Already has `lex:RecognizeUtterance` permission — no changes needed

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Audio input format | PCM 16-bit, 16kHz mono | Widest Lex compatibility; no codec negotiation needed |
| PCM encoding method | AudioContext + ScriptProcessorNode | MediaRecorder doesn't reliably produce raw PCM; AudioContext gives precise control over sample rate and bit depth |
| Audio response format | MPEG (audio/mpeg) | Universal browser playback support via HTMLAudioElement without extra codecs |
| Playback mechanism | HTMLAudioElement with Blob URL | Simple, no Web Audio API decode step needed for MPEG |
| Max recording duration | 15 seconds with auto-submit | Matches Lex utterance limits; prevents accidental long recordings |
| Dual-mode session | Shared sessionId, separate API paths | Text uses RecognizeText, voice uses RecognizeUtterance; same session preserves conversation continuity |
| Polly voice default | "Danielle" (neural) | High-quality US English neural voice; overridable via CloudFormation parameter |

## Architecture

```mermaid
graph TB
    subgraph Browser["Browser (Web UI)"]
        UI[Chat Interface]
        MIC[Microphone Button]
        AR[AudioRecorder<br/>AudioContext + ScriptProcessor]
        AP[Audio Playback<br/>HTMLAudioElement]
        SDK[AWS SDK v2]
    end

    subgraph AWS["AWS Cloud (eu-central-1)"]
        COG[Cognito Identity Pool<br/>Unauthenticated]
        LEX[Lex V2 Bot<br/>en_US + VoiceSettings]
        POLLY[Amazon Polly<br/>Neural Engine]
        LAMBDA[Lambda Function<br/>handler.py]
        BEDROCK[Amazon Bedrock<br/>Claude Haiku]
    end

    UI -->|Text| SDK
    MIC -->|Start/Stop| AR
    AR -->|PCM 16kHz blob| SDK
    SDK -->|RecognizeText| LEX
    SDK -->|RecognizeUtterance<br/>audio/x-l16| LEX
    LEX -->|FallbackIntent| LAMBDA
    LAMBDA -->|InvokeModel| BEDROCK
    BEDROCK -->|Response| LAMBDA
    LAMBDA -->|PlainText| LEX
    LEX -->|SynthesizeSpeech| POLLY
    POLLY -->|Audio| LEX
    LEX -->|audioStream (MPEG)<br/>+ headers| SDK
    SDK -->|Blob URL| AP
    COG -->|Temporary Credentials| SDK
```

### Request Flow: Voice Interaction

1. User taps microphone button → UI requests `getUserMedia` permission
2. AudioContext created at 16kHz; ScriptProcessorNode captures PCM samples
3. User taps again (or 15s timeout) → recording stops, PCM buffer assembled as `Int16Array`
4. SDK calls `recognizeUtterance` with PCM blob, `requestContentType: "audio/x-l16; sample-rate=16000; channel-count=1"`, `responseContentType: "audio/mpeg"`
5. Lex transcribes audio (ASR), routes to FallbackIntent → Lambda → Bedrock → response text
6. Lex passes response text to Polly (via VoiceSettings) → synthesized MPEG audio
7. Response returns: `audioStream` (MPEG body) + base64-encoded `messages` in HTTP headers
8. UI decodes header messages → displays text in chat; creates Blob URL from audioStream → plays via HTMLAudioElement
9. On playback end → re-enable all input controls

### Request Flow: Text Interaction (unchanged)

1. User types text → SDK calls `recognizeText` (existing flow, no audio response)
2. Response messages displayed as text in chat

## Components and Interfaces

### 1. SAM Template Changes (`template.yaml`)

**New Parameter:**
```yaml
PollyVoiceId:
  Type: String
  Default: Danielle
  Description: Polly neural voice ID for the en_US locale speech synthesis.
```

**BotLocale modification** — add `VoiceSettings` to the existing `en_US` locale:
```yaml
BotLocales:
  - LocaleId: en_US
    NluConfidenceThreshold: 0.40
    VoiceSettings:
      VoiceId: !Ref PollyVoiceId
      Engine: neural
    Intents:
      # ... existing intents unchanged
```

No other template changes required. The `LexBotRole` already has `polly:SynthesizeSpeech` and the `CognitoUnauthRole` already has `lex:RecognizeUtterance`.

### 2. Web UI Audio Recorder Module

A self-contained JavaScript module (inline in `index.html`) managing the microphone capture lifecycle.

**Interface:**
```javascript
// AudioRecorder — captures PCM 16kHz mono audio from microphone
const AudioRecorder = {
    isRecording: false,
    audioContext: null,       // AudioContext at 16000 Hz sample rate
    mediaStream: null,        // getUserMedia stream
    scriptProcessor: null,    // ScriptProcessorNode for PCM capture
    pcmBuffers: [],           // Array of Float32Array chunks
    maxDurationMs: 15000,     // Auto-stop after 15 seconds
    timeoutId: null,

    // Start recording: request mic, create AudioContext, begin capture
    async start() → void,

    // Stop recording: close stream, assemble PCM, return ArrayBuffer
    stop() → ArrayBuffer,     // Returns PCM Int16 ArrayBuffer

    // Check if browser supports required APIs
    isSupported() → boolean
};
```

**PCM Encoding Logic:**
- `AudioContext` created with `sampleRate: 16000`
- `ScriptProcessorNode` (bufferSize 4096) captures Float32 samples
- On stop: concatenate buffers → convert Float32 → Int16 (multiply by 0x7FFF, clamp)
- Return raw `ArrayBuffer` of Int16 PCM samples

### 3. Web UI Voice Interaction Controller

Orchestrates the microphone button behavior, API calls, and audio playback.

**Interface:**
```javascript
// VoiceController — manages voice interaction lifecycle
const VoiceController = {
    // Send recorded audio to Lex via RecognizeUtterance
    async sendAudio(pcmBuffer: ArrayBuffer) → void,

    // Play MPEG audio response from Lex
    playAudioResponse(audioStream: Blob) → Promise<void>,

    // Decode base64 messages from RecognizeUtterance response headers
    decodeResponseMessages(response) → Array<{content: string}>,

    // Toggle recording state (called by mic button click)
    toggleRecording() → void
};
```

### 4. Web UI State Management

The UI has distinct states that control which elements are enabled:

| State | Text Input | Send Btn | Mic Btn | Visual Indicator |
|-------|-----------|----------|---------|-----------------|
| Idle | Enabled | Enabled | Enabled | None |
| Recording | Disabled | Disabled | Active (red pulse) | Recording indicator |
| Processing (voice) | Disabled | Disabled | Disabled | Typing dots |
| Playing | Disabled | Disabled | Disabled | Speaker animation |
| Processing (text) | Disabled | Disabled | Disabled | Typing dots |
| Error | Enabled | Enabled | Enabled/Disabled* | Error message |

*Mic button disabled only if browser doesn't support voice.

### 5. HTMLAudioElement Playback

```javascript
// Create Blob URL from audioStream and play
function playAudio(audioBlob) {
    const url = URL.createObjectURL(audioBlob);
    const audio = new Audio(url);
    audio.onended = () => {
        URL.revokeObjectURL(url);
        // Re-enable controls
    };
    audio.onerror = () => {
        URL.revokeObjectURL(url);
        // Show text fallback, re-enable controls
    };
    audio.play();
}
```

## Data Models

### RecognizeUtterance Request Parameters

```javascript
{
    botId: CONFIG.lexBotId,              // Same as RecognizeText
    botAliasId: CONFIG.lexBotAliasId,    // Same as RecognizeText
    localeId: CONFIG.localeId,           // "en_US"
    sessionId: sessionId,                // Shared with text mode
    requestContentType: "audio/x-l16; sample-rate=16000; channel-count=1",
    responseContentType: "audio/mpeg",
    inputStream: pcmArrayBuffer          // Raw PCM Int16 bytes
}
```

### RecognizeUtterance Response Structure

```javascript
{
    audioStream: Blob,                   // MPEG audio of Polly response
    contentType: "audio/mpeg",
    messages: "base64-encoded-json",     // URL-encoded, then base64
    sessionState: "base64-encoded-json", // Session state
    inputTranscript: "base64-encoded"    // What Lex heard (ASR transcript)
}
```

**Header Decoding:**
The `messages` field in the response is URL-encoded then base64-encoded. Decoding:
```javascript
const decoded = JSON.parse(decodeURIComponent(atob(response.messages)));
// decoded = [{content: "Hello! ...", contentType: "PlainText"}]
```

### PCM Audio Buffer Format

| Property | Value |
|----------|-------|
| Encoding | Linear PCM (signed 16-bit integers) |
| Sample Rate | 16,000 Hz |
| Channels | 1 (mono) |
| Byte Order | Little-endian |
| Content-Type | `audio/x-l16; sample-rate=16000; channel-count=1` |

### SAM Template VoiceSettings Schema

```yaml
VoiceSettings:
  VoiceId: String    # Polly voice identifier (e.g., "Danielle")
  Engine: String     # "neural" or "standard"
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: PCM encoding preserves signal characteristics

*For any* array of Float32 audio samples (values in [-1.0, 1.0]), converting to Int16 PCM format SHALL produce an output where: (a) the output array length equals the input array length, (b) every output value is within [-32768, 32767], (c) the sign of each non-zero sample is preserved, and (d) the relative ordering of sample magnitudes is preserved.

**Validates: Requirements 2.5**

### Property 2: Response message decode is a round-trip of encode

*For any* array of message objects with arbitrary string content, encoding via `JSON.stringify → encodeURIComponent → btoa` and then decoding via `atob → decodeURIComponent → JSON.parse` SHALL produce an array equal to the original input messages.

**Validates: Requirements 4.5**

### Property 3: Session ID invariant across interaction modes

*For any* sequence of text and voice interactions (in any order and any count), the `sessionId` parameter passed to both `recognizeText` and `recognizeUtterance` API calls SHALL be the same value throughout the entire sequence.

**Validates: Requirements 5.5**

## Error Handling

### Audio Recording Errors

| Error Condition | Handling | User Impact |
|----------------|----------|-------------|
| `getUserMedia` not supported | Disable mic button, show "Browser does not support voice input" | Text-only mode |
| Microphone permission denied | Disable mic button, show "Microphone access denied" | Text-only mode |
| MediaStream track ends unexpectedly | Stop recording, discard buffer, re-enable controls | Brief error message, can retry |
| AudioContext creation fails | Disable mic button, show error | Text-only mode |

### API Errors

| Error Condition | Handling | User Impact |
|----------------|----------|-------------|
| `recognizeUtterance` network failure | Show "Connection error" in chat, re-enable controls | Can retry |
| `recognizeUtterance` 4xx response | Show specific error text, re-enable controls | Can retry |
| Response timeout (>30s) | Abort request, show timeout message, re-enable controls | Can retry |
| Cognito credentials expired | Refresh credentials automatically (SDK handles), retry once | Transparent |

### Audio Playback Errors

| Error Condition | Handling | User Impact |
|----------------|----------|-------------|
| `Audio.play()` rejected (autoplay policy) | Display text transcript, skip audio | Text fallback |
| Audio decode error | Display text transcript, revoke Blob URL | Text fallback |
| Empty/missing audioStream in response | Display text from decoded headers | Text fallback |

### Graceful Degradation Strategy

The UI always falls back to text display when audio fails. The user is never blocked from continuing the conversation. Controls are re-enabled after any error within 30 seconds maximum.

## Testing Strategy

### Unit Tests (example-based)

Unit tests cover specific behaviors, edge cases, and UI state transitions:

- **Microphone button presence**: Verify the mic button exists in the input area DOM
- **UI state transitions**: Verify correct enable/disable states for each mode (idle, recording, processing, playing)
- **Auto-stop at 15 seconds**: Verify timeout triggers recording stop
- **Error fallback**: Verify text-only mode when getUserMedia is unavailable
- **RecognizeUtterance params**: Verify correct content types and session parameters
- **Audio playback lifecycle**: Verify Blob URL creation, play, and cleanup on ended/error
- **Text mode unchanged**: Verify RecognizeText still works as before

### Property-Based Tests (hypothesis, minimum 100 examples)

Property-based tests verify universal correctness properties using the `hypothesis` library:

| Property | Test Target | Generator Strategy |
|----------|-------------|-------------------|
| PCM encoding signal preservation | `float32ToInt16()` function | Random Float32 arrays with values in [-1.0, 1.0], varying lengths (0 to 16000 samples) |
| Response message decode round-trip | `decodeResponseMessages()` function | Random strings including unicode, special chars, empty strings; arrays of 0-5 messages |
| Session ID invariant | Interaction sequence | Random sequences of "text" and "voice" actions (1-20 actions), verify sessionId constant |

**Configuration:**
- Minimum 100 iterations per property test
- Tag format: `Feature: lex-polly-voice, Property {N}: {property_text}`
- Tests located in `tests/unit/test_properties.py` (extending existing file) or a new `tests/unit/test_voice_properties.py`

### Integration Tests

Integration tests verify end-to-end AWS behavior after deployment:

- Deploy stack with VoiceSettings, verify bot locale has voice configured
- Send RecognizeUtterance with valid audio, verify 200 response with audioStream
- Verify Cognito unauth credentials can call RecognizeUtterance
- Verify invalid PollyVoiceId fails deployment

### Smoke Tests

- SAM template contains `VoiceSettings` with `Engine: neural`
- SAM template has `PollyVoiceId` parameter with default "Danielle"
- Cognito unauth role includes `lex:RecognizeUtterance` action
- Web UI renders mic button, text input, and Send button in same row

