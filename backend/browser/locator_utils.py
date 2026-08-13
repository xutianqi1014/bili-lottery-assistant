from typing import Any


async def stable_class_state(page: Any, selector: str, active_class: str) -> str:
    """Read a class-based state twice so transient DOM updates become unknown."""
    first = await page.locator(selector).first.get_attribute("class")
    await page.wait_for_timeout(400)
    second = await page.locator(selector).first.get_attribute("class")
    if first is None or second is None or first != second:
        return "unknown"
    return "active" if active_class in second.split() else "inactive"
