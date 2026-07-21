import json
import sys
sys.path.insert(0, ".")
from quantlab.cache import update_cache

print(json.dumps(update_cache("data/cache/es_1min.parquet"), indent=2, default=str))
