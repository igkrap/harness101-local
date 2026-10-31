#!/usr/bin/env python3
"""Harness v1: a chat loop. The array IS the conversation.

Chapter 1 of Harness Engineering 101.
Requires: ANTHROPIC_API_KEY in the environment. Zero dependencies.
"""
import json
import os
import urllib.request

import local_llm, sandbox                    # LOCAL: wire adapter + workspace boundary
MODEL = local_llm.MODEL                      # LOCAL: gemma-4-26B-A4B (MoE) via mlx_lm.server
SYSTEM = "You are a concise assistant."


def call_llm(messages):
    body = {"model": MODEL, "max_tokens": 4096,
            "system": SYSTEM, "messages": messages}
    return local_llm.create(body)            # LOCAL: same body, local MoE brain


def main():
    messages = []                                   # the entire "session"
    while True:
        user_text = input("\nyou> ").strip()
        if user_text in ("/quit", ""):
            break
        if user_text == "/clear":
            messages = []                           # "new conversation"
            continue
        messages.append({"role": "user", "content": user_text})
        reply = call_llm(messages)                  # resend EVERYTHING
        text = "".join(b["text"] for b in reply["content"]
                       if b["type"] == "text")
        messages.append({"role": "assistant", "content": reply["content"]})
        print(f"\nassistant> {text}")


if __name__ == "__main__":
    main()
    local_llm.report()                          # LOCAL: tokens, cache, speed
