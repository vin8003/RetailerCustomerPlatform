import os
import json
import time
import hashlib
import logging
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

META_GRAPH_API_VERSION = "v19.0"


def _hash_value(val: str) -> str:
    """Normalize and return SHA256 hash as required by Meta Conversions API."""
    if not val:
        return ""
    clean = val.strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _normalize_phone(phone: str) -> str:
    """Normalize Indian phone numbers to E.164 digits without plus."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def _dispatch_meta_event(payload: dict, dataset_id: str, access_token: str):
    """Worker function executed in background thread."""
    try:
        url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{dataset_id}/events?access_token={access_token}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            logger.info(f"[Meta CAPI] Purchase event delivered successfully: {resp_body}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else str(e)
        logger.warning(f"[Meta CAPI] HTTP Error sending purchase event ({e.code}): {err_body}")
    except Exception as e:
        logger.warning(f"[Meta CAPI] Exception sending purchase event: {str(e)}")


def track_meta_purchase(order, request=None, test_event_code=None):
    """
    Sends a Purchase event to Meta Conversions API asynchronously.
    Guaranteed not to block or crash order processing.
    """
    dataset_id = os.getenv("META_DATASET_ID")
    access_token = os.getenv("META_ACCESS_TOKEN")

    if not dataset_id or not access_token:
        logger.debug("[Meta CAPI] META_DATASET_ID or META_ACCESS_TOKEN not set, skipping.")
        return

    try:
        customer = getattr(order, "customer", None)
        raw_phone = ""
        raw_email = ""
        first_name = ""
        last_name = ""

        if customer:
            raw_phone = getattr(customer, "phone_number", "") or customer.username
            raw_email = getattr(customer, "email", "")
            first_name = getattr(customer, "first_name", "")
            last_name = getattr(customer, "last_name", "")

        # Fallback to delivery address phone if customer phone is empty
        if not raw_phone and hasattr(order, "delivery_phone") and order.delivery_phone:
            raw_phone = order.delivery_phone

        user_data = {}
        norm_phone = _normalize_phone(raw_phone)
        if norm_phone:
            user_data["ph"] = [_hash_value(norm_phone)]

        if raw_email:
            user_data["em"] = [_hash_value(raw_email)]

        if first_name:
            user_data["fn"] = [_hash_value(first_name)]

        if last_name:
            user_data["ln"] = [_hash_value(last_name)]

        # Extract client IP and user agent if request is provided
        if request:
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip = x_forwarded_for.split(",")[0].strip()
            else:
                ip = request.META.get("REMOTE_ADDR")
            if ip:
                user_data["client_ip_address"] = ip

            user_agent = request.META.get("HTTP_USER_AGENT")
            if user_agent:
                user_data["client_user_agent"] = user_agent

        # Order amount
        value = 0.0
        for attr in ["final_amount", "total_amount", "subtotal"]:
            if hasattr(order, attr) and getattr(order, attr) is not None:
                try:
                    value = float(getattr(order, attr))
                    break
                except (ValueError, TypeError):
                    continue

        order_id = str(getattr(order, "order_number", None) or getattr(order, "id", ""))

        custom_data = {
            "currency": "INR",
            "value": round(value, 2),
            "order_id": order_id,
            "content_type": "product",
        }

        # Item contents
        try:
            contents = []
            if hasattr(order, "items"):
                for item in order.items.all():
                    item_id = str(getattr(item, "product_id", "") or getattr(item, "id", ""))
                    qty = getattr(item, "quantity", 1)
                    price = float(getattr(item, "unit_price", 0.0) or getattr(item, "price", 0.0) or 0.0)
                    contents.append({
                        "id": item_id,
                        "quantity": int(qty),
                        "item_price": round(price, 2)
                    })
            if contents:
                custom_data["contents"] = contents
        except Exception:
            pass

        event_data = {
            "event_name": "Purchase",
            "event_time": int(time.time()),
            "action_source": "website",
            "event_source_url": "https://customer.ordereasy.win/checkout/success",
            "user_data": user_data,
            "custom_data": custom_data,
        }

        payload = {"data": [event_data]}

        # If test_event_code is passed or configured in environment
        active_test_code = test_event_code or os.getenv("META_TEST_EVENT_CODE")
        if active_test_code:
            payload["test_event_code"] = active_test_code

        # Fire in background thread so caller returns immediately
        thread = threading.Thread(
            target=_dispatch_meta_event,
            args=(payload, dataset_id, access_token),
            daemon=True
        )
        thread.start()

    except Exception as e:
        logger.warning(f"[Meta CAPI] Error preparing purchase event: {str(e)}")
