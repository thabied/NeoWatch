"""Agent package.

Houses the orchestrator and the specialist agents (fetch, RAG, calc, image,
synthesis). Every agent inherits ``BaseAgent`` and implements
``async def run(self, context) -> AgentResult``, giving them a uniform contract.
"""
