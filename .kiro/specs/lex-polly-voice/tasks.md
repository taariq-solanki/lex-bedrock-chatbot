# Implementation Plan: Lex Polly Voice

## Overview

This implementation adds bidirectional voice interaction to the existing Lex V2 Bedrock chatbot. The work is split into three tracks: SAM template changes (minimal YAML addition), Web UI voice features (microphone capture, RecognizeUtterance API, audio playback), and property-based tests validating correctness invariants. The Lambda function and Cognito permissions require no changes.

## Tasks

- [x] 1. Add Polly voice configuration to SAM template
  - [x] 1.1 Add PollyVoiceId parameter and VoiceSettings to template.yaml
    - Add a `PollyVoiceId` CloudFormation parameter (Type: String, Default: "Danielle") to the Parameters section
    - Add `VoiceSettings` block with `VoiceId: !Ref PollyVoiceId` and `Engine: neural` to the existing `en_US` BotLocale in the LexBot resource
    - Place VoiceSettings between `NluConfidenceThreshold` and `Intents` in the locale definition
    - _Requirements: 1.1, 1.2, 1.4_

- [x] 2. Implement Web UI audio recording
  - [x] 2.1 Add microphone button to the input area in webui/index.html
    - Add a microphone button element in the `.input-area` div between the text input and Send button
    - Style the button with a microphone icon (🎤 emoji or SVG), matching existing button styling (border-radius: 24px, gradient background)
    - Add CSS for recording state: `.mic-btn.recording` with pulsing red animation
    - Add CSS for disabled state and speaker animation indicator for playback
    - _Requirements: 2.1, 2.2, 5.2_

  - [x] 2.2 Implement AudioRecorder module in webui/index.html
    - Create `AudioRecorder` object with `isRecording`, `audioContext`, `mediaStream`, `scriptProcessor`, `pcmBuffers`, `maxDurationMs` (15000), and `timeoutId` properties
    - Implement `isSupported()` method checking for `navigator.mediaDevices.getUserMedia` and `AudioContext`/`webkitAudioContext` availability
    - Implement `start()` method: call `getUserMedia({audio: true})`, create `AudioContext` with `sampleRate: 16000`, connect source → ScriptProcessorNode (bufferSize 4096), collect Float32Array chunks, set 15-second auto-stop timeout
    - Implement `stop()` method: clear timeout, stop media tracks, disconnect nodes, close AudioContext, concatenate Float32 buffers, convert to Int16 PCM (multiply by 0x7FFF, clamp to [-32768, 32767]), return as ArrayBuffer
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.7_

  - [x] 2.3 Implement error handling for unsupported browsers and denied permissions
    - In `AudioRecorder.start()`, catch `NotAllowedError` → show "Microphone access denied", disable mic button
    - In `AudioRecorder.start()`, catch `NotFoundError` → show "No microphone found", disable mic button
    - In `AudioRecorder.isSupported()` returning false → disable mic button on page load, show "Browser does not support voice input"
    - Ensure text-only mode continues working when voice is unavailable
    - _Requirements: 2.6_

- [x] 3. Implement Web UI voice interaction controller
  - [x] 3.1 Implement VoiceController with RecognizeUtterance API integration
    - Create `VoiceController` object with `sendAudio(pcmBuffer)`, `playAudioResponse(audioBlob)`, `decodeResponseMessages(response)`, and `toggleRecording()` methods
    - In `sendAudio()`: call `lexClient.recognizeUtterance()` with params: `botId`, `botAliasId`, `localeId`, `sessionId` (shared with text mode), `requestContentType: "audio/x-l16; sample-rate=16000; channel-count=1"`, `responseContentType: "audio/mpeg"`, `inputStream: pcmBuffer`
    - In `decodeResponseMessages()`: decode response.messages via `atob → decodeURIComponent → JSON.parse`, extract message content array
    - In `toggleRecording()`: if not recording → call `AudioRecorder.start()` and update UI state; if recording → call `AudioRecorder.stop()`, get PCM buffer, call `sendAudio()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.5_

  - [x] 3.2 Implement audio playback via HTMLAudioElement
    - In `playAudioResponse()`: create Blob from audioStream with type "audio/mpeg", create Object URL, instantiate `new Audio(url)`
    - Set `audio.onended` handler: revoke Object URL, re-enable all input controls, clear speaker animation
    - Set `audio.onerror` handler: revoke Object URL, display text transcript as fallback, re-enable controls
    - Call `audio.play()` and handle autoplay policy rejection (catch promise rejection → fall back to text display)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

  - [x] 3.3 Implement UI state management for dual-mode interaction
    - Create `setUIState(state)` function managing states: "idle", "recording", "processing", "playing", "error"
    - In "recording" state: disable text input + Send button, show pulsing red mic icon
    - In "processing" state: disable all controls, show typing indicator
    - In "playing" state: disable all controls, show speaker animation
    - In "error" state: re-enable controls, show error message in chat
    - Wire mic button click to `VoiceController.toggleRecording()`
    - Display voice-transcribed messages (from `inputTranscript`) in the same chat list as text messages
    - Ensure `sessionId` is the same variable used by both `sendMessage()` (text) and `VoiceController.sendAudio()` (voice)
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 3.4 Implement timeout and error handling for RecognizeUtterance calls
    - Add 30-second timeout for RecognizeUtterance API call (abort and show error if exceeded)
    - Handle API errors (4xx, 5xx, network failures): display error message in chat, re-enable all controls
    - Handle missing audioStream in response: decode and display text from response headers, re-enable controls
    - _Requirements: 3.5, 4.7_

- [x] 4. Checkpoint - Verify template and Web UI integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Write property-based tests for voice features
  - [x] 5.1 Write property test for PCM encoding signal preservation
    - **Property 1: PCM encoding preserves signal characteristics**
    - Create test in `tests/unit/test_voice_properties.py`
    - Extract `float32_to_int16()` conversion logic as a testable Python function mirroring the JavaScript implementation
    - Use hypothesis to generate random Float32 arrays (values in [-1.0, 1.0], lengths 0 to 16000)
    - Assert: output length equals input length, all values in [-32768, 32767], sign preserved for non-zero samples, relative magnitude ordering preserved
    - Use `@settings(max_examples=100)` and tag with `Feature: lex-polly-voice, Property 1: PCM encoding preserves signal characteristics`
    - **Validates: Requirements 2.5**

  - [x] 5.2 Write property test for response message decode round-trip
    - **Property 2: Response message decode is a round-trip of encode**
    - Add test to `tests/unit/test_voice_properties.py`
    - Implement Python encode function: `json.dumps → urllib.parse.quote → base64.b64encode`
    - Implement Python decode function: `base64.b64decode → urllib.parse.unquote → json.loads`
    - Use hypothesis to generate random message arrays (0-5 messages, arbitrary unicode strings including special chars and empty strings)
    - Assert: decode(encode(messages)) == messages
    - Use `@settings(max_examples=100)` and tag with `Feature: lex-polly-voice, Property 2: Response message decode is a round-trip of encode`
    - **Validates: Requirements 4.5**

  - [x] 5.3 Write property test for session ID invariant across interaction modes
    - **Property 3: Session ID invariant across interaction modes**
    - Add test to `tests/unit/test_voice_properties.py`
    - Simulate a sequence of text and voice interactions (1-20 actions in random order)
    - Track the sessionId passed to each mocked API call (both recognizeText and recognizeUtterance)
    - Assert: all captured sessionId values are identical
    - Use `@settings(max_examples=100)` and tag with `Feature: lex-polly-voice, Property 3: Session ID invariant across interaction modes`
    - **Validates: Requirements 5.5**

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The Lambda function (`src/handler.py`) requires NO changes — it already returns PlainText messages that Lex feeds to Polly
- Cognito permissions already include `lex:RecognizeUtterance` — no IAM changes needed
- The `deploy-webui.sh` script requires no changes — it already injects all needed config values (region, bot ID, alias ID, Cognito pool ID)
- Property tests use Python `hypothesis` library to mirror and validate the JavaScript logic
- The Web UI is a single `index.html` file with inline JavaScript — all voice modules are added inline
- The existing `sessionId` variable is shared between text and voice flows to preserve conversation continuity

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["2.2", "2.3"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "3.4"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3"] }
  ]
}
```
