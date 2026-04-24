"""
Porkbun DNS API client.
Docs: https://porkbun.com/api/json/v3/documentation
"""
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

PORKBUN_BASE = "https://api.porkbun.com/api/json/v3"


class PorkbunError(Exception):
    pass


async def _post(endpoint: str, api_key: str, secret_key: str, extra: dict = None) -> dict:
    url = f"{PORKBUN_BASE}/{endpoint}"
    payload = {"apikey": api_key, "secretapikey": secret_key}
    if extra:
        payload.update(extra)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
    data = resp.json()
    if data.get("status") != "SUCCESS":
        raise PorkbunError(data.get("message", "Unknown Porkbun error"))
    return data


async def ping(api_key: str, secret_key: str) -> str:
    """
    Validate API credentials. Returns IP on success, raises PorkbunError on failure.
    """
    data = await _post("ping", api_key, secret_key)
    return data.get("yourIp", "")


async def get_dns_records(domain: str, api_key: str, secret_key: str) -> list:
    """Retrieve all DNS records for a domain."""
    try:
        data = await _post(f"dns/retrieve/{domain}", api_key, secret_key)
        return data.get("records", [])
    except PorkbunError:
        return []


async def create_a_record(
    domain: str, subdomain: str, ip: str, api_key: str, secret_key: str, ttl: int = 600
) -> str:
    """
    Create an A record. Returns the DNS record ID.
    subdomain: just the prefix, e.g. "admin" (not "admin.milkyims.com")
    """
    data = await _post(
        f"dns/create/{domain}",
        api_key,
        secret_key,
        {
            "name": subdomain,
            "type": "A",
            "content": ip,
            "ttl": str(ttl),
        },
    )
    return str(data.get("id", ""))


async def delete_dns_record(domain: str, record_id: str, api_key: str, secret_key: str) -> None:
    """Delete a DNS record by ID."""
    await _post(f"dns/delete/{domain}/{record_id}", api_key, secret_key)


async def check_dns_propagation(full_domain: str, expected_ip: str) -> bool:
    """
    Check if the A record has propagated by querying Cloudflare's DNS over HTTPS.
    """
    url = f"https://cloudflare-dns.com/dns-query?name={full_domain}&type=A"
    headers = {"Accept": "application/dns-json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        data = resp.json()
        answers = data.get("Answer", [])
        for ans in answers:
            if ans.get("type") == 1 and ans.get("data") == expected_ip:
                return True
    except Exception as e:
        logger.warning(f"DNS propagation check failed: {e}")
    return False
