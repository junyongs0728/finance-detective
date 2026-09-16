"""Read per-model usage without exposing user questions or access codes."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finance_detective.rag import store
try:
    with store.connection() as db:
        rows=db.execute("""SELECT user_id,stage,model,status,count(*) AS calls,
            sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,
            sum(cached_input_tokens) AS cached_input_tokens,
            sum(actual_microusd)/1000000.0 AS known_estimated_usd,
            sum(CASE WHEN actual_microusd IS NULL THEN reserved_microusd ELSE 0 END)/1000000.0 AS held_usd
            FROM ai_calls WHERE created_at>=date_trunc('month',now())
            GROUP BY user_id,stage,model,status ORDER BY user_id,stage,model,status""").fetchall()
    print(json.dumps(rows,ensure_ascii=False,indent=2,default=str))
finally:store.close()
