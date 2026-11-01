"""Catch truncated JS/Python that pytest HTTP tests cannot see."""
from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
JS_FILES = [
    APP_DIR / "static" / "js" / "booking.js",
    APP_DIR / "static" / "js" / "booking-modal.js",
]
PY_FILES = [
    APP_DIR / "routes.py",
    APP_DIR / "payments.py",
    APP_DIR / "booking_validation.py",
    APP_DIR / "discounting.py",
]
LEFTOVER_NEEDLES = (
    "await initEmbeddedPaymentSession();\n        if (!container) {",
    "await reinitPaymentAfterDiscountChange();\n     * 处理提交",
    "Your discount covers the amount due at booking. Click <strong>Confirm Booking</strong>",
    "var existing = mergedPackages.find(function(m) { return m.package_id === id; });\n        if (couponIsActive())",
)


def test_booking_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to syntax-check booking JS")
    for path in JS_FILES:
        assert path.is_file(), path
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr or result.stdout}"


def test_coupon_python_modules_parse():
    for path in PY_FILES:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))


def test_booking_js_has_no_truncation_leftovers():
    js = (APP_DIR / "static" / "js" / "booking.js").read_text(encoding="utf-8")
    for needle in LEFTOVER_NEEDLES:
        assert needle not in js, f"leftover fragment still in booking.js: {needle!r}"
    assert js.count("function savePackagesData") == 1
    assert js.count("async function applyDiscountCode") == 1
    assert js.count("async function removeDiscountCode") == 1
    assert js.count("function updateOrderSummary") == 1
    # coupon lock must not sit inside the package-merge forEach
    merge_idx = js.find("var mergedPackages = [];")
    assert merge_idx > 0
    merge_chunk = js[merge_idx: merge_idx + 450]
    assert "couponIsActive()" not in merge_chunk
    assert "lockInstallmentRadios()" not in merge_chunk
