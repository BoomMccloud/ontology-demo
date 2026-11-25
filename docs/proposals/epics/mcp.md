# MCP

## Outcome

An external agent, such as one used by a trading system, can retrieve structured ontology data through a read-only interface. The first release covers entity and theme lookups, relationships, and source citations.

## Benefits

Other systems can reuse the team's research without rebuilding its graph or parsing chat responses. Source citations let consumers trace a result back to its supporting evidence.

## Draft user journey

### Look up theme exposure from another agent

1. From their existing trading system, a portfolio manager asks its agent which companies in their watchlist are exposed to the data center rollout theme.
2. The external agent uses MCP to look up the theme and retrieve linked companies, their exposure relationships, and the available source citations.
3. The agent matches the results against the watchlist and shows the portfolio manager which exposures it found, with links to the source evidence.
4. The portfolio manager follows a citation to check the basis for a supplier's exposure before using the result in their research.
