from atlassian import Jira

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("jira_client")


class JiraClient:
    def __init__(self):
        self.client = Jira(
            url=Config.JIRA_URL,
            username=Config.JIRA_EMAIL,
            password=Config.JIRA_API_TOKEN,
            cloud=True,
        )

    def get_ticket(self, ticket_key: str) -> dict:
        """Fetch a Jira ticket and return structured details."""
        logger.info(f"Fetching Jira ticket: {ticket_key}")
        issue = self.client.issue(ticket_key)

        fields = issue.get("fields", {})

        # Extract relevant fields
        ticket = {
            "key": ticket_key,
            "summary": fields.get("summary", ""),
            "description": self._extract_description(fields.get("description")),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "labels": fields.get("labels", []),
            "acceptance_criteria": self._extract_acceptance_criteria(fields),
        }

        logger.info(f"Fetched ticket: {ticket_key} - {ticket['summary']}")
        return ticket

    def _extract_description(self, description) -> str:
        """Extract text from Jira's Atlassian Document Format or plain text."""
        if description is None:
            return ""
        if isinstance(description, str):
            return description

        # Handle ADF (Atlassian Document Format)
        if isinstance(description, dict):
            return self._adf_to_text(description)

        return str(description)

    def _adf_to_text(self, node: dict) -> str:
        """Recursively convert ADF nodes to plain text."""
        if not isinstance(node, dict):
            return str(node) if node else ""

        node_type = node.get("type", "")
        text = ""

        if node_type == "text":
            text = node.get("text", "")
        elif node_type == "hardBreak":
            text = "\n"

        # Process children
        for child in node.get("content", []):
            text += self._adf_to_text(child)

        # Add formatting based on node type
        if node_type == "paragraph":
            text += "\n"
        elif node_type == "heading":
            level = node.get("attrs", {}).get("level", 1)
            text = "#" * level + " " + text
        elif node_type == "bulletList":
            pass  # children handle it
        elif node_type == "listItem":
            text = "• " + text
        elif node_type == "codeBlock":
            text = "```\n" + text + "```\n"

        return text

    def add_comment(self, ticket_key: str, comment_text: str) -> None:
        """Post a plain-text comment on a Jira ticket."""
        logger.info(f"Adding comment to {ticket_key}")
        self.client.issue_add_comment(ticket_key, comment_text)

    def _extract_acceptance_criteria(self, fields: dict) -> str:
        """Try to extract acceptance criteria from common custom fields."""
        # Common field names for acceptance criteria
        for field_key, value in fields.items():
            if field_key.startswith("customfield_") and value:
                if isinstance(value, str) and (
                    "accept" in value.lower() or "criteria" in value.lower()
                ):
                    return value
                if isinstance(value, dict):
                    text = self._adf_to_text(value)
                    if text.strip():
                        return text
        return ""
