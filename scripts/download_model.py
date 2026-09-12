"""Download public Qwen files to this project, pinning the upstream commit.

No authentication, remote Python, pickle, or unrelated cache access.
"""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEST = ROOT / "experiments/models/Qwen2.5-0.5B-Instruct"
FILES = ("config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
         "vocab.json", "merges.txt", "model.safetensors", "README.md", "LICENSE")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{MODEL}", timeout=60) as response:
        info = json.load(response)
    revision = info["sha"]
    available = {entry["rfilename"] for entry in info["siblings"]}
    provenance = {"model": MODEL, "revision": revision, "files": {}}
    (DEST / "download-provenance.json").write_text(json.dumps(provenance, indent=2))
    for filename in FILES:
        if filename not in available:
            continue
        target = DEST / filename
        start = time.perf_counter()
        # Existing complete files are valid only if their recorded upstream revision matches.
        for attempt in range(3):
            try:
                temporary = target.with_suffix(target.suffix + ".part")
                with urllib.request.urlopen(
                    f"https://huggingface.co/{MODEL}/resolve/{revision}/{filename}", timeout=120
                ) as response, temporary.open("wb") as out:
                    digest = hashlib.sha256()
                    while block := response.read(1024 * 1024):
                        out.write(block)
                        digest.update(block)
                temporary.replace(target)
                break
            except Exception as exc:
                print(json.dumps({"file": filename, "attempt": attempt + 1, "error": str(exc)}), flush=True)
                if attempt == 2:
                    raise
        provenance["files"][filename] = {"sha256": digest.hexdigest(), "bytes": target.stat().st_size,
                                          "download_seconds": time.perf_counter() - start}
        (DEST / "download-provenance.json").write_text(json.dumps(provenance, indent=2))
        print(json.dumps({"file": filename, **provenance["files"][filename]}), flush=True)
    output = ROOT / "experiments/model-provenance.json"
    output.write_text(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
