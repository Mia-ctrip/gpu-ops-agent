import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

#retry times
RETRY_TIMES=5

#deepseek
DEEP_SEEK_MODEL_NAME="deepseek-v4-pro"
DEEP_SEEK_BASE_URL="https://api.deepseek.com"

DEEP_SEEK_MODEL_NAME="deepseek-v4-flush"
DEEP_SEEK_BASE_URL="https://api.deepseek.com"


#minimax
MINI_MAX_MODEL_NAME="minimax m3"
MINI_MAX_BASE_URL="https://api.minimax.cn/v1"


def get(model_name, model_supplier):
    env_key = model_name.replace("-","_")
    api_key = os.environ.get(env_key)
    base_url = globals().get(model_supplier.upper() + "_BASE_URL")
    return api_key, base_url