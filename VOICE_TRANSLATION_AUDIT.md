# Nalana Voice-To-Operation Translation Audit

This note answers what currently translates voice commands into Blender operations, whether Nalana is using an LLM now, and how that differs from other providers such as Meshy.

## What Translates The Voice Commands Now

Nalana is using a **hybrid pipeline**, not a single always-on LLM translator.

### 1. Speech-to-text

Raw audio is first converted into text by a local `whisper-cli` wrapper around `faster-whisper`.

- `transcribe()` runs `WHISPER_CLI` with `--model`, `--language`, and `--input`, then extracts the JSON field `"text"`. Source: `voice_to_blender.py:3078-3113`
- The bundled whisper CLI explicitly imports `WhisperModel` from `faster_whisper`. Source: `addon/__init__.py:200-236`
- The README also describes this layer as local `faster-whisper` speech-to-text. Source: `README.md:70-73`

So for audio -> transcript, the tool is:

- **local speech model**: `faster-whisper`


### 2. Command translation

Once Nalana has transcript text, it does **not** immediately call an LLM. It first tries local, non-LLM logic.

The routing order in the main processing block is:

1. Try `_resolve_local_sequence()` first for fast offline command sequences. Source: `voice_to_blender.py:4604-4610`
2. If that fails, try `try_io_rules()` and `try_local_rules()` for local pattern/rule matches. Source: `voice_to_blender.py:4612-4624`
3. Only if those fail does it try the orchestrator / ReAct / GPT fallback path. Source: `voice_to_blender.py:4626-4719`

That means:

- **yes**, some commands use **no LLM at all**
- simple commands can be handled by local rules/regex-style logic
- more complex commands fall back to an AI model

The README architecture diagram matches this high-level flow:

- local rules first
- LLM fallback only when no local match is found

Source: `README.md:76-85`

### Compact decision tree

- audio -> `faster-whisper`
- text -> `_resolve_local_sequence()` if possible
- otherwise -> `try_io_rules()` / `try_local_rules()`
- otherwise -> orchestrator / ReAct / GPT fallback
- resulting JSON ops -> Blender RPC execution

## What Model/Provider Is Used Now

For the **LLM fallback path**, the code default is currently **OpenAI GPT-5**.

- `_get_ai_model_config()` sets `provider = "openai-gpt-5"` as the default. Source: `voice_to_blender.py:132-164`
- If Blender RPC preferences are available, the provider can be overridden at runtime with `rpc.get_ai_model_provider()`. Source: `voice_to_blender.py:143-156`
- `_call_unified_ai_api()` supports both OpenAI and Google Gemini providers. Source: `voice_to_blender.py:178-260`
- For OpenAI providers:
  - `openai-gpt-5` maps to model `"gpt-5"`
  - `openai-gpt-4o` maps to model `"gpt-4o"`

  Source: `voice_to_blender.py:218-249`

The standard GPT mapping path is `gpt_to_json()`, which turns the transcript plus scene context into Blender-op JSON. It is only used if `ENABLE_GPT_FALLBACK` is on and a valid provider key exists. Source: `voice_to_blender.py:4024-4403`

### If a non-default provider is selected

The code supports **Google Gemini** as an alternative LLM provider.

- `_call_unified_ai_api()` has a Google branch for Gemini. Source: `voice_to_blender.py:251-260`
- `gpt_to_json()` checks for either OpenAI or Gemini keys depending on the selected provider. Source: `voice_to_blender.py:4039-4051`

In the ReAct loop, if the primary provider is Google and it fails, the system can switch to **OpenAI GPT-4o** as a fallback for the remaining iterations, as long as an OpenAI key is available. Source: `voice_to_blender.py:2391-2466`

So the most accurate answer is:

- **default in code**: OpenAI GPT-5
- **runtime-selectable alternative**: Google Gemini
- **failure fallback in ReAct**: OpenAI GPT-4o after Gemini failure

One subtle note: the README still describes the LLM fallback as “Gemini Pro 3 / GPT-4o,” but the current code default is `openai-gpt-5`, so the docs are slightly behind the implementation. Sources: `README.md:82-85`, `voice_to_blender.py:139-164`

## What Is Not The Translator

### Meshy is not the voice-command translator

`config/config.json` sets:

```json
"active_provider": "meshy"
```

Source: `config/config.json:1-35`

But this is a **different subsystem**. Meshy is Nalana’s text/image-to-3D provider pipeline, not the thing in `voice_to_blender.py` that interprets ordinary voice commands into Blender operations.

Evidence:

- `config/config.json` defines a Meshy provider with model `v5` and text/image-to-3D endpoints. Source: `config/config.json:4-31`
- `nalana_core/config.py` also defaults `active_provider` to `"meshy"` for the provider pipeline config. Source: `nalana_core/config.py:3-10`
- The local voice-command translator logic in `voice_to_blender.py` is separate and uses:
  - local rules
  - OpenAI / Gemini fallback
  - Blender RPC command execution

### Bottom line

Nalana is **not** using one single tool for all command translation.

- **speech recognition**: local `faster-whisper`
- **simple command translation**: local rule-based logic, no LLM
- **complex command translation**: OpenAI/Gemini LLM fallback
- **separate provider system**: Meshy for 3D generation workflows, not the main voice-command-to-Blender-op translator

So if you ask, “What tool is translating voice commands into Blender operations right now?” the most accurate answer is:

- **for simple commands**: local rules, no model
- **for harder commands**: an LLM fallback, defaulting to **OpenAI GPT-5** in code, with Gemini supported as an alternative
- **for audio transcription**: `faster-whisper`
- **not Meshy**

