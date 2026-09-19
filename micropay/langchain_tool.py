def make_intel_tool(agent, endpoint_url: str, price_per_query_wei: int):
    """Wrap an AutonomousDataAgent as a LangChain tool (lazy import)."""
    from langchain_core.tools import tool

    @tool
    def fetch_security_intel(network: str, address: str) -> str:
        """Buy live security intel (audit score, risk flags) for any contract/wallet, pay-per-query."""
        data = agent.query_node(endpoint_url,
                                {"type": "security_intel", "network": network, "address": address},
                                price_per_query_wei)
        return str(data)

    return fetch_security_intel
