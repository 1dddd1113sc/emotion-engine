import json

path = r"D:\OpenClawData\.openclaw\agents\main\sessions\4c1ffa9b-439f-461e-aad0-16a4aff941ef.jsonl"

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}\n")

for i, line in enumerate(lines):
    try:
        data = json.loads(line)
        content = json.dumps(data, ensure_ascii=False)
        
        # Look for model references
        if "resolvedModel" in content:
            model = data.get("resolvedModel", "N/A")
            provider = data.get("provider", "N/A")
            print(f"Line {i}: resolvedModel={model}, provider={provider}")
        
        # Look for spawn events
        if "sessions_spawn" in content:
            args = data.get("arguments", {})
            if "model" in str(args):
                print(f"Line {i}: SPAWN with model={args.get('model', 'N/A')}")
    except:
        pass
