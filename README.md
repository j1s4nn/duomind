# DuoMind

**A local OpenAI-compatible server that pairs a small LLM with TypeSafe AI's Jev for smarter classification.**
<p align="center"><img src="docs/figures/banner.png" alt="DuoMind — dual-system local AI server (System 1 + System 2), OpenAI-compatible and almost free" width="800"></p>
DuoMind combines two AI systems:
- **System 2 (Reasoning)**: A small local LLM via llama.cpp for text generation and reasoning
- **System 1 (Classification)**: Jev, TypeSafe AI's fast classification API for ALL decision-making

This division of labor lets a small local model punch above its weight by outsourcing classification to Jev while keeping generation private and local.

<p align="center">
  <img src="docs/images/architecture.png" alt="DuoMind architecture" width="700">
</p>

---

## What You Need

- **Windows 11** (primary target; Linux/macOS may work but untested)
- **Python 3.11+** with `pip`
- **At least 25GB free disk space** (models + llama.cpp + cache)
- **8GB+ RAM recommended** (12GB+ for best experience)
- **NVIDIA GPU with 2GB+ VRAM recommended** (6GB+ ideal; CPU fallback available but slow)
- **Internet connection** for setup and Jev API calls
- **Jev API key** from [TypeSafe AI](https://console.typesafe.ai) (paid service, very cheap)

---

## ⚠️ Important Cautions

### Disk Space
- Each model: 1.5-3GB
- llama.cpp binaries: ~500MB
- Cache and logs: 100MB+
- **Recommended: 25GB+ free space**

### RAM and VRAM
- **6GB VRAM**: Fits 2-4B models comfortably
- **2-4GB VRAM**: Use 2B models only
- **No NVIDIA GPU**: Falls back to CPU mode (very slow, 10-50x slower)
- **12GB RAM is tight**: Close browsers and other apps while running
- **Only one model runs at a time**

### OneDrive Warning
**CRITICAL**: This repo is in your OneDrive folder. DuoMind stores models, binaries, and cache in `%LOCALAPPDATA%\duomind` to avoid syncing gigabytes to the cloud. Do NOT move these files into OneDrive.

### Internet and Privacy
- **Setup requires internet** to download models and llama.cpp
- **Jev requires internet** for classification API calls
- **Privacy**: Your prompts are sent to TypeSafe AI's servers for classification. The LLM stays fully local. See "Privacy Notice" below.

### Jev is Paid and Early Access
- **Not free**: Jev charges for input tokens (output is free). Very cheap (~$0.001-0.01 per 1000 classifications).
- **Early access**: Limits and pricing may change without notice.
- **Requires API key**: Get one at [console.typesafe.ai](https://console.typesafe.ai).

---

## Privacy Notice

**Before using DuoMind, understand this:**

- DuoMind sends **your prompts and conversation context** to TypeSafe AI's Jev service for classification (e.g., "Does this request need reasoning?", "Is this safe?").
- This data **leaves your computer** and goes to TypeSafe's servers.
- The **local LLM stays fully local** and never sends data anywhere.
- TypeSafe's privacy policy applies to Jev: [https://typesafe.ai/privacy](https://typesafe.ai/privacy)

If you cannot accept this, do not use DuoMind.

---

## Step-by-Step Setup on Windows (From Zero)

### 1. Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.11 or 3.12 (latest stable)
3. Run the installer
4. **CRITICAL**: Check "Add python.exe to PATH" before clicking Install
5. Click "Install Now"

### 2. Verify Python Installation

Open **PowerShell** (search "PowerShell" in Start menu) and run:

```powershell
python --version
```

You should see `Python 3.11.x` or `3.12.x`. If not, Python is not in PATH—reinstall and check the box.

### 3. Download DuoMind

**Option A: Git clone (if you have Git)**
```powershell
git clone https://github.com/yourusername/duomind.git
cd duomind
```

**Option B: Download ZIP**
1. Click "Code" > "Download ZIP" on GitHub
2. Extract to `C:\Users\YourName\Desktop\duomind`
3. Open PowerShell and navigate:
```powershell
cd C:\Users\YourName\Desktop\duomind
```

### 4. Create Virtual Environment

```powershell
python -m venv .venv
```

### 5. Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

You should see `(.venv)` at the start of your prompt.

**If you get an error about execution policy**, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 6. Install DuoMind

```powershell
pip install -e .
```

This installs DuoMind and all dependencies. Takes 1-2 minutes.

### 7. Run Setup Wizard

```powershell
duomind setup
```

The wizard will guide you through:
- Hardware check
- Privacy acceptance
- Getting and testing your Jev API key
- Choosing an AI model
- Downloading llama.cpp and your chosen model

**Follow the on-screen instructions carefully.** Each step is numbered and explains what it does.

---

## How to Get a Jev API Key

1. Go to [https://typesafe.ai](https://typesafe.ai) to learn about Jev
2. Read the docs: [https://docs.typesafe.ai](https://docs.typesafe.ai)
3. Sign up at [https://console.typesafe.ai](https://console.typesafe.ai)
4. Create an API key in the console
5. Copy the key and paste it into `duomind setup` when prompted

The setup wizard will test the key before continuing.

---

## How to Connect Cline or Kilo Code

After setup completes, you'll see copy-paste settings. Use these:

### For Cline (VS Code)
1. Open Cline settings
2. Set **API Provider**: `OpenAI Compatible`
3. Set **Base URL**: `http://127.0.0.1:8000/v1`
4. Set **API Key**: (leave blank or any value)
5. Set **Model Name**: Use the model ID from setup (e.g., `phi-4-mini-q4`)

### For Kilo Code
Same settings as above. Kilo Code also uses OpenAI-compatible format.

---

## Daily Use

### Start DuoMind
```powershell
duomind start
```

The server runs in the background. You'll see:
```
✓ DuoMind server started (PID 12345)
Base URL: http://127.0.0.1:8000/v1
```

### Stop DuoMind
```powershell
duomind stop
```

### Check Status
```powershell
duomind status
```

Shows: backend, model, Jev status, server PID.

### View Logs
```powershell
duomind logs
```

### Switch Models
```powershell
duomind models list
duomind models switch
```

Choose a different model from your downloaded list. The server restarts automatically.

### Toggle Jev On/Off
```powershell
duomind jev off    # Use local fallback classifier
duomind jev on     # Re-enable Jev
duomind jev status # Check current state
```

Useful for comparing results with and without Jev.

---

## Comparing Jev ON vs OFF

Want to see if Jev actually helps? Run the benchmark:

```powershell
python scripts/benchmark.py
```

This runs the same prompts with Jev enabled and disabled, then reports:
- Latency difference
- Decision agreement
- Confidence scores

Requires a Jev API key. Use `--mock` flag to test without calling Jev.

---

## Troubleshooting

| **Problem** | **Cause** | **Fix** |
|-------------|-----------|---------|
| `python: command not found` | Python not in PATH | Reinstall Python, check "Add to PATH" |
| `duomind: command not found` | Virtual env not activated or install failed | Run `.\.venv\Scripts\Activate.ps1` then `pip install -e .` |
| Server won't start | Port 8000 already in use | Change port in config: `%LOCALAPPDATA%\duomind\config.toml` |
| "CUDA not found" | NVIDIA drivers missing or old | Update drivers from nvidia.com |
| Model download fails | Network issue or HuggingFace down | Retry later, check internet, try different model |
| Jev connection fails | Wrong API key or network issue | Check key at console.typesafe.ai, test internet |
| Out of VRAM | Model too large | Switch to smaller model: `duomind models switch` |
| Very slow generation | Using CPU fallback | Check GPU with `duomind doctor` |
| Cline/Kilo can't connect | Server not running or wrong URL | Run `duomind status`, verify URL matches |

---

## How to Delete Everything

To completely remove DuoMind:

```powershell
duomind uninstall
```

This deletes:
- `%LOCALAPPDATA%\duomind` (models, binaries, config, logs)
- Jev API key from Windows Credential Manager

The repo folder stays (delete manually if desired).

---

## Glossary

- **LLM**: Large Language Model. The local AI that generates text (like GPT, but smaller).
- **GGUF**: A model file format optimized for llama.cpp. Compressed and fast.
- **VRAM**: Video RAM on your GPU. Determines which models fit.
- **API**: Application Programming Interface. How programs talk to each other.
- **Base URL**: The web address where DuoMind's server listens (e.g., `http://127.0.0.1:8000/v1`).
- **System 1 / System 2**: Psychology terms. System 1 = fast, automatic (Jev). System 2 = slow, deliberate (LLM).
- **Jev**: TypeSafe AI's fast classification service. Answers multiple-choice, yes/no, and rating questions in 70-500ms.
- **Noul**: Jev's yes/no question type (returns probability 0-1).
- **Choice**: Jev's multiple-choice question type (pick one from list).
- **Score**: Jev's rating question type (numeric score with confidence).
- **Confidence**: How sure Jev is about its answer (0-1). Below threshold, DuoMind uses local fallback.
- **Fallback**: Simple rule-based classifier used when Jev is disabled, slow, or low-confidence.
- **Circuit breaker**: Safety mechanism. After 3 Jev failures in 60s, switches to fallback for 30s.

---

## FAQ

**Q: Can I use DuoMind without Jev?**  
A: No. Jev is core to DuoMind's design. Without it, you'd just have a basic llama.cpp wrapper. Use `duomind jev off` to test the local fallback, but it's not a full replacement.

**Q: How much does Jev cost?**  
A: Very cheap. Input tokens are metered (~$0.15 per million tokens), output is free. A typical request uses 50-500 tokens. Expect $0.01-0.10 per hour of heavy use. Check TypeSafe's pricing for current rates.

**Q: Is DuoMind affiliated with TypeSafe AI?**  
A: **No.** DuoMind is an unofficial community project. Not affiliated with or endorsed by TypeSafe AI.

**Q: Can I run DuoMind on macOS or Linux?**  
A: Maybe. Code should work, but untested. llama.cpp binaries and paths differ. Try at your own risk.

**Q: Why not use llama-cpp-python?**  
A: Avoids requiring users to compile C++ code. Prebuilt llama-server.exe works out-of-the-box.

**Q: Can I use models from Ollama?**  
A: Yes. Set `llm_backend = "ollama"` in config.toml and ensure Ollama is running. Not tested.

**Q: Will small models give good results?**  
A: Maybe. That's the experiment. Jev handling classification frees the small LLM to focus on generation. Results depend on your use case.

**Q: Can I see what decisions Jev made?**  
A: Yes. Check server logs or use `/v1/duomind/stats` endpoint. Headers `X-DuoMind-Jev` and `X-DuoMind-Decisions` show Jev status and decision count per request.

**Q: Can I add my own decision points?**  
A: Yes, but requires editing `src/duomind/decisions.py`. See `DECISION_REGISTRY`.

**Q: What if Jev is down?**  
A: Circuit breaker kicks in after 3 failures. Falls back to local rules. Requests don't fail.

---

## Honest Limits

- **No proof Jev improves small models** until you benchmark it yourself.
- **Early access software**: Jev is new, DuoMind is new, expect rough edges.
- **Models this small** (2-4B) will make mistakes. No magic.
- **Jev has no explanations**: Just numbers. You won't know *why* it classified something a certain way.
- **Latency**: Jev adds 70-500ms per request (batched). Slower than pure local.
- **Cost**: Jev is paid. If you make 1000 requests/day, expect $1-5/month (rough guess, depends on prompt size).
- **Privacy tradeoff**: Classification goes to cloud. If you need 100% local, this isn't it.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Acknowledgments

- [llama.cpp](https://github.com/ggerganov/llama.cpp) for local inference
- [TypeSafe AI](https://typesafe.ai) for Jev
- [Hugging Face](https://huggingface.co) for model hosting
- Model creators: Microsoft (Phi-4), Alibaba (Qwen), Google (Gemma), Meta (Llama)

---

**Unofficial community project. Not affiliated with or endorsed by TypeSafe AI.**
