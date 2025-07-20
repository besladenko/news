import os

def ensure_dir_exists(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
