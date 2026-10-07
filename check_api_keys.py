"""Check configured credentials without printing secrets or contacting customers."""
import asyncio
import argparse
import json
import os
import aiohttp
from dotenv import dotenv_values


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', choices=['gemini'])
    parser.add_argument('--gemini-model')
    args = parser.parse_args()
    env = {**dotenv_values('.env'), **os.environ}
    if args.gemini_model:
        env['GEMINI_MODEL'] = args.gemini_model
    secrets = [v for k, v in env.items() if v and ('API_KEY' in k or k == 'BOT_TOKEN')]
    def clean(value):
        result = str(value)
        for secret in secrets:
            result = result.replace(secret, '[REDACTED]')
        return result[:2200]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=50)) as session:
        async def check(name, url, headers=None, body=None):
            try:
                async with session.request('POST' if body is not None else 'GET', url, headers=headers, json=body) as response:
                    data = await response.json(content_type=None)
                    result = {'service': name, 'http': response.status}
                    if response.status >= 400 or data.get('ok') is False:
                        result['error'] = data.get('error', data.get('description', data))
                    elif name == 'telegram':
                        result['username'] = data.get('result', {}).get('username')
                    else:
                        result['success'] = True
                        result['returned_model'] = data.get('model')
                        result['usage'] = data.get('usage', data.get('usageMetadata'))
                        if 'choices' in data:
                            result['has_reply'] = bool(data['choices'] and data['choices'][0].get('message', {}).get('content'))
                        if 'candidates' in data:
                            result['has_reply'] = bool(data['candidates'])
                        if name == 'openrouter-key':
                            result['limits'] = {k: v for k, v in data.get('data', {}).items() if k in {'limit', 'limit_remaining', 'is_free_tier', 'usage_daily', 'rate_limit'}}
                    print(clean(json.dumps(result, ensure_ascii=False)), flush=True)
            except Exception as error:
                print(json.dumps({'service': name, 'error_type': type(error).__name__, 'detail': clean(error)}, ensure_ascii=False), flush=True)
        jobs = []
        for name, base in [('openrouter', 'https://openrouter.ai/api/v1'), ('groq', 'https://api.groq.com/openai/v1'), ('deepseek', 'https://api.deepseek.com'), ('openai', 'https://api.openai.com/v1')]:
            if args.only:
                continue
            key, model = env.get(name.upper() + '_API_KEY'), env.get(name.upper() + '_MODEL')
            if key and model:
                jobs.append(check(name, base + '/chat/completions', {'Authorization': 'Bearer ' + key}, {'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK only.'}], 'max_tokens': 256}))
                if name == 'openrouter':
                    jobs.append(check('openrouter-key', base + '/key', {'Authorization': 'Bearer ' + key}))
            else:
                print(json.dumps({'service': name, 'configured': False}))
        key = env.get('GEMINI_API_KEY')
        if key:
            jobs.append(check('gemini', 'https://generativelanguage.googleapis.com/v1beta/models/' + env['GEMINI_MODEL'] + ':generateContent', {'x-goog-api-key': key}, {'contents': [{'parts': [{'text': 'Reply with OK only.'}]}], 'generationConfig': {'maxOutputTokens': 256}}))
        if env.get('BOT_TOKEN') and not args.only:
            jobs.append(check('telegram', 'https://api.telegram.org/bot' + env['BOT_TOKEN'] + '/getMe'))
        await asyncio.gather(*jobs)


if __name__ == '__main__':
    asyncio.run(main())
