from reliable_agents.models import ActionRequest, WorkerOutput


class WriteValueTool:
    version = "write-value@0.1.0"

    def execute(self, request: ActionRequest) -> WorkerOutput:
        value = int(request.arguments["value"])

        return WorkerOutput(value=value, summary=f"Stored value {value}")
