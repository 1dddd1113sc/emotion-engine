import json

path = r"D:\OpenClawData\.openclaw\agents\main\sessions\4c1ffa9b-439f-461e-aad0-16a4aff941ef.jsonl"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Check spawn events at lines 876, 878, 880
for i in [876, 878, 880]:
    data = json.loads(lines[i])
    msg = data.get("message", {})
    content = msg.get("content", [])
    for item in content:
        if item.get("type") == "toolCall" and item.get("name") == "sessions_spawn":
            args = item.get("arguments", {})
            model = args.get("model", "NOT SET")
            label = args.get("label", "NOT SET")
            print(f"Line {i}: sessions_spawn")
            print(f"  model: {model}")
            print(f"  label: {label}")
            print()

# Check tool results at lines 877, 879, 881
for i in [877, 879, 881]:
    data = json.loads(lines[i])
    msg = data.get("message", {})
    content = msg.get("content", [])
    for item in content:
        if item.get("type") == "text":
            text = item.get("text", "")
            if "resolvedModel" in text:
                try:
                    result = json.loads(text)
                    rm = result.get("resolvedModel", "NOT FOUND")
                    rp = result.get("resolvedProvider", "NOT FOUND")
                    print(f"Line {i}: toolResult")
                    print(f"  resolvedModel: {rm}")
                    print(f"  resolvedProvider: {rp}")
                    print()
                except:
                    start = text.find("resolvedModel")
                    print(f"Line {i}: {text[start:start+80]}")
                    print()
