#!/bin/zsh
# Keep the local Qwen MLX server up: relaunch with the same settings whenever it exits (e.g. Metal OOM).
STATE="$(cd "$(dirname "$0")/.." && pwd)/state"
PY="$HOME/.local/share/mlx-server/venv/bin/python"
echo $$ > "$STATE/qwen-supervisor.pid"
while true; do
  "$PY" -m mlx_lm.server --model mlx-community/Qwen3.8-27B-4bit --host 127.0.0.1 --port 8099 \
    --max-tokens 8192 --prefill-step-size 1024 --prompt-cache-size 4 --prompt-cache-bytes 3GB \
    --decode-concurrency 1 --prompt-concurrency 1 \
    --chat-template-args '{"enable_thinking": false, "reasoning_effort": "medium"}' \
    --log-level INFO --temp 0.7 --top-p 0.8 --top-k 20 >> "$STATE/qwen-model-server.log" 2>&1 &
  echo $! > "$STATE/qwen-model-server.pid"
  wait $!
  echo "$(date '+%F %T') qwen server exited with $?; restarting in 5s" >> "$STATE/qwen-model-server.log"
  sleep 5
done
