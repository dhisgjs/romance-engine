import subprocess, sys, pathlib
EXE = r"C:\Users\17838\.codex\tmp\arg0\codex-arg04IyD4J\..\..\..\packages\app-server-daemon\releases\0.160.0-x86_64-pc-windows-msvc\bin\codex.exe"
patch = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
r = subprocess.run([EXE, "--codex-run-as-apply-patch", patch], capture_output=True, text=True, encoding="utf-8")
print(r.stdout or "", r.stderr or "")
sys.exit(r.returncode)