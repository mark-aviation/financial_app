# services/event_bus.py — Lightweight pub/sub event system
#
# 🏛️ Architect: Replaces the blunt refresh_all_tabs() that re-ran
#   everything on every save. Now each tab subscribes only to the
#   events it actually cares about.
#
# Usage:
#   from services.event_bus import bus
#
#   # Subscribe (in tab setup):
#   bus.subscribe("expense.saved", self.reload_expenses)
#   bus.subscribe("expense.saved", self.update_charts)
#
#   # Publish (in save handler):
#   bus.publish("expense.saved")
#
# Events used in Expensis:
#   expense.saved    → wallet_tab, analytics_tab, manage_data_tab
#   expense.deleted  → wallet_tab, analytics_tab, manage_data_tab
#   income.saved     → wallet_tab, analytics_tab
#   income.deleted   → wallet_tab, analytics_tab
#   budget.saved     → wallet_tab
#   deadline.saved   → deadlines_tab
#   deadline.done    → deadlines_tab
#   category.saved   → add_expense_tab (refreshes dropdown)
#   filter.changed   → all data tabs

import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callable) -> None:
        """Register a callback for an event."""
        self._listeners[event].append(callback)
        logger.debug("Subscribed %s to '%s'", callback.__qualname__, event)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        """Remove a specific callback."""
        try:
            self._listeners[event].remove(callback)
        except ValueError:
            pass

    def publish(self, event: str, **kwargs) -> None:
        """
        Fire all callbacks registered for this event.
        Callbacks are called with any kwargs as context.
        Errors in individual callbacks are logged but don't stop others.
        """
        callbacks = self._listeners.get(event, [])
        logger.debug("Publishing '%s' to %d subscriber(s)", event, len(callbacks))
        for cb in callbacks:
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error("Error in event handler %s for '%s': %s", cb.__qualname__, event, e)

    def clear(self) -> None:
        """Clear all subscriptions (useful for testing or logout)."""
        self._listeners.clear()


# Global singleton — import this everywhere
bus = EventBus()
