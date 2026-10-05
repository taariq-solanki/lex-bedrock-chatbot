# Requirements Document

## Introduction

This feature adds voice interaction capabilities to the existing Lex V2 Bedrock chatbot by enabling Lex's built-in Polly voice synthesis and updating the Web UI to support bidirectional audio (microphone input and spoken responses). Lex V2 natively integrates with Amazon Polly when a voice is configured on the bot locale — the Lambda function requires no changes since it already returns PlainText messages that Lex feeds directly to Polly for synthesis.

## Glossary

- **Lex_Bot**: The Amazon Lex V2 bot resource defined in the SAM template that handles conversational interactions
- **Bot_Locale**: The language-specific configuration of the Lex bot (en_US) where voice settings are declared
- **Polly_Voice**: An Amazon Polly neural voice identifier (e.g., "Danielle") configured on the Bot Locale for speech synthesis
- **RecognizeUtterance_API**: The Lex V2 Runtime API that accepts audio input and returns audio output, enabling voice-based interaction
- **Web_UI**: The single-page HTML/CSS/JS browser application that provides the chat interface
- **MediaRecorder**: The browser Web API used to capture microphone audio input as PCM or Opus-encoded audio
- **Audio_Playback**: The browser mechanism (Web Audio API or HTMLAudioElement) used to play back Polly-synthesized speech from Lex responses
- **SAM_Template**: The AWS SAM template.yaml file defining all infrastructure resources for this project

## Requirements

### Requirement 1: Configure Polly Voice on Lex Bot Locale

**User Story:** As a chatbot operator, I want the Lex bot locale to have a Polly neural voice configured, so that Lex can synthesize spoken responses via Polly without any application-level code changes.

#### Acceptance Criteria

1. THE SAM_Template SHALL declare a `VoiceSettings` block on the en_US Bot_Locale with a `VoiceId` property whose value references the PollyVoiceId CloudFormation parameter
2. THE SAM_Template SHALL set the `Engine` property within `VoiceSettings` to "neural"
3. WHEN the SAM stack is deployed, THE Bot_Locale SHALL be configured to synthesize all PlainText response messages defined in that locale as audio using the Polly voice specified by the `VoiceSettings` block
4. THE SAM_Template SHALL expose the Polly voice identifier as a CloudFormation parameter named `PollyVoiceId` with a default value of "Danielle", allowing operators to override the voice at deploy time without modifying the template
5. IF an operator supplies a PollyVoiceId value that is not a valid neural-capable Polly voice for the en_US locale, THEN THE CloudFormation stack SHALL fail to deploy and return a validation error indicating the unsupported voice

### Requirement 2: Web UI Voice Input via Microphone

**User Story:** As a chatbot user, I want to speak to the chatbot using my microphone, so that I can interact hands-free without typing.

#### Acceptance Criteria

1. THE Web_UI SHALL display a microphone button in the input area alongside the text input field and Send button that allows users to start voice recording
2. WHEN the user clicks the microphone button, THE Web_UI SHALL request microphone access via the browser MediaRecorder API and begin capturing audio
3. WHILE recording is active, THE Web_UI SHALL display a visual indicator (pulsing red icon) and disable the text input field and Send button until recording stops
4. WHEN the user clicks the microphone button again to stop recording, THE Web_UI SHALL stop the MediaRecorder and prepare the captured audio for transmission
5. THE Web_UI SHALL encode captured audio in a format accepted by the RecognizeUtterance_API (PCM 16-bit 16kHz mono, or Opus-encoded OGG)
6. IF the browser does not support MediaRecorder or microphone access is denied, THEN THE Web_UI SHALL display an error message stating the specific reason (e.g., "Microphone access denied" or "Browser does not support voice input") and continue operating in text-only mode with the microphone button disabled
7. IF the recording duration exceeds 15 seconds, THEN THE Web_UI SHALL automatically stop recording and submit the captured audio

### Requirement 3: Send Audio to Lex via RecognizeUtterance API

**User Story:** As a chatbot user, I want my spoken audio sent to Lex for processing, so that the bot understands what I said and responds appropriately.

#### Acceptance Criteria

1. WHEN voice recording completes, THE Web_UI SHALL disable the microphone button, text input, and Send button, then call the RecognizeUtterance_API with the captured audio as the `inputStream` parameter
2. WHEN calling the RecognizeUtterance_API, THE Web_UI SHALL set the `requestContentType` parameter to match the audio encoding format used by the MediaRecorder (e.g., "audio/x-l16; sample-rate=16000; channel-count=1" for PCM, or "audio/ogg" for Opus)
3. WHEN calling the RecognizeUtterance_API, THE Web_UI SHALL set the `responseContentType` parameter to "audio/mpeg" to receive Polly-synthesized speech in the response
4. WHEN calling the RecognizeUtterance_API, THE Web_UI SHALL include the `botId`, `botAliasId`, `localeId`, and `sessionId` parameters using the same values as the text-mode RecognizeText API calls
5. IF the RecognizeUtterance_API call fails or does not respond within 30 seconds, THEN THE Web_UI SHALL display an error message indicating the failure reason and re-enable the microphone button, text input, and Send button so the user can retry

### Requirement 4: Play Back Audio Responses

**User Story:** As a chatbot user, I want to hear the bot's responses spoken aloud, so that I have a fully conversational voice experience.

#### Acceptance Criteria

1. WHEN the RecognizeUtterance_API returns a response containing an `audioStream`, THE Web_UI SHALL decode the audio stream into a playable format and play it through the browser's audio output using an HTMLAudioElement
2. THE Web_UI SHALL play the MPEG audio stream received from the API response without requiring additional codec installation by the user
3. WHILE audio playback is in progress, THE Web_UI SHALL display a visual indicator (e.g., speaker icon animation) showing that the bot is speaking
4. WHEN audio playback completes, THE Web_UI SHALL re-enable the microphone button, text input, and Send button for the next user interaction
5. IF the response contains `messages` in the HTTP headers, THE Web_UI SHALL decode the base64-encoded messages, extract the text content, and display it in the chat message area
6. IF audio playback fails (e.g., unsupported format, browser restriction), THEN THE Web_UI SHALL display the text transcript and re-enable input controls without blocking the user
7. IF the RecognizeUtterance_API response does not contain an audioStream, THEN THE Web_UI SHALL display the text transcript from the response headers and re-enable input controls

### Requirement 5: Dual-Mode Interaction (Text and Voice)

**User Story:** As a chatbot user, I want to seamlessly switch between typing and speaking, so that I can choose whichever interaction mode suits my current context.

#### Acceptance Criteria

1. THE Web_UI SHALL retain the existing text input field and Send button for text-based interactions using the RecognizeText API
2. THE Web_UI SHALL place the microphone button in the same input area row as the text input field and Send button, visible without scrolling, so that the user can reach all three controls without navigating away from the input area
3. WHEN the user submits text via the input field, THE Web_UI SHALL continue using the existing RecognizeText API flow (no audio response)
4. WHEN the user submits audio via the microphone, THE Web_UI SHALL use the RecognizeUtterance_API flow and play back the audio response
5. THE Web_UI SHALL maintain a single sessionId across both text and voice interactions to preserve conversation continuity
6. WHILE a voice recording is in progress, THE Web_UI SHALL disable the text input field and Send button until the recording is stopped and the response is received
7. WHILE a text or voice request is being processed, THE Web_UI SHALL disable both the Send button and microphone button until the response is received and displayed
8. THE Web_UI SHALL display both text-submitted messages and voice-transcribed messages in the same chat message list in chronological order

### Requirement 6: Cognito Permissions for RecognizeUtterance

**User Story:** As a chatbot operator, I want the Cognito unauthenticated role to support the RecognizeUtterance API, so that browser users can interact via voice without authentication changes.

#### Acceptance Criteria

1. THE SAM_Template SHALL include `lex:RecognizeUtterance` in the Cognito unauthenticated role's IAM policy actions, scoped to the deployed Lex bot alias resource ARN
2. WHEN a browser client sends a RecognizeUtterance request using Cognito unauthenticated credentials, THE Lex_Bot SHALL return a successful response (HTTP 200) containing audio or text output without authorization errors
3. IF the Cognito credentials used for a RecognizeUtterance request are invalid or expired, THEN THE Lex_Bot SHALL reject the request with an authorization error and not process the utterance
