import uuid

_orders = {}


def _mock_packages():
    return [
        {"id": "pkg_standard", "name": "Standard Package", "price": 120000},
        {"id": "pkg_premium", "name": "Premium Package", "price": 175000},
    ]


def _mock_addons():
    return [
        {"id": "addon_airport", "name": "Airport Pickup", "price": 2500},
        {"id": "addon_insurance", "name": "Travel Insurance", "price": 1800},
    ]


def _mock_participants():
    return [
        {"id": "p1", "name": "Alex Chen"},
        {"id": "p2", "name": "Jamie Lee"},
    ]


def create_order():
    order_id = str(uuid.uuid4())
    _orders[order_id] = {
        "order_id": order_id,
        "trip_id": "mock_trip_001",
        "package_id": "pkg_standard",
        "package_qty": 1,
        "addons": {},
        "participants": 1,
        "packages": _mock_packages(),
        "addons_catalog": _mock_addons(),
        "participants_list": _mock_participants(),
        "base_amount": 0,
        "summary": {},
        "payment_intent_id": None,
        "status": "PENDING",
        "last_quote": {},
    }
    _recalculate(order_id)
    return order_id


def get_order(order_id):
    return _orders.get(order_id)


def update_order_selection(order_id, selection):
    order = _orders.get(order_id)
    if not order:
        return None

    order["package_id"] = selection.get("package_id") or order["package_id"]
    order["package_qty"] = max(1, int(selection.get("package_qty", order["package_qty"])))
    order["participants"] = max(1, int(selection.get("participants", order["participants"])))

    addon_ids = selection.get("addon_ids", [])
    addon_qty_map = selection.get("addon_qty_map", {})
    addons = {}
    for addon_id in addon_ids:
        qty = addon_qty_map.get(addon_id, "1")
        try:
            qty_value = int(qty)
        except (TypeError, ValueError):
            qty_value = 0
        if addon_id and qty_value > 0:
            addons[addon_id] = qty_value
    order["addons"] = addons

    _recalculate(order_id)
    return order


def set_order_payment_intent(order_id, payment_intent_id):
    order = _orders.get(order_id)
    if order:
        order["payment_intent_id"] = payment_intent_id


def record_quote(order_id, payment_method_id, funding, brand, fee, tax_amount, final_amount):
    order = _orders.get(order_id)
    if not order:
        return
    order["last_quote"] = {
        "payment_method_id": payment_method_id,
        "funding": funding,
        "brand": brand,
        "fee": fee,
        "tax_amount": tax_amount,
        "final_amount": final_amount,
    }


def set_order_status(order_id, status):
    order = _orders.get(order_id)
    if order:
        order["status"] = status


def get_order_status(order_id):
    order = _orders.get(order_id)
    if not order:
        return "UNKNOWN"
    return order.get("status", "UNKNOWN")


def _recalculate(order_id):
    order = _orders.get(order_id)
    if not order:
        return

    packages = {p["id"]: p for p in order["packages"]}
    addons = {a["id"]: a for a in order["addons_catalog"]}

    package = packages.get(order["package_id"])
    package_cost = 0
    if package:
        package_cost = package["price"] * order["package_qty"]

    addons_cost = 0
    addon_items = []
    for addon_id, qty in order["addons"].items():
        addon = addons.get(addon_id)
        if addon:
            addons_cost += addon["price"] * qty
            addon_items.append(
                {
                    "id": addon_id,
                    "name": addon["name"],
                    "price": addon["price"],
                    "qty": qty,
                }
            )

    order["base_amount"] = package_cost + addons_cost
    order["summary"] = {
        "package": {
            "id": order["package_id"],
            "name": package["name"] if package else "Unknown",
            "price": package["price"] if package else 0,
            "qty": order["package_qty"],
            "total": package_cost,
        },
        "addons": addon_items,
        "participants": order["participants"],
    }
