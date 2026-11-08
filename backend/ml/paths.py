from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
WORK_DIR = ML_DIR / "data"
FIRMS_DIR = WORK_DIR / "firms"
WEATHER_CACHE = WORK_DIR / "weather_cache.json"
WFIGS_PATH = WORK_DIR / "wfigs_ks.json"
HISTORY_DB = WORK_DIR / "history.sqlite"
DATASET_PATH = WORK_DIR / "dataset.csv"

BACKEND_DIR = ML_DIR.parent
MODEL_DIR = BACKEND_DIR / "data" / "model"
LAYERS_DIR = BACKEND_DIR / "data" / "layers"
REPORT_PATH = ML_DIR / "report.md"

KS_BBOX = (-102.05, 36.99, -94.59, 40.00)
