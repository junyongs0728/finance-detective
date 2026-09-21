"""Add local database and Agent settings without replacing existing API keys."""
from pathlib import Path
import secrets
from urllib.parse import quote
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'.env'
if not path.exists():
    path.write_text((ROOT/'.env.example').read_text())
values=dotenv_values(path)
password=values.get('POSTGRES_PASSWORD') or secrets.token_urlsafe(32)
port=values.get('POSTGRES_PORT') or '55432'
updates={'POSTGRES_PASSWORD':password,'POSTGRES_PORT':port,
         'DATABASE_URL':f'postgresql://finance_detective:{quote(password,safe="")}@127.0.0.1:{port}/finance_detective',
         'AI_AUTH_MODE':'local','AI_DAILY_BUDGET_USD':'5','AI_MONTHLY_BUDGET_USD':'30',
         'AI_USER_DAILY_BUDGET_USD':'1','AI_USER_DAILY_REQUESTS':'50','AI_REQUEST_BUDGET_USD':'0.15',
         'AI_CACHE_TTL_SECONDS':'86400','AI_MAX_CONCURRENT_REQUESTS':'4','AI_MAX_INPUT_TOKENS':'64000',
         'OPENAI_AGENT_MODEL':'gpt-4.1-mini','AGENT_MAX_STEPS':'6','AGENT_MAX_TOOL_CALLS':'8',
         'AGENT_TIMEOUT_SECONDS':'120','NEO4J_PASSWORD':secrets.token_urlsafe(32),
         'NEO4J_USERNAME':'neo4j','NEO4J_DATABASE':'neo4j','NEO4J_HTTP_PORT':'7474','NEO4J_BOLT_PORT':'7687',
         'NEO4J_URI':f"bolt://127.0.0.1:{values.get('NEO4J_BOLT_PORT') or '7687'}"}
missing={key:value for key,value in updates.items() if not values.get(key)}
if missing:
    with path.open('a') as out:
        out.write('\n# PostgreSQL and cost controls (added without replacing existing values)\n')
        for key,value in missing.items():out.write(f'{key}={value}\n')
path.chmod(0o600)
print('Local configuration ready; existing API keys preserved. No secrets displayed.')
