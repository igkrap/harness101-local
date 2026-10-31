#!/usr/bin/env python3
"""Harness v3: the agent loop. Call, execute, append, repeat.

Chapter 4 of Harness Engineering 101.
"""
import json
import os
import subprocess
import urllib.request

import local_llm, sandbox                    # LOCAL: wire adapter + workspace boundary
MODEL = local_llm.MODEL                      # LOCAL: gemma-4-26B-A4B (MoE) via mlx_lm.server
SYSTEM = ("You are a capable engineering agent working on the local machine. "
          "Use your tools to complete the user's task, then summarize what "
          "you did.")
MAX_ROUNDS = 50                                      # NEW: runaway-loop cap

TOOLS = [
    {"name": "read_file",
     "description": "Read a text file and return its contents.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
    {"name": "write_file",                           # NEW: change the world
     "description": "Write content to a file, replacing it if it exists.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "run_command",
     "description": "Run a shell command and return stdout+stderr.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
]


def call_llm(messages):
    body = {"model": MODEL, "max_tokens": 8192, "system": SYSTEM,
            "messages": messages, "tools": TOOLS}
    return local_llm.create(body)            # LOCAL: same body, local MoE brain


def execute_tool(name, args):
    try:
        if name == "read_file":
            return open(sandbox.path(args["path"])).read()
        if name == "write_file":
            with open(sandbox.path(args["path"]), "w") as f:
                f.write(args["content"])
            return f"wrote {len(args['content'])} bytes to {args['path']}"
        if name == "run_command":
            out = sandbox.run(args["command"], timeout=120)   # LOCAL: no-network container
            return (out) or "(no output)"
        return f"ERROR: unknown tool {name}"
    except Exception as e:
        return f"ERROR: {e}"


def run_turn(messages):
    """One user turn = as many model/tool rounds as the task needs."""
    for _ in range(MAX_ROUNDS):                      # NEW: the agent loop
        reply = call_llm(messages)
        messages.append({"role": "assistant", "content": reply["content"]})
        for block in reply["content"]:
            if block["type"] == "text" and block["text"].strip():
                print(f"\nassistant> {block['text']}")

        if reply["stop_reason"] != "tool_use":       # done: hand back to user
            return

        results = []                                 # run EVERY requested tool
        for block in reply["content"]:
            if block["type"] == "tool_use":
                print(f"[tool] {block['name']}({json.dumps(block['input'])[:120]})")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": execute_tool(block["name"], block["input"]),
                })
        messages.append({"role": "user", "content": results})
    print("\n[harness] hit MAX_ROUNDS, stopping this turn")


def main():
    messages = []
    while True:
        user_text = input("\nyou> ").strip()
        if user_text in ("/quit", ""):
            break
        messages.append({"role": "user", "content": user_text})
        run_turn(messages)


if __name__ == "__main__":
    main()
    local_llm.report()                          # LOCAL: tokens, cache, speed
