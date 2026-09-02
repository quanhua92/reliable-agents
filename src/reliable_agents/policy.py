from reliable_agents.models import ActionRequest, Decision, Goal, PolicyDecision


class StaticPolicyEngine:
    version = "static-policy@0.1.0"

    def admit(self, goal: Goal, authoritative_tier: int) -> PolicyDecision:
        if goal.task_class != "code_change":
            return PolicyDecision(Decision.DENY, "unsupported task class")

        if authoritative_tier < 1:
            return PolicyDecision(Decision.DENY, "tier below admission minimum")

        return PolicyDecision(Decision.ALLOW, "admission allowed")

    def authorize(
        self, request: ActionRequest, authoritative_tier: int
    ) -> PolicyDecision:
        if request.tool_name != "write_value":
            return PolicyDecision(Decision.DENY, "tool denied by default")

        if authoritative_tier < 2:
            return PolicyDecision(Decision.REQUIRE_APPROVAL, "write requires tier 2")

        return PolicyDecision(Decision.ALLOW, "action allowed")
