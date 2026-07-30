import subprocess

cmd = [
    r"C:\Users\sasa2\AppData\Local\agy\bin\agy.exe",
    "--model", "Gemini 3.6 Flash (Medium)",
    "--dangerously-skip-permissions",
    "--output-format", "stream-json",
    "--json-schema", '{"type":"object","properties":{"hello":{"type":"string"}}}',
    "-p", "Say hello"
]
res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
