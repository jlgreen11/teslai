"""Fleet API base URLs by region (developer.tesla.com, Base URLs by Region).

All regions share the auth host fleet-auth.prd.vn.cloud.tesla.com. Calling the
wrong regional host still authenticates but vehicle requests fail (404 or 412).
"""

from teslai.errors import TeslaiError

FLEET_BASE_URLS = {
    "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",  # North America, Asia-Pacific ex. China
    "eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",  # Europe, Middle East, Africa
    "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn",   # China
}


def base_url(region: str) -> str:
    try:
        return FLEET_BASE_URLS[region.lower()]
    except KeyError:
        raise TeslaiError("TSL-REGION-WRONG", f"unknown region {region!r}; use na, eu or cn") from None
