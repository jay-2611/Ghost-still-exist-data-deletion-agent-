python-c "import os; from pathlib import Path; p=Path('.env'); print('env file:', p.exists()); print('keys:', [l.split('=')[0] for l in p.read_text().splitlines() if '=' in l and not l.startswith('#')])"

