from collections.abc import Mapping

import httpx


def request_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Referer": referer,
        "Origin": "https://space.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }


async def get_json(
    url: str,
    params: Mapping[str, str | int | float | bool | None],
    timeout: float,
    referer: str,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers=request_headers(referer))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("BILIBILI_RESPONSE_NOT_OBJECT")
    return payload
