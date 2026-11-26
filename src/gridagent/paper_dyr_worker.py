"""Separate interpreter for upstream imports (which use a top-level config module)."""
import json
import sys
from pathlib import Path


def main():
    source, work, harness = map(Path, sys.argv[1:4])
    sys.path.insert(0, str(harness))
    import dyr_tools

    gains = json.loads(sys.argv[4])
    if set(gains) != {"Kqp", "Kqi", "Kvp", "Kvi"}:
        raise ValueError("Exactly four original REECAU1 gains required")
    src, dst = source / "Solar.dyr", work / "Solar.dyr"
    original = src.read_text(encoding="utf-8")
    tokens, spans = dyr_tools._locate_record(original)
    if tokens[0] != "91003" or tokens[2].strip("'\"") != "S1":
        raise ValueError("Incorrect original REECAU1 model identity")
    result = dyr_tools.write_gains(dst, gains, work / "changes.jsonl", 1)
    changed = dst.read_text(encoding="utf-8")
    new_tokens, new_spans = dyr_tools._locate_record(changed)

    def mask(text, positions, indices):
        for i in sorted(indices, reverse=True):
            a, b = positions[i]
            text = text[:a] + "<GAIN>" + text[b:]
        return text

    if mask(original, spans, dyr_tools._gain_indices(tokens)) != mask(
            changed, new_spans, dyr_tools._gain_indices(new_tokens)):
        raise ValueError("Locked model fields changed")
    if (source / "Solar.sav").read_bytes() != (work / "Solar.sav").read_bytes():
        raise ValueError("Locked power-flow case changed")
    print(json.dumps({**result, "locked_fields_verified": True}))


if __name__ == "__main__":
    main()
