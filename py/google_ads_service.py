"""Google Ads API 客户端 — 拉取报告数据。

独立于主项目，通过 Flask API 路由调用。
"""

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

# v24 可用字段：https://developers.google.com/google-ads/api/fields/v24/overview
_GAQL_CAMPAIGN_REPORT = """
SELECT
  campaign.id,
  campaign.name,
  customer.id,
  customer.descriptive_name,
  metrics.cost_micros,
  metrics.impressions,
  metrics.clicks,
  metrics.ctr,
  metrics.conversions,
  metrics.cost_per_conversion
FROM campaign
WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
ORDER BY metrics.cost_micros DESC
"""


class GoogleAdsServiceError(Exception):
    """Google Ads 服务错误。"""
    pass


def _build_client(client_id: str, client_secret: str, refresh_token: str,
                  developer_token: str, login_customer_id: str) -> GoogleAdsClient:
    """构造 Google Ads 客户端。"""
    return GoogleAdsClient.load_from_dict({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "developer_token": developer_token,
        "login_customer_id": login_customer_id.replace("-", ""),
        "use_proto_plus": True,
    })


def list_accounts(client_id: str, client_secret: str, refresh_token: str,
                  developer_token: str, manager_id: str) -> list[str]:
    """列出经理账户下所有可访问的子账户 ID。"""
    client = _build_client(client_id, client_secret, refresh_token,
                           developer_token, manager_id)
    service = client.get_service("CustomerService")
    try:
        customers = service.list_accessible_customers()
    except GoogleAdsException as e:
        raise GoogleAdsServiceError(
            f"获取账户列表失败: {e.error.message if e.error else e}") from e
    return [c.split("/")[-1] for c in customers.resource_names]


def fetch_campaign_report(client_id: str, client_secret: str, refresh_token: str,
                          developer_token: str, manager_id: str,
                          account_id: str, start_date: str, end_date: str) -> list[dict]:
    """拉取广告系列级别报告。

    Args:
        account_id: 要查询的子账户 ID（如 "2083202792"）
        start_date: 开始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"

    Returns:
        [{campaign_id, campaign_name, customer_id, customer_name,
          cost, impressions, clicks, ctr, conversions, cpa}, ...]
    """
    client = _build_client(client_id, client_secret, refresh_token,
                           developer_token, manager_id)
    query = _GAQL_CAMPAIGN_REPORT.format(start_date=start_date, end_date=end_date)

    ga_service = client.get_service("GoogleAdsService")
    try:
        response = ga_service.search(customer_id=account_id.replace("-", ""), query=query)
    except GoogleAdsException as e:
        raise GoogleAdsServiceError(
            f"拉取报告失败: {e.error.message if e.error else e}") from e

    results = []
    for row in response:
        campaign = row.campaign
        customer = row.customer
        metrics = row.metrics
        results.append({
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "customer_id": str(customer.id),
            "customer_name": customer.descriptive_name,
            "cost": round(metrics.cost_micros / 1_000_000, 2) if metrics.cost_micros else 0.0,
            "impressions": int(metrics.impressions) if metrics.impressions else 0,
            "clicks": int(metrics.clicks) if metrics.clicks else 0,
            "ctr": round(metrics.ctr * 100, 2) if metrics.ctr else 0.0,
            "conversions": round(metrics.conversions, 2) if metrics.conversions else 0.0,
            "cpa": round(metrics.cost_per_conversion / 1_000_000, 2)
                   if metrics.cost_per_conversion else 0.0,
        })
    return results
