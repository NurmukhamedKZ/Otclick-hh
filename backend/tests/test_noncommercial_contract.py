from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_payment_runtime_modules_and_pages_are_removed():
    removed = [
        "backend/app/api/billing.py",
        "backend/app/api/webhooks.py",
        "backend/app/services/billing.py",
        "backend/app/schemas/billing.py",
        "frontend/src/app/(app)/billing/page.tsx",
        "frontend/src/app/(app)/billing/success/page.tsx",
    ]
    assert all(not (ROOT / path).exists() for path in removed)


def test_runtime_config_has_no_commercial_provider_settings():
    config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    uv_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    for token in (
        "POLAR_",
        "BILLING_ENABLED",
        "FREE_TOTAL_APPLIES",
        "PAID_DAILY_APPLIES",
        "PLAN_CURRENCY",
    ):
        assert token not in config
        assert token not in env_example
    assert "polar-sdk" not in pyproject
    assert "polar-sdk" not in uv_lock
    assert "POLAR_" not in installer


def test_api_router_does_not_mount_payment_routes():
    router = (ROOT / "backend/app/api/router.py").read_text(encoding="utf-8")
    assert "billing.router" not in router
    assert "webhooks.router" not in router


def test_in_app_commercial_prompts_are_removed():
    files = [
        "frontend/src/components/otclick/sidebar.tsx",
        "frontend/src/app/(app)/account/page.tsx",
        "frontend/src/app/(app)/dashboard/limit-ring.tsx",
        "frontend/src/components/otclick/worker-bar.tsx",
    ]
    text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in files)
    for token in (
        'href="/billing"',
        "/api/billing/",
        "Подписка Pro",
        "открыть тарифы",
        "дальше нужен тариф",
        "₸",
    ):
        assert token not in text


def test_real_submit_safety_gate_stays_off_by_default():
    config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ALLOW_REAL_APPLY: bool = False" in config
    assert "ALLOW_REAL_APPLY=false" in env_example
