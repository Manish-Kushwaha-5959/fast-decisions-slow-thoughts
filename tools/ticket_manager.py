class TicketManager:
    """Manage simulated support tickets in memory."""

    VALID_PRIORITIES = {"low", "medium", "high"}

    def __init__(self):
        self._tickets = []

    def create_ticket(
        self,
        issue: str,
        priority: str
    ) -> dict:
        """Create a simulated support ticket."""

        if not isinstance(issue, str) or not issue.strip():
            raise ValueError("Issue must be a non-empty string.")

        if not isinstance(priority, str):
            raise ValueError("Priority must be a string.")

        normalized_priority = priority.strip().lower()

        if normalized_priority not in self.VALID_PRIORITIES:
            raise ValueError(
                "Priority must be low, medium, or high."
            )

        ticket_number = len(self._tickets) + 1
        ticket_id = f"TICKET-{ticket_number:04d}"

        ticket = {
            "ticket_id": ticket_id,
            "issue": issue.strip(),
            "priority": normalized_priority,
            "status": "created",
            "simulation": True
        }

        self._tickets.append(ticket)

        # Return a copy so callers cannot modify stored ticket data.
        return ticket.copy()

    def get_tickets(self) -> list[dict]:
        """Return all tickets created in this process."""
        return [ticket.copy() for ticket in self._tickets]

    def reset(self):
        """Clear simulated tickets before a new experiment run."""
        self._tickets.clear()


# One shared in-memory manager for the running application.
ticket_manager = TicketManager()


def create_support_ticket(
    issue: str,
    priority: str
) -> dict:
    """Tool interface used by the agent."""
    return ticket_manager.create_ticket(issue, priority)

def reset_simulated_tickets():
    ticket_manager.reset()