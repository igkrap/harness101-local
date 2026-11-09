"""Executed in the existing local server environment; no model weights are loaded."""
import json
import sys
from tokenizers import Tokenizer

data = json.load(sys.stdin)
tokenizer = Tokenizer.from_file(data['tokenizer'])
print(json.dumps({'text': tokenizer.decode(data['ids'], skip_special_tokens=False)}, ensure_ascii=False))
