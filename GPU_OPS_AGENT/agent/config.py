import os

#retry times
RETRY_TIMES=5

#deepseek
DEEP_SEEK_MODEL_NAME="deepseek v4 pro"
DEEP_SEEK_BASE_URL=""

DEEP_SEEK_MODEL_NAME="deepseek v4 flush"
DEEP_SEEK_BASE_URL=""


#minimax
MINI_MAX_MODEL_NAME="minimax m3"
MINI_MAX_BASE_URL=""


def get(model_name, model_supplier):
    env_key = model_name.upper().replace(" ", "_") + "_API_KEY"
    api_key = os.environ.get(env_key)
    base_url = globals().get(model_supplier.upper() + "_BASE_URL")
    return api_key, base_url