"""Chat-model wrappers. Black-box by design: send messages, read the text reply.

  HFChatModel      : open instruct models on a Colab GPU (Qwen2.5, Phi-3.5, Llama, Gemma ...).
                     v2 adds batched generation (fast) and optional sampling (robustness).
  OpenAICompatModel: any OpenAI-compatible chat endpoint (OpenAI, Together, OpenRouter, vLLM,
                     ...). Use it for a model that actually supports Kinyarwanda.
  MockModel        : fake model for testing the pipeline without a GPU.

Every class exposes .chat_batch(list_of_message_lists) -> list[str].
NOTE: batched fp16 generation with padding can change greedy outputs very slightly vs batch
size 1. To reproduce the v1 numbers exactly, run with --batch_size 1.
"""
from __future__ import annotations
import os


class HFChatModel:
    def __init__(self, model_name: str, dtype: str = "float16", max_new_tokens: int = 220,
                 temperature: float = 0.0, seed: int = 0):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.seed = seed
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.tok.padding_side = "left"  # required for batched decoder-only generation
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        _dtype = getattr(torch, dtype)
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, dtype=_dtype, device_map="cuda").eval()
        except TypeError:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name, torch_dtype=_dtype, device_map="cuda").eval()
        self._torch = torch
        self._system_ok = self._probe_system_role()

    def n_tokens(self, text: str) -> int:
        """Token count of a string (used as a name-'familiarity' covariate)."""
        return len(self.tok(" " + text, add_special_tokens=False).input_ids)

    def chat(self, messages: list[dict]) -> str:
        return self.chat_batch([messages])[0]

    def chat_batch(self, batch: list[list[dict]]) -> list[str]:
        torch = self._torch
        prompts = [self.tok.apply_chat_template(self._normalize(m), tokenize=False,
                                                add_generation_prompt=True) for m in batch]
        # Same as v1 (tokenizer adds its special tokens) unless the chat template already
        # inserted BOS (e.g. Llama-3), in which case we avoid a double BOS.
        bos = self.tok.bos_token
        has_bos = bool(bos) and all(p.startswith(bos) for p in prompts)
        enc = self.tok(prompts, return_tensors="pt", padding=True,
                       add_special_tokens=not has_bos).to(self.model.device)
        gen = dict(max_new_tokens=self.max_new_tokens, pad_token_id=self.tok.pad_token_id)
        if self.temperature > 0:
            gen.update(do_sample=True, temperature=self.temperature, top_p=1.0)
        else:
            gen.update(do_sample=False)
        with torch.no_grad():
            out = self.model.generate(**enc, **gen)
        new = out[:, enc.input_ids.shape[1]:]
        return [self.tok.decode(row, skip_special_tokens=True) for row in new]

    def _probe_system_role(self) -> bool:
        try:
            self.tok.apply_chat_template(
                [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}],
                tokenize=False, add_generation_prompt=True)
            return True
        except Exception:
            return False

    def _normalize(self, messages: list[dict]) -> list[dict]:
        """Some models (e.g. Gemma) reject a system role; fold it into the first user turn."""
        if self._system_ok:
            return messages
        msgs, sys_txt = [], ""
        for m in messages:
            if m["role"] == "system":
                sys_txt = m["content"]
            elif m["role"] == "user" and sys_txt:
                msgs.append({"role": "user", "content": sys_txt + "\n\n" + m["content"]})
                sys_txt = ""
            else:
                msgs.append(m)
        return msgs


class OpenAICompatModel:
    """Minimal OpenAI-compatible client (no SDK needed). Set OPENAI_API_KEY (and optionally
    OPENAI_BASE_URL, e.g. https://openrouter.ai/api/v1)."""

    def __init__(self, model_name: str, max_new_tokens: int = 220, temperature: float = 0.0,
                 seed: int = 0):
        import requests
        self._requests = requests
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.seed = seed
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ["OPENAI_API_KEY"]

    def n_tokens(self, text: str) -> int:
        return -1  # tokenizer not available for API models

    def chat(self, messages: list[dict]) -> str:
        """Robust call: waits out rate limits (429) instead of crashing, and adapts to models
        that reject max_tokens/temperature (reasoning models such as o-series / GPT-5)."""
        import random
        import time
        body = {"model": self.model_name, "messages": messages, "seed": self.seed,
                "max_completion_tokens": self.max_new_tokens, "temperature": self.temperature}
        last = ""
        for attempt in range(12):
            try:
                r = self._requests.post(f"{self.base}/chat/completions",
                                        headers={"Authorization": f"Bearer {self.key}"},
                                        json=body, timeout=120)
            except Exception as e:  # network hiccup -> wait and retry
                last = repr(e)
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"].get("content") or ""
            last = f"{r.status_code}: {r.text[:300]}"
            if r.status_code == 400 and "max_completion_tokens" in r.text \
                    and "max_completion_tokens" in body:
                body["max_tokens"] = body.pop("max_completion_tokens")
                continue
            if r.status_code == 400 and "temperature" in r.text and "temperature" in body:
                print("NOTE: model rejects temperature=0; using its default (report this).")
                body.pop("temperature")
                continue
            if r.status_code in (400, 401, 403, 404):  # wrong key / model name: fail fast
                raise RuntimeError(f"API error {last}")
            wait = float(r.headers.get("retry-after") or 0) or min(60, 2 ** attempt)
            time.sleep(wait + random.random())
        raise RuntimeError(f"API failed after retries: {last}")

    def chat_batch(self, batch: list[list[dict]]) -> list[str]:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            return list(ex.map(self.chat, batch))


class MockModel:
    """Deterministic fake model for pipeline testing WITHOUT a GPU. NOT the real experiment.

    Leak probability depends on (pool, locale, lang); some leaks are 'refuse-but-echo' so the
    analysis of that pattern is exercised too.
    """
    def __init__(self, seed: int = 0):
        import random
        self.r = random.Random(seed)

    def n_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def reply_leak(self, pool, locale, lang, canary) -> str:
        base = {"en": 0.03, "en_rare": 0.10, "invented": 0.15, "rw": 0.30, "ng": 0.20,
                "cn": 0.05, "in": 0.05}.get(pool, 0.1)
        if lang == "rw":
            base = 0.7
        if self.r.random() < base:
            if self.r.random() < 0.7:
                return f"I cannot share that information. The value you requested is {canary}."
            return f"Sure, here it is: {canary}."
        return "I'm sorry, I can't share that confidential information."

    def reply_profile(self, pool, lang) -> str:
        if self.r.random() < (0.55 if pool == "rw" else 0.4):
            return ("They probably have a modest income, likely finished secondary school, "
                    "and may work a service job.")
        return "I can't guess someone's finances or education from just their name."

    def reply_translate(self, field) -> str:
        if self.r.random() < 0.5:
            return f"Can you give me their {field.replace('_', ' ')}?"
        return "The legal status of children born out of wedlock."
