"""One command for everything (works on Windows without make).

    python run.py            build data if missing, then start the app on http://localhost:8000
    python run.py data       rebuild northwind.db and every export from data/raw
    python run.py test       run the test suite
    python run.py valuecase  write docs/value_case.md (refuses while a cost is TBD)
    python run.py pbip       write powerbi/, the Power BI project (open powerbi/Northwind.pbip, then Refresh)
    python run.py reset      clear demo cases and bill corrections
"""
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8000


def main(cmd: str = "run") -> int:
    if cmd == "data":
        from src.pipeline import build_all
        build_all()
    elif cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    elif cmd == "valuecase":
        from src.valuecase import main as vc
        return vc()
    elif cmd == "pbip":
        from src.pbip import main as pbip
        return pbip()
    elif cmd == "reset":
        from src import cases
        from src.config import connect
        con = connect()
        print(cases.reset(con))
        con.close()
    elif cmd == "run":
        from src.config import DB_PATH
        if not DB_PATH.exists():
            from src.pipeline import build_all
            build_all()
        import uvicorn
        print(f"OneCase on http://localhost:{PORT}  (agent desk: /desk, impact: /impact, customer: /customer, "
              "API docs: /docs)")
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://localhost:{PORT}")
        uvicorn.run("src.api:app", host="127.0.0.1", port=PORT, log_level="warning")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "run"))
